# 适配自己的开发板

小明同学 IDF 客户端采用**板级包（Board Package）架构（1000+ 板型）**：**一个板型 = `boards/defs/` 下一个 `.h` 文件**，menuconfig 板型菜单和编译时选择头文件由 `gen_boards.py` 自动生成，适配新板型无需修改任何框架代码。

本文档介绍如何为你的硬件适配一个新的板型。

## 架构概述

```
main/boards/
├── board_interface.h      # 接口定义（board_config_t / board_extra_t，框架提供）
├── board.c                # 板级包核心（注册表驱动初始化，框架提供，无需修改）
├── board_select.h         # 编译时板型选择（gen_boards.py 自动生成，勿手改）
├── Kconfig.gen            # menuconfig 板型菜单（gen_boards.py 自动生成，勿手改）
├── tools/gen_boards.py    # 扫描 defs/ 生成 Kconfig.gen + board_select.h
│
├── defs/                  # ★ 板型定义（你只需在这里加文件）
│   ├── board_templates.h  # 板型配置模板宏（BASE/AUDIO/DISPLAY/SERVICE/EXTRAS）
│   ├── breadboard.h            # 面包板无屏幕
│   ├── breadboard_1.54_lcd.h   # 面包板 1.54寸 LCD
│   ├── breadboard_1.54_lcd_official.h  # 官方服务版
│   └── your_board.h            # ← 你的板型定义（新建）
└── audio_codec/es8311.c   # ES8311 编解码器驱动
```

**核心思路：**

- **一个文件定义一个板型**：`defs/<board_name>.h` 中提供一个 `BOARD_CONFIG`（`board_config_t` 实例），通过 `board_templates.h` 的宏组合公共配置，只需 override 差异字段。
- **零框架修改**：`gen_boards.py` 扫描 `defs/` 目录自动生成：
  - `Kconfig.gen` → menuconfig 里的"选择开发板型号"菜单
  - `board_select.h` → 编译时 `#include` 选中的板型定义
- **组件化配置**：音频编解码器（ES8311 / I2S 直连）、显示屏、扩展硬件（触摸/LED/传感器）都通过 `board_config_t` 字段或 `extras` 数组插拔，`board.c` 用**驱动注册表**统一初始化，新增类型无需改框架。

## 快速开始

### 第一步：创建板型定义文件

在 `main/boards/defs/` 下新建 `your_board.h`：

```c
/**
 * your_board 板型定义
 *
 * 引脚定义（示例，按你的硬件修改）：
 * | 功能         | GPIO |
 * |-------------|------|
 * | 唤醒按钮     | 0    |
 * | 麦克风 BCK   | 6    |
 * | 麦克风 WS    | 4    |
 * | 麦克风 DATA  | 17   |
 * | 喇叭 BCK     | 6    |
 * | 喇叭 WS      | 4    |
 * | 喇叭 DATA    | 15   |
 * | LCD SPI CS   | 9    |
 * | LCD SPI DC   | 13   |
 * | LCD SPI CLK  | 38   |
 * | LCD SPI MOSI | 39   |
 */
#pragma once

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "your_board",
    .description = "我的开发板",
    .bin_id      = "your_unique_bin_id_32hex",   // OTA 固件ID，全工程唯一（gen_boards 会校验）

    BOARD_BASE_ESP32S3(0),                        // 唤醒按钮 + 音频（引脚见下方说明）
    BOARD_DISPLAY_ST7789_240(9, 13, 38, 39),      // 显示（无屏幕用 BOARD_DISPLAY_NONE()）
    BOARD_SERVICE_SELF_HOSTED(),                  // 服务模式
    BOARD_EXTRAS_NONE(),                          // 扩展组件（必须放最后）
};
```

要点：

- **宏展开顺序必须固定**：`name/description/bin_id` → `BOARD_BASE_*`（音频）→ `BOARD_DISPLAY_*` → `BOARD_SERVICE_*` → `BOARD_EXTRAS_*`。这是因为 C++ 指定初始化器要求按 `board_config_t` 字段声明顺序赋值，且禁止同一字段重复赋值（`-Werror=override-init`）。
- **`bin_id` 必填且全工程唯一**：`gen_boards.py` 校验失败会直接报错。它是 OTA 升级识别板型的固件 ID（32 位十六进制字符串）。
- **可选 `@meta` 注释**：控制 Kconfig 按芯片分组显示（多芯片工程时需要）：

```c
/// @meta chip=esp32s3 vendor=espressif series=breadboard
```

### 第二步：选择音频编解码器（独立于板型）

音频方案由 `menuconfig → 音频编解码器` 独立选择，与板型解耦：

- **I2S 直连 (INMP441 + MAX98357)**：麦克风/喇叭各自独立 I2S 总线，`audio_codec = AUDIO_CODEC_NONE`
- **ES8311 (全双工 I2S)**：单 I2S 总线全双工驱动 ADC（麦克风）和 DAC（喇叭），需板型提供 `es8311_cfg`

::: danger 必须与硬件一致
音频编解码器选错会直接导致**麦克风/喇叭不工作**（例如硬件是 ES8311 却选了 I2S 直连，麦克风读取全静音、无法语音唤醒）。选择必须与实际硬件严格对应。
:::

### 第三步：重新配置并编译

```bash
idf.py reconfigure   # defs/ 变化后自动触发 gen_boards.py 重新生成 Kconfig.gen / board_select.h
idf.py menuconfig
# 选择开发板型号 → 你的板型
# 音频编解码器 → 与硬件一致
# 配网方式 / 日志级别 按需设置
idf.py build flash monitor
```

### （可选）自定义 ES8311 引脚
默认 ES8311 配置（`ES8311_CFG`）在 `board_templates.h` 中定义（I2C SDA=41/SCL=42、MCLK=5@4.096MHz）。引脚不同的板型可在你的定义文件里 override（**宏与结构体必须写在 `#include board_templates.h` 之前**）：

```c
#pragma once

#define ES8311_CFG_CUSTOM                       // 通知模板不要用默认 ES8311_CFG
static const es8311_config_t ES8311_CFG = {
    .i2c_port  = 0,
    .i2c_sda   = 41,
    .i2c_scl   = 42,
    .i2c_addr  = 0x18,
    .pa_pin    = 2,          // NS4150B PA 使能引脚
    .mclk_pin  = 5,
    .mclk_freq = 4096000,    // 16000 * 256
};

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "your_board",
    .description = "我的开发板",
    .bin_id      = "your_unique_bin_id_32hex",

    BOARD_BASE_ESP32S3(0),
    BOARD_AUDIO_ES8311_CUSTOM(6, 4, 15, 17, &ES8311_CFG),  // bck, ws, spk_tx, mic_rx, cfg
    BOARD_DISPLAY_ST7789_240(9, 13, 38, 39),
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
```

## 多芯片板型（ESP32-C3 等单核 / 无 PSRAM 芯片）

框架支持同一份代码多芯片共存（`gen_boards.py` 按 `@meta chip` 分组，Kconfig 自动加 `depends on IDF_TARGET_*`，编译哪个目标就只显示对应芯片的板型）。已内置 **ESP32-C3 SuperMini** 板型（`boards/defs/esp32c3_supermini.h`）作为参考：

```c
/// @meta chip=esp32c3 vendor=generic series=supermini
...
static const board_config_t BOARD_CONFIG = {
    .name        = "esp32c3_supermini",
    .description = "ESP32-C3 SuperMini (ES8311 全双工, 无屏)",
    .bin_id      = "...",
    BOARD_BASE_ESP32C3(9),
    BOARD_DISPLAY_NONE(),
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
```

适配其他 C3/C2 类板型时注意：

- **基模板用 `BOARD_BASE_ESP32C3()`**（`board_templates.h` 提供，内容与 S3 基模板一致）
- **音频只能用 ES8311 全双工**：C3 只有 I2S0，I2S 直连方案依赖 I2S1，在 C3 上编译不过；`menuconfig → 音频编解码器` 必须选 ES8311
- **无 PSRAM**：`board_compat.h` 自动把任务栈/大缓冲回退到内部 RAM（`BOARD_TASK_CORE_*`、`board_malloc_audio()`），核心代码无需改动
- **任务核固定已兼容**：单核芯片所有 `xTaskCreatePinnedToCore(...,1)` 自动落到 core 0
- **4MB Flash**：`sdkconfig.defaults.esp32c3` 已配置 4MB 分区表（`partitions_c3.csv`，工厂单槽，无 OTA 双槽）+ C3 默认板型
- **构建**：`idf.py set-target esp32c3` 后 `idf.py build`（会切换项目 sdkconfig 到 C3；切回 S3 用 `idf.py set-target esp32s3`）

## 板型模板宏参考

定义在 `main/boards/defs/board_templates.h`，按下面顺序组合进 `BOARD_CONFIG`。

### 基模板 + 音频

| 宏 | 说明 |
|----|------|
| `BOARD_BASE_ESP32S3(wake_gpio)` | 基模板：唤醒按钮 GPIO + 默认音频（`wake_gpio=-1` 表示无按钮） |
| `BOARD_AUDIO_ES8311_DEFAULT()` | ES8311 全双工 + 默认引脚（受 `menuconfig → 音频编解码器` 控制） |
| `BOARD_AUDIO_ES8311_CUSTOM(bck, ws, tx, rx, cfg_ptr)` | ES8311 + 自定义引脚与 `es8311_config_t` |
| `BOARD_AUDIO_I2S_DIRECT(mic_bck, mic_ws, mic_d, spk_bck, spk_ws, spk_d)` | I2S 直连（INMP441 + MAX98357），独立总线 |

### 显示

| 宏 | 说明 |
|----|------|
| `BOARD_DISPLAY_NONE()` | 无屏幕（串口输出状态） |
| `BOARD_DISPLAY_ST7789_240(cs, dc, clk, mosi)` | ST7789 SPI LCD 240x240 |
| `BOARD_DISPLAY_ILI9341_320X240(cs, dc, clk, mosi)` | ILI9341 SPI LCD 320x240 |
| `BOARD_DISPLAY_SSD1306_128X64(sda, scl)` | SSD1306 I2C OLED 128x64 |

### 服务模式

| 宏 | 说明 |
|----|------|
| `BOARD_SERVICE_SELF_HOSTED()` | 自托管服务（默认请求自己的服务端） |
| `BOARD_SERVICE_OFFICIAL()` | ESP-AI 官方服务（node.espai.fun）+ 表情只用内置资源 |

### 扩展组件

| 宏 | 说明 |
|----|------|
| `BOARD_EXTRAS_NONE()` | 无扩展组件（`extras = NULL`） |

## 扩展组件（触摸屏 / LED / 传感器等）

**1000+ 板型架构**的非核心硬件通过 `board_extra_t` 描述符插拔，无需改动 `board_config_t` 核心结构：

```c
// 实现你的组件（放在你的板型文件或独立 .c/.h 中）
static esp_err_t my_led_init(const void *cfg) { ... }        // 初始化
static esp_err_t my_led_cmd(const char *cmd, const char *args,
                            char *resp, size_t resp_len) { ... }  // 命令处理
static void my_led_event(board_event_t ev, void *data) { ... }    // 事件回调

static const board_extra_t MY_LED_EXTRA = {
    .type = "led",
    .config = &my_led_cfg,
    .init = my_led_init,
    .deinit = NULL,
    .handle_command = my_led_cmd,
    .on_event = my_led_event,
};

// 在板型定义中挂载
static const board_extra_t *const MY_EXTRAS[] = { &MY_LED_EXTRA, NULL };
```

`board_init()` 会遍历 `extras` 依次调用 `init`；运行时通过 `board_extra_dispatch()` 分发命令、`board_extra_broadcast_event()` 广播唤醒/播放/网络等事件、`board_deinit()` 逆序反初始化。三者均可为 NULL（仅需 init 的简单组件不用实现命令/事件）。

## 显示驱动

统一接口在 `main/displays/display_driver.h`，由 `board.c` 的注册表按 `display_type` 自动选择（**新增板型无需修改注册表**）：

| 驱动 | 适用场景 | 文件 |
|------|---------|------|
| `display_lcd` | SPI LCD（ST7789/ILI9341 等） | `displays/display_lcd.cpp` |
| `display_uart` | 无屏幕，串口输出状态 | `displays/display_uart.c` |
| `display_oled` | I2C OLED（需自行实现，当前回退串口） | - |

**添加新的显示驱动**（如 OLED）：

1. 在 `main/displays/` 创建 `display_oled.c`，实现 `display_driver_t` 接口
2. 提供 `const display_driver_t *display_driver_oled_get(void)` 工厂函数
3. 在 `board.c` 的 `s_display_registry` 注册表中添加条目（唯一需要改框架的地方）
4. 在 `main/CMakeLists.txt` 的 SRCS 中添加源文件

```c
// display_oled.c 示例
#include "display_driver.h"

static esp_err_t oled_init(void) { /* I2C OLED 初始化 */ }
static esp_err_t oled_show_emotion(const char *e) { /* 显示表情 */ }
static esp_err_t oled_show_status(const char *s) { /* 显示状态 */ }
static esp_err_t oled_show_text(const char *t) { /* 显示文字 */ }

static const display_driver_t s_oled_driver = {
    .name = "oled_ssd1306",
    .init = oled_init,
    .show_emotion = oled_show_emotion,
    .show_status = oled_show_status,
    .show_text = oled_show_text,
    .set_brightness = NULL,
    .show_battery = NULL,
    .clear = NULL,
    .caps = { .has_graphic = true, .has_text = true,
              .has_brightness = false, .has_battery = false },
};

const display_driver_t *display_driver_oled_get(void)
{
    return &s_oled_driver;
}
```

## 板型信息上报

固件通过 `board_get_info_json()` 向服务端上报板型能力（`{"name","bin_id","display","display_w","display_h","audio_codec"}`），服务端据此下发匹配的表情包与配置。`bin_id` 唯一性因此很关键——`gen_boards.py` 会在生成时校验重复。

## 常见问题

### Q: 如何切换不同板型？

```bash
idf.py menuconfig
# 选择开发板型号 → 选择目标板型，保存
idf.py build flash
```

### Q: 板型之间会互相影响吗？

不会。`board_select.h` 通过 `#ifdef CONFIG_BOARD_*` 只 `#include` 选中的板型，其余不参与编译。

### Q: 如何分享我的板型？

把 `boards/defs/your_board.h` 这一个文件分享即可。对方放入自己的 `defs/` 目录后 `idf.py reconfigure` 就能在菜单中看到，无需任何框架修改。

### Q: 新增板型后菜单里看不到？

`defs/` 变化后需要**重新配置**才触发 `gen_boards.py` 重新生成：

```bash
idf.py reconfigure   # 或删除 build/ 后 idf.py build
```

### Q: 音频编解码器选错了会怎样？

麦克风/喇叭不工作（例如选 I2S 直连但硬件是 ES8311，麦克风读到全静音、无法语音唤醒）。在 `menuconfig → 音频编解码器` 改回与硬件一致即可，无需改板型代码。

### Q: 如何调试引脚配置？

使用 `idf.py monitor` 查看启动日志。板型选择与音频方案会打印在 `board` 日志里：

```
I (1498) board: 初始化板级包: breadboard_1.54_lcd
I (1528) board:   音频: ES8311 编解码器 + NS4150B 功放 (全双工 I2S)
```

唤醒词运行期间每约 2.5s 打印一次麦克风诊断，`peak` 持续为 1 说明麦克风未工作：

```
I (6172) wakeup: [MIC诊断] ret=ESP_OK bytes=1024 peak=1
```

## 参考

- [board_interface.h](../../main/boards/board_interface.h) - 接口定义（`board_config_t` / `board_extra_t`）
- [board_templates.h](../../main/boards/defs/board_templates.h) - 板型配置模板宏
- [gen_boards.py](../../main/boards/tools/gen_boards.py) - 板型自动生成脚本
- [breadboard_1.54_lcd.h](../../main/boards/defs/breadboard_1.54_lcd.h) - LCD 板型定义示例
- [breadboard.h](../../main/boards/defs/breadboard.h) - 无屏板型定义示例
