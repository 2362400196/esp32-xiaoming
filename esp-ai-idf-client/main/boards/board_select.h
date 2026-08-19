/**
 * board_select.h - 编译时板型选择（自动生成，请勿手动编辑）
 *
 * 由 gen_boards.py 扫描 boards/defs/ 目录生成
 *
 * 工作原理：
 * - menuconfig 选择 CONFIG_BOARD_<NAME> 宏
 * - 本文件通过 #ifdef 匹配宏，#include 对应板型定义
 *
 * 注意：音频编解码器（ES8311 等）的选择由 Kconfig.projbuild
 *      中的 AUDIO_CODEC 选项控制，与本文件无关。
 */
#pragma once

#ifdef CONFIG_BOARD_BREADBOARD
#include "boards/defs/breadboard.h"
#define ACTIVE_BOARD_CONFIG (&BOARD_CONFIG)
#endif

#ifdef CONFIG_BOARD_BREADBOARD_1_54_LCD
#include "boards/defs/breadboard_1.54_lcd.h"
#define ACTIVE_BOARD_CONFIG (&BOARD_CONFIG)
#endif

#ifdef CONFIG_BOARD_BREADBOARD_1_54_LCD_OFFICIAL
#include "boards/defs/breadboard_1.54_lcd_official.h"
#define ACTIVE_BOARD_CONFIG (&BOARD_CONFIG)
#endif

#ifdef CONFIG_BOARD_ESP32C3_SUPERMINI
#include "boards/defs/esp32c3_supermini.h"
#define ACTIVE_BOARD_CONFIG (&BOARD_CONFIG)
#endif

#ifndef ACTIVE_BOARD_CONFIG
#error "未选择板型，请在 menuconfig → 选择开发板型号 中设置"
#endif
