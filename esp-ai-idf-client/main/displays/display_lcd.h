/**
 * display_lcd.h - SPI LCD 显示驱动接口
 *
 * 基于 LVGL + EEUI 表情显示，支持：
 * - ST7789 / ILI9341 等 SPI LCD
 * - GIF 动画表情
 * - 中文字幕显示
 *
 * 适用于带屏幕的板型（如 esp32s3_breadboard_1.54_lcd）
 */
#pragma once

#include "display_driver.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 获取 LCD 显示驱动
 * 用于注册到 display 模块
 */
const display_driver_t *display_driver_lcd_get(void);

/**
 * 初始化 LCD 显示驱动（内部函数，由驱动框架调用）
 */
esp_err_t display_lcd_init(void);

/**
 * 显示表情（内部函数）
 */
esp_err_t display_lcd_show_emotion(const char *emotion);

/**
 * 显示状态文字（内部函数）
 */
esp_err_t display_lcd_show_status(const char *status);

/**
 * 显示文本（内部函数）
 */
esp_err_t display_lcd_show_text(const char *text);

/**
 * 设置亮度（内部函数）
 */
esp_err_t display_lcd_set_brightness(int percent);

/**
 * 显示电量（内部函数）
 */
esp_err_t display_lcd_show_battery(int percent);

/**
 * 清除显示（内部函数）
 */
esp_err_t display_lcd_clear(void);

#ifdef __cplusplus
}
#endif