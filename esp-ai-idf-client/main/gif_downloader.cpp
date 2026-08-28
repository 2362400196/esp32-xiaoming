/**
 * gif_downloader.cpp
 * 从服务器下载动图到 PSRAM，替换编译固件中的静态图。
 * 移植自 Arduino 客户端 gif_downloader.cpp，使用 ESP-IDF HTTP 客户端
 *
 * 下载流程（与 Arduino 一致）：
 *   1. WiFi 连接后，调用 download_gifs()
 *   2. 从服务端 API /api/v1/emos/{device_id} 获取本设备专属表情列表
 *   3. 根据 API 返回的 url 下载每个 GIF
 *   4. API 失败时回退到固定 URL: {http_base}/emos/packs/default/{filename}
 *   5. 下载成功后，eeui_port_render_emotion 优先使用 PSRAM 中的下载数据
 *   6. 下载完成前使用编译器内置的 GIF 作为后备
 */
#include "gif_downloader.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "config.h"
#include "board_compat.h"
#include "device_id.h"
#include "lvgl.h"
#include "eeui_port.h"
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_spiffs.h"
#include "cJSON.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "gif_downloader";

// 所有动图的映射表（与 Arduino 客户端一致）
const gif_map_entry_t g_gif_files[] = {
    {"联网中",   "wifi.gif"},
    {"请配网",   "wx_qrcode.gif"},
    {"发生错误", "error.gif"},
    {"聆听中",   "listen.gif"},
    {"说话中",   "tts_ing.gif"},
    {"休息中",   "sleep.gif"},
    {"唱歌中",   "music.gif"},
    {"无情绪",   "tts_ing.gif"},
    {"快乐",     "happy.gif"},
    {"伤心",     "sad.gif"},
    {"愤怒",     "angry.gif"},
    {"意外",     "accident.gif"},
    {"否定",     "no.gif"},
};
const int g_gif_files_count = sizeof(g_gif_files) / sizeof(g_gif_files[0]);

// 下载的 GIF 数据存储（PSRAM）
static lv_img_dsc_t *s_downloaded_descs = NULL;
static uint8_t **s_downloaded_data = NULL;
static volatile bool s_download_done = false;
static volatile bool s_download_started = false;  // 下载任务已启动（区分"从未下载"与"下载中"）

// ==================== 退役代际管理 ====================
// LVGL 的 gif 定时器会【零拷贝引用】已下发的数据缓冲并持续异步解码
// （lv_gif_set_src → gd_open_gif_data(img_dsc->data)，不复制数据）。
// 刷新/重新下载时如果立即 free 旧缓冲，正在解码的定时器就会读到
// 已被复用的内存（use-after-free）——表现为解码乱码（unknown sep）→
// 错误循环刷屏 → LVGL 任务吃满 CPU → 触发任务看门狗。
// 因此旧一代数据不立即释放，而是"退役"保留一代；下次刷新时才释放
// 上一次退役的数据（此时 LVGL 必已通过 lv_gif_set_src 切换到新数据）。
static uint8_t **s_retired_data = NULL;
static lv_img_dsc_t *s_retired_descs = NULL;
static int s_retired_count = 0;
static int s_allocated_count = 0;  // 现任 s_downloaded_data 的文件数（换表情包时可能与新清单不同）

/* 退役当前数据（必须在持有 s_gif_mutex 时调用）：现任缓冲转入退役代，释放上上代 */
static void gif_retire_current_locked(void)
{
    /* 1. 释放上一次退役的数据（两代之前，LVGL 必已不再引用）。
     *    注意用退役代自己的文件数释放（换包后清单数量可能已变化） */
    if (s_retired_data) {
        for (int i = 0; i < s_retired_count; i++) {
            if (s_retired_data[i]) free(s_retired_data[i]);
        }
        free(s_retired_data);
        s_retired_data = NULL;
    }
    if (s_retired_descs) {
        free(s_retired_descs);
        s_retired_descs = NULL;
    }
    /* 2. 现任数据降级为退役代（不释放，LVGL 可能仍在异步解码它） */
    s_retired_data = s_downloaded_data;
    s_retired_descs = s_downloaded_descs;
    s_retired_count = s_allocated_count;
    s_allocated_count = g_gif_files_count;
    s_downloaded_data = NULL;
    s_downloaded_descs = NULL;
    s_download_done = false;
}
// 互斥锁：保护 s_downloaded_data/s_downloaded_descs/s_download_done 的访问，
// 防止下载任务与 LVGL 渲染任务（get_downloaded_gif）之间的竞态（use-after-free）
static SemaphoreHandle_t s_gif_mutex = NULL;

static void ensure_gif_mutex(void)
{
    if (!s_gif_mutex) {
        s_gif_mutex = xSemaphoreCreateMutex();
    }
}

// ==================== HTTP 下载 ====================

/** 下载单个文件到 PSRAM 缓冲区 */
static uint8_t *download_file(const char *url, size_t *out_size)
{
    ESP_LOGD(TAG, "下载: %s", url);

    uint8_t *buf = NULL;
    size_t total_read = 0;

    esp_http_client_config_t cfg = {};
    cfg.url = url;
    cfg.timeout_ms = 15000;
    cfg.keep_alive_enable = false;
    // 不强制指定 transport_type，让 ESP-IDF 根据 URL scheme 自动选择（http→TCP, https→SSL）

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        ESP_LOGW(TAG, "HTTP 客户端初始化失败");
        return NULL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "HTTP 连接失败: %s, url=%s", esp_err_to_name(err), url);
        esp_http_client_cleanup(client);
        return NULL;
    }

    int content_length = esp_http_client_fetch_headers(client);
    // 检查 content_length 合理性：防止整数溢出（content_length + 1）和过大分配
    if (content_length <= 0 || content_length > 10 * 1024 * 1024) {
        ESP_LOGW(TAG, "内容大小无效或过大: %d, url=%s", content_length, url);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return NULL;
    }

    // 在 PSRAM 中分配缓冲区
    buf = (uint8_t *)board_malloc_audio(content_length + 1);
    if (!buf) {
        ESP_LOGW(TAG, "PSRAM 分配失败: %d 字节", content_length + 1);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return NULL;
    }

    int read_len;
    while (total_read < content_length) {
        read_len = esp_http_client_read(client, (char *)buf + total_read, content_length - total_read);
        if (read_len < 0) {
            ESP_LOGW(TAG, "读取失败, total_read=%d", total_read);
            free(buf);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return NULL;
        }
        if (read_len == 0) {
            // 没有更多数据
            break;
        }
        total_read += read_len;
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (total_read != content_length) {
        ESP_LOGW(TAG, "下载不完整: %d/%d, url=%s", total_read, content_length, url);
        free(buf);
        return NULL;
    }

    buf[total_read] = '\0';
    if (out_size) *out_size = total_read;
    ESP_LOGD(TAG, "下载完成: %s (%d bytes)", url, total_read);
    return buf;
}

// ==================== SPIFFS 缓存（避免每次开机重复下载 GIF）====================
// GIF 首次下载后写入 /spiffs/emos/，开机优先读本地缓存：
// 每次开机只下载几十字节的清单 JSON，GIF 本体零流量。
// 服务器更新表情时由 refresh_emo 指令清空缓存重新下载。
#define EMO_CACHE_DIR "/spiffs/emos"

// 从 SPIFFS 读取缓存的 GIF（不存在/读取失败返回 NULL）
static uint8_t *load_gif_from_cache(const char *filename, size_t *out_size)
{
    char path[128];
    snprintf(path, sizeof(path), "%s/%s", EMO_CACHE_DIR, filename);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long size = ftell(f);
    if (size <= 0 || size > 10 * 1024 * 1024) { fclose(f); return NULL; }
    fseek(f, 0, SEEK_SET);
    uint8_t *buf = (uint8_t *)board_malloc_audio((size_t)size + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t rd = fread(buf, 1, (size_t)size, f);
    fclose(f);
    if (rd != (size_t)size) {
        free(buf);
        return NULL;
    }
    buf[size] = '\0';
    if (out_size) *out_size = (size_t)size;
    return buf;
}

// 写入 SPIFFS 缓存（失败仅日志，不影响功能；空间不足时自动跳过缓存）
static void save_gif_to_cache(const char *filename, const uint8_t *data, size_t size)
{
    char path[128];
    snprintf(path, sizeof(path), "%s/%s", EMO_CACHE_DIR, filename);
    mkdir(EMO_CACHE_DIR, 0755);  // 确保目录存在（已存在时返回 EEXIST，忽略）
    FILE *f = fopen(path, "wb");
    if (!f) {
        ESP_LOGW(TAG, "缓存写入失败(打开): %s", path);
        return;
    }
    size_t wr = fwrite(data, 1, size, f);
    fclose(f);
    if (wr != size) {
        // 写 0 字节通常是分区已满（storage 分区与 Lua storage 共用）——打印用量便于诊断
        size_t total = 0, used = 0;
        if (esp_spiffs_info("storage", &total, &used) == ESP_OK) {
            ESP_LOGW(TAG, "缓存写入不完整: %s (%d/%d)，删除无效缓存（SPIFFS 总=%luKB 已用=%luKB 空闲=%luKB）",
                     filename, (int)wr, (int)size,
                     (unsigned long)(total / 1024), (unsigned long)(used / 1024),
                     (unsigned long)((total - used) / 1024));
        } else {
            ESP_LOGW(TAG, "缓存写入不完整: %s (%d/%d)，删除无效缓存（SPIFFS 信息读取失败）",
                     filename, (int)wr, (int)size);
        }
        remove(path);
    } else {
        ESP_LOGI(TAG, "%s 已写入缓存 (%d bytes)", filename, (int)size);
    }
}

// 清空 GIF 缓存（refresh_gifs 表情包切换时调用，强制重新下载）
static void clear_gif_cache(void)
{
    DIR *dir = opendir(EMO_CACHE_DIR);
    if (!dir) return;
    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL) {
        if (strstr(ent->d_name, ".gif")) {
            // d_name 最长 255 字节，path 需足够大（避免 -Werror=format-truncation）
            char path[300];
            snprintf(path, sizeof(path), "%s/%s", EMO_CACHE_DIR, ent->d_name);
            remove(path);
        }
    }
    closedir(dir);
    ESP_LOGI(TAG, "GIF 缓存已清空");
}

// 前向声明
static void download_all_from(const char *base_url);

// ==================== API 获取表情列表 ====================

/**
 * 从服务端 API /api/v1/emos/{device_id} 获取表情列表并下载
 * 与 Arduino 客户端 download_gifs() 逻辑一致
 * @param http_base 服务器 HTTP 基础地址，如 "http://192.168.31.176:8088"
 * @param device_id 设备 ID
 * @return true=成功 false=失败（调用方应回退到静态 URL 模式）
 */
static bool download_from_api(const char *http_base, const char *device_id)
{
    char api_url[512];
    snprintf(api_url, sizeof(api_url), "%s/api/v1/emos/%s", http_base, device_id);
    ESP_LOGI(TAG, "请求表情列表: %s", api_url);

    size_t resp_size = 0;
    uint8_t *resp_buf = download_file(api_url, &resp_size);
    if (!resp_buf) {
        ESP_LOGW(TAG, "获取表情列表失败，回退到静态 URL 模式");
        return false;
    }

    // 解析 JSON 响应
    cJSON *root = cJSON_Parse((const char *)resp_buf);
    free(resp_buf);

    if (!root) {
        ESP_LOGW(TAG, "解析表情列表 JSON 失败");
        return false;
    }

    cJSON *data = cJSON_GetObjectItem(root, "data");
    if (!data || !cJSON_IsArray(data)) {
        ESP_LOGW(TAG, "表情列表 data 字段无效");
        cJSON_Delete(root);
        return false;
    }

    int file_count = cJSON_GetArraySize(data);
    if (file_count == 0) {
        ESP_LOGW(TAG, "表情列表为空");
        cJSON_Delete(root);
        return false;
    }

    ESP_LOGI(TAG, "API 返回 %d 个表情文件", file_count);

    // 分配存储（使用局部变量，下载完成后再加锁发布到全局，避免与渲染任务竞态）
    uint8_t **new_data = (uint8_t **)calloc(g_gif_files_count, sizeof(uint8_t *));
    lv_img_dsc_t *new_descs = (lv_img_dsc_t *)calloc(g_gif_files_count, sizeof(lv_img_dsc_t));
    if (!new_data || !new_descs) {
        ESP_LOGW(TAG, "内存分配失败");
        if (new_data) free(new_data);
        if (new_descs) free(new_descs);
        cJSON_Delete(root);
        return false;
    }

    // 遍历本地映射表，从 API 返回的列表中找对应文件下载
    int success = 0;
    for (int i = 0; i < g_gif_files_count; i++) {
        const char *target_file = g_gif_files[i].filename;
        const char *download_url = NULL;
        int expected_size = 0;

        // 在 API 返回的列表中查找匹配的 filename
        for (int j = 0; j < file_count; j++) {
            cJSON *item = cJSON_GetArrayItem(data, j);
            cJSON *fn = cJSON_GetObjectItem(item, "filename");
            if (fn && cJSON_IsString(fn) && strcmp(fn->valuestring, target_file) == 0) {
                cJSON *url_obj = cJSON_GetObjectItem(item, "url");
                if (url_obj && cJSON_IsString(url_obj)) {
                    download_url = url_obj->valuestring;
                }
                cJSON *sz = cJSON_GetObjectItem(item, "size");
                if (sz && cJSON_IsNumber(sz)) expected_size = sz->valueint;
                break;
            }
        }

        if (!download_url) {
            // 当前表情包中缺少此文件，从默认包补充
            // 避免使用内置 GIF 导致表情显示不一致，确保所有表情都有对应 GIF
            char fallback_url[512];
            snprintf(fallback_url, sizeof(fallback_url), "%s/emos/packs/default/%s", http_base, target_file);
            download_url = fallback_url;
            expected_size = 0;
            ESP_LOGI(TAG, "当前包中缺少 %s，从默认包补充", target_file);
        }

        // SPIFFS 缓存：优先读本地（存在且大小与服务器一致 → 跳过下载）
        size_t dsize = 0;
        uint8_t *data_buf = load_gif_from_cache(target_file, &dsize);
        bool from_cache = false;
        if (data_buf) {
            bool size_ok = (expected_size <= 0 || (int)dsize == expected_size);
            bool header_ok = (dsize >= 6) &&
                             (data_buf[0] == 0x47 && data_buf[1] == 0x49 && data_buf[2] == 0x46);
            if (!size_ok || !header_ok) {
                ESP_LOGI(TAG, "%s 缓存无效(大小 %d/期望 %d 或头部错误)，重新下载",
                         target_file, (int)dsize, expected_size);
                free(data_buf);
                data_buf = NULL;
                char path[128];
                snprintf(path, sizeof(path), "%s/%s", EMO_CACHE_DIR, target_file);
                remove(path);  // 删除无效缓存
            } else {
                from_cache = true;
                ESP_LOGI(TAG, "%s 使用本地缓存 (%d bytes)", target_file, (int)dsize);
            }
        }
        if (!data_buf) {
            data_buf = download_file(download_url, &dsize);
        }
        if (data_buf) {
            // 验证 GIF 数据有效性：前 6 字节应为 GIF89a/GIF87a
            bool valid = (dsize >= 6) &&
                         (data_buf[0] == 0x47 && data_buf[1] == 0x49 && data_buf[2] == 0x46);
            if (!valid) {
                ESP_LOGW(TAG, "%s 数据无效(前6字节: %02x %02x %02x %02x %02x %02x), 跳过",
                         target_file,
                         data_buf[0], data_buf[1], data_buf[2],
                         data_buf[3], data_buf[4], data_buf[5]);
                free(data_buf);
                continue;
            }

            // 网络下载成功 → 写入缓存（下次开机直接读本地，零下载流量）
            if (!from_cache) {
                save_gif_to_cache(target_file, data_buf, dsize);
            }

            new_descs[i].data = data_buf;
            new_descs[i].data_size = dsize;
            // LVGL 9: 必须设置 magic，cf 设为 0 让解码器自动检测
            new_descs[i].header.magic = LV_IMAGE_HEADER_MAGIC;
            new_descs[i].header.cf = 0;
            new_descs[i].header.w = 0;
            new_descs[i].header.h = 0;
            new_data[i] = data_buf;
            success++;
        }
    }

    cJSON_Delete(root);
    ESP_LOGI(TAG, "API 下载完成: %d/%d 成功", success, g_gif_files_count);

    if (success == 0) {
        // 所有文件下载失败，释放局部存储，不发布到全局（避免泄漏，download_all_from 会重新分配）
        free(new_data);
        free(new_descs);
        return false;
    }

    // 加锁发布到全局：先释放旧数据，再替换指针，最后置 done 标志
    ensure_gif_mutex();
    if (s_gif_mutex && xSemaphoreTake(s_gif_mutex, portMAX_DELAY)) {
        /* 旧数据退役而非立即释放：LVGL 定时器可能仍在异步解码它（use-after-free 根因） */
        gif_retire_current_locked();
        s_downloaded_data = new_data;
        s_downloaded_descs = new_descs;
        s_download_done = true;
        xSemaphoreGive(s_gif_mutex);
    } else {
        // 锁不可用，释放局部数据避免泄漏
        for (int i = 0; i < g_gif_files_count; i++) {
            if (new_data[i]) free(new_data[i]);
        }
        free(new_data);
        free(new_descs);
        return false;
    }
    return true;
}

// ==================== 主下载入口 ====================

// 下载任务参数：是否显示全屏下载提示
typedef struct {
    bool show_ui;          // true=显示"表情下载中"全屏提示
    bool skip_wifi_wait;   // true=跳过WiFi等待（刷新模式，WiFi已连接）
} download_task_params_t;

static void download_gifs_task(void *arg)
{
    if (s_download_done) {
        vTaskDelete(NULL);
        return;
    }

    bool show_ui = false;
    bool skip_wifi_wait = false;
    if (arg) {
        download_task_params_t *p = (download_task_params_t *)arg;
        show_ui = p->show_ui;
        skip_wifi_wait = p->skip_wifi_wait;
        free(p);
    }

    // 等待 WiFi/LWIP 就绪后才尝试 HTTP（eeui_port_init 时 WiFi 未初始化）
    // LWIP 未初始化时调用 HTTP 会导致 tcpip_send_msg_wait_sem 断言失败
    if (skip_wifi_wait) {
        // 刷新模式：WiFi 已连接（WebSocket 正在通信），无需等待
        ESP_LOGI(TAG, "刷新模式：跳过 WiFi 等待，立即下载");
    } else {
        // 上电模式：轮询检查 WiFi 连接状态，最多等待 15 秒
        // WiFi 通常 3-5 秒内连接完成，避免固定等 15 秒
        bool wifi_ready = false;
        for (int i = 0; i < 30; i++) {
            if (s_wifi_event_group &&
                (xEventGroupGetBits(s_wifi_event_group) & WIFI_CONNECTED_BIT)) {
                wifi_ready = true;
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(500));
        }
        if (wifi_ready) {
            ESP_LOGI(TAG, "WiFi 已就绪，开始下载表情");
        } else {
            ESP_LOGW(TAG, "WiFi 等待超时（15秒），尝试下载...");
        }
        // 额外等待 500ms 确保 LWIP 协议栈完全初始化
        vTaskDelay(pdMS_TO_TICKS(500));
    }

    // 从 websocket 获取服务器 HTTP 基础地址（等待最多 10 秒）
    const char *http_base = NULL;
    for (int i = 0; i < 20; i++) {
        http_base = websocket_get_http_base();
        if (http_base && http_base[0] != '\0') break;
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    if (!http_base || http_base[0] == '\0') {
        ESP_LOGW(TAG, "服务器 HTTP 地址（等待超时），无法下载表情");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "服务器地址: %s", http_base);

    // 等待服务端后台初始化完成（MCP 连接预热等），避免 HTTP 请求撞上事件循环忙期
    ESP_LOGI(TAG, "等待服务端就绪（3s）...");
    vTaskDelay(pdMS_TO_TICKS(3000));

    // 显示全屏下载提示（refresh_emo 触发时）
    if (show_ui) {
        eeui_port_show_emo_downloading();
    }

    // 设备 ID（与 WebSocket 连接使用的 device_id 一致）
    char device_id[64];
    device_id_get(device_id, sizeof(device_id));

    // 先尝试从 API 获取表情列表（最多重试 3 次）
    // 每次重试间隔 3 秒，避免服务器短暂繁忙/网络抖动导致立即 fallback 到默认表情包
    bool ok = false;
    for (int retry = 0; retry < 3; retry++) {
        ok = download_from_api(http_base, device_id);
        if (ok) {
            break;
        }
        ESP_LOGW(TAG, "API 模式失败 (retry %d/3)，3s 后重试", retry + 1);
        if (retry < 2) {
            vTaskDelay(pdMS_TO_TICKS(3000));
        }
    }

    if (!ok) {
        // 所有重试均失败，回退到固定 URL 前缀模式（默认表情包）
        ESP_LOGW(TAG, "API 模式 3 次重试均失败，回退到静态 URL 模式");

        // 先测试连通性，每 3 秒重试
        char test_url[512];
        snprintf(test_url, sizeof(test_url), "%s/emos/packs/default/sleep.gif", http_base);
        bool reachable = false;
        for (int retry = 0; retry < 3; retry++) {
            size_t test_size = 0;
            uint8_t *test = download_file(test_url, &test_size);
            if (test) {
                free(test);
                ESP_LOGI(TAG, "服务器可达，开始下载动图");
                reachable = true;
                break;
            }
            ESP_LOGI(TAG, "服务器暂不可达 (retry %d/3)，3s 后重试", retry + 1);
            if (retry < 2) {
                vTaskDelay(pdMS_TO_TICKS(3000));
            }
        }

        if (reachable) {
            char base_url[512];
            snprintf(base_url, sizeof(base_url), "%s/emos/packs/default/", http_base);
            download_all_from(base_url);
        } else {
            ESP_LOGW(TAG, "服务器不可达，使用内置 GIF");
        }
    }

    // 隐藏全屏下载提示，恢复表情状态
    if (show_ui) {
        eeui_port_hide_emo_downloading();
    }

    vTaskDelete(NULL);
}

/** 回退方案：从固定 URL 前缀下载所有 GIF */
static void download_all_from(const char *base_url)
{
    // 使用局部变量，下载完成后再加锁发布到全局，避免与渲染任务竞态
    uint8_t **new_data = (uint8_t **)calloc(g_gif_files_count, sizeof(uint8_t *));
    lv_img_dsc_t *new_descs = (lv_img_dsc_t *)calloc(g_gif_files_count, sizeof(lv_img_dsc_t));
    if (!new_data || !new_descs) {
        ESP_LOGW(TAG, "内存分配失败");
        if (new_data) free(new_data);
        if (new_descs) free(new_descs);
        return;
    }

    int success = 0;
    for (int i = 0; i < g_gif_files_count; i++) {
        char url[512];
        snprintf(url, sizeof(url), "%s%s", base_url, g_gif_files[i].filename);

        // SPIFFS 缓存：优先读本地（静态模式无 size 信息，仅校验 GIF 头）
        size_t dsize = 0;
        uint8_t *data_buf = load_gif_from_cache(g_gif_files[i].filename, &dsize);
        bool from_cache = false;
        if (data_buf) {
            bool header_ok = (dsize >= 6) &&
                             (data_buf[0] == 0x47 && data_buf[1] == 0x49 && data_buf[2] == 0x46);
            if (!header_ok) {
                ESP_LOGI(TAG, "%s 缓存无效(头部错误)，重新下载", g_gif_files[i].filename);
                free(data_buf);
                data_buf = NULL;
                char path[128];
                snprintf(path, sizeof(path), "%s/%s", EMO_CACHE_DIR, g_gif_files[i].filename);
                remove(path);
            } else {
                from_cache = true;
                ESP_LOGI(TAG, "%s 使用本地缓存 (%d bytes)", g_gif_files[i].filename, (int)dsize);
            }
        }
        if (!data_buf) {
            data_buf = download_file(url, &dsize);
        }
        if (data_buf) {
            // 验证 GIF 数据有效性：前 6 字节应为 GIF89a/GIF87a
            bool valid = (dsize >= 6) &&
                         (data_buf[0] == 0x47 && data_buf[1] == 0x49 && data_buf[2] == 0x46);
            if (!valid) {
                ESP_LOGW(TAG, "%s 数据无效(前6字节: %02x %02x %02x %02x %02x %02x), 跳过",
                         g_gif_files[i].filename,
                         data_buf[0], data_buf[1], data_buf[2],
                         data_buf[3], data_buf[4], data_buf[5]);
                free(data_buf);
                continue;
            }

            // 网络下载成功 → 写入缓存
            if (!from_cache) {
                save_gif_to_cache(g_gif_files[i].filename, data_buf, dsize);
            }

            new_descs[i].data = data_buf;
            new_descs[i].data_size = dsize;
            // LVGL 9: 必须设置 magic，cf 设为 0 让解码器自动检测
            new_descs[i].header.magic = LV_IMAGE_HEADER_MAGIC;
            new_descs[i].header.cf = 0;
            new_descs[i].header.w = 0;
            new_descs[i].header.h = 0;
            new_data[i] = data_buf;
            success++;
        }
    }

    ESP_LOGI(TAG, "下载完成: %d/%d (静态模式)", success, g_gif_files_count);

    if (success == 0) {
        // 所有文件下载失败，释放局部存储
        free(new_data);
        free(new_descs);
        return;
    }

    // 加锁发布到全局：先释放旧数据，再替换指针，最后置 done 标志
    ensure_gif_mutex();
    if (s_gif_mutex && xSemaphoreTake(s_gif_mutex, portMAX_DELAY)) {
        /* 旧数据退役而非立即释放：LVGL 定时器可能仍在异步解码它（use-after-free 根因） */
        gif_retire_current_locked();
        s_downloaded_data = new_data;
        s_downloaded_descs = new_descs;
        s_download_done = true;
        xSemaphoreGive(s_gif_mutex);
    } else {
        // 锁不可用，释放局部数据避免泄漏
        for (int i = 0; i < g_gif_files_count; i++) {
            if (new_data[i]) free(new_data[i]);
        }
        free(new_data);
        free(new_descs);
    }
}

// ==================== 公开接口 ====================

void download_gifs(void)
{
    if (s_download_done) return;

    ensure_gif_mutex();
    ESP_LOGI(TAG, "启动后台下载动图任务...");
    s_download_started = true;  // 标记下载中（唤醒模块据此禁用唤醒，避免内存竞争）

    // 创建后台下载任务（核心 1，避免阻塞核心 0 的 LVGL）
    // 显示全屏下载提示，下载完成后自动刷新表情
    download_task_params_t *params = (download_task_params_t *)malloc(sizeof(download_task_params_t));
    if (!params) {
        ESP_LOGW(TAG, "内存分配失败，使用内置 GIF");
        return;
    }
    params->show_ui = true;
    params->skip_wifi_wait = false;  // 上电模式：需要等待 WiFi 就绪
    BaseType_t ret = xTaskCreatePinnedToCore(
        download_gifs_task,
        "gif_down",
        8192,
        params,
        1,            // 低优先级
        NULL,
        BOARD_TASK_CORE_1  // 双核：核心 1；单核：核心 0
    );

    if (ret != pdPASS) {
        ESP_LOGW(TAG, "创建下载任务失败，使用内置 GIF");
        free(params);
    }
}

// 是否正在下载 GIF 表情（唤醒模块据此禁用唤醒动作，避免下载占用内存时
// 唤醒/播放分配失败导致异常会话；下载完成自动恢复）
bool gif_download_is_busy(void)
{
    return s_download_started && !s_download_done;
}

const lv_img_dsc_t *get_downloaded_gif(const char *name)
{
    // 快速检查：未完成或无数据时直接返回（无需加锁）
    if (!s_download_done || !s_downloaded_descs) return NULL;
    if (!s_gif_mutex) return NULL;  // 互斥锁未初始化，安全回退

    const lv_img_dsc_t *result = NULL;
    // 加锁读取，防止与 refresh_gifs/download 任务的释放/写入竞态（use-after-free）
    if (xSemaphoreTake(s_gif_mutex, pdMS_TO_TICKS(50))) {
        // 锁内重新校验（防止在获取锁期间状态被 refresh_gifs 改变）
        if (s_download_done && s_downloaded_descs) {
            for (int i = 0; i < g_gif_files_count; i++) {
                if (strcmp(g_gif_files[i].name, name) == 0) {
                    if (s_downloaded_descs[i].data != NULL) {
                        result = &s_downloaded_descs[i];
                    }
                    break;
                }
            }
        }
        xSemaphoreGive(s_gif_mutex);
    }
    return result;
}

void refresh_gifs(void)
{
    ESP_LOGI(TAG, "刷新表情包：释放旧数据并重新下载");

    // 清空 SPIFFS 缓存（服务器已切换表情包，旧缓存不可用）
    clear_gif_cache();

    ensure_gif_mutex();
    // 加锁退役旧数据（不立即释放——LVGL 定时器可能仍在异步解码它，见 gif_retire_current_locked）
    if (s_gif_mutex && xSemaphoreTake(s_gif_mutex, portMAX_DELAY)) {
        gif_retire_current_locked();
        xSemaphoreGive(s_gif_mutex);
    }

    // 重新启动下载任务，显示全屏下载提示
    ESP_LOGI(TAG, "启动刷新下载任务（带全屏提示）...");
    download_task_params_t *params = (download_task_params_t *)malloc(sizeof(download_task_params_t));
    if (params) {
        params->show_ui = true;
        params->skip_wifi_wait = true;  // 刷新模式：WiFi 已连接，跳过等待
        BaseType_t ret = xTaskCreatePinnedToCore(
            download_gifs_task,
            "gif_refresh",
            8192,
            params,
            1,
            NULL,
            BOARD_TASK_CORE_1  // 双核：核心 1；单核：核心 0
        );
        if (ret != pdPASS) {
            ESP_LOGW(TAG, "创建刷新下载任务失败");
            free(params);
        }
    }
}
