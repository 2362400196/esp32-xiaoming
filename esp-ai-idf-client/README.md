# ESP-AI IDF Client

基于 ESP-IDF 的 ESP-AI 语音助手客户端实现，支持 **BLE 配网 + 语音唤醒 + TTS 播报 + 屏幕显示**。

## 当前状态

- ✅ BLE 蓝牙配网（NimBLE）
- ✅ WiFi 连接（自动重连）
- ✅ WebSocket 通信（支持 ws/wss）
- ✅ I2S 音频输入（麦克风）
- ✅ I2S 音频输出（喇叭）
- ✅ 语音唤醒（WakeNet 9，hilexin 模型）
- ✅ TFT 屏幕显示（LVGL）
- ✅ 表情动画（GIF 解码）
- ✅ OTA 远程升级
- ✅ Lua 脚本执行
- ✅ 设备绑定与远程唤醒

## 硬件连接

### I2S 麦克风（INMP441）

| 引脚 | GPIO |
|------|------|
| BCK  | 4    |
| WS   | 5    |
| DATA | 6    |

### I2S 喇叭（MAX98357）

| 引脚 | GPIO |
|------|------|
| BCK  | 16   |
| WS   | 17   |
| DATA | 15   |

## 快速开始

### 1. 编译环境

安装 [ESP-IDF v6.0](https://docs.espressif.com/projects/esp-idf/zh_CN/v6.0.2/esp32s3/get-started/) 后，打开 **ESP-IDF 6.0 CMD** 命令行。

### 2. 编译

```cmd
cd 项目目录
idf.py set-target esp32s3
idf.py build
```

### 3. 烧录

首次烧录需要同时烧录分区数据和唤醒词模型：

```cmd
idf.py -p COMx flash
idf.py -p COMx write_partition --partition-name model --input build/srmodels/srmodels.bin
```

或使用合并固件（推荐发给别人）：

```cmd
esptool.py --chip esp32s3 merge_bin -o merged_firmware.bin ^
  0x0 build/bootloader/bootloader.bin ^
  0x8000 build/partition_table/partition-table.bin ^
  0xd000 build/ota_data_initial.bin ^
  0x10000 build/srmodels/srmodels.bin ^
  0x100000 build/esp-ai-idf-client.bin

esptool.py --chip esp32s3 -p COMx write_flash 0x0 merged_firmware.bin
```

### 4. 配网

烧录后首次启动，设备会进入 **BLE 蓝牙配网模式**。使用手机 App 扫描并发送 WiFi 和服务器配置即可。

## BLE 蓝牙配网

- 使用 NimBLE 协议栈
- 广播名称格式：`ESP-AI:XXXX`（XXXX 为 MAC 后 4 位）
- UUID：Service=`0xBAAD`，Characteristic=`0xF00D`
- 数据格式：JSON 键值对，以 `--END--` 标记结束
- 支持 AP 热点配网（HTTP 页面）作为备选

## WebSocket 通信

与服务端通过 WebSocket 保持长连接：

| 服务器协议 | 设备连接 | 说明 |
|-----------|:-------:|------|
| HTTP | `ws://` | 明文连接 |
| HTTPS | `wss://` | TLS 加密，内置 CA 证书验证 |

连接地址由配网数据中的 `ext4`（协议）、`ext5`（地址）、`ext6`（端口）字段自动拼接。

## 语音唤醒

- 使用 ESP-SR 的 WakeNet 9（hilexin 模型）
- 5 个唤醒词：`小爱同学 / 小迪同学 / 天猫精灵 / 你好小微 / Hi Lexin`
- 模型存放在 `model` 分区，编译后生成于 `build/srmodels/srmodels.bin`

## 项目结构

```
esp-ai-idf-client/
├── CMakeLists.txt              # 项目 CMake 配置
├── sdkconfig.defaults          # 默认 SDK 配置
├── sdkconfig                   # 当前 SDK 配置
├── partitions.csv              # 分区表
├── README.md                   # 本文件
├── main/
│   ├── CMakeLists.txt          # 组件 CMake 配置
│   ├── config.h                # 默认配置项
│   ├── main.c                  # 主程序入口
│   ├── wifi.c                  # WiFi 连接 + 配网调度
│   ├── websocket.c             # WebSocket 通信
│   ├── provisioning.c          # BLE 配网（NimBLE）
│   ├── provisioning_page.h     # AP 配网页面（HTML 内联）
│   ├── audio.c                 # I2S 音频播放
│   ├── display.c               # TFT 屏幕显示
│   ├── wakeup.c                # 语音唤醒
│   ├── ota_update.c            # OTA 远程升级
│   └── commands/               # 服务端指令处理
│       ├── command_registry.h  # 指令注册框架
│       ├── callback_commands.c # 回调指令
│       ├── audio_commands.c    # 音频控制指令
│       ├── bind_commands.c     # 设备绑定指令
│       ├── config_commands.c   # 远程配置更新指令
│       ├── display_commands.c  # 显示控制指令
│       ├── lua_commands.c      # Lua 脚本指令
│       ├── lyric_commands.c    # 歌词显示指令
│       └── volume_commands.c   # 音量控制指令
└── components/                 # 板级支持包
    └── esp32s3_breadboard_1_54_lcd/   # 1.54寸 LCD 板级定义
```

## 常用指令（服务器下发）

| command_id | 说明 |
|-----------|------|
| `on_iat_cb` | 语音识别文本回调 |
| `play_audio` | 播放 TTS 音频 |
| `set_volume` | 设置音量 |
| `update_config` | 远程更新配置 |
| `show_bind_code` | 显示绑定码 |
| `execute_lua` | 执行 Lua 脚本 |
| `ota_update` | 远程升级固件 |

## 协议说明

### 文本消息

```json
{
  "type": "消息类型",
  "data": "..."
}
```

### 二进制音频帧

前 6 字节头部 + 音频数据：
- 字节 0-3：会话 ID
- 字节 4-5：状态码
- 字节 6+：音频数据（MP3/PCM）

## 安全须知

当前固件为兼容 ESP-AI 官方客户端协议，存在以下明文传输行为，**不适合在不可信网络中使用**：

1. **设备注册与服务器查询走 HTTP**：`register_device` 会把 WiFi 明文密码和 api_key 通过 `http://api.espai.fun/devices/add` 发送；官方服务器节点查询同样走 HTTP。
2. **官方节点使用 ws:// 无 TLS**：对话内容与音频全程明文。
3. **证书 CN 校验被跳过**：`websocket_init` 中 `skip_cert_common_name_check = true`（开发阶段遗留）。

如需对外分发或生产部署，建议：
- 自建 esp-ai-server 并使用 `wss://`（配网时 ext4 填 `https`）+ 完整证书校验（把 `skip_cert_common_name_check` 改为 `false`）；
- 评估是否必须向官方平台上报 WiFi 凭据。

## 许可证

MIT License
