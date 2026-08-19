/**
 * lua_module_system.c
 * Lua system 模块 — 系统信息、内存、时间
 *
 * 从 esp-claw lua_module_system 移植
 *
 * Lua 用法:
 *   local sys = require("system")
 *   print(sys.millis())       -- 运行毫秒数
 *   print(sys.micros())       -- 运行微秒数
 *   print(sys.free_heap())    -- 剩余堆内存(字节)
 *   print(sys.free_psram())   -- 剩余 PSRAM 大小(字节)
 *   print(sys.chip_info())    -- 芯片信息字符串
 *   print(sys.restart())      -- 重启设备
 */
#include "lua_module_system.h"

#include <stdio.h>
#include <string.h>
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_chip_info.h"
#include "esp_system.h"
#include "lauxlib.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *NVS_NAMESPACE = "esp-ai-kv";

static int l_millis(lua_State *L)
{
    lua_pushinteger(L, (lua_Integer)(esp_timer_get_time() / 1000));
    return 1;
}

static int l_micros(lua_State *L)
{
    lua_pushinteger(L, (lua_Integer)esp_timer_get_time());
    return 1;
}

static int l_free_heap(lua_State *L)
{
    lua_pushinteger(L, (lua_Integer)esp_get_free_heap_size());
    return 1;
}

static int l_free_psram(lua_State *L)
{
    /* 尝试获取 PSRAM 大小，不支持时返回 0 */
    size_t free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    lua_pushinteger(L, (lua_Integer)free);
    return 1;
}

static int l_chip_info(lua_State *L)
{
    esp_chip_info_t info;
    esp_chip_info(&info);

    char buf[128];
    snprintf(buf, sizeof(buf),
             "%s rev %d, %d cores%s%s",
             CONFIG_IDF_TARGET,
             info.revision,
             info.cores,
             (info.features & CHIP_FEATURE_WIFI_BGN) ? " WiFi" : "",
             (info.features & CHIP_FEATURE_BLE) ? " BLE" : "");

    lua_pushstring(L, buf);
    return 1;
}

static int l_restart(lua_State *L)
{
    esp_restart();
    return 0;
}

static int l_read_nvs(lua_State *L)
{
    const char *key = luaL_checkstring(L, 1);
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) {
        lua_pushnil(L);
        return 1;
    }
    char buf[512] = {0};
    size_t len = sizeof(buf);
    err = nvs_get_str(h, key, buf, &len);
    nvs_close(h);
    if (err == ESP_OK && len > 0) {
        lua_pushstring(L, buf);
    } else {
        lua_pushnil(L);
    }
    return 1;
}

static int l_write_nvs(lua_State *L)
{
    const char *key = luaL_checkstring(L, 1);
    const char *val = luaL_checkstring(L, 2);
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h);
    if (err != ESP_OK) {
        lua_pushboolean(L, 0);
        return 1;
    }
    err = nvs_set_str(h, key, val);
    if (err == ESP_OK) {
        nvs_commit(h);
    }
    nvs_close(h);
    lua_pushboolean(L, err == ESP_OK);
    return 1;
}

int luaopen_system(lua_State *L)
{
    static const luaL_Reg sys_funcs[] = {
        {"millis",    l_millis},
        {"micros",    l_micros},
        {"free_heap", l_free_heap},
        {"free_psram", l_free_psram},
        {"chip_info", l_chip_info},
        {"restart",   l_restart},
        {"read_nvs",  l_read_nvs},
        {"write_nvs", l_write_nvs},
        {NULL, NULL}
    };

    lua_newtable(L);
    luaL_setfuncs(L, sys_funcs, 0);
    return 1;
}
