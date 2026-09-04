#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_err.h"

#include "boards/board_interface.h"
#include "boards/board_select.h"
#include "device_id.h"

#ifdef __cplusplus
extern "C" {
#endif

// ==================== WiFi 配置 ====================
// WiFi凭据通过配网流程保存到NVS，无需硬编码
// 连接失败后自动重连，直到成功为止，最大重试 WIFI_MAXIMUM_RETRY 次；
// 每次重试间隔 WIFI_RETRY_DELAY_MS，避免快速失败循环，给路由器/网络恢复时间
#define WIFI_MAXIMUM_RETRY  10
#define WIFI_RETRY_DELAY_MS 3000
// 等待连接结果的总超时：重试次数 × (重试间隔 + 单次连接最长耗时) + 余量。
// 必须大于重试总耗时，否则重试未耗尽就误入配网模式
#define WIFI_CONNECT_WAIT_MS (WIFI_MAXIMUM_RETRY * (WIFI_RETRY_DELAY_MS + 10000) + 10000)

// ==================== 服务器配置 ====================
// 服务器地址和API Key通过配网保存到NVS，无需硬编码
// 配网数据字段: ext1=api_key, ext4=协议(http/https), ext5=地址, ext6=端口
// 若NVS中无配置则使用以下默认值
#define SERVER_URL_DEFAULT  "ws://192.168.31.176:8088"
// ESP-AI 官方服务节点（official_service 板型在无配网配置时默认连接此地址）
#define SERVER_URL_OFFICIAL "ws://node.espai.fun:80"
#define API_KEY_DEFAULT     ""
#define SERVER_PATH         "/connect_espai_node"

// ==================== 音频参数 ====================
// 音频编解码器由 Kconfig → 音频编解码器 选择（与板型独立）：
//   CONFIG_AUDIO_CODEC_ES8311 → AUDIO_SCHEME_ES8311
//   CONFIG_AUDIO_CODEC_NONE   → I2S 直连（INMP441 + MAX98357）
#if defined(CONFIG_AUDIO_CODEC_ES8311) && !defined(AUDIO_SCHEME_ES8311)
#define AUDIO_SCHEME_ES8311 1
#endif

#define AUDIO_SAMPLE_RATE    24000
#define AUDIO_BITS_PER_SAMPLE 16
#define AUDIO_CHANNELS       1
#define AUDIO_BUFFER_SIZE    4096
// 音频流缓冲：S3（有 PSRAM）用 50KB 缓冲网络抖动；C3 无 PSRAM 收紧。
// 注意：C3 不能太小——服务器按 AUDIO_BUFFER_SIZE 切片下发，单帧可达 2.3~3.7KB，
// 实测 2KB 缓冲每帧都溢出丢数据（"缓冲区写入不足"）+ DMA 欠载（I2S 写入间隔 300ms），
// 播放严重卡顿。16KB ≈ 1 秒音频，足够吸收服务器突发 + 解码/重采样抖动；
// 内存账目（播放时 wakeup_pause 已释放 ~80KB，总可用 ~150KB）完全放得下。
#ifdef CONFIG_IDF_TARGET_ESP32C3
#define SPK_STREAM_BUF_SIZE  (1024 * 16)
#else
#define SPK_STREAM_BUF_SIZE  (1024 * 50)
#endif
// 扬声器采样率：ES8311 方案与 WakeNet 对齐用 16kHz（全 16k 链路，ES8311 ADC/DAC 同率），
// I2S 直连方案保持 24kHz
#if defined(AUDIO_SCHEME_ES8311)
#define SPK_SAMPLE_RATE      16000
#else
#define SPK_SAMPLE_RATE      24000
#endif

// ==================== 麦克风采样率（WakeNet 使用）====================
#define MIC_SAMPLE_RATE      16000

// ==================== 唤醒词配置 ====================
// 由 menuconfig 选择，需要烧录对应的 WakeNet 模型到 model 分区
#if CONFIG_WAKE_WORD_XIAOMING
    #define WAKE_WORD_NAME     "小明同学"
    #define WAKENET_MODEL_NAME "wn9_xiaomingtongxue_tts2"
#elif CONFIG_WAKE_WORD_NIHAOWEN
    #define WAKE_WORD_NAME     "你好问问"
    #define WAKENET_MODEL_NAME "wn9_nihaowenwen_tts2"
#elif CONFIG_WAKE_WORD_HIJESON
    #define WAKE_WORD_NAME     "嗨杰森"
    #define WAKENET_MODEL_NAME "wn9_hijeson_tts2"
#elif CONFIG_WAKE_WORD_NIHAOXIAOZHI
    #define WAKE_WORD_NAME     "你好小智"
    #define WAKENET_MODEL_NAME "wn9_nihaoxiaozhi_tts2"
#else
    #define WAKE_WORD_NAME     "小明同学"
    #define WAKENET_MODEL_NAME "wn9_xiaomingtongxue_tts2"
#endif

// ==================== 设备信息 ====================
#define DEVICE_TYPE    "hardware"
// 固件版本由顶层 CMakeLists.txt 从 git tag 动态生成（-DFIRMWARE_VERSION="..."）
// 如果 CMake 未传入版本号（如旧构建缓存），回退到默认值
#ifndef FIRMWARE_VERSION
#define FIRMWARE_VERSION "1.0.0"
#endif
// BIN_ID 已移至各板型的 board_config_t.bin_id 中，使用 board_get_config()->bin_id 获取
// 设备 ID 通过 device_id_get() 从 MAC 地址动态生成，参见 device_id.h

// ==================== 任务优先级 ====================
#define TASK_PRIO_WIFI       5
#define TASK_PRIO_WEBSOCKET  5
#define TASK_PRIO_AUDIO      6
#define TASK_PRIO_DISPLAY    4
#define TASK_PRIO_WAKEUP     7
// 播放任务优先级高于唤醒检测：wakenet_task 持续运行（每 30ms 一次 detect），
// 若与 spk_task 同级或更低，解码/写 I2S 会被抢占 → DMA 欠载 → 音乐卡顿。
// spk_task 大部分时间阻塞在 i2s_channel_write（DMA 满时让出 CPU），
// 唤醒检测在播放间隙仍能运行，不影响唤醒灵敏度。
#define TASK_PRIO_SPK        8

// ==================== 事件组定义 ====================
extern EventGroupHandle_t s_wifi_event_group;
extern EventGroupHandle_t s_wakeup_event_group;

#define WIFI_CONNECTED_BIT    BIT0
#define WIFI_FAIL_BIT         BIT1
#define WAKEUP_TRIGGERED_BIT  BIT2

// ==================== 函数声明 ====================

// 板级包
esp_err_t board_init(void);
const board_config_t *board_get_config(void);
const char *board_get_info_json(void);

// WiFi
esp_err_t wifi_init(void);
void wifi_set_power_save(bool enable);   // 待机省电开关（power_manager 调用）
bool wifi_is_connected(void);            // 真实连接状态（查 AP 记录，不依赖事件位）
void wifi_force_reconnect(void);         // 强制重建连接（websocket 断线自愈调用）

// 会话看门狗（main.c 实现，websocket.c 在收到服务端数据 / iat_start 时调用）
void session_watchdog_refresh(void);
void session_watchdog_start(void);

esp_err_t websocket_init(void);
esp_err_t websocket_send_text(const char *text);
esp_err_t websocket_send_text_nb(const char *text);
esp_err_t websocket_send_binary(const uint8_t *data, size_t len);
bool websocket_is_connected(void);
bool websocket_is_official(void);
bool websocket_is_music_streaming(void);
void websocket_cache_clear(void);
bool websocket_cache_get_tone(const uint8_t **data, size_t *len);
bool websocket_cache_get_greeting(const uint8_t **data, size_t *len);
// 释放 websocket_cache_get_* 获取的引用（get 之后、播放完成后必须调用，
// 持有期间服务端不会释放/覆盖缓存缓冲）
void websocket_cache_release(const uint8_t *data);
const char *websocket_get_http_base(void);
void websocket_reset_conversation_state(void);
void websocket_force_reconnect(void);
void websocket_mark_wakeup_sent(void);
void websocket_clear_wakeup_pending(void);
// 播放异常终止上报（audio.c 看门狗调用；websocket.c 组装完整格式，含
// session_id/tts_task_id，服务端才能正确配对会话）
void websocket_notify_playback_failed(void);
// 触发 OTA 检查 + 表情下载（幂等，仅首次生效；main.c 兜底与 WebSocket 事件共用）
void websocket_trigger_ota_check(void);

esp_err_t audio_init(void);
esp_err_t audio_mic_start(void);
esp_err_t audio_mic_stop(void);
bool audio_mic_is_running(void);
esp_err_t audio_spk_write(const uint8_t *data, size_t len);
void audio_spk_reset_decoder(void);
esp_err_t audio_spk_play(void);
bool audio_spk_is_playing(void);
esp_err_t audio_spk_stop(void);
esp_err_t audio_spk_hard_stop(void);
esp_err_t audio_spk_wait_drain(void);
bool audio_spk_check_drain_done(void);
size_t audio_spk_buffer_available(void);
// 音量控制（移植自 Arduino esp_ai.setVolume）
esp_err_t audio_set_volume(float volume);
float audio_get_volume(void);

esp_err_t display_init(void);
esp_err_t display_show_emotion(const char *emotion);
esp_err_t display_show_status(const char *status);
esp_err_t display_show_text(const char *text);
esp_err_t display_set_brightness(int percent);
esp_err_t display_clear(void);
bool display_has_graphic(void);

// OTA 进度条显示（圆形进度环 + 百分比文字）
esp_err_t display_show_ota_progress(int percent);
esp_err_t display_clear_ota_progress(void);

esp_err_t wakeup_init(void);
esp_err_t wakeup_start(void);
esp_err_t wakeup_stop(void);
void wakeup_pause(void);
void wakeup_resume(void);
void wakeup_clear_cooldown(void);   // 唤醒发送失败时清除冷却（网络恢复后立即可唤醒）
bool wakeup_is_paused(void);
void *wakeup_get_mic_handle(void);
void *wakeup_get_spk_handle(void);

// ==================== 硬件 IO 控制（移植自 Arduino hardware-fns）====================
#include "cJSON.h"
esp_err_t hardware_io_handle_fns(cJSON *json);
esp_err_t hardware_io_report_readings(void);

// ==================== 网络音频播放（移植自 Arduino playNetworkAudio）====================
esp_err_t network_audio_play(const char *url);
esp_err_t network_audio_stop(void);
bool network_audio_is_playing(void);

// ==================== 歌词/进度重置（音乐被打断时调用）====================
void lyric_commands_reset(void);

// ==================== 功耗管理（移植自 xiaozhi AudioService）====================
#include "power_manager.h"

#ifdef __cplusplus
}
#endif
