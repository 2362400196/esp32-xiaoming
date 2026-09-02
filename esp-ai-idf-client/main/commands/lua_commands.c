/**
 * lua_commands.c - Lua 脚本执行指令
 *
 * 处理服务端下发的指令：
 *   - execute_lua: 执行 Lua 代码字符串
 *
 * 移植自 Arduino 版本的 command_handler.cpp
 */
#include "command_registry.h"
#include "config.h"
#include "esp_log.h"
#include "cJSON.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "lua_runtime.h"
#include "lua_module_delay.h"
#include "lua_module_system.h"
#include "lua_module_json.h"
#include "lua_module_gpio.h"
#include "lua_module_led.h"
#include "lua_module_environmental_sensor.h"
#include "lua_driver_adc.h"
#include "lua_module_ledc.h"
#include "lua_module_storage.h"
#include "lua_driver_i2c.h"
#include "lua_module_button.h"
#include "lua_driver_uart.h"
#include "lua_driver_pcnt.h"
#include "lua_driver_touch.h"
#include "lua_driver_mcpwm.h"
#include "lua_driver_rmt.h"
#include "lua_module_http.h"
#include "lua_module_sci.h"
#include "lua_module_thread.h"

// lua_lvgl 声明在 lua_runtime.h 中已有 lua_lvgl_reset()
extern int luaopen_lvgl(lua_State *L);

// 用于上报 Lua 执行结果到服务器
extern esp_err_t websocket_send_text(const char *text);

static const char *TAG = "cmd_lua";

// 执行队列 — 防止 Lua 阻塞 WebSocket 事件回调
#define LUA_TASK_STACK_SIZE 16384
static TaskHandle_t s_lua_task = NULL;
static QueueHandle_t s_lua_queue = NULL;

typedef struct {
    char code[4096];
    bool is_stop;  // true = 仅重置 LVGL，false = 执行 Lua 代码
    bool is_file;  // true = code 字段为文件路径，执行文件而非代码字符串
} lua_exec_req_t;

// Lua 执行 task
static void lua_exec_task(void *arg)
{
    lua_exec_req_t req;
    char output[4096];

    while (1) {
        if (xQueueReceive(s_lua_queue, &req, portMAX_DELAY) == pdTRUE) {
            if (req.is_stop) {
                ESP_LOGI(TAG, "停止 Lua，重置 LVGL 对象");
                lua_lvgl_reset();
                continue;
            }
            esp_err_t err;
            // 置执行标志：脚本执行中禁止 lua_lvgl_reset 清理对象
            // （表情渲染等可能并发触发 reset，删除执行中的对象会导致崩溃）
            lua_lvgl_set_executing(true);
            if (req.is_file) {
                ESP_LOGI(TAG, "执行 Lua 文件 (异步): %s", req.code);
                err = lua_runtime_run_file(req.code, NULL, 5000, output, sizeof(output));
            } else {
                ESP_LOGI(TAG, "执行 Lua (异步): %s", req.code);
                err = lua_runtime_run_string(req.code, "execute_lua", 5000, output, sizeof(output));
            }
            lua_lvgl_set_executing(false);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "Lua 执行失败: %s", output);
                // 上报错误到服务器（堆分配，避免栈溢出）
                char *err_report = malloc(4608);
                if (err_report) {
                    snprintf(err_report, 4608,
                             "{\"type\":\"instruct\",\"command_id\":\"lua_result\",\"data\":\"error: %.4000s\"}",
                             output);
                    websocket_send_text(err_report);
                    free(err_report);
                }
            } else {
                ESP_LOGI(TAG, "Lua 执行成功: %s", output);
                // 对输出做 JSON 转义（换行/引号/反斜线等），堆分配避免栈溢出
                // output 最大 4096，每个字符最坏转义为 2 字节，故 escaped 需 8192
                char *escaped = malloc(8192);
                if (escaped) {
                    size_t j = 0;
                    for (size_t i = 0; output[i] && j < 8190; i++) {
                        char c = output[i];
                        switch (c) {
                            case '\n': escaped[j++] = '\\'; escaped[j++] = 'n'; break;
                            case '\r': escaped[j++] = '\\'; escaped[j++] = 'r'; break;
                            case '\t': escaped[j++] = '\\'; escaped[j++] = 't'; break;
                            case '"':  escaped[j++] = '\\'; escaped[j++] = '"'; break;
                            case '\\': escaped[j++] = '\\'; escaped[j++] = '\\'; break;
                            default:   escaped[j++] = c; break;
                        }
                    }
                    escaped[j] = '\0';
                    // 上报执行结果到服务器（堆分配，避免栈溢出）
                    char *result_report = malloc(4608);
                    if (result_report) {
                        int len = snprintf(result_report, 4608,
                                 "{\"type\":\"instruct\",\"command_id\":\"lua_result\",\"data\":\"%.4000s\"}",
                                 escaped);
                        ESP_LOGI(TAG, "发送 lua_result (%d bytes)", len);
                        esp_err_t send_err = websocket_send_text(result_report);
                        if (send_err != ESP_OK) {
                            ESP_LOGE(TAG, "发送 lua_result 失败: %s", esp_err_to_name(send_err));
                        }
                        free(result_report);
                    }
                    free(escaped);
                }
            }
        }
    }
    vTaskDelete(NULL);
}

// 注册所有 Lua 扩展模块
static void register_lua_modules(void)
{
    lua_runtime_register_module("delay",  luaopen_delay);
    lua_runtime_register_module("system", luaopen_system);
    lua_runtime_register_module("json",   luaopen_json);
    lua_runtime_register_module("gpio",   luaopen_gpio);
    lua_runtime_register_module("led",    luaopen_led);
    lua_runtime_register_module("lvgl",   luaopen_lvgl);
    lua_runtime_register_module("environmental_sensor", luaopen_environmental_sensor);
    lua_runtime_register_module("adc",    luaopen_adc);
    lua_runtime_register_module("ledc",   luaopen_ledc);
    lua_runtime_register_module("storage", luaopen_storage);
    lua_runtime_register_module("i2c",    luaopen_i2c);
    lua_runtime_register_module("button", luaopen_button);
    lua_runtime_register_module("uart",   luaopen_uart);
    lua_runtime_register_module("pcnt",   luaopen_pcnt);
    lua_runtime_register_module("rmt",    luaopen_rmt);
    lua_runtime_register_module("http",   luaopen_http);
    lua_runtime_register_module("sci",    luaopen_sci);
    lua_runtime_register_module("thread", luaopen_thread);
#if CONFIG_IDF_TARGET_ESP32 || CONFIG_IDF_TARGET_ESP32S2 || CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C2 || CONFIG_IDF_TARGET_ESP32C6
    lua_runtime_register_module("touch",  luaopen_touch);
#endif
#if CONFIG_IDF_TARGET_ESP32 || CONFIG_IDF_TARGET_ESP32S2 || CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C6 || CONFIG_IDF_TARGET_ESP32P4
    lua_runtime_register_module("mcpwm",  luaopen_mcpwm);
#endif
    ESP_LOGI(TAG, "Lua 模块注册完成: delay, system, json, gpio, led, lvgl, environmental_sensor, adc, ledc, storage, i2c, button, uart, pcnt, rmt, http, sci, thread, touch, mcpwm");
}

// execute_lua: 执行 Lua 代码（异步到独立 task）
static esp_err_t cmd_execute_lua(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");

    if (!data || !cJSON_IsString(data)) {
        ESP_LOGW(TAG, "execute_lua data 字段缺失或非字符串");
        return ESP_OK;
    }

    const char *lua_code = data->valuestring;
    if (!s_lua_queue) {
        ESP_LOGW(TAG, "Lua 队列未初始化");
        return ESP_OK;
    }

    lua_exec_req_t req = {0};
    if (strlen(lua_code) >= sizeof(req.code)) {
        ESP_LOGW(TAG, "Lua 代码过长 (%zu 字节)，将被截断到 %zu 字节",
                 strlen(lua_code), sizeof(req.code) - 1);
    }
    strncpy(req.code, lua_code, sizeof(req.code) - 1);
    req.code[sizeof(req.code) - 1] = '\0';

    if (xQueueSend(s_lua_queue, &req, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGW(TAG, "Lua 队列已满，丢弃请求");
    }

    return ESP_OK;
}

// execute_lua_file: 执行 Lua 文件（异步到独立 task，避免阻塞 WebSocket 事件回调）
static esp_err_t cmd_execute_lua_file(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");

    if (!data || !cJSON_IsString(data)) {
        ESP_LOGW(TAG, "execute_lua_file data 字段缺失或非字符串");
        return ESP_OK;
    }

    const char *path = data->valuestring;

    if (!s_lua_queue) {
        ESP_LOGW(TAG, "Lua 队列未初始化");
        return ESP_OK;
    }

    if (strlen(path) >= 4096) {
        ESP_LOGW(TAG, "Lua 文件路径过长 (%zu 字节)，无法入队", strlen(path));
        return ESP_OK;
    }

    lua_exec_req_t req = {0};
    strncpy(req.code, path, sizeof(req.code) - 1);
    req.code[sizeof(req.code) - 1] = '\0';
    req.is_file = true;

    if (xQueueSend(s_lua_queue, &req, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGW(TAG, "Lua 队列已满，丢弃 execute_lua_file 请求");
    } else {
        ESP_LOGI(TAG, "execute_lua_file 已入队: %s", path);
    }

    return ESP_OK;
}

// stop_lua: 停止 Lua 执行，直接清除屏幕上 Lua 绘制的内容
// 不通过队列发送（避免被正在执行的 Lua 脚本阻塞），直接调用 lua_lvgl_reset
static esp_err_t cmd_stop_lua(cJSON *json)
{
    ESP_LOGI(TAG, "直接清除 Lua LVGL 对象");
    lua_lvgl_reset();
    return ESP_OK;
}

void register_lua_commands(void)
{
    // 首次使用时注册模块
    register_lua_modules();

    // 创建 Lua 执行队列和 task，避免阻塞 WebSocket 事件回调
    s_lua_queue = xQueueCreate(4, sizeof(lua_exec_req_t));
    if (s_lua_queue) {
        xTaskCreatePinnedToCore(lua_exec_task, "lua_exec", LUA_TASK_STACK_SIZE, NULL, 3, &s_lua_task, 0);
    }

    static command_entry_t cmds[] = {
        {
            .type = "instruct", .command_id = "execute_lua",
            .handler = cmd_execute_lua, .description = "执行 Lua 代码"
        },
        {
            .type = "instruct", .command_id = "execute_lua_file",
            .handler = cmd_execute_lua_file, .description = "执行 Lua 文件"
        },
        {
            .type = "instruct", .command_id = "stop_lua",
            .handler = cmd_stop_lua, .description = "停止 Lua 执行"
        },
    };
    for (int i = 0; i < 3; i++) {
        command_registry_add(&cmds[i]);
    }
    ESP_LOGI(TAG, "Lua 指令注册完成: execute_lua, execute_lua_file, stop_lua");
}
