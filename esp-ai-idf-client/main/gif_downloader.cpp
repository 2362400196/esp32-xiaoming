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
#include "ota_update.h"
#include "power_manager.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "config.h"
#include "board_compat.h"
#include "device_id.h"
#include "sdcard.h"
#include "lvgl.h"
#include "eeui_port.h"
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "esp_spiffs.h"
#include "cJSON.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "freertos/idf_additions.h"  /* xTaskCreatePinnedToCoreWithCaps */
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <unistd.h>

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

// ==================== 下载进度上报 ====================
// 全屏提示里的进度条显示真实百分比：已完成文件数 + 当前文件已读字节占比。
// 只增不减，避免现场出现"进度条往回走"。
static int s_dl_file_total = 0;   // 本轮要处理的文件总数（0 = 当前没有进度可报）
static int s_dl_last_percent = -1; // 上次上报的百分比（去重，避免频繁刷新 LVGL）

// 刷新模式：服务器已切换表情包，本地缓存全部视为过期，本次强制重新下载。
// 不再预删缓存文件（SPIFFS 删除 13 个文件实测要 18 秒，且会拖慢 ACK），
// 新文件直接 fopen("wb") 覆盖旧缓存即可。
static volatile bool s_force_download = false;
static int s_dl_file_index = 0;   // 当前正在处理的文件序号（0 起，等于已完成数）

/** 开始一轮下载：把进度归零（列表请求等辅助下载不算，避免进度乱跳） */
static void dl_progress_begin(int total_files)
{
    s_dl_file_total = total_files > 0 ? total_files : 1;
    s_dl_file_index = 0;
    eeui_port_set_emo_download_progress(0);
}

/** 上报进度：index=已完成文件数，read/total=当前文件已读字节（可为 0/0） */
static void dl_progress_report(int index, size_t read_bytes, size_t total_bytes)
{
    if (s_dl_file_total <= 0) return;
    long long units = (long long)index * 1000;   // 每个文件占 1000 个单位
    if (total_bytes > 0 && read_bytes > 0) {
        long long frac = (long long)read_bytes * 1000 / (long long)total_bytes;
        if (frac > 1000) frac = 1000;
        units += frac;
    }
    int percent = (int)(units / ((long long)s_dl_file_total * 10));
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    // 百分比没变就不碰 UI：HTTP 每读 1KB 回调一次，每次都加锁渲染会让
    // 下载速度被 LVGL 拖到十几 KB/s（表现为切换表情包要等一两分钟）
    if (percent == s_dl_last_percent) return;
    s_dl_last_percent = percent;
    eeui_port_set_emo_download_progress(percent);
}

/** 结束一轮下载：成功则补到 100，失败则清零，然后清空本轮状态 */
static void dl_progress_finish(bool completed)
{
    if (s_dl_file_total > 0) {
        eeui_port_set_emo_download_progress(completed ? 100 : 0);
    }
    s_dl_file_total = 0;
    s_dl_file_index = 0;
    s_dl_last_percent = -1;
}

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
    // 默认 1KB 接收缓冲意味着每收 1KB 就多一次 select/recv 系统调用，
    // 大文件（几百 KB 的 GIF）会被系统调用开销拖到几十 KB/s
    cfg.buffer_size = 4096;
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
        dl_progress_report(s_dl_file_index, total_read, (size_t)content_length);
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

// ==================== 本地缓存（避免每次开机重复下载 GIF）====================
// GIF 首次下载后落盘，开机优先读本地缓存：GIF 本体零流量。
//
// 缓存位置：优先 SD 卡 /sdcard/emos（写入 >100KB/s，且写卡不占用 flash 缓存，
// 不会卡住 WiFi/音频）；没有 SD 卡时【不写缓存】——实测 SPIFFS 写入只有 3KB/s，
// 一个 20KB 的文件要写 1 分钟，会把 HTTP 请求和整机一起拖死。没有缓存时开机
// 重新下载一遍（后台进行，界面用内置图兜底），可接受。
//
// 升级前写在 /spiffs/emos 的旧缓存仍然可读（只读不写），避免一次性重下。
#define EMO_CACHE_SD_DIR     "/sdcard/emos"
#define EMO_CACHE_LEGACY_DIR "/spiffs/emos"

// 缓存写入目录（NULL = 不缓存）
static const char *emo_cache_write_dir(void)
{
    return sdcard_is_mounted() ? EMO_CACHE_SD_DIR : NULL;
}

// 从 SPIFFS 读取缓存的 GIF（不存在/读取失败返回 NULL）
// 注意：本函数执行 flash 操作，必须在内部 RAM 栈的任务中运行（见下方工作线程）
static uint8_t *load_gif_from_cache_impl(const char *path, size_t *out_size)
{
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

// 写入缓存（失败仅日志，不影响功能；空间不足时自动跳过缓存）
// 注意：写 SPIFFS 会禁用 flash 缓存，必须在内部 RAM 栈的任务中运行（见下方工作线程）；
//      写 SD 卡没有这个限制，走同一路径也无副作用。
static void save_gif_to_cache_impl(const char *path, const uint8_t *data, size_t size)
{
    bool is_spiffs = (strncmp(path, "/spiffs", 7) == 0);
    // 目录已由调用方创建；这里再 mkdir 一次兜底（已存在时返回 EEXIST，忽略）
    const char *slash = strrchr(path, '/');
    if (slash && slash != path) {
        char dir[64];
        size_t n = (size_t)(slash - path);
        if (n < sizeof(dir)) {
            memcpy(dir, path, n);
            dir[n] = '\0';
            mkdir(dir, 0755);
        }
    }

    // 空间预检（仅 SPIFFS）：空闲不足以容纳整个文件时直接跳过（留 8KB 余量）
    size_t total = 0, used = 0;
    if (is_spiffs && esp_spiffs_info("storage", &total, &used) == ESP_OK) {
        size_t free_bytes = total - used;
        if (free_bytes < size + 8 * 1024) {
            ESP_LOGW(TAG, "SPIFFS 空闲不足，跳过缓存: %s 需 %dKB，空闲 %dKB（表情仍可在本次运行中正常显示）",
                     path, (int)(size / 1024), (int)(free_bytes / 1024));
            return;
        }
    }

    int64_t t0 = esp_timer_get_time();
    FILE *f = fopen(path, "wb");
    if (!f) {
        ESP_LOGW(TAG, "缓存写入失败(打开): %s (errno=%d %s)", path, errno, strerror(errno));
        return;
    }

    // 分块写入：SPIFFS 对超大单次 write 有失败风险（官方文档明确说明单次写入
    // 超过块大小若干倍可能失败），newlib fwrite 对大块数据可能一次性直传全部
    // 字节；分块写入规避该问题，且失败时能精确定位出错位置
    size_t written = 0;
    const size_t chunk_max = 4096;
    while (written < size) {
        size_t remain = size - written;
        size_t n = fwrite(data + written, 1, remain < chunk_max ? remain : chunk_max, f);
        if (n == 0) {
            ESP_LOGW(TAG, "缓存写入失败@%u/%u: %s (errno=%d %s, ferror=%d)",
                     (unsigned)written, (unsigned)size, path,
                     errno, strerror(errno), ferror(f) ? 1 : 0);
            break;
        }
        written += n;
    }
    // 显式落盘并校验：fclose 内部 flush 失败会被静默吞掉，必须先 fflush 检查
    if (written == size && (fflush(f) != 0 || fsync(fileno(f)) != 0)) {
        ESP_LOGW(TAG, "缓存写入失败(flush/fsync): %s (errno=%d %s)", path, errno, strerror(errno));
        written = 0;
    }
    fclose(f);

    if (written != size) {
        // 删除无效缓存，下次开机重新下载
        remove(path);
        ESP_LOGW(TAG, "缓存写入不完整: %s (%u/%u)，删除无效缓存",
                 path, (unsigned)written, (unsigned)size);
    } else {
        int ms = (int)((esp_timer_get_time() - t0) / 1000);
        ESP_LOGI(TAG, "%s 已写入缓存 (%d bytes, %dms, %dKB/s)", path, (int)size, ms,
                 ms > 0 ? (int)(size / 1024 * 1000 / ms) : 0);
    }
}

// ==================== SPIFFS 内部 RAM 一次性工作线程 ====================
// SPIFFS 读写会禁用 flash 缓存，期间 CPU 无法访问 PSRAM（含 PSRAM 栈），
// 否则触发 esp_task_stack_is_sane_cache_disabled 断言崩溃。
// 下载任务栈在 PSRAM（32KB 用于 HTTP），故所有 SPIFFS 操作统一委托给
// 本内部 RAM 栈的一次性工作线程执行；下载任务同步等待结果。
// 每次操作创建/删除任务（约 100µs），操作完成后 6KB 内部 RAM 立即释放，
// 避免常驻工作线程长期占用紧张的内部 RAM。
typedef struct {
    void (*fn)(void *ctx);   // 在内部 RAM 栈中执行的函数
    void *ctx;               // 上下文（必须分配在内部 RAM）
    SemaphoreHandle_t done;  // 完成信号量
} spiffs_job_t;

static void spiffs_one_shot_task(void *arg)
{
    spiffs_job_t *p = (spiffs_job_t *)arg;
    // 启动时立即把参数拷到内部 RAM 栈局部变量：后续 flash 操作期间缓存禁用，
    // 不能再访问 p（p 在调用方 PSRAM 栈上）
    void (*fn)(void *ctx) = p->fn;
    void *ctx = p->ctx;
    SemaphoreHandle_t done = p->done;
    fn(ctx);
    xSemaphoreGive(done);
    vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps 释放内部 RAM 栈 */
}

// 同步执行 SPIFFS 操作：创建内部 RAM 栈任务执行并阻塞等待完成
static void spiffs_sync(void (*fn)(void *ctx), void *ctx)
{
    spiffs_job_t p = { .fn = fn, .ctx = ctx, .done = xSemaphoreCreateBinary() };
    if (!p.done) return;
    // 栈必须在内部 RAM：SPIFFS 操作期间缓存禁用，PSRAM 栈会断言崩溃
    BaseType_t ret = xTaskCreatePinnedToCoreWithCaps(
        spiffs_one_shot_task, "spiffs", 6144, &p, 2, NULL,
        BOARD_TASK_CORE_1, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (ret == pdPASS) {
        xSemaphoreTake(p.done, portMAX_DELAY);
    } else {
        ESP_LOGW(TAG, "SPIFFS 工作线程创建失败（内部 RAM 不足），本次跳过缓存");
    }
    vSemaphoreDelete(p.done);
}

// SPIFFS 操作上下文（必须分配在内部 RAM：工作线程在缓存禁用期间访问它）
typedef struct {
    char path[128];          // 目标文件完整路径
    const uint8_t *data;     // 写入数据（SAVE）
    size_t size;             // 数据大小（SAVE）/ 读取大小输出（LOAD）
    uint8_t *out_buf;        // 读取缓冲输出（LOAD）
} spiffs_op_ctx_t;

static void spiffs_load_worker(void *ctx)
{
    spiffs_op_ctx_t *c = (spiffs_op_ctx_t *)ctx;
    c->out_buf = load_gif_from_cache_impl(c->path, &c->size);
}

static void spiffs_save_worker(void *ctx)
{
    spiffs_op_ctx_t *c = (spiffs_op_ctx_t *)ctx;
    save_gif_to_cache_impl(c->path, c->data, c->size);
}

static void spiffs_remove_worker(void *ctx)
{
    spiffs_op_ctx_t *c = (spiffs_op_ctx_t *)ctx;
    remove(c->path);
}

// 从指定目录读一个缓存文件（委托内部 RAM 栈工作线程，不存在/失败返回 NULL）
static uint8_t *load_gif_from_dir(const char *dir, const char *filename, size_t *out_size)
{
    spiffs_op_ctx_t *ctx = (spiffs_op_ctx_t *)heap_caps_malloc(sizeof(spiffs_op_ctx_t), MALLOC_CAP_INTERNAL);
    if (!ctx) return NULL;
    snprintf(ctx->path, sizeof(ctx->path), "%s/%s", dir, filename);
    ctx->out_buf = NULL;
    ctx->size = 0;
    spiffs_sync(spiffs_load_worker, ctx);
    uint8_t *buf = ctx->out_buf;
    if (out_size) *out_size = ctx->size;
    heap_caps_free(ctx);
    return buf;
}

// 读取缓存：优先 SD 卡，其次升级前的 SPIFFS 旧缓存（只读）
static uint8_t *load_gif_from_cache(const char *filename, size_t *out_size)
{
    const char *dir = emo_cache_write_dir();
    if (dir) {
        uint8_t *buf = load_gif_from_dir(dir, filename, out_size);
        if (buf) return buf;
    }
    return load_gif_from_dir(EMO_CACHE_LEGACY_DIR, filename, out_size);
}

// 写入缓存（无 SD 卡时不缓存：SPIFFS 写入只有 3KB/s，会拖死整机）
static void save_gif_to_cache(const char *filename, const uint8_t *data, size_t size)
{
    const char *dir = emo_cache_write_dir();
    if (!dir) {
        static bool s_warned = false;
        if (!s_warned) {
            s_warned = true;
            ESP_LOGW(TAG, "未检测到 SD 卡，本次不写表情缓存（下次开机会重新下载）");
        }
        return;
    }
    spiffs_op_ctx_t *ctx = (spiffs_op_ctx_t *)heap_caps_malloc(sizeof(spiffs_op_ctx_t), MALLOC_CAP_INTERNAL);
    if (!ctx) return;
    snprintf(ctx->path, sizeof(ctx->path), "%s/%s", dir, filename);
    ctx->data = data;
    ctx->size = size;
    spiffs_sync(spiffs_save_worker, ctx);
    heap_caps_free(ctx);
}

// 删除缓存文件（SD 卡 + SPIFFS 旧缓存都删，委托内部 RAM 栈工作线程）
static void remove_gif_cache_file(const char *filename)
{
    spiffs_op_ctx_t *ctx = (spiffs_op_ctx_t *)heap_caps_malloc(sizeof(spiffs_op_ctx_t), MALLOC_CAP_INTERNAL);
    if (!ctx) return;
    const char *dir = emo_cache_write_dir();
    if (dir) {
        snprintf(ctx->path, sizeof(ctx->path), "%s/%s", dir, filename);
        spiffs_sync(spiffs_remove_worker, ctx);
    }
    snprintf(ctx->path, sizeof(ctx->path), "%s/%s", EMO_CACHE_LEGACY_DIR, filename);
    spiffs_sync(spiffs_remove_worker, ctx);
    heap_caps_free(ctx);
}

// ==================== 缓存写入延后队列 ====================
// 写缓存不该挡在界面切换之前（尤其 SPIFFS 只有 3KB/s）。这里先把新 GIF 发布给
// LVGL（界面立即切换），再把缓存写入排队，等全屏下载提示收起后统一写盘。
static volatile bool s_cache_flush_abort = false;  // 新一次刷新到来时，放弃上一轮残留的写缓存
#define PENDING_CACHE_MAX 20
typedef struct {
    char filename[40];
    const uint8_t *data;
    size_t size;
} pending_cache_entry_t;
static pending_cache_entry_t s_pending_cache[PENDING_CACHE_MAX];
static int s_pending_cache_count = 0;

static void queue_cache_write(const char *filename, const uint8_t *data, size_t size)
{
    if (s_pending_cache_count >= PENDING_CACHE_MAX) {
        save_gif_to_cache(filename, data, size);  // 队列满，退化为同步写
        return;
    }
    pending_cache_entry_t *e = &s_pending_cache[s_pending_cache_count++];
    strlcpy(e->filename, filename, sizeof(e->filename));
    e->data = data;
    e->size = size;
}

static void flush_pending_cache(void)
{
    if (s_pending_cache_count == 0) return;
    s_cache_flush_abort = false;
    ESP_LOGI(TAG, "界面已切换，开始写 %d 个缓存文件", s_pending_cache_count);
    int64_t t0 = esp_timer_get_time();
    int i = 0;
    for (; i < s_pending_cache_count; i++) {
        if (s_cache_flush_abort) {
            ESP_LOGW(TAG, "有新的表情包刷新，放弃剩余 %d 个缓存写入",
                     s_pending_cache_count - i);
            break;
        }
        save_gif_to_cache(s_pending_cache[i].filename,
                          s_pending_cache[i].data, s_pending_cache[i].size);
    }
    s_pending_cache_count = 0;
    ESP_LOGI(TAG, "缓存写入结束（%d 个），用时 %dms", i,
             (int)((esp_timer_get_time() - t0) / 1000));
}

static void cancel_pending_cache(void)
{
    s_pending_cache_count = 0;
}

// 前向声明
static void download_all_from(const char *base_url, bool force);

// ==================== API 获取表情列表 ====================

/**
 * 从服务端 API /api/v1/emos/{device_id} 获取表情列表并下载
 * 与 Arduino 客户端 download_gifs() 逻辑一致
 * @param http_base 服务器 HTTP 基础地址，如 "http://192.168.31.176:8088"
 * @param device_id 设备 ID
 * @return true=成功 false=失败（调用方应回退到静态 URL 模式）
 */
static bool download_from_api(const char *http_base, const char *device_id, bool force)
{
    dl_progress_finish(false);   // 清掉上一轮残留：列表请求本身不计入进度
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
    dl_progress_begin(g_gif_files_count);
    int success = 0;
    for (int i = 0; i < g_gif_files_count; i++) {
        s_dl_file_index = i;          // 已处理 i 个，当前是第 i+1 个
        dl_progress_report(i, 0, 0);
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

        bool from_default_pack = false;
        if (!download_url) {
            // 当前表情包中缺少此文件，从默认包补充
            // 避免使用内置 GIF 导致表情显示不一致，确保所有表情都有对应 GIF
            char fallback_url[512];
            snprintf(fallback_url, sizeof(fallback_url), "%s/emos/packs/default/%s", http_base, target_file);
            download_url = fallback_url;
            expected_size = 0;
            from_default_pack = true;
            ESP_LOGI(TAG, "当前包中缺少 %s，从默认包补充", target_file);
        }

        // SPIFFS 缓存：优先读本地（存在且大小与服务器一致 → 跳过下载）
        // 刷新模式下丢弃新表情包里的旧缓存（属于上一个包），但从默认包补齐的文件
        // 与表情包无关、内容不变，仍然可以用缓存，省掉这部分下载
        bool allow_cache = !force || from_default_pack;
        size_t dsize = 0;
        uint8_t *data_buf = allow_cache ? load_gif_from_cache(target_file, &dsize) : NULL;
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
                remove_gif_cache_file(target_file);  // 删除无效缓存
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

            // 网络下载成功 → 排入缓存写入队列（等界面切换后再写，见 flush_pending_cache）
            if (!from_cache) {
                queue_cache_write(target_file, data_buf, dsize);
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
        cancel_pending_cache();
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
        // 锁不可用，释放局部数据避免泄漏（排队中的缓存条目指向这些数据，一并丢弃）
        cancel_pending_cache();
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
        vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps 释放 PSRAM 栈 */
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
        s_download_started = false;  // 复位，避免唤醒被永久禁用
        vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps 释放 PSRAM 栈 */
        return;
    }

    ESP_LOGI(TAG, "服务器地址: %s", http_base);

    // 下载期间关闭 WiFi modem sleep：待机态（MIN_MODEM）下吞吐会掉到十几 KB/s，
    // 表现为切换表情包要等一两分钟；下载完成后再恢复省电。
    bool ps_forced = !power_manager_is_active();
    if (ps_forced) {
        wifi_set_power_save(false);
    }

    // 等待服务端后台初始化完成（MCP 连接预热等），避免 HTTP 请求撞上事件循环忙期
    // 刷新模式（refresh_emo）下服务端已在线，跳过这段等待，让指令 ACK 尽快回到服务端
    if (!skip_wifi_wait) {
        ESP_LOGI(TAG, "等待服务端就绪（3s）...");
        vTaskDelay(pdMS_TO_TICKS(3000));
    } else {
        // 给 ACK 留出串口/WS 发送窗口，避免 HTTP 抢占发送队列
        vTaskDelay(pdMS_TO_TICKS(300));
    }

    // 显示全屏下载提示（refresh_emo 触发时）
    if (show_ui) {
        eeui_port_show_emo_downloading();
    }

    // 设备 ID（与 WebSocket 连接使用的 device_id 一致）
    char device_id[64];
    device_id_get(device_id, sizeof(device_id));

    // 刷新标记：本次是切换表情包触发的，缓存全部过期，必须重新下载
    bool force = s_force_download;
    s_force_download = false;

    // 先尝试从 API 获取表情列表（最多重试 3 次）
    // 每次重试间隔 3 秒，避免服务器短暂繁忙/网络抖动导致立即 fallback 到默认表情包
    bool ok = false;
    for (int retry = 0; retry < 3; retry++) {
        ok = download_from_api(http_base, device_id, force);
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
        dl_progress_finish(false);   // 连通性测试不计入进度

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
            download_all_from(base_url, force);
        } else {
            ESP_LOGW(TAG, "服务器不可达，使用内置 GIF");
            s_download_started = false;  // 复位，避免唤醒被永久禁用
        }
    }

    // 隐藏全屏下载提示，恢复表情状态（先把进度补到 100，留 200ms 让 LVGL 画出来）
    if (show_ui) {
        dl_progress_finish(s_download_done);
        vTaskDelay(pdMS_TO_TICKS(200));
        eeui_port_hide_emo_downloading();
    }

    // 界面已经切到新表情，再统一写 SPIFFS 缓存（写 flash 很慢，不能挡在切换之前）
    flush_pending_cache();

    // 下载未成功完成（如内部内存分配失败/部分失败）时复位启动标志，
    // 避免 gif_download_is_busy() 永久为 true 导致唤醒被禁用
    if (!s_download_done) {
        s_download_started = false;
    }

    // 恢复待机省电（若这期间用户已进入会话，保持 NONE 不动）
    if (ps_forced && !power_manager_is_active()) {
        wifi_set_power_save(true);
    }

    vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps 释放 PSRAM 栈 */
}

/** 回退方案：从固定 URL 前缀下载所有 GIF */
static void download_all_from(const char *base_url, bool force)
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
    dl_progress_begin(g_gif_files_count);
    for (int i = 0; i < g_gif_files_count; i++) {
        s_dl_file_index = i;
        dl_progress_report(i, 0, 0);
        char url[512];
        snprintf(url, sizeof(url), "%s%s", base_url, g_gif_files[i].filename);

        // SPIFFS 缓存：优先读本地（静态模式无 size 信息，仅校验 GIF 头）
        size_t dsize = 0;
        uint8_t *data_buf = force ? NULL : load_gif_from_cache(g_gif_files[i].filename, &dsize);
        bool from_cache = false;
        if (data_buf) {
            bool header_ok = (dsize >= 6) &&
                             (data_buf[0] == 0x47 && data_buf[1] == 0x49 && data_buf[2] == 0x46);
            if (!header_ok) {
                ESP_LOGI(TAG, "%s 缓存无效(头部错误)，重新下载", g_gif_files[i].filename);
                free(data_buf);
                data_buf = NULL;
                remove_gif_cache_file(g_gif_files[i].filename);
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

            // 网络下载成功 → 排入缓存写入队列（界面切换后再写）
            if (!from_cache) {
                queue_cache_write(g_gif_files[i].filename, data_buf, dsize);
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
        cancel_pending_cache();
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
        // 锁不可用，释放局部数据避免泄漏（排队中的缓存条目指向这些数据，一并丢弃）
        cancel_pending_cache();
        for (int i = 0; i < g_gif_files_count; i++) {
            if (new_data[i]) free(new_data[i]);
        }
        free(new_data);
        free(new_descs);
    }
}

// ==================== 公开接口 ====================

// 下载任务创建失败后的重试：一次性定时器，30 秒后重试（最多 10 次）。
// 上电初期 WakeNet/音频/WiFi 已占用大量内存，8KB 任务栈可能分配失败；
// 稍后内存释放或网络恢复后再试，避免表情永久缺失。
static esp_timer_handle_t s_retry_timer = NULL;
static int s_retry_count = 0;
#define GIF_DOWNLOAD_MAX_RETRY 10
#define GIF_DOWNLOAD_RETRY_DELAY_US (30 * 1000 * 1000)

static void download_retry_cb(void *arg)
{
    download_gifs();
}

static void schedule_download_retry(void)
{
    if (s_retry_count >= GIF_DOWNLOAD_MAX_RETRY) {
        ESP_LOGW(TAG, "表情下载重试次数已达上限，放弃（唤醒不受影响）");
        return;
    }
    s_retry_count++;
    if (!s_retry_timer) {
        esp_timer_create_args_t args = {
            .callback = download_retry_cb,
            .arg = NULL,
            .dispatch_method = ESP_TIMER_TASK,
            .name = "gif_retry",
            .skip_unhandled_events = false,
        };
        if (esp_timer_create(&args, &s_retry_timer) != ESP_OK) {
            ESP_LOGW(TAG, "创建重试定时器失败");
            return;
        }
    }
    esp_timer_start_once(s_retry_timer, GIF_DOWNLOAD_RETRY_DELAY_US);
}

void download_gifs(void)
{
    if (s_download_done) return;
    if (s_download_started) return;  // 已有下载任务在运行/排队，避免重复创建
    if (ota_is_updating()) {
        ESP_LOGW(TAG, "OTA 升级进行中，跳过表情下载");
        return;
    }

    ensure_gif_mutex();
    ESP_LOGI(TAG, "启动后台下载动图任务...");
    s_download_started = true;  // 标记下载中（唤醒模块据此禁用唤醒，避免内存竞争）

    // 创建后台下载任务（核心 1，避免阻塞核心 0 的 LVGL）
    // 显示全屏下载提示，下载完成后自动刷新表情
    download_task_params_t *params = (download_task_params_t *)malloc(sizeof(download_task_params_t));
    if (!params) {
        ESP_LOGW(TAG, "内存分配失败，使用内置 GIF");
        s_download_started = false;  // 复位，避免唤醒被永久禁用
        return;
    }
    params->show_ui = true;
    params->skip_wifi_wait = false;  // 上电模式：需要等待 WiFi 就绪
    BaseType_t ret = xTaskCreatePinnedToCoreWithCaps(
        download_gifs_task,
        "gif_down",
        32768,        // 字节（有 PSRAM 时栈放 PSRAM，省内部 RAM）
        params,
        1,            // 低优先级
        NULL,
        BOARD_TASK_CORE_1,  // 双核：核心 1；单核：核心 0
        BOARD_STACK_CAPS_AUDIO
    );

    if (ret != pdPASS) {
        ESP_LOGW(TAG, "创建下载任务失败（内部RAM可用=%ldB 最大块=%ldB），稍后重试",
                 (long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                 (long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
        free(params);
        s_download_started = false;  // 复位，避免唤醒被永久禁用
        schedule_download_retry();
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

    // OTA 升级进行中跳过：写 flash 与 OTA 并发会争抢内存/SPIFFS，且升级成功后立即重启
    if (ota_is_updating()) {
        ESP_LOGW(TAG, "OTA 升级进行中，跳过表情刷新");
        return;
    }

    // 标记强制重新下载：旧缓存属于上一个表情包，不能再用。
    // 这里不再预删缓存文件——SPIFFS 删除 13 个 GIF 实测要 18 秒，会把刷新指令的
    // ACK 和界面切换一起拖到 20 秒以上；新文件会直接覆盖同名缓存。
    s_force_download = true;
    // 放弃上一轮（开机下载）还没写完的缓存：它会和本次下载抢 flash/NAND，
    // 之前实测把一次 2KB 的列表请求拖到 15 秒
    s_cache_flush_abort = true;
    // 标记下载中：避免 websocket 重连时又起一个下载任务，也让唤醒模块避开
    s_download_started = true;

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
        BaseType_t ret = xTaskCreatePinnedToCoreWithCaps(
            download_gifs_task,
            "gif_refresh",
            32768,        // 字节（有 PSRAM 时栈放 PSRAM，省内部 RAM）
            params,
            1,
            NULL,
            BOARD_TASK_CORE_1,  // 双核：核心 1；单核：核心 0
            BOARD_STACK_CAPS_AUDIO
        );
        if (ret != pdPASS) {
            ESP_LOGW(TAG, "创建刷新下载任务失败");
            free(params);
        }
    }
}
