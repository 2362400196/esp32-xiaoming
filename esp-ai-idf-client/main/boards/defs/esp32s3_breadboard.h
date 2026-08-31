/**
 * esp32s3_breadboard 板型定义
 *
 * ESP32-S3 面包板（无屏幕，串口输出）
 *
 * 音频方案由 Kconfig → 音频编解码器 选择（与板型独立）：
 *   - I2S 直连：INMP441 数字麦 + MAX98357 数字功放（独立 I2S 总线）
 *   - ES8311：ES8311 编解码器 + NS4150B 功放（全双工 I2S）
 *
 * 引脚定义见 board_templates.h 中 BOARD_BASE_ESP32S3 宏
 */
#pragma once

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "esp32s3_breadboard",
    .description = "ESP32-S3 面包板 (无屏幕)",
    .bin_id      = BOARD_BIN_ID,

    BOARD_BASE_ESP32S3(0),
    BOARD_DISPLAY_NONE(),
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
