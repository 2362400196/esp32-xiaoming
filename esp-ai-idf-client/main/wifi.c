#include "config.h"
#include "provisioning.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "nvs.h"

// WiFi 缓冲数量：S3（有 PSRAM）用 32 动态缓冲；C3 无 PSRAM 必须收紧，
// 否则 WiFi 吃掉太多堆导致音频/唤醒初始化失败
#ifdef CONFIG_IDF_TARGET_ESP32C3
#define ESP_AI_WIFI_DYN  8
#define ESP_AI_WIFI_CACHE 4
#define ESP_AI_WIFI_MGMT    16
#define ESP_AI_WIFI_STATIC_RX 4
#else
#define ESP_AI_WIFI_DYN  32
#define ESP_AI_WIFI_CACHE 8
#define ESP_AI_WIFI_MGMT    32
#define ESP_AI_WIFI_STATIC_RX 6
#endif

static const char *TAG = "wifi";

EventGroupHandle_t s_wifi_event_group;
// 临界区自旋锁：保护 s_retry_num / s_provisioning_mode 的跨任务访问
// （事件循环任务 event_handler 与主任务 wifi_init 并发读写）
static portMUX_TYPE s_wifi_lock = portMUX_INITIALIZER_UNLOCKED;
static int s_retry_num = 0;
static esp_netif_t *s_sta_netif = NULL;
// volatile: 跨任务访问（事件任务写、其他任务读），int8_t 写入在 ESP32 上原子
volatile int8_t s_wifi_rssi = -127;  // 当前 WiFi RSSI 值，供 eeui_port 信号图标使用（-127 表示未连接）

static bool s_provisioning_mode = false;

// 事件处理器 instance handle（静态），用于避免重复注册
static esp_event_handler_instance_t s_wifi_inst_any_id = NULL;
static esp_event_handler_instance_t s_wifi_inst_got_ip = NULL;

static void event_handler(void *arg, esp_event_base_t event_base,
                          int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        bool prov_mode;
        taskENTER_CRITICAL(&s_wifi_lock);
        prov_mode = s_provisioning_mode;
        taskEXIT_CRITICAL(&s_wifi_lock);
        if (!prov_mode) {
            esp_wifi_connect();
        }
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        bool prov_mode;
        taskENTER_CRITICAL(&s_wifi_lock);
        prov_mode = s_provisioning_mode;
        taskEXIT_CRITICAL(&s_wifi_lock);
        // 通知板级扩展组件（extras）：网络断开（esp_event 任务上下文，回调必须快速返回）
        board_extra_broadcast_event(BOARD_EVENT_NETWORK_DOWN, NULL);
        if (prov_mode) {
            return;
        }
        wifi_event_sta_disconnected_t *discon = (wifi_event_sta_disconnected_t *)event_data;
        s_wifi_rssi = -127;
        int retry;
        taskENTER_CRITICAL(&s_wifi_lock);
        retry = s_retry_num;
        taskEXIT_CRITICAL(&s_wifi_lock);
        ESP_LOGI(TAG, "WiFi断开, reason=%d, retry=%d/%d",
                 discon ? discon->reason : -1,
                 retry, WIFI_MAXIMUM_RETRY);
        bool should_retry;
        taskENTER_CRITICAL(&s_wifi_lock);
        should_retry = (s_retry_num < WIFI_MAXIMUM_RETRY);
        if (should_retry) {
            s_retry_num++;
        }
        taskEXIT_CRITICAL(&s_wifi_lock);
        if (should_retry) {
            esp_wifi_connect();
            ESP_LOGI(TAG, "重试连接WiFi...");
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
            ESP_LOGE(TAG, "WiFi连接失败");
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "获取到IP地址: " IPSTR, IP2STR(&event->ip_info.ip));
        // 通知板级扩展组件（extras）：网络就绪
        board_extra_broadcast_event(BOARD_EVENT_NETWORK_UP, NULL);
        taskENTER_CRITICAL(&s_wifi_lock);
        s_retry_num = 0;
        s_provisioning_mode = false;
        taskEXIT_CRITICAL(&s_wifi_lock);
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

// 清除 BLE 临时标记
static void clear_ble_temp_flag(void)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) == ESP_OK) {
        char ble_temp[4] = {0};
        size_t len = sizeof(ble_temp);
        if (nvs_get_str(h, "_ble_temp_", ble_temp, &len) == ESP_OK && strcmp(ble_temp, "1") == 0) {
            nvs_set_str(h, "_ble_temp_", "0");
            nvs_commit(h);
            ESP_LOGI(TAG, "BLE temp flag cleared after WiFi connected");
        }
        nvs_close(h);
    }
}

esp_err_t wifi_init(void)
{
    ESP_LOGI(TAG, "初始化WiFi...");

    // 检查 BLE 配网临时标记（与 esp-ai-client 一致）
    {
        nvs_handle_t h;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            char ble_temp[4] = {0};
            size_t len = sizeof(ble_temp);
            if (nvs_get_str(h, "_ble_temp_", ble_temp, &len) == ESP_OK && strcmp(ble_temp, "1") == 0) {
                nvs_close(h);
                ESP_LOGI(TAG, "检测到 BLE 配网临时标记(_ble_temp_=%s)，执行 BLE 配网后连接流程...", ble_temp);
                display_show_status("蓝牙配网中...");

                ESP_ERROR_CHECK(esp_netif_init());
                ESP_ERROR_CHECK(esp_event_loop_create_default());
                s_sta_netif = esp_netif_create_default_wifi_sta();

                wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
                // static_rx_buf_num=2 会导致 WebSocket 活跃时 HTTP 连接 SYN-ACK 被丢弃
                // 6 个静态 RX 缓冲区可同时处理 WS + HTTP + beacon + 管理帧
                cfg.static_rx_buf_num = ESP_AI_WIFI_STATIC_RX;
                cfg.dynamic_rx_buf_num = ESP_AI_WIFI_DYN;
                cfg.dynamic_tx_buf_num = ESP_AI_WIFI_DYN;
                cfg.cache_tx_buf_num = ESP_AI_WIFI_CACHE;
                cfg.tx_buf_type = 1;  // dynamic
                cfg.rx_mgmt_buf_type = 0; // static
                cfg.mgmt_sbuf_num = ESP_AI_WIFI_MGMT;
                cfg.static_tx_buf_num = 0;
                ESP_ERROR_CHECK(esp_wifi_init(&cfg));

                // 注册 WiFi/IP 事件处理器，确保协议栈正常工作
                s_wifi_event_group = xEventGroupCreate();
                // 使用静态 instance handle，避免重复注册（防止 BLE 配网路径与正常路径重复）
                if (s_wifi_inst_any_id == NULL) {
                    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                                    ESP_EVENT_ANY_ID, &event_handler, NULL, &s_wifi_inst_any_id));
                }
                if (s_wifi_inst_got_ip == NULL) {
                    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                                    IP_EVENT_STA_GOT_IP, &event_handler, NULL, &s_wifi_inst_got_ip));
                }

                // ble_connect_wifi 会在内部完成连接/绑定/重启
                provisioning_ble_connect_wifi();
                return ESP_OK;
            }
            nvs_close(h);
        }
    }

    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_sta_netif = esp_netif_create_default_wifi_sta();
#if CONFIG_PROV_TYPE_AP
    esp_netif_create_default_wifi_ap();
#endif

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    // static_rx_buf_num=2 会导致 WebSocket 活跃时 HTTP 连接 SYN-ACK 被丢弃
    // 6 个静态 RX 缓冲区可同时处理 WS + HTTP + beacon + 管理帧
    cfg.static_rx_buf_num = ESP_AI_WIFI_STATIC_RX;
    cfg.dynamic_rx_buf_num = ESP_AI_WIFI_DYN;
    cfg.dynamic_tx_buf_num = ESP_AI_WIFI_DYN;
    cfg.cache_tx_buf_num = ESP_AI_WIFI_CACHE;
    cfg.tx_buf_type = 1;  // dynamic
    cfg.rx_mgmt_buf_type = 0; // static
    cfg.mgmt_sbuf_num = ESP_AI_WIFI_MGMT;
    cfg.static_tx_buf_num = 0;
    // 打印可用内存用于调试
    ESP_LOGI(TAG, "WiFi init 前可用内部 RAM: %ld bytes",
             (long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    // 内存紧张时可能一次分配失败，重试 3 次
    esp_err_t wifi_err;
    for (int retry = 0; retry < 3; retry++) {
        wifi_err = esp_wifi_init(&cfg);
        if (wifi_err == ESP_OK) break;
        ESP_LOGW(TAG, "WiFi init 失败 (尝试 %d/3): %s 可用RAM:%ld",
                 retry + 1, esp_err_to_name(wifi_err),
                 (long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    ESP_ERROR_CHECK(wifi_err);

    esp_event_handler_instance_t instance_any_id;
    esp_event_handler_instance_t instance_got_ip;
    // 使用静态 instance handle 去重，避免与 BLE 配网路径重复注册同一回调
    if (s_wifi_inst_any_id == NULL) {
        ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT,
                        ESP_EVENT_ANY_ID, &event_handler, NULL, &s_wifi_inst_any_id));
    } else {
        instance_any_id = s_wifi_inst_any_id;
    }
    if (s_wifi_inst_got_ip == NULL) {
        ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT,
                        IP_EVENT_STA_GOT_IP, &event_handler, NULL, &s_wifi_inst_got_ip));
    } else {
        instance_got_ip = s_wifi_inst_got_ip;
    }
    (void)instance_any_id;  // 保留变量兼容（如需后续注销可使用 s_wifi_inst_* ）
    (void)instance_got_ip;

    if (provisioning_is_provisioned()) {
        ESP_LOGI(TAG, "发现已保存的WiFi凭据，直接连接...");

        char ssid[32] = {0};
        char password[64] = {0};
        esp_err_t err = provisioning_get_credentials(ssid, sizeof(ssid), password, sizeof(password));
        if (err == ESP_OK) {
            wifi_config_t wifi_config = {0};
            strlcpy((char *)wifi_config.sta.ssid, ssid, sizeof(wifi_config.sta.ssid));
            strlcpy((char *)wifi_config.sta.password, password, sizeof(wifi_config.sta.password));
            wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

            ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
            ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
            // 在 start 之前禁用省电模式，确保 DHCP 交换期间 WiFi 不休眠
            // （MIN_MODEM 会导致 DHCP DISCOVER/REQUEST 包丢失，IP 获取超时）
            esp_wifi_set_ps(WIFI_PS_NONE);
            ESP_ERROR_CHECK(esp_wifi_start());

            ESP_LOGI(TAG, "WiFi初始化完成，正在连接 %s...", ssid);

            // DHCP 响应可能较慢（尤其在信号弱或路由器繁忙时），等待 30 秒
            // 之前 15 秒导致部分设备关联成功但未获取到 IP 就超时进入配网模式
            EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                    WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                    pdFALSE, pdFALSE, pdMS_TO_TICKS(30000));

            if (bits & WIFI_CONNECTED_BIT) {
                ESP_LOGI(TAG, "WiFi连接成功");
                // 获取初始 RSSI
                wifi_ap_record_t ap_info;
                if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
                    s_wifi_rssi = ap_info.rssi;
                    ESP_LOGI(TAG, "RSSI: %d dBm", s_wifi_rssi);
                }
                clear_ble_temp_flag();
                esp_err_t ps_err = esp_wifi_set_ps(WIFI_PS_NONE);
                if (ps_err != ESP_OK) {
                    ESP_LOGW(TAG, "设置 WiFi 省电模式(WIFI_PS_NONE)失败: %s", esp_err_to_name(ps_err));
                }
                ESP_LOGI(TAG, "WiFi省电模式已禁用");
                return ESP_OK;
            } else {
                ESP_LOGW(TAG, "使用已保存凭据连接失败，进入配网模式...");
                esp_wifi_stop();
                taskENTER_CRITICAL(&s_wifi_lock);
                s_retry_num = 0;
                taskEXIT_CRITICAL(&s_wifi_lock);
                xEventGroupClearBits(s_wifi_event_group, WIFI_FAIL_BIT);
            }
        }
    }

    // 未配网或连接失败，进入配网模式
    taskENTER_CRITICAL(&s_wifi_lock);
    s_provisioning_mode = true;
    taskEXIT_CRITICAL(&s_wifi_lock);
    ESP_LOGI(TAG, "进入配网模式...");
    display_show_status("配网中...");

    esp_err_t ret = provisioning_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "配网启动失败");
        taskENTER_CRITICAL(&s_wifi_lock);
        s_provisioning_mode = false;
        taskEXIT_CRITICAL(&s_wifi_lock);
        return ESP_FAIL;
    }

    // 等待配网完成并连接WiFi
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
            WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
            pdFALSE, pdFALSE, portMAX_DELAY);

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "配网成功，WiFi已连接");
        provisioning_stop();
        clear_ble_temp_flag();
        esp_err_t ps_err2 = esp_wifi_set_ps(WIFI_PS_NONE);
        if (ps_err2 != ESP_OK) {
            ESP_LOGW(TAG, "设置 WiFi 省电模式(WIFI_PS_NONE)失败: %s", esp_err_to_name(ps_err2));
        }
        ESP_LOGI(TAG, "WiFi省电模式已禁用");
        return ESP_OK;
    } else {
        ESP_LOGE(TAG, "配网后WiFi连接失败");
        taskENTER_CRITICAL(&s_wifi_lock);
        s_provisioning_mode = false;
        taskEXIT_CRITICAL(&s_wifi_lock);
        return ESP_FAIL;
    }
}

/* ============ 断线自愈接口 ============ */
/* 查询 WiFi 是否真实连接（直接查 AP 连接记录，不依赖事件位——事件位在静默掉线时会陈旧） */
bool wifi_is_connected(void)
{
    wifi_ap_record_t ap_info;
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
        return true;
    }
    return false;
}

/* ============ 省电控制接口 ============ */
/* 待机省电：WiFi modem sleep（间隔唤醒收包，keepalive 30s 完全够用）；
 * 对话活跃：WIFI_PS_NONE 保证收发低延迟。
 * 注意：语音唤醒（纯 WakeNet）不依赖 WiFi，modem sleep 不影响唤醒触发；
 * 发送数据会立即唤醒 WiFi，唤醒→发 start 延迟 <50ms。
 * 由 power_manager_set_active() 在会话开始/结束时调用。 */
void wifi_set_power_save(bool enable)
{
    wifi_ps_type_t ps = enable ? WIFI_PS_MIN_MODEM : WIFI_PS_NONE;
    esp_err_t err = esp_wifi_set_ps(ps);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "WiFi 省电模式: %s", enable ? "MIN_MODEM（待机）" : "NONE（对话）");
    } else {
        ESP_LOGW(TAG, "设置 WiFi 省电模式失败: %s", esp_err_to_name(err));
    }
}

/* 强制重建 WiFi 连接：清陈旧状态位 -> 断开 -> 重连（供 websocket 断线自愈调用） */
void wifi_force_reconnect(void)
{
    ESP_LOGW(TAG, "WiFi force reconnect (self-heal)");
    xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    esp_wifi_disconnect();
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_wifi_connect();
}


