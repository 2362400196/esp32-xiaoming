/*
 * provisioning.c - BLE配网 (NimBLE版)
 * 与 esp-ai-client 的 open_ble_server.cpp 功能一致:
 *   - UUID: Service=0xBAAD, Char=0xF00D
 *   - 分块接收JSON数据，"--END--"标记结束
 *   - 保存到NVS后重启
 */
#include "provisioning.h"
#include "provisioning_page.h"
#include "config.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "cJSON.h"
#include "esp_http_server.h"
#include "string.h"
#include "stdlib.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"

static const char *TAG = "provisioning";

#define NVS_NAMESPACE "esp-ai-kv"
#define BLE_SERVICE_UUID 0xBAAD
#define BLE_CHAR_UUID    0xF00D
#define EOT_MARKER "--END--"
#define AP_PROVISION_PASSWORD "esp-ai-setup"

static bool s_ble_prov_running = false;
static bool s_is_connected = false;
static uint16_t s_conn_handle;
static uint16_t s_char_val_handle;
static provisioning_on_bind_cb_t s_on_bind_cb = NULL;
static uint8_t s_own_addr_type = BLE_OWN_ADDR_RANDOM;  // 广播地址类型（sync 回调中确定）

// BLE接收缓冲区
#define BLE_BUF_SIZE 2048
static char s_ble_buffer[BLE_BUF_SIZE];
static size_t s_ble_buffer_len = 0;

// BLE错误消息（下次连接时发送）
static char s_ble_err_msg[256] = "";
static bool s_ble_err_pending = false;

static void bleprph_on_sync(void);
static const char *ble_addr_str(const uint8_t *addr);
static void process_ble_complete(void);
static void save_key_to_nvs(const char *key, const char *value);

// ==================== 工具函数 ====================
static const char *ble_addr_str(const uint8_t *addr)
{
    static char buf[18];
    snprintf(buf, sizeof(buf), "%02X:%02X:%02X:%02X:%02X:%02X",
             addr[0], addr[1], addr[2], addr[3], addr[4], addr[5]);
    return buf;
}

static void clear_local_all_data(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
        nvs_erase_all(h);
        nvs_commit(h);
        nvs_close(h);
    }
}

// URL解码（与esp-ai-client的url_decode一致）
static void url_decode(const char *src, int src_len, char *dst, int dst_len)
{
    int si = 0, di = 0;
    while (si < src_len && di < dst_len - 1) {
        if (src[si] == '%' && si + 2 < src_len) {
            char hex[3] = {src[si+1], src[si+2], 0};
            dst[di++] = (char)strtol(hex, NULL, 16);
            si += 3;
        } else if (src[si] == '+') {
            dst[di++] = ' ';
            si++;
        } else {
            dst[di++] = src[si++];
        }
    }
    dst[di] = 0;
}

// ==================== BLE Characteristic 访问回调 ====================
static int gatt_svr_chr_access(uint16_t conn_handle, uint16_t attr_handle,
                                struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    switch (ctxt->op) {
    case BLE_GATT_ACCESS_OP_READ_CHR:
        // 返回当前数据（读操作，返回空）
        os_mbuf_append(ctxt->om, "", 0);
        return 0;

    case BLE_GATT_ACCESS_OP_WRITE_CHR: {
        // 获取写入数据
        size_t wl = OS_MBUF_PKTLEN(ctxt->om);
        if (wl > 0) {
            char *wd = malloc(wl + 1);
            if (!wd) return BLE_ATT_ERR_INSUFFICIENT_RES;
            int rc = ble_hs_mbuf_to_flat(ctxt->om, wd, wl, NULL);
            if (rc != 0) { free(wd); return BLE_ATT_ERR_UNLIKELY; }
            wd[wl] = 0;

            // 检查是否是结束标记（精确匹配，与 Bluedroid 版本一致）
            // strncmp(wd, EOT_MARKER, wl) 有两个缺陷：
            //   1) wl < strlen(EOT_MARKER) 时前缀匹配会误触发（如 "--" 被当作 EOT）
            //   2) wl > strlen(EOT_MARKER) 时尾部换行会导致漏匹配
            if (wl == strlen(EOT_MARKER) && memcmp(wd, EOT_MARKER, wl) == 0) {
                ESP_LOGI(TAG, "BLE received EOT marker");
                free(wd);
                process_ble_complete();
                return 0;
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
            ESP_LOGD(TAG, "BLE chunk: %d bytes, total: %d", wl, s_ble_buffer_len);
            free(wd);
        }
        return 0;
    }
    default:
        return BLE_ATT_ERR_UNLIKELY;
    }
}

// ==================== GATT Service 定义 ====================
static const struct ble_gatt_svc_def gatt_svr_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(BLE_SERVICE_UUID),
        .characteristics = (struct ble_gatt_chr_def[]) { {
            .uuid = BLE_UUID16_DECLARE(BLE_CHAR_UUID),
            .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_NOTIFY,
            .access_cb = gatt_svr_chr_access,
        }, {
            0, /* No more characteristics */
        } },
    },
    {
        0, /* No more services */
    },
};

// ==================== GAP 事件回调 ====================
static int gap_event_cb(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            s_conn_handle = event->connect.conn_handle;
            s_is_connected = true;
            s_ble_buffer_len = 0;
            struct ble_gap_conn_desc desc;
            if (ble_gap_conn_find(s_conn_handle, &desc) == 0) {
                ESP_LOGI(TAG, "BLE connected: %s",
                         ble_addr_str(desc.peer_id_addr.val));
            }
            // 停止广播
            ble_gap_adv_stop();

            // 发送初始通知
            struct ble_gap_conn_desc desc2;
            if (ble_gap_conn_find(s_conn_handle, &desc2) == 0) {
                const char *msg = s_ble_err_pending ? s_ble_err_msg : "HI ESP-AI";
                struct os_mbuf *om = ble_hs_mbuf_from_flat(msg, strlen(msg));
                if (om) {
                    ble_gatts_notify_custom(s_conn_handle, s_char_val_handle, om);
                }
                else { ESP_LOGD(TAG, "notify alloc fail"); }
                s_ble_err_pending = false;
            }
        } else {
            ESP_LOGE(TAG, "BLE connect failed: %d", event->connect.status);
        }
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        s_is_connected = false;
        s_ble_buffer_len = 0;
        ESP_LOGI(TAG, "BLE disconnected, reason: %d", event->disconnect.reason);
        // 重新开始广播（使用与初始广播一致的地址类型）
        ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER,
                          NULL, gap_event_cb, NULL);
        return 0;

    case BLE_GAP_EVENT_ADV_COMPLETE:
        ESP_LOGI(TAG, "BLE advertising complete");
        return 0;

    case BLE_GAP_EVENT_NOTIFY_TX:
        return 0;

    default:
        return 0;
    }
}

// ==================== 处理完整的 BLE 数据 ====================
static void process_ble_complete(void)
{
    if (s_ble_buffer_len == 0) return;

    ESP_LOGI(TAG, "Processing BLE complete data (%d bytes)", s_ble_buffer_len);
    ESP_LOGD(TAG, "Raw: %d bytes received", (int)s_ble_buffer_len);

    // URL解码（用堆分配避免 NimBLE 任务栈溢出，缓冲区与 s_ble_buffer 等大）
    char *decoded = malloc(BLE_BUF_SIZE);
    if (!decoded) { ESP_LOGE(TAG, "malloc failed"); return; }
    memset(decoded, 0, BLE_BUF_SIZE);
    url_decode(s_ble_buffer, s_ble_buffer_len, decoded, BLE_BUF_SIZE);
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

    // JSON解析
    cJSON *json = cJSON_Parse(decoded);
    if (!json) {
        ESP_LOGE(TAG, "JSON parse failed");
        provisioning_ble_set_err("{ \"success\": false, \"message\": \"数据格式错误\" }");
        free(decoded);
        s_ble_buffer_len = 0;
        return;
    }

    // 遍历所有键值对，写入NVS（save_key_to_nvs 会自动维护 _keys_list_）
    int key_count = 0;
    cJSON *item = NULL;
    cJSON_ArrayForEach(item, json) {
        if (cJSON_IsString(item)) {
            const char *key = item->string;
            const char *val = item->valuestring;
            // 敏感字段遮蔽值
            const char *sensitive_keys[] = {"wifi_pwd", "password", "api_key", "key", "secret", NULL};
            bool is_sensitive = false;
            for (int si = 0; sensitive_keys[si]; si++) {
                if (strcmp(key, sensitive_keys[si]) == 0) { is_sensitive = true; break; }
            }
            if (is_sensitive) {
                ESP_LOGI(TAG, "Save: %s = ******", key);
            } else {
                ESP_LOGI(TAG, "Save: %s = %s", key, val);
            }
            save_key_to_nvs(key, val);
            key_count++;
        }
    }
    cJSON_Delete(json);
    ESP_LOGI(TAG, "Saved %d keys to NVS", key_count);

    free(decoded);

    // 设置 BLE 临时标记（与旧客户端一致）
    save_key_to_nvs("_ble_temp_", "1");
    ESP_LOGI(TAG, "BLE prov data saved, _ble_temp_ set to 1");

    // 清空缓冲区
    s_ble_buffer_len = 0;

    ESP_LOGI(TAG, "BLE provisioning data saved, restarting...");
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}

// ==================== GATT Service 注册回调 ====================
static void gatt_svr_register_cb(struct ble_gatt_register_ctxt *ctxt, void *arg)
{
    char buf[BLE_UUID_STR_LEN];
    switch (ctxt->op) {
    case BLE_GATT_REGISTER_OP_SVC:
        ESP_LOGD(TAG, "GATT service registered: uuid=%s handle=%d",
                 ble_uuid_to_str(ctxt->svc.svc_def->uuid, buf),
                 ctxt->svc.handle);
        break;
    case BLE_GATT_REGISTER_OP_CHR:
        s_char_val_handle = ctxt->chr.def_handle;
        ESP_LOGD(TAG, "GATT characteristic registered: uuid=%s def_handle=%d val_handle=%d",
                 ble_uuid_to_str(ctxt->chr.chr_def->uuid, buf),
                 ctxt->chr.def_handle, ctxt->chr.val_handle);
        break;
    default:
        break;
    }
}

// ==================== 初始化 GATT Service ====================
static void gatt_svr_init(void)
{
    ble_svc_gap_init();
    // ble_svc_gatt_init() called by ble_svc_gap_init
    int rc = ble_gatts_count_cfg(gatt_svr_svcs);
    if (rc != 0) { ESP_LOGE(TAG, "ble_gatts_count_cfg: %d", rc); return; }
    rc = ble_gatts_add_svcs(gatt_svr_svcs);
    if (rc != 0) { ESP_LOGE(TAG, "ble_gatts_add_svcs: %d", rc); return; }
}

// ==================== NimBLE Host 任务 ====================
static void host_task(void *arg)
{
    ESP_LOGI(TAG, "NimBLE host task started");
    nimble_port_run();
    ESP_LOGI(TAG, "NimBLE host task ended");
    nimble_port_freertos_deinit();
}

// ==================== 启动 BLE 配网 ====================
static esp_err_t ble_prov_start(void)
{
    s_ble_buffer_len = 0;
    s_is_connected = false;
    s_ble_prov_running = true;

    // 初始化NimBLE
    int rc = nimble_port_init();
    if (rc != 0) { ESP_LOGE(TAG, "nimble_port_init: %d", rc); return ESP_FAIL; }

    // 设置NimBLE配置（必须在 nimble_port_init 之后、nimble_port_run 之前）
    ble_hs_cfg.sync_cb = bleprph_on_sync;
    ble_hs_cfg.gatts_register_cb = gatt_svr_register_cb;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_NO_IO;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 1;
    ble_hs_cfg.sm_sc = 1;

    // 初始化GATT services
    gatt_svr_init();

    // 设置设备名（必须在 gatt_svr_init 之后，否则被 ble_svc_gap_init 覆盖）
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char dn[32];
    snprintf(dn, sizeof(dn), "ESP-AI:%02X%02X", mac[4], mac[5]);
    rc = ble_svc_gap_device_name_set(dn);
    if (rc != 0) { ESP_LOGE(TAG, "set device name: %d", rc); }


    // 启动NimBLE主机任务（sync回调将在主机同步后触发）
    nimble_port_freertos_init(host_task);

    // 广播在 bleprph_on_sync 回调中启动
    
    ESP_LOGI(TAG, "BLE: %s, UUID: BAAD/F00D", dn);
    display_show_status("请使用App配置网络");
    return ESP_OK;
}

static void ble_prov_stop(void)
{
    if (!s_ble_prov_running) return;
    s_ble_prov_running = false;
    if (s_is_connected) {
        ble_gap_terminate(s_conn_handle, BLE_ERR_REM_USER_CONN_TERM);
    }
    nimble_port_stop();
    nimble_port_deinit();
    ESP_LOGI(TAG, "BLE prov stopped");
}

// ==================== NimBLE 同步回调 ====================
// 在ble_hs同步完成后，开始广播
// 需要从host_task的同步回调中调用
static void bleprph_on_sync(void)
{
    ESP_LOGI(TAG, "sync callback fired");
    // 生成并设置随机静态地址
    uint8_t rnd_addr[6];
    esp_fill_random(rnd_addr, 6);
    rnd_addr[5] |= 0xC0;  // bits 47-46 = 11 (静态随机地址标志)
    int rc = ble_hs_id_set_rnd(rnd_addr);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_hs_id_set_rnd failed: %d, falling back to public addr", rc);
        s_own_addr_type = BLE_OWN_ADDR_PUBLIC;
    } else {
        s_own_addr_type = BLE_OWN_ADDR_RANDOM;
    }

    // 开始广播（使用自动选择的地址类型）
    struct ble_gap_adv_params adv_params = {
        .conn_mode = BLE_GAP_CONN_MODE_UND,
        .disc_mode = BLE_GAP_DISC_MODE_GEN,
        .itvl_min = 0x0064,
        .itvl_max = 0x00C8,
        .channel_map = 0x07,
    };

    // 配置广播数据（与 bleprph 示例一致）
    struct ble_hs_adv_fields adv_fields;
    memset(&adv_fields, 0, sizeof(adv_fields));
    adv_fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    adv_fields.tx_pwr_lvl_is_present = 1;
    adv_fields.tx_pwr_lvl = BLE_HS_ADV_TX_PWR_LVL_AUTO;
    const char *name = ble_svc_gap_device_name();
    adv_fields.name = (uint8_t *)name;
    adv_fields.name_len = strlen(name);
    adv_fields.name_is_complete = 1;
    adv_fields.uuids16 = (ble_uuid16_t[]) {
        BLE_UUID16_INIT(BLE_SERVICE_UUID)
    };
    adv_fields.num_uuids16 = 1;
    adv_fields.uuids16_is_complete = 1;
    int adv_rc = ble_gap_adv_set_fields(&adv_fields);
    if (adv_rc != 0) {
        ESP_LOGW(TAG, "adv set fields: %d", adv_rc);
    }

    int adv_rc2 = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER,
                           &adv_params, gap_event_cb, NULL);
    if (adv_rc2 != 0) {
        ESP_LOGE(TAG, "advertising start: %d (own_addr_type=%d)", adv_rc2, s_own_addr_type);
        // 如果随机地址广播失败，回退到公共地址重试一次
        if (s_own_addr_type == BLE_OWN_ADDR_RANDOM) {
            ESP_LOGW(TAG, "retrying with public address...");
            s_own_addr_type = BLE_OWN_ADDR_PUBLIC;
            adv_rc2 = ble_gap_adv_start(s_own_addr_type, NULL, BLE_HS_FOREVER,
                               &adv_params, gap_event_cb, NULL);
            if (adv_rc2 != 0) {
                ESP_LOGE(TAG, "advertising start (public) also failed: %d", adv_rc2);
            } else {
                ESP_LOGI(TAG, "BLE advertising started successfully (public addr)");
            }
        }
    } else {
        ESP_LOGI(TAG, "BLE advertising started successfully");
    }
}

// ==================== 保存到NVS（维护 _keys_list_，与 Arduino 版 set_local_data 一致） ====================
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
        esp_err_t el = nvs_set_str(h, "_keys_list_", keys_list);
        if (el != ESP_OK) {
            ESP_LOGE(TAG, "nvs_set_str _keys_list_ failed: %d", el);
        }
    }

    esp_err_t ek = nvs_set_str(h, key, value);
    if (ek != ESP_OK) {
        ESP_LOGE(TAG, "nvs_set_str %s failed: %d", key, ek);
        nvs_close(h);
        return;
    }
    nvs_commit(h);
    nvs_close(h);
}

// ==================== 公开接口 ====================
void provisioning_set_on_bind_cb(provisioning_on_bind_cb_t cb)
{
    s_on_bind_cb = cb;
}

void provisioning_ble_set_err(const char *err_msg)
{
    strncpy(s_ble_err_msg, err_msg, sizeof(s_ble_err_msg) - 1);
    s_ble_err_pending = true;
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

esp_err_t provisioning_get_credentials(char *ssid, size_t ssid_len,
                                        char *pw, size_t pw_len)
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

    // 设置 WiFi STA 模式并连接（WiFi 已在 wifi_init() 中初始化但未启动）
    esp_wifi_set_mode(WIFI_MODE_STA);

    wifi_config_t sta_config = {
        .sta = { .threshold = { .authmode = WIFI_AUTH_WPA2_PSK } },
    };
    strlcpy((char *)sta_config.sta.ssid, wifi_name, sizeof(sta_config.sta.ssid));
    strlcpy((char *)sta_config.sta.password, wifi_pwd, sizeof(sta_config.sta.password));
    esp_wifi_set_config(WIFI_IF_STA, &sta_config);
    esp_wifi_start();
    esp_wifi_connect();

    // 增加连接超时到 20 秒（40 次 * 500ms），适应不同路由器
    bool connected = false;
    for (int i = 0; i < 40; i++) {
        vTaskDelay(pdMS_TO_TICKS(500));
        wifi_ap_record_t ap_info;
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
            connected = true;
            break;
        }
        if (i % 8 == 7) {
            ESP_LOGI(TAG, "BLE WiFi connecting... (%d/%d)", i + 1, 40);
        }
    }

    if (!connected) {
        ESP_LOGE(TAG, "BLE WiFi connect failed after BLE prov (timeout 20s)");
        // 连接失败时不清除配网数据，保留凭据以便下次重试
        // 只清除 _ble_temp_ 标记，让设备进入正常配网流程
        {
            nvs_handle_t h;
            if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
                nvs_set_str(h, "_ble_temp_", "0");
                nvs_commit(h);
                nvs_close(h);
            }
        }
        esp_wifi_stop();
        vTaskDelay(pdMS_TO_TICKS(1000));
        esp_restart();
        return;
    }

    ESP_LOGI(TAG, "BLE WiFi connected successfully after BLE prov");

    bool bind_ok = true;
    if (s_on_bind_cb != NULL) {
        // 用堆分配构建绑定 JSON（局部数组 ~8KB 会导致 main 任务栈溢出）
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
                    snprintf(mac_str, sizeof(mac_str), "%02X:%02X:%02X:%02X:%02X:%02X",
                             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
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

// ==================== AP 配网（保留） ====================
static char s_ap_ssid[64], s_ap_password[64];
static httpd_handle_t s_ap_server = NULL;
static bool s_ap_prov_running = false;

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
    wifi_config_t apc = { .ap = { .ssid_len = 0, .channel = 1, .max_connection = 4, .authmode = WIFI_AUTH_WPA2_PSK } };
    snprintf((char*)apc.ap.ssid, sizeof(apc.ap.ssid),
        "ESP-AI-AP-%02X%02X", (uint8_t)(esp_random()&0xFF), (uint8_t)(esp_random()&0xFF));
    strlcpy((char *)apc.ap.password, AP_PROVISION_PASSWORD, sizeof(apc.ap.password));
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
    display_show_status("连接热点进行配置");
    return ESP_OK;
}

static void ap_prov_stop(void)
{
    if (!s_ap_prov_running) return;
    s_ap_prov_running = false;
    if (s_ap_server) { httpd_stop(s_ap_server); s_ap_server = NULL; }
    ESP_LOGI(TAG, "AP prov stopped");
}

// ==================== 配网入口 ====================
esp_err_t provisioning_start(void)
{
#if CONFIG_PROV_TYPE_BLE
    ESP_LOGI(TAG, "Starting BLE prov (NimBLE)...");
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

void provisioning_clear_all(void)
{
    ESP_LOGW(TAG, "清除所有配置数据，准备进入配网模式");
    clear_local_all_data();
    // 延迟后重启，设备会检测到无WiFi凭据进入配网模式
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}
