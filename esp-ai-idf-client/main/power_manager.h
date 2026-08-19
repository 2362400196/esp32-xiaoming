/**
 * power_manager.h - 功耗管理模块
 *
 * 移植自 xiaozhi-esp32 的 AudioService 功耗管理机制。
 * 核心思想：音频输出空闲超过阈值（15秒）时，自动关闭 PA 功放 + ES8311 DAC 静音，
 * 降低待机功耗；当新的音频播放请求到来时，自动恢复硬件。
 *
 * 工作流程：
 *   1. audio_spk_play() → power_manager_enable_output() → PA on + DAC unmute
 *   2. spk_task I2S 写入 → power_manager_notify_output() → 刷新时间戳
 *   3. 定时器每秒检查：输出空闲 > 15s → PA off + DAC mute
 *   4. 下次 audio_spk_play() → power_manager_enable_output() → 恢复硬件
 *
 * 注意：
 *   - notify_output() 仅更新时间戳（原子操作），可在热路径调用
 *   - enable/disable 操作通过互斥锁保护，防止定时器与播放任务竞争
 *   - 仅 ES8311 方案有实际硬件控制（PA 引脚 + DAC 静音），I2S 直连方案为空操作
 */
#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 初始化功耗管理模块
 * 
 * 创建互斥锁，设置初始状态（输出已使能）。
 * 必须在 audio_init() 之后调用（PA 引脚已配置）。
 * 
 * @return ESP_OK 或错误码
 */
esp_err_t power_manager_init(void);

/**
 * @brief 启动功耗管理定时器
 * 
 * 每秒检查一次音频输出空闲状态。
 * 必须在 power_manager_init() 之后调用。
 * 
 * @return ESP_OK 或错误码
 */
esp_err_t power_manager_start(void);

/**
 * @brief 通知输出活动（刷新时间戳）
 * 
 * 在音频数据写入 I2S 或收到服务端音频数据时调用。
 * 仅更新时间戳，无锁操作，可在热路径（spk_task）频繁调用。
 */
void power_manager_notify_output(void);

/**
 * @brief 使能音频输出硬件
 * 
 * 如果输出当前已禁用，则恢复 PA 功放 + DAC 解静音。
 * 在 audio_spk_play() 中调用，确保播放前硬件已就绪。
 */
void power_manager_enable_output(void);

/**
 * @brief 查询输出硬件是否已使能
 * 
 * @return true=PA+DAC 已开启, false=已关闭（省电模式）
 */
bool power_manager_is_output_enabled(void);

/**
 * @brief 设置会话活跃状态（省电切换）
 *
 * 待机（active=false，默认）：CPU DFS 空闲降频 + WiFi modem sleep（MIN_MODEM），
 * 语音唤醒持续监听不受影响；对话活跃（active=true）：WiFi 切回 NONE 保证低延迟。
 * 由 main.c（唤醒触发）和 websocket.c（会话结束/断开）调用。
 */
void power_manager_set_active(bool active);

#ifdef __cplusplus
}
#endif
