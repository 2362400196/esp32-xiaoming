/**
 * extras_led.c - 板型扩展组件：状态 LED（LEDC PWM 调光）
 *
 * 演示 extras 组件完整链路的示例实现，接口说明见 extras_led.h。
 * 组件内部状态自持，所有回调可能来自不同任务（LEDC API 线程安全）。
 */

#include "extras_led.h"
#include "esp_log.h"
#include "driver/ledc.h"
#include "cJSON.h"
#include "esp_timer.h"

static const char *TAG = "extras_led";

#define LED_TIMER            LEDC_TIMER_0      // LEDC 定时器（避免与其他模块冲突时再改）
#define LED_CHANNEL          LEDC_CHANNEL_0
#define LED_FREQ_HZ          5000              // 5kHz，无可见频闪
#define LED_DUTY_RES         LEDC_TIMER_10_BIT // 10bit = 0-1023
#define LED_DUTY_MAX         ((1 << 10) - 1)

// 运行状态（init 在 app_main 单线程阶段调用，之后仅被命令/事件回调读写）
static const led_extra_config_t *s_cfg = NULL;
static bool     s_on = false;
static int      s_brightness = 100;  // 0-100
static esp_timer_handle_t s_blink_timer = NULL;
static int      s_blink_count = 0;   // 剩余翻转次数（双闪 = 4 次翻转）

// 当前占空比（含 active_low 反相）
static uint32_t led_target_duty(void)
{
    uint32_t duty = s_on ? (uint32_t)(LED_DUTY_MAX * s_brightness / 100) : 0;
    if (s_cfg && s_cfg->active_low) {
        duty = LED_DUTY_MAX - duty;
    }
    return duty;
}

static void led_apply(void)
{
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LED_CHANNEL, led_target_duty());
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LED_CHANNEL);
}

// 闪烁定时器回调：每 100ms 翻转一次开/关，翻转次数用尽后恢复稳态
static void blink_timer_cb(void *arg)
{
    if (!s_cfg) return;
    s_blink_count--;
    // 奇数次翻转 = 灭（从常态亮开始闪），偶数次 = 亮（回到常态）
    s_on = (s_blink_count % 2 == 0);
    led_apply();
    if (s_blink_count > 0) {
        esp_timer_start_once(s_blink_timer, 100000);
    }
}

esp_err_t extras_led_init(const void *config)
{
    s_cfg = (const led_extra_config_t *)config;
    if (!s_cfg || s_cfg->gpio < 0) {
        return ESP_ERR_INVALID_ARG;
    }

    ledc_timer_config_t timer_cfg = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .timer_num       = LED_TIMER,
        .duty_resolution = LED_DUTY_RES,
        .freq_hz         = LED_FREQ_HZ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer_cfg);
    if (err != ESP_OK) return err;

    ledc_channel_config_t ch_cfg = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = LED_CHANNEL,
        .timer_sel  = LED_TIMER,
        .intr_type  = LEDC_INTR_DISABLE,
        .gpio_num   = s_cfg->gpio,
        .duty       = 0,
        .hpoint     = 0,
    };
    err = ledc_channel_config(&ch_cfg);
    if (err != ESP_OK) return err;

    // 默认常亮（低亮度作待机指示，可由 led_set 调整）
    s_on = true;
    s_brightness = 30;
    led_apply();

    esp_timer_create_args_t targs = {
        .callback = blink_timer_cb,
        .name = "led_blink",
    };
    err = esp_timer_create(&targs, &s_blink_timer);
    if (err != ESP_OK) return err;

    ESP_LOGI(TAG, "LED 扩展组件就绪 (GPIO%d, %s)",
             s_cfg->gpio, s_cfg->active_low ? "低电平点亮" : "高电平点亮");
    return ESP_OK;
}

void extras_led_deinit(void)
{
    if (s_blink_timer) {
        esp_timer_stop(s_blink_timer);
        esp_timer_delete(s_blink_timer);
        s_blink_timer = NULL;
    }
    if (s_cfg) {
        ledc_stop(LEDC_LOW_SPEED_MODE, LED_CHANNEL, s_cfg->active_low ? LED_DUTY_MAX : 0);
    }
    s_cfg = NULL;
}

esp_err_t extras_led_command(const char *cmd, const char *args,
                             char *resp, size_t resp_len)
{
    if (!s_cfg) return ESP_ERR_INVALID_STATE;

    if (strcmp(cmd, "led_set") == 0) {
        cJSON *json = args ? cJSON_Parse(args) : NULL;
        if (!json) {
            snprintf(resp, resp_len, "{\"success\":false,\"message\":\"invalid args\"}");
            return ESP_ERR_INVALID_ARG;
        }
        cJSON *j_on = cJSON_GetObjectItem(json, "on");
        cJSON *j_br = cJSON_GetObjectItem(json, "brightness");
        if (j_on && cJSON_IsBool(j_on)) {
            s_on = cJSON_IsTrue(j_on);
        }
        if (j_br && cJSON_IsNumber(j_br)) {
            int br = j_br->valueint;
            if (br < 0) br = 0;
            if (br > 100) br = 100;
            s_brightness = br;
        }
        cJSON_Delete(json);
        led_apply();
        ESP_LOGI(TAG, "led_set: on=%d brightness=%d", s_on, s_brightness);
        snprintf(resp, resp_len, "{\"success\":true,\"on\":%s,\"brightness\":%d}",
                 s_on ? "true" : "false", s_brightness);
        return ESP_OK;
    }

    if (strcmp(cmd, "led_get") == 0) {
        snprintf(resp, resp_len, "{\"success\":true,\"on\":%s,\"brightness\":%d}",
                 s_on ? "true" : "false", s_brightness);
        return ESP_OK;
    }

    return ESP_ERR_NOT_FOUND;  // 不是本组件的命令，交给下一个组件
}

void extras_led_on_event(board_event_t event, void *data)
{
    (void)data;
    if (!s_cfg || !s_blink_timer) return;

    // 唤醒时双闪两次提示（非阻塞：esp_timer 每 100ms 翻转一次）
    if (event == BOARD_EVENT_WAKEUP && s_blink_count <= 0) {
        s_blink_count = 4;
        s_on = false;
        led_apply();
        esp_timer_start_once(s_blink_timer, 100000);
    }
}
