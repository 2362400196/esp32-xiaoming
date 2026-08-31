/**
 * official_commands.c - 官方服务版专用指令
 *
 * 仅 esp32s3_breadboard_1.54_lcd_official（official_service=true）板型注册。
 * 官方服务(espai.fun)与自定义服务的指令行为不同(对照 esp-ai-client command_handler.cpp)：
 *   - play_music: 官方只设置播放状态+表情,音乐音频由 play_audio("play_music") WS 推流
 *     (websocket.c 的 s_music_streaming 分支处理)；自定义服务走 instruct + HTTP 流式
 *   - volume_up: 官方加音量 0.1 的指令
 *   - volume_down: 官方减音量 0.1 的指令
 *   - query_battery: 官方查询电量并语音播报
 *
 * 本文件指令通过"后注册头插"覆盖同名指令(play_music)：
 * command_registry 为头插链表,分发时从头匹配,后注册的同名指令先命中。
 * 普通板(自定义服务)不注册本文件指令,现有行为完全不受影响。
 */
#include "command_registry.h"
#include "config.h"
#include "eeui_port.h"
#include "nvs.h"
#include "esp_log.h"
#include <stdio.h>

static const char *TAG = "cmd_official";

// 保存音量到 NVS(与官方 up_click 的 setLocalData("ext2") 一致)
static void save_volume_nvs(float vol)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) == ESP_OK) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%.1f", vol);
        nvs_set_str(h, "ext2", buf);
        nvs_commit(h);
        nvs_close(h);
    }
}

// play_music(官方行为):只设状态+表情,音乐音频由 play_audio("play_music") WS 推流播放
static esp_err_t cmd_play_music_official(cJSON *json)
{
    (void)json;
    ESP_LOGI(TAG, "播放音乐(官方推流模式): 显示唱歌中状态");
    display_show_emotion("唱歌中");
    display_show_status("唱歌中");
    // 恢复语音唤醒：音乐长时播放，服务器 play_music 工具接管后不发 session_end，
    // wakenet 从唤醒起一直暂停 → 语音唤醒失效（同自定义服务器 play_music 修复）
    wakeup_resume();
    return ESP_OK;
}

// volume_up(官方):加音量 0.1
static esp_err_t cmd_volume_up_official(cJSON *json)
{
    (void)json;
    ESP_LOGI(TAG, "收到官方加音量指令 (volume_up)");
    float vol = audio_get_volume() + 0.1f;
    if (vol > 1.0f) vol = 1.0f;
    audio_set_volume(vol);
    save_volume_nvs(vol);
    return ESP_OK;
}

// volume_down(官方):减音量 0.1
static esp_err_t cmd_volume_down_official(cJSON *json)
{
    (void)json;
    ESP_LOGI(TAG, "收到官方减音量指令 (volume_down)");
    float vol = audio_get_volume() - 0.1f;
    if (vol < 0.0f) vol = 0.0f;
    audio_set_volume(vol);
    save_volume_nvs(vol);
    return ESP_OK;
}

// query_battery(官方):查询电量
// 当前 IDF 固件无电量检测硬件,显示与电量图标一致的值(100%)
static esp_err_t cmd_query_battery_official(cJSON *json)
{
    (void)json;
    ESP_LOGI(TAG, "查询电量");
    display_show_text("设备电量剩余 100%");
    return ESP_OK;
}

void register_official_commands(void)
{
    const board_config_t *bcfg = board_get_config();
    if (!(bcfg && bcfg->official_service)) {
        ESP_LOGI(TAG, "非官方服务板型，跳过官方指令注册");
        return;
    }

    static command_entry_t entries[] = {
        {
            .type = "instruct", .command_id = "play_music",
            .handler = cmd_play_music_official, .description = "播放音乐(官方推流模式,仅状态)"
        },
        {
            .type = "instruct", .command_id = "volume_up",
            .handler = cmd_volume_up_official, .description = "加音量0.1(官方)"
        },
        {
            .type = "instruct", .command_id = "volume_down",
            .handler = cmd_volume_down_official, .description = "减音量0.1(官方)"
        },
        {
            .type = "instruct", .command_id = "query_battery",
            .handler = cmd_query_battery_official, .description = "查询电量(官方)"
        },
    };
    for (int i = 0; i < sizeof(entries) / sizeof(entries[0]); i++) {
        command_registry_add(&entries[i]);
    }
    ESP_LOGI(TAG, "官方指令注册完成: play_music, volume_up, volume_down, query_battery");
}
