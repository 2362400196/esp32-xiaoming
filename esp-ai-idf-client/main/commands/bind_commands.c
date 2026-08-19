/**
 * bind_commands.c - 设备绑定相关指令
 *
 * 处理服务端下发的指令：
 *   - show_bind_code: 显示绑定码到屏幕
 *   - show_wx_qrcode: 显示微信二维码
 *   - wechat_msg: 显示微信消息
 *   - wechat_bind_success: 微信绑定成功通知
 */
#include "command_registry.h"
#include "config.h"
#include "esp_log.h"
#include "cJSON.h"
#include "provisioning.h"
#include "esp_system.h"
#include <string.h>

static const char *TAG = "cmd_bind";

// show_bind_code: 显示绑定码到屏幕，设备进入待绑定状态
static esp_err_t cmd_show_bind_code(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (!data || !cJSON_IsString(data)) {
        ESP_LOGW(TAG, "show_bind_code data 字段缺失或非字符串");
        return ESP_OK;
    }

    const char *code = data->valuestring;
    ESP_LOGI(TAG, "显示绑定码: %s", code);

    // 在屏幕上显示绑定码
    char bind_text[128];
    snprintf(bind_text, sizeof(bind_text), "绑定码: %s\n请登录 App 输入", code);
    display_show_text(bind_text);
    display_show_status("等待绑定...");

    return ESP_OK;
}

// show_wx_qrcode: 显示微信二维码图片 URL
static esp_err_t cmd_show_wx_qrcode(cJSON *json)
{
    cJSON *data_obj = cJSON_GetObjectItem(json, "data");
    if (!data_obj || !cJSON_IsObject(data_obj)) {
        ESP_LOGW(TAG, "show_wx_qrcode data 字段缺失或非对象");
        return ESP_OK;
    }

    cJSON *qrcode_url = cJSON_GetObjectItem(data_obj, "qrcode_url");
    cJSON *session_key = cJSON_GetObjectItem(data_obj, "session_key");

    ESP_LOGI(TAG, "微信二维码 URL: %s", cJSON_IsString(qrcode_url) ? qrcode_url->valuestring : "N/A");
    ESP_LOGI(TAG, "会话标识: %s", cJSON_IsString(session_key) ? session_key->valuestring : "N/A");

    // 显示微信二维码描述到屏幕（URL 可用于图片下载显示）
    char qr_text[128];
    if (cJSON_IsString(qrcode_url) && qrcode_url->valuestring) {
        snprintf(qr_text, sizeof(qr_text), "微信扫码登录\n请用微信扫描二维码");
    } else {
        snprintf(qr_text, sizeof(qr_text), "微信绑定中...\n请在管理后台操作");
    }
    display_show_text(qr_text);
    display_show_status("微信扫码中...");

    // 如果设备有二维码图片显示能力，可以下载并显示
    // 这里使用内置的 wx_qrcode 表情（如果有）
    display_show_emotion("wx_qrcode");

    return ESP_OK;
}

// wechat_msg: 显示从微信转发来的消息
static esp_err_t cmd_wechat_msg(cJSON *json)
{
    cJSON *data_str = cJSON_GetObjectItem(json, "data");
    if (!data_str || !cJSON_IsString(data_str)) {
        ESP_LOGW(TAG, "wechat_msg data 字段缺失或非字符串");
        return ESP_OK;
    }

    // data 是 JSON 字符串，需要解析
    cJSON *data_obj = cJSON_Parse(data_str->valuestring);
    if (!data_obj) {
        ESP_LOGW(TAG, "wechat_msg data 解析失败: %s", data_str->valuestring);
        return ESP_OK;
    }

    cJSON *text = cJSON_GetObjectItem(data_obj, "text");
    cJSON *user_id = cJSON_GetObjectItem(data_obj, "user_id");

    if (text && text->valuestring) {
        ESP_LOGI(TAG, "微信消息 [来自 %s]: %s",
                 user_id ? user_id->valuestring : "未知",
                 text->valuestring);

        char msg_text[256];
        snprintf(msg_text, sizeof(msg_text), "[微信] %s", text->valuestring);
        display_show_text(msg_text);
    }

    cJSON_Delete(data_obj);
    return ESP_OK;
}

// wechat_bind_success: 微信绑定成功通知
static esp_err_t cmd_wechat_bind_success(cJSON *json)
{
    (void)json;
    ESP_LOGI(TAG, "微信绑定成功！");

    display_show_text("微信已绑定 ✓");
    display_show_status("微信已连接");
    display_show_emotion("快乐");

    return ESP_OK;
}

// factory_reset: 恢复出厂设置（清除所有配置 + 重启）
static esp_err_t cmd_factory_reset(cJSON *json)
{
    ESP_LOGW(TAG, "=========================================");
    ESP_LOGW(TAG, "收到服务端恢复出厂设置指令，即将清除所有配置并重启");
    ESP_LOGW(TAG, "=========================================");

    // 短暂延迟让 ACK 发送出去
    vTaskDelay(pdMS_TO_TICKS(500));

    provisioning_clear_all();
    // provisioning_clear_all 会重启，不会执行到这里
    return ESP_OK;
}

// restart: 重启设备（保留所有配置）
static esp_err_t cmd_restart(cJSON *json)
{
    ESP_LOGW(TAG, "=========================================");
    ESP_LOGW(TAG, "收到服务端重启指令，即将重启...");
    ESP_LOGW(TAG, "=========================================");

    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

void register_bind_commands(void)
{
    static command_entry_t entries[] = {
        {
            .type = "instruct", .command_id = "show_bind_code",
            .handler = cmd_show_bind_code, .description = "显示设备绑定码"
        },
        {
            .type = "instruct", .command_id = "show_wx_qrcode",
            .handler = cmd_show_wx_qrcode, .description = "显示微信二维码"
        },
        {
            .type = "instruct", .command_id = "wechat_msg",
            .handler = cmd_wechat_msg, .description = "显示微信消息"
        },
        {
            .type = "instruct", .command_id = "wechat_bind_success",
            .handler = cmd_wechat_bind_success, .description = "微信绑定成功通知"
        },
        {
            .type = "instruct", .command_id = "factory_reset",
            .handler = cmd_factory_reset, .description = "恢复出厂设置"
        },
        {
            .type = "instruct", .command_id = "restart",
            .handler = cmd_restart, .description = "重启设备"
        },
    };
    for (int i = 0; i < sizeof(entries) / sizeof(entries[0]); i++) {
        command_registry_add(&entries[i]);
    }
    ESP_LOGI(TAG, "绑定指令注册完成: show_bind_code, show_wx_qrcode, wechat_msg, wechat_bind_success, factory_reset, restart");
}
