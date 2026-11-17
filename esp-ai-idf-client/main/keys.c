#include "keys.h"

#include "boards/board_interface.h"
#include "config.h"
#include "eeui_port.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#define TAG "keys"

#define KEY_POLL_MS        10
#define KEY_DEBOUNCE_CNT   3      // 3 × 10ms = 30ms 消抖
#define KEY_REPEAT_DELAY   700    // 长按 700ms 后开始连发
#define KEY_REPEAT_PERIOD  150
#define VOLUME_STEP        0.1f

typedef struct {
    int gpio;
    float delta;
    const char *name;
    int raw;
    int stable_cnt;
    bool pressed;
    int64_t next_repeat_ms;
} volume_key_t;

static volume_key_t s_keys[2];
static int s_key_count;
static bool s_volume_dirty;

static void save_volume(float vol)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) == ESP_OK) {
        char vol_str[16];
        snprintf(vol_str, sizeof(vol_str), "%.1f", vol);
        esp_err_t ret = nvs_set_str(h, "ext2", vol_str);
        if (ret == ESP_OK) {
            ret = nvs_commit(h);
        }
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "音量保存失败: %s", esp_err_to_name(ret));
        }
        nvs_close(h);
    }
}

static void volume_step(float delta)
{
    float vol = audio_get_volume() + delta;
    if (vol < 0.0f) {
        vol = 0.0f;
    } else if (vol > 1.0f) {
        vol = 1.0f;
    }
    vol = roundf(vol * 10.0f) / 10.0f;

    audio_set_volume(vol);
    eeui_port_render_volume(vol);
    s_volume_dirty = true;
    ESP_LOGI(TAG, "音量 %.0f%%", vol * 100.0f);
}

static void keys_task(void *arg)
{
    while (1) {
        int64_t now = esp_timer_get_time() / 1000;

        for (int i = 0; i < s_key_count; i++) {
            volume_key_t *k = &s_keys[i];
            int level = gpio_get_level(k->gpio);

            if (level != k->raw) {
                k->raw = level;
                k->stable_cnt = 0;
                now = esp_timer_get_time() / 1000;
            } else if (k->stable_cnt < KEY_DEBOUNCE_CNT) {
                k->stable_cnt++;
                if (k->stable_cnt == KEY_DEBOUNCE_CNT) {
                    now = esp_timer_get_time() / 1000;
                    if (level == 0) {
                        volume_step(k->delta);
                        k->pressed = true;
                        k->next_repeat_ms = now + KEY_REPEAT_DELAY;
                    } else if (k->pressed) {
                        k->pressed = false;
                        if (s_volume_dirty) {
                            save_volume(audio_get_volume());
                            s_volume_dirty = false;
                        }
                    }
                }
            } else if (k->pressed && level == 0 && now >= k->next_repeat_ms) {
                volume_step(k->delta);
                k->next_repeat_ms = now + KEY_REPEAT_PERIOD;
            }
        }

        vTaskDelay(pdMS_TO_TICKS(KEY_POLL_MS));
    }
}

void keys_init(void)
{
    const board_config_t *cfg = board_get_config();
    if (!cfg) {
        return;
    }

    s_key_count = 0;
    if (cfg->volume_up_gpio >= 0) {
        s_keys[s_key_count++] = (volume_key_t){
            .gpio = cfg->volume_up_gpio,
            .delta = VOLUME_STEP,
            .name = "A",
            .raw = 1,
        };
    }
    if (cfg->volume_down_gpio >= 0) {
        s_keys[s_key_count++] = (volume_key_t){
            .gpio = cfg->volume_down_gpio,
            .delta = -VOLUME_STEP,
            .name = "B",
            .raw = 1,
        };
    }
    if (s_key_count == 0) {
        return;
    }

    uint64_t mask = 0;
    for (int i = 0; i < s_key_count; i++) {
        mask |= (1ULL << s_keys[i].gpio);
    }
    gpio_config_t io = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&io) != ESP_OK) {
        ESP_LOGW(TAG, "音量按键 GPIO 配置失败");
        return;
    }

    xTaskCreate(keys_task, "keys", 3072, NULL, 3, NULL);
    ESP_LOGI(TAG, "音量按键已启动: A=GPIO%d(+), B=GPIO%d(-)",
             s_keys[0].gpio, s_key_count > 1 ? s_keys[1].gpio : -1);
}
