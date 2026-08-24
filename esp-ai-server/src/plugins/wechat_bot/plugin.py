"""微信集成插件：消息收发、二维码登录、设备绑定管理。"""

from src.use_cases.tools_system import tool
from src.use_cases._plugin_helpers import get_device_key, get_wechat_bot, get_wechat_binding_mgr


@tool()
async def send_wechat_message(chat_id: str, text: str, tool_manager=None) -> str:
    """发送微信消息到指定会话。
    参数:
        chat_id: 微信会话 ID（用户的 chat_id 或群聊的 chat_id）
        text: 消息内容
    """
    bot = get_wechat_bot()
    if not bot or not bot.state.configured:
        return "微信未配置或未登录，无法发送消息"
    try:
        await bot.send_text(chat_id, text)
        return f"消息已发送到 {chat_id[:16]}"
    except Exception as e:
        return f"发送失败: {e}"


@tool()
async def send_wechat_image(chat_id: str, image_path: str, caption: str = "", tool_manager=None) -> str:
    """发送图片到微信会话。
    参数:
        chat_id: 微信会话 ID
        image_path: 图片文件路径（服务器本地路径）
        caption: 图片描述文字（可选）
    """
    bot = get_wechat_bot()
    if not bot or not bot.state.configured:
        return "微信未配置或未登录，无法发送图片"
    try:
        await bot.send_image(chat_id, image_path, caption)
        return f"图片已发送到 {chat_id[:16]}"
    except Exception as e:
        return f"发送失败: {e}"


@tool()
async def get_wechat_binding_status(device_key: str = "", tool_manager=None) -> str:
    """查询设备是否已绑定微信。
    参数:
        device_key: 设备标识，不传则自动使用当前设备
    """
    from src.use_cases.wechat_binding import get_wechat_binding_manager
    if not device_key:
        device_key = get_device_key(tool_manager)
    if not device_key:
        return "未获取到设备信息"
    bind_mgr = get_wechat_binding_manager()
    binding = bind_mgr.find_binding(device_key)
    if binding:
        return f"设备已绑定微信（chat_id: {binding.wechat_chat_id[:16]}）"
    return "设备未绑定微信"


@tool()
async def list_wechat_bindings(tool_manager=None) -> str:
    """列出所有微信绑定关系。"""
    from src.use_cases.wechat_binding import get_wechat_binding_manager
    bind_mgr = get_wechat_binding_manager()
    bindings = bind_mgr.get_all_bindings()
    if not bindings:
        return "当前没有微信绑定关系"
    lines = []
    for b in bindings:
        lines.append(f"设备: {b.device_key[:16]} → 微信: {b.wechat_chat_id[:16]}")
    return "\n".join(["微信绑定列表："] + lines)


@tool()
async def get_wechat_qr_login_status(tool_manager=None) -> str:
    """获取微信二维码登录状态。"""
    bot = get_wechat_bot()
    if not bot:
        return "微信机器人未初始化"
    state = bot.state
    if state.configured:
        return "微信已登录"
    qr_state = state.qr_login_state
    if qr_state and qr_state.qr_image_base64:
        return f"微信登录中，二维码已生成（状态: {qr_state.status}）"
    return "微信未登录，需要启动二维码登录流程"


# ============================================================
# 前端 API（通过 exec 桥梁调用）
# ============================================================

async def _api_qr_start():
    bot = get_wechat_bot()
    state = await bot.qr_login_start()
    qr_image = ""
    if state.qr_data_url:
        if state.qr_data_url.startswith("data:image/"):
            qr_image = state.qr_data_url
        else:
            try:
                import qrcode
                from io import BytesIO
                import base64
                img = qrcode.make(state.qr_data_url)
                buf = BytesIO()
                img.save(buf, format="PNG")
                qr_image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:
                qr_image = state.qr_data_url
    elif state.qrcode:
        try:
            import qrcode
            from io import BytesIO
            import base64
            img = qrcode.make(state.qrcode)
            buf = BytesIO()
            img.save(buf, format="PNG")
            qr_image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass
    return {
        "status": state.status, "message": state.message,
        "qr_data_url": qr_image, "session_key": state.session_key,
    }


async def _api_qr_status():
    bot = get_wechat_bot()
    state = await bot.qr_login_get_status()
    return {
        "active": state.active, "completed": state.completed,
        "status": state.status, "message": state.message,
        "bot_token": state.bot_token if state.completed else "",
        "ilink_bot_id": state.ilink_bot_id if state.completed else "",
        "ilink_user_id": state.ilink_user_id if state.completed else "",
        "base_url": state.base_url if state.completed else "",
        "configured": bot.state.configured,
        "token_invalid": bot.state.token_invalid,
    }


async def _api_apply_token():
    bot = get_wechat_bot()
    ok = await bot.apply_qr_token_and_start()
    return {"ok": ok}


async def _api_qr_cancel():
    bot = get_wechat_bot()
    await bot.qr_login_cancel()


async def _api_bindings():
    mgr = get_wechat_binding_mgr()
    return [vars(b) for b in mgr.get_all_bindings()]


async def _api_unbind(device_key: str):
    mgr = get_wechat_binding_mgr()
    ok = mgr.unbind(device_key)
    return {"ok": ok}


frontend_api = {
    "qr_start": _api_qr_start,
    "qr_status": _api_qr_status,
    "apply_token": _api_apply_token,
    "qr_cancel": _api_qr_cancel,
    "bindings": _api_bindings,
    "unbind": _api_unbind,
}