/**
 * lua_module_json.c
 * Lua JSON 模块 — encode/decode
 *
 * 从 esp-claw lua_module_json 移植，使用 cJSON 库
 *
 * Lua 用法:
 *   local json = require("json")
 *   local t = json.decode('{"a":1,"b":2}')
 *   print(t.a)  -- 1
 *   local s = json.encode({x=10, y=20})
 *   print(s)    -- {"x":10,"y":20}
 */
#include "lua_module_json.h"

#include <stdbool.h>
#include <string.h>
#include "cJSON.h"
#include "lauxlib.h"

/* ==================== JSON → Lua table（递归） ==================== */

static void push_json_value(lua_State *L, const cJSON *item)
{
    if (!item || cJSON_IsNull(item)) {
        lua_pushnil(L);
        return;
    }
    if (cJSON_IsBool(item)) {
        lua_pushboolean(L, cJSON_IsTrue(item));
        return;
    }
    if (cJSON_IsNumber(item)) {
        lua_pushnumber(L, item->valuedouble);
        return;
    }
    if (cJSON_IsString(item)) {
        lua_pushstring(L, item->valuestring);
        return;
    }
    if (cJSON_IsArray(item)) {
        lua_newtable(L);
        int index = 1;
        cJSON *child;
        cJSON_ArrayForEach(child, item) {
            push_json_value(L, child);
            lua_rawseti(L, -2, index++);
        }
        return;
    }
    if (cJSON_IsObject(item)) {
        lua_newtable(L);
        cJSON *child;
        cJSON_ArrayForEach(child, item) {
            push_json_value(L, child);
            lua_setfield(L, -2, child->string);
        }
        return;
    }
    lua_pushnil(L);
}

/* ==================== Lua table → JSON（递归） ==================== */

static cJSON *table_to_json(lua_State *L, int index)
{
    if (index < 0) index = lua_gettop(L) + index + 1;

    if (lua_type(L, index) == LUA_TNIL) {
        return cJSON_CreateNull();
    }
    if (lua_isboolean(L, index)) {
        return cJSON_CreateBool(lua_toboolean(L, index));
    }
    if (lua_isinteger(L, index)) {
        return cJSON_CreateNumber((double)lua_tointeger(L, index));
    }
    if (lua_isnumber(L, index)) {
        return cJSON_CreateNumber(lua_tonumber(L, index));
    }
    if (lua_isstring(L, index)) {
        return cJSON_CreateString(lua_tostring(L, index));
    }
    if (lua_istable(L, index)) {
        /* 判断是数组还是对象：如果是纯数字键 1..n 则为数组 */
        int max_key = 0;
        int count = 0;
        bool is_array = true;

        lua_pushnil(L);
        while (lua_next(L, index) != 0) {
            if (lua_type(L, -2) == LUA_TNUMBER) {
                lua_Integer key = lua_tointeger(L, -2);
                if (key >= 1) {
                    if (key > max_key) max_key = (int)key;
                    count++;
                } else {
                    is_array = false;
                }
            } else {
                is_array = false;
            }
            lua_pop(L, 1);
        }

        if (is_array && count == max_key && max_key > 0) {
            /* 数组 */
            cJSON *arr = cJSON_CreateArray();
            if (!arr) return NULL;
            for (int i = 1; i <= max_key; i++) {
                lua_rawgeti(L, index, i);
                cJSON *item = table_to_json(L, -1);
                lua_pop(L, 1);
                if (item) {
                    cJSON_AddItemToArray(arr, item);
                }
            }
            return arr;
        } else {
            /* 对象 */
            cJSON *obj = cJSON_CreateObject();
            if (!obj) return NULL;
            lua_pushnil(L);
            while (lua_next(L, index) != 0) {
                const char *key;
                if (lua_type(L, -2) == LUA_TSTRING) {
                    key = lua_tostring(L, -2);
                } else {
                    /* 数字键转字符串 */
                    lua_pushvalue(L, -2);
                    key = lua_tostring(L, -1);
                }
                cJSON *val = table_to_json(L, -1);
                if (key && val) {
                    cJSON_AddItemToObject(obj, key, val);
                }
                if (lua_type(L, -2) != LUA_TSTRING) {
                    lua_pop(L, 1); /* pop stringified key */
                }
                lua_pop(L, 1);
            }
            return obj;
        }
    }

    return cJSON_CreateNull();
}

/* ==================== Lua 绑定函数 ==================== */

/* json.decode(str) → table */
static int l_decode(lua_State *L)
{
    const char *str = luaL_checkstring(L, 1);

    cJSON *root = cJSON_Parse(str);
    if (!root) {
        const char *err = cJSON_GetErrorPtr();
        return luaL_error(L, "JSON decode error: %s", err ? err : "unknown");
    }

    push_json_value(L, root);
    cJSON_Delete(root);
    return 1;
}

/* json.encode(value) → string */
static int l_encode(lua_State *L)
{
    cJSON *root = table_to_json(L, 1);
    if (!root) {
        return luaL_error(L, "JSON encode error: failed to create JSON");
    }

    char *str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);

    if (!str) {
        return luaL_error(L, "JSON encode error: out of memory");
    }

    lua_pushstring(L, str);
    free(str);
    return 1;
}

/* json.pretty(value) → string */
static int l_pretty(lua_State *L)
{
    cJSON *root = table_to_json(L, 1);
    if (!root) {
        return luaL_error(L, "JSON pretty error");
    }

    char *str = cJSON_Print(root);
    cJSON_Delete(root);

    if (!str) {
        return luaL_error(L, "JSON pretty error: out of memory");
    }

    lua_pushstring(L, str);
    free(str);
    return 1;
}

int luaopen_json(lua_State *L)
{
    static const luaL_Reg json_funcs[] = {
        {"decode", l_decode},
        {"encode", l_encode},
        {"pretty", l_pretty},
        {NULL, NULL}
    };

    lua_newtable(L);
    luaL_setfuncs(L, json_funcs, 0);
    return 1;
}
