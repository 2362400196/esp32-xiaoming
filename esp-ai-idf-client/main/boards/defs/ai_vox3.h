/**
 * ai_vox3 板型定义
 *
 * AI-VOX3（EmakeFun / nulllab，ESP32-S3R8 + ES8311 + NS4150B + 240x240 LCD）
 *
 * 引脚表（来源：AI-VOX3 原理图 Rev V0.6/V1.1）：
 * | 功能              | GPIO | 说明                                   |
 * |-------------------|------|----------------------------------------|
 * | 唤醒按键 B2(BOOT) | 0    | 板载 BOOT 键，外部 10K 上拉，按下接地  |
 * | 音量 + 按键 B1(A) | 46   | 按下接地，内部上拉，低电平有效         |
 * | 音量 - 按键 B3(B) | 45   | 按下接地，内部上拉，低电平有效         |
 * | 电池电压 ADC      | 18   | +BATT—470K—IO18—470K—GND（分压比 2）   |
 * | I2S MCLK          | 11   | ES8311 MCLK                            |
 * | I2S BCLK          | 10   | ES8311 SCLK                            |
 * | I2S LRCK/WS       | 8    | ES8311 LRCK                            |
 * | I2S SDIN (TX)     | 7    | ESP32 → ES8311 DSDIN（DAC）            |
 * | I2S SDOUT (RX)    | 9    | ES8311 ASDOUT（ADC）→ ESP32            |
 * | I2C SDA           | 13   | ES8311 CDATA（同时接 OLED 排针）       |
 * | I2C SCL           | 12   | ES8311 CCLK（同时接 OLED 排针）        |
 * | LCD SPI CS        | 15   |                                        |
 * | LCD SPI DC        | 14   |                                        |
 * | LCD SPI CLK       | 17   |                                        |
 * | LCD SPI MOSI      | 21   |                                        |
 * | LCD 背光          | 16   | Q1(S8050) 高电平点亮，LEDC PWM 调光    |
 * | WS2812 DIN        | 41   | 状态灯（本固件未占用，可作他用）       |
 * | SD 卡 CLK/CMD/D0  | 38/39/40 | MMC 模式（本固件未使用）           |
 *
 * 其他：
 * - ES8311 CE 由 10K 上拉到 +3V3，I2C 地址 0x18
 * - NS4150B 功放 CTRL 由 100K 上拉到 +3V3，常开，无 PA 控制脚
 * - LCD RESET 接芯片 EN 网络，无独立复位 GPIO（驱动走软件复位）
 * - 麦克风为板载模拟麦（LMA2718）→ ES8311 MIC1P/N
 * - 充电芯片 ETA6093 的 STAT 只驱动双色灯 D4，没有接到 MCU，
 *   因此“是否充电”由 USB 主机在位（USB-Serial-JTAG 收到 SOF）+ 电池电压
 *   上升趋势联合判定（见 battery.c）；接充电头（无 SOF）时仅靠趋势判定
 * - SD 卡本固件暂未使用
 * - 屏幕按 240x240 ST7789 适配（原理图只标注 LCD240x240）；
 *   若实际批次为 GC9A01 等同接口屏，需在 display_lcd 中替换控制器初始化
 */
/// @meta chip=esp32s3 vendor=emakefun series=ai_vox3
#pragma once

#include "boards/board_interface.h"

// 自定义 ES8311 引脚（必须在 include board_templates.h 之前）
#define ES8311_CFG_CUSTOM
static const es8311_config_t ES8311_CFG = {
    .i2c_port  = 0,
    .i2c_sda   = 13,
    .i2c_scl   = 12,
    .i2c_addr  = 0x18,
    .pa_pin    = -1,        // NS4150B CTRL 硬件上拉常开
    .mclk_pin  = 11,
    .mclk_freq = 4096000,   // 16000 * 256
};

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "ai_vox3",
    .description = "AI-VOX3 (ESP32-S3 + ES8311 + 240x240 LCD)",

    .wake_button_gpio = 0,      // BOOT 键（B2）
    // bck=10, ws=8, spk_tx=7, mic_rx=9
    BOARD_AUDIO_ES8311_CUSTOM(10, 8, 7, 9, &ES8311_CFG),
    // cs=15, dc=14, clk=17, mosi=21, 背光=16
    BOARD_DISPLAY_ST7789_240_BL(15, 14, 17, 21, 16),
    // 电池 IO18（分压比 2），A 键 IO46 音量+，B 键 IO45 音量-
    BOARD_BATTERY_KEYS(18, 2.0f, 46, 45),
    // SD 卡（SDMMC 1-bit）：CLK=IO39, CMD=IO38, DAT0=IO40
    BOARD_SD_CARD(39, 38, 40),
    BOARD_SERVICE_SELF_HOSTED(),
    BOARD_EXTRAS_NONE(),
};
