/**
 * display_commands.c - 显示相关指令
 *
 * 从 websocket.c 迁移的指令:
 *   - set_brightness: 设置屏幕亮度（0-100）
 *   - refresh_emo: 刷新表情包（服务端切换表情包后通知设备重新下载）
 *
 * 注意: 需要板型配置了背光引脚(display_bl >= 0)才能生效
 */
#include "command_registry.h"
#include "eeui_port.h"
#include "gif_downloader.h"
#include "config.h"
#include "esp_log.h"
#include <stdlib.h>
#include <string.h>
#include "lvgl.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_lcd_panel_io.h"
#include "nvs_flash.h"
#include "nvs.h"

static const char *TAG = "cmd_display";
static const char *NVS_NAMESPACE = "esp-ai-kv";
static const char *NVS_KEY_ROTATION = "display_rot";

// ==================== 屏幕旋转 ====================
void display_apply_rotation(int angle)
{
    if (angle < 0) angle = 0;
    if (angle > 270) angle = 270;
    angle = (angle / 90) * 90;

    // 只通过 LCD 硬件 MADCTL 寄存器旋转，LVGL 保持 0°
    uint8_t madctl;
    switch (angle) {
        case 90:  madctl = 0x60; break;  // MV=1, MX=1
        case 180: madctl = 0xC0; break;  // MX=1, MY=1
        case 270: madctl = 0xA0; break;  // MV=1, MY=1
        default:  madctl = 0x00;
    }

    esp_lcd_panel_io_handle_t io = (esp_lcd_panel_io_handle_t)eeui_port_get_panel_io();
    lv_display_t *disp = (lv_display_t *)eeui_port_get_display();

    // SPI 寄存器操作与 LVGL 刷新共享同一 SPI 总线，需纳入 LVGL 锁保护范围，
    // 防止与 LVGL 渲染任务的 SPI 传输竞态
    if (eeui_port_lvgl_lock(pdMS_TO_TICKS(200))) {
        if (io) {
            // 重新初始化 LCD 控制器，确保 MADCTL 写入生效
            // 某些 ST7789 在多角度切换后需要重新 init
            esp_err_t ret1 = esp_lcd_panel_io_tx_param(io, 0x11, NULL, 0);  // SLPOUT
            if (ret1 != ESP_OK) {
                ESP_LOGW(TAG, "SLPOUT 命令发送失败: %s", esp_err_to_name(ret1));
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            esp_err_t ret2 = esp_lcd_panel_io_tx_param(io, 0x36, (uint8_t[]){madctl}, 1);
            if (ret2 != ESP_OK) {
                ESP_LOGW(TAG, "MADCTL 命令发送失败: %s", esp_err_to_name(ret2));
            }
            vTaskDelay(pdMS_TO_TICKS(50));
        }

        // LVGL 保持 0°，因为 MADCTL 硬件已处理旋转
        if (disp) {
            lv_display_set_rotation(disp, LV_DISPLAY_ROTATION_0);
            lv_obj_invalidate(lv_scr_act());
        }
        eeui_port_lvgl_unlock();
    }

    ESP_LOGI(TAG, "屏幕旋转: %d° (MADCTL=0x%02X)", angle, madctl);
}

static esp_err_t cmd_set_rotation(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    int angle = 0;
    bool is_relative = false;

    if (data && cJSON_IsString(data)) {
        const char *val = data->valuestring;
        if (strcmp(val, "cw") == 0 || strcmp(val, "+") == 0) {
            is_relative = true;
            angle = 90;
        } else if (strcmp(val, "ccw") == 0 || strcmp(val, "-") == 0) {
            is_relative = true;
            angle = -90;
        } else if (val[0] == '+' || val[0] == '-') {
            is_relative = true;
            angle = atoi(val);
        } else {
            angle = atoi(val);
        }
    }

    if (is_relative) {
        // 从 NVS 读取当前角度
        int32_t current = 0;
        nvs_handle_t h;
        if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
            nvs_get_i32(h, NVS_KEY_ROTATION, &current);
            nvs_close(h);
        }
        angle = (current + angle) / 90 * 90;
    }

    angle = angle % 360;
    if (angle < 0) angle += 360;

    // 保存到 NVS
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_i32(h, NVS_KEY_ROTATION, angle);
        nvs_commit(h);
        nvs_close(h);
    }

    display_apply_rotation(angle);
    return ESP_OK;
}

void display_restore_rotation(void)
{
    int32_t angle = 0;
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
        nvs_get_i32(h, NVS_KEY_ROTATION, &angle);
        nvs_close(h);
    }
    if (angle != 0) {
        vTaskDelay(pdMS_TO_TICKS(500));  // 等 LVGL 初始化完成
        display_apply_rotation((int)angle);
    }
}

// set_brightness: data 为亮度百分比字符串，如 "80"
static esp_err_t cmd_set_brightness(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    int level = 100;
    if (data && cJSON_IsString(data)) {
        level = atoi(data->valuestring);
    }
    if (level < 0) level = 0;
    if (level > 100) level = 100;
    ESP_LOGI(TAG, "设置亮度: %d%%", level);
    eeui_port_set_brightness(level);

    // 亮度持久化到 NVS（键 "bl_level"），开机自动恢复（main.c 启动时读取）
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) == ESP_OK) {
        esp_err_t nvs_ret = nvs_set_i32(h, "bl_level", level);
        if (nvs_ret == ESP_OK) {
            nvs_ret = nvs_commit(h);
        }
        if (nvs_ret != ESP_OK) {
            ESP_LOGW(TAG, "亮度写入 NVS 失败: %s", esp_err_to_name(nvs_ret));
        }
        nvs_close(h);
    }
    return ESP_OK;
}

// get_brightness: 查询当前屏幕亮度，回复设备状态给服务器（内置工具 get_brightness 使用）
static esp_err_t cmd_get_brightness(cJSON *json)
{
    extern esp_err_t websocket_send_text(const char *text);
    int level = 100;
    // 亮度由 set_brightness 指令持久化到 NVS（bl_level），未设置过默认 100
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) == ESP_OK) {
        int32_t v = -1;
        if (nvs_get_i32(h, "bl_level", &v) == ESP_OK && v >= 0 && v <= 100) {
            level = (int)v;
        }
        nvs_close(h);
    }
    char reply[96];
    snprintf(reply, sizeof(reply),
             "{\"type\":\"instruct\",\"command_id\":\"device_state_result\",\"data\":\"brightness=%d\"}",
             level);
    websocket_send_text(reply);
    ESP_LOGI(TAG, "查询亮度: %d%%", level);
    return ESP_OK;
}

// refresh_emo: 服务端切换表情包后通知设备重新下载
static esp_err_t cmd_refresh_emo(cJSON *json)
{
    ESP_LOGI(TAG, "收到刷新表情包指令");
    const board_config_t *bcfg = board_get_config();
    if (bcfg && bcfg->emotion_builtin_only) {
        // 内置表情板型（如 1.54 寸 LCD 官方板）不使用服务器表情包，忽略刷新指令
        ESP_LOGI(TAG, "本板型使用编译内置表情，忽略刷新指令");
        return ESP_OK;
    }
    refresh_gifs();
    return ESP_OK;
}

// show_card: 通用卡片渲染（原生 LVGL，非 Lua——支持大号数字/中文字体/天气符号）
// data 为 JSON 卡片描述（协议见 eeui_port.cpp 的 show_card 模块注释）
static esp_err_t cmd_show_card(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        eeui_port_show_card(data->valuestring);
    } else {
        ESP_LOGW(TAG, "show_card: data 字段缺失或非字符串");
    }
    return ESP_OK;
}

// set_rotation: 旋转屏幕方向 0/90/180/270
void register_display_commands(void)
{
    static command_entry_t cmd_brightness = {
        .type = "instruct", .command_id = "set_brightness",
        .handler = cmd_set_brightness, .description = "设置屏幕亮度"
    };
    static command_entry_t cmd_get_brightness_entry = {
        .type = "instruct", .command_id = "get_brightness",
        .handler = cmd_get_brightness, .description = "查询当前屏幕亮度"
    };
    static command_entry_t cmd_show_card_entry = {
        .type = "instruct", .command_id = "show_card",
        .handler = cmd_show_card, .description = "通用卡片渲染（JSON 协议）"
    };
    static command_entry_t cmd_refresh = {
        .type = "instruct", .command_id = "refresh_emo",
        .handler = cmd_refresh_emo, .description = "刷新表情包"
    };
    static command_entry_t cmd_rotation = {
        .type = "instruct", .command_id = "set_rotation",
        .handler = cmd_set_rotation, .description = "旋转屏幕 0/90/180/270"
    };
    command_registry_add(&cmd_brightness);
    command_registry_add(&cmd_get_brightness_entry);
    command_registry_add(&cmd_show_card_entry);
    command_registry_add(&cmd_refresh);
    command_registry_add(&cmd_rotation);
    ESP_LOGI(TAG, "显示指令注册完成: set_brightness, get_brightness, show_card, refresh_emo, set_rotation");
}
