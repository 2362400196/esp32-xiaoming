# 编译固件

本教程从零开始，手把手教你搭建 ESP-IDF 开发环境、下载源码、编译烧录 IDF 客户端固件。

开源地址：[https://gitee.com/zhuxiaohuaqn/esp-ai-idf-client](https://gitee.com/zhuxiaohuaqn/esp-ai-idf-client)

---

### 1. 下载源码

打开终端（Windows 推荐用 PowerShell，macOS/Linux 用 Terminal），执行：

```bash
git clone https://gitee.com/zhuxiaohuaqn/esp-ai-idf-client.git
cd esp-ai-idf-client
```

下载完成后，目录结构如下：

```
esp-ai-idf-client/
├── main/                  # 核心代码
├── managed_components/    # 依赖组件
├── sdkconfig.defaults     # 默认配置
├── CMakeLists.txt         # 构建文件
└── partitions.csv         # 分区表
```

### 2. 安装 ESP-IDF 环境

客户端基于 **ESP-IDF v6.0.x** 开发（实际使用 6.0.2 编译，工具链 GCC 15.2.0 / esp-15.2.0_20251204），你需要先安装 ESP-IDF 工具链。

#### Windows 安装

1. 下载乐鑫官方 [ESP-IDF 一键安装工具](https://dl.espressif.cn/dl/esp-idf/)
2. 运行安装程序，**务必选择版本 `v6.0.x`（如 6.0.2）**，安装路径建议默认 (`C:\Espressif`)
3. 安装程序会自动下载 ESP-IDF、Python、交叉编译工具链等所有依赖，**全程约 10-20 分钟**
4. 安装完成后，开始菜单会出现 `ESP-IDF 6.0 PowerShell`（推荐使用）和 `ESP-IDF 6.0 CMD`

> **Windows 注意事项**：安装路径不要包含中文或空格，否则可能导致编译失败。

#### macOS / Linux 安装

```bash
# 下载 ESP-IDF v6.0.x（以 v6.0.2 为例）
git clone -b v6.0.2 --recursive https://github.com/espressif/esp-idf.git $HOME/esp/esp-idf

# 安装依赖
cd $HOME/esp/esp-idf
./install.sh esp32s3

# 设置环境变量（每次打开新终端都需要执行）
. $HOME/esp/esp-idf/export.sh
```

> **macOS 注意事项**：如果提示 `python3` 未找到，先安装 `brew install python3`。

#### 验证环境

打开 ESP-IDF 终端工具，运行：

```bash
idf.py --version
```

如果看到版本号输出，说明环境安装成功。

### 3. 编译固件

在 ESP-IDF 终端中，进入源码目录，执行编译：

```bash
cd esp-ai-idf-client
idf.py build
```

编译过程约 **2-5 分钟**，终端会实时显示进度。第一次编译会下载并编译所有依赖组件。

编译成功后，终端末尾会显示：

```
Project build complete. To flash, run:
 idf.py flash
```

生成的固件文件位于 `build/` 目录下：

| 文件 | 路径 | 说明 |
|------|------|------|
| 引导加载程序 | `build/bootloader/bootloader.bin` | 芯片上电后最先运行 |
| 分区表 | `build/partition_table/partition-table.bin` | 存储布局：固件区、模型区等 |
| 应用固件 | `build/esp-ai-idf-client.bin` | 核心程序 |
| 语音模型 | `build/srmodels/srmodels.bin` | 唤醒词识别模型 |

> **新手常见问题**：如果编译到一半报错 `ccache not found`，忽略即可，不影响编译。

### 3.1 一键生成全量固件与 OTA 固件

项目根目录提供 `build_firmware.py` 脚本，一次编译同时产出**两种固件**：

| 产物 | 文件名 | 用途 |
|------|--------|------|
| OTA 升级固件 | `esp32s3-xiaoming-{commit}.bin` | 纯 app 二进制，用于服务端 OTA 升级下发 |
| 全量固件 | `esp32s3-xiaoming-{commit}-flash-all.bin` | 合并 bootloader + 分区表 + OTA 初始数据 + 唤醒词模型 + app，用于整片烧录 |

`{commit}` 为当前 git 短提交号，自动获取，便于区分版本。

#### 用法

```bash
python build_firmware.py                 # 编译 + 打包
python build_firmware.py --no-build      # 只打包（编译已完成时）
python build_firmware.py --target esp32c3   # 编译 C3 板
python build_firmware.py --name myboard     # 自定义固件名
python build_firmware.py --out dist         # 自定义输出目录
```

#### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--target` | 从 `sdkconfig` 自动识别 | 目标芯片，支持 `esp32s3` / `esp32c3` |
| `--name` | `xiaoming` | 固件名称，输出为 `{chip}-{name}-{commit}.bin` |
| `--out` | `dist` | 输出目录 |
| `--no-build` | 关闭 | 跳过编译，只打包已构建的产物 |

#### 说明

- 脚本自动配置 ESP-IDF 6.0.2 编译环境（与 `build.ps1` 一致），无需手动激活环境。
- OTA 分区上限为 **6MB**，app 固件超过该大小会告警（OTA 升级可能写失败）。
- ESP32-C3 为工厂单槽分区，合并布局与 S3 不同，脚本已内置支持。
- 合并时若某个文件缺失会自动跳过并告警，不会中断。

### 4. 烧录固件

#### 4.1 连接硬件

1. 用 **USB 数据线**（建议用质量好的数据线，劣质线可能导致烧录失败）连接 ESP32-S3 开发板到电脑
2. Windows 打开 **设备管理器** → `端口 (COM 和 LPT)`，查看新增的 COM 端口号（如 `COM3`）
3. macOS / Linux 使用 `ls /dev/tty*` 查看（通常是 `/dev/ttyUSB0` 或 `/dev/ttyACM0`）

#### 4.2 一键烧录

```bash
# Windows
idf.py -p COM3 flash monitor

# macOS / Linux
idf.py -p /dev/ttyUSB0 flash monitor
```

参数说明：
- `-p COM3` — 指定串口端口号，根据实际修改
- `flash` — 自动烧录 bootloader、分区表、otadata、语音模型、应用 **全部 5 个文件**
- `monitor` — 烧录完成后自动打开串口监视器，查看设备启动日志

#### 4.3 烧录成功标志

终端输出类似以下内容，说明烧录成功：

```
Hash of data verified.
...
Leaving...
Hard resetting via RTS pin...
Done
```

随后 `monitor` 会自动连接，设备重启后会显示启动日志：

```
I (29) boot: ESP-IDF v6.0.2
I (35) boot: 2nd stage bootloader
...
I (1219) main_task: Started on CPU0
I (1254) cmd_lyric: 歌词指令注册完成
```

#### 4.4 进入下载模式（如果烧录失败）

如果烧录失败提示 `A fatal error occurred: Failed to connect to ESP32-S3`，说明芯片没有进入下载模式。**手动进入下载模式**：

1. 按住开发板上的 **BOOT / IO0** 按钮不松开
2. 按住的同时，短按 **RESET / EN** 按钮（约 0.5 秒）
3. 松开 BOOT 按钮
4. 重新执行烧录命令

> 多数 ESP32-S3 开发板支持自动下载电路，不需要手动按。如果出现连接失败，先换根数据线试试。

#### 4.5 退出监视器

串口监视器运行后按 **`Ctrl + ]`** 退出。

### 5. 配置 WiFi

烧录完成后，设备会进入配网模式。用手机 App 或小程序扫描屏幕上的二维码进行 BLE 配网。配网成功后，设备会自动连接 WiFi 到服务端。

> 如果你需要修改 WiFi 或其他配置，参考服务端文档。

### 6. 切换板型

项目内置 3 种板型(esp32s3_breadboard / esp32s3_breadboard_1.54_lcd / esp32s3_breadboard_1.54_lcd_official),`sdkconfig.defaults` 默认选择 **1.54 LCD 普通板**。切换方法、板型差异与选择建议见独立文档:

👉 [**切换开发板**](/dev/client/idf-board-switch)

```bash
idf.py menuconfig   # 选择开发板型号
idf.py reconfigure
idf.py build
```

### 7. 切换唤醒词

默认唤醒词是 **小明同学**。当前版本**不支持**通过 `menuconfig` 直接切换唤醒词：

- `main/config.h` 中定义了 `CONFIG_WAKE_WORD_XIAOMING` / `CONFIG_WAKE_WORD_NIHAOWEN` / `CONFIG_WAKE_WORD_HIJESON` / `CONFIG_WAKE_WORD_NIHAOXIAOZHI` 四个宏，但项目 **Kconfig / sdkconfig 中并未定义这些宏**，因此 `#if CONFIG_WAKE_WORD_XXX` 判断恒为假，实际始终走"小明同学"分支。
- menuconfig 中 `Component config → ESP Speech Recognition → Load Multiple Wake Words (WakeNet9)` 里可勾选的只是 esp-sr 组件自带的 `SR_WN_*` 模型选项，与 `config.h` 的唤醒词宏**不联动**。

如需切换唤醒词，需手动修改 `main/config.h` 中的 `CONFIG_WAKE_WORD_*` 宏（启用目标唤醒词、禁用其他），并在 menuconfig 中同时勾选 esp-sr 对应的 `SR_WN_*` 模型，然后**全量编译**：

```bash
idf.py clean
idf.py build
```

::: warning 重要
切换唤醒词后语音模型会改变，必须全量编译，且烧录时需重新写入 `srmodels.bin`（model 分区）。
:::

### 8. 更新固件

当源码有更新时，拉取最新代码重新编译：

```bash
cd esp-ai-idf-client
git pull
idf.py build
```

如果拉取后编译报错，可能需要清理缓存：

```bash
idf.py clean
idf.py build
```

### 下载预编译固件

如果你不想自己搭建环境编译，可以直接下载预编译好的固件：

[📥 下载 esp-ai-idf-client-firmware.bin](/firmware/esp-ai-idf-client-firmware.bin)

::: warning 完整烧录需要 5 个文件
仅烧录应用文件无法启动，IDF 固件需要同时烧录 bootloader、分区表、otadata、应用和语音模型 5 个文件。建议使用 `idf.py flash` 或乐鑫 Flash Download Tool 完整烧录。
:::
