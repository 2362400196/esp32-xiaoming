/**
 * display.c - 显示模块核心
 *
 * 统一的显示接口，通过驱动注册机制支持不同类型的显示屏：
 * - SPI LCD (ST7789/ILI9341)
 * - I2C OLED (SSD1306/SH1106)
 * - UART 串口输出
 *
 * 使用方法：
 * 1. 各显示驱动实现 display_driver_t 接口
 * 2. 在板型初始化时调用 display_register_driver() 注册
 * 3. 应用代码通过 display_show_* 接口调用，无需关心底层实现
 */
#include "display_driver.h"
#include "esp_log.h"
#include "eeui_port.h"

static const char *TAG = "display";

// 当前注册的驱动
static const display_driver_t *s_driver = NULL;

esp_err_t display_register_driver(const display_driver_t *driver)
{
    if (driver == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    s_driver = driver;
    ESP_LOGI(TAG, "注册显示驱动: %s (图形=%d, 文字=%d)",
             driver->name,
             driver->caps.has_graphic,
             driver->caps.has_text);

    return ESP_OK;
}

const display_driver_t *display_get_driver(void)
{
    return s_driver;
}

bool display_has_graphic(void)
{
    return s_driver && s_driver->caps.has_graphic;
}

// ==================== 公共 API ====================

esp_err_t display_init(void)
{
    ESP_LOGI(TAG, "初始化显示...");

    if (s_driver == NULL) {
        ESP_LOGW(TAG, "无显示驱动注册，跳过初始化");
        return ESP_OK;
    }

    if (s_driver->init == NULL) {
        ESP_LOGW(TAG, "驱动无 init 函数");
        return ESP_OK;
    }

    esp_err_t ret = s_driver->init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "显示驱动初始化失败: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "显示初始化完成: %s", s_driver->name);
    return ESP_OK;
}

esp_err_t display_show_emotion(const char *emotion)
{
    if (emotion == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_LOGD(TAG, "表情: %s", emotion);

    if (s_driver && s_driver->show_emotion) {
        return s_driver->show_emotion(emotion);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_show_status(const char *status)
{
    if (status == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_LOGD(TAG, "状态: %s", status);

    if (s_driver && s_driver->show_status) {
        return s_driver->show_status(status);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_show_text(const char *text)
{
    if (text == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    ESP_LOGD(TAG, "文本: %s", text);

    if (s_driver && s_driver->show_text) {
        return s_driver->show_text(text);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_set_brightness(int percent)
{
    ESP_LOGI(TAG, "亮度: %d%%", percent);

    if (s_driver && s_driver->set_brightness) {
        return s_driver->set_brightness(percent);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_show_battery(int percent)
{
    ESP_LOGD(TAG, "电量: %d%%", percent);

    if (s_driver && s_driver->show_battery) {
        return s_driver->show_battery(percent);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_clear(void)
{
    ESP_LOGI(TAG, "清除显示");

    if (s_driver && s_driver->clear) {
        return s_driver->clear();
    }

    return ESP_ERR_NOT_SUPPORTED;
}

// ==================== OTA 进度条 ====================

esp_err_t display_show_ota_progress(int percent)
{
    ESP_LOGD(TAG, "OTA 进度: %d%%", percent);

    if (display_has_graphic()) {
        eeui_port_render_ota_percent(percent);
        return ESP_OK;
    }

    // 无图形显示时，退化为状态文字
    if (s_driver && s_driver->show_status) {
        // 指针生命周期约束: buf 为栈缓冲区，其指针仅在本次 show_status() 调用期间有效。
        // 驱动实现必须同步消费该字符串内容，不得在异步上下文中保留或延后使用该指针。
        // 当前所有驱动实现（如 uart）均为同步调用，满足此约束；
        // 若后续驱动需异步保存状态文字，应先 strdup 复制后再传递。
        char buf[32];
        snprintf(buf, sizeof(buf), "升级中 %d%%", percent);
        return s_driver->show_status(buf);
    }

    return ESP_ERR_NOT_SUPPORTED;
}

esp_err_t display_clear_ota_progress(void)
{
    if (display_has_graphic()) {
        eeui_port_clear_ota_progress();
        return ESP_OK;
    }
    return ESP_OK;
}