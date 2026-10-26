/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include "esp_err.h"
#include "lua.h"

// PCNT 外设仅在 ESP32/S2/S3/P4/C5/C6/H2/H4 上存在（C3/C2 无此硬件，
// 其 soc_caps.h 甚至不定义 SOC_PCNT_SUPPORTED）。无 PCNT 的芯片不编译
// lua_driver_pcnt.c，这里提供空实现兜底，Lua 调用 pcnt 模块时静默跳过。
#if !defined(CONFIG_SOC_PCNT_SUPPORTED) || !CONFIG_SOC_PCNT_SUPPORTED
static inline int luaopen_pcnt(lua_State *L) { (void)L; return 0; }
static inline esp_err_t lua_driver_pcnt_register(void) { return ESP_OK; }
#else
int luaopen_pcnt(lua_State *L);
esp_err_t lua_driver_pcnt_register(void);
#endif
