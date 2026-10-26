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
// 服务器地址通过配网保存到NVS，无需硬编码
// 配网数据字段: ext4=协议(http/https), ext5=地址, ext6=端口
// 若NVS中无配置则使用以下默认值
#define SERVER_URL_DEFAULT  "ws://192.168.31.176:8088"
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

// ==================== 字幕同步：扬声器链路延迟 ====================
// 字幕字级时间戳以"音频流位置"计（s_tts_start_time_ms = 首包音频到达时刻），
// 而声音实际出喇叭要晚：预缓冲（audio.c 播放前置 6720B）+ I2S TX DMA 管道深度。
// 显示字幕时按 play_pos - 本延迟 对齐可听位置。
// ES8311：预缓冲 6720B/(32B/ms)=210ms + TX DMA 12×240@16k=180ms → 390ms
// 直连：  预缓冲 6720B/(48B/ms)=140ms + TX DMA 480ms@24k       → 620ms
#if defined(AUDIO_SCHEME_ES8311)
#define SPK_PIPELINE_LATENCY_MS  390
#else
#define SPK_PIPELINE_LATENCY_MS  620
#endif

// ==================== 麦克风采样率（WakeNet 使用）====================
#define MIC_SAMPLE_RATE      16000

// ==================== 麦克风模拟增益（ES8311 REG16，离散档 0/6/12/18/24/30/36/42）====
// 【为什么从 36 降到 30】36dB 时自家 TTS 近场回声多次把 ADC 打满（峰值 32768），
// 削顶是非线性失真，线性 AEC 原理上消不掉：残余回声抬高出/参考比值 → 自打断；
// 互相关也被削平 → 滞后标定跟着抖。30dB 比 36 低 6dB（峰值减半），回声落回线性区；
// 又比曾因"唤醒不灵敏"被弃用的 24dB 高 6dB。若实测唤醒变差先回 36 并查喇叭-麦克风
// 距离，不要直接回调 AEC 判据。
#define MIC_GAIN_DB          30

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

// 唤醒灵敏度（wakeup.c 实现，config_commands 远程配置即时生效调用）
void wakeup_set_sensitivity(float threshold);

// 实时打断开关（wakeup.c 实现，config_commands 远程配置即时生效调用）
// false = TTS 播放中说话不打断，仅保留唤醒词打断（旧版行为）
void wakeup_set_barge_in_enabled(bool enabled);

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
// TX 队列代际号：每次 i2s_channel_enable 递增。i2s_channel_disable 会丢弃已排队
// 未发送的样本，AEC 参考的"写入序号=发出序号"账本随之作废，wakeup.c 据此重新起账。
uint32_t audio_spk_tx_epoch(void);
esp_err_t audio_spk_stop(void);
esp_err_t audio_spk_hard_stop(void);
esp_err_t audio_spk_wait_drain(void);
bool audio_spk_check_drain_done(void);
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
bool wakeup_take_barge_in(void);    // 取走并清零"本次唤醒来自 VAD 实时打断"标志
// 打断预缓冲：播放期间滚动保存 AEC 输出，VAD 实时打断开麦时先回灌这一段
// （判据攒满能量窗要 0.8 秒以上，不回灌就必然丢掉用户那句话的开头）。
// 只有打断会话能取，正常唤醒取到 0。见 wakeup.c 本节说明。
#define WAKEUP_PREROLL_MS 1500
#define WAKEUP_PREROLL_MAX_SAMPLES (16 * WAKEUP_PREROLL_MS)   // 16kHz 单声道
// 回灌起点 = 本段连续人声的第一帧，再往前推这么多毫秒。
// 旧实现固定回灌"最后 1.5 秒"：起点落在整段语音之前，把自家 TTS 尾音一起喂给 ASR
// （实测识别出"嗯那还可以…"），而用户话头被挤到缓冲末尾、开头一两个字被截掉。
#define WAKEUP_PREROLL_LEAD_MS 300
void wakeup_preroll_push(const int16_t *samples, int num);
void wakeup_preroll_clear(void);
void wakeup_preroll_mark_onset(int frames);   // 记录本段连续人声起点（frames = 已连续帧数）
int  wakeup_preroll_take(int16_t *dst, int max_samples);      // 返回取走的样本数
void *wakeup_get_mic_handle(void);
void *wakeup_get_spk_handle(void);
// AEC 参考信号（仅 S3 AFE 模式实现）：推送实际写入扬声器的 16kHz 单声道 PCM，
// 供 AEC 消除设备自身播放声，实现 TTS 播放中实时打断（其他平台为空实现）
void wakeup_spk_ref_push(const int16_t *samples, int num);
// TTS 打断窗口 I2S 互斥锁管理：ASR 结束后放锁（afe_task 可读 RX 检测打断），
// 下一轮 ASR 开始前重新拿锁（保护 mic_task 独占 RX）
void wakeup_i2s_mutex_release(void);
void wakeup_i2s_mutex_reacquire(void);

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
