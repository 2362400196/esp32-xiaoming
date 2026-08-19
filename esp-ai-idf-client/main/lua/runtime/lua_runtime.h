/**
 * lua_runtime.h
 * Lua 脚本运行时引擎 — 模块注册、文件执行、超时控制、输出捕获
 * 
 * 用法：
 *   1. 应用启动时调用 lua_runtime_init() 初始化
 *   2. 注册模块：lua_runtime_register_module("delay", luaopen_delay)
 *   3. 执行脚本：lua_runtime_run_file("/spiffs/scripts/test.lua", ...)
 *
 * 从 esp-claw cap_lua 移植，适配 Arduino/PlatformIO 环境
 */
#ifndef LUA_RUNTIME_H
#define LUA_RUNTIME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "lua.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ==================== 模块注册 ==================== */

typedef struct {
    const char *name;
    lua_CFunction open_fn;
} lua_runtime_module_t;

/**
 * @brief 注册一个 Lua 模块（最多 LUA_RUNTIME_MAX_MODULES 个）
 * @param name    Lua 中的模块名（require 时使用的名字）
 * @param open_fn luaopen_xxx 函数
 */
esp_err_t lua_runtime_register_module(const char *name, lua_CFunction open_fn);

/**
 * @brief 批量注册模块
 */
esp_err_t lua_runtime_register_modules(const lua_runtime_module_t *modules, size_t count);

/**
 * @brief 获取已注册模块数量
 */
size_t lua_runtime_get_module_count(void);

/* ==================== 运行时执行 ==================== */

/**
 * @brief 同步执行一个 .lua 文件
 * 
 * @param path        Lua 脚本绝对路径（如 "/spiffs/scripts/test.lua"）
 * @param args_json   脚本参数 JSON 字符串（可为 NULL）
 * @param timeout_ms  超时毫秒（0 = 不设截止时间）
 * @param output      输出缓冲区
 * @param output_size 输出缓冲区大小
 * @return esp_err_t  ESP_OK 成功，否则失败信息写入 output
 */
esp_err_t lua_runtime_run_file(const char *path,
                               const char *args_json,
                               uint32_t timeout_ms,
                               char *output,
                               size_t output_size);

/**
 * @brief 执行 Lua 代码字符串
 * 
 * @param chunk       Lua 代码
 * @param chunk_name  代码块名称（用于错误报告）
 * @param timeout_ms  超时毫秒（0 = 不设截止时间）
 * @param output      输出缓冲区
 * @param output_size 输出缓冲区大小
 * @return esp_err_t  ESP_OK 成功
 */
esp_err_t lua_runtime_run_string(const char *chunk,
                                 const char *chunk_name,
                                 uint32_t timeout_ms,
                                 char *output,
                                 size_t output_size);

/**
 * @brief 创建一个预配置的 Lua 状态（已打开标准库 + 注册模块）
 *        调用者负责 lua_close()
 */
lua_State *lua_runtime_new_state(void);

/**
 * @brief 向 Lua 状态中设置 args 全局变量（JSON 字符串）
 */
void lua_runtime_set_args(lua_State *L, const char *args_json);

/**
 * @brief 检查当前执行是否被请求停止（在钩子中使用）
 */
bool lua_runtime_stop_requested(lua_State *L);

/**
 * @brief 初始化持久 Lua 状态（只创建一次，避免反复创建销毁）
 */
esp_err_t lua_runtime_init_persistent(void);

/**
 * @brief 在持久 Lua 状态中执行代码（避免每次创建新状态的堆开销）
 */
esp_err_t lua_runtime_run_string_persistent(const char *chunk,
                                            const char *chunk_name,
                                            uint32_t timeout_ms,
                                            char *output,
                                            size_t output_size);

/**
 * @brief 删除所有 Lua 创建的 LVGL 对象，恢复 EEUI 正常显示
 */
void lua_lvgl_reset(void);

/**
 * @brief 设置 Lua 脚本执行标志（执行中禁止 reset 清理对象，竞态保护）
 * @param executing true=脚本执行中
 */
void lua_lvgl_set_executing(bool executing);

#ifdef __cplusplus
}
#endif

#endif // LUA_RUNTIME_H
