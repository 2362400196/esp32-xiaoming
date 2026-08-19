/**
 * lua_module_led.h — Lua LED 灯带模块
 */
#ifndef LUA_MODULE_LED_H
#define LUA_MODULE_LED_H

#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_led(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif
