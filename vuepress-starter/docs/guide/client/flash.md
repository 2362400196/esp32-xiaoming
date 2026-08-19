# 烧录固件

## 下载固件

[📥 点击下载 esp-ai-idf-client-firmware.bin](/firmware/esp-ai-idf-client-firmware.bin)

::: tip 什么是 IDF 客户端？
基于 ESP-IDF 原生框架（ESP-IDF v6.0），固件小、指令系统模块化，支持多板型，适合深度定制。
:::

## 烧录步骤

### 1. 下载烧录工具

下载 [ESP32 Flash Download Tool](https://www.espressif.com/en/support/download/other-tools)（乐鑫官方工具）。

### 2. 进入下载模式

- 按住 **BOOT** 按钮
- 短按 **RESET** 按钮
- 松开 **BOOT** 按钮

### 3. 配置并烧录

打开 Flash Download Tool，按以下配置：

| 参数 | 值 |
|------|-----|
| 芯片 | ESP32-S3 |
| Flash | 16MB |
| 模式 | QIO |
| 波特率 | 921600 |
| 地址 | 0x0 |

选择下载的 `.bin` 文件，点击 **START** 开始烧录。

::: warning IDF 客户端烧录注意事项
IDF 客户端固件包含 bootloader、分区表、应用和语音模型等多部分。如果使用 ESP32 Flash Download Tool，需要分别烧录以下文件（地址不同）：

| 文件 | 烧录地址 | 说明 |
|------|----------|------|
| `bootloader.bin` | `0x0` | 引导加载器 |
| `partition-table.bin` | `0x8000` | 分区表 |
| `otadata.bin` | `0xd000` | OTA 分区选择数据（OTA 分区表场景需烧录，决定从 ota_0/ota_1 启动） |
| `esp-ai-idf-client.bin` | `0x100000` | 应用程序（ota_0 分区起始） |
| `srmodels.bin` | `0x10000` | 语音唤醒模型（model 分区起始） |

这些文件位于 `esp-ai-idf-client/build/` 目录中。

> **地址切勿混淆**：`0x10000` 是 model 分区（存放唤醒词模型），`0x100000` 才是 ota_0 分区（存放应用程序）。两者差一个 0，烧错地址会导致设备无法启动或唤醒失效。

> **优先使用 idf.py 烧录**：本项目使用 OTA 分区表（含 ota_0/ota_1 双分区与 otadata），手动配置各文件地址容易出错。建议优先用 `idf.py -p COM3 flash` 一键烧录，工具会自动处理 bootloader、分区表、otadata、应用和语音模型的所有地址与分区。
:::

