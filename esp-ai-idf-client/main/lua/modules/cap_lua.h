/*
 * cap_lua.h - ESP-Claw 兼容层
 * 为移植的 Lua 模块提供 cap_lua 基础设施
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "lua.h"
#include "lauxlib.h"

#ifdef __cplusplus
extern "C" {
#endif

// 模块注册辅助（简化版，不依赖 claw_core）
typedef struct {
    const char *name;
    lua_CFunction open_fn;
} cap_lua_module_t;

// 简单的 luaopen 包装
static inline int cap_lua_open_module(lua_State *L, const char *name, lua_CFunction open_fn)
{
    luaL_requiref(L, name, open_fn, 1);
    lua_pop(L, 1);
    return 0;
}

// 线程/任务相关类型（lua_module_thread 需要）
#define CAP_LUA_JOB_NAME_MAX       32
#define CAP_LUA_JOB_EXCLUSIVE_MAX  32
#define CAP_LUA_JOB_PATH_MAX       192
#define CAP_LUA_JOB_ID_LEN         9

typedef enum {
    CAP_LUA_JOB_QUEUED = 0,
    CAP_LUA_JOB_RUNNING,
    CAP_LUA_JOB_DONE,
    CAP_LUA_JOB_FAILED,
    CAP_LUA_JOB_TIMEOUT,
    CAP_LUA_JOB_STOPPED,
} cap_lua_job_status_t;

typedef enum {
    CAP_LUA_JOB_EVENT_CREATED = 0,
    CAP_LUA_JOB_EVENT_RUNNING,
    CAP_LUA_JOB_EVENT_STOP_REQUESTED,
    CAP_LUA_JOB_EVENT_TERMINAL,
} cap_lua_job_event_type_t;

typedef struct {
    cap_lua_job_event_type_t type;
    cap_lua_job_status_t status;
    char job_id[CAP_LUA_JOB_ID_LEN];
    char name[CAP_LUA_JOB_NAME_MAX];
    char exclusive[CAP_LUA_JOB_EXCLUSIVE_MAX];
    char path[CAP_LUA_JOB_PATH_MAX];
} cap_lua_job_event_t;

typedef void (*cap_lua_job_event_cb_t)(const cap_lua_job_event_t *event, void *user_ctx);

/* 兼容桩：检查 Lua 运行时是否被请求停止 */
static inline bool cap_lua_runtime_stop_requested(lua_State *L)
{
    (void)L;
    return false;
}

/* 兼容桩：注册模块（实际注册在 lua_commands.c 中完成） */
static inline esp_err_t cap_lua_register_module(const char *name, lua_CFunction open_fn)
{
    (void)name;
    (void)open_fn;
    return ESP_OK;
}

/* ==================== 作业管理（cap_lua_jobs.c） ==================== */

/**
 * @brief 同步执行 Lua 脚本文件（包装 lua_runtime_run_file）
 */
esp_err_t cap_lua_run_script(const char *path,
                             const char *args_json,
                             uint32_t timeout_ms,
                             char *output,
                             size_t output_size);

/**
 * @brief 异步执行 Lua 脚本文件（FreeRTOS 任务），成功时 output 返回作业 ID
 * @param name      作业名（可为 NULL，用于 list/get/stop 定位）
 * @param exclusive 互斥键（可为 NULL，同键旧作业会被停止）
 * @param replace   为 true 时替换同名旧作业
 */
esp_err_t cap_lua_run_script_async(const char *path,
                                   const char *args_json,
                                   uint32_t timeout_ms,
                                   const char *name,
                                   const char *exclusive,
                                   bool replace,
                                   char *output,
                                   size_t output_size);

/**
 * @brief 列出作业，output 返回 JSON 数组；status 非空时按状态过滤
 */
esp_err_t cap_lua_list_jobs(const char *status, char *output, size_t output_size);

/**
 * @brief 查询单个作业，output 返回 JSON 对象（含 output 字段）
 */
esp_err_t cap_lua_get_job(const char *id_or_name, char *output, size_t output_size);

/**
 * @brief 停止作业（标记停止并等待其自行结束，最长 wait_ms）
 */
esp_err_t cap_lua_stop_job(const char *id_or_name, uint32_t wait_ms, char *output, size_t output_size);

#ifdef __cplusplus
}
#endif
