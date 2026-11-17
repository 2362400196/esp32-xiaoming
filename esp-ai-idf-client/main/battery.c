#include "battery.h"

#include "boards/board_interface.h"
#include "eeui_port.h"

#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define TAG "battery"

#define BAT_SAMPLE_PERIOD_MS 2000
#define BAT_USB_POLL_MS      200    // USB 供电状态轮询间隔（插拔要立刻响应）
#define BAT_AVG_SAMPLES      24
#define BAT_SAMPLE_GAP_MS    2      // 分压电阻阻值高，逐次采样之间要留建立时间
#define BAT_EMA_ALPHA        0.25f
#define BAT_RISE_MV          10.0f   // 单次采样相对峰值上涨多少 mV 判定为充电
#define BAT_DROP_MV          60.0f   // 相对峰值跌落多少 mV 判定为拔出
#define BAT_NO_RISE_LIMIT    6       // 连续多少次采样未上涨后取消趋势充电判定（6 × 5s = 30s）

// ==================== 电量显示状态机 ====================
// 单纯按端电压换算电量在充电/刚拔电时都不可信：
//   1) 充电器把电池端电压钳在 4.2V 左右，直接换算会从 70% 几分钟内"跳到"100%；
//   2) 拔掉后表面电荷消散，端电压快速回落，直接换算又表现成"每 2 秒掉 1%"。
// 所以显示值不直接跟随电压：
//   - 充电中：冻结电量，每 90 秒 +1%，只在电压稳定满电 2 分钟后显示 100%；
//   - 放电中：拔掉后先保持 90 秒等电压回稳，之后每 30 秒最多变化 1%。
#define BAT_HOLD_AFTER_UNPLUG_MS 90000   // 拔掉充电器后保持显示的时间
#define BAT_PCT_STEP_MS          30000   // 放电时电量每次变化的最小间隔
#define BAT_CHARGE_CREEP_MS      90000   // 充电时电量上涨的最小间隔
#define BAT_FULL_MV              4150    // 满电判定电压（恒压充电平台）
#define BAT_FULL_CONFIRM_MS      60000   // 满电判定需要持续的时长

// 锂电池电压 → 百分比（静置近似曲线）
// 注意：4.15V 以上即视为满电（充电器恒压 4.2V，带载测量通常只有 4.16~4.19V，
// 若把 100% 定在 4.20V，满电时永远显示 98%~99%，所以顶部放平）
static const struct {
    int mv;
    int pct;
} BAT_CURVE[] = {
    {4200, 100}, {4150, 100}, {4100, 96}, {4050, 92}, {4000, 88},
    {3950, 84},  {3900, 79},  {3850, 73}, {3800, 66}, {3750, 58},
    {3700, 50},  {3650, 42},  {3600, 34}, {3550, 26}, {3500, 19},
    {3450, 13},  {3400, 7},   {3350, 3},  {3300, 0},
};

static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_cali;
static adc_channel_t s_chan;
static float s_ratio = 2.0f;

static bool s_charging;
static volatile bool s_usb_present;  // USB 主机在位（原生 USB 收到 SOF）
static bool s_trend_charging;   // 电压上升趋势判定的充电（充电器供电、无 USB 主机时可检测）
static bool s_has_state;
static float s_ema_mv;
static float s_peak_mv;
static int s_no_rise_count;

// 显示电量状态机
static int s_pct = -1;          // 当前显示电量（-1 = 尚未初始化）
static int64_t s_step_ms;       // 上次电量变化时间
static int64_t s_hold_until_ms; // 拔电后的保持截止时间
static int64_t s_full_since_ms; // 电压达到满电阈值的起始时间
static bool s_was_charging;
static bool s_full;             // 已充满（停止充电动画）
static int s_boot_pct = -1;     // 上次关机前记录的电量

// 持久化电量：插着充电器开机时，端电压不可信，用上次记录的电量恢复显示
static void load_boot_pct(void)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    char buf[8] = {0};
    size_t len = sizeof(buf);
    if (nvs_get_str(h, "bat_pct", buf, &len) == ESP_OK) {
        int v = atoi(buf);
        if (v >= 0 && v <= 100) {
            s_boot_pct = v;
        }
    }
    nvs_close(h);
}

static void save_pct(int pct)
{
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READWRITE, &h) != ESP_OK) {
        return;
    }
    char buf[8];
    snprintf(buf, sizeof(buf), "%d", pct);
    if (nvs_set_str(h, "bat_pct", buf) == ESP_OK) {
        nvs_commit(h);
    }
    nvs_close(h);
}

static int voltage_to_percent(float mv)
{
    const int n = (int)(sizeof(BAT_CURVE) / sizeof(BAT_CURVE[0]));
    if (mv >= BAT_CURVE[0].mv) return 100;
    if (mv <= BAT_CURVE[n - 1].mv) return 0;
    for (int i = 0; i < n - 1; i++) {
        if (mv <= BAT_CURVE[i].mv && mv >= BAT_CURVE[i + 1].mv) {
            float span = (float)(BAT_CURVE[i].mv - BAT_CURVE[i + 1].mv);
            float k = (mv - BAT_CURVE[i + 1].mv) / span;
            return BAT_CURVE[i + 1].pct +
                   (int)((BAT_CURVE[i].pct - BAT_CURVE[i + 1].pct) * k + 0.5f);
        }
    }
    return 0;
}

static int read_adc_mv(void)
{
    int sum = 0;
    int count = 0;
    int min_mv = 0x7FFFFFFF;
    int max_mv = -1;

    for (int i = 0; i < BAT_AVG_SAMPLES; i++) {
        // 分压网络阻值高（数百 kΩ 级），连续采样会把采样电容抽空导致读数偏低，
        // 每次转换前留出建立时间
        if (i > 0) {
            vTaskDelay(pdMS_TO_TICKS(BAT_SAMPLE_GAP_MS));
        }
        int raw = 0;
        if (adc_oneshot_read(s_adc, s_chan, &raw) != ESP_OK) {
            continue;
        }
        int mv = 0;
        if (s_cali) {
            if (adc_cali_raw_to_voltage(s_cali, raw, &mv) != ESP_OK) {
                continue;
            }
        } else {
            mv = raw * 3100 / 4095;
        }
        sum += mv;
        count++;
        if (mv < min_mv) min_mv = mv;
        if (mv > max_mv) max_mv = mv;
    }
    if (count == 0) {
        return -1;
    }
    if (count < 3) {
        return sum / count;
    }
    // 去掉一个最大、一个最小值，抑制偶发尖峰
    return (sum - min_mv - max_mv) / (count - 2);
}

// USB 供电快速检测：插拔在 200ms 内反应，不等下一次电压采样。
// 接电脑/电脑充电器时原生 USB 会收到 SOF；接普通充电头没有 SOF，
// 由电压趋势判定兜底（最长一个采样周期）。
static void battery_usb_task(void *arg)
{
    (void)arg;
    for (;;) {
        bool usb = usb_serial_jtag_is_connected();
        if (usb != s_usb_present) {
            s_usb_present = usb;
            if (usb) {
                // 刚接入外部供电：立即显示充电中并把满电标志清零重新判定
                s_full = false;
                ESP_LOGI(TAG, "USB 供电接入，立即显示充电中");
            } else {
                ESP_LOGI(TAG, "USB 供电移除，立即停止充电动画");
            }
            s_charging = usb || s_trend_charging;
            eeui_port_set_charging(s_charging && !s_full);
        }
        vTaskDelay(pdMS_TO_TICKS(BAT_USB_POLL_MS));
    }
}

static void battery_task(void *arg)
{
    int last_pct = -1;

    while (1) {
        // USB 主机在位检测由 battery_usb_task 每 200ms 更新，
        // 这里只读取状态，避免插拔后要等一个采样周期才响应。
        bool usb = s_usb_present;

        int adc_mv = read_adc_mv();
        if (adc_mv > 0) {
            float bat_mv = adc_mv * s_ratio;

            if (!s_has_state) {
                s_ema_mv = bat_mv;
                s_peak_mv = bat_mv;
                s_has_state = true;
            } else {
                s_ema_mv += (bat_mv - s_ema_mv) * BAT_EMA_ALPHA;

                if (s_ema_mv > s_peak_mv + BAT_RISE_MV) {
                    // 电压持续上涨：正在充电
                    s_peak_mv = s_ema_mv;
                    s_trend_charging = true;
                    s_no_rise_count = 0;
                } else if (s_trend_charging) {
                    // 不再上涨：充满转恒压或充电器已拔出，超时/明显跌落则取消
                    if (++s_no_rise_count >= BAT_NO_RISE_LIMIT ||
                        s_ema_mv < s_peak_mv - BAT_DROP_MV) {
                        s_trend_charging = false;
                        s_no_rise_count = 0;
                        s_peak_mv = s_ema_mv;
                    }
                } else if (s_ema_mv < s_peak_mv - BAT_DROP_MV) {
                    // 放电中：峰值跟随下降，便于下次充电重新触发
                    s_peak_mv = s_ema_mv;
                }
            }

            bool charging = usb || s_trend_charging;
            int64_t now_ms = esp_timer_get_time() / 1000;
            int target = voltage_to_percent(s_ema_mv);

            if (s_pct < 0) {
                // 首次采样：充电时端电压被充电器抬高，优先用上次记录的电量
                s_pct = (charging && s_boot_pct >= 0) ? s_boot_pct : target;
                s_step_ms = now_ms;
                s_was_charging = charging;
            }

            if (charging) {
                if (!s_was_charging) {
                    // 刚插上充电器：电压会被充电器抬高，冻结当前电量重新计时
                    s_step_ms = now_ms;
                    s_full_since_ms = 0;
                    s_full = false;
                }

                // 满电：电压持续保持在 4.18V 以上 2 分钟
                if (s_ema_mv >= BAT_FULL_MV) {
                    if (s_full_since_ms == 0) {
                        s_full_since_ms = now_ms;
                    } else if (now_ms - s_full_since_ms >= BAT_FULL_CONFIRM_MS) {
                        s_pct = 100;
                        s_full = true;
                    }
                } else {
                    s_full_since_ms = 0;
                    s_full = false;
                }

                // 充电中电量只缓慢上涨（每 90 秒 +1%），不跟随被钳位的端电压
                if (s_pct < 100 && now_ms - s_step_ms >= BAT_CHARGE_CREEP_MS) {
                    s_pct++;
                    s_step_ms = now_ms;
                }
            } else {
                if (s_was_charging) {
                    // 刚拔掉：先保持 90 秒，等表面电荷消散、电压回稳
                    s_hold_until_ms = now_ms + BAT_HOLD_AFTER_UNPLUG_MS;
                    s_step_ms = now_ms;
                    s_full_since_ms = 0;
                    s_full = false;
                }

                // 放电中：每 30 秒最多变化 1%，避免电压波动造成数字剧烈跳动
                if (now_ms >= s_hold_until_ms && now_ms - s_step_ms >= BAT_PCT_STEP_MS) {
                    if (target < s_pct) {
                        s_pct--;
                        s_step_ms = now_ms;
                    } else if (target > s_pct) {
                        s_pct++;
                        s_step_ms = now_ms;
                    }
                }
            }
            s_was_charging = charging;
            s_charging = charging;

            // 充满后熄灭闪电：避免"显示 100% 却一直充电动画"的误解。
            // 每个周期都下发一次（接口幂等）：即使某次 LVGL 加锁失败，
            // 下一轮也会自动纠正，不会出现拔电后动画停不下来的情况。
            bool show_charging = s_charging && !s_full;
            eeui_port_set_charging(show_charging);

            if (s_pct != last_pct) {
                last_pct = s_pct;
                eeui_port_render_battery(s_pct);
                save_pct(s_pct);
            }
            ESP_LOGI(TAG, "电池 %d mV (%d%%), %s%s%s",
                     (int)s_ema_mv, s_pct,
                     s_full ? "已充满" : (s_charging ? "充电中" : "放电"),
                     usb ? " (USB 在位)" : "",
                     s_pct != target ? " [电压估算差]" : "");
        }
        vTaskDelay(pdMS_TO_TICKS(BAT_SAMPLE_PERIOD_MS));
    }
}

void battery_init(void)
{
    const board_config_t *cfg = board_get_config();
    if (!cfg) {
        ESP_LOGW(TAG, "无板型配置，跳过电池检测");
        return;
    }
    if (cfg->battery_adc_gpio < 0) {
        ESP_LOGI(TAG, "板型未配置电池检测 (gpio=%d)，跳过", cfg->battery_adc_gpio);
        return;
    }

    adc_unit_t unit;
    adc_channel_t chan;
    if (adc_oneshot_io_to_channel(cfg->battery_adc_gpio, &unit, &chan) != ESP_OK) {
        ESP_LOGW(TAG, "GPIO%d 不支持 ADC，跳过电池检测", cfg->battery_adc_gpio);
        return;
    }

    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = unit,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    if (adc_oneshot_new_unit(&unit_cfg, &s_adc) != ESP_OK) {
        ESP_LOGW(TAG, "ADC 初始化失败");
        return;
    }

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_oneshot_config_channel(s_adc, chan, &chan_cfg) != ESP_OK) {
        ESP_LOGW(TAG, "ADC 通道配置失败");
        adc_oneshot_del_unit(s_adc);
        s_adc = NULL;
        return;
    }

    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id = unit,
        .chan = chan,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_cali) != ESP_OK) {
        ESP_LOGW(TAG, "ADC 校准不可用，使用线性换算");
        s_cali = NULL;
    }

    s_chan = chan;
    s_ratio = cfg->battery_divider_ratio > 0 ? cfg->battery_divider_ratio : 2.0f;
    s_usb_present = usb_serial_jtag_is_connected();
    load_boot_pct();

    xTaskCreate(battery_usb_task, "bat_usb", 3072, NULL, 3, NULL);
    xTaskCreate(battery_task, "battery", 4096, NULL, 2, NULL);
    ESP_LOGI(TAG, "电池检测已启动: GPIO%d, 分压比 %.1f", cfg->battery_adc_gpio, s_ratio);
}

// ==================== 状态查询（供 get_battery 指令/工具使用）====================
int battery_get_percent(void)
{
    return s_pct;
}

int battery_get_voltage_mv(void)
{
    return s_has_state ? (int)(s_ema_mv + 0.5f) : -1;
}

bool battery_is_charging(void)
{
    return s_charging;
}

bool battery_is_full(void)
{
    return s_full;
}

bool battery_is_supported(void)
{
    return s_adc != NULL;
}
