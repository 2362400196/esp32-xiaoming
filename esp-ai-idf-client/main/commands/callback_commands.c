/**
 * callback_commands.c - 服务端回调指令
 *
 * 移植自 Arduino 客户端:
 *   - on_llm_cb: 追加到缓冲区，由定时器逐段渲染（与 TTS 节拍同步）
 *   - on_iat_cb: ASR 识别结果，直接显示
 *   - tts_duration: 服务端下发的 TTS 总时长，用于字幕速度同步
 *   - on_tool_status: 工具调用状态
 *   - music_gen_ing: 音乐创作中
 *
 * 字幕与 TTS 同步机制（移植自 Arduino eeui_display.cpp espai_loop_eeui_text）：
 *   1. on_llm_cb 将文本追加到缓冲区 llm_text
 *   2. 500ms 定时器逐段切割显示，一次只显示一段
 *   3. 每段显示时长 = 剩余TTS时长 ÷ 剩余字数 × 段长
 *   4. 无 duration 时按已播放时间估算自动调节
 */

#include "command_registry.h"
#include "config.h"
#include "eeui_port.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "lvgl.h"

// 获取系统容器（eeui_port.cpp）
extern lv_obj_t *eeui_port_get_container(void);
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <string.h>

static const char *TAG = "cmd_callback";

// ==================== TTS 同步状态（全局，供外部设置）====================

/// TTS 是否正在播放（由 websocket 在 tts_chunk_start/tts_real_end 时设置）
bool s_tts_is_playing = false;
/// TTS 开始播放的时间戳（由 websocket 在 tts_chunk_start 时设置）
uint64_t s_tts_start_time_ms = 0;
/// 服务端下发的 TTS 总时长（ms），由 tts_duration 指令设置
int s_tts_duration_ms = 0;
/// TTS 状态互斥锁（保护上述三个变量，跨 WebSocket 任务与定时器回调）
SemaphoreHandle_t s_tts_state_mutex = NULL;

// ==================== 字幕状态 ====================

/// 完整 LLM 文本缓冲区（上限 2048 字节）
static char s_llm_text[2048] = "";

/// 已显示到的字节偏移（Arduino 的 processed_llm_text_index）
static int s_processed_index = 0;

/// 已显示的字数（用于 TTS 同步计算）
static int s_displayed_chars = 0;

/// 逐段显示定时器
static esp_timer_handle_t s_llm_timer = NULL;

/// 互斥锁
static SemaphoreHandle_t s_llm_mutex = NULL;

// ==================== 工具函数 ====================

/// 获取 UTF-8 字符的字节长度（Arduino utf8_char_length）
static int utf8_char_len(char firstByte)
{
    if (((unsigned char)firstByte & 0x80) == 0) return 1;
    else if (((unsigned char)firstByte & 0xE0) == 0xC0) return 2;
    else if (((unsigned char)firstByte & 0xF0) == 0xE0) return 3;
    else if (((unsigned char)firstByte & 0xF8) == 0xF0) return 4;
    return 1;
}

/// 统计字符串中的 Unicode 字符数（Arduino countTextLength）
static int count_text_chars(const char *str)
{
    int count = 0;
    while (*str) {
        uint8_t c = *str;
        if ((c & 0x80) == 0x00) str += 1;
        else if ((c & 0xE0) == 0xC0) str += 2;
        else if ((c & 0xF0) == 0xE0) str += 3;
        else if ((c & 0xF8) == 0xF0) str += 4;
        else str += 1;
        count++;
    }
    return count;
}

/// 获取当前时间戳（ms），相当于 Arduino 的 millis()
static uint64_t now_ms(void)
{
    return esp_timer_get_time() / 1000;
}

// ==================== 定时器回调：逐段渲染（Arduino espai_loop_eeui_text）====================

static void llm_timer_cb(void *arg)
{
    if (xSemaphoreTake(s_llm_mutex, pdMS_TO_TICKS(10)) != pdTRUE) {
        return;
    }

    int total_len = strlen(s_llm_text);
    if (total_len <= 0 || s_processed_index >= total_len) {
        xSemaphoreGive(s_llm_mutex);
        return;
    }

    // 从 s_processed_index 开始取一段
    int current_pos = s_processed_index;
    int next_pos = current_pos;
    bool is_english_segment = true;  // 提升作用域，供 TTS 节拍同步使用

    while (next_pos < total_len) {
        int charByteLen = utf8_char_len(s_llm_text[next_pos]);
        if (next_pos + charByteLen > total_len) break;
        next_pos += charByteLen;

        // 判断是否是英文字母
        is_english_segment = true;
        for (int i = current_pos; i < next_pos; i++) {
            if ((unsigned char)s_llm_text[i] > 127) {
                is_english_segment = false;
                break;
            }
        }

        if (is_english_segment) {
            // 英文：最多 12 字符，按单词边界分割
            if (next_pos - current_pos > 12) {
                bool is_word_boundary = false;
                if (next_pos < total_len) {
                    char c = s_llm_text[next_pos];
                    is_word_boundary = (c == ' ' || c == '.' || c == ',' ||
                                       c == '!' || c == '?' || c == ';' ||
                                       c == ':');
                }
                if (is_word_boundary || next_pos - current_pos > 18) break;
            }
        } else {
            // 中文/混排：最多 30 字节（约 10 个汉字）
            if (next_pos - current_pos > 30) break;
        }
    }

    if (next_pos > current_pos) {
        // 取到一段文本
        char segment_buf[64];
        int seg_len = next_pos - current_pos;
        if (seg_len > (int)sizeof(segment_buf) - 1) seg_len = sizeof(segment_buf) - 1;
        memcpy(segment_buf, s_llm_text + current_pos, seg_len);
        segment_buf[seg_len] = '\0';

        // 显示这段文本
        display_show_text(segment_buf);

        // 计算这段的字数
        int text_chars = count_text_chars(segment_buf);
        s_processed_index = next_pos;

        // === TTS 节拍同步（Arduino eeui_display.cpp 第 105-147 行）===
        // 用 s_tts_state_mutex 保护 TTS 状态变量的读取（跨线程访问）
        bool tts_playing;
        uint64_t tts_start_ms;
        int tts_duration;
        if (s_tts_state_mutex) {
            xSemaphoreTake(s_tts_state_mutex, portMAX_DELAY);
            tts_playing = s_tts_is_playing;
            tts_start_ms = s_tts_start_time_ms;
            tts_duration = s_tts_duration_ms;
            xSemaphoreGive(s_tts_state_mutex);
        } else {
            tts_playing = s_tts_is_playing;
            tts_start_ms = s_tts_start_time_ms;
            tts_duration = s_tts_duration_ms;
        }
        uint64_t elapsed = now_ms() - tts_start_ms;
        int base_speed = is_english_segment ? 80 : 200;  // ms/字，中文慢速确保与语音同步
        int current_speed = base_speed;

        if (tts_playing && tts_duration > 0 && total_len > 0) {
            // 服务端提供准确 duration：剩余时长 ÷ 剩余字数
            int total_chars = count_text_chars(s_llm_text);
            int remain_chars = total_chars - s_displayed_chars - text_chars;
            if (remain_chars > 0 && total_chars > 0) {
                int remain_ms = tts_duration - (int)elapsed;
                if (remain_ms < 300) remain_ms = 300;
                int precise_speed = remain_ms / remain_chars;
                if (precise_speed > 30 && precise_speed < 800) {
                    current_speed = precise_speed;
                }
            }
        } else if (tts_playing) {
            // 无 duration：按已播放时间自适应调节
            int expected_chars = (int)(elapsed / base_speed);
            if (s_displayed_chars + text_chars < expected_chars)
                current_speed = (int)(base_speed * 0.8);
            else if (s_displayed_chars + text_chars > expected_chars + 5)
                current_speed = (int)(base_speed * 1.2);
        } else {
            // TTS 未开始播放时，大幅放慢字幕滚动速度，避免字幕提前走完
            current_speed = 300;  // 300ms/字，约 3 秒一段
        }

        s_displayed_chars += text_chars;

        // 确定下一段的延迟时间（Arduino: display_time = text_chars * current_speed）
        int display_time = text_chars * current_speed;
        if (display_time < 1000) display_time = 1000;  // 至少 1 秒，避免字幕滚动太快

        // 重置定时器到计算出的延迟时间（Arduino: eeui_next_render_time = millis() + display_time）
        if (s_llm_timer) {
            esp_timer_stop(s_llm_timer);
            esp_err_t tr = esp_timer_start_periodic(s_llm_timer, display_time * 1000);
            if (tr != ESP_OK) {
                ESP_LOGE(TAG, "Failed to restart llm_timer: %s", esp_err_to_name(tr));
            }
        }
    }

    xSemaphoreGive(s_llm_mutex);
}

// ==================== 公共 API ====================

const char *callback_get_llm_text(void)
{
    // 注意：返回的是内部缓冲区指针，调用方应在持有 s_llm_mutex 时使用，
    // 或使用 callback_copy_llm_text() 获取线程安全的拷贝。
    if (xSemaphoreTake(s_llm_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        const char *ptr = s_llm_text;
        xSemaphoreGive(s_llm_mutex);
        return ptr;
    }
    return s_llm_text;
}

// 线程安全地拷贝 LLM 文本到调用方提供的缓冲区
bool callback_copy_llm_text(char *buf, size_t buf_size)
{
    if (!buf || buf_size == 0) return false;
    if (xSemaphoreTake(s_llm_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        strlcpy(buf, s_llm_text, buf_size);
        xSemaphoreGive(s_llm_mutex);
        return true;
    }
    buf[0] = '\0';
    return false;
}

void callback_reset_llm_text(void)
{
    if (xSemaphoreTake(s_llm_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        s_llm_text[0] = '\0';
        s_processed_index = 0;
        s_displayed_chars = 0;
        xSemaphoreGive(s_llm_mutex);
    }
    // 恢复定时器到 500ms 周期（Arduino 默认 500ms）
    if (s_llm_timer) {
        esp_timer_stop(s_llm_timer);
        esp_timer_start_periodic(s_llm_timer, 500000);
    }
}

// ==================== 指令处理函数 ====================

// on_iat_cb: ASR 识别结果（Arduino command_handler.cpp on_iat_cb）
static esp_err_t cmd_on_iat_cb(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        ESP_LOGI(TAG, "ASR: %s", data->valuestring);
        // 新对话开始，清除可能残留的工具状态
        eeui_port_clear_tool_status();
        // 与 Arduino 一致：重置 llm_text，显示 ASR 文本
        callback_reset_llm_text();
        display_show_text(data->valuestring);
    }
    return ESP_OK;
}

// on_llm_cb: LLM 回复文本（Arduino command_handler.cpp on_llm_cb）
static esp_err_t cmd_on_llm_cb(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        ESP_LOGI(TAG, "LLM: %s", data->valuestring);

        // 安全措施：LLM 文字到达时，清除可能残留的工具状态显示
        eeui_port_clear_tool_status();

        const char *text_to_show = NULL;
        char text_buf[256];

        // 解析内层 JSON 提取 text 字段（兼容自定义服务器的纯文本）
        cJSON *inner = cJSON_Parse(data->valuestring);
        if (inner) {
            cJSON *text = cJSON_GetObjectItem(inner, "text");
            if (text && cJSON_IsString(text)) {
                text_to_show = text->valuestring;
            } else if (cJSON_IsString(inner)) {
                // 自定义服务器：data 是纯文本（如 "我在等你呀，"），JSON 解析后是字符串
                text_to_show = inner->valuestring;
            }
            if (text_to_show) {
                strncpy(text_buf, text_to_show, sizeof(text_buf) - 1);
                text_buf[sizeof(text_buf) - 1] = '\0';
                text_to_show = text_buf;
            }
            cJSON_Delete(inner);
        } else {
            text_to_show = data->valuestring;
        }

        if (!text_to_show) return ESP_OK;

        // 追加到缓冲区，由定时器逐段渲染（Arduino 一致）
        if (xSemaphoreTake(s_llm_mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
            size_t cur_len = strlen(s_llm_text);
            size_t remaining = sizeof(s_llm_text) - cur_len - 1;
            if (remaining > 0) {
                strncat(s_llm_text, text_to_show, remaining);
            }
            xSemaphoreGive(s_llm_mutex);
        }
    }
    return ESP_OK;
}

// tts_duration: 服务端下发 TTS 总时长（Arduino 的 tts_duration_ms）
static esp_err_t cmd_tts_duration(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        int dur = atoi(data->valuestring);
        if (dur > 0) {
            if (s_tts_state_mutex) {
                xSemaphoreTake(s_tts_state_mutex, portMAX_DELAY);
                s_tts_duration_ms = dur;
                xSemaphoreGive(s_tts_state_mutex);
            } else {
                s_tts_duration_ms = dur;
            }
            ESP_LOGI(TAG, "TTS 时长: %dms", dur);
        }
    }
    return ESP_OK;
}

// on_tool_status: 工具调用状态
// 空字符串 = 清除工具状态；非空 = 显示在底部（与字幕同位置，独立标签，不影响字幕）
static esp_err_t cmd_on_tool_status(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        if (strlen(data->valuestring) == 0) {
            // 空字符串 → 清除工具状态，字幕恢复可见
            eeui_port_clear_tool_status();
            ESP_LOGI(TAG, "工具状态已清除");
        } else {
            ESP_LOGI(TAG, "工具: %s", data->valuestring);
            eeui_port_set_tool_status_text(data->valuestring);
        }
    }
    return ESP_OK;
}

// music_gen_ing: 音乐创作中
static esp_err_t cmd_music_gen_ing(cJSON *json)
{
    ESP_LOGI(TAG, "音乐创作中");
    display_show_emotion("无情绪");
    display_show_status("歌曲创作中");
    return ESP_OK;
}

// ==================== 注册指令 ====================

// clear_screen: 清空屏幕上的 Lua 绘图
static esp_err_t cmd_clear_screen(cJSON *json)
{
    ESP_LOGI(TAG, "清空 Lua 绘图");

    // 所有 LVGL 操作必须通过 eeui_port_lvgl_lock/unlock 加锁保护
    if (!eeui_port_lvgl_lock(pdMS_TO_TICKS(200))) {
        ESP_LOGW(TAG, "LVGL lock timeout, skip clear_screen");
        return ESP_ERR_TIMEOUT;
    }

    // 遍历 scr 的子对象，只保留系统容器 s_container
    // Lua 脚本在 scr 上创建的对象会被删除
    lv_obj_t *scr = lv_scr_act();
    lv_obj_t *container = eeui_port_get_container();
    uint32_t child_cnt = lv_obj_get_child_count(scr);
    for (int32_t i = (int32_t)child_cnt - 1; i >= 0; i--) {
        lv_obj_t *child = lv_obj_get_child(scr, i);
        if (child && child != container) {
            lv_obj_delete(child);
        }
    }

    eeui_port_lvgl_unlock();

    display_show_text("");
    return ESP_OK;
}

// 外部函数声明
extern void register_volume_commands(void);

void register_callback_commands(void)
{
    if (s_llm_mutex == NULL) {
        s_llm_mutex = xSemaphoreCreateMutex();
    }
    if (s_tts_state_mutex == NULL) {
        s_tts_state_mutex = xSemaphoreCreateMutex();
    }

    static command_entry_t entries[] = {
        {.type = "instruct", .command_id = "on_iat_cb",      .handler = cmd_on_iat_cb,      .description = "ASR 识别结果回调"},
        {.type = "instruct", .command_id = "on_llm_cb",      .handler = cmd_on_llm_cb,      .description = "LLM 回复回调"},
        {.type = "instruct", .command_id = "tts_duration",   .handler = cmd_tts_duration,   .description = "TTS 时长同步"},
        {.type = "instruct", .command_id = "on_tool_status", .handler = cmd_on_tool_status, .description = "工具调用状态"},
        {.type = "instruct", .command_id = "music_gen_ing",  .handler = cmd_music_gen_ing,  .description = "音乐创作中状态"},
        {.type = "instruct", .command_id = "clear_screen",   .handler = cmd_clear_screen,   .description = "清空屏幕字幕"},
    };
    for (int i = 0; i < sizeof(entries) / sizeof(entries[0]); i++) {
        command_registry_add(&entries[i]);
    }

    // 注册音量控制指令（需显式调用，ESP-IDF 链接器不包含 constructor 段）
    register_volume_commands();

    // 创建逐段渲染定时器（Arduino 500ms）
    if (s_llm_timer == NULL) {
        const esp_timer_create_args_t timer_args = {
            .callback = llm_timer_cb,
            .name = "llm_render",
        };
        esp_err_t ret = esp_timer_create(&timer_args, &s_llm_timer);
        if (ret == ESP_OK) {
            esp_timer_start_periodic(s_llm_timer, 500000);
            ESP_LOGI(TAG, "字幕渲染定时器已启动 (500ms)");
        } else {
            ESP_LOGE(TAG, "创建字幕渲染定时器失败");
        }
    }
}
