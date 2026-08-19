/**
 * lua_module_http.c
 * Lua HTTP 服务器模块
 *
 * 在 ESP32 上启动 HTTP 服务器，让 Lua 脚本控制返回的网页内容。
 *
 * 设计要点：
 *   - C 层运行 esp_http_server，Lua 脚本通过 API 设置页面内容
 *   - 页面内容存储在 C 层全局缓冲区（PSRAM），Lua 状态销毁后依然有效
 *   - 服务器在后台独立任务中运行，不影响 Lua 脚本执行
 *   - 支持多路径：每个路径存储独立的 HTML 内容
 *
 * Lua API:
 *   http.start(port)              -> boolean   启动 HTTP 服务器
 *   http.stop()                               停止 HTTP 服务器
 *   http.set_page(path, html)     -> boolean   设置路径返回的 HTML 内容
 *   http.set_content_type(type)               设置默认 Content-Type
 *   http.is_running()             -> boolean   服务器是否在运行
 */
#include "lua_module_http.h"

#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#include "esp_log.h"
#include "esp_http_server.h"
#include "esp_heap_caps.h"

#include "lauxlib.h"

static const char *TAG = "lua_http";

/* ==================== 全局状态 ==================== */

#define MAX_HTTP_ROUTES 8
#define MAX_CONTENT_TYPE 64

typedef struct {
    char path[64];          /* URL 路径，如 "/" 或 "/info" */
    char *html;             /* HTML 内容（PSRAM 分配） */
    size_t html_len;        /* HTML 长度 */
    bool used;              /* 是否使用 */
} http_route_t;

static httpd_handle_t s_server = NULL;
static http_route_t s_routes[MAX_HTTP_ROUTES];
static char s_default_content_type[MAX_CONTENT_TYPE] = "text/html; charset=utf-8";

/* ==================== 路由查找 ==================== */

static http_route_t *find_route(const char *path)
{
    for (int i = 0; i < MAX_HTTP_ROUTES; i++) {
        if (s_routes[i].used && strcmp(s_routes[i].path, path) == 0) {
            return &s_routes[i];
        }
    }
    return NULL;
}

static http_route_t *find_free_route(void)
{
    for (int i = 0; i < MAX_HTTP_ROUTES; i++) {
        if (!s_routes[i].used) {
            return &s_routes[i];
        }
    }
    return NULL;
}

static void free_route(http_route_t *route)
{
    if (route->html) {
        free(route->html);
        route->html = NULL;
        route->html_len = 0;
    }
    route->path[0] = '\0';
    route->used = false;
}

/* ==================== HTTP 请求处理 ==================== */

static esp_err_t http_handler(httpd_req_t *req)
{
    const char *uri = req->uri;
    ESP_LOGD(TAG, "请求: %s", uri);

    /* 查找匹配的路由 */
    http_route_t *route = find_route(uri);
    if (!route) {
        /* 未找到路由，尝试回退到 "/" */
        if (strcmp(uri, "/") != 0) {
            route = find_route("/");
        }
    }

    if (!route || !route->html) {
        /* 没有设置任何页面，返回默认提示 */
        const char *default_html =
            "<!DOCTYPE html><html><body>"
            "<h1>ESP-AI HTTP Server</h1>"
            "<p>请通过 Lua 脚本调用 http.set_page() 设置页面内容</p>"
            "</body></html>";
        httpd_resp_set_type(req, "text/html; charset=utf-8");
        httpd_resp_send(req, default_html, strlen(default_html));
        return ESP_OK;
    }

    /* 设置 Content-Type 并发送内容 */
    httpd_resp_set_type(req, s_default_content_type);
    httpd_resp_send(req, route->html, route->html_len);
    return ESP_OK;
}

/* ==================== Lua API 函数 ==================== */

/**
 * http.start(port) -> boolean
 * 启动 HTTP 服务器
 */
static int l_start(lua_State *L)
{
    int port = (int)luaL_optinteger(L, 1, 80);

    if (s_server) {
        ESP_LOGW(TAG, "HTTP 服务器已在运行");
        lua_pushboolean(L, true);
        return 1;
    }

    // 诊断：打印内部 RAM 使用情况
    size_t free_internal = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    size_t largest_internal = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
    size_t free_psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    ESP_LOGI(TAG, "HTTP 服务器启动前内存: 内部RAM可用=%lu 最大块=%lu PSRAM可用=%lu",
             (unsigned long)free_internal, (unsigned long)largest_internal,
             (unsigned long)free_psram);

    // 尝试启动 HTTP 服务器
    // 注意：esp_http_server 的控制结构必须在内部 RAM 中分配。
    // 如果内部 RAM 紧张，任务栈可以分配到 PSRAM
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = port;
    config.max_uri_handlers = MAX_HTTP_ROUTES + 2;
    config.stack_size = 4096;
    config.task_priority = 1;
    config.core_id = 0;
    config.lru_purge_enable = true;
    config.max_open_sockets = 3;
    // 尝试将任务栈分配到 PSRAM，减轻内部 RAM 压力
    config.global_user_ctx = NULL;
#ifdef CONFIG_SPIRAM_USE_MALLOC
    config.stack_size = 6144;  // 栈放 PSRAM 可以稍大一些
#endif

    esp_err_t err = httpd_start(&s_server, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP 服务器启动失败: %s (端口 %d), 启动前内部RAM=%lu 最大块=%lu",
                 esp_err_to_name(err), port,
                 (unsigned long)free_internal, (unsigned long)largest_internal);
        // 提示可能的解决方案
        if (err == ESP_ERR_NO_MEM) {
            ESP_LOGE(TAG, "内部 RAM 不足，建议: 1)拔掉 USB 重试(释放 CDC 缓冲区) "
                     "2)在 sdkconfig 中增大 SPIRAM_MALLOC_RESERVE_INTERNAL");
        }
        lua_pushboolean(L, false);
        lua_pushstring(L, esp_err_to_name(err));
        return 2;
    }

    /* 注册通配 URI 处理器（处理所有 GET 请求） */
    httpd_uri_t uri_get = {
        .uri = "/*",
        .method = HTTP_GET,
        .handler = http_handler,
        .user_ctx = NULL,
    };
    httpd_register_uri_handler(s_server, &uri_get);

    ESP_LOGI(TAG, "HTTP 服务器已启动，端口 %d", port);
    lua_pushboolean(L, true);
    return 1;
}

/**
 * http.stop()
 * 停止 HTTP 服务器
 */
static int l_stop(lua_State *L)
{
    if (s_server) {
        httpd_stop(s_server);
        s_server = NULL;

        /* 释放所有路由内容 */
        for (int i = 0; i < MAX_HTTP_ROUTES; i++) {
            if (s_routes[i].used) {
                free_route(&s_routes[i]);
            }
        }

        ESP_LOGI(TAG, "HTTP 服务器已停止");
    } else {
        ESP_LOGW(TAG, "HTTP 服务器未运行");
    }
    return 0;
}

/**
 * http.set_page(path, html) -> boolean
 * 设置指定路径返回的 HTML 内容
 * path: URL 路径，如 "/" 或 "/info"
 * html: HTML 字符串内容
 */
static int l_set_page(lua_State *L)
{
    const char *path = luaL_checkstring(L, 1);
    size_t html_len = 0;
    const char *html = luaL_checklstring(L, 2, &html_len);

    if (!s_server) {
        ESP_LOGE(TAG, "HTTP 服务器未启动，请先调用 http.start()");
        lua_pushboolean(L, false);
        lua_pushstring(L, "server not started");
        return 2;
    }

    if (strlen(path) >= sizeof(s_routes[0].path)) {
        ESP_LOGE(TAG, "路径过长: %s", path);
        lua_pushboolean(L, false);
        lua_pushstring(L, "path too long");
        return 2;
    }

    /* 查找现有路由或创建新路由 */
    http_route_t *route = find_route(path);
    if (!route) {
        route = find_free_route();
        if (!route) {
            ESP_LOGE(TAG, "路由数量已达上限 (%d)", MAX_HTTP_ROUTES);
            lua_pushboolean(L, false);
            lua_pushstring(L, "too many routes");
            return 2;
        }
        strlcpy(route->path, path, sizeof(route->path));
        route->used = true;
    }

    /* 释放旧内容 */
    if (route->html) {
        free(route->html);
        route->html = NULL;
    }

    /* 分配新内容（优先 PSRAM） */
    route->html = (char *)heap_caps_malloc(html_len + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!route->html) {
        /* PSRAM 失败，尝试普通分配 */
        route->html = (char *)malloc(html_len + 1);
    }
    if (!route->html) {
        ESP_LOGE(TAG, "内存分配失败 (%d 字节)", html_len + 1);
        route->used = false;
        lua_pushboolean(L, false);
        lua_pushstring(L, "out of memory");
        return 2;
    }

    memcpy(route->html, html, html_len);
    route->html[html_len] = '\0';
    route->html_len = html_len;

    ESP_LOGI(TAG, "设置页面: %s (%d 字节)", path, html_len);
    lua_pushboolean(L, true);
    return 1;
}

/**
 * http.set_content_type(type)
 * 设置默认 Content-Type（默认 text/html; charset=utf-8）
 */
static int l_set_content_type(lua_State *L)
{
    const char *ct = luaL_checkstring(L, 1);
    strlcpy(s_default_content_type, ct, sizeof(s_default_content_type));
    ESP_LOGD(TAG, "Content-Type: %s", s_default_content_type);
    return 0;
}

/**
 * http.is_running() -> boolean
 */
static int l_is_running(lua_State *L)
{
    lua_pushboolean(L, s_server != NULL);
    return 1;
}

/* ==================== 模块注册 ==================== */

int luaopen_http(lua_State *L)
{
    static const luaL_Reg http_funcs[] = {
        {"start",           l_start},
        {"stop",            l_stop},
        {"set_page",        l_set_page},
        {"set_content_type", l_set_content_type},
        {"is_running",      l_is_running},
        {NULL, NULL}
    };

    lua_newtable(L);
    luaL_setfuncs(L, http_funcs, 0);
    return 1;
}
