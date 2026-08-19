/**
 * esp32c3_supermini 板型定义
 *
 * /// @meta chip=esp32c3 vendor=generic series=supermini
 *
 * ESP32-C3 SuperMini 开发板（单核 160MHz，无 PSRAM，4MB Flash）
 *
 * 注意：
 * - C3 只有 I2S_NUM_0，音频必须用 ES8311 全双工方案（menuconfig → 音频编解码器 → ES8311）；
 *   I2S 直连方案依赖 I2S_NUM_1，在 C3 上不可用。
 * - 无 PSRAM，固件需用 4MB 分区表（sdkconfig.defaults.esp32c3 已配置），无 OTA 双槽。
 * - 无屏幕（SuperMini 无显示），表情/GIF 自动跳过。
 *
 * ES8311 接线（HW-466AB 引脚表）：
 * | 功能 | GPIO | 接 ES8311 |
 * |------|------|-----------|
 * | SDA  | 4    | SDA       |
 * | SCL  | 5    | SCL       |
 * | MCLK | 1    | CLK       |
 * | BCLK | 3    | SCK       |
 * | WS   | 6    | LRCK      |
 * | DIN  | 7    | DAC SDIN  |
 * | DOUT | 10   | ADC SDOUT |
 * | 唤醒按钮 | 9（板载 BOOT 按键） |
 */
#pragma once

#define ES8311_CFG_CUSTOM
static const es8311_config_t ES8311_CFG = {
    .i2c_port  = 0,
    .i2c_sda   = 4,
    .i2c_scl   = 5,
    .i2c_addr  = 0x18,
    .pa_pin    = -1,        // 无外部 PA 控制脚
    .mclk_pin  = 1,
    .mclk_freq = 4096000,   // 16000 * 256
};

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "esp32c3_supermini",
    .description = "ESP32-C3 SuperMini (ES8311 全双工, 无屏)",
    .bin_id      = "e3a9c5f21d8b47a6b3c0e9d8f7a61234",

    .wake_button_gpio = 9,                                   // 板载 BOOT 按键 (GPIO9)
    BOARD_AUDIO_ES8311_CUSTOM(3, 6, 7, 10, &ES8311_CFG),     // bck, ws, spk_tx, mic_rx
    BOARD_DISPLAY_NONE(),
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
