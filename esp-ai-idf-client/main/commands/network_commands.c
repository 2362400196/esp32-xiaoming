/**
 * network_commands.c - 网络信息查询指令
 *
 * get_ip: 服务器内置工具 get_ip 下发，设备回复 device_state_result：
 *   {"type":"instruct","command_id":"device_state_result",
 *    "data":"ip=192.168.31.123,mac=28:84:85:5A:23:D4,ssid=MyWiFi,rssi=-52"}
 * 未联网时 data="ip=none"。
 */
#include "command_registry.h"
#include "config.h"
#include "device_id.h"
#include "esp_log.h"
#include <stdio.h>

static const char *TAG = "cmd_network";

static esp_err_t cmd_get_ip(cJSON *json)
{
    extern esp_err_t websocket_send_text(const char *text);

    char ip[24] = "";
    char ssid[40] = "";
    char mac[24] = "";
    device_id_get(mac, sizeof(mac));

    char reply[256];
    if (!wifi_get_ip_str(ip, sizeof(ip))) {
        snprintf(reply, sizeof(reply),
                 "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"ip=none,mac=%s\"}",
                 mac);
        ESP_LOGW(TAG, "查询网络: 未连接 (%s)", mac);
        websocket_send_text(reply);
        return ESP_OK;
    }

    const char *ssid_part = wifi_get_ssid(ssid, sizeof(ssid)) ? ssid : "";
    snprintf(reply, sizeof(reply),
             "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"ip=%s,mac=%s,ssid=%s,rssi=%d\"}",
             ip, mac, ssid_part, wifi_get_rssi());
    ESP_LOGI(TAG, "查询网络: %s (%s) SSID=%s RSSI=%d", ip, mac, ssid_part, wifi_get_rssi());
    websocket_send_text(reply);
    return ESP_OK;
}

void register_network_commands(void)
{
    extern void command_registry_add(command_entry_t *entry);

    static command_entry_t cmd_get_ip_entry = {
        .type = "instruct", .command_id = "get_ip",
        .handler = cmd_get_ip, .description = "查询设备 IP/网络信息"
    };
    command_registry_add(&cmd_get_ip_entry);
}
