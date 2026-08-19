/**
 * ota_update.c - ESP32 固件 OTA 升级模块
 *
 * 流程（与 Arduino auto_update + ESPOTAManager 一致）：
 *   1. GET /sdk/query_new_ota?version=x&bin_id=x&is_official=x
 *   2. 解析 JSON：success / data.latest / data.bin_url
 *   3. 若 latest=false 且 bin_url 非空，执行固件下载 + OTA 写入
 *   4. 下载使用 esp_http_client 流式读取，写入 esp_ota_ops 备用分区
 *   5. 进度上报 WebSocket + 屏幕显示
 *   6. 完成后 esp_ota_set_boot_partition + esp_restart
 */

#include "ota_update.h"
#include "config.h"
#include "log_system.h"
#include "boards/board_interface.h"
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_wifi.h"
#include "cJSON.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "device_id.h"

static const char *TAG = "ota_update";

// OTA 状态
static volatile bool s_ota_updating = false;
static volatile bool s_ota_failed = false;
static volatile int s_ota_progress = 0;  // volatile: 跨任务/中断访问（WebSocket 上报、显示任务读取）
static char s_device_id[18] = {0};  // 设备 MAC 地址（与 Arduino device_id 一致）

// 外部函数声明
extern esp_err_t websocket_send_text(const char *text);
extern bool websocket_is_connected(void);

// 获取设备ID（使用 device_id.h 中的 device_id_get）
static void get_device_mac(char *mac_str, size_t len)
{
    device_id_get(mac_str, len);
}

// 发送 OTA 进度到服务端（与 Arduino updateProgressCallback 一致，包含 device_id）
static void send_ota_progress(int percent)
{
    if (!websocket_is_connected()) return;

    char msg[160];
    snprintf(msg, sizeof(msg),
             "{\"type\":\"ota_progress\",\"data\":%d,\"device_id\":\"%s\"}",
             percent, s_device_id);
    websocket_send_text(msg);
}

// 解析服务端响应，提取 bin_url
// 返回：1=需要更新，0=已是最新，-1=错误
static int parse_ota_response(const char *json_str, char *bin_url, size_t url_size)
{
    cJSON *root = cJSON_Parse(json_str);
    if (!root) {
        ESP_LOGE(TAG, "JSON 解析失败");
        return -1;
    }

    int result = -1;
    cJSON *success = cJSON_GetObjectItem(root, "success");
    if (success && cJSON_IsBool(success) && cJSON_IsTrue(success)) {
        cJSON *data = cJSON_GetObjectItem(root, "data");
        if (data) {
            cJSON *latest = cJSON_GetObjectItem(data, "latest");
            if (latest && cJSON_IsBool(latest) && !cJSON_IsTrue(latest)) {
                cJSON *url = cJSON_GetObjectItem(data, "bin_url");
                if (url && cJSON_IsString(url) && strlen(url->valuestring) > 0) {
                    strlcpy(bin_url, url->valuestring, url_size);
                    result = 1;  // 需要更新
                } else {
                    ESP_LOGW(TAG, "bin_url 为空，无需更新");
                    result = 0;
                }
            } else {
                ESP_LOGI(TAG, "已是最新版本");
                result = 0;  // 已是最新
            }
        }
    }

    cJSON_Delete(root);
    return result;
}

// 执行 HTTP OTA 下载并写入备用分区
static esp_err_t perform_ota_update(const char *firmware_url)
{
    ESP_LOGI(TAG, "开始 OTA 升级: %s", firmware_url);

    // 获取备用 OTA 分区
    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        ESP_LOGE(TAG, "找不到 OTA 分区");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "写入分区: %s (size=%lu)", update_partition->label, (unsigned long)update_partition->size);

    // 开始 OTA 会话
    esp_ota_handle_t update_handle = 0;
    esp_err_t err = esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &update_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin 失败: %s", esp_err_to_name(err));
        return err;
    }

    // 如果是 HTTPS 才使用证书验证，本地 HTTP 跳过（避免 TLS 超时）
    esp_http_client_config_t config = {
        .url = firmware_url,
        .timeout_ms = 30000,
        .keep_alive_enable = true,
    };
    if (strncmp(firmware_url, "https://", 8) == 0) {
        config.crt_bundle_attach = esp_crt_bundle_attach;
    } else {
        // 安全警告：HTTP 明文下载固件无法验证来源完整性与真实性，存在中间人篡改风险
        // 建议生产环境使用 HTTPS + 证书校验。此处仅为兼容性保留（如本地调试服务器）
        ESP_LOGW(TAG, "警告: 固件使用 HTTP 明文下载，无完整性/真实性验证（存在中间人风险），建议使用 HTTPS: %s", firmware_url);
    }

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "HTTP 客户端初始化失败");
        esp_ota_abort(update_handle);
        return ESP_FAIL;
    }

    err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP 连接失败: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        esp_ota_abort(update_handle);
        return err;
    }

    int content_length = esp_http_client_fetch_headers(client);
    if (content_length <= 0) {
        ESP_LOGW(TAG, "Content-Length 未知，继续流式下载");
    } else {
        ESP_LOGI(TAG, "固件大小: %d 字节", content_length);
    }

    // 流式下载并写入 OTA 分区
    char *buf = malloc(4096);
    if (!buf) {
        ESP_LOGE(TAG, "分配缓冲区失败");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        esp_ota_abort(update_handle);
        return ESP_ERR_NO_MEM;
    }

    int total_read = 0;
    int last_reported_percent = -1;

    while (1) {
        int read_len = esp_http_client_read(client, buf, 4096);
        if (read_len < 0) {
            ESP_LOGE(TAG, "HTTP 读取错误: %d", read_len);
            free(buf);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            esp_ota_abort(update_handle);
            return ESP_FAIL;
        }
        if (read_len == 0) {
            // 检查是否读完
            if (esp_http_client_is_complete_data_received(client)) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        // 写入 OTA 分区
        err = esp_ota_write(update_handle, buf, read_len);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write 失败: %s", esp_err_to_name(err));
            free(buf);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            esp_ota_abort(update_handle);
            return err;
        }

        total_read += read_len;

        // 上报进度
        if (content_length > 0) {
            // 使用 int64_t 计算避免 total_read * 100 在大固件下整数溢出
            int percent = (int)((int64_t)total_read * 100 / content_length);
            if (percent > 100) percent = 100;
            s_ota_progress = percent;

            // 每 5% 上报一次
            if (percent / 5 != last_reported_percent / 5) {
                last_reported_percent = percent;
                ESP_LOGI(TAG, "OTA 进度: %d%% (%d/%d)", percent, total_read, content_length);
                send_ota_progress(percent);
                display_show_ota_progress(percent);
            }
        }
    }

    free(buf);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    ESP_LOGI(TAG, "固件下载完成，共 %d 字节", total_read);

    // 完成 OTA 写入
    err = esp_ota_end(update_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end 失败: %s", esp_err_to_name(err));
        // esp_ota_end 失败后备用分区可能处于不一致状态，显式将启动分区
        // 还原为当前运行分区，避免下次启动误进入损坏的备用分区
        const esp_partition_t *running = esp_ota_get_running_partition();
        if (running) {
            esp_err_t rb_err = esp_ota_set_boot_partition(running);
            if (rb_err != ESP_OK) {
                ESP_LOGE(TAG, "回滚启动分区失败: %s", esp_err_to_name(rb_err));
            }
        }
        return err;
    }

    // 设置启动分区
    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition 失败: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "OTA 写入完成，准备重启...");
    s_ota_progress = 100;
    send_ota_progress(100);

    return ESP_OK;
}

esp_err_t ota_check_and_update(const char *server_base_url)
{
    if (!server_base_url || strlen(server_base_url) == 0) {
        ESP_LOGW(TAG, "服务器地址为空，跳过 OTA 检查");
        return ESP_ERR_INVALID_ARG;
    }

    // 无 OTA 备用分区（如 C3 单槽分区表）时直接跳过，
    // 避免每次连接后都白跑一次 HTTP 查询再报 "找不到 OTA 分区"
    if (esp_ota_get_next_update_partition(NULL) == NULL) {
        ESP_LOGI(TAG, "无 OTA 备用分区，跳过 OTA 检查（当前固件不支持在线升级）");
        return ESP_OK;
    }

    s_ota_updating = false;
    s_ota_failed = false;
    s_ota_progress = 0;

    // 获取设备 MAC 地址，用于 OTA 进度上报（与 Arduino device_id 一致）
    get_device_mac(s_device_id, sizeof(s_device_id));

    // 获取板级 bin_id，用于服务端判断是否需要升级
    const char *device_bin_id = board_get_config() ? board_get_config()->bin_id : "";
    if (!device_bin_id || device_bin_id[0] == '\0') {
        ESP_LOGW(TAG, "板级 bin_id 为空，跳过 OTA 检查（避免无限升级循环）");
        return ESP_ERR_INVALID_ARG;
    }

    // 构造查询 URL（与 Arduino auto_update 一致）
    // GET /sdk/query_new_ota?version=x&bin_id=x&is_official=x&mac=x
    // mac 参数用于服务端查找设备级 OTA 配置（每个设备有独立的 ota_bin_id）
    char query_url[600];
    snprintf(query_url, sizeof(query_url),
             "%s/sdk/query_new_ota?version=%s&bin_id=%s&is_official=0&mac=%s",
             server_base_url, FIRMWARE_VERSION, device_bin_id, s_device_id);

    ESP_LOGI(TAG, "OTA 查询: %s", query_url);

    esp_http_client_config_t config = {
        .url = query_url,
        .timeout_ms = 5000,
        // 不强制 transport_type，由 ESP-IDF 根据 URL scheme 自动选择
        // https:// 走 TLS（默认），http:// 走 TCP，避免强制明文带来的安全风险
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "HTTP 客户端初始化失败");
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "OTA 查询连接失败: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return err;
    }

    int content_length = esp_http_client_fetch_headers(client);
    int status_code = esp_http_client_get_status_code(client);

    if (status_code != 200) {
        ESP_LOGW(TAG, "OTA 查询返回非 200: %d", status_code);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    // 当服务器未返回 Content-Length 时，使用循环读取直到数据接收完成，
    // 并按需动态扩展缓冲区，避免单次读取导致响应被截断
    #define OTA_QUERY_BUF_INIT  8192   // 初始缓冲区
    #define OTA_QUERY_BUF_MAX   (64 * 1024)  // 最大缓冲区（防止无界增长）

    int buf_cap = (content_length > 0) ? content_length : OTA_QUERY_BUF_INIT;
    if (buf_cap > OTA_QUERY_BUF_MAX) buf_cap = OTA_QUERY_BUF_MAX;

    char *resp_buf = malloc(buf_cap + 1);
    if (!resp_buf) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_NO_MEM;
    }

    int total_read = 0;
    while (1) {
        // 缓冲区已满且未接收完成，尝试扩展
        if (total_read >= buf_cap) {
            if (esp_http_client_is_complete_data_received(client)) {
                break;
            }
            if (buf_cap >= OTA_QUERY_BUF_MAX) {
                ESP_LOGW(TAG, "OTA 查询响应超过最大缓冲区 %d，截断", OTA_QUERY_BUF_MAX);
                break;
            }
            int new_cap = buf_cap * 2;
            if (new_cap > OTA_QUERY_BUF_MAX) new_cap = OTA_QUERY_BUF_MAX;
            char *new_buf = realloc(resp_buf, new_cap + 1);
            if (!new_buf) {
                ESP_LOGW(TAG, "扩展响应缓冲区失败 (%d -> %d)，使用已读数据", buf_cap, new_cap);
                break;
            }
            resp_buf = new_buf;
            buf_cap = new_cap;
        }

        int read_len = esp_http_client_read(client, resp_buf + total_read, buf_cap - total_read);
        if (read_len < 0) {
            ESP_LOGE(TAG, "OTA 查询响应读取错误: %d", read_len);
            free(resp_buf);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return ESP_FAIL;
        }
        if (read_len == 0) {
            if (esp_http_client_is_complete_data_received(client)) {
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        total_read += read_len;
    }

    resp_buf[total_read > 0 ? total_read : 0] = '\0';
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    ESP_LOGD(TAG, "OTA 查询响应: %s", resp_buf);

    // 解析响应
    char bin_url[512] = {0};
    int parse_result = parse_ota_response(resp_buf, bin_url, sizeof(bin_url));
    free(resp_buf);

    if (parse_result != 1) {
        // 无需更新或解析错误
        return ESP_OK;
    }

    ESP_LOGI(TAG, "发现新固件，开始升级: %s", bin_url);
    s_ota_updating = true;

    // 停止当前会话和音频（与 Arduino otaManager.update 一致）
    display_show_ota_progress(0);
    display_show_text("系统升级中...");

    // 执行 OTA 下载和写入
    err = perform_ota_update(bin_url);

    if (err == ESP_OK) {
        s_ota_updating = false;
        ESP_LOGI(TAG, "OTA 升级成功，3 秒后重启...");
        display_show_ota_progress(100);
        display_show_text("重启中...");
        vTaskDelay(pdMS_TO_TICKS(3000));
        esp_restart();
        return ESP_OK;  // 不会执行到这里
    } else {
        s_ota_updating = false;
        s_ota_failed = true;
        ESP_LOGE(TAG, "OTA 升级失败: %s", esp_err_to_name(err));
        display_clear_ota_progress();
        display_show_status("升级失败");
        display_show_text("升级失败，将继续使用当前版本");
        vTaskDelay(pdMS_TO_TICKS(3000));

        // 回滚到当前分区（确保启动分区是当前运行的分区）
        const esp_partition_t *running = esp_ota_get_running_partition();
        if (running) {
            esp_ota_set_boot_partition(running);
        }

        return err;
    }
}

bool ota_is_updating(void)
{
    return s_ota_updating;
}

bool ota_update_failed(void)
{
    return s_ota_failed;
}
