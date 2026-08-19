/**
 * lua_runtime.c
 * Lua 脚本运行时引擎实现
 *
 * 从 esp-claw cap_lua + cap_lua_runtime 移植，适配 Arduino/PlatformIO。
 * 核心功能：
 *   - 模块注册系统（最多 32 个模块）
 *   - 同步执行 .lua 文件和代码字符串
 *   - 超时控制（lua_sethook 每 100 条指令检查）
 *   - print 输出捕获
 *   - JSON args 传递
 */
#include "lua_runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "cJSON.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lauxlib.h"
#include "lualib.h"
#include "esp_heap_caps.h"

static const char *TAG = "lua_rt";

/* ==================== 内部常量 ==================== */

#define LUA_RUNTIME_MAX_MODULES     32
#define LUA_RUNTIME_MAX_SCRIPT_SIZE (16 * 1024)
#define LUA_RUNTIME_DEFAULT_TIMEOUT 60000

/* ==================== 执行上下文 ==================== */

typedef struct {
    char *buf;              /* 输出缓冲区 */
    size_t size;            /* 缓冲区总大小 */
    size_t len;             /* 已写入长度 */
    bool truncated;         /* 是否截断 */
    int64_t deadline_us;    /* 截止时间（微秒），0 = 无截止 */
    int64_t start_us;       /* 开始时间，用于限制最大执行时长 */
} lua_runtime_exec_ctx_t;

/* ==================== 全局状态 ==================== */

static lua_runtime_module_t s_modules[LUA_RUNTIME_MAX_MODULES];
static size_t s_module_count = 0;
static bool s_module_locked = false;

/* ==================== 模块注册 ==================== */

esp_err_t lua_runtime_register_module(const char *name, lua_CFunction open_fn)
{
    if (!name || !open_fn) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_module_locked) {
        ESP_LOGE(TAG, "Module registration locked (runtime already used)");
        return ESP_ERR_INVALID_STATE;
    }
    if (s_module_count >= LUA_RUNTIME_MAX_MODULES) {
        ESP_LOGE(TAG, "Too many modules (max %d)", LUA_RUNTIME_MAX_MODULES);
        return ESP_ERR_NO_MEM;
    }

    s_modules[s_module_count].name = name;
    s_modules[s_module_count].open_fn = open_fn;
    s_module_count++;
    ESP_LOGD(TAG, "Registered Lua module: %s", name);
    return ESP_OK;
}

esp_err_t lua_runtime_register_modules(const lua_runtime_module_t *modules, size_t count)
{
    esp_err_t err;

    for (size_t i = 0; i < count; i++) {
        err = lua_runtime_register_module(modules[i].name, modules[i].open_fn);
        if (err != ESP_OK) {
            return err;
        }
    }
    return ESP_OK;
}

size_t lua_runtime_get_module_count(void)
{
    return s_module_count;
}

/* ==================== 内部辅助函数 ==================== */

static void load_registered_modules(lua_State *L)
{
    for (size_t i = 0; i < s_module_count; i++) {
        if (s_modules[i].name && s_modules[i].open_fn) {
            luaL_requiref(L, s_modules[i].name, s_modules[i].open_fn, 1);
            lua_pop(L, 1);
        }
    }
}

/* print 输出捕获 */
static int lua_print_capture(lua_State *L)
{
    lua_runtime_exec_ctx_t *ctx = (lua_runtime_exec_ctx_t *)lua_touserdata(
                                      L, lua_upvalueindex(1));
    int top = lua_gettop(L);

    for (int i = 1; i <= top; i++) {
        size_t len = 0;
        const char *text = luaL_tolstring(L, i, &len);

        if (i > 1) {
            /* 多个参数用 tab 分隔 */
            if (ctx && ctx->buf && ctx->len < ctx->size - 1) {
                ctx->buf[ctx->len++] = '\t';
            }
            putchar('\t');
        }

        if (ctx && ctx->buf && ctx->len < ctx->size - 1) {
            size_t room = ctx->size - 1 - ctx->len;
            size_t copy = len < room ? len : room;
            memcpy(ctx->buf + ctx->len, text, copy);
            ctx->len += copy;
            if (copy < len) {
                ctx->truncated = true;
            }
        }

        fwrite(text, 1, len, stdout);
        lua_pop(L, 1);
    }

    if (ctx && ctx->buf && ctx->len < ctx->size - 1) {
        ctx->buf[ctx->len++] = '\n';
        ctx->buf[ctx->len] = '\0';
    }
    putchar('\n');
    fflush(stdout);
    return 0;
}

/* 超时/停止钩子 — 每 10 条指令触发一次 */
static void lua_timeout_hook(lua_State *L, lua_Debug *ar)
{
    (void)ar;
    int64_t now = esp_timer_get_time();
    lua_runtime_exec_ctx_t *ctx = NULL;

    /* 每 100 次钩子触发（约 1000 条指令）让出一次调度 */
    static int yield_counter = 0;
    if (++yield_counter >= 10) {
        yield_counter = 0;
        taskYIELD();
    }

    lua_getglobal(L, "__lua_rt_ctx");
    ctx = (lua_runtime_exec_ctx_t *)lua_touserdata(L, -1);
    lua_pop(L, 1);
    if (!ctx) return;

    if (ctx->deadline_us != 0 && now > ctx->deadline_us) {
        luaL_error(L, "execution timed out");
    }

    /* 如果执行超过 3000ms 仍未完成，主动超时以防止阻塞 TTS */
    if (ctx->start_us == 0) {
        ctx->start_us = now;
    } else if ((now - ctx->start_us) > 3000000) {
        luaL_error(L, "execution exceeded 3s limit");
    }
}

/* JSON → Lua table 递归推入 */
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

static void set_args_global(lua_State *L, const char *args_json)
{
    if (args_json && args_json[0]) {
        cJSON *root = cJSON_Parse(args_json);
        if (root) {
            push_json_value(L, root);
            cJSON_Delete(root);
        } else {
            lua_newtable(L);
        }
    } else {
        lua_newtable(L);
    }
    lua_setglobal(L, "args");
}

static void append_output(lua_runtime_exec_ctx_t *ctx, const char *text, size_t len)
{
    if (!ctx || !ctx->buf || ctx->size == 0 || !text || len == 0) return;
    if (ctx->len >= ctx->size - 1) {
        ctx->truncated = true;
        return;
    }
    size_t room = ctx->size - 1 - ctx->len;
    size_t copy = len < room ? len : room;
    memcpy(ctx->buf + ctx->len, text, copy);
    ctx->len += copy;
    ctx->buf[ctx->len] = '\0';
    if (copy < len) {
        ctx->truncated = true;
    }
}

/* ==================== 持久状态（避免反复创建销毁 Lua 状态） ==================== */

static lua_State *s_persistent_L = NULL;

esp_err_t lua_runtime_init_persistent(void)
{
    if (s_persistent_L) {
        lua_close(s_persistent_L);
    }
    s_persistent_L = lua_runtime_new_state();
    return s_persistent_L ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t lua_runtime_run_string_persistent(const char *chunk,
                                             const char *chunk_name,
                                             uint32_t timeout_ms,
                                             char *output,
                                             size_t output_size)
{
    if (!s_persistent_L) {
        /* 延迟初始化：第一次实际用到时才创建 Lua 状态 */
        s_persistent_L = lua_runtime_new_state();
    }
    if (!s_persistent_L) {
        snprintf(output, output_size, "Error: failed to create Lua state");
        return ESP_ERR_NO_MEM;
    }

    if (!output || output_size == 0) return ESP_ERR_INVALID_ARG;
    output[0] = '\0';
    if (!chunk || !chunk[0]) {
        snprintf(output, output_size, "Error: empty chunk");
        return ESP_ERR_INVALID_ARG;
    }

    /* 清除栈上残留 */
    lua_settop(s_persistent_L, 0);

    lua_runtime_exec_ctx_t ctx = {
        .buf = output,
        .size = output_size,
        .deadline_us = (timeout_ms == 0) ? 0 : esp_timer_get_time() + ((int64_t)timeout_ms * 1000),
        .start_us = 0,
    };

    lua_pushlightuserdata(s_persistent_L, &ctx);
    lua_setglobal(s_persistent_L, "__lua_rt_ctx");

    lua_pushlightuserdata(s_persistent_L, &ctx);
    lua_pushcclosure(s_persistent_L, lua_print_capture, 1);
    lua_setglobal(s_persistent_L, "print");

    lua_sethook(s_persistent_L, lua_timeout_hook, LUA_MASKCOUNT, 10);

    int status = luaL_loadstring(s_persistent_L, chunk);
    if (status != LUA_OK) {
        const char *msg = lua_tostring(s_persistent_L, -1);
        snprintf(output, output_size, "Error: %s", msg ? msg : "compile error");
        lua_close(s_persistent_L);
        s_persistent_L = NULL;
        return ESP_FAIL;
    }

    lua_newtable(s_persistent_L);
    lua_setglobal(s_persistent_L, "args");

    status = lua_pcall(s_persistent_L, 0, 0, 0);
    if (status != LUA_OK) {
        const char *msg = lua_tostring(s_persistent_L, -1);
        if (ctx.len > 0) append_output(&ctx, "\nERROR: ", 8);
        append_output(&ctx, msg ? msg : "unknown Lua error", strlen(msg ? msg : "unknown Lua error"));
        lua_close(s_persistent_L);
        s_persistent_L = NULL;
        return ESP_FAIL;
    }

    if (ctx.len == 0) append_output(&ctx, "Lua completed with no output.\n", 30);
    else if (ctx.truncated) append_output(&ctx, "\n[output truncated]\n", 19);

    lua_settop(s_persistent_L, 0);

    /* 执行完毕，释放 Lua 状态以归还堆内存（下回调用时延迟重建） */
    lua_close(s_persistent_L);
    s_persistent_L = NULL;

    return ESP_OK;
}

/* ==================== 公共 API ==================== */

static void *lua_psram_alloc(void *ud, void *ptr, size_t osize, size_t nsize)
{
    (void)ud;
    (void)osize;
    if (nsize == 0) {
        free(ptr);
        return NULL;
    }
    void *newptr = heap_caps_realloc(ptr, nsize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!newptr && nsize > 0) {
        newptr = realloc(ptr, nsize);
    }
    return newptr;
}

lua_State *lua_runtime_new_state(void)
{
    lua_State *L = lua_newstate(lua_psram_alloc, NULL, 0);
    if (!L) {
        ESP_LOGE(TAG, "lua_newstate 失败 (PSRAM 不足或分配器错误)");
        return NULL;
    }

    luaL_openlibs(L);
    s_module_locked = true;
    load_registered_modules(L);
    return L;
}

void lua_runtime_set_args(lua_State *L, const char *args_json)
{
    set_args_global(L, args_json);
}

bool lua_runtime_stop_requested(lua_State *L)
{
    if (!L) return false;
    lua_getglobal(L, "__lua_rt_ctx");
    lua_runtime_exec_ctx_t *ctx = (lua_runtime_exec_ctx_t *)lua_touserdata(L, -1);
    lua_pop(L, 1);
    /* 当前简化版不实现外部停止，只支持超时 */
    (void)ctx;
    return false;
}

esp_err_t lua_runtime_run_file(const char *path,
                               const char *args_json,
                               uint32_t timeout_ms,
                               char *output,
                               size_t output_size)
{
    struct stat st;

    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';

    if (!path || !path[0]) {
        snprintf(output, output_size, "Error: path is empty");
        return ESP_ERR_INVALID_ARG;
    }

    /* 入口喂狗 */
    // 跳过 esp_task_wdt_reset，避免在非 WatchDog 订阅的上下文中调用报错

    /* 检查文件存在性 */
    if (stat(path, &st) != 0) {
        snprintf(output, output_size, "Error: Lua script not found: %s", path);
        return ESP_ERR_NOT_FOUND;
    }
    if (st.st_size <= 0 || st.st_size > LUA_RUNTIME_MAX_SCRIPT_SIZE) {
        snprintf(output, output_size, "Error: invalid script size: %ld bytes", (long)st.st_size);
        return ESP_ERR_INVALID_SIZE;
    }

    /* 创建 Lua 状态 */
    lua_State *L = lua_runtime_new_state();
    if (!L) {
        snprintf(output, output_size, "Error: failed to create Lua state");
        return ESP_ERR_NO_MEM;
    }

    /* 设置执行上下文 */
    lua_runtime_exec_ctx_t ctx = {
        .buf = output,
        .size = output_size,
        .deadline_us = (timeout_ms == 0)
                       ? 0
                       : esp_timer_get_time() + ((int64_t)timeout_ms * 1000),
    };

    lua_pushlightuserdata(L, &ctx);
    lua_setglobal(L, "__lua_rt_ctx");

    /* 替换 print */
    lua_pushlightuserdata(L, &ctx);
    lua_pushcclosure(L, lua_print_capture, 1);
    lua_setglobal(L, "print");

    /* 设置 args */
    set_args_global(L, args_json);

    /* 设置超时钩子 */
    lua_sethook(L, lua_timeout_hook, LUA_MASKCOUNT, 10);

    /* 执行文件 */
    int status = luaL_dofile(L, path);

    if (status != LUA_OK) {
        const char *msg = lua_tostring(L, -1);
        if (ctx.len > 0) {
            append_output(&ctx, "\nERROR: ", 8);
        }
        append_output(&ctx,
                      msg ? msg : "unknown Lua error",
                      strlen(msg ? msg : "unknown Lua error"));
        lua_close(L);
        return ESP_FAIL;
    }

    if (ctx.len == 0) {
        append_output(&ctx, "Lua script completed with no output.\n", 36);
    } else if (ctx.truncated) {
        append_output(&ctx, "\n[output truncated]\n", 19);
    }

    lua_close(L);
    return ESP_OK;
}

esp_err_t lua_runtime_run_string(const char *chunk,
                                 const char *chunk_name,
                                 uint32_t timeout_ms,
                                 char *output,
                                 size_t output_size)
{
    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';

    if (!chunk || !chunk[0]) {
        snprintf(output, output_size, "Error: empty chunk");
        return ESP_ERR_INVALID_ARG;
    }

    /* 入口喂狗 */
    // 跳过 esp_task_wdt_reset，避免在非 WatchDog 订阅的上下文中调用报错

    lua_State *L = lua_runtime_new_state();
    if (!L) {
        snprintf(output, output_size, "Error: failed to create Lua state");
        return ESP_ERR_NO_MEM;
    }

    lua_runtime_exec_ctx_t ctx = {
        .buf = output,
        .size = output_size,
        .deadline_us = (timeout_ms == 0)
                       ? 0
                       : esp_timer_get_time() + ((int64_t)timeout_ms * 1000),
    };

    lua_pushlightuserdata(L, &ctx);
    lua_setglobal(L, "__lua_rt_ctx");

    lua_pushlightuserdata(L, &ctx);
    lua_pushcclosure(L, lua_print_capture, 1);
    lua_setglobal(L, "print");

    lua_sethook(L, lua_timeout_hook, LUA_MASKCOUNT, 10);

    /* chunk_name 保留在 API 中以备将来错误报告使用 */
    (void)chunk_name;

    int status = luaL_loadstring(L, chunk);
    if (status != LUA_OK) {
        const char *msg = lua_tostring(L, -1);
        snprintf(output, output_size, "Error: %s", msg ? msg : "compile error");
        lua_close(L);
        return ESP_FAIL;
    }

    /* 加载 args 为空 table（确保全局存在） */
    lua_newtable(L);
    lua_setglobal(L, "args");

    status = lua_pcall(L, 0, 0, 0);
    if (status != LUA_OK) {
        const char *msg = lua_tostring(L, -1);
        if (ctx.len > 0) {
            append_output(&ctx, "\nERROR: ", 8);
        }
        append_output(&ctx,
                      msg ? msg : "unknown Lua error",
                      strlen(msg ? msg : "unknown Lua error"));
        lua_close(L);
        return ESP_FAIL;
    }

    if (ctx.len == 0) {
        append_output(&ctx, "Lua completed with no output.\n", 30);
    } else if (ctx.truncated) {
        append_output(&ctx, "\n[output truncated]\n", 19);
    }

    lua_close(L);
    return ESP_OK;
}
