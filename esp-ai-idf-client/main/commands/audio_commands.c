/**
 * audio_commands.c - 音频相关指令
 *
 * 从 websocket.c 迁移的指令:
 *   - play_music: 播放网络音乐（HTTP 流式 MP3）
 *   - stop_music: 停止网络音乐播放并清空扬声器缓冲区
 */
#include "command_registry.h"
#include "config.h"
#include "network_audio.h"
#include "eeui_port.h"
#include "esp_log.h"

static const char *TAG = "cmd_audio";

// play_music: data 为音乐 URL 字符串
static esp_err_t cmd_play_music(cJSON *json)
{
    cJSON *data = cJSON_GetObjectItem(json, "data");
    if (data && cJSON_IsString(data)) {
        ESP_LOGI(TAG, "播放音乐: %s", data->valuestring);
        // 启用自动续播：歌曲自然结束后自动请求下一首随机歌曲
        network_audio_set_auto_continue(true);
        network_audio_play(data->valuestring);
    }
    // 恢复语音唤醒：音乐长时播放，服务器 play_music 工具接管后不发 session_end
    // （raise StopPipeline 后会话悬挂），wakenet 从唤醒起一直暂停 → 播放音乐时
    // 语音唤醒失效（按钮唤醒正常）。此处主动恢复，听歌时可直接喊"暂停音乐"等。
    wakeup_resume();
    return ESP_OK;
}

// stop_music: 停止网络音乐播放（data 可为空）
static esp_err_t cmd_stop_music(cJSON *json)
{
    ESP_LOGI(TAG, "停止音乐播放");
    // 1. 清除自动续播标志（用户主动停止）
    network_audio_set_auto_continue(false);
    // 2. 停止网络音频任务（HTTP 流式下载 + 解码播放任务）
    network_audio_stop();
    // 3. 硬停止扬声器（清空 I2S 缓冲区 + 重置解码器）
    audio_spk_hard_stop();
    // 4. 重置歌词/进度条状态（停止进度定时器、清空歌词、进度条归零）
    lyric_commands_reset();
    // 5. 隐藏音乐播放器覆盖层
    eeui_port_hide_music_player();
    // 6. 回待机省电（音乐播放时服务器不发 session_end，主动恢复待机状态）
    power_manager_set_active(false);
    return ESP_OK;
}

void register_audio_commands(void)
{
    static command_entry_t cmds[] = {
        {
            .type = "instruct", .command_id = "play_music",
            .handler = cmd_play_music, .description = "播放网络音乐"
        },
        {
            .type = "instruct", .command_id = "stop_music",
            .handler = cmd_stop_music, .description = "停止网络音乐播放"
        },
    };
    for (int i = 0; i < sizeof(cmds) / sizeof(cmds[0]); i++) {
        command_registry_add(&cmds[i]);
    }
    ESP_LOGI(TAG, "音频指令注册完成: play_music, stop_music");
}
