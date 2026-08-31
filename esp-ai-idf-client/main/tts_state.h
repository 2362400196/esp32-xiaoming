#pragma once
// 字幕 TTS 同步状态（定义在 commands/callback_commands.c，供 websocket.c 等读取）。
// 单独成头文件以替代散落在各 .c 中的 extern 声明，避免签名漂移。

#include <stdint.h>
#include <stdbool.h>
#include "freertos/semphr.h"

#ifdef __cplusplus
extern "C" {
#endif

// TTS 是否正在播放（字幕节拍同步用）
extern bool s_tts_is_playing;
// 本段 TTS 播放起始时间（ms，esp_timer 时基）
extern uint64_t s_tts_start_time_ms;
// 本段 TTS 预期时长（ms）
extern int s_tts_duration_ms;
// 保护上述三个变量的互斥锁（可能为 NULL，调用方需判空回退为无锁访问）
extern SemaphoreHandle_t s_tts_state_mutex;

#ifdef __cplusplus
}
#endif
