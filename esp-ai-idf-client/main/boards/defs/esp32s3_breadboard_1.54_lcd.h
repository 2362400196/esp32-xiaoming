/**
 * breadboard_1.54_lcd 板型定义
 *
 * ESP32-S3 面包板 + 1.54寸 ST7789 LCD (240x240)
 *
 * 音频方案由 Kconfig → 音频编解码器 选择（与板型独立）：
 *   - I2S 直连：INMP441 数字麦 + MAX98357 数字功放
 *   - ES8311：ES8311 编解码器 + NS4150B 功放（全双工 I2S）
 *
 * 背光：display_bl = GPIO16（LEDC PWM 调亮度，0-100%），
 * 屏幕 BCLK 需接到 GPIO16（不再接 3V3）；服务端 set_brightness 指令可调。
 *
 * 继承 BOARD_BASE_ESP32S3 基模板，仅覆盖显示配置
 */
#pragma once

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "breadboard_1.54_lcd",
    .description = "ESP32-S3 面包板 (1.54寸 LCD)",
    .bin_id      = "5d47bb925ea440b3b615f4ed6e4d2263",

    BOARD_BASE_ESP32S3(0),
    BOARD_DISPLAY_ST7789_240_BL(9, 13, 38, 39, 16),   // cs, dc, clk, mosi, 背光 GPIO16
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
