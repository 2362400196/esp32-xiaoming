/**
 * display_lcd.cpp - SPI LCD 显示驱动实现
 *
 * 基于 LVGL + EEUI 表情显示，实现 display_driver_t 接口
 */
#include "display_lcd.h"
#include "eeui_port.h"
#include "esp_log.h"

static const char *TAG = "display_lcd";

// 驱动能力
static const display_driver_t s_lcd_driver = {
    .name = "lcd_lvgl",
    .init = display_lcd_init,
    .show_emotion = display_lcd_show_emotion,
    .show_status = display_lcd_show_status,
    .show_text = display_lcd_show_text,
    .set_brightness = display_lcd_set_brightness,
    .show_battery = display_lcd_show_battery,
    .clear = display_lcd_clear,
    .caps = {
        .has_graphic = true,
        .has_text = true,
        .has_brightness = true,
        .has_battery = true,
    },
};

const display_driver_t *display_driver_lcd_get(void)
{
    return &s_lcd_driver;
}

esp_err_t display_lcd_init(void)
{
    ESP_LOGI(TAG, "初始化 LCD 显示驱动...");

    esp_err_t ret = eeui_port_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "EEUI 初始化失败");
        return ret;
    }

    ESP_LOGI(TAG, "LCD 显示驱动初始化完成");
    return ESP_OK;
}

esp_err_t display_lcd_show_emotion(const char *emotion)
{
    eeui_port_render_emotion(emotion);
    return ESP_OK;
}

esp_err_t display_lcd_show_status(const char *status)
{
    eeui_port_set_status_text(status, true, "top_left");
    return ESP_OK;
}

esp_err_t display_lcd_show_text(const char *text)
{
    eeui_port_set_bottom_text(text);
    return ESP_OK;
}

esp_err_t display_lcd_set_brightness(int percent)
{
    eeui_port_set_brightness(percent);
    return ESP_OK;
}

esp_err_t display_lcd_show_battery(int percent)
{
    eeui_port_render_battery(percent);
    return ESP_OK;
}

esp_err_t display_lcd_clear(void)
{
    // 清除所有显示元素
    eeui_port_set_status_text("", false, "top_left");
    eeui_port_set_bottom_text("");
    eeui_port_render_emotion("休息中");
    return ESP_OK;
}