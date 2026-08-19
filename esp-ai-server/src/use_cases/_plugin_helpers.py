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
"""

import asyncio
import os
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
                       content=None, timeout: float = 10.0):
    """发起 HTTP 请求。成功返回 (response, None)；失败返回 (None, error)。"""
    require_permission("network", f"发起 HTTP {method.upper()} 请求 {url}")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, params=params, headers=headers, content=content)
            resp.raise_for_status()
            return resp, None
    except Exception as e:
        return None, e


async def http_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                        timeout: float = 8.0):
    """GET 请求并解析 JSON。成功返回 (data, None)；失败返回 (None, error)。"""
    resp, err = await http_request("GET", url, params=params, headers=headers, timeout=timeout)
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
