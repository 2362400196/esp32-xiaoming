/**
 * lua_module_delay.h
 * Lua delay 模块 — sleep_ms / sleep_us
 */
#ifndef LUA_MODULE_DELAY_H
#define LUA_MODULE_DELAY_H

#include "esp_err.h"
#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_delay(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif // LUA_MODULE_DELAY_H
