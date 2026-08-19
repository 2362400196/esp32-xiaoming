/**
 * hardware_io.c - 硬件 IO 控制（移植自 Arduino esp-ai 客户端的 hardware-fns 指令）
 *
 * 对应 Arduino libraries/esp-ai/src/webSocketEvent/main.cpp 中 type == "hardware-fns" 分支:
 *   pinMode / digitalWrite / digitalRead / analogWrite / analogRead / ledcWrite
 *
 * ESP-IDF 对应 API:
 *   pinMode       → gpio_config / ledc_timer_config + ledc_channel_config
 *   digitalWrite  → gpio_set_level
 *   digitalRead   → gpio_get_level (加入定时上报列表)
 *   analogWrite   → ledc_set_duty + ledc_update_duty
 *   analogRead    → adc_oneshot_read (加入定时上报列表)
 *   ledcWrite     → ledc_set_duty (角度→占空比，舵机控制)
 */
#include "hardware_io.h"
#include "config.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "hardware_io";

// 互斥锁：保护 s_ledc_channels / s_digital_read_pins / s_analog_read_pins 等静态数组
// hardware_io_handle_fns 从 WebSocket 事件任务调用，hardware_io_report_readings 从 main 任务调用
static SemaphoreHandle_t s_io_mutex = NULL;

// 确保互斥锁已创建（懒初始化，首次调用时创建）
static void ensure_io_mutex(void)
{
    if (s_io_mutex == NULL) {
        s_io_mutex = xSemaphoreCreateMutex();
        if (s_io_mutex == NULL) {
            ESP_LOGE(TAG, "创建 IO 互斥锁失败");
        }
    }
}

// ==================== LEDC 通道状态表 ====================
// Arduino ledcSetup/ledcAttachPin 在 ESP-IDF 中需 ledc_timer_config + ledc_channel_config
// 维护 pin → channel 映射，analogWrite 时通过 pin 查找已配置的通道
#define MAX_LEDC_CHANNELS 8

typedef struct {
    int pin;
    int channel;
    int freq;
    int resolution;
    bool configured;
} ledc_channel_state_t;

static ledc_channel_state_t s_ledc_channels[MAX_LEDC_CHANNELS] = {0};

// ==================== 读取引脚列表 ====================
// Arduino digitalRead/analogRead 把引脚加入列表，由 reporting_sensor_data 定时上报
#define MAX_READ_PINS 16

static int s_digital_read_pins[MAX_READ_PINS] = {0};
static int s_digital_read_count = 0;
static int s_analog_read_pins[MAX_READ_PINS] = {0};
static int s_analog_read_count = 0;

// ADC 句柄（ADC1，WiFi 启用时 ADC2 不可用）
#include "esp_adc/adc_oneshot.h"
static adc_oneshot_unit_handle_t s_adc1_handle = NULL;

// ==================== 工具函数 ====================

// 舵机角度转占空比（移植自 Arduino angleToDutyCycle）
// 50Hz → 20ms 周期, 10bit 分辨率 (0-1023)
// 0° = 0.5ms → duty 26, 180° = 2.5ms → duty 128
static int angle_to_duty_cycle(int angle, int resolution)
{
    if (angle < 0) angle = 0;
    if (angle > 180) angle = 180;
    // 防止 resolution 过大导致 (1 << resolution) 整数溢出/未定义行为
    if (resolution < 1 || resolution > 20) resolution = 10;
    int max_duty = (1 << resolution) - 1;
    // 0.5ms/20ms = 2.5%, 2.5ms/20ms = 12.5%
    int min_duty = (int)(max_duty * 0.025f);
    int max_servo_duty = (int)(max_duty * 0.125f);
    return min_duty + (angle * (max_servo_duty - min_duty)) / 180;
}

// 通过 pin 查找已配置的 LEDC 通道
static ledc_channel_state_t *find_ledc_channel(int pin)
{
    for (int i = 0; i < MAX_LEDC_CHANNELS; i++) {
        if (s_ledc_channels[i].configured && s_ledc_channels[i].pin == pin) {
            return &s_ledc_channels[i];
        }
    }
    return NULL;
}

// 分配一个空闲的 LEDC 通道槽
static ledc_channel_state_t *alloc_ledc_channel(int pin, int channel, int freq, int resolution)
{
    // 先查重
    ledc_channel_state_t *existing = find_ledc_channel(pin);
    if (existing) return existing;

    for (int i = 0; i < MAX_LEDC_CHANNELS; i++) {
        if (!s_ledc_channels[i].configured) {
            s_ledc_channels[i].pin = pin;
            s_ledc_channels[i].channel = channel;
            s_ledc_channels[i].freq = freq;
            s_ledc_channels[i].resolution = resolution;
            s_ledc_channels[i].configured = true;
            return &s_ledc_channels[i];
        }
    }
    return NULL;
}

// 初始化 ADC1（首次模拟读取时调用）
static void ensure_adc_init(void)
{
    if (s_adc1_handle != NULL) return;
    adc_oneshot_unit_init_cfg_t init_cfg = {
        .unit_id = ADC_UNIT_1,
    };
    if (adc_oneshot_new_unit(&init_cfg, &s_adc1_handle) == ESP_OK) {
        ESP_LOGD(TAG, "ADC1 初始化完成");
    } else {
        ESP_LOGE(TAG, "ADC1 初始化失败");
    }
}

// ==================== 指令处理 ====================

// pinMode: 配置引脚模式
// str_val: "OUTPUT" / "INPUT" / "INPUT_PULLUP" / "INPUT_PULLDOWN" / "LEDC"
static esp_err_t handle_pin_mode(int pin, const char *str_val, cJSON *json)
{
    if (pin < 0 || pin >= GPIO_NUM_MAX) {
        ESP_LOGW(TAG, "pinMode: 无效引脚 %d", pin);
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t ret;

    if (strcmp(str_val, "OUTPUT") == 0) {
        gpio_config_t cfg = {
            .pin_bit_mask = (1ULL << pin),
            .mode = GPIO_MODE_OUTPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ret = gpio_config(&cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "pinMode(%d, OUTPUT) gpio_config 失败: %s", pin, esp_err_to_name(ret));
            return ret;
        }
        ESP_LOGD(TAG, "pinMode(%d, OUTPUT)", pin);
    }
    else if (strcmp(str_val, "INPUT") == 0) {
        gpio_config_t cfg = {
            .pin_bit_mask = (1ULL << pin),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ret = gpio_config(&cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "pinMode(%d, INPUT) gpio_config 失败: %s", pin, esp_err_to_name(ret));
            return ret;
        }
        ESP_LOGD(TAG, "pinMode(%d, INPUT)", pin);
    }
    else if (strcmp(str_val, "INPUT_PULLUP") == 0) {
        gpio_config_t cfg = {
            .pin_bit_mask = (1ULL << pin),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ret = gpio_config(&cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "pinMode(%d, INPUT_PULLUP) gpio_config 失败: %s", pin, esp_err_to_name(ret));
            return ret;
        }
        ESP_LOGD(TAG, "pinMode(%d, INPUT_PULLUP)", pin);
    }
    else if (strcmp(str_val, "INPUT_PULLDOWN") == 0) {
        gpio_config_t cfg = {
            .pin_bit_mask = (1ULL << pin),
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_ENABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ret = gpio_config(&cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "pinMode(%d, INPUT_PULLDOWN) gpio_config 失败: %s", pin, esp_err_to_name(ret));
            return ret;
        }
        ESP_LOGD(TAG, "pinMode(%d, INPUT_PULLDOWN)", pin);
    }
    // LEDC: 配置 PWM 通道（舵机/PWM 输出）
    else if (strcmp(str_val, "LEDC") == 0) {
        int channel = 0;
        cJSON *ch = cJSON_GetObjectItem(json, "channel");
        if (ch && cJSON_IsNumber(ch)) channel = ch->valueint;

        int freq = 50;  // 舵机默认 50Hz
        cJSON *f = cJSON_GetObjectItem(json, "freq");
        if (f && cJSON_IsNumber(f)) freq = f->valueint;

        int resolution = 10;  // 默认 10bit
        cJSON *r = cJSON_GetObjectItem(json, "resolution");
        if (r && cJSON_IsNumber(r)) resolution = r->valueint;

        // 配置 LEDC 定时器
        ledc_timer_config_t timer_cfg = {
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .duty_resolution = (ledc_timer_bit_t)resolution,
            .timer_num = LEDC_TIMER_0,
            .freq_hz = freq,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        ret = ledc_timer_config(&timer_cfg);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "LEDC 定时器配置失败: %s", esp_err_to_name(ret));
            return ret;
        }

        // 配置 LEDC 通道
        ledc_channel_config_t ch_cfg = {
            .gpio_num = pin,
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = (ledc_channel_t)channel,
            .intr_type = LEDC_INTR_DISABLE,
            .timer_sel = LEDC_TIMER_0,
            .duty = 0,
            .hpoint = 0,
        };
        ret = ledc_channel_config(&ch_cfg);
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "LEDC 通道配置失败: %s", esp_err_to_name(ret));
            return ret;
        }

        alloc_ledc_channel(pin, channel, freq, resolution);
        ESP_LOGD(TAG, "pinMode(%d, LEDC) ch=%d freq=%d res=%d", pin, channel, freq, resolution);
    }
    else {
        ESP_LOGW(TAG, "pinMode: 未知模式 '%s'", str_val);
    }

    return ESP_OK;
}

// digitalWrite: 数字写
static esp_err_t handle_digital_write(int pin, const char *str_val)
{
    if (pin < 0 || pin >= GPIO_NUM_MAX) return ESP_ERR_INVALID_ARG;

    int level = 0;
    if (strcmp(str_val, "HIGH") == 0) level = 1;
    else if (strcmp(str_val, "LOW") == 0) level = 0;
    else level = atoi(str_val);

    gpio_set_level((gpio_num_t)pin, level);
    ESP_LOGD(TAG, "digitalWrite(%d, %s)", pin, str_val);
    return ESP_OK;
}

// digitalRead: 加入数字读取列表
static esp_err_t handle_digital_read(int pin)
{
    if (pin < 0 || pin >= GPIO_NUM_MAX) return ESP_ERR_INVALID_ARG;

    // 避免重复添加
    for (int i = 0; i < s_digital_read_count; i++) {
        if (s_digital_read_pins[i] == pin) return ESP_OK;
    }
    if (s_digital_read_count < MAX_READ_PINS) {
        s_digital_read_pins[s_digital_read_count++] = pin;
        ESP_LOGD(TAG, "digitalRead: 添加引脚 %d 到上报列表", pin);
    }
    return ESP_OK;
}

// analogWrite: PWM 输出（通过 LEDC）
static esp_err_t handle_analog_write(int pin, int num_val)
{
    ledc_channel_state_t *ch = find_ledc_channel(pin);
    if (!ch) {
        ESP_LOGW(TAG, "analogWrite: 引脚 %d 未配置 LEDC，自动配置默认参数", pin);
        // 自动配置：默认 5000Hz, 10bit
        ledc_timer_config_t timer_cfg = {
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .duty_resolution = LEDC_TIMER_10_BIT,
            .timer_num = LEDC_TIMER_1,
            .freq_hz = 5000,
            .clk_cfg = LEDC_AUTO_CLK,
        };
        if (ledc_timer_config(&timer_cfg) != ESP_OK) return ESP_FAIL;

        // 找空闲通道
        int ch_idx = -1;
        for (int i = 0; i < MAX_LEDC_CHANNELS; i++) {
            if (!s_ledc_channels[i].configured) { ch_idx = i; break; }
        }
        if (ch_idx < 0) return ESP_FAIL;

        ledc_channel_config_t ch_cfg = {
            .gpio_num = pin,
            .speed_mode = LEDC_LOW_SPEED_MODE,
            .channel = (ledc_channel_t)ch_idx,
            .intr_type = LEDC_INTR_DISABLE,
            .timer_sel = LEDC_TIMER_1,
            .duty = 0,
            .hpoint = 0,
        };
        if (ledc_channel_config(&ch_cfg) != ESP_OK) return ESP_FAIL;

        ch = alloc_ledc_channel(pin, ch_idx, 5000, 10);
        if (!ch) return ESP_FAIL;
    }

    ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)ch->channel, num_val);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)ch->channel);
    ESP_LOGD(TAG, "analogWrite(%d, %d)", pin, num_val);
    return ESP_OK;
}

// analogRead: 加入模拟读取列表
static esp_err_t handle_analog_read(int pin)
{
    // ESP32-S3 ADC1: GPIO1~GPIO10 (ADC1_CH0~CH9)
    if (pin < 1 || pin > 10) {
        ESP_LOGW(TAG, "analogRead: 引脚 %d 不在 ADC1 范围(1-10)", pin);
        return ESP_ERR_INVALID_ARG;
    }
    for (int i = 0; i < s_analog_read_count; i++) {
        if (s_analog_read_pins[i] == pin) return ESP_OK;
    }
    if (s_analog_read_count < MAX_READ_PINS) {
        ensure_adc_init();
        // 通道配置仅做一次（添加引脚时），避免每次上报都重新配置
        if (s_adc1_handle) {
            adc_channel_t ch = (adc_channel_t)(pin - 1);
            adc_oneshot_chan_cfg_t chan_cfg = {
                .atten = ADC_ATTEN_DB_12,
                .bitwidth = ADC_BITWIDTH_12,
            };
            esp_err_t adc_ret = adc_oneshot_config_channel(s_adc1_handle, ch, &chan_cfg);
            if (adc_ret != ESP_OK) {
                ESP_LOGW(TAG, "analogRead: ADC 通道 %d 配置失败: %s", pin, esp_err_to_name(adc_ret));
            }
        }
        s_analog_read_pins[s_analog_read_count++] = pin;
        ESP_LOGD(TAG, "analogRead: 添加引脚 %d 到上报列表", pin);
    }
    return ESP_OK;
}

// ledcWrite: 舵机角度控制
static esp_err_t handle_ledc_write(int channel, int deg, cJSON *json)
{
    int resolution = 10;
    ledc_channel_state_t *ch = NULL;
    for (int i = 0; i < MAX_LEDC_CHANNELS; i++) {
        if (s_ledc_channels[i].configured && s_ledc_channels[i].channel == channel) {
            ch = &s_ledc_channels[i];
            resolution = ch->resolution;
            break;
        }
    }
    if (!ch) {
        ESP_LOGW(TAG, "ledcWrite: 通道 %d 未配置", channel);
        return ESP_FAIL;
    }

    int duty = angle_to_duty_cycle(deg, resolution);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel, duty);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel);
    ESP_LOGD(TAG, "ledcWrite(ch=%d, deg=%d) → duty=%d", channel, deg, duty);
    return ESP_OK;
}

// ==================== 对外接口 ====================

esp_err_t hardware_io_handle_fns(cJSON *json)
{
    if (!json) return ESP_ERR_INVALID_ARG;

    // 加锁保护静态数组（与 hardware_io_report_readings 互斥）
    ensure_io_mutex();
    if (s_io_mutex) xSemaphoreTake(s_io_mutex, portMAX_DELAY);

    cJSON *pin_item = cJSON_GetObjectItem(json, "pin");
    cJSON *fn_item = cJSON_GetObjectItem(json, "fn_name");
    cJSON *str_val = cJSON_GetObjectItem(json, "str_val");
    cJSON *num_val = cJSON_GetObjectItem(json, "num_val");

    if (!fn_item || !cJSON_IsString(fn_item)) {
        ESP_LOGW(TAG, "hardware-fns: 缺少 fn_name");
        if (s_io_mutex) xSemaphoreGive(s_io_mutex);
        return ESP_ERR_INVALID_ARG;
    }

    int pin = (pin_item && cJSON_IsNumber(pin_item)) ? pin_item->valueint : -1;
    const char *fn_name = fn_item->valuestring;
    const char *str_v = (str_val && cJSON_IsString(str_val)) ? str_val->valuestring : "";
    int num_v = (num_val && cJSON_IsNumber(num_val)) ? num_val->valueint : 0;

    esp_err_t result;
    if (strcmp(fn_name, "pinMode") == 0) {
        result = handle_pin_mode(pin, str_v, json);
    }
    else if (strcmp(fn_name, "digitalWrite") == 0) {
        result = handle_digital_write(pin, str_v);
    }
    else if (strcmp(fn_name, "digitalRead") == 0) {
        result = handle_digital_read(pin);
    }
    else if (strcmp(fn_name, "analogWrite") == 0) {
        result = handle_analog_write(pin, num_v);
    }
    else if (strcmp(fn_name, "analogRead") == 0) {
        result = handle_analog_read(pin);
    }
    else if (strcmp(fn_name, "ledcWrite") == 0) {
        int channel = 0;
        cJSON *ch = cJSON_GetObjectItem(json, "channel");
        if (ch && cJSON_IsNumber(ch)) channel = ch->valueint;
        int deg = 0;
        cJSON *d = cJSON_GetObjectItem(json, "deg");
        if (d && cJSON_IsNumber(d)) deg = d->valueint;
        result = handle_ledc_write(channel, deg, json);
    }
    else {
        ESP_LOGW(TAG, "hardware-fns: 未知 fn_name '%s'", fn_name);
        result = ESP_ERR_NOT_SUPPORTED;
    }

    if (s_io_mutex) xSemaphoreGive(s_io_mutex);
    return result;
}

esp_err_t hardware_io_report_readings(void)
{
    ensure_io_mutex();
    if (s_io_mutex) xSemaphoreTake(s_io_mutex, portMAX_DELAY);

    if (s_digital_read_count == 0 && s_analog_read_count == 0) {
        if (s_io_mutex) xSemaphoreGive(s_io_mutex);
        return ESP_OK;
    }

    extern esp_err_t websocket_send_text(const char *text);

    // 上报数字读取
    for (int i = 0; i < s_digital_read_count; i++) {
        int pin = s_digital_read_pins[i];
        int level = gpio_get_level((gpio_num_t)pin);
        char msg[64];
        snprintf(msg, sizeof(msg),
                 "{\"type\":\"hardware_read\",\"pin\":%d,\"val\":%d,\"mode\":\"digital\"}",
                 pin, level);
        websocket_send_text(msg);
    }

    // 上报模拟读取（通道已在 handle_analog_read 中配置一次，此处仅读取）
    if (s_adc1_handle && s_analog_read_count > 0) {
        for (int i = 0; i < s_analog_read_count; i++) {
            int pin = s_analog_read_pins[i];
            // GPIO1~10 → ADC1_CH0~CH9
            adc_channel_t ch = (adc_channel_t)(pin - 1);
            int raw = 0;
            if (adc_oneshot_read(s_adc1_handle, ch, &raw) == ESP_OK) {
                char msg[64];
                snprintf(msg, sizeof(msg),
                         "{\"type\":\"hardware_read\",\"pin\":%d,\"val\":%d,\"mode\":\"analog\"}",
                         pin, raw);
                websocket_send_text(msg);
            }
        }
    }

    if (s_io_mutex) xSemaphoreGive(s_io_mutex);
    return ESP_OK;
}
