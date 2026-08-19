#pragma once
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 获取设备唯一标识（基于WiFi MAC地址）
 * 格式: "XX:XX:XX:XX:XX:XX" (MAC地址)
 */
void device_id_get(char *buf, size_t len);

/**
 * 获取设备唯一标识的紧凑格式（无冒号，用于某些场景）
 */
void device_id_get_compact(char *buf, size_t len);

#ifdef __cplusplus
}
#endif
