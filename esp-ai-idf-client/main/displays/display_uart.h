/**
 * display_uart.h - 串口显示驱动接口
 *
 * 通过串口输出状态信息，无图形显示
 * 适用于无屏幕的板型（如 breadboard）
 */
#pragma once

#include "display_driver.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 获取串口显示驱动
 */
const display_driver_t *display_driver_uart_get(void);

#ifdef __cplusplus
}
#endif