/**
 * board_templates.h - 板型配置模板（1000+ 板型架构）
 *
 * 设计理念：
 * - 将公共配置提取为宏，板型定义只需 override 差异字段
 * - 利用 C99 指定初始化器的 GCC 扩展：后出现的字段赋值覆盖前面的
 * - 1000 个板型从 ~80,000 行配置缩减到 ~15,000 行
 *
 * 使用方法：
 *   #include "boards/defs/board_templates.h"
 *
 *   static const board_config_t BOARD_CONFIG = {
 *       .name = "my_board",
 *       .bin_id = "...",
 *       BOARD_BASE_ESP32S3(0),                   // 唤醒 + 音频
 *       BOARD_DISPLAY_ST7789_240(9, 13, 38, 39), // 显示
 *       BOARD_SERVICE_SELF_HOSTED(),             // 服务模式
 *       BOARD_EXTRAS_NONE(),                     // 扩展组件（必须放最后）
 *   };
 *
 * 自定义 ES8311 引脚：
 *   #define ES8311_CFG_CUSTOM
 *   static const es8311_config_t ES8311_CFG = { ... };
 *   #include "boards/defs/board_templates.h"
 *   // BOARD_AUDIO_ES8311_CUSTOM() 使用自定义 ES8311_CFG
 *
 * 注意：
 *   C++ 指定初始化器要求字段按结构体声明顺序赋值（-Werror=missing-field-initializers）。
 *   且禁止同一字段重复赋值（-Werror=override-init）。
 *   宏展开顺序：BASE（唤醒+音频）→ DISPLAY → SERVICE → EXTRAS，与结构体字段顺序一致。
 */
#pragma once

#include "boards/board_interface.h"
#include "boards/extras/extras_led.h"  // BOARD_EXTRAS_LED 组件接口

// ==================== ES8311 默认配置 ====================

#ifdef CONFIG_AUDIO_CODEC_ES8311
#ifndef ES8311_CFG_CUSTOM
static const es8311_config_t ES8311_CFG = {
    .i2c_port  = 0,
    .i2c_sda   = 41,
    .i2c_scl   = 42,
    .i2c_addr  = 0x18,
    .pa_pin    = -1,        // NS4150B 常通，无外部 PA GPIO
    .mclk_pin  = 5,         // 对齐 xiaozhi xingzhi-metal-1.54-wifi
    .mclk_freq = 4096000,   // 16000 * 256 (对齐 xiaozhi)
};
#endif
#endif

// ==================== 音频配置宏 ====================

/**
 * ES8311 全双工音频（BCLK/WS 共享，默认引脚）
 * 麦克风和扬声器共用同一 I2S 总线
 */
#ifdef CONFIG_AUDIO_CODEC_ES8311
#define BOARD_AUDIO_ES8311_DEFAULT() \
    .mic_i2s_bck  = 6,  \
    .mic_i2s_ws   = 4,  \
    .mic_i2s_data = 17, \
    .spk_i2s_bck  = 6,  \
    .spk_i2s_ws   = 4,  \
    .spk_i2s_data = 15, \
    .audio_codec = AUDIO_CODEC_ES8311, \
    .i2s_full_duplex = true, \
    .es8311_cfg = &ES8311_CFG
#else
#define BOARD_AUDIO_ES8311_DEFAULT() \
    .mic_i2s_bck  = 4, \
    .mic_i2s_ws   = 5, \
    .mic_i2s_data = 6, \
    .spk_i2s_bck  = 16, \
    .spk_i2s_ws   = 17, \
    .spk_i2s_data = 15, \
    .audio_codec = AUDIO_CODEC_NONE, \
    .i2s_full_duplex = false, \
    .es8311_cfg = NULL
#endif

/**
 * ES8311 自定义引脚（bck, ws, data_tx, data_rx, es8311_cfg_ptr）
 * 用于引脚与默认不同的板型
 */
#define BOARD_AUDIO_ES8311_CUSTOM(bck, ws, tx, rx, cfg_ptr) \
    .mic_i2s_bck  = bck, \
    .mic_i2s_ws   = ws, \
    .mic_i2s_data = rx, \
    .spk_i2s_bck  = bck, \
    .spk_i2s_ws   = ws, \
    .spk_i2s_data = tx, \
    .audio_codec = AUDIO_CODEC_ES8311, \
    .i2s_full_duplex = true, \
    .es8311_cfg = cfg_ptr

/**
 * I2S 直连音频（INMP441 + MAX98357A，独立总线）
 */
#define BOARD_AUDIO_I2S_DIRECT(mic_bck, mic_ws, mic_d, spk_bck, spk_ws, spk_d) \
    .mic_i2s_bck  = mic_bck, \
    .mic_i2s_ws   = mic_ws, \
    .mic_i2s_data = mic_d, \
    .spk_i2s_bck  = spk_bck, \
    .spk_i2s_ws   = spk_ws, \
    .spk_i2s_data = spk_d, \
    .audio_codec = AUDIO_CODEC_NONE, \
    .i2s_full_duplex = false, \
    .es8311_cfg = NULL

// ==================== 显示配置宏 ====================

/** 无屏幕（串口输出） */
#define BOARD_DISPLAY_NONE() \
    .display_type     = DISPLAY_TYPE_NONE, \
    .display_width    = 0, \
    .display_height   = 0, \
    .display_spi_host = SPI_HOST_UNUSED, \
    .display_spi_cs   = -1, \
    .display_spi_dc   = -1, \
    .display_spi_clk  = -1, \
    .display_spi_mosi = -1, \
    .display_rst      = -1, \
    .display_bl       = -1, \
    .display_i2c_sda  = -1, \
    .display_i2c_scl  = -1, \
    .display_i2c_addr = 0

/** ST7789 SPI LCD 240x240（常见 1.54 寸屏），无背光控制（BCLK 需接 3V3 常亮） */
#define BOARD_DISPLAY_ST7789_240(cs, dc, clk, mosi) \
    BOARD_DISPLAY_ST7789_240_BL(cs, dc, clk, mosi, -1)

/** ST7789 SPI LCD 240x240 + 背光控制（LEDC PWM，亮度 0-100） */
#define BOARD_DISPLAY_ST7789_240_BL(cs, dc, clk, mosi, bl) \
    .display_type     = DISPLAY_TYPE_LCD_ST7789, \
    .display_width    = 240, \
    .display_height   = 240, \
    .display_spi_host = SPI_HOST_2, \
    .display_spi_cs   = cs, \
    .display_spi_dc   = dc, \
    .display_spi_clk  = clk, \
    .display_spi_mosi = mosi, \
    .display_rst      = -1, \
    .display_bl       = bl, \
    .display_i2c_sda  = -1, \
    .display_i2c_scl  = -1, \
    .display_i2c_addr = 0

/** ILI9341 SPI LCD 320x240（常见 2.4/2.8 寸屏） */
#define BOARD_DISPLAY_ILI9341_320X240(cs, dc, clk, mosi) \
    .display_type     = DISPLAY_TYPE_LCD_ILI9341, \
    .display_width    = 320, \
    .display_height   = 240, \
    .display_spi_host = SPI_HOST_2, \
    .display_spi_cs   = cs, \
    .display_spi_dc   = dc, \
    .display_spi_clk  = clk, \
    .display_spi_mosi = mosi, \
    .display_rst      = -1, \
    .display_bl       = -1, \
    .display_i2c_sda  = -1, \
    .display_i2c_scl  = -1, \
    .display_i2c_addr = 0

/** SSD1306 I2C OLED 128x64 */
#define BOARD_DISPLAY_SSD1306_128X64(sda, scl) \
    .display_type     = DISPLAY_TYPE_OLED_SSD1306, \
    .display_width    = 128, \
    .display_height   = 64, \
    .display_spi_host = SPI_HOST_UNUSED, \
    .display_spi_cs   = -1, \
    .display_spi_dc   = -1, \
    .display_spi_clk  = -1, \
    .display_spi_mosi = -1, \
    .display_rst      = -1, \
    .display_bl       = -1, \
    .display_i2c_sda  = sda, \
    .display_i2c_scl  = scl, \
    .display_i2c_addr = 0x3C

// ==================== 服务模式宏 ====================

/** 自托管服务（默认请求用户自己的服务端） */
#define BOARD_SERVICE_SELF_HOSTED() \
    .official_service    = false, \
    .emotion_builtin_only = false

/** ESP-AI 官方服务（node.espai.fun + 内置表情） */
#define BOARD_SERVICE_OFFICIAL() \
    .official_service    = true, \
    .emotion_builtin_only = true

// ==================== 扩展组件宏 ====================

/** 无扩展组件（触摸屏/LED/传感器等） */
#define BOARD_EXTRAS_NONE() \
    .extras = NULL

/**
 * 状态 LED 扩展组件（extras_led，首个真实组件示例）
 * 服务端指令: led_set / led_get；事件: 唤醒时双闪两次
 *
 * @param gpio       LED 引脚
 * @param active_low true: 低电平点亮
 *
 * 多组件挂载示例（数组逗号分隔，NULL 结尾）：
 *   .extras = (const board_extra_t *const[]){ &xxx_component, NULL }
 */
#define BOARD_EXTRAS_LED(gpio_, active_low_) \
    .extras = (const board_extra_t *const[]){ \
        &(const board_extra_t){ \
            .type = "led", \
            .config = &(const led_extra_config_t){ .gpio = (gpio_), .active_low = (active_low_) }, \
            .init = extras_led_init, \
            .deinit = extras_led_deinit, \
            .handle_command = extras_led_command, \
            .on_event = extras_led_on_event }, \
        NULL }

// ==================== 基模板 ====================
// 注意：C++ 指定初始化器要求按结构体声明顺序赋值，且禁止重复赋值。
// 宏展开顺序必须为：BASE → DISPLAY → SERVICE → EXTRAS
// i2s_full_duplex / es8311_cfg 已在结构体中移至 audio_codec 之后，
// 因此 BOARD_AUDIO_* 宏可安全地在 BASE 中展开。

/**
 * ESP32-S3 基模板：唤醒按钮 + 默认音频
 * 不包含显示、服务模式、扩展组件，板型定义中必须显式指定。
 *
 * @param wake_gpio 唤醒按钮 GPIO 编号（-1 表示无按钮唤醒）
 *
 * 使用示例：
 *   static const board_config_t BOARD_CONFIG = {
 *       .name = "my_board",
 *       .bin_id = "...",
 *       BOARD_BASE_ESP32S3(0),
 *       BOARD_DISPLAY_ST7789_240(9, 13, 38, 39),
 *       BOARD_SERVICE_SELF_HOSTED(),
 *       BOARD_EXTRAS_NONE(),
 *   };
 */
#define BOARD_BASE_ESP32S3(wake_gpio) \
    .wake_button_gpio = wake_gpio, \
    BOARD_AUDIO_ES8311_DEFAULT()

/**
 * ESP32-C3 基模板：唤醒按钮 + 默认音频（无 PSRAM，音频/任务已做兼容）
 * 注意：C3 只有 I2S_NUM_0，音频只能用 ES8311 全双工方案
 * （I2S 直连方案依赖 I2S_NUM_1，C3 上不可用，选择 I2S 直连无法编译）。
 *
 * 使用示例：
 *   static const board_config_t BOARD_CONFIG = {
 *       .name = "esp32c3_supermini",
 *       .bin_id = "...",
 *       BOARD_BASE_ESP32C3(9),
 *       BOARD_DISPLAY_NONE(),
 *       BOARD_SERVICE_SELF_HOSTED(),
 *       BOARD_EXTRAS_NONE(),
 *   };
 */
#define BOARD_BASE_ESP32C3(wake_gpio) \
    .wake_button_gpio = wake_gpio, \
    BOARD_AUDIO_ES8311_DEFAULT()
