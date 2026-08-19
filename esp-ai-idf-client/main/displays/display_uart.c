/**
 * display_uart.c - 串口显示驱动实现
 *
 * 通过串口输出状态信息，无图形显示
 * 适用于无屏幕的板型
 */
#include "display_uart.h"
#include "esp_log.h"
#include "stdio.h"

static const char *TAG = "display_uart";

// 前向声明
static esp_err_t uart_init(void);
static esp_err_t uart_show_emotion(const char *emotion);
static esp_err_t uart_show_status(const char *status);
static esp_err_t uart_show_text(const char *text);

// 驱动实例
static const display_driver_t s_uart_driver = {
    .name = "uart",
    .init = uart_init,
    .show_emotion = uart_show_emotion,
    .show_status = uart_show_status,
    .show_text = uart_show_text,
    .set_brightness = NULL,  // 不支持
    .show_battery = NULL,    // 不支持
    .clear = NULL,
    .caps = {
        .has_graphic = false,
        .has_text = true,
        .has_brightness = false,
        .has_battery = false,
    },
};

const display_driver_t *display_driver_uart_get(void)
{
    return &s_uart_driver;
}

static esp_err_t uart_init(void)
{
    ESP_LOGI(TAG, "串口显示驱动初始化完成（无图形显示）");
    /* 以下 printf 输出为显示内容（启动横幅），通过串口呈现给用户查看。
     * 这是 UART 显示驱动的"显示"职责，并非调试日志。
     * 不能替换为 ESP_LOGI，否则日志前缀会破坏显示格式。 */
    printf("\n========================================\n");
    printf("  ESP-AI 设备已启动\n");
    printf("  显示模式: 串口输出\n");
    printf("========================================\n\n");
    return ESP_OK;
}

static esp_err_t uart_show_emotion(const char *emotion)
{
    /* printf 输出为显示内容（表情），通过串口呈现给用户查看，并非调试日志。
     * 不能替换为 ESP_LOGI，否则日志前缀会破坏显示格式。 */
    printf("\n[表情] %s\n", emotion ? emotion : "无");
    return ESP_OK;
}

static esp_err_t uart_show_status(const char *status)
{
    /* printf 输出为显示内容（状态），通过串口呈现给用户查看，并非调试日志。
     * 不能替换为 ESP_LOGI，否则日志前缀会破坏显示格式。 */
    printf("[状态] %s\n", status ? status : "无");
    return ESP_OK;
}

static esp_err_t uart_show_text(const char *text)
{
    /* printf 输出为显示内容（字幕），通过串口呈现给用户查看，并非调试日志。
     * 不能替换为 ESP_LOGI，否则日志前缀会破坏显示格式。 */
    if (text && strlen(text) > 0) {
        printf("[字幕] %s\n", text);
    }
    return ESP_OK;
}