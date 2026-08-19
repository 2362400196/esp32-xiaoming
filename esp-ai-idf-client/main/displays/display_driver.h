/**
 * display_driver.h - 显示驱动接口
 *
 * 定义统一的显示驱动接口，支持不同类型的显示屏：
 * - SPI LCD (ST7789/ILI9341 等)
 * - I2C OLED (SSD1306/SH1106 等)
 * - UART 串口输出
 *
 * 每个板型可选择合适的显示驱动
 */
#pragma once

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 显示驱动结构体
 * 每种显示屏实现自己的驱动，注册到系统
 */
typedef struct display_driver {
    const char *name;                   // 驱动名称

    /**
     * 初始化显示硬件
     * @return ESP_OK 成功
     */
    esp_err_t (*init)(void);

    /**
     * 渲染表情（GIF 或图片）
     * @param emotion 表情名称: "联网中"/"聆听中"/"说话中"/"休息中"/"快乐" 等
     * @return ESP_OK 成功，ESP_ERR_NOT_SUPPORTED 不支持
     */
    esp_err_t (*show_emotion)(const char *emotion);

    /**
     * 显示状态文字（顶部）
     * @param status 状态文字，如 "休息中"、"聆听中"
     * @return ESP_OK 成功
     */
    esp_err_t (*show_status)(const char *status);

    /**
     * 显示文本（底部字幕）
     * @param text 文本内容
     * @return ESP_OK 成功
     */
    esp_err_t (*show_text)(const char *text);

    /**
     * 设置背光亮度
     * @param percent 0-100
     * @return ESP_OK 成功，ESP_ERR_NOT_SUPPORTED 不支持
     */
    esp_err_t (*set_brightness)(int percent);

    /**
     * 显示电量图标
     * @param percent 0-100
     * @return ESP_OK 成功，ESP_ERR_NOT_SUPPORTED 不支持
     */
    esp_err_t (*show_battery)(int percent);

    /**
     * 清除显示
     * @return ESP_OK 成功
     */
    esp_err_t (*clear)(void);

    /**
     * 驱动能力标志
     */
    struct {
        bool has_graphic;      // 是否支持图形/表情
        bool has_text;         // 是否支持文字显示
        bool has_brightness;   // 是否支持亮度调节
        bool has_battery;      // 是否支持电量显示
    } caps;

} display_driver_t;

/**
 * 注册显示驱动
 * @param driver 驱动结构体指针
 * @return ESP_OK 成功
 */
esp_err_t display_register_driver(const display_driver_t *driver);

/**
 * 获取当前显示驱动
 * @return 驱动指针，未注册返回 NULL
 */
const display_driver_t *display_get_driver(void);

/**
 * 检查是否支持图形显示
 * @return true 支持
 */
bool display_has_graphic(void);

#ifdef __cplusplus
}
#endif