/**
 * config_commands.c - 远程配置更新指令
 *
 * 处理服务端下发的指令：
 *   - update_config: 更新设备配置，data 为键值对对象
 *
 * 使用方法：服务器下发
 *   {"type":"instruct","command_id":"update_config","data":{"volume":"0.8","wake_sensitivity":"0.6"}}
 *
 * 所有配置项保存到 NVS "esp-ai-kv" 命名空间，重启后生效（部分项可即时生效）
 */
#include "command_registry.h"
#include "config.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "cJSON.h"
#include <string.h>

extern void websocket_force_reconnect(void);

static const char *TAG = "cmd_config";

// 即时生效的配置项处理（在保存到 NVS 后额外执行）
static void apply_config_immediate(const char *key, const char *value)
{
    // 音量：立即生效
    if (strcmp(key, "volume") == 0) {
        float vol = atof(value);
        if (vol >= 0.0f && vol <= 1.0f) {
            audio_set_volume(vol);
            ESP_LOGI(TAG, "音量已即时调整: %s", value);
        } else {
            ESP_LOGW(TAG, "音量值 %.2f 超出范围 [0.0, 1.0]，跳过即时生效", vol);
        }
    }
    // 可在此添加其他支持即时生效的配置项
}

// update_config: 解析 data 对象中的键值对，全部写入 NVS
// 兼容两种 data 格式（esp-ai-server 下发为 JSON 字符串，其他服务可能为对象）：
//   data: '{"llm_system_prompt": "..."}'
//   data: {"llm_system_prompt": "..."}
static esp_err_t cmd_update_config(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (!data) {
        ESP_LOGW(TAG, "update_config: data 字段缺失");
        return ESP_OK;
    }

    cJSON *obj = data;
    bool is_tmp = false;
    if (cJSON_IsString(data)) {
        // data 为 JSON 字符串，解析为对象
        obj = cJSON_Parse(data->valuestring);
        is_tmp = true;
    }
    if (!obj || !cJSON_IsObject(obj)) {
        if (is_tmp && obj) cJSON_Delete(obj);
        ESP_LOGW(TAG, "update_config: data 非对象且无法解析");
        return ESP_OK;
    }

    nvs_handle_t h;
    esp_err_t err = nvs_open("esp-ai-kv", NVS_READWRITE, &h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "NVS 打开失败: %s", esp_err_to_name(err));
        if (is_tmp) cJSON_Delete(obj);
        return ESP_OK;
    }

    int count = 0;
    cJSON *item = NULL;
    cJSON_ArrayForEach(item, obj) {
        const char *key = item->string;
        if (!key) continue;

        // ESP-IDF NVS 键名最大 15 字符（ESP_ERR_NVS_KEY_TOO_LONG）。
        // 服务端下发的服务端专用配置键（如 llm_system_prompt，17 字符）固件本地
        // 不消费，超长键直接跳过；这是正常情况，用 DEBUG 级别避免刷日志。
        if (strlen(key) > 15) {
            ESP_LOGD(TAG, "NVS 键名超长(>15)跳过: %s", key);
            continue;
        }

        if (cJSON_IsString(item)) {
            esp_err_t nret = nvs_set_str(h, key, item->valuestring);
            if (nret != ESP_OK) {
                ESP_LOGE(TAG, "NVS 写入失败 (key=%s): %s", key, esp_err_to_name(nret));
            } else {
                apply_config_immediate(key, item->valuestring);
                ESP_LOGI(TAG, "配置更新: %s = %s", key, item->valuestring);
                count++;
            }
        } else if (cJSON_IsNumber(item)) {
            // 数字也存为字符串，与 Arduino 端一致
            char buf[32];
            if (item->valuedouble == (double)item->valueint) {
                snprintf(buf, sizeof(buf), "%d", item->valueint);
            } else {
                snprintf(buf, sizeof(buf), "%.2f", item->valuedouble);
            }
            esp_err_t nret = nvs_set_str(h, key, buf);
            if (nret != ESP_OK) {
                ESP_LOGE(TAG, "NVS 写入失败 (key=%s): %s", key, esp_err_to_name(nret));
            } else {
                apply_config_immediate(key, buf);
                ESP_LOGI(TAG, "配置更新: %s = %s", key, buf);
                count++;
            }
        } else if (cJSON_IsBool(item)) {
            const char *bool_str = item->valueint ? "true" : "false";
            esp_err_t nret = nvs_set_str(h, key, bool_str);
            if (nret != ESP_OK) {
                ESP_LOGE(TAG, "NVS 写入失败 (key=%s): %s", key, esp_err_to_name(nret));
            } else {
                ESP_LOGI(TAG, "配置更新: %s = %s", key, bool_str);
                count++;
            }
        }
    }

    nvs_commit(h);
    nvs_close(h);

    if (is_tmp) cJSON_Delete(obj);

    ESP_LOGI(TAG, "配置更新完成，共 %d 项", count);
    return ESP_OK;
}

// config_updated: 配置已变更,延时 2 秒(等当前音频播完)后自动重连 WS,使新配置生效。
// 服务端在 /config 保存成功后推送,设备重连后重新握手/初始化,ASR/TTS/LLM 网关全用新配置。
static esp_timer_handle_t s_config_updated_timer = NULL;
static void config_updated_timer_cb(void *arg)
{
    websocket_force_reconnect();
    s_config_updated_timer = NULL;
}

static esp_err_t cmd_config_updated(cJSON *json)
{
    ESP_LOGI(TAG, "收到 config_updated:配置已变更,2 秒后自动重连应用新配置");
    // 取消上一次未触发的重连定时器(连续改配置只重连一次)
    if (s_config_updated_timer) {
        esp_timer_stop(s_config_updated_timer);
        esp_timer_delete(s_config_updated_timer);
        s_config_updated_timer = NULL;
    }
    esp_timer_create_args_t args = {
        .callback = config_updated_timer_cb,
        .name = "cfg_recon",
    };
    if (esp_timer_create(&args, &s_config_updated_timer) != ESP_OK) {
        websocket_force_reconnect();  // 定时器创建失败,立即重连兜底
        return ESP_OK;
    }
    esp_timer_start_once(s_config_updated_timer, 2 * 1000 * 1000);  // 2 秒后重连
    return ESP_OK;
}

void register_config_commands(void)
{
    extern void command_registry_add(command_entry_t *entry);

    static command_entry_t cmd_update_config_entry = {
        .type = "instruct", .command_id = "update_config",
        .handler = cmd_update_config, .description = "更新设备配置"
    };
    command_registry_add(&cmd_update_config_entry);

    static command_entry_t cmd_config_updated_entry = {
        .type = "instruct", .command_id = "config_updated",
        .handler = cmd_config_updated, .description = "配置已变更,自动重连使新配置生效"
    };
    command_registry_add(&cmd_config_updated_entry);
}
