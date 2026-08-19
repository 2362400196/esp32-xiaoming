/**
 * lua_module_http.h
 * Lua HTTP 模块 — 在 ESP32 上启动 HTTP 服务器
 *
 * Lua 用法:
 *   local http = require("http")
 *   local sys = require("system")
 *
 *   -- 生成网页内容（可动态读取系统信息）
 *   local html = string.format(
 *     "<html><body><h1>ESP-AI</h1>" ..
 *     "<p>Free RAM: %d</p><p>Free PSRAM: %d</p>" ..
 *     "</body></html>",
 *     sys.free_heap(), sys.free_psram())
 *
 *   -- 启动服务器并设置页面
 *   http.start(80)        -- 启动 HTTP 服务器，端口 80
 *   http.set_page("/", html)  -- 设置根路径返回的 HTML
 *   -- 服务器会在后台持续运行，脚本结束后不停止
 *
 *   -- 也可以设置多个路径
 *   http.set_page("/info", "<html><body>Info page</body></html>")
 *
 *   -- 停止服务器
 *   http.stop()
 */
#ifndef LUA_MODULE_HTTP_H
#define LUA_MODULE_HTTP_H

#include "esp_err.h"
#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

int luaopen_http(lua_State *L);

#ifdef __cplusplus
}
#endif

#endif /* LUA_MODULE_HTTP_H */
