/**
 * extras_led.h - 板型扩展组件：状态 LED（LEDC PWM 调光）
 *
 * 第一个真实 extras 组件示例，演示「组件定义 → 板型挂载 → 服务端指令/系统事件」
 * 的完整链路。其他板级专属硬件（触摸屏/传感器/灯带等）照此模式添加即可。
 *
 * 服务端指令（instruct 类型，command_id 直接命中组件）：
 *   led_set   参数 {"on":true,"brightness":0-100}（brightness 可省略，默认 100）
 *   led_get   无参数，返回 {"on":bool,"brightness":N}
 *
 * 系统事件：收到 BOARD_EVENT_WAKEUP 时双闪两次（非阻塞，esp_timer 实现）。
 *
 * 板型挂载（boards/defs/<name>.h 末尾，替换 BOARD_EXTRAS_NONE()）：
 *   BOARD_EXTRAS_LED(48, false),   // GPIO48，高电平点亮
 */

#pragma once

#include "boards/board_interface.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** LED 组件的板型配置（BOARD_EXTRAS_LED 宏中实例化） */
typedef struct {
    int  gpio;        // LED 引脚
    bool active_low;  // true: 低电平点亮
} led_extra_config_t;

// 组件接口实现（由 BOARD_EXTRAS_LED 宏装配到 extras 数组）
esp_err_t extras_led_init(const void *config);
void      extras_led_deinit(void);
esp_err_t extras_led_command(const char *cmd, const char *args,
                             char *resp, size_t resp_len);
void      extras_led_on_event(board_event_t event, void *data);

#ifdef __cplusplus
}
#endif
