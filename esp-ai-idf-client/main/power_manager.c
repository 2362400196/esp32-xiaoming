/**
 * power_manager.c - 功耗管理模块实现
 *
 * 移植自 xiaozhi-esp32 的 AudioService 功耗管理机制。
 * 参考：audio_service.cc 的 CheckAndUpdateAudioPowerState()
 *
 * 本板 pa_pin=-1（NS4150B 常通，无 PA GPIO），空闲省电仅依赖 ES8311 DAC 静音。
 * 注意：DAC 静音/解静音会影响播放，改动需谨慎验证。
 */

#include "power_manager.h"
#include "config.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_pm.h"
#include "driver/gpio.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "eeui_port.h"  /* eeui_port_screensaver_set：待机屏保 */
#include "network_audio.h"  /* network_audio_is_playing：音乐播放状态检测 */

#if defined(AUDIO_SCHEME_ES8311)
#include "audio_codec/es8311.h"
#endif

static const char *TAG = "power_mgr";

// 空闲超时：15 秒无音频输出 → 关闭 PA
#define OUTPUT_IDLE_TIMEOUT_MS    15000
// 检查间隔：1 秒
#define POWER_CHECK_INTERVAL_MS   1000
// PA 启用延时：DAC 恢复后等待稳定再开 PA，避免爆音
#define PA_ENABLE_DELAY_MS        10

// 屏保配置（默认关闭，30 秒超时）
static bool s_screensaver_enabled = false;
static int s_screensaver_timeout_sec = 30;

static esp_timer_handle_t s_timer = NULL;
static SemaphoreHandle_t s_mutex = NULL;

// 时间戳：使用 TickType_t（32 位原子读写，无需互斥锁）
static volatile TickType_t s_last_output_tick = 0;
// 输出使能状态：bool 在 32 位平台原子读写
static volatile bool s_output_enabled = true;
static bool s_initialized = false;

// 会话活跃状态（省电切换）：
// 待机（无会话）：WiFi MIN_MODEM（modem sleep，间隔唤醒收包，keepalive 30s 无压力）
// 活跃（唤醒/ASR/TTS）：WiFi NONE（收发低延迟）
// 语音唤醒（纯 WakeNet）走本地 I2S，不依赖 WiFi 状态，任意时刻都能唤醒；
// modem sleep 下发送数据会立即唤醒 WiFi，唤醒→发 start 延迟 <50ms。
static volatile bool s_active = false;
// 屏保延迟计时：进入待机的时间戳 + 屏保是否已显示（避免对话结束立即黑屏）
static volatile TickType_t s_idle_since_tick = 0;
static bool s_screensaver_shown = false;

/**
 * 内部：执行硬件禁用（PA off + DAC mute）
 * 调用者必须持有 s_mutex
 */
static void do_disable_output(void)
{
    if (!s_output_enabled) return;

#if defined(AUDIO_SCHEME_ES8311)
    // 1. DAC 静音（先于 PA 关闭，避免爆音）
    if (es8311_is_initialized()) {
        es8311_set_output_enabled(false);
    }
    // 2. PA 功放关闭（NS4150B）— GPIO 操作
    int pa_pin = board_get_config()->es8311_cfg->pa_pin;
    if (pa_pin >= 0) {
        gpio_set_level(pa_pin, 0);
    }
#endif
    s_output_enabled = false;
    ESP_LOGI(TAG, "音频输出已关闭（空闲省电：PA off + DAC mute）");
}

/**
 * 内部：执行硬件启用（DAC unmute + PA on）
 * 调用者必须持有 s_mutex
 */
static void do_enable_output(void)
{
    if (s_output_enabled) return;

#if defined(AUDIO_SCHEME_ES8311)
    // 1. DAC 解静音（先于 PA 开启，让 DAC 输出稳定）
    if (es8311_is_initialized()) {
        es8311_set_output_enabled(true);
        // 2. 等待 DAC 输出稳定
        vTaskDelay(pdMS_TO_TICKS(PA_ENABLE_DELAY_MS));
    }
    // 3. PA 功放开启（NS4150B）
    int pa_pin = board_get_config()->es8311_cfg->pa_pin;
    if (pa_pin >= 0) {
        gpio_set_level(pa_pin, 1);
    }
#endif
    s_output_enabled = true;
    ESP_LOGI(TAG, "音频输出已恢复（PA on + DAC unmute）");
}

/**
 * 定时器回调：每秒检查输出空闲状态 + 屏保延迟触发
 */
static void power_check_callback(void *arg)
{
    if (s_mutex == NULL) return;

    // 非阻塞获取互斥锁：如果 enable/disable 正在进行，跳过本次检查
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(100)) != pdTRUE) return;

    if (s_output_enabled) {
        TickType_t now = xTaskGetTickCount();
        uint32_t idle_ms = (now - s_last_output_tick) * portTICK_PERIOD_MS;
        if (idle_ms > OUTPUT_IDLE_TIMEOUT_MS) {
            ESP_LOGI(TAG, "输出空闲 %ums，关闭 PA", idle_ms);
            do_disable_output();
        }
    }

    // 屏保退出兜底：屏保被禁用时，每次 timer 回调都尝试退出屏保。
    // 不依赖 s_screensaver_shown 标志（该标志可能在会话结束时被误置为 false，
    // 导致屏保 UI 仍在显示但软件无法退出），eeui_port_screensaver_set(false)
    // 内部是幂等的——屏保已退出时立即返回 true。
    if (!s_screensaver_enabled) {
        if (eeui_port_screensaver_set(false)) {
            if (s_screensaver_shown) {
                s_screensaver_shown = false;
                ESP_LOGI(TAG, "屏保已禁用，在定时器中成功退出");
            }
        } else {
            ESP_LOGW(TAG, "屏保已禁用但退出失败（LVGL 锁竞争），下次重试");
        }
    }

    // 屏保延迟触发：进入待机（等待唤醒）后延迟指定秒数才显示，
    // （对话结束/开机完成先保持正常表情显示，避免屏幕突然变黑）
    // 注意：音乐播放时不进入屏保（用户听歌时需要看到歌词/进度等信息）
    // 可通过 screensaver_enabled 配置完全禁用屏保
    // 注意：此条件中的 s_screensaver_shown 仅在上述兜底退出成功后才可能为 false
    if (!s_active && !s_screensaver_shown && s_screensaver_enabled) {
        TickType_t now = xTaskGetTickCount();
        uint32_t idle_ms = (now - s_idle_since_tick) * portTICK_PERIOD_MS;
        uint32_t timeout_ms = (uint32_t)s_screensaver_timeout_sec * 1000;
        // 如果正在播放音乐，跳过屏保触发
        if (idle_ms > timeout_ms && !network_audio_is_playing()) {
            if (eeui_port_screensaver_set(true)) {
                s_screensaver_shown = true;
                ESP_LOGI(TAG, "待机 %ums 无交互，进入屏保", idle_ms);
            } else {
                ESP_LOGW(TAG, "进入屏保失败（LVGL 锁竞争），下次重试");
            }
        }
    }

    xSemaphoreGive(s_mutex);
}

esp_err_t power_manager_init(void)
{
    if (s_initialized) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "初始化功耗管理模块...");

    // CPU 动态降频（DFS）：空闲 80MHz / 忙时自动升回最高频率
    // 语音唤醒（纯 WakeNet 分块检测）在 80MHz 下有余量，忙时（WiFi 收发/
    // 播放/唤醒检测）esp_pm 自动升频，不影响唤醒与对话
#ifdef CONFIG_PM_ENABLE
    esp_pm_config_t pm_cfg = {
        .max_freq_mhz = CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,  // C3:160 / S3:240
        .min_freq_mhz = 80,
        .light_sleep_enable = false,  // 不开 light sleep：WakeNet 需持续运行
    };
    esp_err_t pm_ret = esp_pm_configure(&pm_cfg);
    if (pm_ret == ESP_OK) {
        ESP_LOGI(TAG, "CPU 动态降频已启用: %d/%dMHz (DFS)",
                 pm_cfg.max_freq_mhz, pm_cfg.min_freq_mhz);
    } else {
        ESP_LOGW(TAG, "esp_pm_configure 失败: %s（继续使用固定频率）",
                 esp_err_to_name(pm_ret));
    }
#else
    ESP_LOGW(TAG, "CONFIG_PM_ENABLE 未开启，DFS 不可用");
#endif

    s_mutex = xSemaphoreCreateMutex();
    if (s_mutex == NULL) {
        ESP_LOGE(TAG, "创建互斥锁失败");
        return ESP_ERR_NO_MEM;
    }

    // 初始状态：输出已使能（PA 在 audio_init 中已拉高）
    s_output_enabled = true;
    s_last_output_tick = xTaskGetTickCount();

    // 创建定时器（不启动，由 power_manager_start 启动）
    esp_timer_create_args_t timer_args = {
        .callback = power_check_callback,
        .arg = NULL,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "power_mgr",
        .skip_unhandled_events = true,
    };
    esp_err_t ret = esp_timer_create(&timer_args, &s_timer);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "创建定时器失败: %s", esp_err_to_name(ret));
        vSemaphoreDelete(s_mutex);
        s_mutex = NULL;
        return ret;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "功耗管理模块初始化完成（空闲超时: %ds）", OUTPUT_IDLE_TIMEOUT_MS / 1000);
    return ESP_OK;
}

esp_err_t power_manager_start(void)
{
    if (!s_initialized || s_timer == NULL) {
        ESP_LOGE(TAG, "功耗管理未初始化");
        return ESP_ERR_INVALID_STATE;
    }

    // 刷新时间戳，避免启动时立即触发关闭
    s_last_output_tick = xTaskGetTickCount();

    esp_err_t ret = esp_timer_start_periodic(s_timer, POWER_CHECK_INTERVAL_MS * 1000);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "启动定时器失败: %s", esp_err_to_name(ret));
        return ret;
    }

    // 系统启动完成进入待机：WiFi modem sleep（省电）。
    // 注意：不能依赖 power_manager_set_active(false)（s_active 初始即 false，
    // 幂等检查会跳过），必须在此显式切换一次，否则 WiFi 永远停在 NONE。
    s_active = false;
    wifi_set_power_save(true);
    // 屏保延迟触发：开机后先显示正常表情/状态，延迟 SCREENSAVER_DELAY_MS 后
    // 由 power_check_callback 切入屏保（避免开机立即黑屏）
    s_idle_since_tick = xTaskGetTickCount();
    s_screensaver_shown = false;

    ESP_LOGI(TAG, "功耗管理定时器已启动（每 %ds 检查）", POWER_CHECK_INTERVAL_MS / 1000);
    return ESP_OK;
}

void power_manager_notify_output(void)
{
    // 原子写 TickType_t，无需互斥锁
    // 仅在输出已使能时刷新（禁用状态下不刷新，避免定时器误判）
    s_last_output_tick = xTaskGetTickCount();
}

void power_manager_enable_output(void)
{
    if (s_mutex == NULL) return;

    xSemaphoreTake(s_mutex, portMAX_DELAY);

    if (!s_output_enabled) {
        do_enable_output();
    }
    // 无论是否刚刚启用，都刷新时间戳
    s_last_output_tick = xTaskGetTickCount();

    xSemaphoreGive(s_mutex);
}

bool power_manager_is_output_enabled(void)
{
    return s_output_enabled;
}

// ==================== 会话状态（省电切换）====================
void power_manager_set_active(bool active)
{
    if (s_active == active) return;
    s_active = active;
    wifi_set_power_save(!active);  // 待机开省电，活跃关省电
    // 会话边界清除 show_card 卡片（唤醒=新会话开始、回待机=会话结束，
    // 卡片让位恢复表情；会话内 TTS 播报等表情变化不清卡片）
    eeui_port_clear_cards();
    if (active) {
        // 活跃：立即退出屏保，恢复表情显示；重置屏保延迟计时
        // 不依赖 s_screensaver_shown 标志（该标志可能因之前退出失败而不准确），
        // eeui_port_screensaver_set(false) 内部幂等，屏保已退出时立即返回 true。
        if (eeui_port_screensaver_set(false)) {
            s_screensaver_shown = false;
        } else {
            ESP_LOGW(TAG, "活跃时退出屏保失败（LVGL 锁竞争），下次重试");
        }
        s_idle_since_tick = xTaskGetTickCount();
    } else {
        // 待机：不立即进屏保，记录待机起始时间（延迟 SCREENSAVER_DELAY_MS 由定时器触发）
        s_idle_since_tick = xTaskGetTickCount();
        // 注意：不要将 s_screensaver_shown 置为 false！
        // 如果屏保 UI 实际仍在显示（之前退出失败），s_screensaver_shown = true 是正确的，
        // 将其置为 false 会导致后续关闭屏保时无法触发退出逻辑。
    }
    ESP_LOGI(TAG, "会话状态: %s", active ? "活跃" : "待机");
}

void power_manager_set_screensaver_config(int enabled, int timeout_sec)
{
    if (enabled >= 0) {
        s_screensaver_enabled = (enabled == 1);
        // 如果用户关闭了屏保，立即尝试退出。
        // 不依赖 s_screensaver_shown 标志（该标志可能在会话结束时被误置为 false，
        // 导致屏保 UI 仍在显示但软件无法退出）。
        // eeui_port_screensaver_set(false) 内部幂等，屏保已退出时立即返回 true。
        if (!s_screensaver_enabled) {
            if (eeui_port_screensaver_set(false)) {
                s_screensaver_shown = false;
                ESP_LOGI(TAG, "屏保已退出（用户关闭屏保）");
            } else {
                ESP_LOGW(TAG, "立即退出屏保失败（LVGL 锁竞争），将在定时器中重试");
            }
        }
    }
    if (timeout_sec > 0) {
        s_screensaver_timeout_sec = timeout_sec;
    }
    ESP_LOGI(TAG, "屏保配置已更新: %s, 超时=%ds",
             s_screensaver_enabled ? "开启" : "关闭", s_screensaver_timeout_sec);
}
