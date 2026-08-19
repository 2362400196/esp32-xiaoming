# 指令扩展指南

## 快速开始

在 `commands/` 目录中创建一个新的 `.c` 文件，例如 `my_commands.c`：

```c
#include "command_registry.h"
#include "esp_log.h"

// 1. 实现处理函数
static esp_err_t cmd_my_command(cJSON *json)
{
    // 从 json 中解析 data 字段
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        ESP_LOGI("MY_CMD", "收到数据: %s", data->valuestring);
    }
    return ESP_OK;
}

// 2. 注册指令（自动注册，无需手动调用）
REGISTER_COMMAND("instruct", "my_command", cmd_my_command, "我的自定义指令");
```

重新编译即可，**无需修改任何其他文件**。

## 工作原理

1. `REGISTER_COMMAND` 宏使用 `__attribute__((constructor))`，在 `app_main` 之前自动注册指令
2. `websocket.c` 收到 `type == "instruct"` 的消息时，调用 `commands_dispatch()` 分发
3. `commands_dispatch()` 按 `command_id` 匹配已注册的处理函数
4. `CMakeLists.txt` 使用 `file(GLOB)` 自动收集 `commands/*.c`，无需手动添加源文件

## JSON 消息格式

服务端下发的指令格式：

```json
{
    "type": "instruct",
    "command_id": "my_command",
    "data": "参数值"
}
```

handler 接收完整的 JSON 对象，可自行解析任意字段：

```c
static esp_err_t cmd_handler(cJSON *json)
{
    cJSON *cmd_id = cJSON_GetObjectItem(json, "command_id");  // 指令ID
    cJSON *data    = cJSON_GetObjectItem(json, "data");        // 数据字段
    // ...
    return ESP_OK;
}
```

## 可用的 API

指令处理函数中可以调用以下模块的接口（通过 `#include "config.h"`）：

| 模块 | 接口 | 说明 |
|------|------|------|
| 音频 | `audio_set_volume(float)` | 设置音量 (0.0-1.0) |
| 音频 | `audio_get_volume(void)` | 获取当前音量 |
| 音频 | `network_audio_play(const char *url)` | 播放网络音乐 |
| 音频 | `network_audio_stop(void)` | 停止播放 |
| 显示 | `display_show_emotion(const char *)` | 切换表情 |
| 显示 | `display_show_text(const char *)` | 显示底部字幕 |
| 显示 | `display_show_status(const char *)` | 显示状态文字 |
| 显示 | `eeui_port_set_brightness(int)` | 设置屏幕亮度 (0-100) |
| IO | `hardware_io_handle_fns(cJSON *)` | 处理硬件 IO 指令 |
| WebSocket | `websocket_send_text(const char *)` | 发送消息到服务端 |

## 调试

启动时会在日志中打印所有已注册指令：

```
I cmd_registry: ========== 已注册指令列表 ==========
I cmd_registry:   1. [instruct] set_volume - 设置音量
I cmd_registry:   2. [instruct] add_volume - 增加音量
I cmd_registry:   3. [instruct] play_music - 播放网络音乐
I cmd_registry: ========== 共 N 条指令 ==========
```

## 现有指令文件

| 文件 | 指令 | 说明 |
|------|------|------|
| `command_registry.c` | - | 注册系统核心（勿改） |
| `volume_commands.c` | set_volume / add_volume / subtract_volume | 音量控制 |
| `audio_commands.c` | play_music | 网络音乐播放 |
| `display_commands.c` | set_brightness | 屏幕亮度 |
| `callback_commands.c` | on_iat_cb / on_llm_cb | 服务端回调 |

## 注意事项

- 添加新 `.c` 文件后若编译未包含，运行 `idf.py reconfigure` 重新配置
- `REGISTER_COMMAND` 宏的第一个参数必须是字符串字面量（如 `"instruct"`）
- 同一个 `command_id` 重复注册时，后注册的会被插入链表头部（先匹配）
- handler 返回 `ESP_ERR_NOT_FOUND` 以外的错误码不影响应答（始终回复 `instruct_ack`）
