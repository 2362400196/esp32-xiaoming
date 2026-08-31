/**
 * breadboard_1.54_lcd_official 板型定义
 *
 * ESP32-S3 面包板 + 1.54寸 ST7789 LCD (240x240)
 *
 * 面向 ESP-AI 官方服务（espai.fun）适配：
 *   - official_service = true   : 默认请求官方服务节点
 *   - emotion_builtin_only = true : 表情只用编译内置资源
 *
 * 音频方案由 Kconfig → 音频编解码器 选择（与板型独立）：
 *   - I2S 直连：INMP441 数字麦 + MAX98357 数字功放
 *   - ES8311：ES8311 编解码器 + NS4150B 功放（全双工 I2S）
 *
 * 继承 BOARD_BASE_ESP32S3 基模板，覆盖显示配置 + 服务模式
 */
#pragma once

#include "boards/defs/board_templates.h"

static const board_config_t BOARD_CONFIG = {
    .name        = "breadboard_1.54_lcd_official",
    .description = "ESP32-S3 面包板 (1.54寸 LCD, 官方服务版)",
    .bin_id      = "0f3a7c21e8d94b56a2c1d5e4f6071829",

    BOARD_BASE_ESP32S3(0),
    BOARD_DISPLAY_ST7789_240(9, 13, 38, 39),
    BOARD_SERVICE_OFFICIAL(),
    BOARD_EXTRAS_NONE(),
};
