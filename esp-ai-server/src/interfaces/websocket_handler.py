"""WebSocket Handler - Interface Adapters 层

本模块仅保留 WebSocket 入口函数 handle_websocket（被 infrastructure/web.py
注册为路由）。完整的会话生命周期逻辑已拆分至
WebSocketSessionHandler（见 ws_session_handler.py）。
"""
from __future__ import annotations

import asyncio
import secrets
import string
import time
import uuid

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from src.infrastructure.config import get_settings
from src.infrastructure.concurrency import try_acquire_global_slot, release_global_slot
from src.infrastructure.logging import get_logger, set_trace_id
from src.infrastructure.web import get_auth_service
from src.interfaces.ws_session_handler import WebSocketSessionHandler

logger = get_logger(__name__)

_WS_GLOBAL_SLOT_ACQUIRE_TIMEOUT = 5.0


def _generate_bind_code() -> str:
    """生成 6 位大写字母+数字绑定码（使用密码学安全随机数）"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(6))


async def _send_bind_code_and_close(websocket: WebSocket, device_mac: str) -> None:
    """生成绑定码，存入 DB，通过 WS 发送给设备，然后关闭连接"""
    from src.infrastructure.db.session import get_session_ctx
    from src.infrastructure.db.models.device import DeviceModel
    from sqlalchemy import select

    bind_code = _generate_bind_code()
    expires = time.time() + 300  # 5 分钟有效

    async with get_session_ctx() as session:
        result = await session.execute(
            select(DeviceModel).where(DeviceModel.mac_address == device_mac)
        )
        device = result.scalar_one_or_none()
        if not device:
            result2 = await session.execute(
                select(DeviceModel).where(DeviceModel.device_id == device_mac)
            )
            device = result2.scalar_one_or_none()

        # 仍未找到时，尝试截断 MAC 查找（旧版缓冲区 18 字节截断为 17 字符）
        if not device and len(device_mac) > 17:
            from sqlalchemy import or_
            truncated = device_mac[:17]
            result3 = await session.execute(
                select(DeviceModel).where(
                    or_(
                        DeviceModel.mac_address == truncated,
                        DeviceModel.device_id == truncated,
                    )
                )
            )
            device = result3.scalar_one_or_none()
            if device:
                old_mac = device.mac_address
                device.mac_address = device_mac
                await session.flush()
                logger.info(f"[Bind] 设备 MAC 迁移: '{old_mac}' → '{device_mac}'")

        if not device:
            device = DeviceModel(
                device_id=device_mac,
                name=f"Device-{device_mac[-6:]}",
                # device_key 使用密码学安全随机数生成，不可由 MAC 推导
                device_key="auto_" + secrets.token_hex(16),
                mac_address=device_mac,
            )
            session.add(device)

        # 如果已有未过期的绑定码，复用，不覆盖（避免设备重连生成新码导致用户输入的旧码失效）
        if device.bind_code and device.bind_code_expires and device.bind_code_expires > time.time():
            bind_code = device.bind_code
            logger.info(f"[Bind] 复用已有绑定码 {bind_code} 给设备 {device_mac}")
        else:
            device.bind_code = bind_code
            device.bind_code_expires = expires
        await session.flush()

    logger.info(f"[Bind] 生成绑定码 {bind_code} 给设备 {device_mac}，有效期 5 分钟")

    try:
        await websocket.accept()
        await websocket.send_json({
            "type": "instruct",
            "command_id": "show_bind_code",
            "data": bind_code,
        })
        # 使用 1000 正常关闭码，确保 esp_websocket_client 触发自动重连
        await websocket.close(code=1000, reason="Need binding")
        logger.info(f"[Bind] 已发送绑定码 {bind_code} 给设备 {device_mac}")
    except Exception as e:
        logger.warning(f"[Bind] 发送绑定码失败: {e}")


async def handle_websocket(websocket: WebSocket):
    """WebSocket 入口 - 解析参数、鉴权后委托给 WebSocketSessionHandler"""
    settings = get_settings()

    device_key = websocket.query_params.get("key", "") or websocket.query_params.get("api_key", "")
    device_mac = websocket.query_params.get("mac", "") or websocket.query_params.get("device_id", "")
    device_firmware_version = websocket.query_params.get("version", "") or websocket.query_params.get("v", "")
    client_audio_buffer_size = int(websocket.query_params.get("AUDIO_BUFFER_SIZE", "10240"))
    # 设备喇叭采样率（如 spk_sample_rate=16000），用于让 TTS 按设备能力输出，避免 ES8311 等
    # 16kHz 喇叭链路播放 24kHz 音频导致无声/变调；解析失败或缺失时保持 0（服务端用默认值）
    try:
        spk_sample_rate = int(websocket.query_params.get("spk_sample_rate", "") or 0)
    except (ValueError, TypeError):
        spk_sample_rate = 0
    ws_path = websocket.url.path
    trace_id = str(uuid.uuid4())
    # 设备屏幕能力上报（固件 URL 参数：C3 headless=0，S3=1；缺失=未知，回退到设备配置）
    reported_has_display = websocket.query_params.get("has_display", "")
    if reported_has_display in ("0", "1"):
        reported_has_display = reported_has_display == "1"
    else:
        reported_has_display = None
    try:
        set_trace_id(trace_id)
    except Exception:
        pass

    logger.info(f"[WS] New connection: path={ws_path}, device_id={device_mac or 'N/A'}, version={device_firmware_version or 'N/A'}, trace_id={trace_id}")

    # 当前连接对应的设备记录（带 key / 不带 key 两条路径都必须赋值，供后续封禁检查使用）
    device = None

    # 无 key 连接：查 DB 补全 device_key
    if not device_key:
        if not device_mac:
            await websocket.close(code=4001, reason="Missing device identifier")
            return

        # 查 DB 看设备是否已绑定到用户
        from src.infrastructure.db.session import get_session_ctx
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select, or_

        async with get_session_ctx() as session:
            # 先按 mac_address 精确查找
            result = await session.execute(
                select(DeviceModel).where(
                    DeviceModel.mac_address == device_mac
                )
            )
            device = result.scalar_one_or_none()

            # mac_address 未找到时，回退按 device_key / device_id 查找
            if not device:
                result = await session.execute(
                    select(DeviceModel).where(
                        or_(
                            DeviceModel.device_key == device_mac,
                            DeviceModel.device_id == device_mac,
                        )
                    )
                )
                device = result.scalar_one_or_none()
                if device and device.mac_address != device_mac:
                    old_mac = device.mac_address
                    device.mac_address = device_mac
                    await session.flush()
                    logger.info(f"[WS] 设备 {device_mac} MAC 已从 '{old_mac}' 更新为完整值")

            # 精确匹配到但未绑定时，尝试截断 MAC 查找已绑定的旧记录
            # （旧版缓冲区 18 字节截断为 17 字符，可能有已绑定的旧记录）
            if (not device or not device.user_id) and len(device_mac) > 17:
                truncated = device_mac[:17]
                result = await session.execute(
                    select(DeviceModel).where(
                        or_(
                            DeviceModel.mac_address == truncated,
                            DeviceModel.device_id == truncated,
                        ),
                        DeviceModel.user_id.isnot(None),  # 只找已绑定的
                    )
                )
                bound_device = result.scalar_one_or_none()
                if bound_device:
                    # 删除未绑定的重复记录
                    if device and not device.user_id:
                        await session.delete(device)
                        logger.info(f"[WS] 删除未绑定的重复记录: {device.device_id}")
                    # 更新已绑定记录的 MAC
                    old_mac = bound_device.mac_address
                    bound_device.mac_address = device_mac
                    await session.flush()
                    logger.info(f"[WS] 设备 MAC 迁移: '{old_mac}' → '{device_mac}'")
                    device = bound_device

        if device and device.user_id:
            if device.device_key:
                # 已绑定且有 key：从 DB 取出 device_key 用于后续认证
                device_key = device.device_key
                logger.info(f"[WS] 设备 {device_mac} 已绑定，从 DB 获取 device_key 进行认证")
            else:
                # 安全修复：已绑定但无 key 的连接不得自动生成 key 放行认证。
                # MAC 地址可被嗅探，若仅凭 MAC 即接管已绑定设备会话，攻击者可冒充设备。
                # 拒绝连接，让用户走重新配网/绑定流程。
                logger.warning(
                    f"[WS][安全] 设备 {device_mac} 已绑定用户但连接未携带 device_key，"
                    f"拒绝连接，请走重新配网/绑定流程"
                )
                await websocket.close(
                    code=4004, reason="Device bound but missing key, please re-bind"
                )
                return

        await session.commit()  # 确保 device_key 立即持久化

        if device and device.user_id and device_key:
            pass  # 已处理，继续
        else:
            # 未绑定：进入绑定模式
            logger.info(f"[WS] 设备 {device_mac} 未绑定，进入绑定模式")
            await _send_bind_code_and_close(websocket, device_mac)
            return

    # 强制认证：所有连接必须验证 device_key，不跳过
    auth_service = get_auth_service()
    auth_ok = False
    if auth_service and auth_service.verify_api_key(device_key):
        auth_ok = True
    else:
        # 内存中找不到时回退到数据库查找（通过 to_thread 避免阻塞事件循环）
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select

        def _auth_lookup():
            with get_sync_session() as sess:
                r = sess.execute(select(DeviceModel).where(DeviceModel.device_key == device_key))
                return r.scalar_one_or_none() is not None

        auth_ok = await asyncio.to_thread(_auth_lookup)
    if not auth_ok:
        logger.warning(f"[WS] Authentication failed for device_id={device_mac or 'unknown'}")
        await websocket.close(code=4003, reason="Authentication failed")
        return

    # 带 key 连接路径：无 key 分支未加载 device 记录，此处按 device_key 查询，
    # 确保封禁检查对两条路径都生效（放在鉴权之后，避免未认证请求触发 DB 查询）
    if device is None:
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select

        def _lookup_device_by_key():
            with get_sync_session() as sess:
                r = sess.execute(select(DeviceModel).where(DeviceModel.device_key == device_key))
                return r.scalar_one_or_none()

        device = await asyncio.to_thread(_lookup_device_by_key)

    # 检查设备是否被封禁
    if device:
        if device.is_banned:
            reason = device.ban_reason or "设备已被管理员封禁"
            logger.warning(f"[WS] Banned device rejected: {device.device_id}, reason: {reason}")
            await websocket.close(code=4003, reason=f"Device banned: {reason}")
            return
    else:
        # 尝试从 DB 查设备封禁状态
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from sqlalchemy import select

        def _ban_check():
            with get_sync_session() as sess:
                r = sess.execute(select(DeviceModel).where(
                    (DeviceModel.device_key == device_key) |
                    (DeviceModel.mac_address == device_mac) |
                    (DeviceModel.device_id == device_mac)
                ))
                return r.scalar_one_or_none()
        banned_device = await asyncio.to_thread(_ban_check)
        if banned_device and banned_device.is_banned:
            reason = banned_device.ban_reason or "设备已被管理员封禁"
            logger.warning(f"[WS] Banned device rejected: {banned_device.device_id}, reason: {reason}")
            await websocket.close(code=4003, reason=f"Device banned: {reason}")
            return

    acquired = await try_acquire_global_slot(timeout=_WS_GLOBAL_SLOT_ACQUIRE_TIMEOUT)
    if not acquired:
        logger.warning(f"[WS] Server overloaded, rejecting connection: device_id={device_mac or 'unknown'}")
        await websocket.close(code=1013, reason="Server overloaded")
        return

    is_multi_mode = settings.deploy_mode == "multi"
    user_config = None

    # 统一从 DB 加载设备配置
    if is_multi_mode:
        from src.infrastructure.db.compat.sync_session import get_sync_session
        from src.infrastructure.db.models.device import DeviceModel
        from src.use_cases.device_config import DeviceConfig

        # 通过 to_thread 执行同步 DB 查询，避免阻塞事件循环
        def _load_device_config():
            with get_sync_session() as session:
                result = session.execute(
                    select(DeviceModel).where(DeviceModel.device_key == device_key)
                )
                model = result.scalar_one_or_none()
                if not model:
                    return None

                logger.info(f"[WS] DB加载设备配置: asr_provider='{model.asr_provider}', asr_config={dict(model.asr_config or {})}, tts_config={dict(model.tts_config or {})}")
                llm = {
                    "api_key": model.llm_api_key or "",
                    "base_url": model.llm_base_url or "",
                    "model": model.llm_model or "",
                    "system_prompt": model.llm_system_prompt or "",
                    "memory_enabled": model.llm_memory_enabled,
                    "memory_max_messages": model.llm_memory_max_messages,
                    "memory_long_term_enabled": model.llm_memory_long_term_enabled,
                    "memory_long_term_auto_extract": model.llm_memory_long_term_auto_extract,
                }
                uc = DeviceConfig(
                    device_id=model.device_id,
                    name=model.name,
                    key=model.device_key,
                    asr_provider=model.asr_provider,
                    llm_type=model.llm_type,
                    tts_type=model.tts_type,
                    asr_config=dict(model.asr_config or {}),
                    tts_config=dict(model.tts_config or {}),
                    music_config=dict(model.music_config or {}),
                    wakeup_config=dict(model.wakeup_config or {}),
                    mcp_servers=dict(model.mcp_servers or {}),
                    llm_api_key=model.llm_api_key,
                    llm_base_url=model.llm_base_url,
                    llm_model=model.llm_model,
                    llm_system_prompt=model.llm_system_prompt,
                    llm_memory_enabled=model.llm_memory_enabled,
                    llm_memory_max_messages=model.llm_memory_max_messages,
                    llm_memory_long_term_enabled=model.llm_memory_long_term_enabled,
                    llm_memory_long_term_auto_extract=model.llm_memory_long_term_auto_extract,
                    enabled_plugins=list(model.enabled_plugins or []),
                    plugin_configs=dict(model.plugin_configs or {}),
                    has_display=model.has_display,
                    disabled_tools=list(model.disabled_tools or []),
                    disabled_mcp_servers=list(model.disabled_mcp_servers or []),
                    disabled_mcp_tools=dict(model.disabled_mcp_tools or {}),
                    disabled_skills=list(model.disabled_skills or []),
                    skills=list(model.skills or []),
                    robot_mode=model.robot_mode or "false",
                    screensaver_enabled=model.screensaver_enabled or "true",
                    screensaver_timeout=model.screensaver_timeout or "30",
                )
                logger.info(f"[WS] 设备 {device_mac} 配置已从 DB 加载")

                # 绑定成功后设备重连，触发重启（bind_code == "BOUND" 表示刚绑定）
                if model.bind_code == "BOUND":
                    logger.info(f"[WS] 设备 {device_mac} 刚绑定，清除标记")
                    model.bind_code = None
                    session.flush()
                    # 直接继续正常会话，会话初始化会重置显示覆盖绑定码
                return uc

        user_config = await asyncio.to_thread(_load_device_config)
        if not user_config:
            logger.warning(f"[WS] 认证通过但 DB 中未找到 device_key 对应设备")
            await websocket.close(code=4003, reason="Device not found")
            release_global_slot()
            return

    handler = WebSocketSessionHandler(
        websocket, device_key, device_mac, device_firmware_version, trace_id,
    )
    handler.client_audio_buffer_size = client_audio_buffer_size
    handler.spk_sample_rate = spk_sample_rate
    handler.reported_has_display = reported_has_display
    handler.user_config = user_config
    handler.is_multi_mode = is_multi_mode

    try:
        await handler.initialize()
        await handler.run()
    except WebSocketDisconnect as e:
        logger.info(f"[WS] Client disconnected: code={e.code}")
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        await handler.cleanup()
        release_global_slot()
