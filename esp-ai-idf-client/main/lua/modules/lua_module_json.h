/**
 * lua_module_json.h
 * Lua JSON 模块 — encode/decode
 */
#ifndef LUA_MODULE_JSON_H
#define LUA_MODULE_JSON_H

#include "esp_err.h"
#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_json(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif // LUA_MODULE_JSON_H
