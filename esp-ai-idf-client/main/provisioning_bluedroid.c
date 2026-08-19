#include "config.h"
#include "provisioning.h"
#include "provisioning_page.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_bt.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"
#include "esp_gatts_api.h"
#include "esp_bt_device.h"
#include "esp_http_server.h"
#include "cJSON.h"
#include "esp_random.h"
#include "esp_mac.h"
#include <string.h>
#include <stdlib.h>

#define BLE_SERVICE_UUID 0xBAAD
// 静态广告参数（与 ESP-IDF gatt_server 示例一致）
static esp_ble_adv_params_t s_adv_params = {
    .adv_int_min        = 0x0020,
    .adv_int_max        = 0x0040,
    .adv_type           = ADV_TYPE_IND,
    .own_addr_type      = BLE_ADDR_TYPE_RANDOM,
    .channel_map        = ADV_CHNL_ALL,
    .adv_filter_policy  = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
};
#define BLE_CHAR_UUID 0xF00D
#define EOT_MARKER "--END--"

static const char *TAG = "provisioning";
#define NVS_NAMESPACE "esp-ai-kv"

// BLE 接收缓冲区
static char s_ble_buffer[2048] = {0};
static size_t s_ble_buffer_len = 0;

static uint16_t s_service_handle = 0;
static uint16_t s_char_handle = 0;
static uint16_t s_conn_id = 0;
static esp_gatt_if_t s_gatts_if = 0xff;
static bool s_is_connected = false;
static bool s_ble_prov_running = false;
static uint8_t s_adv_config_done = 0;
static bool s_advertising = false;
static bool s_ap_prov_running = false;
static httpd_handle_t s_ap_server = NULL;
static char s_ap_ssid[32] = {0};
static char s_ap_password[64] = {0};

static void gatts_h(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if, esp_ble_gatts_cb_param_t *param);
static void gap_h(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param);

// ==================== 设备绑定回调（与 esp-ai-client 的 onBindDeviceCb 一致） ====================
static provisioning_on_bind_cb_t s_on_bind_cb = NULL;

void provisioning_set_on_bind_cb(provisioning_on_bind_cb_t cb)
{
    s_on_bind_cb = cb;
}

// ==================== BLE 错误消息（与 esp-ai-client 的 ESP_AI_BLE_ERR 一致） ====================
static char s_ble_err_msg[256] = {0};
static bool s_ble_err_pending = false;

void provisioning_ble_set_err(const char *err_msg)
{
    strncpy(s_ble_err_msg, err_msg, sizeof(s_ble_err_msg) - 1);
    s_ble_err_msg[sizeof(s_ble_err_msg) - 1] = 0;
    s_ble_err_pending = true;
}

// ==================== URL 解码（与旧客户端 decodeURIComponent 一致） ====================
static void url_decode(const char *src, size_t src_len, char *dst, size_t dst_len)
{
    size_t j = 0;
    for (size_t i = 0; i < src_len && j < dst_len - 1; i++) {
        if (src[i] == '%' && i + 2 < src_len) {
            char hex[3] = {src[i+1], src[i+2], 0};
            dst[j++] = (char)strtol(hex, NULL, 16);
            i += 2;
        } else if (src[i] == '+') {
            dst[j++] = ' ';
        } else {
            dst[j++] = src[i];
        }
    }
    dst[j] = 0;
}

// ==================== 保存所有 key 到 NVS（与旧客户端 set_local_data 一致） ====================
static void save_key_to_nvs(const char *key, const char *value)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) return;

    // 更新 keys 列表（与旧客户端的 _keys_list_ 一致）
    char keys_list[1024] = {0};
    size_t len = sizeof(keys_list);
    bool has_list = (nvs_get_str(h, "_keys_list_", keys_list, &len) == ESP_OK);

    if (!has_list || len == 0) {
        keys_list[0] = 0;
    }

    // 检查 key 是否已存在
    bool key_exists = false;
    char *p = keys_list;
    while (p && *p) {
        char *comma = strchr(p, ',');
        if (comma) *comma = 0;
        if (strcmp(p, key) == 0) { key_exists = true; if (comma) *comma = ','; break; }
        if (comma) { *comma = ','; p = comma + 1; }
        else break;
    }

    // key 不存在则追加到列表
    if (!key_exists) {
        size_t cur = strlen(keys_list);
        if (cur > 0) { keys_list[cur] = ','; cur++; }
        snprintf(keys_list + cur, sizeof(keys_list) - cur, "%s", key);
        nvs_set_str(h, "_keys_list_", keys_list);
    }

    nvs_set_str(h, key, value);
    nvs_commit(h);
    nvs_close(h);
}

// ==================== 清除所有本地数据（与 esp-ai-client 的 clear_local_all_data 一致） ====================
static void clear_local_all_data(void)
{
    // 只擦除 esp-ai-kv 命名空间，避免影响其他分区数据
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
        esp_err_t err = nvs_erase_all(h);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "NVS erase failed: %d", err);
        } else {
            nvs_commit(h);
            ESP_LOGI(TAG, "NVS namespace erased");
        }
        nvs_close(h);
    } else {
        ESP_LOGE(TAG, "NVS open failed for erase");
    }
}

// ==================== BLE 数据接收完成后的处理 ====================
static void process_ble_complete(void)
{
    if (s_ble_buffer_len == 0) return;

    // 1. URL 解码（用堆分配避免栈溢出，与旧客户端 decodeURIComponent 一致）
    char *decoded = malloc(2048);
    if (!decoded) { ESP_LOGE(TAG, "malloc failed"); return; }
    memset(decoded, 0, 2048);
    url_decode(s_ble_buffer, s_ble_buffer_len, decoded, 2048);
    // 解析并显示 key 列表（不显示敏感的 value）
    cJSON *keys_json = cJSON_Parse(decoded);
    if (keys_json) {
        int key_count = 0;
        char key_list[256] = "";
        cJSON *item_json = NULL;
        cJSON_ArrayForEach(item_json, keys_json) {
            size_t cur_len = strlen(key_list);
            int prefix = (key_count > 0) ? 2 : 0; // ", " 前缀
            if (cur_len + prefix + strlen(item_json->string) + 1 < sizeof(key_list)) {
                if (key_count > 0) strcat(key_list, ", ");
                strcat(key_list, item_json->string);
            } else {
                ESP_LOGW(TAG, "key_list 溢出，截断");
                break;
            }
            key_count++;
        }
        ESP_LOGI(TAG, "Decoded keys (%d): %s", key_count, key_list);
        cJSON_Delete(keys_json);
    } else {
        ESP_LOGD(TAG, "Decoded: %s", decoded);
    }

    // 2. 解析 JSON
    cJSON *json = cJSON_Parse(decoded);
    free(decoded);
    if (!json) {
        ESP_LOGE(TAG, "JSON parse failed");
        s_ble_buffer_len = 0;
        return;
    }

    // 3. 遍历所有 key，逐个保存到 NVS（与旧客户端 handle_ble_data 一致）
    int key_count = 0;
    cJSON *child = NULL;
    cJSON_ArrayForEach(child, json) {
        if (cJSON_IsString(child)) {
            save_key_to_nvs(child->string, child->valuestring);
            key_count++;
        }
    }

    cJSON_Delete(json);
    ESP_LOGI(TAG, "Saved %d keys to NVS", key_count);

    // 4. 设置 BLE 临时标记（与旧客户端一致）
    save_key_to_nvs("_ble_temp_", "1");

    // 5. 清空缓冲区
    s_ble_buffer_len = 0;

    // 6. 重启设备（与旧客户端一致）
    ESP_LOGI(TAG, "BLE provisioning data saved, restarting...");
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}

// ==================== GAP 回调 ====================
static void gap_h(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param)
{
    switch (event) {
    case ESP_GAP_BLE_ADV_DATA_SET_COMPLETE_EVT:
        s_adv_config_done |= 1;
        if (s_adv_config_done >= 3) {
            esp_ble_gap_start_advertising(&s_adv_params);
        }
        break;
    case ESP_GAP_BLE_SCAN_RSP_DATA_SET_COMPLETE_EVT:
        s_adv_config_done |= 2;
        if (s_adv_config_done >= 3) {
            esp_ble_gap_start_advertising(&s_adv_params);
        }
        break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
        if (param->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS) {
            s_advertising = true;
            ESP_LOGI(TAG, "BLE advertising started successfully");
        } else {
            ESP_LOGE(TAG, "BLE advertising start failed, status: %d", param->adv_start_cmpl.status);
        }
        break;
    default:
        break;
    }
}

// ==================== 启动 BLE 配网 ====================
static esp_err_t ble_prov_start(void)
{
    s_adv_config_done = 0; s_is_connected = false; s_ble_buffer_len = 0;
    s_advertising = false;
    s_ble_prov_running = true;

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    esp_err_t ret = esp_bt_controller_init(&bt_cfg);
    if (ret) { ESP_LOGE(TAG, "BT ctrl init fail"); return ret; }
    ret = esp_bt_controller_enable(ESP_BT_MODE_BLE);
    if (ret) { ESP_LOGE(TAG, "BT ctrl enable fail"); return ret; }

    ret = esp_bluedroid_init();
    if (ret) { ESP_LOGE(TAG, "Bluedroid init fail"); return ret; }
    ret = esp_bluedroid_enable();
    if (ret) { ESP_LOGE(TAG, "Bluedroid enable fail"); return ret; }

    ret = esp_ble_gatts_register_callback(gatts_h);
    if (ret) { ESP_LOGE(TAG, "GATTS cb fail"); return ret; }
    ret = esp_ble_gap_register_callback(gap_h);
    if (ret) { ESP_LOGE(TAG, "GAP cb fail"); return ret; }
    ret = esp_ble_gatts_app_register(0);
    if (ret) { ESP_LOGE(TAG, "GATTS app fail"); return ret; }

    // 设置设备名（与 esp-ai-client 的 get_ap_name() 一致）
    // esp-ai-client: 取 WiFi MAC 的后5字符去掉冒号，如 "B2:C3" 变"B2C3"
    uint8_t wifi_mac[6] = {0};
    esp_read_mac(wifi_mac, ESP_MAC_WIFI_STA);
    char dn[32];
    // 格式: ESP-AI: + MAC 后2字节去掉冒号
    // MAC: XX:XX:XX:XX:B2:C3, 取 "B2:C3" 去掉: = "B2C3"
    snprintf(dn, sizeof(dn), "ESP-AI:%02X%02X", wifi_mac[4], wifi_mac[5]);
    esp_ble_gap_set_device_name(dn);

    // ESP32-S3 rev v0.2 需要设置随机地址才能广播
    esp_bd_addr_t rand_addr;
    esp_fill_random(rand_addr, 6);
    rand_addr[0] |= 0xC0;  // 随机静态地址标志
    esp_err_t rand_ret = esp_ble_gap_set_rand_addr(rand_addr);
    if (rand_ret != ESP_OK) {
        ESP_LOGW(TAG, "esp_ble_gap_set_rand_addr failed: %d", rand_ret);
    }

    ESP_LOGI(TAG, "BLE: %s, UUID: BAAD/F00D", dn);
    display_show_status("Please use APP to configure");
    return ESP_OK;
}

static void ble_prov_stop(void)
{
    if (!s_ble_prov_running) return;
    s_ble_prov_running = false;
    if (s_is_connected) esp_ble_gatts_close(s_gatts_if, s_conn_id);
    esp_ble_gap_stop_advertising();
    esp_bluedroid_disable(); esp_bluedroid_deinit();
    esp_bt_controller_disable(); esp_bt_controller_deinit();
    ESP_LOGI(TAG, "BLE prov stopped");
}

// ==================== AP 配网 HTTP 处理器 ====================
static esp_err_t ap_http_h(httpd_req_t *req)
{
    if (req->method == HTTP_GET) {
        httpd_resp_set_type(req, "text/html");
        httpd_resp_send(req, provisioning_html, strlen(provisioning_html));
        return ESP_OK;
    }
    if (req->method == HTTP_POST) {
        char buf[512] = {0};
        int r = httpd_req_recv(req, buf, sizeof(buf) - 1);
        if (r <= 0) { httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "No data"); return ESP_FAIL; }
        buf[r] = 0;
        char *sv = strstr(buf, "ssid=");
        if (sv) { sv += 5; char *e = strchr(sv, '&'); if (e) *e = 0;
            url_decode(sv, strlen(sv), s_ap_ssid, sizeof(s_ap_ssid)); }
        char *pv = strstr(buf, "password=");
        if (pv) { pv += 9; char *e = strchr(pv, '&'); if (e) *e = 0;
            url_decode(pv, strlen(pv), s_ap_password, sizeof(s_ap_password)); }
        ESP_LOGI(TAG, "AP prov: ssid=%s", s_ap_ssid);
        httpd_resp_set_type(req, "application/json");
        httpd_resp_send(req, "{\"status\":\"ok\"}", 13);
        provisioning_save_credentials(s_ap_ssid, s_ap_password);
        esp_wifi_connect();
        return ESP_OK;
    }
    return ESP_FAIL;
}

static esp_err_t ap_prov_start(void)
{
    s_ap_prov_running = true;
    wifi_config_t apc = { .ap = { .ssid_len = 0, .channel = 1, .max_connection = 4, .authmode = WIFI_AUTH_OPEN } };
    snprintf((char*)apc.ap.ssid, sizeof(apc.ap.ssid),
        "ESP-AI-AP-%02X%02X", (uint8_t)(esp_random()&0xFF), (uint8_t)(esp_random()&0xFF));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &apc));
    ESP_ERROR_CHECK(esp_wifi_start());
    httpd_config_t hc = HTTPD_DEFAULT_CONFIG();
    hc.lru_purge_enable = true;
    if (httpd_start(&s_ap_server, &hc) == ESP_OK) {
        httpd_register_uri_handler(s_ap_server, &(httpd_uri_t){ .uri = "/", .method = HTTP_GET, .handler = ap_http_h });
        httpd_register_uri_handler(s_ap_server, &(httpd_uri_t){ .uri = "/", .method = HTTP_POST, .handler = ap_http_h });
    }
    ESP_LOGI(TAG, "AP prov: %s", (char*)apc.ap.ssid);
    display_show_status("Connect to AP and configure");
    return ESP_OK;
}

static void ap_prov_stop(void)
{
    if (!s_ap_prov_running) return;
    s_ap_prov_running = false;
    if (s_ap_server) { httpd_stop(s_ap_server); s_ap_server = NULL; }
    ESP_LOGI(TAG, "AP prov stopped");
}

bool provisioning_is_provisioned(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) return false;
    char ssid[64] = {0}; size_t l = sizeof(ssid);
    esp_err_t e = nvs_get_str(h, "wifi_name", ssid, &l);
    nvs_close(h);
    return (e == ESP_OK && strlen(ssid) > 0);
}

esp_err_t provisioning_get_credentials(char *ssid, size_t ssid_len, char *pw, size_t pw_len)
{
    nvs_handle_t h;
    esp_err_t e = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (e) return e;
    size_t l = ssid_len; e = nvs_get_str(h, "wifi_name", ssid, &l);
    if (e) { nvs_close(h); return e; }
    l = pw_len; e = nvs_get_str(h, "wifi_pwd", pw, &l);
    nvs_close(h);
    return e;
}

esp_err_t provisioning_save_credentials(const char *ssid, const char *password)
{
    save_key_to_nvs("wifi_name", ssid);
    save_key_to_nvs("wifi_pwd", password);
    return ESP_OK;
}

void provisioning_ble_connect_wifi(void)
{
    char wifi_name[64] = {0};
    char wifi_pwd[64] = {0};
    {
        nvs_handle_t h;
        if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
            size_t l = sizeof(wifi_name);
            nvs_get_str(h, "wifi_name", wifi_name, &l);
            l = sizeof(wifi_pwd);
            nvs_get_str(h, "wifi_pwd", wifi_pwd, &l);
            nvs_close(h);
        }
    }

    if (strlen(wifi_name) == 0) {
        ESP_LOGE(TAG, "No wifi credentials found in NVS after BLE prov");
        {
            nvs_handle_t h;
            if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
                nvs_set_str(h, "_ble_temp_", "0");
                nvs_commit(h);
                nvs_close(h);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(500));
        esp_restart();
        return;
    }

    ESP_LOGI(TAG, "BLE connecting to WiFi: %s", wifi_name);

    esp_err_t ws_ret = esp_wifi_stop();
    if (ws_ret != ESP_OK) { ESP_LOGW(TAG, "esp_wifi_stop: %d", ws_ret); }
    vTaskDelay(pdMS_TO_TICKS(100));
    esp_wifi_set_mode(WIFI_MODE_STA);

    wifi_config_t sta_config = {
        .sta = {
            .threshold = { .authmode = WIFI_AUTH_WPA2_PSK },
        },
    };
    strlcpy((char *)sta_config.sta.ssid, wifi_name, sizeof(sta_config.sta.ssid));
    strlcpy((char *)sta_config.sta.password, wifi_pwd, sizeof(sta_config.sta.password));
    esp_wifi_set_config(WIFI_IF_STA, &sta_config);
    esp_err_t wst_ret = esp_wifi_start();
    if (wst_ret != ESP_OK) { ESP_LOGE(TAG, "esp_wifi_start: %d", wst_ret); }
    esp_err_t wc_ret = esp_wifi_connect();
    if (wc_ret != ESP_OK) { ESP_LOGE(TAG, "esp_wifi_connect: %d", wc_ret); }

    bool connected = false;
    for (int i = 0; i < 15; i++) {
        vTaskDelay(pdMS_TO_TICKS(500));
        wifi_ap_record_t ap_info;
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            connected = true;
            break;
        }
    }

    if (!connected) {
        ESP_LOGE(TAG, "BLE WiFi connect failed after BLE prov");
        provisioning_ble_set_err("{ \"success\": false, \"message\": \"wifi连接失败，请检查账号密码。\" }");
        clear_local_all_data();
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
        return;
    }

    ESP_LOGI(TAG, "BLE WiFi connected successfully after BLE prov");

    bool bind_ok = true;
    if (s_on_bind_cb != NULL) {
        // 用堆分配构建绑定 JSON（局部数组 ~8KB 会导致栈溢出）
        char *all_json = malloc(2048);
        char *keys_list = malloc(1024);
        char *temp_json = malloc(2048);
        char *val = malloc(256);
        char *escaped = malloc(512);
        char *entry = malloc(2048);
        if (!all_json || !keys_list || !temp_json || !val || !escaped || !entry) {
            ESP_LOGE(TAG, "bind JSON malloc failed, skipping bind");
            if (all_json) free(all_json);
            if (keys_list) free(keys_list);
            if (temp_json) free(temp_json);
            if (val) free(val);
            if (escaped) free(escaped);
            if (entry) free(entry);
        } else {
            all_json[0] = 0;
            nvs_handle_t h;
            if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
                keys_list[0] = 0;
                size_t len = 1024;
                if (nvs_get_str(h, "_keys_list_", keys_list, &len) == ESP_OK) {
                    strcpy(temp_json, "{");
                    char *p = keys_list;
                    bool first = true;
                    while (p && *p) {
                        char *comma = strchr(p, ',');
                        if (comma) *comma = 0;
                        if (strcmp(p, "_keys_list_") != 0 && strcmp(p, "_ble_temp_") != 0) {
                            val[0] = 0;
                            size_t vlen = 256;
                            if (nvs_get_str(h, p, val, &vlen) == ESP_OK) {
                                escaped[0] = 0;
                                int si = 0;
                                for (int vi = 0; val[vi] && si < 510; vi++) {
                                    if (val[vi] == '"' || val[vi] == '\\') escaped[si++] = '\\';
                                    escaped[si++] = val[vi];
                                }
                                escaped[si] = 0;
                                snprintf(entry, 2048, "\"%s\":\"%s\"", p, escaped);
                                size_t cur = strlen(temp_json);
                                size_t entry_len = strlen(entry);
                                size_t need = entry_len + (first ? 0 : 1) + 2; // 逗号 + "}" + 裕量
                                if (cur + need < 2048) {
                                    if (!first) strcat(temp_json, ",");
                                    first = false;
                                    strcat(temp_json, entry);
                                } else {
                                    ESP_LOGW(TAG, "temp_json 溢出，停止拼接");
                                    break;
                                }
                            }
                        }
                        if (comma) { *comma = ','; p = comma + 1; }
                        else break;
                    }
                    uint8_t mac[6] = {0};
                    esp_read_mac(mac, ESP_MAC_WIFI_STA);
                    char mac_str[18];
                    snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
                    char dev_entry[128];
                    snprintf(dev_entry, sizeof(dev_entry), "\"device_id\":\"%s\"", mac_str);
                    {
                        size_t cur = strlen(temp_json);
                        size_t need = strlen(dev_entry) + (first ? 0 : 1) + 2; // 逗号 + "}" + 裕量
                        if (cur + need < 2048) {
                            if (!first) strcat(temp_json, ",");
                            strcat(temp_json, dev_entry);
                        } else {
                            ESP_LOGW(TAG, "temp_json 溢出，跳过 dev_entry");
                        }
                        strcat(temp_json, "}");
                    }
                    if (strlen(temp_json) + 1 < 2048) {
                        strcpy(all_json, temp_json);
                    } else {
                        ESP_LOGW(TAG, "all_json 溢出，截断");
                        all_json[0] = 0;
                    }
                }
                nvs_close(h);
            }
            char *bind_result = s_on_bind_cb(all_json);
            if (bind_result) {
                cJSON *res_json = cJSON_Parse(bind_result);
                if (res_json) {
                    cJSON *success_item = cJSON_GetObjectItem(res_json, "success");
                    if (cJSON_IsBool(success_item)) {
                        bind_ok = cJSON_IsTrue(success_item);
                    }
                    cJSON_Delete(res_json);
                }
                free(bind_result);
            }
            free(all_json);
            free(keys_list);
            free(temp_json);
            free(val);
            free(escaped);
            free(entry);
        }
    }

    if (bind_ok) {
        {
            nvs_handle_t h;
            if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
                nvs_set_str(h, "_ble_temp_", "0");
                nvs_commit(h);
                nvs_close(h);
            }
        }
        ESP_LOGI(TAG, "Device bind success, restarting...");
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    } else {
        ESP_LOGW(TAG, "Device bind failed, clearing data and restarting...");
        clear_local_all_data();
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
    }
}

esp_err_t provisioning_start(void)
{
#if CONFIG_PROV_TYPE_BLE
    ESP_LOGI(TAG, "Starting BLE prov...");
    return ble_prov_start();
#elif CONFIG_PROV_TYPE_AP
    ESP_LOGI(TAG, "Starting AP prov...");
    return ap_prov_start();
#else
    ESP_LOGE(TAG, "No prov method");
    return ESP_FAIL;
#endif
}

void provisioning_stop(void)
{
#if CONFIG_PROV_TYPE_BLE
    ble_prov_stop();
#elif CONFIG_PROV_TYPE_AP
    ap_prov_stop();
#endif
}

// ==================== GATTS 回调（与旧客户端完全一致的 UUID） ====================
static void gatts_h(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if, esp_ble_gatts_cb_param_t *param)
{
    switch (event) {
    case ESP_GATTS_REG_EVT:
        s_gatts_if = gatts_if;
        {
            esp_gatt_srvc_id_t sid = {
                .id = { .uuid = { .len = ESP_UUID_LEN_16, .uuid = { .uuid16 = BLE_SERVICE_UUID } }, .inst_id = 0 },
                .is_primary = true,
            };
            esp_ble_gatts_create_service(gatts_if, &sid, 5);
        }
        break;
    case ESP_GATTS_CREATE_EVT:
        s_service_handle = param->create.service_handle;
        {
            esp_bt_uuid_t uuid = { .len = ESP_UUID_LEN_16, .uuid = { .uuid16 = BLE_CHAR_UUID } };
            esp_ble_gatts_add_char(s_service_handle, &uuid,
                ESP_GATT_PERM_READ | ESP_GATT_PERM_WRITE,
                ESP_GATT_CHAR_PROP_BIT_READ | ESP_GATT_CHAR_PROP_BIT_WRITE | ESP_GATT_CHAR_PROP_BIT_NOTIFY,
                NULL, NULL);
        }
        break;
    case ESP_GATTS_ADD_CHAR_EVT:
        s_char_handle = param->add_char.attr_handle;
        esp_ble_gatts_start_service(s_service_handle);
        // 服务已启动，配置广告数据
        {
            esp_ble_adv_data_t ad = {
                .set_scan_rsp = false, .include_name = true, .include_txpower = false,
                .min_interval = 0x0006, .max_interval = 0x0010, .appearance = 0x00,
                .manufacturer_len = 0, .p_manufacturer_data = NULL,
                .service_data_len = 0, .p_service_data = NULL,
                .service_uuid_len = 0, .p_service_uuid = NULL,
                .flag = (ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT),
            };
            esp_ble_gap_config_adv_data(&ad);
            esp_ble_adv_data_t scan_rsp = {
                .set_scan_rsp = true, .include_name = true, .include_txpower = false,
                .min_interval = 0x0006, .max_interval = 0x0010, .appearance = 0x00,
                .manufacturer_len = 0, .p_manufacturer_data = NULL,
                .service_data_len = 0, .p_service_data = NULL,
                .service_uuid_len = 0, .p_service_uuid = NULL,
                .flag = 0,
            };
            esp_ble_gap_config_adv_data(&scan_rsp);
        }
        break;
    case ESP_GATTS_CONNECT_EVT:
        s_is_connected = true; s_conn_id = param->connect.conn_id; s_ble_buffer_len = 0;
        esp_ble_gap_stop_advertising();
        {
            esp_gatt_status_t st;
            if (s_ble_err_pending) {
                st = esp_ble_gatts_send_indicate(s_gatts_if, s_conn_id, s_char_handle,
                    strlen(s_ble_err_msg), (uint8_t *)s_ble_err_msg, false);
                s_ble_err_pending = false;
            } else {
                const char *init_val = "HI ESP-AI";
                st = esp_ble_gatts_send_indicate(s_gatts_if, s_conn_id, s_char_handle,
                    strlen(init_val), (uint8_t *)init_val, false);
            }
            if (st != ESP_GATT_OK) {
                ESP_LOGW(TAG, "send init indicate failed: %d", st);
            }
        }
        break;
    case ESP_GATTS_DISCONNECT_EVT:
        s_is_connected = false; s_ble_buffer_len = 0;
        s_adv_config_done = 0;
        {
            // 重新配置并启动广播
            esp_ble_adv_data_t ad = {
                .set_scan_rsp = false, .include_name = true, .include_txpower = false,
                .min_interval = 0x0006, .max_interval = 0x0010, .appearance = 0x00,
                .manufacturer_len = 0, .p_manufacturer_data = NULL,
                .service_data_len = 0, .p_service_data = NULL,
                .service_uuid_len = 0, .p_service_uuid = NULL,
                .flag = (ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT),
            };
            esp_ble_gap_config_adv_data(&ad);
            esp_ble_adv_data_t scan_rsp = {
                .set_scan_rsp = true, .include_name = true, .include_txpower = false,
                .min_interval = 0x0006, .max_interval = 0x0010, .appearance = 0x00,
                .manufacturer_len = 0, .p_manufacturer_data = NULL,
                .service_data_len = 0, .p_service_data = NULL,
                .service_uuid_len = 0, .p_service_uuid = NULL,
                .flag = 0,
            };
            esp_ble_gap_config_adv_data(&scan_rsp);
        }
        break;
    case ESP_GATTS_WRITE_EVT:
        if (!param->write.is_prep) {
            size_t wl = param->write.len;
            const uint8_t *wd = param->write.value;

            // 检查是否是结束标记
            if (wl == strlen(EOT_MARKER) && memcmp(wd, EOT_MARKER, wl) == 0) {
                ESP_LOGI(TAG, "BLE received EOT marker, processing complete data...");
                process_ble_complete();
                return;
            }

            // 追加数据到缓冲区
            size_t sp = sizeof(s_ble_buffer) - s_ble_buffer_len - 1;
            if (wl > sp) {
                ESP_LOGW(TAG, "BLE buf overflow, dropped %d bytes", wl - (int)sp);
                wl = sp;  // 只写能写下的部分，不丢弃已有数据
            }
            if (wl > 0) {
                memcpy(s_ble_buffer + s_ble_buffer_len, wd, wl);
                s_ble_buffer_len += wl;
                s_ble_buffer[s_ble_buffer_len] = 0;
            }

            ESP_LOGD(TAG, "BLE chunk appended, total: %d bytes", s_ble_buffer_len);
        }
        break;
    default:
        break;
    }
}
