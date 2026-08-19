#include "config.h"
#include "board_compat.h"
#include <stdlib.h>
#include <math.h>
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "freertos/stream_buffer.h"
#include "esp_timer.h"
#include "mp3_decoder_wrapper.h"
#if defined(AUDIO_SCHEME_ES8311)
#include "audio_codec/es8311.h"
#endif
#include "eeui_port.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"

// DMA 配置
#define SPK_DMA_DESC_NUM     24
#define SPK_DMA_FRAME_NUM    480

// 扬声器任务缓冲区大小（C3 无 PSRAM，缩小以通过初始化）
#ifdef CONFIG_IDF_TARGET_ESP32C3
#define SPK_OUT_BUF_SIZE     2304
#define SPK_READ_BUF_SIZE    1024
#define SPK_RESIDUAL_BUF_SIZE 2048
#else
#define SPK_OUT_BUF_SIZE     4608
#define SPK_READ_BUF_SIZE    2048
#define SPK_RESIDUAL_BUF_SIZE 4096
#endif

// 麦克风采集目标间隔
#define MIC_TARGET_INTERVAL_US 40000

// 看门狗超时阈值（每5ms一次检查）
#define SPK_WATCHDOG_TIMEOUT_NORMAL 2000   // 10秒
#define SPK_WATCHDOG_TIMEOUT_FIRST  6000   // 30秒（首帧更宽容）

// 待播放缓冲（pending）：WebSocket 文本消息（play_audio）可能因 esp_websocket_client
// 的消息处理延迟晚于二进制音频帧到达，导致 s_spk_ing 仍为 false 时音频帧被丢弃。
// 该缓冲暂存这些提前到达的数据，play_audio 处理时补入播放流。
// C3 无 PSRAM，只能缩小（S3 用 64KB 缓冲音频帧提前到达；C3 实测服务器单帧
// 2.3~3.7KB，1KB 连一帧都装不下会丢弃首帧，4KB 至少容纳一帧）
#ifdef CONFIG_IDF_TARGET_ESP32C3
#define SPK_PENDING_MAX (4 * 1024)
#else
#define SPK_PENDING_MAX (64 * 1024)
#endif
static uint8_t *s_spk_pending_buf = NULL;
static size_t s_spk_pending_len = 0;

static const char *TAG = "audio";

static i2s_chan_handle_t s_mic_handle = NULL;
static i2s_chan_handle_t s_spk_handle = NULL;
static bool s_mic_running = false;

// MP3 解码器（使用原始 helix 解码，支持 MPEG 2.5）
static mp3_decoder_handle_t s_mp3_dec = NULL;

// 音频流缓冲区（StreamBuffer，和原版 Arduino 一致）
#define SPK_BUF_SIZE SPK_STREAM_BUF_SIZE
static StreamBufferHandle_t s_spk_stream = NULL;
static SemaphoreHandle_t s_audio_mutex = NULL;
static bool s_spk_running = false;
static volatile bool s_spk_ing = false;
static TaskHandle_t s_spk_task_handle = NULL;
static volatile bool s_spk_ready = false;
static volatile bool s_spk_wait_drain = false;
static volatile bool s_spk_need_reset = false;
static volatile bool s_spk_overflow = false;
static volatile bool s_spk_drain_done = false;
static volatile bool s_spk_reset_decoder_flag = false;  // 异步重置解码器标志
static int s_spk_frame_count = 0;  // 调试：解码帧计数
static int64_t s_last_i2s_write_us = 0;  // I2S 写入时间戳，用于检测写入间隔
#if defined(AUDIO_SCHEME_ES8311)
// 当前 I2S 硬件实际采样率（ES8311 方案，用于播放结束后恢复 16kHz 唤醒时钟）
static int s_i2s_clock_rate = 0;
#endif

// 音量控制（0.0 ~ 1.0），移植自 Arduino esp-ai 客户端的 volume 机制
// 在 PCM 16bit 采样写入 I2S 前乘以音量系数，不影响 MP3 解码
// 使用对数曲线映射（-40dB~0dB），使音量感知更线性：
//   volume=0.0 → gain=0（静音），volume=1.0 → gain=1.0（原音量）
// s_vol_q15 为预计算的 Q15 定点增益，避免播放热路径上的浮点运算
static float s_volume = 1.0f;
static int32_t s_vol_q15 = 32767;

// 麦克风采集任务
static TaskHandle_t s_mic_task_handle = NULL;

// 初始化I2S麦克风（使用 wakeup 模块创建的共享句柄）
// I2S_NUM_0 只支持一个 RX 通道，必须与 WakeNet 共享
static esp_err_t init_mic(void)
{
    ESP_LOGI(TAG, "初始化I2S麦克风（共享 WakeNet 句柄）...");

    // 从 wakeup 模块获取已创建的 I2S 麦克风句柄
    s_mic_handle = (i2s_chan_handle_t)wakeup_get_mic_handle();
    if (s_mic_handle == NULL) {
        ESP_LOGE(TAG, "获取共享麦克风句柄失败（wakeup_init 未调用?）");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "I2S麦克风初始化完成（共享句柄，%dHz）", MIC_SAMPLE_RATE);
    return ESP_OK;
}

// 初始化I2S喇叭
static esp_err_t init_spk(void)
{
    ESP_LOGI(TAG, "初始化I2S喇叭...");

#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工方案：PA 使能 + 复用 wakeup 创建的 TX handle
    int pa_pin = board_get_config()->es8311_cfg->pa_pin;
    if (pa_pin >= 0) {
        gpio_config_t pa_cfg = {
            .pin_bit_mask = 1ULL << pa_pin,
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        gpio_config(&pa_cfg);
        gpio_set_level(pa_pin, 1);
        ESP_LOGI(TAG, "NS4150B 功放已使能 (PA=GPIO%d)", pa_pin);
    }

    // 复用 wakeup 模块创建的全双工 TX 通道
    // I2S 通道的创建、std 模式初始化、使能均在 wakeup_init() 中完成
    s_spk_handle = (i2s_chan_handle_t)wakeup_get_spk_handle();
    if (s_spk_handle == NULL) {
        ESP_LOGE(TAG, "获取共享扬声器 TX 句柄失败（wakeup_init 未调用?）");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "I2S喇叭初始化完成（共享全双工 TX 句柄）");
    return ESP_OK;
#else
    // I2S 直连方案：创建独立的 I2S_NUM_1 通道
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    chan_cfg.dma_desc_num = SPK_DMA_DESC_NUM;
    chan_cfg.dma_frame_num = SPK_DMA_FRAME_NUM;

    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &s_spk_handle, NULL));

    // ESP32-S3 (HW v2) 关键：MONO 模式必须用 I2S_STD_SLOT_BOTH
    // 只有 slot_mask=BOTH 时，HAL 才会启用 tx_mono+tx_chan_equal，硬件每帧只读 1 个采样并自动复制到 L+R
    // 如果用 I2S_STD_SLOT_LEFT，is_copy_mono=false，硬件每帧读 2 个采样，导致 2 倍速播放
    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SPK_SAMPLE_RATE),
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_BOTH,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            .left_align = false,
            .big_endian = false,
            .bit_order_lsb = false,
        },
        .gpio_cfg = {
            // I2S 直连方案：MAX98357 数字功放（板型引脚）
            .mclk = I2S_GPIO_UNUSED,
            .bclk = board_get_config()->spk_i2s_bck,
            .ws = board_get_config()->spk_i2s_ws,
            .dout = board_get_config()->spk_i2s_data,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_spk_handle, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(s_spk_handle));

    ESP_LOGI(TAG, "I2S喇叭初始化完成");
    return ESP_OK;
#endif
}

#if defined(AUDIO_SCHEME_ES8311)
// Catmull-Rom 三次插值重采样到 16kHz
// 相比线性插值，三次插值有更好的抗混叠特性（滚降更陡），
// 显著降低 24k→16k 下采样时的高频混叠 → 消除"沙沙/嘶嘶"噪声。
// in: 源 PCM(16bit mono), in_samples: 源样本数, rate: 源采样率
// out: 输出缓冲, out_capacity: 输出样本容量；返回输出样本数
static int resample_to_16k(const short *in, int in_samples, int rate, short *out, int out_capacity)
{
    if (rate <= 0 || in_samples <= 0) return 0;
    if (rate == SPK_SAMPLE_RATE) {
        int n = in_samples < out_capacity ? in_samples : out_capacity;
        memcpy(out, in, (size_t)n * sizeof(short));
        return n;
    }
    int out_samples = (int)((int64_t)in_samples * SPK_SAMPLE_RATE / rate);
    if (out_samples > out_capacity) out_samples = out_capacity;
    if (out_samples < 1) return 0;

    const float step = (float)rate / (float)SPK_SAMPLE_RATE;  // 源样本/输出样本
    for (int i = 0; i < out_samples; i++) {
        float pos = (float)i * step;
        int idx = (int)pos;
        float frac = pos - (float)idx;

        /* Catmull-Rom 需要相邻 4 点：in[idx-1], in[idx], in[idx+1], in[idx+2] */
        int i0 = idx - 1;
        int i1 = idx;
        int i2 = idx + 1;
        int i3 = idx + 2;
        if (i0 < 0) i0 = 0;
        if (i3 >= in_samples) i3 = in_samples - 1;
        if (i2 >= in_samples) i2 = in_samples - 1;

        float y0 = in[i0];
        float y1 = in[i1];
        float y2 = in[i2];
        float y3 = in[i3];

        /* Catmull-Rom 三次插值 */
        float c0 = y1;
        float c1 = 0.5f * (y2 - y0);
        float c2 = y0 - 2.5f * y1 + 2.0f * y2 - 0.5f * y3;
        float c3 = 0.5f * (y3 - y0) + 1.5f * (y1 - y2);

        float sample = c0 + c1 * frac + c2 * frac * frac + c3 * frac * frac * frac;

        /* 限制到 16bit 范围，防止溢出削波 */
        if (sample > 32767.0f) sample = 32767.0f;
        if (sample < -32768.0f) sample = -32768.0f;
        out[i] = (short)sample;
    }
    return out_samples;
}

// ES8311 方案：切换 I2S 采样率并同步 ES8311 内部时钟分频
// MCLK 倍率按 coeff 表匹配：512 优先（16k→8.192MHz），无匹配回退 256（标准 MCLK 全覆盖）
// 时序关键：必须先 i2s_channel_enable（MCLK 稳定输出新频率）再写 ES8311 coeff，
// 否则 ES8311 时钟管理器在 MCLK 停止时写入可能不生效 → DAC 时钟错乱 → 播放杂音
static esp_err_t spk_switch_es8311_clock(int rate)
{
    i2s_std_clk_config_t clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(rate);
    if (es8311_check_clock((uint32_t)rate * 512, (uint32_t)rate)) {
        clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_512;
    } else {
        clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    }
    i2s_channel_disable(s_spk_handle);
    esp_err_t err = i2s_channel_reconfig_std_clock(s_spk_handle, &clk_cfg);
    i2s_channel_enable(s_spk_handle);   // 先使能，让 MCLK 输出新频率
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "I2S时钟重配失败: %s", esp_err_to_name(err));
        return err;
    }
    // MCLK 稳定后切换 ES8311 内部时钟分频
    // ES8311 未初始化时跳过 I2C 操作（软重启后芯片不响应）
    if (!es8311_is_initialized()) {
        ESP_LOGW(TAG, "ES8311 未初始化，跳过时钟切换");
        s_i2s_clock_rate = rate;
        return ESP_OK;  // I2S 时钟已切换，ES8311 部分跳过
    }
    err = es8311_set_sample_rate((uint32_t)rate);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "ES8311 采样率切换失败: %s", esp_err_to_name(err));
        return err;
    }
    // 重新执行上电/解静音序列，确保 DAC 正常输出
    es8311_power_up();
    s_i2s_clock_rate = rate;
    ESP_LOGI(TAG, "I2S+ES8311 时钟重配: %dHz", rate);
    return ESP_OK;
}

// ES8311 方案：播放结束后恢复 16kHz（唤醒词检测依赖 RX 时钟）
static void spk_restore_es8311_clock(void)
{
    if (s_i2s_clock_rate == 0 || s_i2s_clock_rate == SPK_SAMPLE_RATE) {
        return;
    }
    if (spk_switch_es8311_clock(SPK_SAMPLE_RATE) != ESP_OK) {
        ESP_LOGW(TAG, "恢复 16kHz 时钟失败");
    }
}
#endif

// 确保 MP3 解码器已分配（延迟分配，C3 内存优化）
// helix 解码器结构约 45KB（8 块独立 malloc），启动阶段不分配，
// 首次播放时才申请，避免与 WebSocket/音频初始化抢堆。
// 返回 false 表示分配失败（堆不足），调用方应放弃本段音频。
static bool ensure_mp3_decoder(void)
{
    if (s_mp3_dec) return true;
    s_mp3_dec = mp3_decoder_init();
    if (s_mp3_dec == NULL) {
        ESP_LOGW(TAG, "MP3解码器分配失败（剩余堆: %d bytes）",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        return false;
    }
    ESP_LOGI(TAG, "MP3解码器已分配（首次播放延迟分配）");
    return true;
}

// 喇叭播放任务 - 阻塞式 I2S 写入，自然限速解码循环
// i2s_channel_write 阻塞直到 DMA 有空间，解码速率自然匹配播放速率
// 不需要 pcm_pending，不会丢数据，不会卡顿
static void spk_task(void *arg)
{
    ESP_LOGI(TAG, "音频播放任务启动");
    s_spk_ready = true;
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：TX/RX 已在 wakeup_init 以 16kHz/512× 配置并 enable
    s_i2s_clock_rate = SPK_SAMPLE_RATE;
#endif

    short *pcm_buffer = (short *)malloc(SPK_OUT_BUF_SIZE);
    uint8_t *i2s_buffer = (uint8_t *)malloc(SPK_OUT_BUF_SIZE);
    uint8_t *read_buf = (uint8_t *)malloc(SPK_READ_BUF_SIZE);
    uint8_t *residual_buf = (uint8_t *)malloc(SPK_RESIDUAL_BUF_SIZE);
#if defined(AUDIO_SCHEME_ES8311)
    short *resample_buf = (short *)malloc(SPK_OUT_BUF_SIZE);  // 软件重采样缓冲（非16k音频→16k）
#endif
    int residual_len = 0;
    int i2s_rate = 0;
    int no_data_count = 0;  // 连续无数据计数（每次 20ms），用于看门狗超时
    int64_t total_written = 0;  // 本次播放累计写入 I2S 的字节数（诊断用）

    if (!pcm_buffer || !i2s_buffer || !read_buf || !residual_buf
#if defined(AUDIO_SCHEME_ES8311)
        || !resample_buf
#endif
    ) {
        ESP_LOGE(TAG, "分配缓冲区失败，剩余堆: %d bytes",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        free(pcm_buffer); free(i2s_buffer); free(read_buf); free(residual_buf);
#if defined(AUDIO_SCHEME_ES8311)
        free(resample_buf);
#endif
        vTaskDelete(NULL);
        return;
    }

    while (s_spk_running) {
        if (s_spk_need_reset) {
            s_spk_need_reset = false;
            s_spk_overflow = false;
            residual_len = 0;
            i2s_rate = 0;              // 重置采样率，确保下一帧重新设置
#if defined(AUDIO_SCHEME_ES8311)
            spk_restore_es8311_clock();  // 若上一段播放用了非 16kHz，先恢复唤醒时钟
#endif
            s_spk_frame_count = 0;     // 重置帧计数，使淡入生效
            s_spk_reset_decoder_flag = false;
            s_last_i2s_write_us = 0;   // 重置 I2S 写入计时
            no_data_count = 0;         // 重置看门狗计数，新播放会话不应继承旧计数
            // 诊断：打印本次播放实际写入 I2S 的数据量，用于区分"数据没进 I2S"还是"功放/喇叭无声"
            if (total_written > 0) {
                ESP_LOGD(TAG, "本次播放结束: 解码 %d 帧, 共写入 I2S %lld bytes (约 %.0f ms)",
                         s_spk_frame_count, (long long)total_written,
                         (double)total_written * 1000.0 / 2.0 / (double)SPK_SAMPLE_RATE);
                total_written = 0;
            }
            // 不再 xStreamBufferReset：audio_spk_play() 已清过，这里再清会丢失期间到达的数据
            // 不再 i2s_channel_disable/enable：清 DMA 缓冲区会产生约 480ms 静音间隙（卡顿主因）
            // 新播放开始时 DMA 应已为空（上次音频已播完），直接写入新数据即可
            // 解码器延迟分配：释放旧实例，下一段音频首次解码时再申请（C3 省内存）
            if (s_mp3_dec) { mp3_decoder_free(s_mp3_dec); s_mp3_dec = NULL; }
        }

        if (!s_spk_ing) {
            // 如果正在等待 drain 但播放已停止（play_audio 被忽略或无音频数据），
            // 立即完成 drain，防止 drain_check_timer 永远等待
            if (s_spk_wait_drain) {
                ESP_LOGI(TAG, "播放已停止但 drain 等待中，立即完成 drain");
                s_spk_wait_drain = false;
                s_spk_drain_done = true;
            }
            uint8_t drain_tmp[512];
            while (xStreamBufferReceive(s_spk_stream, drain_tmp, sizeof(drain_tmp), 0) > 0) {}
            i2s_rate = 0;
            residual_len = 0;
#if defined(AUDIO_SCHEME_ES8311)
            spk_restore_es8311_clock();
#endif
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        // 从 StreamBuffer 读一块数据（5ms 超时，减少 DMA 欠载风险）
        size_t got = xStreamBufferReceive(s_spk_stream, read_buf, SPK_READ_BUF_SIZE, pdMS_TO_TICKS(5));

        // 看门狗：如果长时间没收到数据且不在等待 drain，强制停止播放
        // 防止服务端异常断连导致 spk_task 永远卡在 continue 循环
        // 首帧解码前用更长超时（30s），容忍 TTS 生成延迟；首帧后用 10s 超时
        if (got > 0 || residual_len > 0) {
            no_data_count = 0;
        } else {
            no_data_count++;
            int timeout_threshold = (s_spk_frame_count > 0) ? SPK_WATCHDOG_TIMEOUT_NORMAL : SPK_WATCHDOG_TIMEOUT_FIRST;  // 10s 或 30s
            if (!s_spk_wait_drain && no_data_count > timeout_threshold) {
                ESP_LOGW(TAG, "看门狗超时：%d秒无数据(帧#%d)，强制停止播放",
                         timeout_threshold * 5 / 1000, s_spk_frame_count);
                s_spk_ing = false;
                s_spk_drain_done = true;  // 防止 drain 定时器继续等待
                i2s_rate = 0;
                residual_len = 0;
                no_data_count = 0;
                // 通知服务端音频播放异常终止
                char over_msg[128];
                snprintf(over_msg, sizeof(over_msg),
                    "{\"type\":\"client_out_audio_over\",\"session_status\":\"03\"}");
                websocket_send_text_nb(over_msg);
                continue;
            }
        }

        // drain 无进展保护：drain 等待期间若数据"卡死"（MP3 残留数据解不出、
        // 无新数据且无消费）持续 3 秒，强制完成 drain。
        // 背景：唤醒音频帧丢失/损坏时 residual 残留，drain 完成条件
        // （residual_len == 0）永不满足，而看门狗在 wait_drain 时被禁用，
        // 设备 10 秒静默 → 服务器 "Wake audio wait timeout" 放弃会话 → "唤醒没反应"。
        // 原理：正常播放时 stream/residual 状态持续变化（数据被消费/补充），
        // 状态不变才累计超时，不会误杀正常长音频。
        static TickType_t s_drain_stall_tick = 0;
        static size_t s_drain_stall_state = 0;
        if (s_spk_wait_drain) {
            size_t stream_bytes = xStreamBufferBytesAvailable(s_spk_stream);
            size_t state = (size_t)(residual_len << 16) | (stream_bytes & 0xFFFF);
            if (got > 0 || state != s_drain_stall_state) {
                s_drain_stall_state = state;
                s_drain_stall_tick = xTaskGetTickCount();  // 有进展，重置计时
            } else if ((xTaskGetTickCount() - s_drain_stall_tick) * portTICK_PERIOD_MS > 3000) {
                // 3 秒内 stream/residual 状态完全没变：解码卡死，强制完成
                ESP_LOGW(TAG, "drain 等待 3 秒无进展 (residual=%d, stream=%d)，强制完成播放",
                         residual_len, (int)stream_bytes);
                s_drain_stall_tick = 0;
                s_drain_stall_state = 0;
                s_spk_wait_drain = false;
                s_spk_ing = false;
                s_spk_drain_done = true;
                if (s_mp3_dec) { mp3_decoder_free(s_mp3_dec); s_mp3_dec = NULL; }
                continue;
            }
        } else {
            s_drain_stall_tick = 0;
            s_drain_stall_state = 0;
        }

        // drain 检查：必须在 continue 之前，否则 StreamBuffer 空时永远到不了
        // 必须同时检查 residual_len == 0，否则残留 MP3 数据没解码完就认为播放完成
        // 必须同时检查待播放缓冲为空，否则 play_audio 晚到时先到的音频会被误判为已完成
        size_t pending_now = 0;
        if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
        pending_now = s_spk_pending_len;
        if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
        if (s_spk_wait_drain && xStreamBufferBytesAvailable(s_spk_stream) == 0 && got == 0 && residual_len == 0 && pending_now == 0) {
            // StreamBuffer 空了且无新数据，等 I2S DMA 播完最后的数据
            vTaskDelay(pdMS_TO_TICKS(400));
            s_spk_wait_drain = false;
            s_spk_ing = false;
            s_spk_drain_done = true;
            // 播放自然结束：释放 MP3 解码器（~45KB）还给堆，
            // 供 wakeup_resume() 重建 WakeNet 实例使用（C3 内存优化）
            if (s_mp3_dec) {
                mp3_decoder_free(s_mp3_dec);
                s_mp3_dec = NULL;
                ESP_LOGI(TAG, "播放结束，MP3解码器已释放 (剩余堆: %d bytes)",
                         (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
            }
            continue;
        }

        if (got == 0 && residual_len == 0) continue;

        // 在拼接数据前检查重置标志，避免旧 residual 被解码产生杂音
        // 注意：只重置解码器和残留数据，不能清 I2S DMA！
        // 清 DMA 会打断正在播放的音频，产生约 480ms 静音间隙（"卡"）
        // 旧句子的 PCM 数据在 DMA 中是正常的，让它自然播完
        if (s_spk_reset_decoder_flag) {
            s_spk_reset_decoder_flag = false;
            if (s_mp3_dec) { mp3_decoder_free(s_mp3_dec); s_mp3_dec = NULL; }
            residual_len = 0;
            i2s_rate = 0;           // 重置采样率，新句子首帧重新设置
            s_spk_frame_count = 0;  // 重置帧计数，使淡入生效
            // 不 continue，继续处理新数据
        }

        // 拼接残留数据 + 新数据
        uint8_t *decode_buf;
        int decode_len;
        if (residual_len > 0 && got > 0) {
            int total = residual_len + (int)got;
            if (total > SPK_RESIDUAL_BUF_SIZE) {
                residual_len = 0;
                decode_buf = read_buf;
                decode_len = (int)got;
            } else {
                memcpy(residual_buf + residual_len, read_buf, got);
                decode_buf = residual_buf;
                decode_len = total;
            }
        } else if (residual_len > 0) {
            decode_buf = residual_buf;
            decode_len = residual_len;
        } else {
            decode_buf = read_buf;
            decode_len = (int)got;
        }

        // 解码循环
        uint8_t *ptr = decode_buf;
        int bytes_left = decode_len;
        bool clear_residual = false;

        while (bytes_left > 0 && s_spk_ing && !s_spk_need_reset) {
            // 兜底检查：如果外层漏掉了 flag（理论上不会发生）
            if (s_spk_reset_decoder_flag) {
                s_spk_reset_decoder_flag = false;
                if (s_mp3_dec) { mp3_decoder_free(s_mp3_dec); s_mp3_dec = NULL; }
                residual_len = 0;
                i2s_rate = 0;
                s_spk_frame_count = 0;
                clear_residual = true;
                break;
            }

            // MP3 解码器延迟分配：首次解码前确保已申请（C3 内存优化）
            if (!ensure_mp3_decoder()) {
                // 堆不足无法分配解码器：放弃本次播放（限流日志），
                // 播放停止后 drain 定时器会向服务端发送 over，下次 play_audio 重试
                static uint32_t s_dec_oom_cnt = 0;
                if ((s_dec_oom_cnt++ % 20) == 0) {
                    ESP_LOGW(TAG, "MP3解码器分配失败(堆不足) 第%u次，停止本次播放", s_dec_oom_cnt);
                }
                s_spk_ing = false;
                s_spk_drain_done = true;
                residual_len = 0;
                break;
            }

            int sync_off = mp3_decoder_find_sync(ptr, bytes_left);
            if (sync_off < 0) break;
            if (sync_off > 0) {
                ptr += sync_off;
                bytes_left -= sync_off;
            }
            if (bytes_left < 4) break;

            uint8_t *dec_ptr = ptr;
            int dec_left = bytes_left;
            int out_samps = 0;
            int ret = mp3_decoder_decode_frame(s_mp3_dec, &dec_ptr, &dec_left, pcm_buffer, &out_samps);

            if (ret == 0 && out_samps > 0) {
                mp3_decoder_info_t info;
                mp3_decoder_get_info(s_mp3_dec, &info);

                // 采样率处理：
                // - i2s_rate == 0：首帧，设置采样率并配置 I2S
                // - i2s_rate != 0 且不匹配：真实跳变（如 24000↔44100）重配 I2S 时钟
                //   忽略小幅振荡（如 24000→48000→24000 的解码器误判）
                if (i2s_rate == 0) {
#if defined(AUDIO_SCHEME_ES8311)
                    // ES8311 方案：I2S 硬件固定 16kHz（与唤醒/收音共用，避免运行期切时钟把 ES8311 搞乱），
                    // 非 16kHz 音频（如服务端 24kHz TTS）在写入前软件重采样到 16kHz
                    i2s_rate = SPK_SAMPLE_RATE;
                    ESP_LOGD(TAG, "首帧: 音频 %dHz/%dch, ES8311 固定 %dHz 播放(软件重采样)",
                             info.sample_rate, info.channels, SPK_SAMPLE_RATE);
#else
                    i2s_rate = info.sample_rate;
                    ESP_LOGD(TAG, "设置I2S采样率: %dHz, 声道: %d, 码率: %d, 解码输出: %d samps",
                             i2s_rate, info.channels, info.bitrate, out_samps);
                    // 首帧：先 disable 再重配 I2S 硬件时钟，再 enable
                    i2s_channel_disable(s_spk_handle);
                    i2s_std_clk_config_t clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(i2s_rate);
                    esp_err_t err = i2s_channel_reconfig_std_clock(s_spk_handle, &clk_cfg);
                    if (err == ESP_OK) {
                        i2s_channel_enable(s_spk_handle);
                        ESP_LOGD(TAG, "I2S时钟重配成功: %dHz", i2s_rate);
                    } else {
                        i2s_channel_enable(s_spk_handle);
                        ESP_LOGW(TAG, "I2S时钟重配失败: %s", esp_err_to_name(err));
                    }
#endif
                } else if (info.sample_rate != i2s_rate) {
#if defined(AUDIO_SCHEME_ES8311)
                    // ES8311 方案：硬件固定 16k，采样率变化由软件重采样处理，不重配硬件时钟
                    if (info.sample_rate >= 8000 && info.sample_rate <= 48000) {
                        ESP_LOGD(TAG, "采样率变化: %dHz, 软件重采样到 16kHz", info.sample_rate);
                    } else {
                        ESP_LOGW(TAG, "忽略异常采样率: %dHz", info.sample_rate);
                    }
#else
                    // 大幅跳变 → 真实采样率变化（如 TTS 24000 → 音乐 44100），重配 I2S
                    int old_rate = i2s_rate;
                    if (info.sample_rate >= 8000 && info.sample_rate <= 48000 &&
                        abs(info.sample_rate - old_rate) >= 10000) {
                        ESP_LOGD(TAG, "采样率大幅变化: %d -> %d，重配I2S时钟", old_rate, info.sample_rate);
                        i2s_channel_disable(s_spk_handle);
                        i2s_std_clk_config_t clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(info.sample_rate);
                        esp_err_t err = i2s_channel_reconfig_std_clock(s_spk_handle, &clk_cfg);
                        if (err == ESP_OK) {
                            i2s_channel_enable(s_spk_handle);
                            i2s_rate = info.sample_rate;
                            ESP_LOGD(TAG, "I2S时钟重配成功: %dHz", i2s_rate);
                        } else {
                            i2s_channel_enable(s_spk_handle);
                            ESP_LOGW(TAG, "I2S时钟重配失败: %s", esp_err_to_name(err));
                        }
                    } else {
                        ESP_LOGW(TAG, "忽略采样率跳变: %d -> %d (差值过小/非法值)", i2s_rate, info.sample_rate);
                    }
#endif
                }

                // 始终写入 PCM 数据（即使采样率不匹配也只影响 1 帧 24ms，比重配 I2S 中断小得多）
                {
                    int bytes = 0;
                    if (info.channels == 2) {
                        int num_samps = out_samps / 2;
                        int max_samps = SPK_OUT_BUF_SIZE / sizeof(short);
                        if (num_samps > max_samps) num_samps = max_samps;
                        for (int i = 0; i < num_samps; i++) {
                            ((short*)i2s_buffer)[i] = pcm_buffer[i * 2];
                        }
                        bytes = num_samps * sizeof(short);
                    } else {
                        bytes = out_samps * sizeof(short);
                        if (bytes > SPK_OUT_BUF_SIZE) bytes = SPK_OUT_BUF_SIZE;
                        memcpy(i2s_buffer, pcm_buffer, bytes);
                    }

#if defined(AUDIO_SCHEME_ES8311)
                    // 软件重采样：非 16kHz → 16kHz（保持音调；ES8311 硬件固定 16k，绝不运行期切时钟）
                    if (info.sample_rate != SPK_SAMPLE_RATE && info.sample_rate >= 8000 && info.sample_rate <= 48000) {
                        int in_samps = bytes / (int)sizeof(short);
                        int out_samps = resample_to_16k((const short *)i2s_buffer, in_samps,
                                                        info.sample_rate, resample_buf,
                                                        SPK_OUT_BUF_SIZE / (int)sizeof(short));
                        if (out_samps > 0) {
                            memcpy(i2s_buffer, resample_buf, (size_t)out_samps * sizeof(short));
                            bytes = out_samps * (int)sizeof(short);
                        }
                    }
#endif

                    // 调试日志
                    s_spk_frame_count++;
                    if (s_spk_frame_count <= 3 || s_spk_frame_count % 50 == 0) {
                        ESP_LOGD(TAG, "解码帧#%d: ch=%d, out_samps=%d, pcm_bytes=%d",
                                 s_spk_frame_count, info.channels, out_samps, bytes);
                    }
                    // 诊断：统计整个播放会话的 PCM 峰值（含所有帧，区分解码静音 vs 真实音频）
                    {
                        static int16_t s_spk_session_peak = 0;
                        static uint32_t s_spk_session_frames = 0;
                        int ns = bytes / (int)sizeof(short);
                        for (int i = 0; i < ns; i++) {
                            int16_t v = ((short*)i2s_buffer)[i];
                            if (v < 0) v = -v;
                            if (v > s_spk_session_peak) s_spk_session_peak = v;
                        }
                        s_spk_session_frames++;
                        if (s_spk_session_frames % 100 == 0) {
                            ESP_LOGD(TAG, "[SPK诊断] rate=%dHz ch=%d bitrate=%dkbps 累计%d帧 pcm_peak=%d",
                                     info.sample_rate, info.channels, info.bitrate,
                                     s_spk_session_frames, s_spk_session_peak);
                        }
                    }

                    // 前4帧做淡入，防止音频起始爆音(click/pop)
                    // 24kHz 下每帧 24ms，4帧 = 96ms 渐进淡入
                    if (s_spk_frame_count <= 4) {
                        int num_samples = bytes / sizeof(short);
                        for (int i = 0; i < num_samples; i++) {
                            int32_t sample = (int32_t)((short*)i2s_buffer)[i];
                            // 全局进度: 0 → 1.0，跨4帧平滑过渡
                            // frame 1: 0.000 → 0.250, frame 2: 0.250 → 0.500
                            // frame 3: 0.500 → 0.750, frame 4: 0.750 → 1.000
                            int32_t fade_start = ((int32_t)(s_spk_frame_count - 1) * 16384) / 4;
                            int32_t fade_end = ((int32_t)s_spk_frame_count * 16384) / 4;
                            int32_t fade = fade_start + (fade_end - fade_start) * (int32_t)i / num_samples;
                            ((short*)i2s_buffer)[i] = (short)((sample * fade) >> 14);
                        }
                    }

                    // 应用音量系数（对数曲线预计算，定点运算无浮点开销）
                    // s_vol_q15 在 audio_set_volume 中预计算，int32_t 原子读取无需加锁
                    if (s_vol_q15 < 32767) {
                        int num_samples = bytes / sizeof(short);
                        for (int i = 0; i < num_samples; i++) {
                            int32_t sample = (int32_t)((short*)i2s_buffer)[i];
                            ((short*)i2s_buffer)[i] = (short)((sample * s_vol_q15) >> 15);
                        }
                    }

                    // 阻塞写入 I2S：等 DMA 有空间再写，自然限速
                    // DMA 缓冲区 480ms，足够吸收解码抖动
                    size_t written = 0;
                    // 诊断：检测 I2S 写入间隔，超过 30ms 说明 DMA 可能欠载
                    int64_t now_us = esp_timer_get_time();
                    if (s_last_i2s_write_us > 0) {
                        int64_t gap_ms = (now_us - s_last_i2s_write_us) / 1000;
                        if (gap_ms > 30) {
                            ESP_LOGW(TAG, "I2S 写入间隔: %lldms (帧#%d, 可能欠载)", gap_ms, s_spk_frame_count);
                        }
                    }
                    esp_err_t wr = i2s_channel_write(s_spk_handle, i2s_buffer, bytes, &written, pdMS_TO_TICKS(2000));
                    if (wr != ESP_OK) {
                        ESP_LOGW(TAG, "I2S write timeout/error: %s", esp_err_to_name(wr));
                        // 仍推进解码位置，避免重复解码同一帧导致死循环
                        ptr = dec_ptr;
                        bytes_left = dec_left;
                        continue;
                    }
                    s_last_i2s_write_us = esp_timer_get_time();
                    total_written += (int64_t)written;
                    // 功耗管理：刷新输出活动时间戳，防止空闲超时关闭 PA
                    power_manager_notify_output();
                }
                ptr = dec_ptr;
                bytes_left = dec_left;
            } else if (ret == -1 || ret == -2) {
                break;
            } else {
                ptr += 2;
                bytes_left -= 2;
            }
        }

        // 保存未消费的残留数据
        if (clear_residual) {
            residual_len = 0;
        } else if (bytes_left > 0 && bytes_left <= SPK_RESIDUAL_BUF_SIZE) {
            memmove(residual_buf, ptr, bytes_left);
            residual_len = bytes_left;
        } else {
            residual_len = 0;
        }
    }

    free(pcm_buffer);
    free(i2s_buffer);
    free(read_buf);
    free(residual_buf);
#if defined(AUDIO_SCHEME_ES8311)
    free(resample_buf);
#endif
    s_spk_task_handle = NULL;
    vTaskDelete(NULL);
}

// 麦克风采集任务
static void mic_task(void *arg)
{
    // 使用较小的 chunk 避免大二进制帧导致 WebSocket 断开
    #define MIC_CHUNK_SIZE 1024  // 32ms @ 16kHz 16bit mono
    uint8_t *buffer = malloc(MIC_CHUNK_SIZE);
    if (buffer == NULL) {
        ESP_LOGE(TAG, "分配音频缓冲区失败");
        vTaskDelete(NULL);
        return;
    }

    // 等待 WakeNet 完全暂停，避免 I2S 句柄竞争
    int wait_count = 0;
    while (!wakeup_is_paused() && s_mic_running) {
        vTaskDelay(pdMS_TO_TICKS(10));
        wait_count++;
        if (wait_count > 100) {  // 最多等 1 秒
            ESP_LOGE(TAG, "麦克风: 等待 WakeNet 暂停超时，放弃本次采集");
            free(buffer);
            s_mic_task_handle = NULL;
            vTaskDelete(NULL);
            return;
        }
    }

    size_t bytes_read = 0;
    int fail_count = 0;
    // 动态节流：匹配音频实时采样率，避免突发发送填满 TCP 缓冲区
    // 1024 bytes @ 16kHz 16bit mono = 32ms 音频
    // 目标间隔 40ms（80% 实时率），给 WiFi 半双工留出接收 ACK 的时间窗口
    int64_t cycle_start = esp_timer_get_time();
    const int64_t target_interval_us = MIC_TARGET_INTERVAL_US;  // 40ms

    while (s_mic_running) {
        esp_err_t ret = i2s_channel_read(s_mic_handle, buffer, MIC_CHUNK_SIZE, &bytes_read, pdMS_TO_TICKS(100));
        if (ret == ESP_OK && bytes_read > 0 && s_mic_running) {
            // 发送前再次检查连接状态（避免竞态条件）
            if (!websocket_is_connected()) {
                ESP_LOGW(TAG, "麦克风: WebSocket 未连接，停止采集");
                break;
            }
            esp_err_t send_ret = websocket_send_binary(buffer, bytes_read);
            if (send_ret != ESP_OK) {
                fail_count++;
                if (fail_count >= 3) {
                    ESP_LOGW(TAG, "麦克风: 连续 %d 次发送失败，停止采集", fail_count);
                    break;
                }
            } else {
                fail_count = 0;  // 成功则重置计数
            }
            // 动态节流：确保发送间隔 >= 40ms，给 WiFi 留出接收 TCP ACK 的窗口
            int64_t elapsed_us = esp_timer_get_time() - cycle_start;
            if (elapsed_us < target_interval_us) {
                vTaskDelay(pdMS_TO_TICKS((target_interval_us - elapsed_us) / 1000));
            }
            cycle_start = esp_timer_get_time();
        }
    }

    free(buffer);
    s_mic_task_handle = NULL;
    vTaskDelete(NULL);
}

esp_err_t audio_init(void)
{
    ESP_LOGI(TAG, "初始化音频系统...");

    // 创建音频流缓冲区（类似原版 BufferRTOS）
    s_spk_stream = xStreamBufferCreate(SPK_BUF_SIZE, 1);
    if (s_spk_stream == NULL) {
        ESP_LOGE(TAG, "创建音频流缓冲区失败 (需 %d 字节)，剩余堆: %d bytes",
                 (int)SPK_BUF_SIZE, (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        return ESP_FAIL;
    }

    // 创建音频互斥锁
    s_audio_mutex = xSemaphoreCreateMutex();
    if (s_audio_mutex == NULL) {
        ESP_LOGE(TAG, "创建音频互斥锁失败");
        vStreamBufferDelete(s_spk_stream);
        s_spk_stream = NULL;
        return ESP_FAIL;
    }

    // 分配待播放缓冲（优先 PSRAM，避免占用紧张的内部 RAM）
    s_spk_pending_buf = board_malloc_audio(SPK_PENDING_MAX);
    if (s_spk_pending_buf == NULL) {
        ESP_LOGW(TAG, "PSRAM 分配待播放缓冲失败，尝试内部 RAM");
        s_spk_pending_buf = malloc(SPK_PENDING_MAX);
    }
    if (s_spk_pending_buf == NULL) {
        ESP_LOGW(TAG, "待播放缓冲分配失败，音频帧提前到达时将退化为丢弃");
    } else {
        s_spk_pending_len = 0;
    }

    esp_err_t ret = init_mic();
    if (ret != ESP_OK) {
        goto cleanup;
    }

    ret = init_spk();
    if (ret != ESP_OK) {
        goto cleanup;
    }

    // MP3 解码器不在启动时分配（~45KB，延迟到首次播放，见 ensure_mp3_decoder）
    ESP_LOGI(TAG, "MP3解码器延迟分配（首次播放时申请）");

    // 启动播放任务
    s_spk_running = true;
    BaseType_t task_ret = xTaskCreatePinnedToCore(
        spk_task,
        "spk_task",
#ifdef CONFIG_IDF_TARGET_ESP32C3
        4096,   // C3 无 PSRAM，收紧任务栈
#else
        6144,   // 从 8192 减到 6144，释放内部 RAM（LCD 版本内部 RAM 紧张）
#endif
        NULL,
        TASK_PRIO_AUDIO,
        &s_spk_task_handle,
        BOARD_TASK_CORE_1  // 双核：核心1（与 WebSocket/网络分离）；单核：核心0
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "创建播放任务失败");
        s_spk_running = false;
        goto cleanup;
    }

    ESP_LOGI(TAG, "音频系统初始化完成");
    return ESP_OK;

cleanup:
    // 集中清理已分配的资源，避免部分初始化失败时泄漏
    // 注意：s_mic_handle 来自 wakeup 模块的共享句柄，不在此处释放
    if (s_mp3_dec) {
        mp3_decoder_free(s_mp3_dec);
        s_mp3_dec = NULL;
    }
    if (s_spk_handle) {
        i2s_channel_disable(s_spk_handle);
        i2s_del_channel(s_spk_handle);
        s_spk_handle = NULL;
    }
    if (s_audio_mutex) {
        vSemaphoreDelete(s_audio_mutex);
        s_audio_mutex = NULL;
    }
    if (s_spk_stream) {
        vStreamBufferDelete(s_spk_stream);
        s_spk_stream = NULL;
    }
    return ESP_FAIL;
}

esp_err_t audio_mic_start(void)
{
    if (s_mic_running) {
        ESP_LOGW(TAG, "麦克风已在运行");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "启动麦克风采集...");
    s_mic_running = true;

    BaseType_t ret = xTaskCreatePinnedToCore(
        mic_task,
        "mic_task",
#ifdef CONFIG_IDF_TARGET_ESP32C3
        2048,   // C3 无 PSRAM，收紧任务栈
#else
        4096,
#endif
        NULL,
        TASK_PRIO_AUDIO,
        &s_mic_task_handle,
        BOARD_TASK_CORE_1  // 双核：核心1；单核：核心0
    );

    if (ret != pdPASS) {
        ESP_LOGE(TAG, "创建麦克风任务失败");
        s_mic_running = false;
        return ESP_FAIL;
    }

    return ESP_OK;
}

esp_err_t audio_mic_stop(void)
{
    if (!s_mic_running) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "停止麦克风采集...");
    s_mic_running = false;

    return ESP_OK;
}

bool audio_mic_is_running(void)
{
    return s_mic_running;
}

// 流控上报节流
static int64_t s_last_flow_report_ms = 0;

// 发送流控消息的内部函数
// value 语义按连接模式区分：
//   - 官方服务器(node.espai*.fun)：上报"已缓冲待播放字节数"，与 Arduino
//     esp_ai_spk_queue.available() 一致；空缓冲上报 0 表示"可以立即发送"
//   - 本地 esp-ai-server(自定义服务器)：上报"剩余空间"，配合其缓冲满保护逻辑
//     (pipeline 中 _device_buffer < client_max_buffer*0.1 时 sleep 等待)
// 若语义错配，服务端会把空缓冲误判为"缓冲满"而不下发/节流音频
static void send_flow_control(void) {
    int available = websocket_is_official()
                        ? (int)xStreamBufferBytesAvailable(s_spk_stream)
                        : (int)xStreamBufferSpacesAvailable(s_spk_stream);
    char msg[64];
    snprintf(msg, sizeof(msg), "{\"type\":\"client_available_audio\",\"value\":%d}", available);
    websocket_send_text_nb(msg);
    s_last_flow_report_ms = esp_timer_get_time() / 1000;
}

// 追加数据到待播放缓冲（须在 s_audio_mutex 外调用，内部加锁）
static esp_err_t spk_pending_append(const uint8_t *data, size_t len)
{
    if (s_spk_pending_buf == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    if (s_spk_pending_len + len > SPK_PENDING_MAX) {
        if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
        ESP_LOGW(TAG, "待播放缓冲溢出，丢弃 %d bytes (pending=%d)", (int)len, (int)s_spk_pending_len);
        return ESP_ERR_INVALID_STATE;
    }
    memcpy(s_spk_pending_buf + s_spk_pending_len, data, len);
    s_spk_pending_len += len;
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
    return ESP_OK;
}

esp_err_t audio_spk_write(const uint8_t *data, size_t len)
{
    if (s_spk_stream == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    // 共享标志 s_spk_ing / s_spk_wait_drain 需在互斥锁保护下访问，
    // 避免与 spk_task / audio_spk_stop 等并发修改产生竞态。
    // 注意：xStreamBufferSend 可能阻塞，不能在持锁状态下调用，否则会死锁。
    bool can_write = false;
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    can_write = s_spk_ing;
    // 收到实际音频数据，清除 drain 等待状态
    // （二进制 "03" 可能先于 play_audio 到达，设置了 drain 等待，
    //  但后续有新音频数据到来，不应触发 drain 完成）
    if (can_write && s_spk_wait_drain && len > 0) {
        s_spk_wait_drain = false;
    }
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);

    if (!can_write) {
        // play_audio（文本消息）可能因 WebSocket 消息处理延迟晚于音频帧到达，
        // 此时 s_spk_ing 仍为 false。数据不丢弃，暂存待播放缓冲，
        // 待 play_audio 处理时补入播放流（修复唤醒提示音偶发无声）。
        // 音乐推流模式下播放器已由 play_audio 强制启动，若仍为 false
        // 说明播放被打断/停止，直接丢弃多余数据，避免 pending 缓冲堆积溢出。
        if (websocket_is_music_streaming()) {
            return ESP_OK;
        }
        return spk_pending_append(data, len);
    }

    // 功耗管理：数据即将写入播放缓冲，刷新输出活动时间戳
    power_manager_notify_output();

    // 音乐推流模式（play_audio + tts_task_id="play_music"）：
    // 整首音乐经 WS 大流量下发（25600B+ 每帧，服务端初始会突发推 ~150KB）。
    // 不能无限阻塞（会堵死 WebSocket 回调导致指令延迟），也不能完全不阻塞
    // （无 TCP 反压，服务端持续超量推流，缓冲永远满、音乐严重卡顿）。
    // 采用 500ms 短阻塞：提供 TCP 反压让服务端减速（与 Arduino 阻塞写一致），
    // 同时每帧最多阻塞 500ms，指令延迟可控；仍写不完则丢弃多余数据。
    if (websocket_is_music_streaming()) {
        size_t written_m = xStreamBufferSend(s_spk_stream, data, len, pdMS_TO_TICKS(500));
        if (written_m < len) {
            size_t dropped = len - written_m;
            // 丢弃日志限流：每丢满 256KB 打印一次，避免刷屏
            static uint32_t s_music_dropped_total = 0;
            s_music_dropped_total += dropped;
            if (s_music_dropped_total >= 256 * 1024) {
                ESP_LOGW(TAG, "音乐推流：累计丢弃 %u KB，播放速度跟不上服务端推流", s_music_dropped_total / 1024);
                s_music_dropped_total = 0;
            }
        }
        return ESP_OK;
    }

    // 流控上报策略：
    // 不再周期性发送 client_available_audio，避免服务端 Pipeline 因流控 sleep 延长发送时间。
    // 长文本场景下流控 sleep 累计会导致 Pipeline 30s 超时，音频帧被丢弃但 tts_real_end 仍发送，
    // 设备误以为音频已发完，提前进入下一轮（"说不完就进入下一轮"）。
    // 正常情况下依靠 xStreamBufferSend 阻塞写入 + TCP 反压自然控制发送速率，
    // 仅在缓冲区溢出时上报流控通知服务端减速。
    // 这与 Arduino 客户端的行为一致（Arduino 不发送 client_available_audio）。

    // 阻塞写入：等待缓冲区有空间，不丢数据
    // 超时 1000ms，spk_task 消费速率 ~8KB/s，1秒可腾出 ~8KB 空间
    // 过短超时会导致 MP3 数据丢失 → 解码出杂音
    size_t written = xStreamBufferSend(s_spk_stream, data, len, pdMS_TO_TICKS(1000));
    if (written < len) {
        s_spk_overflow = true;
        ESP_LOGW(TAG, "缓冲区写入不足: %d/%d bytes", (int)written, (int)len);
        // 仅在溢出时上报流控，通知服务端减速
        send_flow_control();
    }

    return ESP_OK;
}

// 当前是否正在播放音频（play_audio 分段判断用）
// 服务端会将一句 TTS 拆成多个 play_audio 分段流式下发，
// 播放中收到新 play_audio 应视为分段(不重置播放器)，而非新音频流
bool audio_spk_is_playing(void)
{
    bool playing = false;
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    playing = s_spk_ing;
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
    return playing;
}

esp_err_t audio_spk_play(void)
{
    ESP_LOGI(TAG, "开始音频播放...");

    // 功耗管理：确保 PA 功放 + DAC 已使能（空闲超时后可能已关闭）
    // 必须在播放开始前完成，否则首段音频会被静音
    power_manager_enable_output();

    // 等待 spk_task 就绪（首次启动时防竞态）
    int wait = 0;
    while (!s_spk_ready && wait < 50) {
        vTaskDelay(pdMS_TO_TICKS(10));
        wait++;
    }

    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);

    // 同步重置：清空缓冲区
    if (s_spk_stream) xStreamBufferReset(s_spk_stream);

    // 使用 s_spk_need_reset 让 spk_task 安全地执行完整重置
    // 包括：清空 I2S DMA、重置解码器、重置采样率和帧计数
    // 不能在这里直接调用 i2s_channel_disable/enable，因为 spk_task 可能正在写 I2S
    s_spk_need_reset = true;
    s_spk_reset_decoder_flag = false;  // s_spk_need_reset 会处理，避免重复

    s_spk_ing = true;
    // 不重置 s_spk_wait_drain：如果二进制 "03" 已设置 drain 等待，
    // play_audio 消息可能晚于 "03" 到达（WebSocket 消息顺序），
    // 重置会导致 drain 检查失效，看门狗 30s 超时
    s_spk_drain_done = false;
    s_spk_frame_count = 0;
    s_last_flow_report_ms = 0;

    // 补入待播放缓冲：play_audio（文本）晚于音频帧到达时，先到的音频在此写入播放流
    if (s_spk_pending_buf != NULL && s_spk_pending_len > 0) {
        size_t p_len = s_spk_pending_len;
        size_t w = xStreamBufferSend(s_spk_stream, s_spk_pending_buf, p_len, 0);
        if (w < p_len) {
            ESP_LOGW(TAG, "待播放数据补入不完整: %d/%d", (int)w, (int)p_len);
        }
        ESP_LOGI(TAG, "补入待播放音频: %d bytes", (int)p_len);
        s_spk_pending_len = 0;
    }

    // 立即发送首帧流控消息，让服务端知道缓冲区初始状态
    // 不等第一帧音频到达，否则服务端会在收到流控前疯狂发送
    send_flow_control();

    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);

    return ESP_OK;
}

esp_err_t audio_spk_stop(void)
{
    ESP_LOGI(TAG, "停止音频播放...");

    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    s_spk_ing = false;
    s_spk_wait_drain = false;
    s_spk_drain_done = false;
    s_spk_need_reset = true;
    if (s_spk_pending_buf != NULL) {
        s_spk_pending_len = 0;  // 停止时丢弃未播出的待播放数据
    }
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);

    return ESP_OK;
}

// 硬停止：同步清空所有缓冲区 + 解码器重置（Arduino mp3_player_stop 一致）
// 用于唤醒打断场景，与 audio_spk_stop 的异步模式不同
esp_err_t audio_spk_hard_stop(void)
{
    ESP_LOGI(TAG, "硬停止音频播放...");

    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);

    // 1. 关闭播放闸门
    s_spk_ing = false;
    s_spk_wait_drain = false;
    s_spk_drain_done = false;
    if (s_spk_pending_buf != NULL) {
        s_spk_pending_len = 0;  // 硬停止时丢弃待播放数据
    }

    // 2. 清空流缓冲区（同步）
    if (s_spk_stream) {
        xStreamBufferReset(s_spk_stream);
    }

    // 3. 重置解码器状态（实际由 spk 任务在 s_spk_need_reset 时完成 locals 重置）
    s_spk_need_reset = true;
    s_spk_reset_decoder_flag = false;
    s_spk_frame_count = 0;

    // 4. 解码器释放与重建交由 spk_task 在安全时机完成
    //    不在此处直接 mp3_decoder_free：spk_task 解码循环可能正在使用 s_mp3_dec，
    //    直接释放会导致 use-after-free。s_spk_need_reset 已置位，spk_task 会在
    //    下一次循环顶部检测并安全地释放/重建解码器。
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);

    return ESP_OK;
}

void audio_spk_reset_decoder(void)
{
    // 设置异步重置标志，由 spk_task 在安全时机执行
    // 不能直接释放解码器，因为 spk_task 可能正在使用它
    s_spk_reset_decoder_flag = true;
}

esp_err_t audio_spk_wait_drain(void)
{
    ESP_LOGI(TAG, "等待音频缓冲区排空...");
    // s_spk_drain_done / s_spk_wait_drain 被 spk_task 读写，需加锁保护
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    s_spk_drain_done = false;
    s_spk_wait_drain = true;
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
    return ESP_OK;
}

// 由 WebSocket handler 定期调用，检查播放完成并发送确认
bool audio_spk_check_drain_done(void)
{
    bool done = false;
    // s_spk_drain_done 被 spk_task 写入，读改操作需加锁保护
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    if (s_spk_drain_done) {
        s_spk_drain_done = false;
        done = true;
    }
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
    return done;
}

// 获取音频缓冲区流控上报值（按连接模式区分语义，详见 send_flow_control 注释）
size_t audio_spk_buffer_available(void)
{
    if (s_spk_stream == NULL) return 0;
    if (websocket_is_official()) {
        // 官方服务端语义：已缓冲待播放字节数（与 Arduino esp_ai_spk_queue.available() 一致）
        return xStreamBufferBytesAvailable(s_spk_stream);
    }
    // 本地 esp-ai-server 语义：剩余空间
    return xStreamBufferSpacesAvailable(s_spk_stream);
}

// ==================== 音量控制（移植自 Arduino esp-ai 客户端）====================
// 音量范围 0.0 ~ 1.0，在 PCM 采样写入 I2S 前应用系数
// 与 Arduino 的 esp_ai.setVolume(vol) 等价
esp_err_t audio_set_volume(float volume)
{
    if (volume < 0.0f) volume = 0.0f;
    if (volume > 1.0f) volume = 1.0f;
    // s_volume / s_vol_q15 跨任务被 spk_task 读取，写操作需加锁保护
    if (s_audio_mutex) xSemaphoreTake(s_audio_mutex, portMAX_DELAY);
    s_volume = volume;
    // 对数曲线：volume=0 → 静音(gain=0)，volume>0 → -40dB~0dB 对数映射
    // 感知音量更线性：低音量区间精度提升，避免量化噪声明显
    if (volume <= 0.001f) {
        s_vol_q15 = 0;
    } else {
        float db_attenuation = -40.0f * (1.0f - volume);
        float gain = powf(10.0f, db_attenuation / 20.0f);
        if (gain > 1.0f) gain = 1.0f;
        s_vol_q15 = (int32_t)(gain * 32768.0f);
    }
    if (s_audio_mutex) xSemaphoreGive(s_audio_mutex);
    ESP_LOGI(TAG, "设置音量: %.2f (%d%%) gain=%d/32768", volume, (int)(volume * 100), s_vol_q15);
    // 联动 ES8311 DAC 硬件音量（REG32）：若嘶嘶声随 DAC 音量变化 → DAC 增益问题（软件可缓解）；
    // 若不变 → 功放/电源噪声（硬件问题，软件无法解决）
#if defined(AUDIO_SCHEME_ES8311)
    if (es8311_is_initialized()) {
        es8311_set_volume((int)(volume * 100));
    }
#endif
    eeui_port_render_volume(volume);
    return ESP_OK;
}

float audio_get_volume(void)
{
    return s_volume;
}
