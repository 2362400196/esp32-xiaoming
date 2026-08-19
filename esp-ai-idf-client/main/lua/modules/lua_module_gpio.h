/**
 * lua_module_gpio.h — Lua GPIO 模块
 */
#ifndef LUA_MODULE_GPIO_H
#define LUA_MODULE_GPIO_H

#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_gpio(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif
