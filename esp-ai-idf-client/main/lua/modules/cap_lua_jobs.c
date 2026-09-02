/*
 * cap_lua_jobs.c - thread 模块作业管理实现
 *
 * 为移植的 thread Lua 模块补齐 cap_lua_* 作业接口：
 *   - cap_lua_run_script       同步执行（包装 lua_runtime_run_file）
 *   - cap_lua_run_script_async 异步执行（FreeRTOS 任务 + 作业注册表）
 *   - cap_lua_list_jobs / get_job / stop_job
 *
 * 注意：底层 lua_runtime 每次执行创建独立 Lua 状态，可安全并发；
 * 但运行时带 3 秒硬超时，异步作业最长运行 3 秒。
 */
#include "cap_lua.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lua_runtime.h"

#define CAP_LUA_JOBS_MAX        4
#define CAP_LUA_JOB_STACK_SIZE  8192
#define CAP_LUA_JOB_OUTPUT_SIZE 2048
#define CAP_LUA_JOB_ID_PREFIX   "JOB"

static const char *TAG = "cap_lua_jobs";

typedef struct {
    bool in_use;
    bool stop_requested;
    char id[CAP_LUA_JOB_ID_LEN];
    char name[CAP_LUA_JOB_NAME_MAX];
    char exclusive[CAP_LUA_JOB_EXCLUSIVE_MAX];
    char path[CAP_LUA_JOB_PATH_MAX];
    cap_lua_job_status_t status;
    TaskHandle_t task;
    uint32_t timeout_ms;
    char *args_json;
    char output[CAP_LUA_JOB_OUTPUT_SIZE];
} cap_lua_job_t;

static cap_lua_job_t s_jobs[CAP_LUA_JOBS_MAX];
static SemaphoreHandle_t s_jobs_mutex;
static uint32_t s_job_seq = 0;

static const char *cap_lua_job_status_str(cap_lua_job_status_t status)
{
    switch (status) {
    case CAP_LUA_JOB_QUEUED:  return "queued";
    case CAP_LUA_JOB_RUNNING: return "running";
    case CAP_LUA_JOB_DONE:    return "done";
    case CAP_LUA_JOB_FAILED:  return "failed";
    case CAP_LUA_JOB_TIMEOUT: return "timeout";
    case CAP_LUA_JOB_STOPPED: return "stopped";
    default:                  return "unknown";
    }
}

static void cap_lua_jobs_lock(void)
{
    if (!s_jobs_mutex) {
        s_jobs_mutex = xSemaphoreCreateMutex();
    }
    if (s_jobs_mutex) {
        xSemaphoreTake(s_jobs_mutex, portMAX_DELAY);
    }
}

static void cap_lua_jobs_unlock(void)
{
    if (s_jobs_mutex) {
        xSemaphoreGive(s_jobs_mutex);
    }
}

/* 查找作业；已请求停止的作业不参与匹配（replace 后旧作业让位给新作业） */
static cap_lua_job_t *cap_lua_job_find(const char *id_or_name)
{
    for (int i = 0; i < CAP_LUA_JOBS_MAX; i++) {
        if (!s_jobs[i].in_use || s_jobs[i].stop_requested) {
            continue;
        }
        if (strcmp(s_jobs[i].id, id_or_name) == 0 ||
            (s_jobs[i].name[0] && strcmp(s_jobs[i].name, id_or_name) == 0)) {
            return &s_jobs[i];
        }
    }
    return NULL;
}

static void cap_lua_job_request_stop(cap_lua_job_t *job)
{
    job->stop_requested = true;
    job->status = CAP_LUA_JOB_STOPPED;
}

static void cap_lua_job_task(void *arg)
{
    cap_lua_job_t *job = (cap_lua_job_t *)arg;
    esp_err_t err;

    if (job->stop_requested) {
        job->status = CAP_LUA_JOB_STOPPED;
    } else {
        job->status = CAP_LUA_JOB_RUNNING;
        err = lua_runtime_run_file(job->path,
                                   job->args_json,
                                   job->timeout_ms,
                                   job->output,
                                   sizeof(job->output));

        if (job->stop_requested) {
            job->status = CAP_LUA_JOB_STOPPED;
        } else if (err == ESP_OK) {
            job->status = CAP_LUA_JOB_DONE;
        } else {
            job->status = CAP_LUA_JOB_FAILED;
        }
    }

    free(job->args_json);
    job->args_json = NULL;
    job->task = NULL;
    vTaskDelete(NULL);
}

esp_err_t cap_lua_run_script(const char *path,
                             const char *args_json,
                             uint32_t timeout_ms,
                             char *output,
                             size_t output_size)
{
    return lua_runtime_run_file(path, args_json, timeout_ms, output, output_size);
}

esp_err_t cap_lua_run_script_async(const char *path,
                                   const char *args_json,
                                   uint32_t timeout_ms,
                                   const char *name,
                                   const char *exclusive,
                                   bool replace,
                                   char *output,
                                   size_t output_size)
{
    cap_lua_job_t *job = NULL;
    int slot = -1;

    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';
    if (!path || !path[0]) {
        snprintf(output, output_size, "Error: path is empty");
        return ESP_ERR_INVALID_ARG;
    }

    cap_lua_jobs_lock();

    /* replace：停止同名旧作业（不复用其槽位，避免旧任务仍在运行破坏新作业） */
    if (replace && name && name[0]) {
        cap_lua_job_t *existing = cap_lua_job_find(name);
        if (existing) {
            cap_lua_job_request_stop(existing);
        }
    }

    /* exclusive：停掉同互斥键的其他作业 */
    if (exclusive && exclusive[0]) {
        for (int i = 0; i < CAP_LUA_JOBS_MAX; i++) {
            if (s_jobs[i].in_use && !s_jobs[i].stop_requested &&
                strcmp(s_jobs[i].exclusive, exclusive) == 0) {
                cap_lua_job_request_stop(&s_jobs[i]);
            }
        }
    }

    /* 找空闲槽位；没有则回收一个已结束（任务已退出）的槽位 */
    for (int i = 0; i < CAP_LUA_JOBS_MAX; i++) {
        if (!s_jobs[i].in_use) {
            slot = i;
            break;
        }
    }
    if (slot < 0) {
        for (int i = 0; i < CAP_LUA_JOBS_MAX; i++) {
            if (s_jobs[i].task == NULL) {
                slot = i;
                break;
            }
        }
    }
    if (slot < 0) {
        cap_lua_jobs_unlock();
        snprintf(output, output_size, "Error: too many concurrent jobs (max %d)", CAP_LUA_JOBS_MAX);
        return ESP_ERR_NO_MEM;
    }

    job = &s_jobs[slot];
    memset(job, 0, sizeof(*job));
    job->in_use = true;
    job->status = CAP_LUA_JOB_QUEUED;
    job->timeout_ms = timeout_ms;
    snprintf(job->id, sizeof(job->id), "%s%04u", CAP_LUA_JOB_ID_PREFIX, (unsigned)(++s_job_seq % 10000));
    strlcpy(job->path, path, sizeof(job->path));
    if (name && name[0]) {
        strlcpy(job->name, name, sizeof(job->name));
    }
    if (exclusive && exclusive[0]) {
        strlcpy(job->exclusive, exclusive, sizeof(job->exclusive));
    }
    if (args_json && args_json[0]) {
        job->args_json = strdup(args_json);
    }

    BaseType_t ok = xTaskCreate(cap_lua_job_task, "lua_job", CAP_LUA_JOB_STACK_SIZE,
                                job, tskIDLE_PRIORITY + 2, &job->task);
    if (ok != pdPASS) {
        free(job->args_json);
        job->args_json = NULL;
        memset(job, 0, sizeof(*job));
        cap_lua_jobs_unlock();
        snprintf(output, output_size, "Error: failed to create job task");
        return ESP_ERR_NO_MEM;
    }

    snprintf(output, output_size, "%s", job->id);
    cap_lua_jobs_unlock();
    return ESP_OK;
}

esp_err_t cap_lua_list_jobs(const char *status, char *output, size_t output_size)
{
    cJSON *root = cJSON_CreateArray();

    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';
    if (!root) {
        return ESP_ERR_NO_MEM;
    }

    cap_lua_jobs_lock();
    for (int i = 0; i < CAP_LUA_JOBS_MAX; i++) {
        cap_lua_job_t *job = &s_jobs[i];

        if (!job->in_use) {
            continue;
        }
        if (status && status[0] && strcmp(status, cap_lua_job_status_str(job->status)) != 0) {
            continue;
        }

        cJSON *item = cJSON_CreateObject();
        if (!item) {
            continue;
        }
        cJSON_AddStringToObject(item, "id", job->id);
        cJSON_AddStringToObject(item, "name", job->name);
        cJSON_AddStringToObject(item, "exclusive", job->exclusive);
        cJSON_AddStringToObject(item, "path", job->path);
        cJSON_AddStringToObject(item, "status", cap_lua_job_status_str(job->status));
        cJSON_AddItemToArray(root, item);
    }
    cap_lua_jobs_unlock();

    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!text) {
        return ESP_ERR_NO_MEM;
    }
    strlcpy(output, text, output_size);
    free(text);
    return ESP_OK;
}

esp_err_t cap_lua_get_job(const char *id_or_name, char *output, size_t output_size)
{
    cJSON *item = NULL;
    cap_lua_job_t *job = NULL;

    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';
    if (!id_or_name || !id_or_name[0]) {
        snprintf(output, output_size, "Error: job id or name required");
        return ESP_ERR_INVALID_ARG;
    }

    cap_lua_jobs_lock();
    job = cap_lua_job_find(id_or_name);
    if (job) {
        item = cJSON_CreateObject();
        if (item) {
            cJSON_AddStringToObject(item, "id", job->id);
            cJSON_AddStringToObject(item, "name", job->name);
            cJSON_AddStringToObject(item, "exclusive", job->exclusive);
            cJSON_AddStringToObject(item, "path", job->path);
            cJSON_AddStringToObject(item, "status", cap_lua_job_status_str(job->status));
            cJSON_AddStringToObject(item, "output", job->output);
        }
    }
    cap_lua_jobs_unlock();

    if (!job) {
        snprintf(output, output_size, "Error: job not found: %s", id_or_name);
        return ESP_ERR_NOT_FOUND;
    }
    if (!item) {
        return ESP_ERR_NO_MEM;
    }

    char *text = cJSON_PrintUnformatted(item);
    cJSON_Delete(item);
    if (!text) {
        return ESP_ERR_NO_MEM;
    }
    strlcpy(output, text, output_size);
    free(text);
    return ESP_OK;
}

esp_err_t cap_lua_stop_job(const char *id_or_name, uint32_t wait_ms, char *output, size_t output_size)
{
    TaskHandle_t task = NULL;

    if (!output || output_size == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    output[0] = '\0';
    if (!id_or_name || !id_or_name[0]) {
        snprintf(output, output_size, "Error: job id or name required");
        return ESP_ERR_INVALID_ARG;
    }

    cap_lua_jobs_lock();
    cap_lua_job_t *job = cap_lua_job_find(id_or_name);
    if (!job) {
        cap_lua_jobs_unlock();
        snprintf(output, output_size, "Error: job not found: %s", id_or_name);
        return ESP_ERR_NOT_FOUND;
    }
    cap_lua_job_request_stop(job);
    task = job->task;
    cap_lua_jobs_unlock();

    /* 运行时无法中断脚本，只能等待其自行结束（受 3 秒硬超时约束） */
    if (task && wait_ms > 0) {
        uint32_t waited = 0;
        while (waited < wait_ms) {
            vTaskDelay(pdMS_TO_TICKS(50));
            waited += 50;
            cap_lua_jobs_lock();
            bool still_running = job->in_use && job->task != NULL;
            cap_lua_jobs_unlock();
            if (!still_running) {
                break;
            }
        }
    }

    snprintf(output, output_size, "stopped: %s", id_or_name);
    return ESP_OK;
}
