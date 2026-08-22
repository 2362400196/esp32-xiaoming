"""服务端权限裁决器：对子进程 SDK 请求做边界裁决并执行。

子进程没有 channel / DB / 真实 LTM 服务，所有 SDK 能力都通过 RPC 回到这里。
本模块是沙箱的真正边界：
    - 权限检查：manifest.permissions 声明（比 AST 静态审计更强——此处是运行时强制）
    - URL 校验：http/https + 阻止 SSRF（内网/回环/元数据地址）
    - 环境变量白名单：只能读插件自身命名空间或 PLUGIN_ 前缀变量
    - 设备作用域：日记/设备配置等数据操作强制限定在本次调用绑定的设备
    - 与进程内插件共用同一套 _plugin_helpers，行为完全一致
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 需要权限的 op → 权限名
_OP_PERMS: dict[str, str] = {
    "device_send_instruct": "device",
    "device_send_command": "device",
    "device_send_command_ack": "device",
    "device_request_result": "device",
    "http_request": "network",
    "http_get_json": "network",
    "ltm_store": "ltm",
    "ltm_recall": "ltm",
    "ltm_list_all": "ltm",
    "ltm_update": "ltm",
    "ltm_forget": "ltm",
    "diary_get_recent": "db",
    "diary_upsert_entry": "db",
    "diary_search": "db",
    "device_config_get": "db",
    "device_config_update_partial": "db",
    "env_read": "env_read",
    # 新增能力
    "llm_chat": "llm",
    "llm_generate": "llm",
    "tts_synthesize": "tts",
    "device_is_online": "device",
    "device_get_info": "device",
    "plugin_data_read": "file_read",
    "plugin_data_write": "file_write",
    "plugin_data_list": "file_read",
    "plugin_data_delete": "file_write",
    "kv_get": "kv",
    "kv_set": "kv",
    "kv_delete": "kv",
    "kv_list": "kv",
    "get_user_profile_summary": "db",
}

# 无需显式权限的只读 op（设备 key 解析 / 技能目录 / 插件配置）
_NO_PERM_OPS = frozenset({
    "device_key", "resolve_device_key", "plugin_config", "skill_catalog",
    "plugin_log",
})

# 内置插件默认权限（内置插件仍可放宽，但已声明为准）
BUILTIN_DEFAULT_PERMS = frozenset({
    "network", "device", "ltm", "db", "file_read", "file_write",
    "subprocess", "exec", "env_read", "llm", "tts", "kv",
})


@dataclass
class CallContext:
    """一次工具调用的运行上下文（主进程持有真实对象）。"""

    call_id: int
    tool_manager: Any = None
    channel: Any = None
    ctx: Any = None
    fsm: Any = None
    device_key: str = ""
    plugin_config: dict = field(default_factory=dict)
    user_config: Any = None


# ════════════════════════════════════════════════════════════
# SSRF 防护
# ════════════════════════════════════════════════════════════

_PRIVATE_IP_BLOCKS = (
    ("10.0.0.0", 8),
    ("127.0.0.0", 8),      # 回环
    ("169.254.0.0", 16),   # 链路本地（含云元数据 169.254.169.254）
    ("172.16.0.0", 12),
    ("192.168.0.0", 16),
    ("0.0.0.0", 8),
    ("100.64.0.0", 10),    # CGNAT
)


def _is_private_ip(ip: str) -> bool:
    import ipaddress

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_private or addr.is_multicast or addr.is_reserved:
        return True
    # 显式块（补充标准库覆盖不到的情况）
    for base, prefix in _PRIVATE_IP_BLOCKS:
        try:
            if addr in ipaddress.ip_network(f"{base}/{prefix}"):
                return True
        except ValueError:
            continue
    return False


async def _hostname_to_ips(hostname: str) -> list[str]:
    """异步 DNS 解析，防止阻塞事件循环。"""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, family=0, type=0), timeout=10.0
        )
        return sorted({info[4][0] for info in infos})
    except (asyncio.TimeoutError, OSError, ValueError):
        return []


async def validate_url(url: str, allowlist: set[str]) -> tuple[str | None, str | None]:
    """校验 HTTP URL 安全（防 SSRF）。

    异步版本：DNS 解析使用 asyncio event loop 的 getaddrinfo，
    避免阻塞事件循环。

    Returns:
        (error, resolved_ip): error 为 None 表示通过；resolved_ip 为校验时解析的 IP，
        传给 HTTP 客户端 pin 连接以防止 DNS 重绑定。
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"仅允许 http/https 协议: {url}", None
    host = (parsed.hostname or "").lower()
    if not host:
        return f"URL 缺少主机名: {url}", None
    if host in allowlist or host.endswith(tuple("." + h for h in allowlist if h)):
        return None, None
    ips = await _hostname_to_ips(host)
    if not ips:
        return f"无法解析主机名: {host}", None
    for ip in ips:
        if _is_private_ip(ip):
            return f"URL 解析到内网/保留地址，已阻止（SSRF 防护）: {url} -> {ip}", None
    return None, ips[0]


# ════════════════════════════════════════════════════════════
# 环境变量白名单
# ════════════════════════════════════════════════════════════


def env_var_allowed(plugin_id: str, env_var: str) -> bool:
    """环境变量读取白名单：仅允许插件命名空间（<plugin_id>_）或 PLUGIN_ 前缀。

    与进程内插件共用同一规则（见 plugin_security.env_var_allowed）。
    """
    from src.infrastructure.plugin_security import env_var_allowed as _check
    return _check(plugin_id, env_var)


# ════════════════════════════════════════════════════════════
# 裁决器
# ════════════════════════════════════════════════════════════


class PermissionDenied(Exception):
    """权限被拒绝（统一映射为 PermissionError 语义）。"""


class Adjudicator:
    """针对单个插件的 SDK 请求裁决器。"""

    def __init__(self, plugin_id: str, permissions: list[str],
                 url_allowlist: list[str] | None = None) -> None:
        self.plugin_id = plugin_id
        self.permissions = frozenset(permissions or [])
        self.url_allowlist = set(url_allowlist or _global_url_allowlist())
        self._permission_setup_done = False

    # ── 权限上下文 ──────────────────────────────────────────

    def _enter_perm_ctx(self):
        """进入插件权限上下文（复用进程内 require_permission 检查）。"""
        from src.infrastructure.plugin_security import set_plugin_context
        token = set_plugin_context(self.plugin_id, list(self.permissions))
        return token

    @staticmethod
    def _exit_perm_ctx(token) -> None:
        from src.infrastructure.plugin_security import reset_plugin_context
        reset_plugin_context(token)

    def _check(self, op: str) -> None:
        perm = _OP_PERMS.get(op)
        if perm and perm not in self.permissions:
            raise PermissionDenied(
                f"插件「{self.plugin_id}」未声明 {perm} 权限，SDK 操作 {op} 已被阻止"
            )
        if perm is None and op not in _NO_PERM_OPS:
            raise PermissionDenied(f"未知的 SDK 操作: {op}")

    # ── 主入口 ──────────────────────────────────────────────

    async def handle(self, op: str, params: dict, ctx: CallContext) -> Any:
        self._check(op)
        token = self._enter_perm_ctx()
        try:
            handler = getattr(self, f"_op_{op}", None)
            if handler is None:
                raise PermissionDenied(f"未知的 SDK 操作: {op}")
            return await handler(params, ctx)
        finally:
            self._exit_perm_ctx(token)

    # ── 设备标识 ────────────────────────────────────────────

    async def _op_device_key(self, params, ctx) -> str:
        return ctx.device_key or ""

    async def _op_resolve_device_key(self, params, ctx) -> str:
        device_key = params.get("device_key") or ""
        if device_key:
            return device_key
        return ctx.device_key or ""

    # ── 设备指令 ────────────────────────────────────────────

    async def _op_device_send_instruct(self, params, ctx) -> None:
        from src.use_cases._plugin_helpers import send_instruct

        if ctx.channel is None:
            raise RuntimeError("设备未连接")
        await send_instruct(ctx.channel, params.get("command_id", ""), params.get("data", ""))

    async def _op_device_send_command(self, params, ctx) -> str | None:
        from src.use_cases._plugin_helpers import send_device_command

        if ctx.tool_manager is None:
            return "设备未连接"
        return await send_device_command(
            ctx.tool_manager, params.get("command_id", ""), params.get("data", "")
        )

    async def _op_device_send_command_ack(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import send_device_command_ack

        if ctx.tool_manager is None:
            return [None, "offline", "设备未连接"]
        result, status, detail = await send_device_command_ack(
            ctx.tool_manager, params.get("command_id", ""),
            params.get("data", ""), float(params.get("timeout", 8.0)),
        )
        return [result, status, detail]

    async def _op_device_request_result(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import request_device_result

        if ctx.tool_manager is None:
            return [None, "offline", "设备未连接"]
        result, status, detail = await request_device_result(
            ctx.tool_manager,
            params.get("command_id", ""),
            params.get("future_attr", ""),
            float(params.get("timeout", 8.0)),
            params.get("data", ""),
            params.get("if_busy"),
        )
        return [result, status, detail]

    # ── HTTP ────────────────────────────────────────────────

    async def _op_http_request(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import http_request

        import time as _time
        _t0 = _time.time()

        method = str(params.get("method", "GET")).upper()
        url = str(params.get("url", ""))
        err, pin_ip = await validate_url(url, self.url_allowlist)
        if err:
            _t1 = _time.time()
            logger.warning(f"[插件沙箱] 插件 {self.plugin_id} 的 HTTP 请求被拦截（{_t1-_t0:.2f}s）: {err}")
            return [None, None, err]
        _t1 = _time.time()
        resp, http_err = await http_request(
            method, url,
            params=params.get("params"),
            headers=params.get("headers"),
            content=params.get("content"),
            timeout=float(params.get("timeout", 10.0)),
            pin_ip=pin_ip,
        )
        _t2 = _time.time()
        if http_err is not None:
            logger.warning(f"[插件沙箱] 插件 {self.plugin_id} HTTP 请求失败（{_t2-_t1:.2f}s）: {http_err}")
            return [None, None, str(http_err)]
        logger.info(f"[插件沙箱] 插件 {self.plugin_id} HTTP 请求成功（DNS={_t1-_t0:.2f}s, 请求={_t2-_t1:.2f}s）")
        return [resp.status_code, resp.text, None]

    async def _op_http_get_json(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import http_get_json

        url = str(params.get("url", ""))
        err, pin_ip = await validate_url(url, self.url_allowlist)
        if err:
            logger.warning(f"[插件沙箱] 插件 {self.plugin_id} 的 HTTP 请求被拦截: {err}")
            return [None, err]
        data, http_err = await http_get_json(
            url,
            params=params.get("params"),
            headers=params.get("headers"),
            timeout=float(params.get("timeout", 8.0)),
            pin_ip=pin_ip,
        )
        if http_err is not None:
            return [None, str(http_err)]
        return [data, None]

    # ── 插件配置 / 环境变量 ─────────────────────────────────

    async def _op_plugin_config(self, params, ctx) -> str:
        from src.use_cases._plugin_helpers import get_plugin_config_or_env

        plugin = params.get("plugin") or self.plugin_id
        key = params.get("key") or ""
        env_var = params.get("env_var") or ""
        default = params.get("default") or ""

        # 环境变量仅允许插件命名空间 / PLUGIN_ 前缀
        if env_var and not env_var_allowed(self.plugin_id, env_var):
            logger.warning(f"[插件沙箱] 插件 {self.plugin_id} 尝试读取非白名单环境变量 {env_var}，已拒绝")
            return default

        if ctx.tool_manager is not None and hasattr(ctx.tool_manager, "get_plugin_config"):
            cfg = ctx.tool_manager.get_plugin_config(plugin, key, "")
            if cfg:
                return cfg
        if env_var:
            return os.environ.get(env_var, default)
        return default

    async def _op_env_read(self, params, ctx) -> str:
        env_var = str(params.get("env_var", ""))
        if not env_var_allowed(self.plugin_id, env_var):
            raise PermissionDenied(
                f"插件「{self.plugin_id}」尝试读取非白名单环境变量 {env_var}"
            )
        return os.environ.get(env_var, "")

    # ── LTM ─────────────────────────────────────────────────

    async def _op_ltm_store(self, params, ctx) -> list:
        from src.domain.entities import MemoryItem
        from src.use_cases._plugin_helpers import get_ltm_service

        self._check_device_scope(params.get("item", {}).get("device_id", ""), ctx, "ltm")
        service = get_ltm_service(ctx.tool_manager)
        item = MemoryItem.from_dict(params["item"])
        memory_id, changed = await service.store(item)
        return [memory_id, changed]

    async def _op_ltm_recall(self, params, ctx) -> list:
        from src.domain.value_objects import MemoryQuery
        from src.use_cases._plugin_helpers import get_ltm_service

        query = params.get("query") or {}
        self._check_device_scope(query.get("device_id", ""), ctx, "ltm")
        service = get_ltm_service(ctx.tool_manager)
        mq = MemoryQuery(
            device_id=query.get("device_id") or ctx.device_key or "",
            summary_labels=tuple(query.get("summary_labels") or ()),
            keyword=query.get("keyword", ""),
            limit=int(query.get("limit", 8)),
        )
        items = await service.recall(mq)
        return [getattr(i, "to_dict", lambda: vars(i))() for i in items]

    async def _op_ltm_list_all(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import get_ltm_service

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "ltm")
        service = get_ltm_service(ctx.tool_manager)
        items = await service.list_all(device_id)
        return [getattr(i, "to_dict", lambda: vars(i))() for i in items]

    async def _op_ltm_update(self, params, ctx) -> bool:
        from src.use_cases._plugin_helpers import get_ltm_service

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "ltm")
        service = get_ltm_service(ctx.tool_manager)
        return bool(await service.update(params.get("memory_id", ""), params.get("patch") or {}, device_id))

    async def _op_ltm_forget(self, params, ctx) -> Any:
        from src.use_cases._plugin_helpers import get_ltm_service

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "ltm")
        service = get_ltm_service(ctx.tool_manager)
        item = await service.forget(params.get("memory_id", ""), device_id)
        return getattr(item, "to_dict", lambda: vars(item))() if item else None

    # ── 日记 ────────────────────────────────────────────────

    async def _op_diary_get_recent(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import get_diary_repository

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "diary")
        repo = get_diary_repository()
        return await repo.get_recent(device_id, limit=int(params.get("limit", 7)))

    async def _op_diary_upsert_entry(self, params, ctx) -> None:
        from src.use_cases._plugin_helpers import get_diary_repository

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "diary")
        repo = get_diary_repository()
        await repo.upsert_entry(
            device_id, params.get("date", ""), params.get("content", ""),
            append=bool(params.get("append", False)),
        )

    async def _op_diary_search(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import get_diary_repository

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "diary")
        repo = get_diary_repository()
        return await repo.search(device_id, params.get("keyword", ""))

    # ── 设备配置 ────────────────────────────────────────────

    async def _op_device_config_get(self, params, ctx) -> Any:
        from src.use_cases._plugin_helpers import get_device_repository

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "device_config")
        repo = get_device_repository()
        return await repo.get_device_config(device_id)

    async def _op_device_config_update_partial(self, params, ctx) -> Any:
        from src.use_cases._plugin_helpers import get_device_repository

        device_id = params.get("device_id") or ctx.device_key or ""
        self._check_device_scope(device_id, ctx, "device_config")
        repo = get_device_repository()
        return await repo.update_device_partial(device_id, params.get("partial") or {})

    # ── 技能目录 ────────────────────────────────────────────

    async def _op_skill_catalog(self, params, ctx) -> str:
        from src.use_cases._plugin_helpers import skill_catalog_text

        return skill_catalog_text(ctx.tool_manager)

    # ── 插件日志 ────────────────────────────────────────────

    async def _op_plugin_log(self, params, ctx) -> None:
        from src.infrastructure.plugin_log_store import add_log
        level = str(params.get("level", "info")).lower()
        if level not in ("debug", "info", "warn", "error"):
            level = "info"
        message = str(params.get("message", ""))
        if message:
            add_log(self.plugin_id, level, message)
        return None

    # ═════════════════════════════════════════════════════════
    # LLM 对话
    # ═════════════════════════════════════════════════════════

    async def _op_llm_chat(self, params, ctx) -> str:
        from src.use_cases._plugin_helpers import llm_chat
        return await llm_chat(
            messages=params.get("messages", []),
            system_prompt=params.get("system_prompt"),
            tool_manager=ctx.tool_manager,
        )

    async def _op_llm_generate(self, params, ctx) -> str:
        from src.use_cases._plugin_helpers import llm_generate
        return await llm_generate(
            prompt=params.get("prompt", ""),
            system_prompt=params.get("system_prompt"),
            tool_manager=ctx.tool_manager,
        )

    # ═════════════════════════════════════════════════════════
    # TTS 语音合成
    # ═════════════════════════════════════════════════════════

    async def _op_tts_synthesize(self, params, ctx) -> str | None:
        from src.use_cases._plugin_helpers import tts_synthesize
        import base64
        audio_bytes = await tts_synthesize(
            text=params.get("text", ""),
            voice=params.get("voice"),
            tool_manager=ctx.tool_manager,
        )
        if audio_bytes:
            return base64.b64encode(audio_bytes).decode("ascii")
        return None

    # ═════════════════════════════════════════════════════════
    # 设备状态
    # ═════════════════════════════════════════════════════════

    async def _op_device_is_online(self, params, ctx) -> bool:
        from src.use_cases._plugin_helpers import device_is_online
        device_key = params.get("device_key") or ctx.device_key or ""
        return device_is_online(device_key=device_key, tool_manager=ctx.tool_manager)

    async def _op_device_get_info(self, params, ctx) -> dict:
        from src.use_cases._plugin_helpers import device_get_info
        device_key = params.get("device_key") or ctx.device_key or ""
        self._check_device_scope(device_key, ctx, "device_get_info")
        return await device_get_info(device_key=device_key, tool_manager=ctx.tool_manager)

    # ═════════════════════════════════════════════════════════
    # 插件数据持久化
    # ═════════════════════════════════════════════════════════

    async def _op_plugin_data_read(self, params, ctx) -> str | None:
        from src.use_cases._plugin_helpers import plugin_data_read
        return plugin_data_read(path=params.get("path", ""), tool_manager=ctx.tool_manager)

    async def _op_plugin_data_write(self, params, ctx) -> None:
        from src.use_cases._plugin_helpers import plugin_data_write
        plugin_data_write(
            path=params.get("path", ""),
            content=params.get("content", ""),
            tool_manager=ctx.tool_manager,
        )

    async def _op_plugin_data_list(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import plugin_data_list
        return plugin_data_list(path=params.get("path", ""), tool_manager=ctx.tool_manager)

    async def _op_plugin_data_delete(self, params, ctx) -> bool:
        from src.use_cases._plugin_helpers import plugin_data_delete
        return plugin_data_delete(path=params.get("path", ""), tool_manager=ctx.tool_manager)

    # ═════════════════════════════════════════════════════════
    # 键值存储
    # ═════════════════════════════════════════════════════════

    async def _op_kv_get(self, params, ctx) -> Any:
        from src.use_cases._plugin_helpers import kv_get
        return kv_get(
            key=params.get("key", ""),
            default=params.get("default"),
            tool_manager=ctx.tool_manager,
        )

    async def _op_kv_set(self, params, ctx) -> None:
        from src.use_cases._plugin_helpers import kv_set
        kv_set(key=params.get("key", ""), value=params.get("value"), tool_manager=ctx.tool_manager)

    async def _op_kv_delete(self, params, ctx) -> bool:
        from src.use_cases._plugin_helpers import kv_delete
        return kv_delete(key=params.get("key", ""), tool_manager=ctx.tool_manager)

    async def _op_kv_list(self, params, ctx) -> list:
        from src.use_cases._plugin_helpers import kv_list
        return kv_list(prefix=params.get("prefix", ""), tool_manager=ctx.tool_manager)

    # ═════════════════════════════════════════════════════════
    # 用户画像
    # ═════════════════════════════════════════════════════════

    async def _op_get_user_profile_summary(self, params, ctx) -> str:
        from src.use_cases._plugin_helpers import get_user_profile_summary
        device_key = params.get("device_key") or ctx.device_key or ""
        self._check_device_scope(device_key, ctx, "user_profile")
        return await get_user_profile_summary(device_key=device_key, tool_manager=ctx.tool_manager)

    # ── 设备作用域检查 ──────────────────────────────────────

    def _check_device_scope(self, target_device: str, ctx: CallContext, what: str) -> None:
        """数据操作必须限定在本次调用绑定的设备（防越权读他人数据）。"""
        if not ctx.device_key:
            # 无绑定设备时允许插件使用调用方传入的设备标识（与进程内行为一致）
            return
        if target_device and target_device != ctx.device_key:
            raise PermissionDenied(
                f"插件「{self.plugin_id}」尝试访问非当前设备的数据（{what}），已阻止"
            )


def _global_url_allowlist() -> list[str]:
    """全局 URL 白名单（环境变量 PLUGIN_URL_ALLOWLIST，逗号分隔域名）。"""
    raw = os.environ.get("PLUGIN_URL_ALLOWLIST", "").strip()
    if not raw:
        return []
    return [h.strip().lower() for h in raw.split(",") if h.strip()]