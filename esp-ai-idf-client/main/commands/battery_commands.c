/**
 * battery_commands.c - 电池状态查询指令
 *
 * get_battery: 服务器内置工具 get_battery 下发，设备回复 device_state_result：
 *   {"type":"instruct","command_id":"device_state_result",
 *    "data":"battery=88,voltage=4227,charging=1,full=0"}
 * 板型不支持电池检测时回复 data="battery=unknown"。
 */
#include "command_registry.h"
#include "battery.h"
#include "esp_log.h"
#include <stdio.h>

static const char *TAG = "cmd_battery";

static esp_err_t cmd_get_battery(cJSON *json)
{
    extern esp_err_t websocket_send_text(const char *text);

    int pct = battery_get_percent();
    int mv = battery_get_voltage_mv();
    bool charging = battery_is_charging();
    bool full = battery_is_full();

    char reply[160];
    if (!battery_is_supported() || pct < 0 || mv < 0) {
        snprintf(reply, sizeof(reply),
                 "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"battery=unknown\"}");
    } else {
        snprintf(reply, sizeof(reply),
                 "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"battery=%d,voltage=%d,charging=%d,full=%d\"}",
                 pct, mv, charging ? 1 : 0, full ? 1 : 0);
    }
    websocket_send_text(reply);
    ESP_LOGI(TAG, "查询电量: %d%% %dmV %s", pct, mv,
             full ? "已充满" : (charging ? "充电中" : "放电"));
    return ESP_OK;
}

void register_battery_commands(void)
{
    extern void command_registry_add(command_entry_t *entry);

    static command_entry_t cmd_get_battery_entry = {
        .type = "instruct", .command_id = "get_battery",
        .handler = cmd_get_battery, .description = "查询电池电量"
    };
    command_registry_add(&cmd_get_battery_entry);
}
