/**
 * ota_commands.c - OTA 升级指令
 *
 * 处理服务端下发的 ota_update 指令（管理员在设备详情里触发强制升级）：
 *   {"type": "instruct", "command_id": "ota_update",
 *    "data": "{\"url\": \"http://.../firmware.bin\", \"version\": \"1.2.0\"}"}
 *
 * data 字段为 JSON 字符串（服务端 _send_ota_to_device 组装），取其中的 url
 * 直接下载固件并写入 OTA 分区，完成后重启（不做版本比对，即强制升级）。
 */
#include "command_registry.h"
#include "ota_update.h"
#include "esp_log.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "cmd_ota";

// 同时只允许一个 OTA 任务（下载+写 flash 阻塞且重资源）
static volatile bool s_ota_task_running = false;

typedef struct {
    char url[512];
} ota_cmd_params_t;

static void ota_task(void *arg)
{
    ota_cmd_params_t *params = (ota_cmd_params_t *)arg;
    ESP_LOGI(TAG, "开始执行 OTA 升级: %s", params->url);
    esp_err_t err = ota_update_from_url(params->url);
    // 成功路径会 esp_restart，走到这里即失败
    ESP_LOGE(TAG, "OTA 升级未完成: %s", esp_err_to_name(err));
    s_ota_task_running = false;
    free(params);
    vTaskDelete(NULL);
}

static esp_err_t cmd_ota_update(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    char url[512] = {0};

    if (cJSON_IsString(data)) {
        // data 是 JSON 字符串（服务端 json.dumps 产物），解析内层取 url
        cJSON *inner = cJSON_Parse(data->valuestring);
        if (inner) {
            cJSON *u = cJSON_GetObjectItem(inner, "url");
            if (cJSON_IsString(u) && u->valuestring[0]) {
                strlcpy(url, u->valuestring, sizeof(url));
            }
            cJSON_Delete(inner);
        }
    } else if (cJSON_IsObject(data)) {
        cJSON *u = cJSON_GetObjectItem(data, "url");
        if (cJSON_IsString(u) && u->valuestring[0]) {
            strlcpy(url, u->valuestring, sizeof(url));
        }
    }

    if (url[0] == '\0') {
        ESP_LOGW(TAG, "ota_update 指令缺少 url 字段，忽略");
        return ESP_ERR_INVALID_ARG;
    }
    if (s_ota_task_running) {
        ESP_LOGW(TAG, "OTA 任务进行中，忽略重复指令");
        return ESP_ERR_INVALID_STATE;
    }

    ota_cmd_params_t *params = malloc(sizeof(*params));
    if (!params) {
        return ESP_ERR_NO_MEM;
    }
    memset(params, 0, sizeof(*params));
    strlcpy(params->url, url, sizeof(params->url));

    BaseType_t ret = xTaskCreate(ota_task, "ota_cmd", 8192, params, 3, NULL);
    if (ret != pdPASS) {
        free(params);
        return ESP_FAIL;
    }
    s_ota_task_running = true;
    ESP_LOGI(TAG, "OTA 升级任务已启动: %s", url);
    return ESP_OK;
}

void register_ota_commands(void)
{
    extern void command_registry_add(command_entry_t *entry);
    static command_entry_t cmd_ota_update_entry = {
        .type = "instruct",
        .command_id = "ota_update",
        .handler = cmd_ota_update,
        .description = "OTA 强制升级（服务端下发固件 URL）",
    };
    command_registry_add(&cmd_ota_update_entry);
}
