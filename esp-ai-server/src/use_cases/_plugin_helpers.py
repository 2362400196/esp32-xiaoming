"""插件公共工具函数（Plugin SDK）。

被 src/plugins/ 下各插件共享。以下划线前缀命名，auto_discover 扫描 use_cases
目录时会跳过，避免被当作工具模块加载。

统一封装：
  - 设备标识解析：get_device_key / resolve_device_key
  - 设备指令下发：send_instruct / send_device_command / request_device_result
  - 插件配置读取：get_plugin_config_or_env
  - HTTP 请求：http_request / http_get_json
  - LTM 长期记忆服务：get_ltm_service / get_default_ltm_service
  - Repository 工厂：get_diary_repository / get_device_repository
  - 技能目录渲染：skill_catalog_text
  - LLM 对话：llm_chat / llm_generate
  - TTS 语音合成：tts_synthesize
  - 设备状态：device_is_online / device_get_info
  - 插件数据持久化：plugin_data_read / plugin_data_write / plugin_data_list / plugin_data_delete
  - 键值存储：kv_get / kv_set / kv_delete / kv_list
  - 用户画像：get_user_profile_summary
  - 通用工具函数：generate_uuid / current_timestamp / json_dumps / json_loads
"""

import asyncio
import json
import os
import time as _time
import uuid as _uuid
from typing import Any

import httpx

from src.infrastructure.plugin_security import mask_secret, require_permission  # noqa: F401

# ════════════════════════════════════════════════════════════
# 设备标识解析
# ════════════════════════════════════════════════════════════


def get_device_key(tool_manager) -> str:
    """获取设备绑定 key（bound_xxx 格式）；未连接/未配置时返回空字符串。"""
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        return getattr(tool_manager.user_config, 'key', None) or ''
    return ''


def resolve_device_key(device_key: str, tool_manager) -> str:
    """自动填充 device_key：优先 tool_manager.user_config.key（bound_xxx 格式），
    其次 user_config.device_id（MAC）经 devices 表映射为 device_key。

    所有工具都通过此函数获取设备标识，确保查询 diary/short_term_memories 等
    内部表时使用正确的 bound_xxx 格式，而非 MAC 地址。
    """
    if device_key:
        return device_key
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        cfg = tool_manager.user_config
        key = getattr(cfg, 'key', None)
        if key:
            return key
        cfg_id = getattr(cfg, 'device_id', None)
        if cfg_id:
            # 统一映射：通过 devices 表将 MAC 地址转为 bound_xxx 格式
            try:
                from sqlalchemy import select

                from src.infrastructure.db.compat.sync_session import get_sync_session
                from src.infrastructure.db.models.device import DeviceModel
                with get_sync_session() as session:
                    result = session.execute(
                        select(DeviceModel.device_key).where(DeviceModel.device_id == cfg_id)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return row
            except Exception:
                pass
            return cfg_id
    return device_key


# ════════════════════════════════════════════════════════════
# 设备指令下发
# ════════════════════════════════════════════════════════════


async def send_instruct(channel, command_id, data="") -> None:
    """向设备通道发送一条 instruct 指令（不检查连接状态）。"""
    require_permission("device", f"下发设备指令 {command_id}")
    await channel.send_json({"type": "instruct", "command_id": command_id, "data": data})


async def send_device_command(tool_manager, command_id, data="") -> str | None:
    """向设备发送一条 instruct 指令。

    Returns:
        None 表示发送成功；字符串表示失败原因（"设备未连接" 或 "发送失败: xxx"）。
    """
    if not tool_manager or not tool_manager.channel:
        return "设备未连接"
    try:
        await send_instruct(tool_manager.channel, command_id, data)
        return None
    except PermissionError:
        return "设备指令权限未声明"
    except Exception as e:
        return f"发送失败: {e}"


async def send_device_command_ack(tool_manager, command_id, data="", timeout=8.0) -> tuple:
    """下发设备指令并等待设备 ack 确认（instruct_ack 消息）。

    相比 send_device_command 的 fire-and-forget，此函数会等待设备端回发
    {"type": "instruct_ack", "command_id": ..., "data": ...}，从而确认设备
    真实收到了指令并开始执行。

    Returns:
        (result, status, detail)：
          - status="ok"     → 设备已 ack，result 为 ack 携带的 data（或空字符串）
          - status="offline"→ 设备未连接
          - status="timeout"→ 超时未收到 ack
          - status="error"  → 发送异常
    """
    if not tool_manager or not tool_manager.channel:
        return None, "offline", "设备未连接"
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    tool_manager._pending_command_ack_future = future
    try:
        await send_instruct(tool_manager.channel, command_id, data)
    except PermissionError as e:
        tool_manager._pending_command_ack_future = None
        return None, "error", str(e)
    except Exception as e:
        tool_manager._pending_command_ack_future = None
        return None, "error", f"发送失败: {e}"
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result, "ok", ""
    except asyncio.TimeoutError:
        return None, "timeout", f"设备未在 {timeout} 秒内确认指令 {command_id}"
    finally:
        tool_manager._pending_command_ack_future = None


async def request_device_result(tool_manager, command_id, future_attr, timeout=8.0, data="", if_busy=None):
    """下发设备指令并等待设备通过 future 回复结果。

    Args:
        command_id: 设备指令名（execute_lua / get_volume / get_brightness 等）
        future_attr: tool_manager 上挂载 future 的属性名（_pending_lua_future / _pending_device_state_future）
        timeout: 等待超时秒数
        data: 指令数据
        if_busy: 若该 future 正被占用，返回 "busy" 状态并附此文案（None 表示不检查占用）

    Returns:
        (result, status, detail)：
          - status="ok"     → result 为设备回复字符串
          - status="offline"→ 设备未连接，detail="设备未连接"
          - status="timeout"→ 超时，detail="设备未在 X 秒内响应"
          - status="error"  → 发送异常，detail 含异常信息
          - status="busy"   → future 被占用，detail=if_busy
    """
    if not tool_manager or not tool_manager.channel:
        return None, "offline", "设备未连接"
    require_permission("device", f"下发设备指令 {command_id} 并等待结果")
    if if_busy is not None:
        busy_future = getattr(tool_manager, future_attr, None)
        if busy_future is not None and not busy_future.done():
            return None, "busy", if_busy
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    setattr(tool_manager, future_attr, future)
    try:
        await send_instruct(tool_manager.channel, command_id, data)
    except Exception as e:
        setattr(tool_manager, future_attr, None)
        return None, "error", f"发送失败: {e}"
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
        return result, "ok", ""
    except asyncio.TimeoutError:
        return None, "timeout", f"设备未在 {timeout} 秒内响应"
    finally:
        setattr(tool_manager, future_attr, None)


# ════════════════════════════════════════════════════════════
# 插件配置读取
# ════════════════════════════════════════════════════════════


def get_plugin_config_or_env(tool_manager, plugin: str, key: str, env_var: str | None = None, default: str = "") -> str:
    """读取插件配置：优先设备插件商店配置（tool_manager.get_plugin_config），
    其次环境变量（仅限白名单），最后默认值。"""
    if tool_manager is not None and hasattr(tool_manager, "get_plugin_config"):
        cfg = tool_manager.get_plugin_config(plugin, key, "")
        if cfg:
            return cfg
    if env_var:
        # 环境变量读取白名单：防止读取任意敏感环境变量（绕过 env_read 权限）
        from src.infrastructure.plugin_security import current_plugin, env_var_allowed
        ctx = current_plugin()
        plugin_id = ctx.plugin if ctx else plugin
        if env_var_allowed(plugin_id, env_var):
            val = os.environ.get(env_var, "")
            if val:
                return val
    return default


# ════════════════════════════════════════════════════════════
# HTTP 请求
# ════════════════════════════════════════════════════════════


async def http_request(method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
                       content=None, timeout: float = 10.0, pin_ip: str | None = None):
    """发起 HTTP 请求。成功返回 (response, None)；失败返回 (None, error)。

    Args:
        pin_ip: 校验时解析的 IP，用于 pin 连接防止 DNS 重绑定。
                 设置后会在 URL 中替换主机名为该 IP，并通过 Host header 保留原主机名。
    """
    require_permission("network", f"发起 HTTP {method.upper()} 请求 {url}")
    try:
        req_headers = dict(headers or {})
        if pin_ip:
            import urllib.parse as _up
            parsed = _up.urlparse(url)
            host = parsed.hostname or ""
            if host and host != pin_ip and parsed.scheme == "http":
                port = f":{parsed.port}" if parsed.port else ""
                url = _up.urlunparse((
                    parsed.scheme, f"{pin_ip}{port}",
                    parsed.path, parsed.params, parsed.query, parsed.fragment
                ))
                req_headers.setdefault("Host", host)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, headers=req_headers, content=content)
            resp.raise_for_status()
            return resp, None
    except Exception as e:
        return None, e


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                        timeout: float = 8.0, pin_ip: str | None = None):
    """GET 请求并解析 JSON。成功返回 (data, None)；失败返回 (None, error)。"""
    resp, err = await http_request("GET", url, params=params, headers=headers, timeout=timeout, pin_ip=pin_ip)
    if err:
        return None, err
    try:
        return resp.json(), None
    except Exception as e:
        return None, e


# ════════════════════════════════════════════════════════════
# LTM 长期记忆服务
# ════════════════════════════════════════════════════════════

_ltm_service: Any = None


def get_default_ltm_service():
    """创建默认 LTM 服务（模块级单例，无注入时的回退）"""
    require_permission("ltm", "访问长期记忆")
    global _ltm_service
    if _ltm_service is None:
        from src.infrastructure.db.repositories.ltm_repository import SqlLongTermMemoryRepository
        from src.use_cases.memory import LongTermMemoryServiceImpl
        repo = SqlLongTermMemoryRepository()
        _ltm_service = LongTermMemoryServiceImpl(repository=repo)
    return _ltm_service


def get_ltm_service(tool_manager=None):
    """获取 LTM 服务：优先从 tool_manager 注入获取，无则用默认单例"""
    require_permission("ltm", "访问长期记忆")
    if tool_manager and hasattr(tool_manager, 'ltm_service') and tool_manager.ltm_service:
        return tool_manager.ltm_service
    return get_default_ltm_service()


# ════════════════════════════════════════════════════════════
# Repository 工厂
# ════════════════════════════════════════════════════════════


def get_diary_repository():
    """获取日记仓储实例（延迟导入避免插件启动时加载 DB 依赖）。"""
    require_permission("db", "访问日记数据库")
    from src.infrastructure.db.repositories.growth_repositories import DiaryRepository
    return DiaryRepository()


def get_device_repository():
    """获取设备仓储实例（延迟导入避免插件启动时加载 DB 依赖）。"""
    require_permission("db", "访问设备数据库")
    from src.infrastructure.db.repositories.device_repository import DeviceRepository
    return DeviceRepository()


# ════════════════════════════════════════════════════════════
# 技能目录
# ════════════════════════════════════════════════════════════


def skill_catalog_text(tool_manager) -> str:
    """渲染当前设备可用技能目录文本（过滤禁用技能），供 LLM 工具直接返回。"""
    from src.use_cases import skill_system

    device_key = get_device_key(tool_manager)
    catalog = skill_system.get_catalog(device_id=device_key)

    user_config = getattr(tool_manager, 'user_config', None) if tool_manager else None
    disabled_skills = getattr(user_config, 'disabled_skills', None) if user_config else None
    if disabled_skills:
        catalog = [e for e in catalog if e.id not in disabled_skills]

    if not catalog:
        return "当前没有可用的技能。"

    lines = ["## 可用技能列表\n"]
    for entry in catalog:
        badge = " [设备专属]" if entry.device_id else ""
        tags = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        lines.append(f"- **{entry.id}**: {entry.description}{tags}{badge}")
    lines.append("")
    lines.append("提示: 使用 read_skill_document 工具(参数 skill_id)查看某个技能的详细使用说明，不要在回复中写出函数调用，要用 tool call API。")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# 插件日志
# ════════════════════════════════════════════════════════════


def plugin_log(message: str, level: str = "info") -> None:
    """写入插件日志（内置插件直接写共享存储，开发者可通过 API 查看）。

    Args:
        message: 日志消息
        level: 日志级别（debug/info/warn/error）
    """
    from src.infrastructure.plugin_log_store import add_log
    from src.infrastructure.plugin_security import current_plugin
    ctx = current_plugin()
    plugin_id = ctx.plugin if ctx else "unknown"
    add_log(plugin_id, level, message)


# ════════════════════════════════════════════════════════════
# LLM 对话
# ════════════════════════════════════════════════════════════


async def llm_chat(messages: list, system_prompt: str | None = None, tool_manager=None) -> str:
    """调用 LLM 进行对话。

    发送 messages 列表给 LLM，返回完整回复文本。
    支持自定义 system_prompt，如不传则使用全局配置的 system prompt。

    Args:
        messages: 消息列表，每项 {"role": "user"/"assistant", "content": "..."}
        system_prompt: 可选，覆盖全局 system prompt
        tool_manager: 自动传入

    Returns:
        LLM 回复文本
    """
    require_permission("llm", "调用 LLM 对话")
    from src.interfaces.llm_gateways import create_llm_gateway
    llm = create_llm_gateway(config=None, tool_manager=tool_manager)
    user_config = None
    if tool_manager and hasattr(tool_manager, 'user_config') and tool_manager.user_config:
        user_config = tool_manager.user_config
    return await llm.generate(messages, user_config=user_config)


async def llm_generate(prompt: str, system_prompt: str | None = None, tool_manager=None) -> str:
    """简单文本生成（单轮对话）。

    相比 llm_chat 更简洁，直接传入提示文本即可。

    Args:
        prompt: 用户提示文本
        system_prompt: 可选，覆盖全局 system prompt
        tool_manager: 自动传入

    Returns:
        LLM 生成的回复文本
    """
    messages = [{"role": "user", "content": prompt}]
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})
    return await llm_chat(messages, tool_manager=tool_manager)


# ════════════════════════════════════════════════════════════
# TTS 语音合成
# ════════════════════════════════════════════════════════════


async def tts_synthesize(text: str, voice: str | None = None, tool_manager=None) -> bytes:
    """文本转语音合成。

    将文本转换为 MP3 格式音频数据，可用于发送给设备播放。

    Args:
        text: 要合成的文本
        voice: 可选，音色（如 "BV001_streaming"），不传使用全局配置
        tool_manager: 自动传入

    Returns:
        MP3 音频字节数据
    """
    require_permission("tts", "调用 TTS 语音合成")
    from src.interfaces.tts_gateways import create_tts_gateway
    config = {}
    if voice:
        config["voice_type"] = voice
    tts = create_tts_gateway(config)
    chunks = []
    async for chunk in tts.synthesize(text):
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


# ════════════════════════════════════════════════════════════
# 设备状态
# ════════════════════════════════════════════════════════════


def device_is_online(device_key: str = "", tool_manager=None) -> bool:
    """检查设备是否在线。

    不传 device_key 时自动使用当前调用上下文绑定的设备。

    Args:
        device_key: 设备标识（bound_xxx 格式），为空时自动推断
        tool_manager: 自动传入

    Returns:
        True 表示设备在线
    """
    require_permission("device", "查询设备在线状态")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return False
    from src.infrastructure.device_api import get_device_registry
    registry = get_device_registry()
    if not registry:
        return False
    return registry.has(device_key)


async def device_get_info(device_key: str = "", tool_manager=None) -> dict:
    """获取设备信息。

    返回设备的基本信息，包括固件版本、MAC 地址、注册时间、OTA 状态等。

    Args:
        device_key: 设备标识，为空时自动推断
        tool_manager: 自动传入

    Returns:
        dict 包含设备信息，设备不在线时返回空 dict
    """
    require_permission("device", "查询设备信息")
    if not device_key and tool_manager:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return {}
    from src.infrastructure.device_api import get_device_registry
    registry = get_device_registry()
    if not registry:
        return {}
    device = registry.get(device_key)
    if not device:
        return {}
    return {
        "device_key": device_key,
        "mac": device.get("mac", ""),
        "firmware_version": device.get("firmware_version", ""),
        "register_time": device.get("register_time", 0),
        "ota_updating": device.get("ota_updating", False),
        "ota_progress": device.get("ota_progress", 0.0),
    }


# ════════════════════════════════════════════════════════════
# 插件数据持久化（文件系统）
# ════════════════════════════════════════════════════════════


def _get_plugin_id() -> str:
    """获取当前插件 ID。"""
    from src.infrastructure.plugin_security import current_plugin
    ctx = current_plugin()
    return ctx.plugin if ctx else "unknown"


def _get_project_root() -> str:
    """获取项目根目录。"""
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_plugin_data_dir() -> str:
    """获取当前插件的数据目录（自动创建）。"""
    plugin_id = _get_plugin_id()
    base = os.path.join(_get_project_root(), "data", "plugins", "data", plugin_id)
    os.makedirs(base, exist_ok=True)
    return base


def _safe_resolve_path(base: str, relative_path: str) -> str:
    """安全解析路径，防止路径穿越攻击。"""
    full = os.path.normpath(os.path.join(base, relative_path))
    if not full.startswith(base):
        raise PermissionError(f"路径越界: {relative_path}")
    return full


def plugin_data_read(path: str, tool_manager=None) -> str | None:
    """读取插件数据文件。

    文件必须位于插件专属数据目录下，禁止路径穿越。

    Args:
        path: 相对路径（如 "config.json" 或 "subdir/data.txt"）
        tool_manager: 自动传入

    Returns:
        文件内容字符串，文件不存在时返回 None
    """
    require_permission("file_read", "读取插件数据文件")
    full = _safe_resolve_path(_get_plugin_data_dir(), path)
    if not os.path.isfile(full):
        return None
    with open(full, "r", encoding="utf-8") as f:
        return f.read()


def plugin_data_write(path: str, content: str, tool_manager=None) -> None:
    """写入插件数据文件。

    自动创建中间目录，禁止路径穿越。

    Args:
        path: 相对路径（如 "config.json"）
        content: 文件内容
        tool_manager: 自动传入
    """
    require_permission("file_write", "写入插件数据文件")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def plugin_data_list(path: str = "", tool_manager=None) -> list:
    """列出插件数据目录下的文件和子目录。

    Args:
        path: 相对目录路径，为空时列出根目录
        tool_manager: 自动传入

    Returns:
        列表，每项包含 name/is_dir/size/mtime
    """
    require_permission("file_read", "列出插件数据目录")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    if not os.path.isdir(full):
        return []
    result = []
    for entry in os.scandir(full):
        size = entry.stat().st_size if entry.is_file() else 0
        result.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": size,
            "mtime": entry.stat().st_mtime,
        })
    return result


def plugin_data_delete(path: str, tool_manager=None) -> bool:
    """删除插件数据文件或空目录。

    Args:
        path: 相对路径
        tool_manager: 自动传入

    Returns:
        True 表示删除成功，False 表示路径不存在
    """
    require_permission("file_write", "删除插件数据文件")
    base = _get_plugin_data_dir()
    full = _safe_resolve_path(base, path)
    if os.path.isfile(full):
        os.remove(full)
        return True
    if os.path.isdir(full):
        import shutil
        shutil.rmtree(full)
        return True
    return False


# ════════════════════════════════════════════════════════════
# 插件键值存储（KV Store）
# ════════════════════════════════════════════════════════════


def _get_kv_store_path() -> str:
    """获取当前插件的 KV 存储文件路径。"""
    plugin_id = _get_plugin_id()
    kv_dir = os.path.join(_get_project_root(), "data", "plugins", "kv")
    os.makedirs(kv_dir, exist_ok=True)
    return os.path.join(kv_dir, f"{plugin_id}.json")


def _load_kv_store() -> dict:
    """加载 KV 存储。"""
    path = _get_kv_store_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_kv_store(store: dict) -> None:
    """保存 KV 存储。"""
    path = _get_kv_store_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def kv_get(key: str, default: Any = None, tool_manager=None) -> Any:
    """读取键值存储。

    插件专属的简单键值存储，数据持久化在服务器磁盘上。

    Args:
        key: 键名
        default: 键不存在时返回的默认值
        tool_manager: 自动传入

    Returns:
        存储的值，键不存在时返回 default
    """
    require_permission("kv", "读取键值存储")
    store = _load_kv_store()
    return store.get(key, default)


def kv_set(key: str, value: Any, tool_manager=None) -> None:
    """写入键值存储。

    Args:
        key: 键名
        value: 值（必须是 JSON 可序列化的类型）
        tool_manager: 自动传入
    """
    require_permission("kv", "写入键值存储")
    store = _load_kv_store()
    store[key] = value
    _save_kv_store(store)


def kv_delete(key: str, tool_manager=None) -> bool:
    """删除键值存储中的条目。

    Args:
        key: 键名
        tool_manager: 自动传入

    Returns:
        True 表示删除成功，False 表示键不存在
    """
    require_permission("kv", "删除键值存储")
    store = _load_kv_store()
    if key in store:
        del store[key]
        _save_kv_store(store)
        return True
    return False


def kv_list(prefix: str = "", tool_manager=None) -> list:
    """列出键值存储中的所有条目（可按前缀过滤）。

    Args:
        prefix: 可选，只返回键以此前缀开头的条目
        tool_manager: 自动传入

    Returns:
        列表，每项包含 {"key": "...", "value": ...}
    """
    require_permission("kv", "列出键值存储")
    store = _load_kv_store()
    if prefix:
        return [{"key": k, "value": v} for k, v in store.items() if k.startswith(prefix)]
    return [{"key": k, "value": v} for k, v in store.items()]


# ════════════════════════════════════════════════════════════
# 用户画像
# ════════════════════════════════════════════════════════════


async def get_user_profile_summary(device_key: str = "", tool_manager=None) -> str:
    """获取用户画像摘要。

    返回当前设备用户的画像摘要信息，包括姓名、特征、偏好等。

    Args:
        device_key: 设备标识，为空时自动推断
        tool_manager: 自动传入

    Returns:
        用户画像摘要文本，如 "暂无用户信息"
    """
    require_permission("db", "访问用户画像")
    if not device_key and tool_manager:
        device_key = resolve_device_key("", tool_manager)
    if not device_key:
        return "暂无用户信息"
    from src.use_cases.growth.user_profile import UserProfileService
    svc = UserProfileService("")
    summary = await svc.get_profile_summary(device_key)
    return summary or "暂无用户信息"


# ════════════════════════════════════════════════════════════
# 通用工具函数
# ════════════════════════════════════════════════════════════


def generate_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(_uuid.uuid4())


def current_timestamp() -> float:
    """获取当前时间戳（秒）。"""
    return _time.time()


def json_dumps(obj: Any, indent: int | None = None) -> str:
    """JSON 序列化对象为字符串。

    Args:
        obj: 要序列化的对象
        indent: 可选缩进空格数

    Returns:
        JSON 字符串
    """
    return json.dumps(obj, ensure_ascii=False, indent=indent)


def json_loads(s: str) -> Any:
    """JSON 反序列化字符串为 Python 对象。

    Args:
        s: JSON 字符串

    Returns:
        反序列化后的 Python 对象
    """
    return json.loads(s)
