/**
 * command_registry.c - 指令注册系统实现
 *
 * 使用链表管理所有通过 REGISTER_COMMAND 宏注册的指令。
 * 注册通过 __attribute__((constructor)) 在 app_main 之前自动完成。
 */
#include "command_registry.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "cmd_registry";

// 注册表链表头（BSS 变量，在构造函数之前已清零）
//
// 线程安全约定：
//   注册（command_registry_add）通过 __attribute__((constructor)) 在 app_main
//   启动前单线程执行，此时 commands_dispatch 尚未被调用，无读写并发风险。
//   分发（commands_dispatch / commands_list）仅在 app_main 之后的运行期被调用，
//   此时注册阶段已全部结束，链表只读。
//   若后续需要在运行期动态注册指令，必须引入 portENTER_CRITICAL 锁保护链表操作。
static command_entry_t *s_head = NULL;

void command_registry_add(command_entry_t *entry)
{
    if (entry == NULL) {
        return;
    }

    // 查重：遍历链表，若该 entry 已注册则跳过，避免重复条目
    for (command_entry_t *cur = s_head; cur != NULL; cur = cur->next) {
        if (cur == entry) {
            ESP_LOGW(TAG, "指令已注册，跳过重复注册: [%s] %s",
                     entry->type, entry->description ? entry->description : "");
            return;
        }
    }

    // 头插法
    entry->next = s_head;
    s_head = entry;
}

esp_err_t commands_dispatch(const char *type, const char *command_id, cJSON *json)
{
    if (type == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    for (command_entry_t *e = s_head; e != NULL; e = e->next) {
        // 类型不匹配，跳过
        if (strcmp(e->type, type) != 0) {
            continue;
        }

        // command_id 为 NULL 表示匹配整个 type（如 emotion、hardware-fns 等）
        if (e->command_id == NULL) {
            ESP_LOGD(TAG, "分发: type=%s → %s", type, e->description);
            return e->handler(json);
        }

        // 否则需要匹配 command_id
        if (command_id != NULL && strcmp(e->command_id, command_id) == 0) {
            ESP_LOGD(TAG, "分发: type=%s cmd=%s → %s", type, command_id, e->description);
            return e->handler(json);
        }
    }

    return ESP_ERR_NOT_FOUND;
}

void commands_list(void)
{
    int count = 0;
    ESP_LOGI(TAG, "========== 已注册指令列表 ==========");
    for (command_entry_t *e = s_head; e != NULL; e = e->next) {
        count++;
        if (e->command_id) {
            ESP_LOGI(TAG, "  %2d. [%s] %s - %s", count, e->type, e->command_id, e->description);
        } else {
            ESP_LOGI(TAG, "  %2d. [%s] * - %s", count, e->type, e->description);
        }
    }
    ESP_LOGI(TAG, "========== 共 %d 条指令 ==========", count);
}
