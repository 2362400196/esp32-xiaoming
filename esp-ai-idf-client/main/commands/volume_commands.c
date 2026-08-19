/**
 * volume_commands.c - 音量控制指令
 *
 * 从 websocket.c 迁移的指令:
 *   - set_volume:      设置音量（0.0-1.0）
 *   - add_volume:      增加音量
 *   - subtract_volume: 减少音量
 *
 * 音量持久化到 NVS（键 "ext2"），开机自动恢复
 */
#include "command_registry.h"
#include "config.h"
#include "nvs.h"
#include <stdlib.h>

static const char *TAG = "cmd_volume";

// 保存音量到 NVS（与 Arduino ext2 键一致）
static void save_volume(float vol)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) == ESP_OK) {
        char vol_str[16];
        snprintf(vol_str, sizeof(vol_str), "%.1f", vol);
        esp_err_t ret = nvs_set_str(h, "ext2", vol_str);
        if (ret == ESP_OK) {
            ret = nvs_commit(h);
        }
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "音量写入NVS失败: %s", esp_err_to_name(ret));
        }
        nvs_close(h);
    }
}

// set_volume: data 为音量值字符串，如 "0.5"
static esp_err_t cmd_set_volume(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    float vol = 1.0f;
    if (data && cJSON_IsString(data)) {
        vol = atof(data->valuestring);
    }
    audio_set_volume(vol);
    save_volume(vol);
    ESP_LOGI(TAG, "设置音量: %.2f", vol);
    return ESP_OK;
}

// add_volume: data 为增量字符串，如 "0.1"
static esp_err_t cmd_add_volume(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    float delta = 0.1f;
    if (data && cJSON_IsString(data)) {
        delta = atof(data->valuestring);
    }
    float vol = audio_get_volume() + delta;
    audio_set_volume(vol);
    save_volume(vol);
    ESP_LOGI(TAG, "增加音量: +%.2f → %.2f", delta, vol);
    return ESP_OK;
}

// subtract_volume: data 为减量字符串，如 "0.1"
static esp_err_t cmd_subtract_volume(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    float delta = 0.1f;
    if (data && cJSON_IsString(data)) {
        delta = atof(data->valuestring);
    }
    float vol = audio_get_volume() - delta;
    audio_set_volume(vol);
    save_volume(vol);
    ESP_LOGI(TAG, "减少音量: -%.2f → %.2f", delta, vol);
    return ESP_OK;
}

// get_volume: 查询当前音量，回复设备状态给服务器（内置工具 get_volume 使用）
static esp_err_t cmd_get_volume(cJSON *json)
{
    extern esp_err_t websocket_send_text(const char *text);
    float vol = audio_get_volume();
    int percent = (int)(vol * 100 + 0.5f);
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    char reply[96];
    snprintf(reply, sizeof(reply),
             "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"volume=%d\"}",
             percent);
    websocket_send_text(reply);
    ESP_LOGI(TAG, "查询音量: %d%%", percent);
    return ESP_OK;
}

// 显式注册函数：ESP-IDF 下不用 REGISTER_COMMAND 宏的 constructor 方式，
// 避免链接器优化导致注册失效，也防止 constructor + 显式调用重复注册形成链表环。
void register_volume_commands(void)
{
    extern void command_registry_add(command_entry_t *entry);

    static command_entry_t cmd_set_volume_entry = {
        .type = "instruct", .command_id = "set_volume",
        .handler = cmd_set_volume, .description = "设置音量"
    };
    static command_entry_t cmd_volume_up_entry = {
        .type = "instruct", .command_id = "volume_up",
        .handler = cmd_add_volume, .description = "增加音量"
    };
    static command_entry_t cmd_volume_down_entry = {
        .type = "instruct", .command_id = "volume_down",
        .handler = cmd_subtract_volume, .description = "减少音量"
    };
    static command_entry_t cmd_add_volume_entry = {
        .type = "instruct", .command_id = "add_volume",
        .handler = cmd_add_volume, .description = "增加音量"
    };
    static command_entry_t cmd_subtract_volume_entry = {
        .type = "instruct", .command_id = "subtract_volume",
        .handler = cmd_subtract_volume, .description = "减少音量"
    };
    static command_entry_t cmd_get_volume_entry = {
        .type = "instruct", .command_id = "get_volume",
        .handler = cmd_get_volume, .description = "查询当前音量"
    };

    command_registry_add(&cmd_set_volume_entry);
    command_registry_add(&cmd_volume_up_entry);
    command_registry_add(&cmd_volume_down_entry);
    command_registry_add(&cmd_add_volume_entry);
    command_registry_add(&cmd_subtract_volume_entry);
    command_registry_add(&cmd_get_volume_entry);
}
