"""子进程 SDK 桩模块：替代插件代码中的服务器内部模块。

插件通过 `from src.use_cases.tools_system import tool` 与
`from src.use_cases._plugin_helpers import ...` 使用 SDK。
在子进程中，这两个模块被本文件的桩实现替换：
    - 装饰器/类（tool / StopPipeline / get_all_tools）在子进程内本地工作
    - SDK 函数（http_request / send_device_command / get_ltm_service ...）
      全部转为 RPC 请求，由主进程按权限裁决后执行

桩模块在 import 插件代码前注入 sys.modules，因此插件 import 语句不会触发
真正的服务器模块加载。
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import json as _json
import sys
import types
from typing import Any

from . import client

# ════════════════════════════════════════════════════════════
# tools_system 桩
# ════════════════════════════════════════════════════════════


class StopPipeline(Exception):
    """插件抛出此异常以终止 LLM 生成流程（与主进程同义）。"""


_TOOLS: dict[str, dict] = {}


def _build_schema(func) -> dict:
    sig = inspect.signature(func)
    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "tool_manager", "channel", "ctx", "fsm"):
            continue
        prop = {"type": "string"}
        ann = param.annotation
        if ann is inspect.Parameter.empty:
            pass
        elif ann is int:
            prop["type"] = "integer"
        elif ann is float:
            prop["type"] = "number"
        elif ann is bool:
            prop["type"] = "boolean"
        elif ann is list:
            prop["type"] = "array"
        elif ann is dict:
            prop["type"] = "object"
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            prop["default"] = param.default
        properties[param_name] = prop
    parameters_schema = {"type": "object", "properties": properties}
    if required:
        parameters_schema["required"] = required
    return parameters_schema


def _tool_decorator(name=None, description=None, cache=True):
    def decorator(func):
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip() or tool_name
        _TOOLS[tool_name] = {
            "name": tool_name,
            "description": tool_desc,
            "schema": _build_schema(func),
            "cache": cache,
            "is_coro": inspect.iscoroutinefunction(func),
            "_func": func,
        }
        return func

    return decorator


def register_tool(td) -> None:
    """兼容接口：接受 ToolDefinition 兼容对象或 dict。"""
    if isinstance(td, dict):
        _TOOLS[td["name"]] = dict(td)
        return
    _TOOLS[td.name] = {
        "name": td.name,
        "description": td.description,
        "schema": td.parameters,
        "cache": getattr(td, "cache", True),
        "is_coro": inspect.iscoroutinefunction(td.func),
        "_func": td.func,
    }


def get_all_tools() -> dict:
    """返回可序列化的工具描述（不含函数对象）。"""
    out = {}
    for name, t in _TOOLS.items():
        out[name] = {k: v for k, v in t.items() if k != "_func"}
    return out


def get_tool_func(name: str):
    t = _TOOLS.get(name)
    return t.get("_func") if t else None


def build_tools_system_shim() -> types.ModuleType:
    mod = types.ModuleType("src.use_cases.tools_system")
    mod.__dict__.update({
        "StopPipeline": StopPipeline,
        "tool": _tool_decorator,
        "register_tool": register_tool,
        "get_all_tools": get_all_tools,
    })
    return mod


# ════════════════════════════════════════════════════════════
# _plugin_helpers 桩
# ════════════════════════════════════════════════════════════


# 纯本地实现（不涉及主进程能力）
_SECRET_SUFFIXES = ("key", "token", "secret", "password", "passwd", "appid")


def is_secret_key(key: str) -> bool:
    k = (key or "").lower().replace("-", "_")
    return any(k == s or k.endswith("_" + s) for s in _SECRET_SUFFIXES)


def mask_secret(value, visible=4) -> str:
    s = str(value)
    if not s:
        return ""
    if len(s) <= visible:
        return "*" * len(s)
    return "*" * (len(s) - visible) + s[-visible:]


def require_permission(perm: str, what: str = "") -> None:
    """子进程内不强制（权限在主进程边界裁决）；保留签名以兼容 import。"""
    return None


def _to_plain(o) -> Any:
    """将 SDK 参数/结果对象序列化为可 JSON 传输的普通结构。"""
    if o is None or isinstance(o, (str, int, float, bool)):
        return o
    if isinstance(o, (tuple, list)):
        return [_to_plain(x) for x in o]
    if isinstance(o, dict):
        return {k: _to_plain(v) for k, v in o.items()}
    if isinstance(o, enum.Enum):
        return o.value
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: _to_plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if hasattr(o, "to_dict"):
        return _to_plain(o.to_dict())
    d = {k: _to_plain(v) for k, v in vars(o).items()}
    if d:
        return d
    return {k: _to_plain(getattr(o, k)) for k in dir(o)
            if not k.startswith("_") and not callable(getattr(o, k))}


def _resp(result):
    return _to_plain(result)


# ── 设备标识 ────────────────────────────────────────────────


def get_device_key(tool_manager=None) -> str:
    return client.send_sync("device_key", {}) or ""


def resolve_device_key(device_key: str = "", tool_manager=None) -> str:
    return client.send_sync("resolve_device_key", {"device_key": device_key or ""}) or device_key


# ── 设备指令 ────────────────────────────────────────────────


async def send_instruct(channel=None, command_id="", data="") -> None:
    await client.send_async("device_send_instruct", {"command_id": command_id, "data": data})


async def send_device_command(tool_manager=None, command_id="", data="") -> str | None:
    return await client.send_async("device_send_command", {"command_id": command_id, "data": data})


async def send_device_command_ack(tool_manager=None, command_id="", data="", timeout=8.0) -> tuple:
    result = await client.send_async(
        "device_send_command_ack", {"command_id": command_id, "data": data, "timeout": timeout}
    )
    return tuple(result) if isinstance(result, list) else (None, "error", "无效返回")


async def request_device_result(tool_manager=None, command_id="", future_attr="",
                               timeout=8.0, data="", if_busy=None) -> tuple:
    result = await client.send_async(
        "device_request_result",
        {"command_id": command_id, "future_attr": future_attr,
         "timeout": timeout, "data": data, "if_busy": if_busy},
    )
    return tuple(result) if isinstance(result, list) else (None, "error", "无效返回")


# ── 插件配置 ────────────────────────────────────────────────


def get_plugin_config_or_env(tool_manager=None, plugin: str = "", key: str = "",
                             env_var: str | None = None, default: str = "") -> str:
    return client.send_sync(
        "plugin_config", {"plugin": plugin, "key": key,
                          "env_var": env_var or "", "default": default}
    ) or default


# ── HTTP ────────────────────────────────────────────────────


async def http_request(method: str, url: str, *, params: dict | None = None,
                       headers: dict | None = None, content=None, timeout: float = 10.0):
    result = await client.send_async(
        "http_request", {"method": method, "url": url, "params": params,
                         "headers": headers, "content": content, "timeout": timeout}
    )
    # 返回 (resp, err) 结构：[status, body_text, err]
    if not isinstance(result, list) or len(result) < 3:
        return None, RuntimeError("无效的 http_request 返回")
    status, body, err = result
    if err is not None:
        return None, RuntimeError(err)
    resp = _FakeResponse(status, body)
    return resp, None


class _FakeResponse:
    """模拟 httpx.Response 的最小实现（仅暴露 .status_code / .text / .json()）。"""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        return _json.loads(self.text)


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                        timeout: float = 8.0):
    result = await client.send_async(
        "http_get_json", {"url": url, "params": params, "headers": headers, "timeout": timeout}
    )
    if not isinstance(result, list) or len(result) < 2:
        return None, RuntimeError("无效的 http_get_json 返回")
    data, err = result
    if err is not None:
        return None, RuntimeError(err)
    return data, None


# ── LTM / Repository 代理 ──────────────────────────────────


class _LtmProxy:
    """get_ltm_service / get_default_ltm_service 返回的代理对象。"""

    async def store(self, item) -> tuple:
        res = await client.send_async("ltm_store", {"item": _resp(item)})
        return tuple(res) if isinstance(res, list) else (None, False)

    async def recall(self, query) -> list:
        res = await client.send_async("ltm_recall", {"query": _resp(query)})
        return res or []

    async def list_all(self, device_id: str) -> list:
        res = await client.send_async("ltm_list_all", {"device_id": device_id})
        return res or []

    async def update(self, memory_id: str, patch: dict, device_id: str) -> bool:
        return await client.send_async(
            "ltm_update", {"memory_id": memory_id, "patch": patch, "device_id": device_id}
        )

    async def forget(self, memory_id: str, device_id: str):
        return await client.send_async("ltm_forget", {"memory_id": memory_id, "device_id": device_id})


class _DiaryRepoProxy:
    async def get_recent(self, device_id: str, limit: int = 7) -> list:
        res = await client.send_async("diary_get_recent", {"device_id": device_id, "limit": limit})
        return res or []

    async def upsert_entry(self, device_id: str, date: str, content: str, append: bool = False):
        return await client.send_async(
            "diary_upsert_entry", {"device_id": device_id, "date": date,
                                   "content": content, "append": append}
        )

    async def search(self, device_id: str, keyword: str) -> list:
        res = await client.send_async("diary_search", {"device_id": device_id, "keyword": keyword})
        return res or []


class _DeviceRepoProxy:
    async def get_device_config(self, device_id: str):
        return await client.send_async("device_config_get", {"device_id": device_id})

    async def update_device_partial(self, device_id: str, partial: dict):
        return await client.send_async(
            "device_config_update_partial", {"device_id": device_id, "partial": partial}
        )


def get_ltm_service(tool_manager=None):
    return _LtmProxy()


def get_default_ltm_service():
    return _LtmProxy()


def get_diary_repository():
    return _DiaryRepoProxy()


def get_device_repository():
    return _DeviceRepoProxy()


def skill_catalog_text(tool_manager=None) -> str:
    return client.send_sync("skill_catalog", {}) or ""


def plugin_log(message: str, level: str = "info") -> None:
    """插件自定义日志（通过 RPC 写入主进程日志存储，供 API 查询）。"""
    try:
        client.send_sync("plugin_log", {"level": level, "message": message})
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
# LLM 对话
# ════════════════════════════════════════════════════════════


async def llm_chat(messages: list, system_prompt: str | None = None, tool_manager=None) -> str:
    result = await client.send_async("llm_chat", {
        "messages": messages, "system_prompt": system_prompt,
    })
    return result or ""


async def llm_generate(prompt: str, system_prompt: str | None = None, tool_manager=None) -> str:
    result = await client.send_async("llm_generate", {
        "prompt": prompt, "system_prompt": system_prompt,
    })
    return result or ""


# ════════════════════════════════════════════════════════════
# TTS 语音合成
# ════════════════════════════════════════════════════════════


async def tts_synthesize(text: str, voice: str | None = None, tool_manager=None) -> bytes:
    import base64
    result = await client.send_async("tts_synthesize", {
        "text": text, "voice": voice,
    })
    if result:
        return base64.b64decode(result)
    return b""


# ════════════════════════════════════════════════════════════
# 设备状态
# ════════════════════════════════════════════════════════════


def device_is_online(device_key: str = "", tool_manager=None) -> bool:
    result = client.send_sync("device_is_online", {"device_key": device_key})
    return bool(result)


async def device_get_info(device_key: str = "", tool_manager=None) -> dict:
    result = await client.send_async("device_get_info", {"device_key": device_key})
    return result or {}


# ════════════════════════════════════════════════════════════
# 插件数据持久化
# ════════════════════════════════════════════════════════════


def plugin_data_read(path: str, tool_manager=None) -> str | None:
    return client.send_sync("plugin_data_read", {"path": path})


def plugin_data_write(path: str, content: str, tool_manager=None) -> None:
    client.send_sync("plugin_data_write", {"path": path, "content": content})


def plugin_data_list(path: str = "", tool_manager=None) -> list:
    return client.send_sync("plugin_data_list", {"path": path}) or []


def plugin_data_delete(path: str, tool_manager=None) -> bool:
    return bool(client.send_sync("plugin_data_delete", {"path": path}))


# ════════════════════════════════════════════════════════════
# 键值存储
# ════════════════════════════════════════════════════════════


def kv_get(key: str, default: Any = None, tool_manager=None) -> Any:
    return client.send_sync("kv_get", {"key": key, "default": default})


def kv_set(key: str, value: Any, tool_manager=None) -> None:
    client.send_sync("kv_set", {"key": key, "value": value})


def kv_delete(key: str, tool_manager=None) -> bool:
    return bool(client.send_sync("kv_delete", {"key": key}))


def kv_list(prefix: str = "", tool_manager=None) -> list:
    return client.send_sync("kv_list", {"prefix": prefix}) or []


# ════════════════════════════════════════════════════════════
# 用户画像
# ════════════════════════════════════════════════════════════


async def get_user_profile_summary(device_key: str = "", tool_manager=None) -> str:
    result = await client.send_async("get_user_profile_summary", {"device_key": device_key})
    return result or "暂无用户信息"


# ════════════════════════════════════════════════════════════
# 通用工具函数（纯本地实现，无需 RPC）
# ════════════════════════════════════════════════════════════


def generate_uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def current_timestamp() -> float:
    import time
    return time.time()


def json_dumps(obj: Any, indent: int | None = None) -> str:
    return _json.dumps(obj, ensure_ascii=False, indent=indent)


def json_loads(s: str) -> Any:
    return _json.loads(s)


def build_helpers_shim() -> types.ModuleType:
    mod = types.ModuleType("src.use_cases._plugin_helpers")
    mod.__dict__.update({
        "get_device_key": get_device_key,
        "resolve_device_key": resolve_device_key,
        "send_instruct": send_instruct,
        "send_device_command": send_device_command,
        "send_device_command_ack": send_device_command_ack,
        "request_device_result": request_device_result,
        "get_plugin_config_or_env": get_plugin_config_or_env,
        "http_request": http_request,
        "http_get_json": http_get_json,
        "get_ltm_service": get_ltm_service,
        "get_default_ltm_service": get_default_ltm_service,
        "get_diary_repository": get_diary_repository,
        "get_device_repository": get_device_repository,
        "skill_catalog_text": skill_catalog_text,
        "plugin_log": plugin_log,
        "mask_secret": mask_secret,
        "is_secret_key": is_secret_key,
        "require_permission": require_permission,
        # 新增能力
        "llm_chat": llm_chat,
        "llm_generate": llm_generate,
        "tts_synthesize": tts_synthesize,
        "device_is_online": device_is_online,
        "device_get_info": device_get_info,
        "plugin_data_read": plugin_data_read,
        "plugin_data_write": plugin_data_write,
        "plugin_data_list": plugin_data_list,
        "plugin_data_delete": plugin_data_delete,
        "kv_get": kv_get,
        "kv_set": kv_set,
        "kv_delete": kv_delete,
        "kv_list": kv_list,
        "get_user_profile_summary": get_user_profile_summary,
        "generate_uuid": generate_uuid,
        "current_timestamp": current_timestamp,
        "json_dumps": json_dumps,
        "json_loads": json_loads,
    })
    return mod


# ════════════════════════════════════════════════════════════
# 桩模块注册
# ════════════════════════════════════════════════════════════


def install_shims(plugin_id: str, src_dir: str) -> None:
    """将 SDK 桩模块注入 sys.modules，并注册沙箱额外放行名单。

    Args:
        plugin_id: 插件 ID（用于命名插件模块）
        src_dir: 服务器 src 目录（允许导入只读数据类如 src.domain.entities）
    """
    from . import sandbox

    sandbox.set_allowed_extra([
        "src.use_cases.tools_system",
        "src.use_cases._plugin_helpers",
        "src.domain",
        "src.domain.entities",
        "src.domain.value_objects",
    ])
    tools_mod = build_tools_system_shim()
    helpers_mod = build_helpers_shim()
    sys.modules["src.use_cases.tools_system"] = tools_mod
    sys.modules["src.use_cases._plugin_helpers"] = helpers_mod
    # 父包占位：src 指向真实目录（只读数据类可导入），use_cases 用空路径（SDK 已桩化）
    if "src" not in sys.modules:
        src_pkg = types.ModuleType("src")
        src_pkg.__path__ = [src_dir]
        sys.modules["src"] = src_pkg
    if "src.use_cases" not in sys.modules:
        uc_pkg = types.ModuleType("src.use_cases")
        uc_pkg.__path__ = []
        sys.modules["src.use_cases"] = uc_pkg