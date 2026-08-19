/**
 * lua_module_delay.c
 * Lua delay 模块 — sleep_ms / sleep_us
 *
 * 从 esp-claw lua_module_delay 移植
 *
 * Lua 用法:
 *   local delay = require("delay")
 *   delay.delay_ms(1000)   -- 延时 1 秒
 *   delay.delay_us(500)    -- 延时 500 微秒
 */
#include "lua_module_delay.h"

#include <stdint.h>
#include "lauxlib.h"
#include "esp_rom_sys.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LUA_MODULE_DELAY_US_MAX_BLOCKING 1000000U

static int l_sleep_ms(lua_State *L)
{
    lua_Integer ms = luaL_checkinteger(L, 1);
    if (ms < 0) ms = 0;

    /* 长延时直接阻塞，但每 100ms 喂一次狗 */
    while (ms >= 100) {
        vTaskDelay(pdMS_TO_TICKS(100));
        esp_task_wdt_reset();
        ms -= 100;
    }
    if (ms > 0) {
        vTaskDelay(pdMS_TO_TICKS((uint32_t)ms));
        esp_task_wdt_reset();
    }
    return 0;
}

static int l_sleep_us(lua_State *L)
{
    lua_Integer us = luaL_checkinteger(L, 1);
    if (us < 0) us = 0;
    if ((uint64_t)us > LUA_MODULE_DELAY_US_MAX_BLOCKING) {
        return luaL_error(L, "delay_us supports 0..%u only; use delay_ms for longer waits",
                          LUA_MODULE_DELAY_US_MAX_BLOCKING);
    }
    esp_rom_delay_us((uint32_t)us);
    return 0;
}

int luaopen_delay(lua_State *L)
{
    lua_newtable(L);
    lua_pushcfunction(L, l_sleep_ms);
    lua_setfield(L, -2, "delay_ms");
    lua_pushcfunction(L, l_sleep_us);
    lua_setfield(L, -2, "delay_us");
    return 1;
}
