/**
 * sdcard.h - SD 卡挂载（SDMMC 1-bit）
 *
 * 板型通过 BOARD_SD_CARD(clk, cmd, d0) 配置引脚后，调用 sdcard_init() 挂载到 /sdcard。
 * 未配置（引脚为 -1）时直接跳过，不影响其他板型。
 */
#pragma once

#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 挂载 SD 卡到 /sdcard（未配置或未插卡时返回错误，不阻塞启动） */
esp_err_t sdcard_init(void);

/** 是否已成功挂载 */
bool sdcard_is_mounted(void);

/** 挂载点路径（固定 "/sdcard"） */
const char *sdcard_mount_point(void);

#ifdef __cplusplus
}
#endif
