/**
 * network_audio.h - 网络音频播放（移植自 Arduino audio_player.cpp 的 playNetworkAudio）
 *
 * 通过 HTTP 流式下载 MP3 数据，喂入现有 audio_spk 解码播放管道。
 * 对应 Arduino 指令: play_music
 */
#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 播放网络音频（非阻塞，内部创建任务）
 * @param url MP3 音频 URL
 * @return ESP_OK 或错误码
 */
esp_err_t network_audio_play(const char *url);

/**
 * 停止网络音频播放
 */
esp_err_t network_audio_stop(void);

/**
 * 网络音频是否正在播放
 */
bool network_audio_is_playing(void);

/**
 * 设置自动续播标志（播放完一首歌后自动请求下一首随机歌曲）
 * @param enable true=启用自动续播, false=关闭
 */
void network_audio_set_auto_continue(bool enable);

/**
 * 查询自动续播是否启用
 */
bool network_audio_is_auto_continue(void);

#ifdef __cplusplus
}
#endif
