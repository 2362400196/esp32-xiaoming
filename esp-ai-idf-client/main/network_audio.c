/**
 * network_audio.c - 网络音频播放（移植自 Arduino audio_player.cpp 的 playNetworkAudio）
 *
 * 流程:
 *   1. 创建 FreeRTOS 任务
 *   2. esp_http_client 流式读取 MP3
 *   3. audio_spk_play() 启动 I2S + MP3 解码管道
 *   4. audio_spk_write() 写入 MP3 数据块
 *   5. 读取完成后等待播放 drain
 *
 * 对应 Arduino: playNetworkAudio(url) → http.GET() 循环 → mp3_player_write()
 */
#include "network_audio.h"
#include "config.h"
#include "eeui_port.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "network_audio";

static volatile bool s_playing = false;
static TaskHandle_t s_task_handle = NULL;
static char *s_current_url = NULL;
// 等待旧任务退出的调用者任务句柄（任务通知同步用）
static TaskHandle_t s_waiter_handle = NULL;
// 播放代次：每次 network_audio_play 递增，任务启动时记录自己的代次。
// 停止等待超时（旧任务可能仍在 drain）后新播放会推进代次；旧任务清理时
// 发现代次已变即跳过所有共享状态操作（s_playing/s_current_url/UI），
// 否则会杀死新播放或释放新 URL（双任务竞态）。
static volatile uint32_t s_generation = 0;

// 任务参数（任务自行释放）
typedef struct {
    char *url;
    uint32_t gen;
} net_audio_params_t;
// 自动续播标志：歌曲自然结束后自动请求下一首随机歌曲
// 由 cmd_play_music 设置为 true，由 network_audio_stop / cmd_stop_music / 唤醒清为 false
static volatile bool s_auto_continue = false;

// HTTP 读取缓冲区（与 Arduino 一致，增大可提升吞吐）
#define HTTP_READ_BUF 4096

// HTTP 事件处理器
static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    switch (evt->event_id) {
    case HTTP_EVENT_ERROR:
        ESP_LOGD(TAG, "HTTP 事件: 错误");
        break;
    case HTTP_EVENT_ON_CONNECTED:
        ESP_LOGD(TAG, "HTTP 事件: 已连接");
        break;
    case HTTP_EVENT_DISCONNECTED:
        ESP_LOGD(TAG, "HTTP 事件: 断开");
        break;
    default:
        break;
    }
    return ESP_OK;
}

// 网络音频播放任务
static void network_audio_task(void *pvParameters)
{
    net_audio_params_t *params = (net_audio_params_t *)pvParameters;
    char *url = params->url;
    const uint32_t my_gen = params->gen;
    free(params);

    // should_continue 必须在所有 goto cleanup 之前声明并初始化，
    // 否则编译器会报 maybe-uninitialized（goto 跳过变量初始化）
    bool should_continue = false;
    ESP_LOGI(TAG, "开始播放网络音频: %s", url);

    // 配置 HTTP 客户端
    esp_http_client_config_t config = {
        .url = url,
        .event_handler = http_event_handler,
        .timeout_ms = 15000,
        .buffer_size = HTTP_READ_BUF,
        .buffer_size_tx = 1024,
        .disable_auto_redirect = false,
    };

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "HTTP 客户端初始化失败");
        goto cleanup;
    }

    // 打开连接
    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP 打开失败: %s", esp_err_to_name(err));
        // 诊断：打印网络状态
        if (err == ESP_ERR_HTTP_CONNECT) {
            ESP_LOGE(TAG, "TCP 连接被拒绝，请检查: 1)音乐服务是否已启动(端口2233) "
                     "2)PC防火墙是否放行了2233端口 3)路由器是否开启了AP隔离");
        } else if (err == ESP_ERR_HTTP_CONNECTING) {
            ESP_LOGE(TAG, "TCP 连接超时(15s)，IP可能可达但端口无响应");
        }
        goto cleanup;
    }

    int content_length = esp_http_client_fetch_headers(client);
    if (content_length < 0) {
        ESP_LOGE(TAG, "HTTP 获取响应头失败: %d (HTTP状态码=%d)",
                 content_length, esp_http_client_get_status_code(client));
        goto cleanup;
    }
    ESP_LOGI(TAG, "HTTP 连接成功, 状态码=%d, 内容长度=%d 字节",
             esp_http_client_get_status_code(client), content_length);

    // 启动音频播放管道（I2S + MP3 解码）
    audio_spk_stop();   // 先停止当前播放（TTS 等）
    vTaskDelay(pdMS_TO_TICKS(50));
    audio_spk_play();

    // 流式读取并写入解码器
    char *buf = malloc(HTTP_READ_BUF);
    if (!buf) {
        ESP_LOGE(TAG, "缓冲区分配失败");
        goto cleanup;
    }

    int total_read = 0;
    // 代次检查：被新播放顶替时立即退出，避免新旧两个任务同时写音频管道
    while (s_playing && s_generation == my_gen) {
        int read_len = esp_http_client_read(client, buf, HTTP_READ_BUF);
        if (read_len < 0) {
            ESP_LOGE(TAG, "HTTP 读取错误: %d", read_len);
            break;
        }
        if (read_len == 0) {
            // 读取完成
            break;
        }

        // 写入 MP3 解码管道
        audio_spk_write((const uint8_t *)buf, read_len);
        total_read += read_len;

        if (total_read % (HTTP_READ_BUF * 8) == 0) {
            ESP_LOGD(TAG, "已读取 %d 字节", total_read);
        }
    }

    free(buf);
    ESP_LOGI(TAG, "网络音频读取完成，共 %d 字节", total_read);

    // 等待播放管道 drain（解码+I2S 播放完毕）
    // audio_spk_check_drain_done 由 websocket 主循环检测，这里等待标志
    int wait_count = 0;
    while (s_playing && s_generation == my_gen && wait_count < 600) {  // 最多等 60 秒
        if (audio_spk_check_drain_done()) {
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
        wait_count++;
    }

    // 判断是否为自然结束（未被用户停止、未被新播放顶替）
    if (s_generation == my_gen) {
        if (s_playing) {
            should_continue = s_auto_continue;
        }
        // 无论是否续播，都清除标志（续播时由服务端响应的 play_music 重新设置）
        s_auto_continue = false;
    }

cleanup:
    if (client) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
    }

    if (s_generation == my_gen) {
        // 本任务仍是当前播放：正常收尾共享状态
        s_playing = false;

        if (should_continue) {
            // 自动续播：重置歌词和进度条（清空旧歌词、停止进度定时器、进度归零），
            // 但不隐藏音乐播放器界面，等待下一首歌的 music_meta/lyric_line 刷新
            lyric_commands_reset();
            audio_spk_stop();
            ESP_LOGI(TAG, "自动续播：请求下一首随机歌曲");
        } else {
            // 正常结束或用户停止：重置歌词/进度条状态，隐藏音乐播放器
            lyric_commands_reset();
            eeui_port_hide_music_player();
            // 回待机省电：音乐长时播放时服务器不发 session_end（工具接管），
            // WiFi 会一直停在 NONE。音乐结束主动切回待机（WiFi modem sleep + 屏保计时）
            power_manager_set_active(false);
        }

        if (s_current_url) {
            free(s_current_url);
            s_current_url = NULL;
        }
        // 先清空 s_task_handle，再通知等待者
        s_task_handle = NULL;

        // 自动续播：通知服务端播放下一首随机歌曲
        if (should_continue) {
            websocket_send_text("{\"type\":\"music_play_next\"}");
        }

        // 通过任务通知告知等待者（network_audio_stop/play）本任务已退出
        TaskHandle_t waiter = s_waiter_handle;
        if (waiter) {
            xTaskNotifyGive(waiter);
        }
    } else {
        // 已被新播放顶替（停止等待超时后新播放已启动）：
        // 只回收自己的 URL，绝不触碰 s_playing/s_current_url/s_task_handle/UI——
        // 那些已属于新播放任务
        ESP_LOGW(TAG, "播放任务退出时代次已变（被新播放顶替），跳过共享状态清理");
    }

    free(url);

    ESP_LOGI(TAG, "网络音频播放任务结束%s", should_continue ? "（等待下一首）" : "");
    vTaskDelete(NULL);
}

esp_err_t network_audio_play(const char *url)
{
    if (!url || strlen(url) == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    // 停止当前播放并等待旧任务真正退出（任务通知同步，替代固定延时）
    if (s_playing) {
        network_audio_stop();
    }

    // 旧任务退出后，其 cleanup 已释放 s_current_url 并置 NULL。
    // 若超时未退出，s_current_url 可能仍非空——此时不释放（让旧任务自己清理），
    // 避免与旧任务 cleanup 产生双重释放/释放后使用竞态。
    if (s_current_url) {
        ESP_LOGW(TAG, "旧任务未在超时内退出，s_current_url 仍非空，放弃本次播放");
        return ESP_FAIL;
    }

    // 确认旧任务已退出后再分配新 URL。URL 由任务持有并自行释放，
    // params 同时传递代次，防止与旧任务清理窗口产生竞态
    net_audio_params_t *params = malloc(sizeof(net_audio_params_t));
    if (!params) {
        return ESP_ERR_NO_MEM;
    }
    params->url = strdup(url);
    if (!params->url) {
        free(params);
        return ESP_ERR_NO_MEM;
    }
    params->gen = ++s_generation;
    // 占位 s_current_url：旧任务清理窗口期间阻止并发播放
    s_current_url = params->url;

    s_playing = true;

    // 显示音乐播放器覆盖层
    eeui_port_show_music_player();

    // 创建播放任务：s_task_handle 仅在新任务成功创建后由 xTaskCreate 写入，
    // 避免与旧任务退出时清空 s_task_handle 产生竞态
    BaseType_t ret = xTaskCreate(network_audio_task, "net_audio", 8192,
                                 params, 5, &s_task_handle);
    if (ret != pdPASS) {
        ESP_LOGE(TAG, "创建播放任务失败");
        s_playing = false;
        free(params->url);
        free(params);
        s_current_url = NULL;
        return ESP_FAIL;
    }

    return ESP_OK;
}

esp_err_t network_audio_stop(void)
{
    if (!s_playing) {
        // 即使没有在播放，也要清除自动续播标志
        // 场景：歌曲刚结束、正在等待服务端响应下一首时用户唤醒
        s_auto_continue = false;
        return ESP_OK;
    }

    TaskHandle_t old_task = s_task_handle;
    // 先注册等待者，再置 s_playing=false，确保旧任务 cleanup 能读到 s_waiter_handle
    if (old_task) {
        s_waiter_handle = xTaskGetCurrentTaskHandle();
        // 清除可能残留的通知位，避免误唤醒
        xTaskNotifyStateClear(s_waiter_handle);
    }
    s_playing = false;
    s_auto_continue = false;  // 用户主动停止，清除自动续播
    audio_spk_stop();

    // 等待任务真正退出：使用任务通知替代固定 vTaskDelay
    // HTTP 超时最长 15s、drain 最长 60s，固定 200ms 无法保证任务已退出
    if (old_task) {
        uint32_t notify_value = 0;
        if (xTaskNotifyWait(ULONG_MAX, ULONG_MAX, &notify_value, pdMS_TO_TICKS(1000)) != pdPASS) {
            ESP_LOGW(TAG, "等待网络音频任务退出超时(1s)，任务可能仍在运行");
        }
        s_waiter_handle = NULL;
    }

    return ESP_OK;
}

bool network_audio_is_playing(void)
{
    return s_playing;
}

void network_audio_set_auto_continue(bool enable)
{
    s_auto_continue = enable;
}

bool network_audio_is_auto_continue(void)
{
    return s_auto_continue;
}
