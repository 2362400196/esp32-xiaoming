/**
 * lua_module_system.h
 * Lua system 模块 — 系统信息、内存、时间
 */
#ifndef LUA_MODULE_SYSTEM_H
#define LUA_MODULE_SYSTEM_H

#include "esp_err.h"
#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_system(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif // LUA_MODULE_SYSTEM_H
