#include "config.h"
#include "board_compat.h"
#include "provisioning.h"
#include "driver/gpio.h"
#include "driver/i2s_std.h"
#include <math.h>  /* sqrt（麦克风信号强度诊断） */
// 纯 WakeNet 接口（对齐 xiaozhi-esp32 C3 方案）：
// 不经过完整 AFE（NS/VAD/AEC/ringbuffer），I2S 数据累积到 chunksize 后直接 detect()。
// 相比 AFE 方案：内存更小、无 "Ringbuffer of AFE is empty" 刷屏问题。
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "model_path.h"
#include "esp_heap_caps.h"  /* heap_caps_get_free_size（内存诊断） */
#include "gif_downloader.h" /* gif_download_is_busy：表情下载期间禁用唤醒 */
#include "freertos/idf_additions.h"  /* xTaskCreatePinnedToCoreWithCaps */
#include "freertos/semphr.h"
#if defined(AUDIO_SCHEME_ES8311)
#include "audio_codec/es8311.h"
#endif

static const char *TAG = "wakeup";

// 唤醒状态
static bool s_wakeup_running = false;
static TaskHandle_t s_wakeup_task_handle = NULL;
static TaskHandle_t s_wakenet_task_handle = NULL;

// 事件组
EventGroupHandle_t s_wakeup_event_group;

// BOOT 按钮引脚 (ESP32-S3) - 运行时获取
// 在需要获取按钮引脚的地方使用 board_get_config()->wake_button_gpio

// keepalive 检查计数器
static int s_keepalive_check_counter = 0;
static TickType_t s_last_wakeup_trigger_tick = 0;

#define WAKEUP_TRIGGER_COOLDOWN_MS 3000

// WakeNet 状态（纯 wakenet 接口，无 AFE）
static const esp_wn_iface_t *s_wakenet = NULL;      // WakeNet 接口
static model_iface_data_t *s_wakenet_data = NULL;   // WakeNet 实例（激活缓冲，~80KB）
static srmodel_list_t *s_models = NULL;
static const char *s_model_name = NULL;             // 模型名（指向 s_models 内部）
static volatile bool s_wakenet_paused = false;
static volatile bool s_wakenet_reading = false;  // 标记是否正在读取 I2S
static i2s_chan_handle_t s_wakenet_mic_handle = NULL;
static i2s_chan_handle_t s_spk_tx_handle = NULL;  // ES8311 全双工方案的 TX 句柄
static SemaphoreHandle_t s_i2s_mutex = NULL;

// 前向声明
extern void websocket_check_keepalive(void);
static void wakeup_apply_det_threshold(void);

// ==================== 按钮唤醒任务（保留原有逻辑）====================

static void button_wakeup_task(void *arg)
{
    ESP_LOGI(TAG, "按钮唤醒任务启动");

    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << board_get_config()->wake_button_gpio),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_conf);

    int last_state = 1;
    int loop_count = 0;

    // 4 次按键进入配网检测
    const int REPROV_PRESS_THRESHOLD = 4;
    int s_press_count = 0;
    TickType_t s_first_press_tick = 0;

    while (s_wakeup_running) {
        int current_state = gpio_get_level(board_get_config()->wake_button_gpio);

        // 每100次循环打印一次状态（约1秒）
        loop_count++;
        if (loop_count >= 100) {
            ESP_LOGD(TAG, "按钮状态: GPIO%d = %d", board_get_config()->wake_button_gpio, current_state);
            loop_count = 0;

            // 每 1 秒检查一次 keepalive 超时
            s_keepalive_check_counter++;
            if (s_keepalive_check_counter >= 1) {
                s_keepalive_check_counter = 0;
                websocket_check_keepalive();
            }
        }

        // 检查 4 次按键超时重置：如果第一下按键超过 2 秒没有后续，清零
        TickType_t now = xTaskGetTickCount();
        if (s_press_count > 0 && s_press_count < REPROV_PRESS_THRESHOLD) {
            TickType_t since_first = (now - s_first_press_tick) * portTICK_PERIOD_MS;
            if (since_first >= 2000) {
                s_press_count = 0;
                s_first_press_tick = 0;
                ESP_LOGI(TAG, "4次按键超时，计数清零");
            }
        }

        // 检测按钮按下（下降沿）
        if (current_state == 0 && last_state == 1) {
            // 更新按键计数（滑动窗口：同一 2s 窗口内计数）
            if (s_press_count == 0) {
                s_first_press_tick = xTaskGetTickCount();
            }
            s_press_count++;

            if (s_press_count >= REPROV_PRESS_THRESHOLD) {
                ESP_LOGW(TAG, "=========================================");
                ESP_LOGW(TAG, "%d次按键检测到，清除配置进入配网!", REPROV_PRESS_THRESHOLD);
                ESP_LOGW(TAG, "=========================================");
                s_press_count = 0;
                s_first_press_tick = 0;

                // 等待按钮释放
                vTaskDelay(pdMS_TO_TICKS(50));
                while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                }

                // 清除所有配置并重启
                provisioning_clear_all();
                vTaskDelete(NULL);  // 防御兜底：若 provisioning_clear_all 未重启，任务不能以 return 退出
                return;
            }

            // 正常唤醒触发（单次按键），受冷却限制
            if (s_last_wakeup_trigger_tick != 0) {
                TickType_t elapsed_ms = (now - s_last_wakeup_trigger_tick) * portTICK_PERIOD_MS;
                if (elapsed_ms < WAKEUP_TRIGGER_COOLDOWN_MS) {
                    ESP_LOGW(TAG, "Wakeup ignored: trigger cooldown active (%d/%d ms)",
                             (int)elapsed_ms, WAKEUP_TRIGGER_COOLDOWN_MS);
                    vTaskDelay(pdMS_TO_TICKS(50));
                    while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                        vTaskDelay(pdMS_TO_TICKS(10));
                    }
                    last_state = 1;
                    continue;
                }
            }
            // 表情下载期间禁用唤醒（与语音唤醒一致，避免下载占用内存时
            // 唤醒/播放分配失败导致异常会话）。放在冷却计时之前：
            // 忽略的唤醒不启动 8 秒冷却，下载完成后可立即唤醒。
            if (gif_download_is_busy()) {
                static TickType_t s_last_ignored_btn = 0;
                TickType_t now_t2 = xTaskGetTickCount();
                if ((now_t2 - s_last_ignored_btn) * portTICK_PERIOD_MS > 5000) {
                    s_last_ignored_btn = now_t2;
                    ESP_LOGW(TAG, "表情下载中，忽略按钮唤醒（下载完成后自动恢复）");
                }
                // 等待按钮释放并消抖
                vTaskDelay(pdMS_TO_TICKS(50));
                while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                    vTaskDelay(pdMS_TO_TICKS(10));
                }
                last_state = 1;
                continue;
            }

            s_last_wakeup_trigger_tick = now;

            ESP_LOGI(TAG, "=========================================");
            ESP_LOGI(TAG, "检测到按钮唤醒触发! (2秒内再按%d次可进入配网)",
                     REPROV_PRESS_THRESHOLD - s_press_count);
            ESP_LOGI(TAG, "=========================================");

            // 设置唤醒事件
            xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);

            // 等待按钮释放并消抖
            vTaskDelay(pdMS_TO_TICKS(50));
            while (gpio_get_level(board_get_config()->wake_button_gpio) == 0) {
                vTaskDelay(pdMS_TO_TICKS(10));
            }
            ESP_LOGI(TAG, "按钮已释放");

            // 释放后继续消抖
            vTaskDelay(pdMS_TO_TICKS(100));
        }

        last_state = current_state;
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    s_wakeup_task_handle = NULL;
    vTaskDelete(NULL);
}

// ==================== 语音唤醒任务（纯 WakeNet，无 AFE）====================

static void wakenet_task(void *arg)
{
    ESP_LOGI(TAG, "语音唤醒任务启动");

    // 为 detect 分配 PCM 缓冲（chunksize × 通道数）
    int chunksize = s_wakenet->get_samp_chunksize(s_wakenet_data);
    int wn_channels = s_wakenet->get_channel_num(s_wakenet_data);
    int16_t *feed_buf = (int16_t *)board_malloc_audio(chunksize * wn_channels * sizeof(int16_t));
    if (feed_buf == NULL) {
        ESP_LOGE(TAG, "分配 WakeNet PCM 缓冲区失败");
        s_wakenet_task_handle = NULL;
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "WakeNet chunksize=%d, channels=%d", chunksize, wn_channels);

    while (s_wakeup_running) {
        // 会话期间暂停语音唤醒（s_wakenet_data 可能已被 wakeup_pause 销毁释放内存）
        if (s_wakenet_paused || s_wakenet_data == NULL) {
            s_wakenet_reading = false;  // 标记未在读取
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        // 标记正在读取 I2S
        s_wakenet_reading = true;

        // 尝试获取 I2S 互斥锁（非阻塞，让 mic_task 也有机会获取）
        // 如果 wakeup_pause 已获取锁，这里会快速退出
        if (s_i2s_mutex && xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(5)) != pdTRUE) {
            s_wakenet_reading = false;
            continue;
        }

        // 再次检查暂停（获取锁后检查）
        if (s_wakenet_paused || s_wakenet_data == NULL) {
            if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);
            s_wakenet_reading = false;
            continue;
        }

        // 从 I2S 麦克风读取音频数据，累积读满一个 detect 块（chunksize 采样）
        const size_t chunk_bytes = (size_t)chunksize * wn_channels * sizeof(int16_t);
        size_t filled = 0;
        bool read_failed = false;
        int read_empty_count = 0;  // 连续空读保护
        while (filled < chunk_bytes && s_wakeup_running && !s_wakenet_paused && s_wakenet_data != NULL) {
            size_t bytes_read = 0;
            esp_err_t ret = i2s_channel_read(s_wakenet_mic_handle,
                                             (uint8_t *)feed_buf + filled,
                                             chunk_bytes - filled,
                                             &bytes_read, pdMS_TO_TICKS(50));
            if (ret != ESP_OK) { read_failed = true; break; }
            if (bytes_read > 0) {
                filled += bytes_read;
                read_empty_count = 0;
            } else {
                read_empty_count++;
                // 连续 10 次空读（约 500ms 无数据）→ 放弃本轮，避免死循环
                if (read_empty_count >= 10) {
                    ESP_LOGW(TAG, "I2S RX 连续空读 %d 次，放弃本轮检测", read_empty_count);
                    read_failed = true;
                    break;
                }
            }
        }
        // 读取完成后释放互斥锁，让 mic_task 可以使用
        if (s_i2s_mutex) xSemaphoreGive(s_i2s_mutex);

        // 诊断：统计本次读取的音频峰值，判断麦克风是否有有效数据
        // （若峰值一直为 0，说明 ES8311 ADC 未工作/收音静音）
        static uint32_t s_mic_diag_cnt = 0;
        s_mic_diag_cnt++;

        // ── 麦克风健康看门狗 ──
        // 现象：设备运行一段时间后无法语音唤醒，按键唤醒后也无法录音。
        // 本质多为 ES8311 ADC 时钟失锁 / 寄存器被 WiFi 射频干扰写坏（I2C 抗干扰经典坑），
        // 固件无任何自愈逻辑时只能靠重启恢复。
        // 自愈：连续检测到"读取失败/无数据"或"长期全零"时，重跑 es8311_power_up()
        // 重新锁存 CSM 时钟 + 重新上电 ADC/DAC + 解静音，恢复收音。
        static int s_mic_bad_reads = 0;         // 连续"读取失败/无数据"次数
        static uint32_t s_mic_zero_reads = 0;   // 连续"全零数据"次数
        static TickType_t s_last_mic_recover_tick = 0;  // 自愈冷却
        if (read_failed || filled == 0 || (filled < chunk_bytes && !s_wakenet_paused)) {
            s_mic_bad_reads++;
            s_mic_zero_reads = 0;
        } else if (filled == chunk_bytes) {
            bool all_zero = true;
            int zsamples = (int)(filled / sizeof(int16_t));
            for (int i = 0; i < zsamples; i++) {
                if (feed_buf[i] != 0) { all_zero = false; break; }
            }
            if (all_zero) {
                s_mic_zero_reads++;
                s_mic_bad_reads = 0;
            } else {
                s_mic_bad_reads = 0;
                s_mic_zero_reads = 0;
            }
        }
        // 周期性信号强度诊断：每 ~6 秒打印一次输入峰值/RMS（正常说话时应明显高于底噪）
        static uint32_t s_mic_sig_cnt = 0;
        if (filled == chunk_bytes && s_mic_bad_reads == 0 && s_mic_zero_reads == 0) {
            s_mic_sig_cnt++;
            if (s_mic_sig_cnt % 200 == 0) {
                int16_t peak = 0;
                int64_t sum_sq = 0;
                int zsamples = (int)(filled / sizeof(int16_t));
                for (int i = 0; i < zsamples; i++) {
                    int16_t v = feed_buf[i];
                    int16_t a = v < 0 ? (int16_t)-v : v;
                    if (a > peak) peak = a;
                    sum_sq += (int64_t)v * v;
                }
                int rms = (int)sqrt((double)sum_sq / zsamples);
                ESP_LOGI(TAG, "麦克风信号: 峰值=%d (%.0f%%), RMS=%d", peak,
                         peak * 100.0f / 32767.0f, rms);
            }
        }
        // 连续 ~2s 无数据 或 连续 ~30s 全零 → 判定麦克风失效，触发自愈（带 30s 冷却）
        if ((s_mic_bad_reads >= 40 || s_mic_zero_reads >= 600)) {
            TickType_t now_tick = xTaskGetTickCount();
            if ((now_tick - s_last_mic_recover_tick) * portTICK_PERIOD_MS > 30000) {
                s_last_mic_recover_tick = now_tick;
                ESP_LOGW(TAG, "麦克风检测失效 (bad_reads=%d, zero_reads=%u)，尝试 ES8311 重新锁存恢复...",
                         s_mic_bad_reads, (unsigned)s_mic_zero_reads);
                s_mic_bad_reads = 0;
                s_mic_zero_reads = 0;
#if defined(AUDIO_SCHEME_ES8311)
                if (es8311_is_initialized()) {
                    es8311_power_up();
                    es8311_dump_regs();
                    ESP_LOGW(TAG, "麦克风自愈完成，已重新锁存 ES8311 时钟/ADC");
                }
#endif
            }
        }

        if (s_mic_diag_cnt % 50 == 0) {
            // 麦克风峰值诊断：DEBUG 级别，生产模式不显示（排查麦克风问题时
            // 将 wakeup 日志级别调为 DEBUG 即可恢复）
            int16_t peak = 0;
            int samples = (int)(filled / sizeof(int16_t));
            for (int i = 0; i < samples; i++) {
                int16_t v = feed_buf[i];
                if (v < 0) v = -v;
                if (v > peak) peak = v;
            }
            ESP_LOGD(TAG, "[MIC诊断] ret=%s bytes=%d peak=%d",
                     read_failed ? "FAIL" : "OK", (int)filled, peak);
        }

        if (read_failed || filled < chunk_bytes) {
            // 读取失败或暂停退出（未读满一块）：不检测，下一轮继续累积
            s_wakenet_reading = false;
            continue;
        }

        // 唤醒词检测（纯 WakeNet，直接对原始 PCM 检测）
        wakenet_state_t state = s_wakenet->detect(s_wakenet_data, feed_buf);
        s_wakenet_reading = false;

        // 诊断：每 200 次检测（约 6 秒）打印一次 detect 结果，确认 WakeNet 在运行
        static uint32_t s_detect_diag = 0;
        s_detect_diag++;
        if (s_detect_diag % 200 == 0) {
            ESP_LOGD(TAG, "WakeNet 检测状态: %s (迭代 %u)",
                     state == WAKENET_DETECTED ? "DETECTED" :
                     state == WAKENET_NO_DETECT ? "NOT_DETECTED" : "UNKNOWN",
                     (unsigned)s_detect_diag);
        }

        if (state == WAKENET_DETECTED) {
            // 表情下载期间禁用唤醒（下载占用内存，唤醒后播放/重建可能分配失败
            // 导致异常会话；下载完成自动恢复）。日志节流 5 秒一次避免刷屏。
            if (gif_download_is_busy()) {
                static TickType_t s_last_ignored_log = 0;
                TickType_t now_t = xTaskGetTickCount();
                if ((now_t - s_last_ignored_log) * portTICK_PERIOD_MS > 5000) {
                    s_last_ignored_log = now_t;
                    ESP_LOGW(TAG, "表情下载中，忽略语音唤醒（下载完成后自动恢复）");
                }
                continue;
            }
            // 冷却检查（和按钮唤醒共用冷却机制）
            TickType_t now = xTaskGetTickCount();
            if (s_last_wakeup_trigger_tick != 0) {
                TickType_t elapsed_ms = (now - s_last_wakeup_trigger_tick) * portTICK_PERIOD_MS;
                if (elapsed_ms < WAKEUP_TRIGGER_COOLDOWN_MS) {
                    ESP_LOGW(TAG, "语音唤醒忽略: 冷却中 (%d/%d ms)",
                             (int)elapsed_ms, WAKEUP_TRIGGER_COOLDOWN_MS);
                    continue;
                }
            }
            s_last_wakeup_trigger_tick = now;

            ESP_LOGI(TAG, "=========================================");
            // 注意：wn9s 的唤醒词索引从 1 开始（0 会触发 "index is out of range"）
            ESP_LOGI(TAG, "检测到语音唤醒! (词: %s)",
                     s_wakenet->get_word_name(s_wakenet_data, 1));
            ESP_LOGI(TAG, "=========================================");

            // 设置唤醒事件
            xEventGroupSetBits(s_wakeup_event_group, WAKEUP_TRIGGERED_BIT);

            // 暂停语音唤醒，等待会话结束后由 wakeup_resume() 恢复
            s_wakenet_paused = true;
            s_wakenet_reading = false;
            ESP_LOGI(TAG, "语音唤醒已暂停，等待会话结束");
        }
    }

    free(feed_buf);
    s_wakenet_task_handle = NULL;
    vTaskDeleteWithCaps(NULL);  /* 配合 xTaskCreatePinnedToCoreWithCaps */
}

// ==================== 初始化和控制 API ====================

esp_err_t wakeup_init(void)
{
    ESP_LOGI(TAG, "初始化唤醒模块...");

    // 创建事件组
    s_wakeup_event_group = xEventGroupCreate();
    if (s_wakeup_event_group == NULL) {
        ESP_LOGE(TAG, "创建事件组失败（内存不足）");
        return ESP_ERR_NO_MEM;
    }

    // 初始化 WakeNet（纯 wakenet 接口，对齐 xiaozhi-esp32 C3 方案）
    ESP_LOGI(TAG, "初始化 WakeNet (纯 wakenet 接口)...");

    // 1. 从分区加载模型列表
    s_models = esp_srmodel_init("model");
    if (s_models == NULL) {
        ESP_LOGE(TAG, "加载 SR 模型失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "SR 模型加载成功，共 %d 个模型", s_models->num);

    // 2. 过滤出 WakeNet 模型
    s_model_name = esp_srmodel_filter(s_models, ESP_WN_PREFIX, NULL);
    if (s_model_name == NULL) {
        ESP_LOGE(TAG, "未找到 WakeNet 模型!");
        goto fail;
    }

    // 3. 获取 WakeNet 接口
    s_wakenet = esp_wn_handle_from_name(s_model_name);
    if (s_wakenet == NULL) {
        ESP_LOGE(TAG, "获取 WakeNet 接口失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 模型: %s (灵敏度 DET_MODE_95)", s_model_name);

    // 4. 创建 WakeNet 实例（激活缓冲 ~80KB）
    // 内存优化：会话期间 wakeup_pause 会 destroy 释放该内存给音频播放，
    // wakeup_resume 时重建（见 wakeup_pause/wakeup_resume）
    s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
    if (s_wakenet_data == NULL) {
        ESP_LOGE(TAG, "WakeNet 创建失败!");
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 创建成功");
    wakeup_apply_det_threshold();

    // 为 WakeNet 创建 I2S 通道
    ESP_LOGI(TAG, "初始化 WakeNet I2S 通道...");
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    // DMA 缓冲区：与 xiaozhi 一致（6 描述符 × 240 帧），默认 2 描述符太小易欠载
    chan_cfg.dma_desc_num = 6;
    chan_cfg.dma_frame_num = 240;
    esp_err_t i2s_err = ESP_OK;

#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工方案：单 I2S 控制器同时驱动 ADC（麦克风）和 DAC（扬声器）
    // TX 和 RX 共享 BCLK/WS/MCLK，ES8311 只有一组 I2S 总线
    ESP_LOGI(TAG, "ES8311 全双工：创建 TX+RX 通道 (I2S_NUM_0)");
    i2s_err = i2s_new_channel(&chan_cfg, &s_spk_tx_handle, &s_wakenet_mic_handle);
#else
    // I2S 直连方案：仅创建 RX 通道（扬声器使用独立的 I2S_NUM_1）
    i2s_err = i2s_new_channel(&chan_cfg, NULL, &s_wakenet_mic_handle);
#endif
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "创建 I2S 通道失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

#if defined(AUDIO_SCHEME_ES8311)
    // ---- ES8311 全双工：先初始化 TX（设置 MCLK/BCLK/WS 引脚），再初始化 RX（共享时钟） ----
    // TX：扬声器通道（DAC），设置主时钟和 BCLK/WS 引脚
    // 引脚从板级配置获取（es8311_cfg + spk_i2s_*）
    const board_config_t *bcfg = board_get_config();
    i2s_std_config_t tx_cfg = {
        .clk_cfg = {
            .sample_rate_hz = SPK_SAMPLE_RATE,
            .clk_src = I2S_CLK_SRC_DEFAULT,
            .mclk_multiple = I2S_MCLK_MULTIPLE_256,  /* 对齐 xiaozhi: 256× (16k→4.096MHz) */
        },
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_BOTH,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            .left_align = true,   // 标准 I2S 左对齐（与 xiaozhi/es8311 一致，right_align 会致 ES8311 DAC 收错数据）
            .big_endian = false,
            .bit_order_lsb = false,
        },
        .gpio_cfg = {
            .mclk = bcfg->es8311_cfg->mclk_pin,
            .bclk = bcfg->spk_i2s_bck,
            .ws = bcfg->spk_i2s_ws,
            .dout = bcfg->spk_i2s_data,
            .din = I2S_GPIO_UNUSED,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    i2s_err = i2s_channel_init_std_mode(s_spk_tx_handle, &tx_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "TX I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // RX：麦克风通道（ADC），共享 BCLK/WS，仅配置 DIN 引脚
    // 关键：RX 的 mclk_multiple 必须与 TX 一致！
    // slot 配置也必须与 TX 完全一致（left_align 等），否则 ADC 数据对齐错误
    i2s_std_config_t rx_cfg = {
        .clk_cfg = {
            .sample_rate_hz = 16000,  // WakeNet 要求 16kHz
            .clk_src = I2S_CLK_SRC_DEFAULT,
            .mclk_multiple = I2S_MCLK_MULTIPLE_256,  /* 必须与 TX 一致！ */
        },
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_LEFT,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            .left_align = true,    // 与 TX 一致，ES8311 ADC 输出左对齐数据
            .big_endian = false,
            .bit_order_lsb = false,
        },
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = I2S_GPIO_UNUSED,   // 共享 TX 的 BCLK
            .ws = I2S_GPIO_UNUSED,     // 共享 TX 的 WS
            .dout = I2S_GPIO_UNUSED,
            .din = bcfg->mic_i2s_data,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    i2s_err = i2s_channel_init_std_mode(s_wakenet_mic_handle, &rx_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "RX I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // 使能 TX 和 RX（全双工同时工作）
    i2s_err = i2s_channel_enable(s_spk_tx_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "TX I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    i2s_err = i2s_channel_enable(s_wakenet_mic_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "RX I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }

    // MCLK 已由 I2S TX 通道稳定输出，让 ES8311 锁存时钟并恢复 ADC/DAC。
    // ES8311 的寄存器配置（含 CSM 使能）已在 main.c 的 es8311_init() 中完成，
    // 但当时 MCLK 未运行，CSM 无法锁定。现在 MCLK 稳定输出，调用 es8311_power_up()
    // 重新锁存时钟，否则 DAC 时钟错乱 → 巨大电流声 + 无收音。
    // 注意：此顺序（先 es8311_init 配寄存器，再启动 MCLK 后 power_up）用户实测验证可用，
    // 不要改成 MCLK 运行后再完整 init（会导致无法唤醒/收音/播放）。
    if (es8311_is_initialized()) {
        vTaskDelay(pdMS_TO_TICKS(50));  // 等 MCLK 稳定
        es8311_power_up();
        es8311_set_format_16bit_i2s();  // MCLK 稳定后重新确认 REG09/0A 格式（MCLK 未运行时可能读回 0xFF）
        es8311_set_mic_gain(36);   // 重新设置麦克风增益（power_up 会重置寄存器）
        ESP_LOGI(TAG, "ES8311 时钟已锁存（MCLK 稳定后 power_up）");
    } else {
        // main.c 中初始化失败（软重启后 I2C 不响应等），MCLK 运行后再重试一次完整初始化
        ESP_LOGW(TAG, "ES8311 未初始化(MCLK 已运行)，尝试重新初始化...");
        const es8311_config_t *ecfg = bcfg->es8311_cfg;
        esp_err_t es_err = es8311_init(ecfg->i2c_port,
                                       ecfg->i2c_sda,
                                       ecfg->i2c_scl,
                                       ecfg->i2c_addr,
                                       ecfg->mclk_freq,
                                       SPK_SAMPLE_RATE);
        if (es_err == ESP_OK) {
            es8311_set_mic_gain(36);
            ESP_LOGI(TAG, "ES8311 重新初始化成功（MCLK 运行后恢复）");
        } else {
            ESP_LOGE(TAG, "ES8311 重新初始化仍失败: %s（音频不可用，建议断电重启）",
                     esp_err_to_name(es_err));
        }
    }

    ESP_LOGI(TAG, "ES8311 全双工 I2S 初始化完成 (TX+RX, 16kHz, MCLK=4.096MHz)");
#else
    // ---- I2S 直连方案：仅 RX（麦克风），扬声器在 audio.c 中用 I2S_NUM_1 ----
    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(16000),  // WakeNet 要求 16kHz
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_mode = I2S_SLOT_MODE_MONO,
            .slot_mask = I2S_STD_SLOT_LEFT,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,},
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = board_get_config()->mic_i2s_bck,
            .ws = board_get_config()->mic_i2s_ws,
            .dout = I2S_GPIO_UNUSED,
            .din = board_get_config()->mic_i2s_data,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };

    i2s_err = i2s_channel_init_std_mode(s_wakenet_mic_handle, &std_cfg);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "I2S 标准模式初始化失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    i2s_err = i2s_channel_enable(s_wakenet_mic_handle);
    if (i2s_err != ESP_OK) {
        ESP_LOGE(TAG, "I2S 通道使能失败: %s", esp_err_to_name(i2s_err));
        goto fail;
    }
    ESP_LOGI(TAG, "WakeNet 专用 I2S 麦克风初始化完成 (16kHz)");
#endif

    // 创建 I2S 互斥锁（用 Binary 而非 Mutex，避免跨任务 Give 触发优先级继承断言）
    s_i2s_mutex = xSemaphoreCreateBinary();
    if (s_i2s_mutex == NULL) {
        ESP_LOGE(TAG, "创建 I2S 互斥锁失败");
        goto fail;
    }
    xSemaphoreGive(s_i2s_mutex);  // 初始化为"已释放"状态

    ESP_LOGI(TAG, "唤醒模块初始化完成");
    // 打印实际加载的唤醒词模型（从 esp-sr 模型列表读取，避免硬编码与实际模型不符）
    if (s_models && s_models->num > 0) {
        char *wake_words = esp_srmodel_get_wake_words(s_models, s_models->model_name[0]);
        ESP_LOGI(TAG, "唤醒词模型: %s (唤醒词: %s)",
                 s_models->model_name[0], wake_words ? wake_words : "未知");
    }
    return ESP_OK;

fail:
    // 初始化失败，按逆序清理已分配资源，避免泄漏
    if (s_i2s_mutex) { vSemaphoreDelete(s_i2s_mutex); s_i2s_mutex = NULL; }
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：TX 和 RX 是一对，都需要清理
    if (s_spk_tx_handle) { i2s_channel_disable(s_spk_tx_handle); i2s_del_channel(s_spk_tx_handle); s_spk_tx_handle = NULL; }
#endif
    if (s_wakenet_mic_handle) { i2s_channel_disable(s_wakenet_mic_handle); i2s_del_channel(s_wakenet_mic_handle); s_wakenet_mic_handle = NULL; }
    if (s_wakenet_data && s_wakenet) { s_wakenet->destroy(s_wakenet_data); s_wakenet_data = NULL; }
    if (s_models) { esp_srmodel_deinit(s_models); s_models = NULL; }
    return ESP_FAIL;
}

esp_err_t wakeup_start(void)
{
    if (s_wakeup_running) {
        ESP_LOGW(TAG, "唤醒检测已在运行");
        return ESP_OK;
    }

    ESP_LOGI(TAG, "启动唤醒检测...");
    s_wakeup_running = true;

    // 启动按钮唤醒任务
    BaseType_t task_ret = xTaskCreatePinnedToCore(
        button_wakeup_task,
        "btn_wakeup",
        4096,
        NULL,
        TASK_PRIO_WAKEUP,
        &s_wakeup_task_handle,
        BOARD_TASK_CORE_1  // 双核：核心1；单核：核心0
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "创建按钮唤醒任务失败");
        s_wakeup_running = false;
        return ESP_FAIL;
    }

    // 启动语音唤醒任务（有 PSRAM 时栈放 PSRAM，无 PSRAM 回退内部 RAM）
    task_ret = xTaskCreatePinnedToCoreWithCaps(
        wakenet_task,
        "wakenet",
#ifdef CONFIG_IDF_TARGET_ESP32C3
        6144,   // C3 无 PSRAM，栈走内部 RAM，收紧以省堆
#else
        8192,   // 恢复 8192（有 PSRAM 时栈不受内部 RAM 限制）
#endif
        NULL,
        TASK_PRIO_WAKEUP,
        &s_wakenet_task_handle,
        BOARD_TASK_CORE_0,  // 双核：核心0（与按钮任务分核运行）；单核：核心0
        BOARD_STACK_CAPS_AUDIO
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "创建语音唤醒任务失败");
        // 按钮唤醒仍然可用，不返回错误
    } else {
        ESP_LOGI(TAG, "语音唤醒任务创建成功（PSRAM 栈）");
    }

    ESP_LOGI(TAG, "唤醒检测已启动（按钮 + 语音）");
    return ESP_OK;
}

esp_err_t wakeup_stop(void)
{
    if (!s_wakeup_running) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "停止唤醒检测...");
    s_wakeup_running = false;

    // 等待任务结束（最多等待 5 秒，超时后记录警告并继续，避免无限阻塞）
    const int WAKEUP_STOP_TIMEOUT_MS = 5000;
    int waited_ms = 0;
    while (s_wakeup_task_handle != NULL || s_wakenet_task_handle != NULL) {
        if (waited_ms >= WAKEUP_STOP_TIMEOUT_MS) {
            ESP_LOGW(TAG, "等待唤醒任务退出超时(%dms)，强制继续停止流程 (btn=%p, wakenet=%p)",
                     WAKEUP_STOP_TIMEOUT_MS, s_wakeup_task_handle, s_wakenet_task_handle);
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
        waited_ms += 10;
    }

    // 销毁 WakeNet 实例
    if (s_wakenet_data && s_wakenet) {
        s_wakenet->destroy(s_wakenet_data);
        s_wakenet_data = NULL;
    }

    // 释放模型列表
    if (s_models) {
        esp_srmodel_deinit(s_models);
        s_models = NULL;
    }

    // 关闭 WakeNet 专用 I2S 麦克风
    if (s_wakenet_mic_handle) {
        i2s_channel_disable(s_wakenet_mic_handle);
        i2s_del_channel(s_wakenet_mic_handle);
        s_wakenet_mic_handle = NULL;
    }
#if defined(AUDIO_SCHEME_ES8311)
    // ES8311 全双工：关闭 TX 通道（扬声器）
    if (s_spk_tx_handle) {
        i2s_channel_disable(s_spk_tx_handle);
        i2s_del_channel(s_spk_tx_handle);
        s_spk_tx_handle = NULL;
    }
#endif

    ESP_LOGI(TAG, "唤醒检测已停止");
    return ESP_OK;
}

void wakeup_pause(void)
{
    // 置暂停标志（幂等：语音唤醒路径 wakenet_task 已自行置位，此处可能非首次）
    bool already_paused = s_wakenet_paused;
    s_wakenet_paused = true;

    // 等待 WakeNet 真正停止读取 I2S，避免与 mic_task 竞争
    if (!already_paused) {
        int wait = 0;
        while (s_wakenet_reading && wait < 20) {  // 最多等 200ms
            vTaskDelay(pdMS_TO_TICKS(10));
            wait++;
        }
        // 超时后再次检查：若仍正在读取，记录警告并额外等待更长时间
        if (s_wakenet_reading) {
            ESP_LOGW(TAG, "语音唤醒暂停超时(200ms)，s_wakenet_reading 仍为 true，额外等待 500ms");
            int wait2 = 0;
            while (s_wakenet_reading && wait2 < 50) {  // 额外等待 500ms
                vTaskDelay(pdMS_TO_TICKS(10));
                wait2++;
            }
        }
    } else {
        // wakenet_task 自行暂停（语音唤醒打断路径）：读取可能仍在进行，同样等它停
        int wait = 0;
        while (s_wakenet_reading && wait < 20) {
            vTaskDelay(pdMS_TO_TICKS(10));
            wait++;
        }
    }
    // 获取 I2S 互斥锁，阻止 WakeNet 读 I2S（仅首次暂停时拿，锁一直持有到
    // wakeup_resume() 释放）。重复调用 pause（如"02"连续对话流程的 iat_start
    // 前再次 pause）时锁已被本模块持有，FreeRTOS 互斥锁不可重入，
    // 再 take 会 1 秒超时刷 E 日志——已暂停状态下无需再拿。
    // 使用有限超时（1秒）而非 portMAX_DELAY，避免在 WakeNet 卡死时永久阻塞导致死锁
    if (s_i2s_mutex && !already_paused) {
        if (xSemaphoreTake(s_i2s_mutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
            ESP_LOGE(TAG, "wakeup_pause 获取 I2S 互斥锁超时(1s)，可能 WakeNet 任务卡死");
        }
    }
    if (s_wakenet_reading) {
        ESP_LOGE(TAG, "语音唤醒暂停失败：s_wakenet_reading 仍为 true，I2S 可能存在竞争");
    } else {
        ESP_LOGI(TAG, "语音唤醒已暂停");
    }

    // 内存优化：销毁 WakeNet 实例，把激活缓冲还给堆，供音频播放使用。
    // C3（无 PSRAM）：WakeNet 激活缓冲 ~80KB + MP3 解码器 45KB 都在内部 RAM，
    // 无法共存，必须销毁以释放内存给 MP3 解码器（否则播放无声）。
    // 非 C3（有 PSRAM）：WakeNet 激活缓冲在 PSRAM，MP3 解码器用内部 RAM，
    // 无内存冲突，保留实例可避免"02"连续对话中 iat_end 未到达时 WakeNet 永久失效。
    // 注意：即使条件跳过销毁，I2S 互斥锁仍被持有，wakenet_task 不会读取 I2S。
#if defined(CONFIG_IDF_TARGET_ESP32C3)
    if (s_wakenet && s_wakenet_data) {
        s_wakenet->destroy(s_wakenet_data);
        s_wakenet_data = NULL;
        ESP_LOGI(TAG, "WakeNet 实例已销毁，释放堆给播放使用 (剩余堆: %d bytes)",
                 (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    }
#else
    ESP_LOGI(TAG, "WakeNet 实例保留（PSRAM 模式，无需释放内存，剩余堆: %d bytes, PSRAM: %d bytes)",
             (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
             (int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif
}

// WakeNet 重建失败重试任务：
// 会话异常结束时（如服务器"Wake audio failed"后不发 session_end），设备端只能靠
// 看门狗/超时检测恢复唤醒。若此刻内存不足（如 GIF 表情下载占用中），create 失败，
// 语音唤醒会永久失效（实测必须重启）。本任务每 10 秒重试重建，直到成功或系统停止。
// 唤醒灵敏度：WakeNet 模型默认阈值 ~0.63，对部分环境/扬声器偏严（需大声喊才能唤醒）。
// 通过 set_det_threshold 调低阈值提升灵敏度（合法范围 0.4~0.9999，越低越灵敏、误唤醒率越高）。
// 0.55 为当前取值：上一版 0.60 在 TTS 播放中（扬声器回声干扰）打断不灵敏。0.55 在降噪环境下
// 误唤醒率仍可接受，但显著提升打断成功率。若误唤醒过多可回 0.60，难唤醒可降至 0.50。
#define WAKENET_DET_THRESHOLD 0.55f

// 调低 WakeNet 触发阈值（须在 create 之后调用；wakeup_resume/延迟重试重建后阈值会重置，需重新设置）
static void wakeup_apply_det_threshold(void)
{
    if (!s_wakenet || !s_wakenet_data) return;
    int wn = s_wakenet->get_word_num(s_wakenet_data);
    if (wn <= 0) return;
    for (int i = 0; i < wn; i++) {
        int idx = i + 1;  // 唤醒词索引从 1 开始
        float old_t = s_wakenet->get_det_threshold(s_wakenet_data, idx);
        s_wakenet->set_det_threshold(s_wakenet_data, WAKENET_DET_THRESHOLD, idx);
        float new_t = s_wakenet->get_det_threshold(s_wakenet_data, idx);
        const char *wname = s_wakenet->get_word_name(s_wakenet_data, idx);
        ESP_LOGI(TAG, "唤醒阈值[%s]: %.3f → %.3f", wname ? wname : "?", old_t, new_t);
    }
}

static void wakenet_rebuild_task(void *arg)
{
    // 快速重试：前 5 次每秒重试（快速恢复打断能力），之后每 10 秒重试
    int retry_count = 0;
    const int FAST_RETRY_LIMIT = 5;
    const TickType_t FAST_RETRY_DELAY = pdMS_TO_TICKS(1000);
    const TickType_t SLOW_RETRY_DELAY = pdMS_TO_TICKS(10000);
    while (s_wakeup_running) {
        TickType_t delay = (retry_count < FAST_RETRY_LIMIT) ? FAST_RETRY_DELAY : SLOW_RETRY_DELAY;
        vTaskDelay(delay);
        retry_count++;
        if (!s_wakeup_running) break;
        if (s_wakenet_data != NULL) break;          // 已重建成功（可能由其他路径重建）
        if (s_wakenet_paused) continue;             // 会话中，等 resume
        if (s_wakenet == NULL || s_model_name == NULL) break;  // 模块已停
        s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
        if (s_wakenet_data != NULL) {
            wakeup_apply_det_threshold();
            ESP_LOGI(TAG, "WakeNet 重建成功（延迟重试恢复，重试次数=%d）", retry_count);
            break;
        }
        if (retry_count <= FAST_RETRY_LIMIT) {
            ESP_LOGW(TAG, "WakeNet 重建重试 #%d 失败（堆不足），1 秒后再试, 剩余堆: %d bytes",
                     retry_count, (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
        } else {
            ESP_LOGW(TAG, "WakeNet 重建重试 #%d 失败（堆不足），10 秒后再试", retry_count);
        }
    }
    vTaskDelete(NULL);
}

void wakeup_resume(void)
{
    if (s_wakenet_paused) {
        s_wakenet_paused = false;
        if (s_i2s_mutex) {
            xSemaphoreGive(s_i2s_mutex);
        }
        // 内存优化：重建被 wakeup_pause 销毁的 WakeNet 实例，恢复语音唤醒
        // 播放结束后 MP3 解码器已释放（spk_task drain 时释放），堆充足
        if (s_wakenet_data == NULL && s_wakenet != NULL && s_model_name != NULL) {
            ESP_LOGI(TAG, "WakeNet 创建中... 剩余堆: %d bytes",
                     (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
            s_wakenet_data = s_wakenet->create(s_model_name, DET_MODE_95);
            if (s_wakenet_data == NULL) {
                ESP_LOGE(TAG, "WakeNet 重建失败（堆不足），启动延迟重试... 剩余堆: %d bytes",
                         (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
                // 不放弃：启动后台重试任务（GIF 下载等内存占用结束后即可恢复），
                // 否则异常会话结束后语音唤醒永久失效，必须重启
                xTaskCreate(wakenet_rebuild_task, "wn_rebuild", 4096, NULL, 2, NULL);
            } else {
                wakeup_apply_det_threshold();
                ESP_LOGI(TAG, "WakeNet 重建成功，语音唤醒已恢复 (剩余堆: %d bytes)",
                         (int)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
            }
        } else if (s_wakenet_data != NULL) {
            ESP_LOGI(TAG, "语音唤醒已恢复（WakeNet 实例已存在，未重建）");
        } else {
            ESP_LOGI(TAG, "语音唤醒标记已恢复（WakeNet 接口未就绪，等待重建任务）");
        }
    }
}

// 清除唤醒冷却：唤醒触发后发送失败（WS 未连接等）时调用，
// 让用户在网络恢复后能立即再次唤醒，不被 8 秒冷却惩罚
// （否则断线期间每次唤醒都失败+冷却，感知为"永远唤不醒"）
void wakeup_clear_cooldown(void)
{
    s_last_wakeup_trigger_tick = 0;
    ESP_LOGI(TAG, "唤醒冷却已清除（上次唤醒发送失败）");
}

void *wakeup_get_mic_handle(void)
{
    return (void *)s_wakenet_mic_handle;
}

void *wakeup_get_spk_handle(void)
{
    return (void *)s_spk_tx_handle;
}

bool wakeup_is_paused(void)
{
    return s_wakenet_paused && !s_wakenet_reading;
}
