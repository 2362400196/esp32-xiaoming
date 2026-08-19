/**
 * log_system.h - 统一日志系统
 *
 * 通过 menuconfig 的 CONFIG_LOG_LEVEL_PRODUCTION / CONFIG_LOG_LEVEL_DEBUG 开关控制日志级别：
 *   - 生产级别（默认）：仅显示 WARNING 和 ERROR，静默 INFO 和 DEBUG
 *   - 调试级别：显示全部日志（DEBUG/INFO/WARNING/ERROR）
 *
 * 用法：在各源文件中用 LOG_TAG 宏声明 TAG，然后用 LOGI/LOGW/LOGE/LOGD 替代 ESP_LOGI 等。
 *   #define LOG_TAG "my_module"
 *   #include "log_system.h"
 *   LOGI("初始化完成");
 *
 * 也可直接用 ESP_LOGI 等，此头文件会根据配置自动控制它们是否输出。
 */
#pragma once

#include "esp_log.h"

/* ==================== 日志级别配置 ====================
 * menuconfig 中选择 CONFIG_LOG_LEVEL_PRODUCTION 或 CONFIG_LOG_LEVEL_DEBUG
 * 生产级别：ESP_LOG_INFO 级别的日志被静默
 * 调试级别：全部日志可见
 */

#ifdef CONFIG_LOG_LEVEL_DEBUG
    /* 调试模式：使用 ESP-IDF 默认行为，所有级别日志均可输出 */
    #define LOGI(tag, fmt, ...)  ESP_LOGI(tag, fmt, ##__VA_ARGS__)
    #define LOGW(tag, fmt, ...)  ESP_LOGW(tag, fmt, ##__VA_ARGS__)
    #define LOGE(tag, fmt, ...)  ESP_LOGE(tag, fmt, ##__VA_ARGS__)
    #define LOGD(tag, fmt, ...)  ESP_LOGD(tag, fmt, ##__VA_ARGS__)
#else
    /* 生产模式：静默 INFO 和 DEBUG，仅保留 WARNING 和 ERROR */
    #define LOGI(tag, fmt, ...)  do {} while(0)
    #define LOGD(tag, fmt, ...)  do {} while(0)
    #define LOGW(tag, fmt, ...)  ESP_LOGW(tag, fmt, ##__VA_ARGS__)
    #define LOGE(tag, fmt, ...)  ESP_LOGE(tag, fmt, ##__VA_ARGS__)
#endif

/* ==================== 便捷宏（使用文件级 LOG_TAG）====================
 * 如果源文件中定义了 LOG_TAG，可直接使用 LOG_I/LOG_W/LOG_E/LOG_D
 */
#ifdef LOG_TAG
    #define LOG_I(fmt, ...)   LOGI(LOG_TAG, fmt, ##__VA_ARGS__)
    #define LOG_W(fmt, ...)   LOGW(LOG_TAG, fmt, ##__VA_ARGS__)
    #define LOG_E(fmt, ...)   LOGE(LOG_TAG, fmt, ##__VA_ARGS__)
    #define LOG_D(fmt, ...)   LOGD(LOG_TAG, fmt, ##__VA_ARGS__)
#endif
