/**
 * lyric_commands.c - 歌词与音乐元数据指令
 *
 * 移植自 xiaozhi-esp32-qingning 的歌词处理模式：
 *   1. 所有 lyric_line 存入带时间戳的缓冲区
 *   2. 进度定时器每秒触发，根据当前 elapsed 在缓冲区中找到对应歌词
 *   3. 歌词变化时才刷新 UI（避免一次性涌入覆盖）
 *
 * music_meta: 歌曲元数据
 * lyric_line: 歌词行（存入缓冲区）
 * music_end: 停止播放，重置
 */
#include "command_registry.h"
#include "config.h"
#include "eeui_port.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "cmd_lyric";

// 歌词条目结构（晴宁: vector<pair<int,string>> lyrics_）
#define MAX_LYRICS 200
static char *s_lyrics_text[MAX_LYRICS];
static uint32_t s_lyrics_time[MAX_LYRICS];
static int s_lyrics_count = 0;
static int s_current_lyric_index = -1;

// 进度自驱定时器
static esp_timer_handle_t s_progress_timer = NULL;
static uint64_t s_start_time_us = 0;
static uint32_t s_total_ms = 300000;
// duration 是否已由 music_meta 显式设置（true 时 lyric_line 不再覆盖 s_total_ms）
static bool s_duration_set = false;

// 歌词数据互斥锁：保护所有歌词数组及进度状态（防止 cmd_music_end 释放内存时定时器回调 use-after-free）
static SemaphoreHandle_t s_lyric_mutex = NULL;

// 进度定时器回调
static void progress_timer_cb(void *arg)
{
    if (!s_lyric_mutex) return;
    if (xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(10)) != pdTRUE) {
        return;
    }

    if (s_start_time_us == 0 || s_total_ms == 0) {
        xSemaphoreGive(s_lyric_mutex);
        return;
    }

    uint64_t now = esp_timer_get_time();
    uint32_t total_ms_snapshot = s_total_ms;
    uint32_t elapsed = (uint32_t)((now - s_start_time_us) / 1000);
    if (elapsed > total_ms_snapshot) elapsed = total_ms_snapshot;

    // 晴宁: UpdateLyricDisplay(current_time_ms) — 根据时间找歌词
    int new_index = -1;
    for (int i = 0; i < s_lyrics_count; i++) {
        if (s_lyrics_time[i] > elapsed) {
            new_index = i - 1;
            break;
        }
    }
    if (new_index < 0 && s_lyrics_count > 0) {
        // 所有歌词时间都 <= elapsed，显示最后一条
        new_index = s_lyrics_count - 1;
    }

    // 晴宁: 歌词变化时才更新 UI
    if (new_index != s_current_lyric_index && new_index >= 0) {
        s_current_lyric_index = new_index;

        const char *next = NULL;
        if (new_index + 1 < s_lyrics_count) {
            next = s_lyrics_text[new_index + 1];
        }
        eeui_port_music_update_lyrics(s_lyrics_text[new_index], next);
    }

    xSemaphoreGive(s_lyric_mutex);

    eeui_port_music_update_progress(elapsed, total_ms_snapshot);
}

// 调用者必须持有 s_lyric_mutex
static void start_progress_timer(void)
{
    s_start_time_us = esp_timer_get_time();
    if (s_progress_timer == NULL) {
        esp_timer_create_args_t targs = {};
        targs.callback = progress_timer_cb;
        targs.name = "music_progress";
        esp_err_t ret = esp_timer_create(&targs, &s_progress_timer);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to create progress timer: %s", esp_err_to_name(ret));
            s_start_time_us = 0;
            return;
        }
    }
    esp_timer_start_periodic(s_progress_timer, 200000);  // 200ms 高频检查
}

static void stop_progress_timer(void)
{
    if (s_progress_timer) {
        esp_timer_stop(s_progress_timer);
    }
}

static void reset_all(void)
{
    stop_progress_timer();
    if (s_lyric_mutex) xSemaphoreTake(s_lyric_mutex, portMAX_DELAY);
    for (int i = 0; i < s_lyrics_count; i++) {
        if (s_lyrics_text[i]) {
            free(s_lyrics_text[i]);
            s_lyrics_text[i] = NULL;
        }
    }
    s_lyrics_count = 0;
    s_current_lyric_index = -1;
    s_start_time_us = 0;
    s_total_ms = 300000;
    s_duration_set = false;
    if (s_lyric_mutex) xSemaphoreGive(s_lyric_mutex);
}

// 导出函数：供 audio_commands.c / network_audio.c 在停止播放时调用，
// 确保进度定时器停止、歌词清空、进度条归零
void lyric_commands_reset(void)
{
    // 进度条归零显示
    eeui_port_music_update_progress(0, 0);
    reset_all();
}

// 按时间插入歌词（晴宁: std::sort 后用 vector）
static void add_lyric(uint32_t time_ms, const char *text)
{
    if (s_lyric_mutex) xSemaphoreTake(s_lyric_mutex, portMAX_DELAY);
    if (s_lyrics_count >= MAX_LYRICS) {
        if (s_lyric_mutex) xSemaphoreGive(s_lyric_mutex);
        return;
    }
    s_lyrics_time[s_lyrics_count] = time_ms;
    s_lyrics_text[s_lyrics_count] = strdup(text);
    if (!s_lyrics_text[s_lyrics_count]) {
        ESP_LOGE(TAG, "strdup failed for lyric text, skipping");
        if (s_lyric_mutex) xSemaphoreGive(s_lyric_mutex);
        return;
    }
    s_lyrics_count++;
    // 冒泡排序保持时间递增（晴宁: sort(lyrics_.begin(), lyrics_.end())）
    for (int i = s_lyrics_count - 1; i > 0; i--) {
        if (s_lyrics_time[i] < s_lyrics_time[i - 1]) {
            uint32_t tmp_t = s_lyrics_time[i];
            s_lyrics_time[i] = s_lyrics_time[i - 1];
            s_lyrics_time[i - 1] = tmp_t;
            char *tmp_s = s_lyrics_text[i];
            s_lyrics_text[i] = s_lyrics_text[i - 1];
            s_lyrics_text[i - 1] = tmp_s;
        }
    }
    if (s_lyric_mutex) xSemaphoreGive(s_lyric_mutex);
}

// 解析 lyric_line JSON，存入缓冲区
static void parse_lyric_line(const char *json_str)
{
    if (!json_str) return;

    cJSON *obj = cJSON_Parse(json_str);
    if (!obj) return;

    cJSON *text = cJSON_GetObjectItem(obj, "text");
    cJSON *time_item = cJSON_GetObjectItem(obj, "time");

    if (text && cJSON_IsString(text)) {
        uint32_t t = 0;
        if (time_item && cJSON_IsNumber(time_item)) {
            t = (uint32_t)time_item->valuedouble;
        }
        ESP_LOGI(TAG, "歌词[%u]: %s", t, text->valuestring);
        add_lyric(t, text->valuestring);
    }

    if (time_item && cJSON_IsNumber(time_item)) {
        uint32_t t = (uint32_t)time_item->valuedouble;
        if (s_lyric_mutex && xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
            // 仅当 music_meta 未提供 duration 时，用歌词时间戳作为 fallback
            if (!s_duration_set && t + 10000 > s_total_ms) {
                s_total_ms = t + 10000;
            }
            xSemaphoreGive(s_lyric_mutex);
        }
    }

    cJSON_Delete(obj);
}

// music_meta
static esp_err_t cmd_music_meta(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (!data || !cJSON_IsString(data)) return ESP_OK;

    cJSON *obj = cJSON_Parse(data->valuestring);
    if (!obj) {
        eeui_port_music_set_song_info(data->valuestring, NULL);
        return ESP_OK;
    }

    cJSON *name = cJSON_GetObjectItem(obj, "song_name");
    if (!name || !cJSON_IsString(name)) name = cJSON_GetObjectItem(obj, "title");
    cJSON *artist = cJSON_GetObjectItem(obj, "artist");
    cJSON *duration_item = cJSON_GetObjectItem(obj, "duration");
    const char *song = (name && cJSON_IsString(name)) ? name->valuestring : "未知歌曲";
    const char *art = (artist && cJSON_IsString(artist)) ? artist->valuestring : "未知艺术家";
    ESP_LOGI(TAG, "歌曲: %s - %s", song, art);
    eeui_port_music_set_song_info(song, art);

    // 从 music_meta 中读取 duration（秒），设置实际歌曲总时长
    if (duration_item && cJSON_IsNumber(duration_item)) {
        uint32_t duration_sec = (uint32_t)duration_item->valuedouble;
        if (duration_sec > 0) {
            uint32_t duration_ms = duration_sec * 1000;
            if (s_lyric_mutex && xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                s_total_ms = duration_ms;
                s_duration_set = true;
                xSemaphoreGive(s_lyric_mutex);
            }
            ESP_LOGI(TAG, "歌曲总时长: %u 秒 (%u ms)", duration_sec, duration_ms);
        }
    }

    cJSON_Delete(obj);
    return ESP_OK;
}

// lyric_line
static esp_err_t cmd_lyric_line(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (!data) return ESP_OK;

    if (cJSON_IsString(data)) {
        parse_lyric_line(data->valuestring);
    } else if (cJSON_IsObject(data)) {
        cJSON *text = cJSON_GetObjectItem(data, "text");
        cJSON *time_item = cJSON_GetObjectItem(data, "time");
        uint32_t t = 0;
        if (time_item && cJSON_IsNumber(time_item)) {
            t = (uint32_t)time_item->valuedouble;
            // s_total_ms 修改需在锁内（与 add_lyric 的锁顺序，避免嵌套）
            if (s_lyric_mutex && xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                // 仅当 music_meta 未提供 duration 时，用歌词时间戳作为 fallback
                if (!s_duration_set && t + 10000 > s_total_ms) s_total_ms = t + 10000;
                xSemaphoreGive(s_lyric_mutex);
            }
        }
        if (text && cJSON_IsString(text)) {
            ESP_LOGI(TAG, "歌词[%u]: %s", t, text->valuestring);
            add_lyric(t, text->valuestring);
        }
    }

    // 第一条歌词：启动进度定时器（所有共享变量访问在锁内）
    if (s_lyric_mutex && xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        if (s_start_time_us == 0) {
            start_progress_timer();  // 调用者已持锁，start_progress_timer 不再单独加锁
            // 立即显示第一条歌词
            if (s_lyrics_count > 0) {
                const char *next = (s_lyrics_count > 1) ? s_lyrics_text[1] : NULL;
                eeui_port_music_update_lyrics(s_lyrics_text[0], next);
                s_current_lyric_index = 0;
            }
        }
        xSemaphoreGive(s_lyric_mutex);
    }
    return ESP_OK;
}

// music_end
static esp_err_t cmd_music_end(cJSON *json)
{
    ESP_LOGI(TAG, "音乐播放结束");
    // 读取 s_total_ms 需在锁内（reset_all 会修改并释放内存）
    uint32_t total_snapshot = 0;
    if (s_lyric_mutex && xSemaphoreTake(s_lyric_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        total_snapshot = s_total_ms;
        xSemaphoreGive(s_lyric_mutex);
    }
    if (total_snapshot > 0) {
        eeui_port_music_update_progress(total_snapshot, total_snapshot);
    }
    reset_all();  // 内部加锁，释放歌词内存并重置状态
    eeui_port_hide_music_player();  // 隐藏覆盖层，由新的 play_music 指令触发重建
    return ESP_OK;
}

void register_lyric_commands(void)
{
    if (s_lyric_mutex == NULL) {
        s_lyric_mutex = xSemaphoreCreateMutex();
    }

    static command_entry_t cmds[] = {
        {.type = "instruct", .command_id = "music_meta", .handler = cmd_music_meta, .description = "音乐元数据"},
        {.type = "instruct", .command_id = "lyric_line", .handler = cmd_lyric_line, .description = "歌词行"},
        {.type = "instruct", .command_id = "music_end", .handler = cmd_music_end, .description = "音乐播放结束"},
    };
    for (int i = 0; i < 3; i++) {
        command_registry_add(&cmds[i]);
    }
    ESP_LOGI(TAG, "歌词指令注册完成: music_meta, lyric_line, music_end");
}
