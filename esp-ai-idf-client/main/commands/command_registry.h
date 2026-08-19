#ifndef COMMAND_REGISTRY_H
#define COMMAND_REGISTRY_H

#include "esp_err.h"
#include "cJSON.h"

#ifdef __cplusplus
extern "C" {
#endif

// 指令条目结构体
typedef struct command_entry command_entry_t;
struct command_entry {
    const char *type;                    // 指令类型（如 "instruct"）
    const char *command_id;              // 指令 ID（如 "on_iat_cb"）
    esp_err_t (*handler)(cJSON *json);   // 处理函数
    const char *description;             // 描述
    command_entry_t *next;               // 链表指针
};

// 注册指令宏（兼容旧代码，在 ESP-IDF 静态库中可能无效，建议使用显式注册）
#define REGISTER_COMMAND(type_, id_, handler_, desc_) \
    static command_entry_t CONCAT(__cmd_, __LINE__) __attribute__((section(".commands"))) = { \
        .type = type_, .command_id = id_, .handler = handler_, .description = desc_ \
    }; \
    __attribute__((constructor)) static void CONCAT(__reg_, __LINE__)() { \
        command_registry_add(&CONCAT(__cmd_, __LINE__)); \
    }

// CONCAT 辅助宏
#define CONCAT(a, b) CONCAT_INNER(a, b)
#define CONCAT_INNER(a, b) a ## b

/**
 * 列出所有已注册指令（调试用）
 */
void commands_list(void);

/**
 * 注册回调指令（在 main.c 初始化时调用）
 */
void register_callback_commands(void);

/**
 * 注册显示指令（在 main.c 初始化时调用）
 */
void register_display_commands(void);
void display_restore_rotation(void);
void display_apply_rotation(int angle);

/**
 * 重置 LLM 文本缓存（新对话开始 / on_iat_cb 时调用）
 */
void callback_reset_llm_text(void);

/**
 * 获取 LLM 文本缓冲区指针（供 eeui_port 渲染循环使用）
 * 注意：返回的是内部缓冲区指针，调用方应在持有 s_llm_mutex 时使用，
 * 或使用 callback_copy_llm_text() 获取线程安全的拷贝。
 */
const char *callback_get_llm_text(void);

/**
 * 线程安全地拷贝 LLM 文本到调用方提供的缓冲区
 */
bool callback_copy_llm_text(char *buf, size_t buf_size);

/**
 * 根据 command_id 和 type 分发指令
 */
esp_err_t commands_dispatch(const char *type, const char *command_id, cJSON *json);

/**
 * 注册指令
 */
void command_registry_add(command_entry_t *entry);

#ifdef __cplusplus
}
#endif

#endif
