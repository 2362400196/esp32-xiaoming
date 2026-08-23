"""Plugin SDK 包 - 为插件提供统一的设备控制、HTTP 请求、数据持久化等能力。

每个子模块按功能拆分，插件开发者可按需导入：

    from src.use_cases.sdk.http import http_request, http_get_json
    from src.use_cases.sdk.device import send_device_command, request_device_result
    from src.use_cases.sdk.music import play_music_url
    from src.use_cases.sdk.io import gpio_write, gpio_read
    from src.use_cases.sdk.storage import plugin_data_read, kv_get
    from src.use_cases.sdk.services import llm_chat, tts_synthesize
    from src.use_cases.sdk.utils import json_dumps, get_device_key
"""