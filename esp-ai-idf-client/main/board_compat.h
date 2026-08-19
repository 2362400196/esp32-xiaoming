/**
 * board_compat.h - 跨芯片板级兼容宏（多芯片支持，ESP32-S3/C3/C2 等）
 *
 * 设计目标：新增单核 / 无 PSRAM 芯片（如 ESP32-C3）板型时，核心代码
 * 无需改动，只需把任务核心 / 内存分配改成这里提供的兼容宏。
 * 双核 + PSRAM 的 ESP32-S3 行为与原先完全一致（条件编译展开）。
 */
#pragma once

#include "freertos/FreeRTOSConfig.h"
#include "esp_heap_caps.h"
#include <stddef.h>

// ==================== 任务核心 ====================
// 双核芯片：音频/唤醒/显示任务固定到 core 1（与网络分离），core 0 跑网络；
// 单核芯片（C3/C2 等，无 core 1）：全部固定到 core 0。
#if (configNUMBER_OF_CORES > 1)
#define BOARD_TASK_CORE_0   0
#define BOARD_TASK_CORE_1   1
#else
#define BOARD_TASK_CORE_0   0
#define BOARD_TASK_CORE_1   0
#endif

// ==================== 栈内存能力（PSRAM 回退）====================
// 有 PSRAM：任务栈放 PSRAM（省内部 RAM）；无 PSRAM（C3）：回退内部 RAM。
#if defined(CONFIG_SPIRAM)
#define BOARD_STACK_CAPS_AUDIO  (MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)
#else
#define BOARD_STACK_CAPS_AUDIO  (MALLOC_CAP_8BIT)
#endif

// ==================== 大缓冲分配（PSRAM 优先，内部 RAM 兜底）====================
// 用于 AFE feed 缓冲、音频待播放缓冲、GIF 下载缓冲等大块内存。
// 有 PSRAM 时优先用 PSRAM（与 S3 原行为一致）；无 PSRAM 时用内部 RAM。
static inline void *board_malloc_audio(size_t size)
{
#if defined(CONFIG_SPIRAM)
    void *p = heap_caps_malloc(size, MALLOC_CAP_SPIRAM);
    if (p != NULL) {
        return p;
    }
#endif
    return heap_caps_malloc(size, MALLOC_CAP_8BIT);
}
