#include "config.h"
#include "boards/board_interface.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_http_client.h"
#include "freertos/semphr.h"
#include "esp_crt_bundle.h"
#include "cJSON.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "commands/command_registry.h"
#include "ota_update.h"
#include "device_id.h"
#include <time.h>
#include <sys/time.h>  /* settimeofday（stc_time 同步系统时间，屏保时钟用） */

/* 字幕 TTS 同步状态（定义在 callback_commands.c） */
extern bool s_tts_is_playing;
extern uint64_t s_tts_start_time_ms;
extern int s_tts_duration_ms;
/* TTS 状态互斥锁（定义在 callback_commands.c，保护上述三个变量） */
extern SemaphoreHandle_t s_tts_state_mutex;

/* 会话看门狗刷新（定义在 main.c）：收到服务端数据时重置会话超时计时 */
extern void session_watchdog_refresh(void);

/* WiFi 断线自愈接口（定义在 wifi.c） */
extern bool wifi_is_connected(void);
extern void wifi_force_reconnect(void);

static const char *TAG = "websocket";

/* 断线自愈：连续断开计数。esp_websocket_client 自动重连失败会反复触发
 * EVENT_DISCONNECTED（约 18s 一次：reconnect 3s + connect 15s 超时），
 * 达到阈值后逐级升级：检查 WiFi -> 强制重建 WiFi -> 整机重启。 */
static int s_disconnect_count = 0;
#define WS_SELF_HEAL_CHECK_WIFI_THRESHOLD  3   /* ~54s：检查 WiFi，掉线则重连 */
#define WS_SELF_HEAL_FORCE_WIFI_THRESHOLD  6   /* ~108s：无条件强制重建 WiFi */
#define WS_SELF_HEAL_RESTART_THRESHOLD     15  /* ~4.5min：整机重启兜底恢复 */

static esp_websocket_client_handle_t s_client = NULL;
static bool s_is_connected = false;
static bool s_reconnect_pending = false;  // 防止重复创建重连任务
static SemaphoreHandle_t s_ws_mutex = NULL;  // websocket 互斥锁（保护重连/发送状态）

// 延迟重连任务：服务端主动关闭后手动触发重连
// 注意：managed 版 esp_websocket_client 的 start() 要求 state < INIT，
// 必须先用 stop() 把 state 重置为 UNKNOW，否则 start 报 "The client has started"
// 且什么都不做（实测 config_updated 后重连失败、连接卡死）。
// 且 stop() 不能在 websocket 任务上下文调用（stop_wait_task 有检查），
// 因此 stop+start 都放在本独立任务中执行。
static void reconnect_task(void *arg)
{
    vTaskDelay(pdMS_TO_TICKS(3000));
    if (s_client) {
        esp_websocket_client_stop(s_client);
        vTaskDelay(pdMS_TO_TICKS(100));  // 等状态稳定
        esp_websocket_client_start(s_client);
    }
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    s_reconnect_pending = false;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    vTaskDelete(NULL);
}

// 强制重连 WebSocket:配置变更(config_updated)后调用,重新握手使新配置生效。
// 对已连接的连接,esp_websocket_client_start() 会先 stop 再 connect,触发完整重连流程。
void websocket_force_reconnect(void)
{
    if (!s_client) return;
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    if (s_reconnect_pending) {
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        return;
    }
    s_reconnect_pending = true;
    s_is_connected = false;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    ESP_LOGW(TAG, "配置已更新,强制重连 WebSocket 使新配置生效");
    xTaskCreate(reconnect_task, "ws_recon", 2048, NULL, 3, NULL);
}
static bool s_is_official = false;        // 是否连接到官方服务器
static bool s_music_streaming = false;    // 音乐推流模式(play_audio + tts_task_id="play_music")
static char s_server_http_base[256] = {0}; // HTTP 基础 URL（用于 OTA 查询）
static bool s_ota_checked = false;         // OTA 是否已检查过（仅首次连接检查）

// 排空完成后执行的动作类型
typedef enum {
    DRAIN_ACTION_NONE,       // 无操作，由 send_audio_over() 处理
    DRAIN_ACTION_CONTINUE,   // 连续对话（"02"）
    DRAIN_ACTION_SESSION_END,// 会话结束继续（"03"）
} drain_action_t;
static drain_action_t s_drain_action = DRAIN_ACTION_NONE;

// 音频播放状态
static bool s_audio_playing = false;
static bool s_audio_over_sent = false;  // 防止重复发送 client_out_audio_over
char s_current_session_id[5] = "0001";
char s_current_tts_task_id[16] = "";
static esp_timer_handle_t s_drain_check_timer = NULL;
static esp_timer_handle_t s_flow_ctrl_timer = NULL;  // 官方服务器流控上报定时器
static int64_t s_last_keepalive_ms = 0;  // 上次收到 keepalive 的时间
// 唤醒响应超时检测：发送 start 后若超过阈值未收到服务端任何数据，判定连接半开并主动重连
static volatile bool s_wakeup_pending = false;
static int64_t s_wakeup_sent_ms = 0;
static void send_audio_over(void);  // 前向声明
static void send_audio_over_internal(const char *session_status);  // 前向声明

// 定时检查音频播放完成，不等 keepalive（keepalive 间隔 5s，唤醒音频可能 <2s）
static void drain_check_timer_cb(void *arg)
{
    if (!audio_spk_check_drain_done()) {
        return;
    }
    // 排空完成
    if (s_drain_check_timer) {
        esp_timer_stop(s_drain_check_timer);
    }

    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    drain_action_t action = s_drain_action;
    s_drain_action = DRAIN_ACTION_NONE;
    s_audio_playing = false;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);

    if (action == DRAIN_ACTION_CONTINUE) {
	        // 二进制 "02" (SID_TTS_END_RESTART)：继续对话，与 Arduino wakeUp("continue") 一致
	        // 服务端发完 "02" 结束帧后会自动发 iat_start，无需客户端主动 start（避免与服务端
	        // _start_next_asr 竞态）。这里只停止唤醒监听，等 iat_start 启动麦克风。
	        audio_spk_stop();
	        vTaskDelay(pdMS_TO_TICKS(50));
	        // tts_task_id 已在二进制处理器中清除（与 Arduino 一致）
	        send_audio_over_internal("02");
	        // Arduino wakeUp("continue"): esp_ai_session_id = ""
	        // 清除旧 session_id，新 session_start 会设置新的
	        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
	        s_current_session_id[0] = '\0';
	        s_audio_over_sent = false;  // 新会话重置发送标志
	        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
	        // 注意：不在这里调用 wakeup_pause()！WakeNet 已在上一轮 iat_end 重建并运行，
	        // 这里提前销毁会导致 WakeNet 永久失效（需等 iat_end 才能重建）。
	        // iat_start 处理器内部会检查 WakeNet 状态并自行暂停。
	        display_show_status("聆听中");
        display_show_emotion("聆听中");
        display_show_text("");
    } else if (action == DRAIN_ACTION_SESSION_END) {
        // 二进制 "03" (SID_TTS_END)：会话结束，与 Arduino SID_TTS_END 一致
        // Arduino 流程：wait_mp3_player_done → send over("03") → clear tts_task_id → session_end
        audio_spk_stop();
        vTaskDelay(pdMS_TO_TICKS(50));
        // 确保麦克风已停止（应已在 iat_end 中停止，此处为安全兜底）
        audio_mic_stop();
        // 发送时保留 tts_task_id（Arduino 在发送后才清除）
        send_audio_over_internal("03");
        // 发送后清除 tts_task_id（与 Arduino 一致）
        s_current_tts_task_id[0] = '\0';
        // 会话结束，恢复语音唤醒
        wakeup_resume();
        power_manager_set_active(false);  // 回待机省电（WiFi modem sleep）
        display_show_status("等待唤醒...");
        display_show_emotion("休息中");
        display_show_text("");
    } else {
        send_audio_over();
    }
}

// 流控上报定时器回调：官方服务器模式下，定期上报缓冲区剩余空间
// Arduino 的 play_audio.cpp:play_audio_task_static 每 ~1s 发送 client_available_audio
// 使用非阻塞发送（短超时），避免在 ASR 二进制音频帧发送时抢锁
static void flow_ctrl_timer_cb(void *arg)
{
    if (!s_is_connected || !s_is_official) {
        return;
    }
    // 麦克风录音时不要抢锁发文本（流控数据对 ASR 阶段无意义）
    if (audio_mic_is_running()) {
        return;
    }

    size_t available = audio_spk_buffer_available();
    char msg[96];
    snprintf(msg, sizeof(msg),
             "{\"type\":\"client_available_audio\",\"session_id\":\"%s\",\"value\":%u}",
             s_current_session_id, (unsigned)available);
    websocket_send_text_nb(msg);
}


// ID3v2 标签大小缓存（原始 helix 解码器内部自己会跳过 ID3，此处仅做优化预跳过）
static int s_id3_skip_size = 0;
// 音频帧计数（限流诊断日志用）
static uint32_t s_bin_frame_count = 0;

// ==================== 唤醒提示音缓存 ====================
// 服务端连接时以 BIN 帧下发唤醒提示音缓存（与 Arduino SID_TONE_CACHE/SID_WAKEUP_REP_CACHE 一致）：
//   session_id="1000" = 唤醒"叮"声  → s_cache_tone
//   session_id="1001" = 唤醒问候语  → s_cache_greeting
// 唤醒时（handle_wakeup）本地播放，不依赖服务端实时下发。
#define CACHE_AUDIO_MAX (512 * 1024)   // 单条缓存上限 512KB
static uint8_t *s_cache_tone = NULL;
static size_t s_cache_tone_len = 0, s_cache_tone_cap = 0;
static uint8_t *s_cache_greeting = NULL;
static size_t s_cache_greeting_len = 0, s_cache_greeting_cap = 0;

static void cache_audio_append(uint8_t **buf, size_t *len, size_t *cap,
                               const uint8_t *data, size_t data_len)
{
    if (data_len == 0) return;
    if (*len + data_len > CACHE_AUDIO_MAX) return;  // 超限丢弃
    if (*len + data_len > *cap) {
        size_t new_cap = *cap ? *cap * 2 : 4096;
        while (new_cap < *len + data_len) new_cap *= 2;
        if (new_cap > CACHE_AUDIO_MAX) new_cap = CACHE_AUDIO_MAX;
        uint8_t *nb = realloc(*buf, new_cap);
        if (!nb) return;
        *buf = nb;
        *cap = new_cap;
    }
    memcpy(*buf + *len, data, data_len);
    *len += data_len;
}

// 清空唤醒提示音缓存（重连/断开时调用）
void websocket_cache_clear(void)
{
    if (s_cache_tone) { free(s_cache_tone); s_cache_tone = NULL; }
    s_cache_tone_len = 0; s_cache_tone_cap = 0;
    if (s_cache_greeting) { free(s_cache_greeting); s_cache_greeting = NULL; }
    s_cache_greeting_len = 0; s_cache_greeting_cap = 0;
}

// 获取唤醒"叮"声缓存（未缓存返回 false）
bool websocket_cache_get_tone(const uint8_t **data, size_t *len)
{
    if (s_cache_tone_len == 0) return false;
    *data = s_cache_tone;
    *len = s_cache_tone_len;
    return true;
}

// 获取唤醒问候语缓存（未缓存返回 false）
bool websocket_cache_get_greeting(const uint8_t **data, size_t *len)
{
    if (s_cache_greeting_len == 0) return false;
    *data = s_cache_greeting;
    *len = s_cache_greeting_len;
    return true;
}

// 获取设备ID（使用 device_id.h 中的 device_id_get）
static uint8_t *s_bin_msg_buf = NULL;
static size_t s_bin_msg_buf_cap = 0;
static size_t s_bin_msg_expected_len = 0;
static size_t s_bin_msg_received_len = 0;

static void get_device_mac(char *mac_str, size_t len)
{
    device_id_get(mac_str, len);
}

// 发送音频播放完成确认（纯发送，不包含显示清理）
// session_status: "02" = 继续对话, "03" = 会话结束
static void send_audio_over_internal(const char *session_status)
{
    char msg[128];
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    if (s_audio_over_sent) {
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        return;  // 已发送，不重复
    }
    s_audio_over_sent = true;
    snprintf(msg, sizeof(msg),
             "{\"type\":\"client_out_audio_over\",\"session_id\":\"%s\",\"session_status\":\"%s\",\"tts_task_id\":\"%s\"}",
             s_current_session_id, session_status, s_current_tts_task_id);
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    ESP_LOGI(TAG, "发送音频播放完成: %s", msg);
    websocket_send_text(msg);
}

// 发送音频播放完成确认 + 清理显示
static void send_audio_over(void)
{
    // 守卫：只在音频播放中或会话结束时才发送
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    bool skip = (!s_audio_playing && s_drain_action == DRAIN_ACTION_NONE);
    if (skip) {
        s_audio_playing = false;
    }
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    if (skip) {
        ESP_LOGW(TAG, "音频已停止，跳过发送 client_out_audio_over");
        if (s_drain_check_timer) {
            esp_timer_stop(s_drain_check_timer);
        }
        return;
    }
    send_audio_over_internal("03");
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    s_audio_playing = false;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    // 停止 drain 检查定时器
    if (s_drain_check_timer) {
        esp_timer_stop(s_drain_check_timer);
    }
    // 不在这里恢复语音唤醒！Arduino 版本在 session_end 后才恢复
    // iat_start 会到来，此时 WakeNet 应保持暂停状态
    display_show_status("等待唤醒...");
    display_show_emotion("休息中");
    display_show_text("");  // 清除底部字幕
}

static void handle_audio_binary_message(const uint8_t *payload, size_t len)
{
    // 记录所有二进制帧（用于调试）
    ESP_LOGD(TAG, "Binary frame: len=%d, first bytes: %02x %02x %02x %02x %02x %02x",
             (int)len,
             len > 0 ? payload[0] : 0, len > 1 ? payload[1] : 0,
             len > 2 ? payload[2] : 0, len > 3 ? payload[3] : 0,
             len > 4 ? payload[4] : 0, len > 5 ? payload[5] : 0);

    // 所有服务器统一使用 6 字节头部格式（与 Arduino 客户端完全一致）
    // Arduino 客户端不区分官方/自定义服务器，始终按 6 字节头部解析：
    //   session_id(4 bytes) + status(2 bytes) + audio_data
    // 官方服务器(node.espai.fun)和自定义服务器使用相同的二进制音频帧格式
    if (len < 6) {
        return;
    }

    char session_id[5] = {0};
    char status[3] = {0};
    memcpy(session_id, payload, 4);
    memcpy(status, payload + 4, 2);

    const uint8_t *audio_data = payload + 6;
    size_t audio_len = len - 6;

    // 唤醒提示音缓存帧（对齐 Arduino SID_TONE_CACHE="1000" / SID_WAKEUP_REP_CACHE="1001"）：
    // 服务端连接时下发，存入缓存供唤醒时播放，不直接播放（否则会混入连接提示音乱响）
    if (memcmp(session_id, "1000", 4) == 0) {
        cache_audio_append(&s_cache_tone, &s_cache_tone_len, &s_cache_tone_cap, audio_data, audio_len);
        return;
    }
    if (memcmp(session_id, "1001", 4) == 0) {
        cache_audio_append(&s_cache_greeting, &s_cache_greeting_len, &s_cache_greeting_cap, audio_data, audio_len);
        return;
    }

    // 限流诊断日志：默认日志级别(INFO)下也能确认二进制音频帧是否到达设备
    // 每 50 帧打印一次，避免刷屏
    if (audio_len > 0 && (s_bin_frame_count++ % 50) == 0) {
        ESP_LOGD(TAG, "收到音频数据帧#%u: len=%d status=%.2s", (unsigned)(s_bin_frame_count - 1), (int)audio_len, status);
    }

    if (audio_len >= 3 && audio_data[0] == 'I' && audio_data[1] == 'D' && audio_data[2] == '3') {
        ESP_LOGD(TAG, "New MP3 stream with ID3 tag");
        if (audio_len >= 10) {
            size_t sz = ((audio_data[6] & 0x7F) << 21) |
                        ((audio_data[7] & 0x7F) << 14) |
                        ((audio_data[8] & 0x7F) << 7) |
                        (audio_data[9] & 0x7F);
            int id3_total = 10 + (int)sz;
            // 上限验证：ID3v2 标签通常不超过 1MB，异常值则忽略
            if (id3_total > 0 && id3_total <= 1024 * 1024) {
                s_id3_skip_size = id3_total;
                ESP_LOGD(TAG, "ID3v2 tag size: %d bytes", s_id3_skip_size);
            } else {
                s_id3_skip_size = 0;
                ESP_LOGW(TAG, "ID3v2 tag size %d out of range, ignoring", id3_total);
            }
        }
    }

    if (s_id3_skip_size > 0) {
        if ((int)audio_len <= s_id3_skip_size) {
            s_id3_skip_size -= (int)audio_len;
            audio_len = 0;
        } else {
            audio_data += s_id3_skip_size;
            audio_len -= s_id3_skip_size;
            s_id3_skip_size = 0;
            ESP_LOGD(TAG, "ID3 skip complete, audio bytes: %d", (int)audio_len);
        }
    }

    if (audio_len > 0) {
        ESP_LOGD(TAG, "Audio data: %d bytes", (int)audio_len);
        audio_spk_write(audio_data, audio_len);
    }

    // 处理音频帧状态（与 Arduino 一致）
    // "02" = TTS 结束，需要继续对话 → 自动开始下一轮 ASR
    // "03" = TTS 结束，无需继续 → 进入待机
    if (memcmp(status, "01", 2) == 0) {
        // TTS 片段结束（SID_TTS_CHUNK_END），与 Arduino 一致：清除 tts_task_id
        ESP_LOGD(TAG, "TTS chunk end");
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_current_tts_task_id[0] = '\0';
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    } else if (memcmp(status, "02", 2) == 0) {
        ESP_LOGI(TAG, "TTS 结束，继续下一轮对话");
        // 与 Arduino SID_TTS_END_RESTART 一致：
        // 1. 先清除 tts_task_id（Arduino 在 wait_mp3_player_done 之前清除）
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_current_tts_task_id[0] = '\0';
        // 2. 设置 drain action，等待音频播完后由 drain_check_timer_cb 处理
        s_audio_playing = false;
        s_drain_action = DRAIN_ACTION_CONTINUE;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        // 启动 drain 定时器，等待音频播完后再处理连续对话
        audio_spk_wait_drain();
        if (!s_drain_check_timer) {
            const esp_timer_create_args_t timer_args = {
                .callback = drain_check_timer_cb,
                .name = "drain_check",
            };
            esp_err_t tr = esp_timer_create(&timer_args, &s_drain_check_timer);
            if (tr != ESP_OK) {
                ESP_LOGE(TAG, "Failed to create drain_check timer: %s", esp_err_to_name(tr));
                return;
            }
        }
        esp_timer_start_periodic(s_drain_check_timer, 200000);
    } else if (memcmp(status, "03", 2) == 0) {
        ESP_LOGI(TAG, "TTS 结束，本轮对话完成 (payload=%d bytes)", (int)audio_len);
        // 与 Arduino SID_TTS_END 一致：
        // 不在此处清除 tts_task_id（Arduino 在发送 over 后才清除）
        // drain_check_timer_cb 会在音频播完后发送 over("03") 并清除 tts_task_id
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_drain_action = DRAIN_ACTION_SESSION_END;
        s_audio_playing = false;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        // 不能阻塞 WebSocket 回调！改用 drain 定时器
        audio_spk_wait_drain();
        if (!s_drain_check_timer) {
            const esp_timer_create_args_t timer_args = {
                .callback = drain_check_timer_cb,
                .name = "drain_check",
            };
            esp_err_t tr = esp_timer_create(&timer_args, &s_drain_check_timer);
            if (tr != ESP_OK) {
                ESP_LOGE(TAG, "Failed to create drain_check timer: %s", esp_err_to_name(tr));
                return;
            }
        }
        esp_timer_start_periodic(s_drain_check_timer, 200000);
    }
}

static void handle_audio_binary_event(const esp_websocket_event_data_t *data)
{
    ESP_LOGD(TAG, "Binary event: payload_len=%d, offset=%d, data_len=%d",
             (int)data->payload_len, (int)data->payload_offset, (int)data->data_len);
    if (data->payload_len <= 0) {
        return;
    }

    size_t payload_len = (size_t)data->payload_len;
    size_t offset = (size_t)data->payload_offset;
    size_t data_len = (size_t)data->data_len;

    if (offset == 0 && data_len == payload_len) {
        handle_audio_binary_message((const uint8_t *)data->data_ptr, data_len);
        return;
    }

    if (offset == 0) {
        s_bin_msg_expected_len = payload_len;
        s_bin_msg_received_len = 0;
        if (s_bin_msg_buf_cap < payload_len) {
            uint8_t *new_buf = (uint8_t *)realloc(s_bin_msg_buf, payload_len);
            if (!new_buf) {
                ESP_LOGE(TAG, "Failed to allocate WS binary reassembly buffer: %d bytes", (int)payload_len);
                free(s_bin_msg_buf);
                s_bin_msg_buf = NULL;
                s_bin_msg_buf_cap = 0;
                s_bin_msg_expected_len = 0;
                return;
            }
            s_bin_msg_buf = new_buf;
            s_bin_msg_buf_cap = payload_len;
        }
    }

    if (!s_bin_msg_buf || s_bin_msg_expected_len != payload_len ||
        offset + data_len > s_bin_msg_expected_len) {
        ESP_LOGW(TAG, "Drop malformed WS binary fragment: off=%d len=%d total=%d expected=%d",
                 (int)offset, (int)data_len, (int)payload_len, (int)s_bin_msg_expected_len);
        s_bin_msg_expected_len = 0;
        s_bin_msg_received_len = 0;
        return;
    }

    if (data_len > 0) {
        memcpy(s_bin_msg_buf + offset, data->data_ptr, data_len);
        size_t end = offset + data_len;
        if (end > s_bin_msg_received_len) {
            s_bin_msg_received_len = end;
        }
    }

    if (s_bin_msg_received_len >= s_bin_msg_expected_len) {
        handle_audio_binary_message(s_bin_msg_buf, s_bin_msg_expected_len);
        s_bin_msg_expected_len = 0;
        s_bin_msg_received_len = 0;
    }
}

// OTA 检查任务（与 Arduino on_ready → auto_update 一致）
// 在独立任务中执行，避免阻塞 WebSocket 事件处理
static void ota_check_task(void *arg)
{
    // 等待 WebSocket 连接稳定，让初始握手和配置同步完成
    vTaskDelay(pdMS_TO_TICKS(2000));

    if (s_server_http_base[0] == '\0') {
        ESP_LOGW(TAG, "服务器 HTTP 地址为空，跳过 OTA 检查");
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "开始检查 OTA 升级: %s", s_server_http_base);
    esp_err_t ret = ota_check_and_update(s_server_http_base);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA 检查完成，无需更新或更新成功");
    } else {
        ESP_LOGW(TAG, "OTA 检查失败: %s，将继续使用当前版本", esp_err_to_name(ret));
    }

    vTaskDelete(NULL);
}

static void websocket_event_handler(void *handler_args, esp_event_base_t base,
                                    int32_t event_id, void *event_data)
{
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        ESP_LOGI(TAG, "EVENT_CONNECTED");
        // 重连后服务端会重新下发缓存帧，清掉旧的唤醒提示音缓存
        websocket_cache_clear();
        // 连接成功，重置断线自愈计数
        s_disconnect_count = 0;
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_is_connected = true;
        s_last_keepalive_ms = 0;
        s_wakeup_pending = false;   // 连接恢复，清除唤醒响应超时检测
        // 与 Arduino 一致：连接成功时清除会话状态
        s_current_session_id[0] = '\0';
        s_current_tts_task_id[0] = '\0';
        s_audio_playing = false;
        s_audio_over_sent = false;
        s_drain_action = DRAIN_ACTION_NONE;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        display_show_status("服务连接成功");
        // 上报板型信息（服务端可根据板型能力下发不同指令，如无屏板型不下发表情命令）
        {
            char info_msg[320];
            snprintf(info_msg, sizeof(info_msg), "{\"type\":\"device_info\",\"data\":%s}", board_get_info_json());
            websocket_send_text(info_msg);
        }
        if (s_is_official) {
            websocket_send_text("{\"type\":\"play_audio_ws_conntceed\"}");
            // 启动流控上报定时器（官方服务器需要周期性 client_available_audio）
            if (s_flow_ctrl_timer == NULL) {
                esp_timer_create_args_t args = {
                    .callback = flow_ctrl_timer_cb,
                    .name = "flow_ctrl"
                };
                esp_err_t tr = esp_timer_create(&args, &s_flow_ctrl_timer);
                if (tr != ESP_OK) {
                    ESP_LOGE(TAG, "Failed to create flow_ctrl timer: %s", esp_err_to_name(tr));
                    break;
                }
            }
            esp_timer_start_periodic(s_flow_ctrl_timer, 1000000);  // 每 1s（Arduino 一致）
        }
        // 首次连接时检查 OTA 升级（与 Arduino on_ready → auto_update 一致）
        if (!s_ota_checked) {
            s_ota_checked = true;
            xTaskCreate(ota_check_task, "ota_check", 8192, NULL, 3, NULL);
        }
        break;

    case WEBSOCKET_EVENT_DISCONNECTED:
        ESP_LOGI(TAG, "EVENT_DISCONNECTED");
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_is_connected = false;
        s_music_streaming = false;
        websocket_cache_clear();
        // 与 Arduino 一致：断开时清除会话状态、停止麦克风和扬声器
        s_current_session_id[0] = '\0';
        s_current_tts_task_id[0] = '\0';
        s_audio_playing = false;
        s_audio_over_sent = false;
        s_drain_action = DRAIN_ACTION_NONE;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);

        // ===== 断线自愈 =====
        // 连续断开升级处理：检查 WiFi -> 强制重建 WiFi -> 整机重启
        s_disconnect_count++;
        ESP_LOGW(TAG, "EVENT_DISCONNECTED (连续第 %d 次)", s_disconnect_count);
        if (s_disconnect_count >= WS_SELF_HEAL_RESTART_THRESHOLD) {
            ESP_LOGE(TAG, "持续断线 %d 次仍无法恢复，整机重启", s_disconnect_count);
            vTaskDelay(pdMS_TO_TICKS(200));
            esp_restart();
        } else if (s_disconnect_count >= WS_SELF_HEAL_FORCE_WIFI_THRESHOLD) {
            // WiFi 状态位可能陈旧（静默掉线时无 STA_DISCONNECTED 事件），无条件强制重建
            ESP_LOGW(TAG, "持续断线，强制重建 WiFi");
            wifi_force_reconnect();
        } else if (s_disconnect_count >= WS_SELF_HEAL_CHECK_WIFI_THRESHOLD) {
            // 检查 WiFi 真实连接状态，掉线则主动重连（esp_websocket_client 自动重连救不了 WiFi）
            if (!wifi_is_connected()) {
                ESP_LOGW(TAG, "检测到 WiFi 已掉线，触发 WiFi 重连");
                wifi_force_reconnect();
            }
        }
        // =====================

        if (s_drain_check_timer) {
            esp_timer_stop(s_drain_check_timer);
        }
        if (s_flow_ctrl_timer) {
            esp_timer_stop(s_flow_ctrl_timer);
        }
        audio_mic_stop();
        audio_spk_stop();
        // 恢复语音唤醒，断线期间仍可检测唤醒词
        wakeup_resume();
        power_manager_set_active(false);  // 回待机省电（WiFi modem sleep）
        display_show_status("服务断开，自动重连中...");
        break;

    case WEBSOCKET_EVENT_CLOSED:
        ESP_LOGI(TAG, "EVENT_CLOSED, disconnected=%d", s_is_connected);
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_is_connected = false;
        bool need_reconnect = !s_reconnect_pending;
        s_reconnect_pending = true;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        display_show_status("服务已关闭");
        // 服务端主动关闭时不会触发自动重连，需手动 start
        // 添加标志位防止重复创建重连任务
        if (s_client && need_reconnect) {
            xTaskCreate(reconnect_task, "ws_recon", 2048, NULL, 3, NULL);
        }
        break;

    case WEBSOCKET_EVENT_ERROR:
        ESP_LOGW(TAG, "EVENT_ERROR");
        break;

    case WEBSOCKET_EVENT_BEGIN:
        ESP_LOGD(TAG, "EVENT_BEGIN");
        break;

    case WEBSOCKET_EVENT_FINISH:
        ESP_LOGD(TAG, "EVENT_FINISH");
        break;

    case WEBSOCKET_EVENT_DATA:
        ESP_LOGD(TAG, "WS_DATA: op=0x%02x pay=%d off=%d dlen=%d first=0x%02x",
                 data->op_code, (int)data->payload_len, (int)data->payload_offset,
                 (int)data->data_len,
                 data->data_len > 0 ? (unsigned char)data->data_ptr[0] : 0);

        // keepalive 心跳不视为会话活动：不清除唤醒超时、不刷新会话看门狗。
        // 否则服务端只发心跳不回复唤醒消息时，唤醒检测永久卡死。
        bool is_keepalive = (data->op_code == 0x01 &&
                             data->data_len == 36 &&
                             memcmp(data->data_ptr, "{\"type\":\"keepalive\"", 19) == 0);

        if (!is_keepalive) {
            // 收到服务端数据 = 会话有活动，刷新看门狗计时（避免长对话被误判超时）
            session_watchdog_refresh();
            // 收到服务端任何数据 = 连接活跃，清除唤醒响应超时检测
            s_wakeup_pending = false;
        }

        if (data->op_code == 0x01) {  // 文本消息
            // keepalive 消息用 LOGV 避免刷屏，其他文本消息用 LOGD
            if (is_keepalive) {
                ESP_LOGV(TAG, "收到文本消息: %.*s", data->data_len, data->data_ptr);
            } else {
                ESP_LOGD(TAG, "收到文本消息: %.*s", data->data_len, data->data_ptr);
            }

            // 处理纯文本 "session_end" 消息
            if (data->data_len == 11 && memcmp(data->data_ptr, "session_end", 11) == 0) {
                ESP_LOGI(TAG, "收到 session_end 纯文本");
                // 与 Arduino 一致：如果 drain 动作已在等待，跳过
                if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                if (s_drain_action != DRAIN_ACTION_NONE) {
                    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                    return;
                }
                // 与 Arduino 一致：清除 session_id、tts_task_id、停止麦克风
                s_current_session_id[0] = '\0';
                s_current_tts_task_id[0] = '\0';
                s_audio_playing = false;
                if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                audio_mic_stop();
                if (s_drain_check_timer) {
                    esp_timer_stop(s_drain_check_timer);
                }
                display_show_status("等待唤醒...");
                display_show_emotion("休息中");
                display_show_text("");
                audio_spk_stop();
                wakeup_resume();
                power_manager_set_active(false);  // 回待机省电（WiFi modem sleep）
                return;
            }

            // 解析JSON消息
            cJSON *json = cJSON_ParseWithLength(data->data_ptr, data->data_len);
            if (json) {
                cJSON *type = cJSON_GetObjectItem(json, "type");
                if (type && cJSON_IsString(type)) {
                    // 处理 play_audio_ws_conntceed - 服务端连接确认
                    if (strcmp(type->valuestring, "play_audio_ws_conntceed") == 0) {
                        ESP_LOGI(TAG, "收到服务端连接确认，回复确认消息");
                        websocket_send_text("{\"type\":\"play_audio_ws_conntceed\"}");
                    }
                    // 处理 stc_time - 服务端时间戳：设置系统时间（屏保时钟用），回复 cts_time
                    else if (strcmp(type->valuestring, "stc_time") == 0) {
                        cJSON *stc_time = cJSON_GetObjectItem(json, "stc_time");
                        if (stc_time && cJSON_IsString(stc_time)) {
                            // 服务器秒级时间戳 → 设置系统时间（屏保/日志时间戳使用）
                            long ts = atol(stc_time->valuestring);
                            if (ts > 1000000000) {  // 合理范围（2001 年之后）
                                struct timeval tv = { .tv_sec = ts, .tv_usec = 0 };
                                settimeofday(&tv, NULL);
                                // 时区固定北京时间（CST-8），屏保显示本地时间
                                setenv("TZ", "CST-8", 1);
                                tzset();
                                // 打印可读时间便于排查（时间不对时先看这里：
                                // 若显示 2009 年说明服务器 stc_time 仍是旧测试值，需重启服务器）
                                struct tm tmv;
                                time_t ts_sec = (time_t)ts;
                                localtime_r(&ts_sec, &tmv);
                                char tbuf[32];
                                strftime(tbuf, sizeof(tbuf), "%Y-%m-%d %H:%M:%S", &tmv);
                                ESP_LOGI(TAG, "系统时间已同步: %ld (%s)", ts, tbuf);
                            }
                            char msg[64];
                            snprintf(msg, sizeof(msg), "{\"type\":\"cts_time\",\"stc_time\":\"%s\"}", stc_time->valuestring);
                            ESP_LOGD(TAG, "回复时间戳: %s", msg);
                            websocket_send_text(msg);
                        }
                    }
                    // 处理会话状态
                    else if (strcmp(type->valuestring, "session_status") == 0) {
                        cJSON *status = cJSON_GetObjectItem(json, "status");
                        if (status && cJSON_IsString(status)) {
                            if (strcmp(status->valuestring, "iat_start") == 0) {
                                ESP_LOGI(TAG, "ASR 开始，启动麦克风采集");
                                // 停止 drain check timer
                                if (s_drain_check_timer) {
                                    esp_timer_stop(s_drain_check_timer);
                                }
                                // Arduino iat_start: wait_mp3_player_done()
                                // 停止任何正在播放的音频
                                audio_spk_stop();
                                // 清空 LLM 文本缓冲区，新对话开始
                                callback_reset_llm_text();
                                // 确保 WakeNet 已暂停（应已在 handle_wakeup 中暂停）
                                if (!wakeup_is_paused()) {
                                    ESP_LOGW(TAG, "收到 iat_start 但 WakeNet 未暂停，先暂停 WakeNet");
                                    wakeup_pause();
                                }
                                display_show_status("聆听中");
                                display_show_emotion("聆听中");
                                display_show_text("");  // 新对话开始，清除上轮字幕
                                // Arduino: esp_ai_start_send_audio = true
                                // 与 Arduino 一致：iat_start 时启动麦克风采集发送
                                // Arduino 在 iat_start 设 esp_ai_start_send_audio = true，
                                // loop() 中开始 mic_to_ws_copier.copyBytes() 发送数据
                                // IDF 对应：audio_mic_start() 创建采集任务开始发送
                                audio_mic_start();
                            } else if (strcmp(status->valuestring, "iat_end") == 0) {
                                ESP_LOGI(TAG, "ASR 结束，关闭麦克风");
                                // 与 Arduino 一致：iat_end 不切换表情 GIF（保持"聆听中"）
                                audio_mic_stop();
                                // 恢复 WakeNet 以支持 TTS 播放中语音打断：
                                // Arduino 在 iat_end 恢复 WakeNet 支持打断，但 C3 无 PSRAM 时
                                // WakeNet 激活缓冲 ~33KB + MP3 解码器 45KB 无法同时容纳。
                                // 有 PSRAM 时无此限制，无条件恢复打断能力。
                                // 注意：wakeup_resume() 会释放 I2S 互斥锁，mic_task 不使用该锁
                                // 所以 ASR 采集不受影响。
#if !defined(CONFIG_IDF_TARGET_ESP32C3)
                                wakeup_resume();
                                ESP_LOGI(TAG, "TTS 阶段已恢复语音唤醒，支持打断");
#else
                                // C3 无 PSRAM：WakeNet 激活缓冲 ~33KB + MP3 解码器 45KB
                                // 无法同时容纳，延迟到会话真正结束（session_end / "03"/断线）
                                // 由 wakeup_resume() 恢复；TTS 播放期间仍可用板载按钮打断。
                                ESP_LOGI(TAG, "C3 内存限制，TTS 阶段不恢复语音唤醒（按钮打断可用）");
#endif
                            } else if (strcmp(status->valuestring, "tts_chunk_start") == 0) {
                                ESP_LOGI(TAG, "TTS 音频开始");
                                if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                                s_audio_playing = true;
                                if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                                if (s_tts_state_mutex) {
                                    xSemaphoreTake(s_tts_state_mutex, portMAX_DELAY);
                                    s_tts_is_playing = true;
                                    s_tts_start_time_ms = esp_timer_get_time() / 1000;  // 字幕 TTS 节拍同步起点
                                    xSemaphoreGive(s_tts_state_mutex);
                                } else {
                                    s_tts_is_playing = true;
                                    s_tts_start_time_ms = esp_timer_get_time() / 1000;
                                }
                                display_show_status("说话中");
                                display_show_emotion("说话中");
                            } else if (strcmp(status->valuestring, "tts_chunk_end") == 0) {
                                ESP_LOGI(TAG, "TTS 音频块结束");
                            } else if (strcmp(status->valuestring, "tts_real_end") == 0) {
                                ESP_LOGI(TAG, "TTS 真实结束");
                                if (s_tts_state_mutex) {
                                    xSemaphoreTake(s_tts_state_mutex, portMAX_DELAY);
                                    s_tts_is_playing = false;
                                    xSemaphoreGive(s_tts_state_mutex);
                                } else {
                                    s_tts_is_playing = false;
                                }
                                /* 不清空 LLM 文本：字幕应在 TTS 播放期间保持可见，
                                 * 由后续 session_end 或新对话 iat_start 清除 */
                            } else if (strcmp(status->valuestring, "session_end") == 0) {
                                ESP_LOGI(TAG, "会话结束");
                                // 与 Arduino 一致：如果 drain 动作已在等待，跳过
                                if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                                drain_action_t cur_drain = s_drain_action;
                                if (cur_drain == DRAIN_ACTION_SESSION_END) {
                                    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                                    ESP_LOGI(TAG, "二进制 03 已处理，跳过 JSON session_end");
                                    return;
                                }
                                if (cur_drain == DRAIN_ACTION_CONTINUE) {
                                    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                                    ESP_LOGI(TAG, "连续对话中，忽略 session_end");
                                    return;
                                }
                                // 与 Arduino 一致：清除 session_id、tts_task_id、停止麦克风
                                s_current_session_id[0] = '\0';
                                s_current_tts_task_id[0] = '\0';
                                s_audio_playing = false;
                                if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                                audio_mic_stop();
                                if (s_drain_check_timer) {
                                    esp_timer_stop(s_drain_check_timer);
                                }
                                display_show_status("等待唤醒...");
                                display_show_emotion("休息中");
                                display_show_text("");
                                audio_spk_stop();
                                wakeup_resume();
                                power_manager_set_active(false);  // 回待机省电（WiFi modem sleep）
                            }
                        }
                    }
                    // 处理情绪
                    else if (strcmp(type->valuestring, "emotion") == 0) {
                        cJSON *emotion_data = cJSON_GetObjectItem(json, "data");
                        if (emotion_data && cJSON_IsString(emotion_data)) {
                            ESP_LOGI(TAG, "收到情绪: %s", emotion_data->valuestring);
                            display_show_emotion(emotion_data->valuestring);
                        }
                    }
                    // 处理指令（分发到 commands/ 目录中注册的处理函数）
                    else if (strcmp(type->valuestring, "instruct") == 0) {
                        cJSON *command_id = cJSON_GetObjectItem(json, "command_id");

                        if (command_id && cJSON_IsString(command_id)) {
                            ESP_LOGI(TAG, "收到指令: %s", command_id->valuestring);

                            // 分发到指令注册系统（commands/ 目录中的处理函数）
                            esp_err_t cmd_ret = commands_dispatch("instruct", command_id->valuestring, json);
                            if (cmd_ret == ESP_ERR_NOT_FOUND) {
                                ESP_LOGW(TAG, "未注册的指令: %s（在 commands/ 目录中添加即可）", command_id->valuestring);
                            }
                        }
                        // 发送应答
                        websocket_send_text("{\"type\":\"instruct_ack\"}");
                    }
                    // 处理硬件 IO 控制（移植自 Arduino hardware-fns）
                    else if (strcmp(type->valuestring, "hardware-fns") == 0) {
                        hardware_io_handle_fns(json);
                    }
                    // 处理音频播放
                    else if (strcmp(type->valuestring, "play_audio") == 0) {
                        // 与 Arduino 一致：麦克风正在录音时，忽略 play_audio（esp_ai_start_send_audio 检查）
                        if (audio_mic_is_running()) {
                            ESP_LOGW(TAG, "麦克风正在录音，忽略 play_audio");
                            if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                            s_current_tts_task_id[0] = '\0';
                            if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                            cJSON_Delete(json);
                            return;
                        }
                        cJSON *tts_task_id = cJSON_GetObjectItem(json, "tts_task_id");
                        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                        if (tts_task_id && cJSON_IsString(tts_task_id)) {
                            strncpy(s_current_tts_task_id, tts_task_id->valuestring, sizeof(s_current_tts_task_id) - 1);
                            s_current_tts_task_id[sizeof(s_current_tts_task_id) - 1] = '\0';  // 显式 null 终止
                            ESP_LOGI(TAG, "开始播放音频: %s", s_current_tts_task_id);
                            // 官方服务端用 play_audio + tts_task_id="play_music" 触发音乐推流
                            // （整首音乐通过 WS 二进制帧下发，与 Arduino 客户端 webSocketEvent 行为一致）
                            s_music_streaming = (strcmp(s_current_tts_task_id, "play_music") == 0);
                        } else {
                            s_music_streaming = false;
                        }
                        s_audio_playing = true;
                        s_audio_over_sent = false;  // 新音频开始，重置发送标志
                        s_drain_action = DRAIN_ACTION_NONE;  // 新音频开始，清除 drain 动作
                        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                        s_id3_skip_size = 0;
                        if (s_music_streaming) {
                            // 音乐推流：新的音乐流，强制重新开始播放（确保 spk_ing=true，
                            // 后续大流量音乐帧快速写入不被 pending 缓冲堆积丢弃）
                            ESP_LOGI(TAG, "音乐推流模式开始");
                            audio_spk_play();
                        } else {
                            // 服务端会将一句 TTS 拆成多个 play_audio 分段流式下发
                            // (长文本时 on_llm_cb/play_audio/tts_chunk_start 反复出现)。
                            // 正在播放时新 play_audio 视为分段：不 reset 播放缓冲/解码器，
                            // 否则每段开头都重建解码器+重配I2S，导致"前几个字丢失+卡顿"。
                            // 未在播放时(新音频流)才调 audio_spk_play() 重新开始。
                            if (audio_spk_is_playing()) {
                                ESP_LOGI(TAG, "音频播放中，play_audio 视为分段，不重置播放器");
                            } else {
                                audio_spk_play();
                            }
                        }
                    }
                    // 处理会话开始
                    else if (strcmp(type->valuestring, "session_start") == 0) {
                        cJSON *session_id = cJSON_GetObjectItem(json, "session_id");
                        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                        if (session_id && cJSON_IsString(session_id)) {
                            strncpy(s_current_session_id, session_id->valuestring, sizeof(s_current_session_id) - 1);
                            s_current_session_id[sizeof(s_current_session_id) - 1] = '\0';  // 显式 null 终止
                            ESP_LOGI(TAG, "会话开始: %s", s_current_session_id);
                        }
                        // 与 Arduino 一致：重置喇叭状态，准备接收 TTS
                        s_audio_playing = false;
                        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                        // 不 wakeup_pause：Arduino 只在 iat_start 时才暂停
                    }
                    // 处理会话停止（Arduino 的 session_stop）
                    else if (strcmp(type->valuestring, "session_stop") == 0) {
                        cJSON *sid = cJSON_GetObjectItem(json, "session_id");
                        // 读取 s_current_session_id 需在锁内
                        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                        char cur_sid[sizeof(s_current_session_id)];
                        strlcpy(cur_sid, s_current_session_id, sizeof(cur_sid));
                        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                        const char *stop_sid = (sid && cJSON_IsString(sid)) ? sid->valuestring : cur_sid;
                        cJSON *data_field = cJSON_GetObjectItem(json, "data");
                        const char *stop_data = (data_field && cJSON_IsString(data_field)) ? data_field->valuestring : "";
                        ESP_LOGI(TAG, "会话停止: %s, data=%s", stop_sid, stop_data);
                        // 与 Arduino 一致：回复 session_stop_ack
                        char ack_buf[128];
                        snprintf(ack_buf, sizeof(ack_buf),
                                 "{\"type\":\"session_stop_ack\",\"session_id\":\"%s\"}", stop_sid);
                        websocket_send_text(ack_buf);
                        // 与 Arduino 一致：麦克风正在录音时，清除 tts_task_id 并返回
                        if (audio_mic_is_running()) {
                            if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                            s_current_tts_task_id[0] = '\0';
                            if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                            cJSON_Delete(json);
                            return;
                        }
                        // 与 Arduino 一致：清除 session_id
                        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                        s_current_session_id[0] = '\0';
                        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                        // 与 Arduino 一致：data == "1" 时停止 ASR 和扬声器
                        if (strcmp(stop_data, "1") == 0) {
                            audio_mic_stop();
                            audio_spk_stop();
                        }
                    }
                    // 处理心跳
                    else if (strcmp(type->valuestring, "keepalive") == 0) {
                        // 更新 keepalive 时间戳
                        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
                        s_last_keepalive_ms = esp_timer_get_time() / 1000;
                        bool no_drain = (s_drain_action == DRAIN_ACTION_NONE);
                        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
                        // 回复pong
                        websocket_send_text("{\"type\":\"pong\"}");
                        // 检查播放完成：仅在无 drain action 时检查
                        // （02/03 由 drain_check_timer_cb 处理，避免 consume drain_done flag）
                        if (no_drain && audio_spk_check_drain_done()) {
                            send_audio_over();
                        }
                    }
                    // 处理 pong
                    else if (strcmp(type->valuestring, "pong") == 0) {
                        // 忽略
                    }
                }
                cJSON_Delete(json);
            }
        } else if (data->op_code == 0x02) {  // 二进制消息 - 音频数据
            ESP_LOGV(TAG, "收到二进制帧: op_code=0x%02x, payload_len=%d, offset=%d, data_len=%d",
                     data->op_code, (int)data->payload_len, (int)data->payload_offset, (int)data->data_len);
            // 参考原版: 直接处理完整的二进制帧
            // 原版代码: memcpy(session_id_string, payload, 4); memcpy(session_status_string, payload + 4, 2);
            //           audioData = payload + 6; audioLength = length - 6;

            handle_audio_binary_event(data);
        }
        break;

    default:
        break;
    }
}

// ==================== 官方 API 服务器查询（Arduino get_server_config）====================
// 当 ext1(api_key) 存在但 ext4/ext5/ext6 为空时，向官方平台查询服务节点地址
// 接口: http://api.espai.fun/sdk/get_server_info_by_api_key?api_key=xxx
// 返回: {"success":true,"data":{"ip":"...","port":...,"protocol":"...","path":"..."}}
// 成功时填充 server_url（如 "ws://node.espai.fun:80"），返回 ESP_OK
// 失败时使用默认地址，返回 ESP_FAIL
static esp_err_t query_official_server(const char *api_key, char *server_url, size_t url_size)
{
    if (api_key == NULL || api_key[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }

    char query_url[256];
    snprintf(query_url, sizeof(query_url),
             "http://api.espai.fun/sdk/get_server_info_by_api_key?api_key=%s", api_key);
    ESP_LOGI(TAG, "查询官方服务器: (API Key 已隐藏)");

    esp_http_client_config_t http_cfg = {
        .url = query_url,
        .timeout_ms = 10000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
    if (!client) {
        ESP_LOGE(TAG, "HTTP client init failed");
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP open failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    int content_length = esp_http_client_fetch_headers(client);
    if (content_length <= 0) {
        ESP_LOGW(TAG, "HTTP response empty");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    // 上限检查：响应体不应超过 64KB，防止异常大响应耗尽内存
    if (content_length > 64 * 1024) {
        ESP_LOGE(TAG, "HTTP response too large: %d bytes (max 64KB)", content_length);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_FAIL;
    }

    char *buf = malloc(content_length + 1);
    if (!buf) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return ESP_ERR_NO_MEM;
    }

    int read_len = esp_http_client_read_response(client, buf, content_length);
    buf[read_len > 0 ? read_len : 0] = '\0';
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    ESP_LOGD(TAG, "官方服务器响应: %s", buf);

    // 解析 JSON
    cJSON *root = cJSON_Parse(buf);
    free(buf);
    if (!root) {
        ESP_LOGW(TAG, "JSON parse failed");
        return ESP_FAIL;
    }

    cJSON *success = cJSON_GetObjectItem(root, "success");
    if (!success || !cJSON_IsTrue(success)) {
        ESP_LOGW(TAG, "API query returned success=false");
        cJSON_Delete(root);
        return ESP_FAIL;
    }

    cJSON *data = cJSON_GetObjectItem(root, "data");
    if (!data) {
        ESP_LOGW(TAG, "No data in response");
        cJSON_Delete(root);
        return ESP_FAIL;
    }

    cJSON *ip = cJSON_GetObjectItem(data, "ip");
    cJSON *port = cJSON_GetObjectItem(data, "port");
    cJSON *protocol = cJSON_GetObjectItem(data, "protocol");

    const char *ip_str = (ip && cJSON_IsString(ip)) ? ip->valuestring : "node.espai.fun";

    /* 去除 ip 尾部可能带的 / (如 "node.espai2.fun/") */
    char ip_clean[128];
    strlcpy(ip_clean, ip_str, sizeof(ip_clean));
    size_t clean_len = strlen(ip_clean);
    if (clean_len > 0 && ip_clean[clean_len - 1] == '/') {
        ip_clean[clean_len - 1] = '\0';
    }

    /* 官方服务器统一使用 ws:// 无 TLS（同 Arduino 行为），
       避免 node.espai2.fun 证书不在 ESP-IDF CA bundle 中的验证失败问题。
       端口统一用 80（Arduino 使用 node.espai.fun:80 无 TLS），
       如果返回的是 443 端口也强制降级为 80。 */
    snprintf(server_url, url_size, "ws://%s:80", ip_clean);

    ESP_LOGI(TAG, "官方服务器地址: %s", server_url);
    cJSON_Delete(root);
    return ESP_OK;
}

// ==================== 设备注册（Arduino on_bind_device）====================
// 首次连接官方服务器前，向平台注册设备。
// 接口: HTTP POST http://api.espai.fun/devices/add
// 参数: {version, device_id, api_key, wifi_ssid, wifi_pwd}
// 已注册过的设备(api_key 不变)会跳过，不会重复绑定
static esp_err_t register_device(const char *api_key, const char *device_id)
{
    // 从 NVS 获取 wifi 信息
    char wifi_ssid[64] = {0}, wifi_pwd[64] = {0};
    {
        nvs_handle_t h;
        if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
            size_t l = sizeof(wifi_ssid);
            nvs_get_str(h, "wifi_name", wifi_ssid, &l);
            l = sizeof(wifi_pwd);
            nvs_get_str(h, "wifi_pwd", wifi_pwd, &l);
            nvs_close(h);
        }
    }

    char post_url[128];
    snprintf(post_url, sizeof(post_url), "http://api.espai.fun/devices/add");
    ESP_LOGI(TAG, "注册设备: %s", post_url);

    // 构造 JSON body
    cJSON *body = cJSON_CreateObject();
    cJSON_AddStringToObject(body, "version", FIRMWARE_VERSION);
    cJSON_AddStringToObject(body, "bin_id", board_get_config()->bin_id);
    cJSON_AddStringToObject(body, "device_id", device_id);
    cJSON_AddStringToObject(body, "api_key", api_key);
    cJSON_AddStringToObject(body, "wifi_ssid", wifi_ssid);
    cJSON_AddStringToObject(body, "wifi_pwd", wifi_pwd);
    char *body_str = cJSON_PrintUnformatted(body);
    cJSON_Delete(body);
    if (!body_str) {
        ESP_LOGE(TAG, "cJSON_PrintUnformatted failed (out of memory)");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "注册请求: (已隐藏敏感信息)");

    esp_http_client_config_t http_cfg = {
        .url = post_url,
        .method = HTTP_METHOD_POST,
        .timeout_ms = 15000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);
    if (!client) {
        ESP_LOGE(TAG, "HTTP client init failed");
        free(body_str);
        return ESP_FAIL;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");

    // 手动 open/write/fetch_headers/read 流程（与 query_official_server 一致）
    esp_err_t err = esp_http_client_open(client, strlen(body_str));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "HTTP open failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        free(body_str);
        return ESP_FAIL;
    }

    int wlen = esp_http_client_write(client, body_str, strlen(body_str));
    if (wlen < 0) {
        ESP_LOGW(TAG, "HTTP write failed");
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        free(body_str);
        return ESP_FAIL;
    }

    int content_length = esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "注册响应: HTTP %d, content_length=%d", status, content_length);

    if (content_length > 0) {
        char *resp_buf = malloc(content_length + 1);
        if (resp_buf) {
            int rlen = esp_http_client_read_response(client, resp_buf, content_length);
            resp_buf[rlen > 0 ? rlen : 0] = '\0';
            ESP_LOGI(TAG, "注册响应 body: %s", resp_buf);
            free(resp_buf);
        }
    } else {
        ESP_LOGI(TAG, "注册响应 body: (empty)");
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    free(body_str);

    // 检查 HTTP 状态码，非 2xx 视为失败
    if (status < 200 || status >= 300) {
        ESP_LOGE(TAG, "设备注册失败: HTTP %d", status);
        return ESP_FAIL;
    }

    return ESP_OK;
}

// 板型默认服务器：official_service 板（如 1.54 寸 LCD 官方板）默认连 ESP-AI 官方节点，
// 其余板型保持连本地默认地址
static const char *default_server_url(void)
{
    const board_config_t *bcfg = board_get_config();
    if (bcfg && bcfg->official_service) {
        return SERVER_URL_OFFICIAL;
    }
    return SERVER_URL_DEFAULT;
}

esp_err_t websocket_init(void)
{
    ESP_LOGI(TAG, "初始化WebSocket...");

    // 获取设备MAC地址（DEVICE_ID 可能是 32 字符的 UUID，缓冲区需足够大）
    char device_mac[64];
    char ws_key_diy[128] = {0};  // 从 diyServerParams 提取的 key
    get_device_mac(device_mac, sizeof(device_mac));

    // 从 NVS 读取服务器配置（配网时保存）
    char server_url[128] = {0};
    char api_key_from_nvs[128] = {0};
    char ext1_val[128] = {0};

    nvs_handle_t nvs_handle;
    if (nvs_open("esp-ai-kv", NVS_READONLY, &nvs_handle) == ESP_OK) {
        // 读取 ext1 (api_key，开放平台配网时 App 通常存 ext1)
        size_t len = sizeof(ext1_val);
        nvs_get_str(nvs_handle, "ext1", ext1_val, &len);

        // 读取 api_key (独立字段，兼容旧配网 App 直接存 api_key 键)
        len = sizeof(api_key_from_nvs);
        if (nvs_get_str(nvs_handle, "api_key", api_key_from_nvs, &len) != ESP_OK) {
            strlcpy(api_key_from_nvs, API_KEY_DEFAULT, sizeof(api_key_from_nvs));
        }

        // 优先从 ext4/ext5/ext6 组合构建服务器地址
        char ext4[8] = {0}, ext5[64] = {0}, ext6[8] = {0};
        len = sizeof(ext4);
        bool has_ext4 = (nvs_get_str(nvs_handle, "ext4", ext4, &len) == ESP_OK);
        len = sizeof(ext5);
        bool has_ext5 = (nvs_get_str(nvs_handle, "ext5", ext5, &len) == ESP_OK);
        len = sizeof(ext6);
        bool has_ext6 = (nvs_get_str(nvs_handle, "ext6", ext6, &len) == ESP_OK);

        if (has_ext4 && has_ext5 && has_ext6) {
            // 自定义服务器: ext4(协议)+ext5(地址)+ext6(端口) → ws://addr:port
            snprintf(server_url, sizeof(server_url), "%s://%s:%s",
                     strcmp(ext4, "https") == 0 ? "wss" : "ws", ext5, ext6);
            ESP_LOGI(TAG, "使用自定义服务器: %s", server_url);
        } else {
            // 官方模式：ext1 或 api_key 任一有值即查询官方节点（与 Arduino get_server_config 一致）
            const char *query_key = ext1_val[0] ? ext1_val : api_key_from_nvs;
            if (query_key[0] != '\0') {
                ESP_LOGI(TAG, "检测到 API Key，查询官方服务器...");
                if (query_official_server(query_key, server_url, sizeof(server_url)) != ESP_OK) {
                    ESP_LOGW(TAG, "官方服务器查询失败，使用默认地址");
                    strlcpy(server_url, default_server_url(), sizeof(server_url));
                }
            } else {
                // 无任何配置，使用默认服务器地址（官方板默认连 node.espai.fun）
                strlcpy(server_url, default_server_url(), sizeof(server_url));
            }
        }

        // 读取 diyServerParams (自定义参数，可能包含 key=xxx)
        char diy_key[128] = {0};

        size_t len2 = sizeof(diy_key);
        esp_err_t diy_err = nvs_get_str(nvs_handle, "diyServerParams", diy_key, &len2);
        ESP_LOGD(TAG, "NVS diyServerParams: %d '%s'", diy_err, (diy_err == ESP_OK) ? diy_key : "(not found)");
        if (diy_err == ESP_OK) {
            char *kp = strstr(diy_key, "key=");
            if (kp) {
                kp += 4;
                char *end = strchr(kp, '&');
                if (end) *end = 0;
                strlcpy(ws_key_diy, kp, sizeof(ws_key_diy));
            }
        }

        nvs_close(nvs_handle);
    } else {
        // NVS 打开失败，使用默认值（官方板默认连 node.espai.fun）
        strlcpy(server_url, default_server_url(), sizeof(server_url));
        strlcpy(api_key_from_nvs, API_KEY_DEFAULT, sizeof(api_key_from_nvs));
    }

    ESP_LOGD(TAG, "服务器地址: %s", server_url);

    // 将 WebSocket URL 转换为 HTTP 基础 URL（用于 OTA 查询）
    if (strncmp(server_url, "wss://", 6) == 0) {
        snprintf(s_server_http_base, sizeof(s_server_http_base), "https://%s", server_url + 6);
    } else if (strncmp(server_url, "ws://", 5) == 0) {
        snprintf(s_server_http_base, sizeof(s_server_http_base), "http://%s", server_url + 5);
    } else {
        strlcpy(s_server_http_base, server_url, sizeof(s_server_http_base));
    }
    ESP_LOGD(TAG, "OTA HTTP 基础地址: %s", s_server_http_base);

    // key 优先级: ext1(APP填的APIKey) > diyServerParams(key=xxx) > api_key
    const char *ws_key = ext1_val[0] ? ext1_val : (ws_key_diy[0] ? ws_key_diy : api_key_from_nvs);

    // 判断是否为官方服务器（含有 node.espai 域名）
    bool is_official = (strstr(server_url, "node.espai") != NULL);
    s_is_official = is_official;
    char url[768];
    if (is_official) {
        // 连接官方服务器前注册设备（Arduino 的 on_bind_device 流程）
        ESP_LOGI(TAG, "官方模式，尝试注册设备...");
        register_device(ws_key, device_mac);

        // 获取音量 ext2
        char ext2_val[16] = {0};
        {
            nvs_handle_t h;
            if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
                size_t l = sizeof(ext2_val);
                nvs_get_str(h, "ext2", ext2_val, &l);
                nvs_close(h);
            }
        }

        // 官方服务器路径为 /，与 Arduino connect_ws.cpp 完全一致的参数
        // 注意：不要添加 spk_sample_rate/spk_channels/spk_format 等参数，
        // Arduino 官方客户端（esp-ai-client）不传这些参数，官方服务端按默认
        // MP3 下发；加 spk_* 参数可能导致官方服务端音频路径不一致（设备无声）
        snprintf(url, sizeof(url),
                 "%s/?v=%s&device_id=%s&api_key=%s&ext1=%s&ext2=%s"
                 "&AUDIO_BUFFER_SIZE=%d&bitrate=%d",
                 server_url, FIRMWARE_VERSION, device_mac, ws_key, ws_key, ext2_val,
                 SPK_STREAM_BUF_SIZE, 64);
    } else {
        // 自定义服务器：去掉 api_key，只传 mac 作为设备标识
        // 设备绑定时服务端会返回 bind_code，用户在 App 输入后完成绑定
        // has_display=0/1：上报屏幕能力，服务端据此对设备级插件做能力适配
        // （无屏设备自动隐藏 screen 等 requires=display 插件的工具）
        snprintf(url, sizeof(url),
                 "%s%s?mac=%s&v=%s&AUDIO_BUFFER_SIZE=%d"
                 "&spk_sample_rate=%d&spk_channels=%d&spk_format=mp3&spk_bitrate=%d"
                 "&has_display=%d",
                 server_url, SERVER_PATH,
                 device_mac, FIRMWARE_VERSION,
                 SPK_STREAM_BUF_SIZE, SPK_SAMPLE_RATE, AUDIO_CHANNELS, 64,
                 display_has_graphic() ? 1 : 0);
    }

    // 遮蔽 API Key
    char url_safe[768];
    strlcpy(url_safe, url, sizeof(url_safe));
    char *key_start = strstr(url_safe, "api_key=");
    if (key_start) {
        char *key_end = strchr(key_start + 8, '&');
        if (key_end) {
            memset(key_start + 8, '*', key_end - key_start - 8);
        } else {
            memset(key_start + 8, '*', strlen(key_start + 8));
        }
    }
    ESP_LOGI(TAG, "WebSocket URL: %s", url_safe);

    esp_websocket_client_config_t websocket_cfg = {
        .uri = url,
#ifdef CONFIG_IDF_TARGET_ESP32C3
        .buffer_size = 2048,       // C3 无 PSRAM：静态模式分配 2×buffer，降到 2KB 才能过初始化
        .task_stack = 6144,        // C3 收紧任务栈
#else
        .buffer_size = 16384,      // 16KB，防止 TTS 音频大二进制帧分片导致数据丢失
        .task_stack = 8192,        // 8192：WebSocket 握手 + HTTP 解析需要足够栈
#endif
        .disable_auto_reconnect = false,   // 使用库自带的自动重连
        .reconnect_timeout_ms = 3000,      // 断线后 3 秒重连
        .network_timeout_ms = 15000,       // 15秒网络超时（WiFi 网络延迟可能较大）
        .skip_cert_common_name_check = true,  // 跳过证书 CN 验证（开发阶段启用，生产环境建议改为 false）
        .crt_bundle_attach = esp_crt_bundle_attach,
    };

    if (s_ws_mutex == NULL) {
        s_ws_mutex = xSemaphoreCreateMutex();
    }

    s_client = esp_websocket_client_init(&websocket_cfg);
    if (s_client == NULL) {
        ESP_LOGE(TAG, "WebSocket初始化失败");
        return ESP_FAIL;
    }

    esp_websocket_register_events(s_client, WEBSOCKET_EVENT_ANY, websocket_event_handler, NULL);

    esp_err_t err = esp_websocket_client_start(s_client);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "WebSocket启动失败: %s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "WebSocket初始化完成");
    return ESP_OK;
}

esp_err_t websocket_send_text(const char *text)
{
    if (s_client == NULL || !s_is_connected) {
        ESP_LOGW(TAG, "WebSocket未连接");
        return ESP_ERR_INVALID_STATE;
    }

    int len = esp_websocket_client_send_text(s_client, text, strlen(text), pdMS_TO_TICKS(200));
    if (len < 0) {
        ESP_LOGE(TAG, "发送文本失败");
        return ESP_FAIL;
    }

    return ESP_OK;
}

esp_err_t websocket_send_text_nb(const char *text)
{
    if (s_client == NULL || !s_is_connected) {
        return ESP_ERR_INVALID_STATE;
    }

    int len = esp_websocket_client_send_text(s_client, text, strlen(text), pdMS_TO_TICKS(50));
    if (len < 0) {
        return ESP_FAIL;
    }

    return ESP_OK;
}

esp_err_t websocket_send_binary(const uint8_t *data, size_t len)
{
    if (s_client == NULL || !s_is_connected) {
        return ESP_ERR_INVALID_STATE;
    }

    // 超时必须短于 esp_websocket_client 的 PING 锁超时（WEBSOCKET_TX_LOCK_TIMEOUT_MS=2000ms）！
    // 否则 TCP 发送阻塞（服务器不消费数据导致 snd_buf 满）时，本函数会长时间持有
    // tx_lock，库内部任务发送 PING 拿不到锁 → "Could not lock ws-client ... for PING"
    // → PING 超时判定连接异常 → 整条连接被强制断开。
    // 实测：服务器 8 秒不读数据时，5 秒超时的 send_bin 饿死了 PING，导致 ASR 中段线。
    // 改为 1500ms：TCP 堵塞时主动放弃本次发送（mic_task 连续失败 3 次会停止采集），
    // PING 最多等 1500ms 即可拿到锁，连接保持存活，服务器恢复后 ASR 可重试。
    int sent = esp_websocket_client_send_bin(s_client, (const char *)data, len, pdMS_TO_TICKS(1500));
    if (sent >= 0) {
        return ESP_OK;
    }

    ESP_LOGW(TAG, "发送二进制数据失败 (sent=%d)", sent);
    return ESP_FAIL;
}

bool websocket_is_connected(void)
{
    return s_is_connected;
}

// 是否连接到官方服务器（node.espai*.fun）
// 流控上报语义区分用：官方服务端按"已缓冲字节数"理解 client_available_audio，
// 本地 esp-ai-server(自定义服务器)按"剩余空间"理解
bool websocket_is_official(void)
{
    return s_is_official;
}

// 是否处于音乐推流模式（play_audio + tts_task_id="play_music"）
// 音乐音频经 WS 大流量下发，audio_spk_write 需快速写入不阻塞 WebSocket 回调，
// 否则服务端后续文本指令(停止/切歌/音量等)会被音乐帧阻塞而延迟执行
bool websocket_is_music_streaming(void)
{
    return s_music_streaming;
}

// 获取服务器 HTTP 基础地址（用于表情下载等 HTTP 请求）
// 返回 ws/wss 转 http/https 后的地址，如 "http://192.168.31.176:8088"
const char *websocket_get_http_base(void)
{
    return s_server_http_base;
}

// 重置对话状态（唤醒/打断时调用，与 Arduino wakeUp 中 esp_ai_session_id = "" 一致）
void websocket_reset_conversation_state(void)
{
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    s_current_session_id[0] = '\0';
    s_current_tts_task_id[0] = '\0';
    s_audio_playing = false;
    s_audio_over_sent = false;
    s_drain_action = DRAIN_ACTION_NONE;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
    if (s_drain_check_timer) {
        esp_timer_stop(s_drain_check_timer);
    }
}

// keepalive 超时检测：如果超过 45 秒没收到 keepalive，主动断开
void websocket_check_keepalive(void)
{
    int64_t now_ms = esp_timer_get_time() / 1000;

    // 唤醒响应超时检测（必须放在连接状态判断之前：即使 s_is_connected 为 false，
    // 只要唤醒消息已发送且 10 秒无任何服务端数据，都判定连接异常并主动重连，
    // 否则半开连接下“无法唤醒”无法自愈）。
    // 10s 而非 6s：服务端唤醒音频 TTS 冷缓存合成（连接/合成超时上限）可能超过 6s，
    // 放宽可减少对正常但偏慢响应的误杀，超时后重连再试一次基本可恢复。
    if (s_wakeup_pending) {
        if (now_ms - s_wakeup_sent_ms > 10000) {
            ESP_LOGW(TAG, "唤醒消息 10 秒无响应，判定连接异常，主动重连");
            s_wakeup_pending = false;
            if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
            s_is_connected = false;
            s_audio_playing = false;
            if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
            display_show_status("连接异常，重连中...");
            websocket_force_reconnect();
            wakeup_resume();   // 恢复语音唤醒，等重连成功后再试
            power_manager_set_active(false);  // 回待机省电（WiFi modem sleep）
        }
    }

    if (!s_is_connected) return;

    // 用锁保护 s_last_keepalive_ms 的读取（int64_t 跨任务无锁访问不安全）
    if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    int64_t last_keepalive = s_last_keepalive_ms;
    if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);

    // 首次收到 keepalive 之前不检测（s_last_keepalive_ms == 0）
    if (last_keepalive == 0) return;

    int64_t elapsed = now_ms - last_keepalive;
    if (elapsed > 45000) {  // 45 秒超时（服务器 keepalive 间隔 30 秒，留 15 秒余量）
        ESP_LOGW(TAG, "Keepalive 超时: %lld 秒未收到心跳，主动断开", elapsed / 1000);
        if (s_ws_mutex) xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
        s_is_connected = false;
        s_audio_playing = false;
        if (s_ws_mutex) xSemaphoreGive(s_ws_mutex);
        display_show_status("心跳超时，重连中...");
        // 注意：不能用 esp_websocket_client_stop()，因为它不会触发 EVENT_DISCONNECTED
        // 直接 start 会先 stop 再 connect，触发完整重连流程
        if (s_client) {
            esp_websocket_client_start(s_client);
        }
    }
}

// 标记唤醒消息已发送，启动唤醒响应超时检测
void websocket_mark_wakeup_sent(void)
{
    s_wakeup_pending = true;
    s_wakeup_sent_ms = esp_timer_get_time() / 1000;
}

// 清除唤醒响应超时检测（收到服务端数据/连接事件时调用）
void websocket_clear_wakeup_pending(void)
{
    s_wakeup_pending = false;
}
