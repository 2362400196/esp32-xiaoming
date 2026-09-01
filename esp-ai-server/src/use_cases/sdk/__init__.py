"""Plugin SDK 包 - 为插件提供统一的设备控制、HTTP 请求、数据持久化等能力。

每个子模块按功能拆分，插件开发者可按需导入：

    from src.use_cases.sdk.tools import tool, StopPipeline
    from src.use_cases.sdk.http import http_request, http_get_json
    from src.use_cases.sdk.device import send_device_command, request_device_result
    from src.use_cases.sdk.music import play_music_url
    from src.use_cases.sdk.io import gpio_write, gpio_read
    from src.use_cases.sdk.storage import plugin_data_read, kv_get
    from src.use_cases.sdk.services import llm_chat, tts_synthesize
    from src.use_cases.sdk.utils import json_dumps, get_device_key

════════════════════════════════════════════════════════════════════
SDK 错误约定（新代码必须遵守）
════════════════════════════════════════════════════════════════════

★ 新约定：凡是"可能失败的操作"，一律返回 ``(result, status, detail)`` 三元组：

    result: 成功时的结果数据；失败时为 None
    status: "ok" / "offline" / "timeout" / "error" / "busy"
        - ok:      成功
        - offline: 设备未连接 / 目标不存在
        - timeout: 设备未在超时时间内响应
        - error:   发送失败、权限未声明等本地错误（detail 说明原因）
        - busy:    上一次同类指令尚未完成（仅带 if_busy 判断的调用会产生）
    detail: 失败时的可读原因；成功时为空字符串

遵循新约定的 SDK 函数（推荐新插件使用）：

    sdk.device.lua_execute            (result, status, detail)
    sdk.device.get_device_state       (result, status, detail)
    sdk.device.device_command_ack     (result, status, detail)

旧约定（保留兼容，已废弃，新插件请用对应新封装替代）：

    sdk.device.request_device_result  (result, status, detail)
        → 与新约定格式一致，但要求插件传框架私有 future 属性名，
          已废弃，请改用 lua_execute / get_device_state / device_command_ack
    sdk.device.send_device_command_ack  (result, status, detail)
        → 格式一致；简单的"发完即走"场景请配合 sdk.device.send_device_command
    sdk.device.send_device_command    None=成功 / 字符串=失败原因
        → 已废弃，新插件请用 device_command_ack（需要设备确认时）
    sdk.io.gpio_write / gpio_mode / pwm_write / servo_write
                                      "ok"=成功 / 字符串=失败原因
        → 旧约定保留，暂无替代
    sdk.io.gpio_read / adc_read       int（-1=失败）
        → 旧约定保留，暂无替代
    sdk.infrastructure.speak_direct   bool
        → 已废弃（要求插件持有框架内部对象），新插件请用 speak_to_device
    sdk.infrastructure.speak_to_device bool（设备离线等返回 False）

例外（不属于元组约定）：sdk.services.llm_chat / tts_synthesize
会直接抛出异常（内部调用 AI 网关，失败即抛，由调用方捕获处理），
这是历史遗留行为，新插件调用时请自行 try/except。
"""

# ════════════════════════════════════════════════════════════
# 工具注册（插件开发的第一入口）
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.tools import tool, StopPipeline, ToolDefinition  # noqa: F401

# ════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.utils import (  # noqa: F401
    get_device_key,
    resolve_device_key,
    get_plugin_config_or_env,
    generate_uuid,
    current_timestamp,
    json_dumps,
    json_loads,
)

# ════════════════════════════════════════════════════════════
# 设备指令下发
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.device import (  # noqa: F401
    send_instruct,
    send_device_command,
    send_device_command_ack,
    request_device_result,
    lua_execute,
    get_device_state,
    device_command_ack,
    device_is_online,
    device_get_info,
)

# ════════════════════════════════════════════════════════════
# HTTP 请求
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.http import (  # noqa: F401
    http_request,
    http_get_json,
    http_stream_open,
    http_stream_read,
    http_stream_close,
)

# ════════════════════════════════════════════════════════════
# 音乐播放 SDK
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.music import (  # noqa: F401
    play_music_url,
)

# ════════════════════════════════════════════════════════════
# 设备 IO 控制
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.io import (  # noqa: F401
    gpio_mode,
    gpio_write,
    gpio_read,
    pwm_write,
    adc_read,
    servo_write,
)

# ════════════════════════════════════════════════════════════
# 数据持久化
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.storage import (  # noqa: F401
    plugin_data_read,
    plugin_data_write,
    plugin_data_list,
    plugin_data_delete,
    kv_get,
    kv_set,
    kv_delete,
    kv_list,
)

# ════════════════════════════════════════════════════════════
# AI 服务与仓库
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.services import (  # noqa: F401
    get_default_ltm_service,
    get_ltm_service,
    get_diary_repository,
    get_device_repository,
    skill_catalog_text,
    plugin_log,
    llm_chat,
    llm_generate,
    tts_synthesize,
    get_user_profile_summary,
)

# ════════════════════════════════════════════════════════════
# 计费上报（插件主动上报本轮用量）
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.billing import (  # noqa: F401
    add_asr,
    add_llm,
    add_tts,
)

# ════════════════════════════════════════════════════════════
# 安全工具（来自 infrastructure）
# ════════════════════════════════════════════════════════════
from src.infrastructure.plugin_security import mask_secret, require_permission  # noqa: F401

# ════════════════════════════════════════════════════════════
# 框架基础设施封装（插件不直接 import infrastructure）
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.infrastructure import (  # noqa: F401
    get_logger,
    get_settings,
    get_device_registry,
    speak_direct,
    speak_to_device,
    get_wechat_bot,
    get_wechat_binding_mgr,
    get_remote_config_provider,
)

# ════════════════════════════════════════════════════════════
# WebSocket 操作 SDK（沙箱插件通过此 SDK 管理 WS 连接）
# ════════════════════════════════════════════════════════════
from src.use_cases.sdk.ws import (  # noqa: F401
    ws_connect,
    ws_send,
    ws_recv,
    ws_close,
)
