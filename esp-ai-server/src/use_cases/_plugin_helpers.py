"""
插件 SDK 统一导出层（兼容旧导入路径）

被 src/plugins/ 下各插件共享。以下划线前缀命名，auto_discover 扫描 use_cases
目录时会跳过，避免被当作工具模块加载。

所有功能已按领域拆分到 src/use_cases/sdk/ 子模块中，本文件仅做统一导出，
保持旧版 from src.use_cases._plugin_helpers import xxx 的兼容性。

新代码推荐直接导入 sdk 子模块：
    from src.use_cases.sdk.tools import tool, StopPipeline
    from src.use_cases.sdk.http import http_request, http_get_json
    from src.use_cases.sdk.device import send_device_command, request_device_result
    from src.use_cases.sdk.music import play_music_url
    from src.use_cases.sdk.io import gpio_write, gpio_read
    from src.use_cases.sdk.storage import plugin_data_read, kv_get
    from src.use_cases.sdk.services import llm_chat, tts_synthesize
    from src.use_cases.sdk.utils import json_dumps, get_device_key
"""

# ════════════════════════════════════════════════════════════
# 工具注册（插件开发的第一入口，惰性 re-export 自 tools_system）
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