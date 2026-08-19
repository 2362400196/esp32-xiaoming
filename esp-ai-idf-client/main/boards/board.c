/**
 * board.c - 板级包核心（1000+ 板型架构）
 *
 * 通过 board_select.h 自动选择板型，集中管理初始化流程。
 * 使用驱动注册表替代 switch-case，新增显示/编解码器类型无需修改本文件。
 * 添加新板型无需修改本文件。
 */
#include "board_interface.h"
#include "board_select.h"
#include "displays/display_driver.h"
#include "displays/display_lcd.h"
#include "displays/display_uart.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "board";

// ==================== 显示驱动注册表 ====================
// 新增显示类型只需在此数组添加条目，无需修改 board_init()

typedef const display_driver_t *(*display_driver_getter_t)(void);

typedef struct {
    display_type_t        type;
    display_driver_getter_t get_driver;
    const char           *log_str;       // 日志描述
} display_registry_entry_t;

static const display_registry_entry_t s_display_registry[] = {
    { DISPLAY_TYPE_LCD_ST7789,   display_driver_lcd_get,
      "SPI LCD" },
    { DISPLAY_TYPE_LCD_ILI9341,  display_driver_lcd_get,
      "SPI LCD" },
    { DISPLAY_TYPE_OLED_SSD1306, display_driver_uart_get,
      "OLED (回退串口)" },   // TODO: 替换为 OLED 驱动
    { DISPLAY_TYPE_NONE,         display_driver_uart_get,
      "无（串口输出）" },
};
#define DISPLAY_REGISTRY_SIZE  (sizeof(s_display_registry) / sizeof(s_display_registry[0]))

// ==================== 音频编解码器信息表 ====================

typedef struct {
    audio_codec_type_t type;
    const char        *log_str;       // 日志描述
    const char        *json_str;      // JSON 标识
} audio_codec_info_t;

static const audio_codec_info_t s_audio_codec_info[] = {
    { AUDIO_CODEC_NONE,    "I2S 直连 (INMP441 + MAX98357A)",       "i2s_direct" },
    { AUDIO_CODEC_ES8388,  "ES8388 编解码器",                      "es8388"     },
    { AUDIO_CODEC_PCM5102, "PCM5102 DAC",                          "pcm5102"    },
    { AUDIO_CODEC_ES8311,  "ES8311 编解码器 + NS4150B 功放 (全双工 I2S)", "es8311" },
};
#define AUDIO_CODEC_INFO_SIZE  (sizeof(s_audio_codec_info) / sizeof(s_audio_codec_info[0]))

// ==================== 显示类型字符串表（board_get_info_json 用） ====================

static const char *const s_disp_type_strs[] = {
    [DISPLAY_TYPE_NONE]         = "none",
    [DISPLAY_TYPE_LCD_ST7789]   = "st7789",
    [DISPLAY_TYPE_LCD_ILI9341]  = "ili9341",
    [DISPLAY_TYPE_OLED_SSD1306] = "ssd1306",
};

// 板型信息 JSON 缓冲区（首次调用时生成，后续直接返回）
static char s_board_info_json[256] = {0};

// ==================== 公共 API ====================

const board_config_t *board_get_config(void)
{
    return ACTIVE_BOARD_CONFIG;
}

esp_err_t board_init(void)
{
    const board_config_t *cfg = ACTIVE_BOARD_CONFIG;
    ESP_LOGI(TAG, "初始化板级包: %s", cfg->name);
    ESP_LOGI(TAG, "  描述: %s", cfg->description);
    ESP_LOGI(TAG, "  bin_id: %s", cfg->bin_id);

    // 1. 通过注册表查找并注册显示驱动
    esp_err_t ret = ESP_ERR_NOT_FOUND;
    for (int i = 0; i < (int)DISPLAY_REGISTRY_SIZE; i++) {
        if (s_display_registry[i].type == cfg->display_type) {
            ret = display_register_driver(s_display_registry[i].get_driver());
            if (ret != ESP_OK) {
                ESP_LOGE(TAG, "注册显示驱动失败: %s", esp_err_to_name(ret));
                return ret;
            }
            ESP_LOGI(TAG, "  屏幕: %dx%d %s",
                     cfg->display_width, cfg->display_height,
                     s_display_registry[i].log_str);
            break;
        }
    }
    if (ret == ESP_ERR_NOT_FOUND) {
        ESP_LOGW(TAG, "未知显示类型 %d，回退到串口", cfg->display_type);
        ret = display_register_driver(display_driver_uart_get());
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "注册串口显示驱动失败");
            return ret;
        }
    }

    // 2. 音频编解码器信息（ES8311 的 I2C 初始化在 main.c 中完成，
    //    因为需要在 wakeup_init() 之前配置 codec 寄存器）
    for (int i = 0; i < (int)AUDIO_CODEC_INFO_SIZE; i++) {
        if (s_audio_codec_info[i].type == cfg->audio_codec) {
            ESP_LOGI(TAG, "  音频: %s", s_audio_codec_info[i].log_str);
            break;
        }
    }

    // 3. 服务模式
    if (cfg->official_service) {
        ESP_LOGI(TAG, "  服务: ESP-AI 官方服务 (node.espai.fun)");
    }
    if (cfg->emotion_builtin_only) {
        ESP_LOGI(TAG, "  表情: 编译内置资源，不从服务器下载");
    }

    // 4. 初始化扩展组件（如有）
    if (cfg->extras) {
        for (int i = 0; cfg->extras[i] != NULL; i++) {
            const board_extra_t *extra = cfg->extras[i];
            if (extra->init) {
                esp_err_t e_ret = extra->init(extra->config);
                if (e_ret != ESP_OK) {
                    ESP_LOGW(TAG, "扩展组件 '%s' 初始化失败: %s",
                             extra->type ? extra->type : "unknown",
                             esp_err_to_name(e_ret));
                } else {
                    ESP_LOGI(TAG, "  扩展组件 '%s' 初始化完成", extra->type);
                }
            }
        }
    }

    // 5. 广播初始化完成事件
    board_extra_broadcast_event(BOARD_EVENT_INIT, NULL);

    ESP_LOGI(TAG, "板级包初始化完成");
    return ESP_OK;
}

void board_deinit(void)
{
    const board_config_t *cfg = ACTIVE_BOARD_CONFIG;

    // 广播反初始化事件
    board_extra_broadcast_event(BOARD_EVENT_DEINIT, NULL);

    // 反初始化扩展组件（逆序）
    if (cfg->extras) {
        int count = 0;
        while (cfg->extras[count] != NULL) count++;
        for (int i = count - 1; i >= 0; i--) {
            const board_extra_t *extra = cfg->extras[i];
            if (extra->deinit) {
                extra->deinit();
                ESP_LOGI(TAG, "扩展组件 '%s' 已反初始化", extra->type);
            }
        }
    }

    ESP_LOGI(TAG, "板级包已反初始化");
}

const char *board_get_info_json(void)
{
    const board_config_t *cfg = ACTIVE_BOARD_CONFIG;

    // 首次调用时生成 JSON，后续直接返回缓存
    if (s_board_info_json[0] == '\0') {
        const char *disp_str = "none";
        if (cfg->display_type >= 0 &&
            cfg->display_type < (int)(sizeof(s_disp_type_strs) / sizeof(s_disp_type_strs[0])) &&
            s_disp_type_strs[cfg->display_type]) {
            disp_str = s_disp_type_strs[cfg->display_type];
        }

        const char *codec_str = "i2s_direct";
        for (int i = 0; i < (int)AUDIO_CODEC_INFO_SIZE; i++) {
            if (s_audio_codec_info[i].type == cfg->audio_codec) {
                codec_str = s_audio_codec_info[i].json_str;
                break;
            }
        }

        snprintf(s_board_info_json, sizeof(s_board_info_json),
            "{\"name\":\"%s\",\"bin_id\":\"%s\",\"display\":\"%s\",\"display_w\":%d,\"display_h\":%d,\"audio_codec\":\"%s\"}",
            cfg->name, cfg->bin_id, disp_str,
            cfg->display_width, cfg->display_height, codec_str);
    }
    return s_board_info_json;
}

// ==================== 扩展组件运行时 API ====================

esp_err_t board_extra_dispatch(const char *cmd, const char *args,
                                char *resp, size_t resp_len)
{
    const board_config_t *cfg = ACTIVE_BOARD_CONFIG;
    if (!cmd || !cfg->extras) {
        return ESP_ERR_NOT_FOUND;
    }

    for (int i = 0; cfg->extras[i] != NULL; i++) {
        const board_extra_t *extra = cfg->extras[i];
        if (extra->handle_command) {
            esp_err_t ret = extra->handle_command(cmd, args, resp, resp_len);
            if (ret == ESP_OK) {
                return ESP_OK;
            }
            // ESP_ERR_NOT_FOUND 表示此组件不处理该命令，继续尝试下一个
        }
    }

    return ESP_ERR_NOT_FOUND;
}

void board_extra_broadcast_event(board_event_t event, void *data)
{
    const board_config_t *cfg = ACTIVE_BOARD_CONFIG;
    if (!cfg->extras) {
        return;
    }

    for (int i = 0; cfg->extras[i] != NULL; i++) {
        const board_extra_t *extra = cfg->extras[i];
        if (extra->on_event) {
            extra->on_event(event, data);
        }
    }
}
