/**
 * eeui_port.cpp - EEUI 表情显示（LVGL 9 直接驱动，完全对齐 LVGL 8 Lite 版本）
 */
#include "eeui_port.h"
#include "config.h"
#include "board_compat.h"
#include "gif_downloader.h"
#include "boards/board_interface.h"
#include "commands/command_registry.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/spi_master.h"
#include "driver/ledc.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_panel_ops.h"
#include "esp_wifi.h"

#include "lvgl.h"
#include "libs/gif/lv_gif.h"
#include "draw/sw/lv_draw_sw.h"
#include "core/lv_refr.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <math.h>
#include <time.h>  /* time_t / localtime_r（屏保时钟） */
#include "cJSON.h" /* show_card 卡片 JSON 解析 */
#include <stdlib.h>

/* 天气图标表（fonts/weather_icons.c 生成，ARGB8565；C 文件符号需 extern "C"） */
typedef struct { const char *id; const lv_image_dsc_t *img; } weather_icon_entry_t;
extern "C" {
extern const lv_font_t font_puhui_16_4;
/* lua_lvgl.c 是 C 文件，C++ 调用需 extern "C"（否则符号被 name-mangle 链接失败） */
void lua_lvgl_reset(void);
extern const weather_icon_entry_t weather_icon_table[];
extern const int weather_icon_count;
}

/* show_card 卡片对象清理（定义在文件末尾的卡片渲染模块，此处前向声明供 render_emotion 使用） */
static void card_clear_objects(void);

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wmissing-field-initializers"
#include "emos/wifi.h"
#include "emos/wx_qrcode.h"
#include "emos/error.h"
#include "emos/listen.h"
#include "emos/tts_ing.h"
#include "emos/sleep.h"
#include "emos/music.h"
#include "emos/happy.h"
#include "emos/sad.h"
#include "emos/angry.h"
#include "emos/accident.h"
#include "emos/no.h"
#include "emos/ap_qrcode.h"
#include "emos/rechargeing.h"
#pragma GCC diagnostic pop

static const char *TAG = "eeui_port";

struct EmotionEntry { const char *name; const lv_img_dsc_t *img; };
static const EmotionEntry s_emotions[] = {
    {"联网中",   &wifi_img},    {"请配网",   &wx_qrcode_img},
    {"AP配网",   &ap_qrcode_img},{"发生错误", &error_img},
    {"聆听中",   &listen_img},  {"说话中",   &tts_ing_img},
    {"休息中",   &sleep_img},   {"唱歌中",   &music_img},
    {"无情绪",   &tts_ing_img}, {"快乐",     &happy_img},
    {"伤心",     &sad_img},     {"愤怒",     &angry_img},
    {"意外",     &accident_img},{"否定",     &no_img},
    {"充电中",   &rechargeing_gif},
};
static const int s_emotions_count = sizeof(s_emotions) / sizeof(s_emotions[0]);

// ==================== 全局状态 ====================
static esp_lcd_panel_handle_t s_lcd_panel = NULL;
static esp_lcd_panel_io_handle_t s_panel_io = NULL;
static lv_display_t *s_display = NULL;
static volatile bool s_lvgl_ready = false;
static SemaphoreHandle_t s_lvgl_mutex = NULL;
static esp_timer_handle_t s_tick_timer = NULL;
static esp_timer_handle_t s_signal_timer = NULL;

static lv_obj_t *s_container = NULL;
static lv_obj_t *s_emo_img = NULL;
static lv_obj_t *s_status_label = NULL;
static lv_obj_t *s_bottom_label = NULL;
static lv_obj_t *s_tool_status_label = NULL;  // 工具状态标签（底部，独立于字幕）

// OTA 进度条 UI（对齐 Arduino eeui.cpp render_ota_percent）
static lv_obj_t *s_ota_arc = NULL;
static lv_obj_t *s_ota_label = NULL;
static lv_obj_t *s_ota_overlay = NULL;  // 全屏遮罩
static lv_obj_t *s_ota_status_label = NULL;  // "正在升级" 文字

// 表情下载中提示 UI
static lv_obj_t *s_emo_dl_overlay = NULL;   // 全屏遮罩
static lv_obj_t *s_emo_dl_label = NULL;     // "表情下载中..." 文字
static lv_obj_t *s_emo_dl_arc = NULL;       // 旋转加载圆弧（进度指示）

static int s_screen_width = 240;
static int s_screen_height = 240;

// 音量、信号 UI 结构体（前移以便 ui_reorder_layers 引用）
struct VolumeUI {
    lv_obj_t *icon;        // 音量图标（canvas）
    lv_obj_t *bar;         // 音量进度条
    lv_obj_t *label;       // 百分比标签
    esp_timer_handle_t hide_timer;
    float current_volume;
} s_vol_ui = {};

struct SignalUI {
    lv_obj_t *canvas;
    int last_strength;
} s_sig_ui = { .canvas = NULL, .last_strength = -1 };

// 电量 UI
struct BatteryUI {
    lv_obj_t *body;        // 电池外框
    lv_obj_t *top;         // 电池正极
    lv_obj_t *label;       // 百分比文字
    lv_obj_t *fill;        // 内部电量条
    int percent;
} s_bat_ui = {};

// 位置计算（对齐 Arduino eeui.cpp get_bat_offset）
static int get_bat_offset(int percent)
{
    if (percent < 100 && percent > 10) return 48;
    else if (percent < 10) return 40;
    else return 52;  // 100%
}

// 显示缓冲区指针（根据实际屏幕尺寸动态分配）
static uint8_t *s_buf1 = NULL;
static uint8_t *s_buf2 = NULL;

// ==================== flush 回调 ====================
static void IRAM_ATTR disp_flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    if (s_lcd_panel) {
        lv_draw_sw_rgb565_swap(px_map, lv_area_get_size(area));
        esp_lcd_panel_draw_bitmap(s_lcd_panel,
                                   area->x1, area->y1,
                                   area->x2 + 1, area->y2 + 1,
                                   px_map);
    }
}

// DMA 传输完成回调（ISR 上下文），通知 LVGL buffer 可重用
static bool IRAM_ATTR on_color_trans_done_cb(esp_lcd_panel_io_handle_t panel_io,
                                              esp_lcd_panel_io_event_data_t *edata,
                                              void *user_ctx)
{
    lv_display_t *disp = (lv_display_t *)user_ctx;
    if (disp) lv_disp_flush_ready(disp);
    return false;
}

// ==================== LVGL tick（5ms）====================
static void IRAM_ATTR lv_tick_cb(void *arg)
{
    if (s_lvgl_ready) lv_tick_inc(5);
}

// ==================== LVGL 主任务 ====================
static void lvgl_task(void *arg)
{
    ESP_LOGI(TAG, "LVGL 任务启动");
    vTaskDelay(pdMS_TO_TICKS(200));
    s_lvgl_ready = true;
    while (1) {
        if (xSemaphoreTake(s_lvgl_mutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            lv_timer_handler();
            xSemaphoreGive(s_lvgl_mutex);
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

// ==================== 锁包装 ====================
static bool lvgl_lock(uint32_t timeout_ms)
{
    return xSemaphoreTake(s_lvgl_mutex, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

static void lvgl_unlock(void)
{
    xSemaphoreGive(s_lvgl_mutex);
}

// ==================== 公共锁接口（供 Lua 等外部模块使用）====================
bool eeui_port_lvgl_lock(uint32_t timeout_ms)
{
    if (!s_lvgl_mutex) return false;
    return xSemaphoreTake(s_lvgl_mutex, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

void eeui_port_lvgl_unlock(void)
{
    if (s_lvgl_mutex) xSemaphoreGive(s_lvgl_mutex);
}

void *eeui_port_get_display(void)
{
    return (void *)s_display;
}

void *eeui_port_get_lcd_panel(void)
{
    return (void *)s_lcd_panel;
}

void *eeui_port_get_panel_io(void)
{
    return (void *)s_panel_io;
}

// ==================== 层级管理 ====================
// 统一把所有 UI 元素移到正确的 z-order：
// 表情 GIF 在最底层，字幕/状态文字在中层，音量/WiFi/电量图标在最前
static void ui_reorder_layers(void)
{
    // 表情 GIF 移到最底层
    if (s_emo_img && lv_obj_is_valid(s_emo_img)) {
        lv_obj_move_background(s_emo_img);
    }
    // 中层：状态文字、底部字幕
    if (s_status_label && lv_obj_is_valid(s_status_label)) {
        lv_obj_move_foreground(s_status_label);
    }
    if (s_bottom_label && lv_obj_is_valid(s_bottom_label)) {
        lv_obj_move_foreground(s_bottom_label);
    }
    // 工具状态标签
    if (s_tool_status_label && lv_obj_is_valid(s_tool_status_label)) {
        lv_obj_move_foreground(s_tool_status_label);
    }
    // 最前：音量图标、WiFi信号图标、电量图标
    if (s_vol_ui.icon && lv_obj_is_valid(s_vol_ui.icon)) {
        lv_obj_move_foreground(s_vol_ui.icon);
    }
    if (s_sig_ui.canvas && lv_obj_is_valid(s_sig_ui.canvas)) {
        lv_obj_move_foreground(s_sig_ui.canvas);
    }
    // 电量图标各组件
    if (s_bat_ui.body && lv_obj_is_valid(s_bat_ui.body)) lv_obj_move_foreground(s_bat_ui.body);
    if (s_bat_ui.top && lv_obj_is_valid(s_bat_ui.top)) lv_obj_move_foreground(s_bat_ui.top);
    if (s_bat_ui.label && lv_obj_is_valid(s_bat_ui.label)) lv_obj_move_foreground(s_bat_ui.label);
    if (s_bat_ui.fill && lv_obj_is_valid(s_bat_ui.fill)) lv_obj_move_foreground(s_bat_ui.fill);
}

// ==================== 初始化 ====================
esp_err_t eeui_port_init(void)
{
    ESP_LOGI(TAG, "初始化 EEUI (LVGL 9 直接驱动)...");

    esp_lcd_panel_io_handle_t panel_io = NULL;
    esp_lcd_panel_handle_t panel = NULL;

    ESP_LOGI(TAG, "初始化 SPI LCD...");
    spi_bus_config_t bus_config = {};
    bus_config.sclk_io_num = board_get_config()->display_spi_clk;
    bus_config.mosi_io_num = board_get_config()->display_spi_mosi;
    bus_config.miso_io_num = -1;
    bus_config.quadwp_io_num = -1;
    bus_config.quadhd_io_num = -1;
    // 注意：必须用板型配置的宽高，不能用 s_screen_width（此时还是 0）！
    // max_transfer_sz=0 会被 ESP-IDF 回退到 SPI 内部 FIFO 大小（64B），
    // 每帧图像被拆成 64B 碎片传输，屏幕刷新极慢/卡死。
    // 设为整帧大小（240x240x2=115200），DMA 一次传输即可
    bus_config.max_transfer_sz = board_get_config()->display_width *
                                 board_get_config()->display_height * 2;
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &bus_config, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_spi_config_t io_config = {};
    io_config.dc_gpio_num = (gpio_num_t)board_get_config()->display_spi_dc;
    io_config.cs_gpio_num = (gpio_num_t)board_get_config()->display_spi_cs;
    io_config.pclk_hz = 40 * 1000 * 1000;
    io_config.lcd_cmd_bits = 8;
    io_config.lcd_param_bits = 8;
    io_config.spi_mode = 0;
    io_config.trans_queue_depth = 3;
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)SPI2_HOST,
                                              &io_config, &panel_io));

    esp_lcd_panel_dev_config_t panel_config = {};
    panel_config.reset_gpio_num = (gpio_num_t)board_get_config()->display_rst;
    panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB;
    panel_config.bits_per_pixel = 16;
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(panel_io, &panel_config, &panel));
    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel));
    esp_lcd_panel_invert_color(panel, true);
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel, true));

    s_panel_io = panel_io;
    s_lcd_panel = panel;
    s_screen_width = board_get_config()->display_width;
    s_screen_height = board_get_config()->display_height;
    ESP_LOGI(TAG, "LCD 初始化完成: %dx%d", s_screen_width, s_screen_height);

    // 恢复之前保存的旋转状态
    display_restore_rotation();

    // 背光
    int bl_pin = board_get_config()->display_bl;
    if (bl_pin >= 0) {
        ledc_timer_config_t timer_cfg = {};
        timer_cfg.speed_mode = LEDC_LOW_SPEED_MODE;
        timer_cfg.duty_resolution = LEDC_TIMER_8_BIT;
        timer_cfg.timer_num = LEDC_TIMER_2;
        timer_cfg.freq_hz = 5000;
        timer_cfg.clk_cfg = LEDC_AUTO_CLK;
        ledc_timer_config(&timer_cfg);
        ledc_channel_config_t ch_cfg = {};
        ch_cfg.gpio_num = bl_pin;
        ch_cfg.speed_mode = LEDC_LOW_SPEED_MODE;
        ch_cfg.channel = LEDC_CHANNEL_2;
        ch_cfg.timer_sel = LEDC_TIMER_2;
        ch_cfg.duty = 255;
        ch_cfg.hpoint = 0;
        ledc_channel_config(&ch_cfg);
        ESP_LOGI(TAG, "背光初始化完成 (pin=%d)", bl_pin);
    } else {
        ESP_LOGI(TAG, "无背光引脚，跳过");
    }

    s_lvgl_mutex = xSemaphoreCreateMutex();
    if (!s_lvgl_mutex) return ESP_ERR_NO_MEM;

    xSemaphoreTake(s_lvgl_mutex, portMAX_DELAY);
    lv_init();

    // 根据实际屏幕尺寸动态分配显示缓冲区（DMA-capable 内部 RAM）
    size_t buf_size = (size_t)s_screen_width * 10 * 2;
    s_buf1 = (uint8_t *)heap_caps_malloc(buf_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    s_buf2 = (uint8_t *)heap_caps_malloc(buf_size, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    if (!s_buf1 || !s_buf2) {
        ESP_LOGE(TAG, "显示缓冲区分配失败");
        if (s_buf1) { free(s_buf1); s_buf1 = NULL; }
        if (s_buf2) { free(s_buf2); s_buf2 = NULL; }
        xSemaphoreGive(s_lvgl_mutex);
        vSemaphoreDelete(s_lvgl_mutex); s_lvgl_mutex = NULL;
        return ESP_FAIL;
    }

    s_display = lv_display_create(s_screen_width, s_screen_height);
    lv_display_set_color_format(s_display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(s_display, disp_flush_cb);
    lv_display_set_buffers(s_display, s_buf1, s_buf2, buf_size,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    esp_lcd_panel_io_callbacks_t cbs = {};
    cbs.on_color_trans_done = on_color_trans_done_cb;
    esp_lcd_panel_io_register_event_callbacks(panel_io, &cbs, s_display);

    s_container = lv_obj_create(lv_scr_act());
    lv_obj_set_size(s_container, s_screen_width, s_screen_height);
    lv_obj_align(s_container, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_obj_remove_flag(s_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(s_container, LV_SCROLLBAR_MODE_OFF);
    lv_obj_set_style_clip_corner(s_container, true, 0);
    lv_obj_set_style_border_width(s_container, 0, 0);
    lv_obj_set_style_pad_all(s_container, 0, 0);
    lv_obj_set_style_radius(s_container, 0, 0);
    lv_obj_set_style_bg_color(s_container, lv_color_white(), 0);
    xSemaphoreGive(s_lvgl_mutex);

    esp_timer_create_args_t tick_args = {};
    tick_args.callback = lv_tick_cb;
    tick_args.arg = NULL;
    tick_args.dispatch_method = ESP_TIMER_TASK;
    tick_args.name = "lv_tick";
    ESP_ERROR_CHECK(esp_timer_create(&tick_args, &s_tick_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(s_tick_timer, 5000));

    // 信号强度定时轮询（每 1 秒，Arduino 一致）
    esp_timer_create_args_t sig_args = {};
    sig_args.callback = [] (void*) {
        extern int8_t s_wifi_rssi;  // wifi.c 中维护
        // RSSI 读取和强度计算不需要 LVGL 锁，放在外面避免因锁超时跳过更新
        int strength = 0;
        if (s_wifi_rssi >= -60) strength = 3;
        else if (s_wifi_rssi >= -75) strength = 2;
        else if (s_wifi_rssi >= -90) strength = 1;
        else strength = 0;
        // render_signal 内部自己加锁，不要在外部重复加锁
        eeui_port_render_signal(strength);
    };
    sig_args.name = "sig_poll";
    ESP_ERROR_CHECK(esp_timer_create(&sig_args, &s_signal_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(s_signal_timer, 1000000));

    // LVGL 任务（双核 Core 1 / 单核 Core 0, 优先级 1, 16384 栈——GIF 渲染 + LVGL 刷新管线需要大栈）
    BaseType_t ret = xTaskCreatePinnedToCore(lvgl_task, "LVGL", 16384, NULL, 1, NULL, BOARD_TASK_CORE_1);
    if (ret != pdPASS) {
        ESP_LOGE(TAG, "创建 LVGL 任务失败");
        // 清理已创建的资源：timers、display buffers、LCD panel、mutex
        if (s_tick_timer) { esp_timer_stop(s_tick_timer); esp_timer_delete(s_tick_timer); s_tick_timer = NULL; }
        if (s_signal_timer) { esp_timer_stop(s_signal_timer); esp_timer_delete(s_signal_timer); s_signal_timer = NULL; }
        if (s_buf1) { free(s_buf1); s_buf1 = NULL; }
        if (s_buf2) { free(s_buf2); s_buf2 = NULL; }
        if (s_lcd_panel) { esp_lcd_panel_del(s_lcd_panel); s_lcd_panel = NULL; }
        if (s_panel_io) { esp_lcd_panel_io_del(s_panel_io); s_panel_io = NULL; }
        if (s_lvgl_mutex) { vSemaphoreDelete(s_lvgl_mutex); s_lvgl_mutex = NULL; }
        return ESP_FAIL;
    }

    eeui_port_wait_init();

    // LVGL 就绪后，主动创建常驻图标（WiFi 信号、音量、电量）
    // 这些图标需要常驻显示，不能等事件触发才创建
    // 注意：render_* 内部会自己加锁，不能在外层加锁
    eeui_port_render_signal(0);  // 初始无信号（灰色），之后由定时器更新
    eeui_port_render_volume(audio_get_volume());  // 创建音量图标，bar/label 1.5s 后隐藏，icon 常驻
    eeui_port_render_battery(100);  // 电量图标显示 100%（暂无硬件，假数据）

    // 创建完所有图标后，统一重排层级
    if (lvgl_lock(200)) {
        ui_reorder_layers();
        lvgl_unlock();
    }

    ESP_LOGI(TAG, "EEUI (LVGL 9 直接驱动) 初始化完成");
    // 字体版本指纹：font_puhui_16_4.c 重新生成后 cmap 数量变化（旧残缺版=54，全量版=96）。
    // 若此日志显示 54 说明固件里还是旧字体（未重新编译/烧录）。
    const lv_font_fmt_txt_dsc_t *fdsc = (const lv_font_fmt_txt_dsc_t *)font_puhui_16_4.dsc;
    ESP_LOGI(TAG, "字体指纹 font_puhui_16_4: cmap_num=%u, line_height=%d (全量版应为 96)",
             (unsigned)fdsc->cmap_num, font_puhui_16_4.line_height);
    return ESP_OK;
}

void eeui_port_wait_init(void)
{
    int wait = 0;
    while (!s_lvgl_ready && wait < 100) {
        vTaskDelay(pdMS_TO_TICKS(10));
        wait++;
    }
}

// ==================== 表情渲染（直接锁，不用 async_call）====================
// 默认优先使用从服务端下载的表情（PSRAM），未下载或下载失败时回退到编译内置 GIF；
// emotion_builtin_only 板型（如 1.54 寸 LCD 官方板）只用编译内置表情，不从服务器下载
static const lv_img_dsc_t *find_emotion_img(const char *name)
{
    // 1. 非内置-only 板型：优先查找已下载的表情
    const board_config_t *bcfg = board_get_config();
    if (!(bcfg && bcfg->emotion_builtin_only)) {
        const lv_img_dsc_t *downloaded = get_downloaded_gif(name);
        if (downloaded) return downloaded;
    }

    // 2. 回退到编译内置的 GIF
    for (int i = 0; i < s_emotions_count; i++) {
        if (strcmp(s_emotions[i].name, name) == 0) return s_emotions[i].img;
    }
    return NULL;
}

void eeui_port_render_emotion(const char *name)
{
    if (!s_lvgl_ready || !name) return;
    // 系统表情渲染时清除 Lua 插件绘制的临时对象（保持原行为）；
    // 注意：show_card 卡片【不】在此清除——卡片与语音播报同步展示
    // （工具调用 → 卡片显示 → TTS 播报，表情变化不应清掉卡片），
    // 卡片由 eeui_port_clear_cards() 在会话边界（唤醒/会话结束）清除。
    lua_lvgl_reset();

    const lv_img_dsc_t *img = find_emotion_img(name);
    if (!img) { ESP_LOGW(TAG, "未找到表情: %s", name); return; }

    if (lvgl_lock(200)) {
        if (s_emo_img != NULL && lv_obj_is_valid(s_emo_img)) {
            // === 复用旧对象，原地更换 canvas 数据 ===
            // 直接操作 lv_gif_t 内部 canvas：不创建新对象、不删除旧对象，
            // 完全避免 LVGL 脏区域刷新导致的黑框闪烁。
            // lv_gif_set_src 内部会清空并重建 canvas，不触发对象级刷新。
            lv_gif_set_src(s_emo_img, img);

            ui_reorder_layers();
            lv_refr_now(NULL);
        } else {
            // 首次创建：没有旧对象可复用
            s_emo_img = lv_gif_create(s_container);
            if (s_emo_img) {
                lv_obj_set_style_bg_opa(s_emo_img, LV_OPA_TRANSP, 0);
                lv_obj_align(s_emo_img, LV_ALIGN_CENTER, 0, 0);
                lv_gif_set_src(s_emo_img, img);

                ui_reorder_layers();
                lv_refr_now(NULL);
            }
        }
        lvgl_unlock();
    }
}

// ==================== OTA 圆形进度条（对齐 Arduino eeui.cpp render_ota_percent）====================
void eeui_port_render_ota_percent(int percent)
{
    if (!s_lvgl_ready) return;
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;

    if (lvgl_lock(100)) {
        // 首次调用：创建全屏遮罩，隐藏所有 UI 元素
        if (s_ota_overlay == NULL) {
            // 删除表情 GIF
            if (s_emo_img != NULL && lv_obj_is_valid(s_emo_img)) {
                lv_gif_pause(s_emo_img);
                lv_anim_delete(s_emo_img, NULL);
                lv_obj_delete(s_emo_img);
                s_emo_img = NULL;
            }
            // 删除状态文字
            if (s_status_label != NULL && lv_obj_is_valid(s_status_label)) {
                lv_obj_delete(s_status_label);
                s_status_label = NULL;
            }
            // 删除底部字幕
            if (s_bottom_label != NULL && lv_obj_is_valid(s_bottom_label)) {
                lv_obj_delete(s_bottom_label);
                s_bottom_label = NULL;
            }
            // 删除工具状态文字
            if (s_tool_status_label != NULL && lv_obj_is_valid(s_tool_status_label)) {
                lv_obj_delete(s_tool_status_label);
                s_tool_status_label = NULL;
            }
            // 隐藏电池图标（不删除，保留结构体状态）
            if (s_bat_ui.body != NULL && lv_obj_is_valid(s_bat_ui.body)) {
                lv_obj_add_flag(s_bat_ui.body, LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(s_bat_ui.top, LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(s_bat_ui.label, LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(s_bat_ui.fill, LV_OBJ_FLAG_HIDDEN);
            }
            // 隐藏音量图标
            if (s_vol_ui.icon != NULL && lv_obj_is_valid(s_vol_ui.icon)) {
                lv_obj_add_flag(s_vol_ui.icon, LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(s_vol_ui.bar, LV_OBJ_FLAG_HIDDEN);
                lv_obj_add_flag(s_vol_ui.label, LV_OBJ_FLAG_HIDDEN);
            }
            // 隐藏信号图标
            if (s_sig_ui.canvas != NULL && lv_obj_is_valid(s_sig_ui.canvas)) {
                lv_obj_add_flag(s_sig_ui.canvas, LV_OBJ_FLAG_HIDDEN);
            }

            // 创建全屏白色遮罩（覆盖所有 UI，遮挡底层元素）
            s_ota_overlay = lv_obj_create(s_container);
            lv_obj_set_size(s_ota_overlay, s_screen_width, s_screen_height);
            lv_obj_set_pos(s_ota_overlay, 0, 0);
            lv_obj_set_style_bg_color(s_ota_overlay, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(s_ota_overlay, LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(s_ota_overlay, 0, 0);
            lv_obj_set_style_radius(s_ota_overlay, 0, 0);
            lv_obj_set_scrollbar_mode(s_ota_overlay, LV_SCROLLBAR_MODE_OFF);
            lv_obj_remove_flag(s_ota_overlay, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_move_foreground(s_ota_overlay);

            // 百分比文字标签（在遮罩之上）
            s_ota_label = lv_label_create(s_ota_overlay);
            lv_obj_set_style_text_font(s_ota_label, &font_puhui_16_4, 0);
            lv_obj_set_style_text_color(s_ota_label, lv_color_make(80, 80, 80), 0);
            lv_obj_center(s_ota_label);

            // 圆形进度环（在遮罩之上）
            s_ota_arc = lv_arc_create(s_ota_overlay);
            lv_arc_set_rotation(s_ota_arc, 270);
            lv_arc_set_bg_angles(s_ota_arc, 0, 360);
            lv_arc_set_range(s_ota_arc, 0, 100);
            lv_obj_set_size(s_ota_arc, 150, 150);
            lv_obj_center(s_ota_arc);

            // "正在升级" 状态文字（在遮罩之上，进度环下方）
            s_ota_status_label = lv_label_create(s_ota_overlay);
            lv_obj_set_style_text_font(s_ota_status_label, &font_puhui_16_4, 0);
            lv_obj_set_style_text_color(s_ota_status_label, lv_color_make(120, 120, 120), 0);
            lv_label_set_text(s_ota_status_label, "正在升级");
            lv_obj_align(s_ota_status_label, LV_ALIGN_CENTER, 0, 95);

            // 移除 knob，不可点击
            lv_obj_remove_style(s_ota_arc, NULL, LV_PART_KNOB);
            lv_obj_remove_flag(s_ota_arc, LV_OBJ_FLAG_CLICKABLE);

            // 弧线颜色样式
            lv_obj_set_style_arc_color(s_ota_arc, lv_color_make(220, 220, 220), LV_PART_MAIN);
            lv_obj_set_style_arc_width(s_ota_arc, 8, LV_PART_MAIN);
            lv_obj_set_style_arc_color(s_ota_arc, lv_color_make(102, 126, 234), LV_PART_INDICATOR);
            lv_obj_set_style_arc_width(s_ota_arc, 8, LV_PART_INDICATOR);
            lv_obj_set_style_arc_rounded(s_ota_arc, true, LV_PART_INDICATOR);
        }

        // 更新进度
        lv_arc_set_value(s_ota_arc, percent);
        lv_label_set_text_fmt(s_ota_label, "%d%%", percent);

        lvgl_unlock();
    }
}

void eeui_port_clear_ota_progress(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        // 删除全屏遮罩（自动销毁其子对象 arc + label）
        if (s_ota_overlay && lv_obj_is_valid(s_ota_overlay)) {
            lv_obj_delete(s_ota_overlay);
            s_ota_overlay = NULL;
        }
        s_ota_arc = NULL;
        s_ota_label = NULL;
        s_ota_status_label = NULL;

        // 恢复隐藏的图标（取消隐藏）
        if (s_bat_ui.body != NULL && lv_obj_is_valid(s_bat_ui.body)) {
            lv_obj_remove_flag(s_bat_ui.body, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.top, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.label, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.fill, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_vol_ui.icon != NULL && lv_obj_is_valid(s_vol_ui.icon)) {
            lv_obj_remove_flag(s_vol_ui.icon, LV_OBJ_FLAG_HIDDEN);
            if (s_vol_ui.bar) lv_obj_remove_flag(s_vol_ui.bar, LV_OBJ_FLAG_HIDDEN);
            if (s_vol_ui.label) lv_obj_remove_flag(s_vol_ui.label, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_sig_ui.canvas != NULL && lv_obj_is_valid(s_sig_ui.canvas)) {
            lv_obj_remove_flag(s_sig_ui.canvas, LV_OBJ_FLAG_HIDDEN);
        }

        lvgl_unlock();
    }
}

// ==================== 状态文字 ====================
void eeui_port_set_status_text(const char *text, bool need_ani, const char *align)
{
    if (!s_lvgl_ready || !text) return;
    if (lvgl_lock(100)) {
        if (s_status_label == NULL) {
            s_status_label = lv_label_create(s_container);
            lv_label_set_long_mode(s_status_label, LV_LABEL_LONG_WRAP);
            lv_obj_set_width(s_status_label, s_screen_width);
            lv_obj_set_style_text_font(s_status_label, &font_puhui_16_4, 0);
            lv_obj_set_style_text_color(s_status_label, lv_color_black(), 0);
            lv_obj_set_style_bg_color(s_status_label, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(s_status_label, LV_OPA_50, 0);
            lv_obj_set_style_pad_left(s_status_label, 3, 0);
            lv_obj_set_style_pad_right(s_status_label, 3, 0);
            lv_obj_move_foreground(s_status_label);
        }
        lv_label_set_text(s_status_label, text);
        lv_obj_update_layout(s_status_label);
        lv_obj_set_pos(s_status_label, 0, 3);
        if (strcmp(align ? align : "top_left", "bottom_center") == 0) {
            lv_coord_t w = lv_obj_get_self_width(s_status_label);
            lv_obj_set_pos(s_status_label, s_screen_width / 2 - w / 2, s_screen_height - 30);
        }
        // 统一重排层级，确保图标在最前
        ui_reorder_layers();
        lvgl_unlock();
    }
}

// ==================== 底部字幕 ====================
void eeui_port_set_bottom_text(const char *text)
{
    if (!s_lvgl_ready || !text) return;
    if (lvgl_lock(100)) {
        if (s_bottom_label == NULL) {
            s_bottom_label = lv_label_create(s_container);
            lv_label_set_long_mode(s_bottom_label, LV_LABEL_LONG_WRAP);
            lv_obj_set_width(s_bottom_label, s_screen_width);
            lv_obj_set_style_text_font(s_bottom_label, &font_puhui_16_4, 0);
            lv_obj_set_style_text_color(s_bottom_label, lv_color_make(25, 50, 83), 0);
            lv_obj_set_style_bg_color(s_bottom_label, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(s_bottom_label, LV_OPA_50, 0);
            lv_obj_set_style_pad_left(s_bottom_label, 5, 0);
            lv_obj_set_style_pad_right(s_bottom_label, 5, 0);
            lv_obj_move_foreground(s_bottom_label);
        }
        lv_label_set_text(s_bottom_label, text);
        lv_obj_update_layout(s_bottom_label);
        lv_coord_t h = lv_obj_get_self_height(s_bottom_label);
        lv_obj_set_pos(s_bottom_label, 0, s_screen_height - h - 5);
        // 统一重排层级，确保图标在最前
        ui_reorder_layers();
        lvgl_unlock();
    }
}

// ==================== 工具状态（底部，独立于字幕）====================
// 与字幕同位置但独立标签，显示时覆盖字幕，清除后字幕恢复可见
void eeui_port_set_tool_status_text(const char *text)
{
    if (!s_lvgl_ready || !text) return;
    if (lvgl_lock(100)) {
        if (s_tool_status_label == NULL) {
            s_tool_status_label = lv_label_create(s_container);
            lv_label_set_long_mode(s_tool_status_label, LV_LABEL_LONG_WRAP);
            lv_obj_set_width(s_tool_status_label, s_screen_width);
            lv_obj_set_style_text_font(s_tool_status_label, &font_puhui_16_4, 0);
            lv_obj_set_style_text_color(s_tool_status_label, lv_color_make(80, 80, 200), 0);
            lv_obj_set_style_bg_color(s_tool_status_label, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(s_tool_status_label, LV_OPA_80, 0);
            lv_obj_set_style_pad_left(s_tool_status_label, 5, 0);
            lv_obj_set_style_pad_right(s_tool_status_label, 5, 0);
        }
        lv_label_set_text(s_tool_status_label, text);
        lv_obj_update_layout(s_tool_status_label);
        lv_coord_t h = lv_obj_get_self_height(s_tool_status_label);
        // 与字幕相同位置（底部）
        lv_obj_set_pos(s_tool_status_label, 0, s_screen_height - h - 5);
        // 移到最前，覆盖字幕
        lv_obj_move_foreground(s_tool_status_label);
        lvgl_unlock();
    }
}

void eeui_port_clear_tool_status(void)
{
    if (!s_lvgl_ready || !s_tool_status_label) return;
    if (lvgl_lock(100)) {
        if (s_tool_status_label && lv_obj_is_valid(s_tool_status_label)) {
            lv_obj_delete(s_tool_status_label);
            s_tool_status_label = NULL;
        }
        lvgl_unlock();
    }
}

extern "C" lv_obj_t *eeui_port_get_container(void)
{
    return s_container;
}

// ==================== 背光 ====================
void eeui_port_set_brightness(int percent)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    // 检查是否配置了背光引脚（未配置时 LEDC 通道未初始化）
    if (board_get_config()->display_bl < 0) {
        ESP_LOGW(TAG, "未配置背光引脚，无法设置亮度");
        return;
    }
    // LEDC_TIMER_8_BIT → max duty = 255
    uint32_t duty = (uint32_t)(percent * 255 / 100);
    esp_err_t ret = ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2, duty);
    if (ret == ESP_OK) {
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_2);
        ESP_LOGI(TAG, "背光亮度: %d%% (duty=%lu)", percent, (unsigned long)duty);
    } else {
        ESP_LOGW(TAG, "设置背光占空比失败: %s", esp_err_to_name(ret));
    }
}

// ==================== 电量 ====================
// 对齐 Arduino eeui.cpp render_battery_todo（12x16 电池外框 + 正极 + 百分比文字 + 内部电量条）
#define BAT_WIDTH  12
#define BAT_HEIGHT 16
#define BAT_TOP_W  4
#define BAT_TOP_H  2

void eeui_port_render_battery(int percent)
{
    if (!s_lvgl_ready) return;
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    s_bat_ui.percent = percent;

    if (lvgl_lock(100)) {
        bool is_low_bat = (percent <= 20);
        int offset_right = get_bat_offset(percent);
        int x = s_screen_width - offset_right;
        int y = 2;
        int fill_h = (BAT_HEIGHT - 4) * percent / 100;

        if (s_bat_ui.body == NULL) {
            // 首次创建：电池外框
            s_bat_ui.body = lv_obj_create(s_container);
            lv_obj_set_size(s_bat_ui.body, BAT_WIDTH, BAT_HEIGHT);
            lv_obj_set_style_radius(s_bat_ui.body, 3, 0);
            lv_obj_set_style_border_width(s_bat_ui.body, 1, 0);
            lv_obj_set_style_border_color(s_bat_ui.body, lv_color_make(80, 80, 80), 0);
            lv_obj_set_style_bg_color(s_bat_ui.body, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(s_bat_ui.body, LV_OPA_TRANSP, 0);
            lv_obj_set_scrollbar_mode(s_bat_ui.body, LV_SCROLLBAR_MODE_OFF);
            lv_obj_remove_flag(s_bat_ui.body, LV_OBJ_FLAG_SCROLLABLE);

            // 电池正极（顶部小方块）
            s_bat_ui.top = lv_obj_create(s_container);
            lv_obj_set_size(s_bat_ui.top, BAT_TOP_W, BAT_TOP_H);
            lv_obj_set_style_radius(s_bat_ui.top, 1, 0);
            lv_obj_set_style_border_width(s_bat_ui.top, 1, 0);
            lv_obj_set_style_border_color(s_bat_ui.top, lv_color_make(80, 80, 80), 0);
            lv_obj_set_style_bg_color(s_bat_ui.top, lv_color_make(80, 80, 80), 0);
            lv_obj_set_style_bg_opa(s_bat_ui.top, LV_OPA_COVER, 0);
            lv_obj_set_scrollbar_mode(s_bat_ui.top, LV_SCROLLBAR_MODE_OFF);
            lv_obj_remove_flag(s_bat_ui.top, LV_OBJ_FLAG_SCROLLABLE);

            // 百分比文字
            s_bat_ui.label = lv_label_create(s_container);
            lv_obj_set_style_text_font(s_bat_ui.label, &font_puhui_16_4, 0);

            // 内部电量条
            s_bat_ui.fill = lv_obj_create(s_container);
            lv_obj_set_style_radius(s_bat_ui.fill, 1, 0);
            lv_obj_set_style_border_width(s_bat_ui.fill, 0, 0);
            lv_obj_set_scrollbar_mode(s_bat_ui.fill, LV_SCROLLBAR_MODE_OFF);
            lv_obj_remove_flag(s_bat_ui.fill, LV_OBJ_FLAG_SCROLLABLE);
        }

        // 更新位置和大小
        lv_obj_set_pos(s_bat_ui.body, x, y);
        lv_obj_set_pos(s_bat_ui.top, x + BAT_WIDTH / 2 - BAT_TOP_W / 2, y - BAT_TOP_H / 2);

        char buf[16];
        snprintf(buf, sizeof(buf), "%d%%", percent);
        lv_label_set_text(s_bat_ui.label, buf);
        lv_obj_set_pos(s_bat_ui.label, x + BAT_WIDTH + 3, y);

        lv_obj_set_size(s_bat_ui.fill, BAT_WIDTH - 4, fill_h);
        lv_obj_set_pos(s_bat_ui.fill, x + 2, y + 2 + (BAT_HEIGHT - 4 - fill_h));

        // 低电量红色，正常绿色
        lv_color_t fill_color = is_low_bat ? lv_color_make(255, 0, 0) : lv_color_make(0, 180, 80);
        lv_obj_set_style_bg_color(s_bat_ui.fill, fill_color, 0);
        lv_obj_set_style_bg_opa(s_bat_ui.fill, LV_OPA_COVER, 0);

        ui_reorder_layers();
        lvgl_unlock();
    }
}

void eeui_port_hide_battery(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        if (s_bat_ui.body && lv_obj_is_valid(s_bat_ui.body)) lv_obj_delete(s_bat_ui.body);
        if (s_bat_ui.top && lv_obj_is_valid(s_bat_ui.top)) lv_obj_delete(s_bat_ui.top);
        if (s_bat_ui.label && lv_obj_is_valid(s_bat_ui.label)) lv_obj_delete(s_bat_ui.label);
        if (s_bat_ui.fill && lv_obj_is_valid(s_bat_ui.fill)) lv_obj_delete(s_bat_ui.fill);
        s_bat_ui = {};
        lvgl_unlock();
    }
}

// ==================== 音量、信号 ====================

// LVGL 9.2 canvas 辅助：填充矩形（逐像素，替代废弃的 lv_canvas_draw_rect）
static void canvas_fill_rect(lv_obj_t *canvas, int x, int y, int w, int h, lv_color_t color, lv_opa_t opa)
{
    for (int row = y; row < y + h; row++) {
        for (int col = x; col < x + w; col++) {
            lv_canvas_set_px(canvas, col, row, color, opa);
        }
    }
}

// LVGL 9.2 canvas 辅助：画点（替代单像素 lv_canvas_draw_rect）
static void canvas_draw_px(lv_obj_t *canvas, int x, int y, lv_color_t color, lv_opa_t opa)
{
    lv_canvas_set_px(canvas, x, y, color, opa);
}

// 音量图标 + 进度条（Arduino 一致）
#define VOL_CANVAS_W 28
#define VOL_CANVAS_H 32
#define VOL_BAR_W 20
#define VOL_BAR_H 140

// 信号强度图标
#define SIG_CANVAS_W 28
#define SIG_CANVAS_H 32

static void volume_hide_cb(void *arg)
{
    if (lvgl_lock(50)) {
        if (s_vol_ui.bar && lv_obj_is_valid(s_vol_ui.bar)) {
            lv_obj_add_flag(s_vol_ui.bar, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_vol_ui.label && lv_obj_is_valid(s_vol_ui.label)) {
            lv_obj_add_flag(s_vol_ui.label, LV_OBJ_FLAG_HIDDEN);
        }
        lvgl_unlock();
    }
}

void eeui_port_render_volume(float volume)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        // === 音量图标（LVGL 符号字体，不强制指定字体让系统 fallback）===
        if (s_vol_ui.icon == NULL) {
            s_vol_ui.icon = lv_label_create(s_container);
            lv_label_set_text(s_vol_ui.icon, LV_SYMBOL_VOLUME_MAX);
            /* 音量图标用 LVGL 内置 symbol 字形（仅 montserrat 系列包含），
             * 显式指定避免 fallback 到中文字体（font_puhui_16_4 无 symbol 字形）导致方框 */
            lv_obj_set_style_text_font(s_vol_ui.icon, &lv_font_montserrat_14, 0);
            lv_obj_set_pos(s_vol_ui.icon, 130, 2);
        }

        // 根据实时音量切换符号
        if (volume <= 0.0f) {
            lv_label_set_text(s_vol_ui.icon, LV_SYMBOL_MUTE);
        } else if (volume < 0.5f) {
            lv_label_set_text(s_vol_ui.icon, LV_SYMBOL_VOLUME_MID);
        } else {
            lv_label_set_text(s_vol_ui.icon, LV_SYMBOL_VOLUME_MAX);
        }
        lv_obj_set_style_text_color(s_vol_ui.icon, lv_color_make(80, 80, 80), 0);
        lv_obj_set_pos(s_vol_ui.icon, 130, 2);
        lv_obj_move_foreground(s_vol_ui.icon);

        // === 音量进度条（竖条，Arduino 一致）===
        if (s_vol_ui.bar == NULL) {
            s_vol_ui.bar = lv_bar_create(s_container);
            lv_obj_set_size(s_vol_ui.bar, VOL_BAR_W, VOL_BAR_H);
            lv_bar_set_range(s_vol_ui.bar, 0, 100);
            lv_bar_set_mode(s_vol_ui.bar, LV_BAR_MODE_NORMAL);
            // 进度条位于屏幕左侧中部
            lv_obj_align(s_vol_ui.bar, LV_ALIGN_LEFT_MID, 10, 0);
            // 进度条背景样式
            lv_obj_set_style_bg_color(s_vol_ui.bar, lv_color_make(220, 220, 220), LV_PART_MAIN);
            lv_obj_set_style_bg_opa(s_vol_ui.bar, LV_OPA_50, LV_PART_MAIN);
            lv_obj_set_style_radius(s_vol_ui.bar, 5, LV_PART_MAIN);
            // 进度条指示器样式：蓝紫色渐变
            lv_obj_set_style_bg_color(s_vol_ui.bar, lv_color_make(102, 126, 234), LV_PART_INDICATOR);
            lv_obj_set_style_radius(s_vol_ui.bar, 5, LV_PART_INDICATOR);

            // 百分比标签
            s_vol_ui.label = lv_label_create(s_container);
            lv_obj_set_style_text_font(s_vol_ui.label, &lv_font_montserrat_14, 0);
            lv_label_set_text(s_vol_ui.label, "");
        }

        // 更新进度条位置（始终左侧中部）
        lv_obj_align(s_vol_ui.bar, LV_ALIGN_LEFT_MID, 10, 0);

        // 更新进度条值（Arduino 一致：500ms 动画过渡）
        int val = (int)(volume * 100);
        lv_bar_set_value(s_vol_ui.bar, val, LV_ANIM_ON);
        lv_obj_clear_flag(s_vol_ui.bar, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(s_vol_ui.bar);

        char buf[8];
        snprintf(buf, sizeof(buf), "%d%%", val);
        lv_label_set_text(s_vol_ui.label, buf);
        lv_obj_clear_flag(s_vol_ui.label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_align_to(s_vol_ui.label, s_vol_ui.bar, LV_ALIGN_OUT_BOTTOM_MID, 0, 5);

        s_vol_ui.current_volume = volume;

        // 1.5 秒后自动隐藏进度条和标签
        if (s_vol_ui.hide_timer) {
            esp_timer_stop(s_vol_ui.hide_timer);
        }
        if (s_vol_ui.hide_timer == NULL) {
            esp_timer_create_args_t targs = {};
            targs.callback = volume_hide_cb;
            targs.dispatch_method = ESP_TIMER_TASK;
            targs.name = "vol_hide";
            esp_timer_create(&targs, &s_vol_ui.hide_timer);
        }
        esp_timer_start_once(s_vol_ui.hide_timer, 1500000);

        lvgl_unlock();
    }
}

// ==================== 音乐播放器 UI 覆盖层（移植自 xiaozhi-esp32-qingning lcd_display.cc）====================
// 全屏白色覆盖层，包含：歌曲名、艺术家、当前歌词、下句歌词、进度条、当前时间、总时长

static lv_obj_t *s_music_overlay = NULL;             // 覆盖层容器
static lv_obj_t *s_music_song_label = NULL;           // 歌曲名标签
static lv_obj_t *s_music_artist_label = NULL;         // 艺术家标签
static lv_obj_t *s_music_current_lyric = NULL;        // 当前歌词标签
static lv_obj_t *s_music_next_lyric = NULL;           // 下一句歌词标签
static lv_obj_t *s_music_progress_bar = NULL;         // 进度条
static lv_obj_t *s_music_time_label = NULL;           // 当前时间标签
static lv_obj_t *s_music_total_time_label = NULL;     // 总时长标签
static bool s_music_overlay_visible = false;

static void eeui_port_destroy_music_overlay_locked(void)
{
    if (s_music_overlay) {
        lv_obj_delete(s_music_overlay);
        s_music_overlay = NULL;
        s_music_song_label = NULL;
        s_music_artist_label = NULL;
        s_music_current_lyric = NULL;
        s_music_next_lyric = NULL;
        s_music_progress_bar = NULL;
        s_music_time_label = NULL;
        s_music_total_time_label = NULL;
        s_music_overlay_visible = false;
    }
}

static void eeui_port_create_music_overlay_locked(void)
{
    if (s_music_overlay != NULL) return;

    auto screen = lv_scr_act();

    // 创建覆盖层容器 - 不透明白色背景
    s_music_overlay = lv_obj_create(screen);
    lv_obj_set_size(s_music_overlay, s_screen_width, s_screen_height);
    lv_obj_set_style_bg_color(s_music_overlay, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(s_music_overlay, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(s_music_overlay, 0, 0);
    lv_obj_set_style_pad_all(s_music_overlay, 0, 0);
    lv_obj_set_style_border_width(s_music_overlay, 0, 0);
    lv_obj_align(s_music_overlay, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_obj_set_scrollbar_mode(s_music_overlay, LV_SCROLLBAR_MODE_OFF);
    lv_obj_remove_flag(s_music_overlay, LV_OBJ_FLAG_SCROLLABLE);

    // 创建垂直布局容器（中间 90% 区域）
    lv_obj_t *content = lv_obj_create(s_music_overlay);
    lv_obj_set_size(content, (int)(s_screen_width * 0.9f), (int)(s_screen_height * 0.9f));
    lv_obj_set_style_bg_color(content, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(content, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(content, 0, 0);
    lv_obj_set_style_pad_all(content, 10, 0);
    lv_obj_set_flex_flow(content, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_flex_align(content, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_row(content, 10, 0);
    lv_obj_align(content, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_scrollbar_mode(content, LV_SCROLLBAR_MODE_OFF);
    lv_obj_remove_flag(content, LV_OBJ_FLAG_SCROLLABLE);

    // 歌曲名标签 - 顶部
    s_music_song_label = lv_label_create(content);
    lv_obj_set_width(s_music_song_label, (int)(s_screen_width * 0.85f));
    lv_label_set_long_mode(s_music_song_label, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_align(s_music_song_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(s_music_song_label, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_song_label, lv_color_black(), 0);
    lv_label_set_text(s_music_song_label, "未知歌曲");

    // 艺术家标签
    s_music_artist_label = lv_label_create(content);
    lv_obj_set_width(s_music_artist_label, (int)(s_screen_width * 0.85f));
    lv_label_set_long_mode(s_music_artist_label, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_obj_set_style_text_align(s_music_artist_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(s_music_artist_label, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_artist_label, lv_palette_main(LV_PALETTE_GREY), 0);
    lv_label_set_text(s_music_artist_label, "未知艺术家");

    // 当前歌词标签
    s_music_current_lyric = lv_label_create(content);
    lv_obj_set_width(s_music_current_lyric, (int)(s_screen_width * 0.9f));
    lv_label_set_long_mode(s_music_current_lyric, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(s_music_current_lyric, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(s_music_current_lyric, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_current_lyric, lv_color_black(), 0);
    lv_obj_set_style_text_opa(s_music_current_lyric, LV_OPA_COVER, 0);
    lv_label_set_text(s_music_current_lyric, "");
    lv_obj_set_scrollbar_mode(s_music_current_lyric, LV_SCROLLBAR_MODE_OFF);

    // 下一句歌词标签
    s_music_next_lyric = lv_label_create(content);
    lv_obj_set_width(s_music_next_lyric, (int)(s_screen_width * 0.9f));
    lv_label_set_long_mode(s_music_next_lyric, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(s_music_next_lyric, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(s_music_next_lyric, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_next_lyric, lv_palette_main(LV_PALETTE_GREY), 0);
    lv_obj_set_style_text_opa(s_music_next_lyric, LV_OPA_60, 0);
    lv_label_set_text(s_music_next_lyric, "");
    lv_obj_set_scrollbar_mode(s_music_next_lyric, LV_SCROLLBAR_MODE_OFF);

    // 进度条区域
    lv_obj_t *progress_area = lv_obj_create(content);
    lv_obj_set_size(progress_area, (int)(s_screen_width * 0.9f), 36);
    lv_obj_set_style_bg_color(progress_area, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(progress_area, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(progress_area, 0, 0);
    lv_obj_set_style_pad_all(progress_area, 5, 0);
    lv_obj_remove_flag(progress_area, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_scrollbar_mode(progress_area, LV_SCROLLBAR_MODE_OFF);

    // 当前时间标签 - 左侧
    s_music_time_label = lv_label_create(progress_area);
    lv_obj_set_style_text_font(s_music_time_label, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_time_label, lv_color_black(), 0);
    lv_label_set_text(s_music_time_label, "0:00");
    lv_obj_align(s_music_time_label, LV_ALIGN_LEFT_MID, 0, 0);

    // 总时长标签 - 右侧
    s_music_total_time_label = lv_label_create(progress_area);
    lv_obj_set_style_text_font(s_music_total_time_label, &font_puhui_16_4, 0);
    lv_obj_set_style_text_color(s_music_total_time_label, lv_color_black(), 0);
    lv_label_set_text(s_music_total_time_label, "3:00");
    lv_obj_align(s_music_total_time_label, LV_ALIGN_RIGHT_MID, 0, 0);

    // 进度条 - 中间
    s_music_progress_bar = lv_bar_create(progress_area);
    lv_obj_set_size(s_music_progress_bar, (int)(s_screen_width * 0.5f), 6);
    lv_obj_set_style_bg_color(s_music_progress_bar, lv_palette_main(LV_PALETTE_GREY), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(s_music_progress_bar, LV_OPA_30, LV_PART_MAIN);
    lv_obj_set_style_bg_color(s_music_progress_bar, lv_palette_main(LV_PALETTE_BLUE), LV_PART_INDICATOR);
    lv_bar_set_range(s_music_progress_bar, 0, 100);
    lv_bar_set_value(s_music_progress_bar, 0, LV_ANIM_OFF);
    lv_obj_align(s_music_progress_bar, LV_ALIGN_CENTER, 0, 0);

    // 默认隐藏覆盖层
    lv_obj_add_flag(s_music_overlay, LV_OBJ_FLAG_HIDDEN);

    ESP_LOGI(TAG, "音乐播放器覆盖层创建完成");
}

void eeui_port_show_music_player(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        if (s_music_overlay == NULL) {
            eeui_port_create_music_overlay_locked();
        }
        if (s_music_overlay != NULL) {
            lv_obj_remove_flag(s_music_overlay, LV_OBJ_FLAG_HIDDEN);
            lv_obj_move_foreground(s_music_overlay);
            s_music_overlay_visible = true;
        }
        lvgl_unlock();
    }
}

void eeui_port_hide_music_player(void)
{
    if (!s_lvgl_ready) return;
    // 先恢复电池/音量/WiFi 和销毁覆盖层（需要 LVGL 锁）
    if (lvgl_lock(100)) {
        eeui_port_destroy_music_overlay_locked();

        if (s_bat_ui.body != NULL && lv_obj_is_valid(s_bat_ui.body)) {
            lv_obj_remove_flag(s_bat_ui.body, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.top, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.label, LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_bat_ui.fill, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_vol_ui.icon != NULL && lv_obj_is_valid(s_vol_ui.icon)) {
            lv_obj_remove_flag(s_vol_ui.icon, LV_OBJ_FLAG_HIDDEN);
        }
        if (s_sig_ui.canvas != NULL && lv_obj_is_valid(s_sig_ui.canvas)) {
            lv_obj_remove_flag(s_sig_ui.canvas, LV_OBJ_FLAG_HIDDEN);
        }
        lvgl_unlock();
    }
    // 恢复默认表情和状态文字（它们内部自己加锁，不要在锁内调用）
    eeui_port_render_emotion("休息中");
    eeui_port_set_status_text("休息中", true, "top_left");
}

void eeui_port_music_set_song_info(const char *song, const char *artist)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        if (s_music_song_label != NULL && song != NULL) {
            lv_label_set_text(s_music_song_label, song);
        }
        if (s_music_artist_label != NULL) {
            if (artist != NULL && strlen(artist) > 0) {
                lv_label_set_text(s_music_artist_label, artist);
            } else {
                lv_label_set_text(s_music_artist_label, "未知艺术家");
            }
        }
        lvgl_unlock();
    }
}

void eeui_port_music_update_lyrics(const char *current_lyric, const char *next_lyric)
{
    if (!s_lvgl_ready) return;
    if (!s_music_overlay_visible) return;
    if (lvgl_lock(100)) {
        if (s_music_current_lyric != NULL && current_lyric != NULL) {
            lv_label_set_text(s_music_current_lyric, current_lyric);
        }
        if (s_music_next_lyric != NULL) {
            if (next_lyric != NULL && strlen(next_lyric) > 0) {
                lv_label_set_text(s_music_next_lyric, next_lyric);
            } else {
                lv_label_set_text(s_music_next_lyric, "");
            }
        }
        lvgl_unlock();
    }
}

void eeui_port_music_update_progress(uint32_t current_ms, uint32_t total_ms)
{
    if (!s_lvgl_ready) return;
    if (!s_music_overlay_visible) return;
    if (lvgl_lock(100)) {
        // 更新进度条
        if (s_music_progress_bar != NULL && total_ms > 0) {
            int progress = (int)((current_ms * 100) / total_ms);
            if (progress > 100) progress = 100;
            lv_bar_set_value(s_music_progress_bar, progress, LV_ANIM_ON);
        }
        // 更新当前时间标签
        if (s_music_time_label != NULL) {
            uint32_t sec = current_ms / 1000;
            uint32_t min = sec / 60;
            sec = sec % 60;
            char buf[16];
            snprintf(buf, sizeof(buf), "%lu:%02lu", (unsigned long)min, (unsigned long)sec);
            lv_label_set_text(s_music_time_label, buf);
        }
        // 更新总时长标签
        if (s_music_total_time_label != NULL && total_ms > 0) {
            uint32_t sec = total_ms / 1000;
            uint32_t min = sec / 60;
            sec = sec % 60;
            char buf[16];
            snprintf(buf, sizeof(buf), "%lu:%02lu", (unsigned long)min, (unsigned long)sec);
            lv_label_set_text(s_music_total_time_label, buf);
        }
        lvgl_unlock();
    }
}

void eeui_port_music_destroy(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(100)) {
        eeui_port_destroy_music_overlay_locked();
        lvgl_unlock();
    }
}

// ==================== 表情下载中提示 ====================

void eeui_port_show_emo_downloading(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(200)) {
        // 已存在则只置顶
        if (s_emo_dl_overlay != NULL && lv_obj_is_valid(s_emo_dl_overlay)) {
            lv_obj_move_foreground(s_emo_dl_overlay);
            lvgl_unlock();
            return;
        }

        // 创建全屏白色遮罩
        s_emo_dl_overlay = lv_obj_create(s_container);
        lv_obj_set_size(s_emo_dl_overlay, s_screen_width, s_screen_height);
        lv_obj_set_pos(s_emo_dl_overlay, 0, 0);
        lv_obj_set_style_bg_color(s_emo_dl_overlay, lv_color_white(), 0);
        lv_obj_set_style_bg_opa(s_emo_dl_overlay, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(s_emo_dl_overlay, 0, 0);
        lv_obj_set_style_radius(s_emo_dl_overlay, 0, 0);
        lv_obj_set_style_pad_all(s_emo_dl_overlay, 0, 0);
        lv_obj_set_scrollbar_mode(s_emo_dl_overlay, LV_SCROLLBAR_MODE_OFF);
        lv_obj_remove_flag(s_emo_dl_overlay, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_move_foreground(s_emo_dl_overlay);

        // 创建旋转加载圆弧（spinner 风格）
        s_emo_dl_arc = lv_arc_create(s_emo_dl_overlay);
        lv_obj_set_size(s_emo_dl_arc, 60, 60);
        lv_obj_align(s_emo_dl_arc, LV_ALIGN_CENTER, 0, -20);
        lv_arc_set_range(s_emo_dl_arc, 0, 100);
        lv_arc_set_value(s_emo_dl_arc, 0);
        // 隐藏旋钮
        lv_obj_remove_style(s_emo_dl_arc, NULL, LV_PART_KNOB);
        // 设置圆弧颜色
        lv_obj_set_style_arc_color(s_emo_dl_arc, lv_color_hex(0xCCCCCC), LV_PART_MAIN);
        lv_obj_set_style_arc_color(s_emo_dl_arc, lv_color_hex(0x4A90D9), LV_PART_INDICATOR);
        lv_obj_set_style_arc_width(s_emo_dl_arc, 4, LV_PART_INDICATOR);
        lv_obj_set_style_arc_width(s_emo_dl_arc, 4, LV_PART_MAIN);
        // 启动旋转动画
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, s_emo_dl_arc);
        lv_anim_set_values(&a, 0, 360);
        lv_anim_set_duration(&a, 1000);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_exec_cb(&a, [](void *var, int32_t v) {
            lv_arc_set_start_angle((lv_obj_t *)var, v);
            lv_arc_set_end_angle((lv_obj_t *)var, v + 90);
        });
        lv_anim_start(&a);

        // 创建提示文字
        s_emo_dl_label = lv_label_create(s_emo_dl_overlay);
        lv_label_set_text(s_emo_dl_label, "表情下载中...");
        lv_obj_set_style_text_font(s_emo_dl_label, &font_puhui_16_4, 0);
        lv_obj_set_style_text_color(s_emo_dl_label, lv_color_hex(0x333333), 0);
        lv_obj_align(s_emo_dl_label, LV_ALIGN_CENTER, 0, 30);

        lvgl_unlock();
    }
    ESP_LOGI(TAG, "显示表情下载中提示");
}

void eeui_port_hide_emo_downloading(void)
{
    if (!s_lvgl_ready) return;
    if (lvgl_lock(200)) {
        if (s_emo_dl_overlay != NULL && lv_obj_is_valid(s_emo_dl_overlay)) {
            // 停止旋转动画
            if (s_emo_dl_arc) {
                lv_anim_delete(s_emo_dl_arc, NULL);
            }
            lv_obj_delete(s_emo_dl_overlay);
            s_emo_dl_overlay = NULL;
            s_emo_dl_label = NULL;
            s_emo_dl_arc = NULL;
        }
        lvgl_unlock();
    }

    // 恢复默认表情状态（内部自己加锁，不在锁内调用）
    eeui_port_render_emotion("休息中");
    eeui_port_set_status_text("休息中", true, "top_left");
    ESP_LOGI(TAG, "隐藏表情下载中提示，恢复表情状态");

    // 预解码关键表情（"聆听中"、"说话中"），消除首次唤醒时的黑框
    // 原理：首次 GIF 解码需要 LZW 解压 + PSRAM 分配 + 首帧渲染，耗时较长
    // 下载的表情（180x180）比内置的（120x120）大，首次解码更慢
    // 预解码后指令缓存和数据缓存已预热，实际唤醒时解码速度大幅提升
    vTaskDelay(pdMS_TO_TICKS(300));  // 等待"休息中"渲染完成

    const char *prewarm_names[] = {"聆听中", "说话中"};
    for (int i = 0; i < 2; i++) {
        const lv_img_dsc_t *img = find_emotion_img(prewarm_names[i]);
        if (!img) continue;

        if (lvgl_lock(500)) {
            // 创建隐藏的临时 GIF 对象进行预解码
            // lv_gif_set_src 会同步解码首帧（gd_get_frame）
            lv_obj_t *tmp = lv_gif_create(s_container);
            if (tmp) {
                lv_obj_add_flag(tmp, LV_OBJ_FLAG_HIDDEN);  // 隐藏，不影响显示
                lv_gif_set_src(tmp, img);  // 同步解码首帧，预热缓存

                // 立即删除临时对象
                lv_gif_pause(tmp);
                lv_anim_delete(tmp, NULL);
                lv_obj_delete(tmp);
                ESP_LOGI(TAG, "预解码表情: %s", prewarm_names[i]);
            }
            lvgl_unlock();
        }
        vTaskDelay(pdMS_TO_TICKS(50));  // 释放锁让 LVGL 任务运行
    }
    ESP_LOGI(TAG, "表情预解码完成");
}

// ==================== 信号强度图标 ====================

void eeui_port_render_signal(int strength)
{
    if (!s_lvgl_ready) return;
    if (strength == s_sig_ui.last_strength) return;  // 无变化跳过
    s_sig_ui.last_strength = strength;

    if (lvgl_lock(100)) {
        if (s_sig_ui.canvas == NULL) {
            s_sig_ui.canvas = lv_canvas_create(s_container);
            lv_obj_set_size(s_sig_ui.canvas, SIG_CANVAS_W, SIG_CANVAS_H);
            lv_obj_set_style_bg_opa(s_sig_ui.canvas, LV_OPA_TRANSP, 0);
            static uint8_t cbuf[SIG_CANVAS_W * SIG_CANVAS_H * 2];
            lv_canvas_set_buffer(s_sig_ui.canvas, cbuf, SIG_CANVAS_W, SIG_CANVAS_H, LV_COLOR_FORMAT_RGB565);
        }
        // 固定位置：在音量图标(130~144)和电池(x≈188+)之间，不跟随电池跳动
        lv_obj_set_pos(s_sig_ui.canvas, 155, 0);

        // 清空
        lv_canvas_fill_bg(s_sig_ui.canvas, lv_color_white(), LV_OPA_COVER);

        lv_color_t active = lv_color_make(80, 80, 80);
        lv_color_t grey = lv_color_make(215, 215, 215);

        // 弧线中心点（对齐 Arduino：center=(14, 17)）
        // 注意屏幕坐标系 y 轴向下为正，sin(270°)=-1 → y = center_y + radius*sin(rad) = center_y - radius 向上
        const int cx = 14, cy = 17;

        if (strength == 0) {
            // 无信号：灰色信号图标
            // 底部圆点（灰色）
            canvas_fill_rect(s_sig_ui.canvas, cx - 2, cy - 2, 4, 4, grey, LV_OPA_COVER);
            // 三圈弧线全部灰色（对齐 Arduino：240~300, 225~315, 220~320）
            struct { int radius; int start; int end; } arcs[] = {
                {6, 240, 300},
                {10, 225, 315},
                {14, 220, 320},
            };
            for (int i = 0; i < 3; i++) {
                for (int a = arcs[i].start; a <= arcs[i].end; a++) {
                    float rad = a * 3.14159f / 180.0f;
                    int x = cx + (int)(arcs[i].radius * cosf(rad));
                    // 屏幕 y 轴向下，sin(270°)=-1 → y 减小（向上） = 弧线朝上
                    int y = cy + (int)(arcs[i].radius * sinf(rad));
                    if (x >= 0 && x < SIG_CANVAS_W && y >= 0 && y < SIG_CANVAS_H) {
                        canvas_draw_px(s_sig_ui.canvas, x, y, grey, LV_OPA_COVER);
                    }
                }
            }
        } else {
            // 底部圆点
            canvas_fill_rect(s_sig_ui.canvas, cx - 2, cy - 2, 4, 4, active, LV_OPA_COVER);

            // 三圈弧线（对齐 Arduino）
            struct { int radius; int limit; int start; int end; } arcs[] = {
                {6, 1, 240, 300},   // 内圈（strength >= 1）
                {10, 2, 225, 315},  // 中圈（strength >= 2）
                {14, 3, 220, 320},  // 外圈（strength >= 3）
            };
            for (int i = 0; i < 3; i++) {
                lv_color_t color = strength > arcs[i].limit ? active : grey;
                for (int a = arcs[i].start; a <= arcs[i].end; a++) {
                    float rad = a * 3.14159f / 180.0f;
                    int x = cx + (int)(arcs[i].radius * cosf(rad));
                    // 屏幕 y 轴向下，sin(270°)=-1 → y 减小（向上）= 弧线朝上
                    int y = cy + (int)(arcs[i].radius * sinf(rad));
                    if (x >= 0 && x < SIG_CANVAS_W && y >= 0 && y < SIG_CANVAS_H) {
                        canvas_draw_px(s_sig_ui.canvas, x, y, color, LV_OPA_COVER);
                    }
                }
            }
        }
        lvgl_unlock();
    }
}

// ==================== 屏保（省电模式时钟）====================
// 待机省电时显示：纯黑背景 + 居中大号时间（冒号每秒闪烁）+ 日期星期小字 + 顶部细线装饰。
// 背光同步调暗至 30%（省电），退出屏保时恢复用户设置的亮度。
// 由 power_manager 在待机/活跃状态切换时调用。

static lv_obj_t *s_ss_root = NULL;
static lv_obj_t *s_ss_time_label = NULL;
static lv_obj_t *s_ss_date_label = NULL;
static lv_obj_t *s_ss_deco_line = NULL;
static lv_timer_t *s_ss_timer = NULL;
static int s_ss_brightness_backup = -1;

static void screensaver_tick_cb(lv_timer_t *timer)
{
    if (!s_ss_time_label || !s_ss_date_label) return;
    time_t now = time(NULL);
    struct tm tmv;
    localtime_r(&now, &tmv);
    char buf[16];
    // 大号时间 HH:MM（冒号常显，不闪烁）
    snprintf(buf, sizeof(buf), "%02d:%02d", tmv.tm_hour, tmv.tm_min);
    lv_label_set_text(s_ss_time_label, buf);
    // 日期 + 星期（次级信息，暗灰色）
    static const char *wday_cn[] = {"周日", "周一", "周二", "周三", "周四", "周五", "周六"};
    char date_buf[32];
    snprintf(date_buf, sizeof(date_buf), "%d月%d日 %s", tmv.tm_mon + 1, tmv.tm_mday, wday_cn[tmv.tm_wday]);
    lv_label_set_text(s_ss_date_label, date_buf);
}

// 读取用户设置的亮度（NVS bl_level，set_brightness 指令持久化；未设置过默认 100）
static int screensaver_load_brightness(void)
{
    int level = 100;
    nvs_handle_t h;
    if (nvs_open("esp-ai-kv", NVS_READONLY, &h) == ESP_OK) {
        int32_t v = -1;
        if (nvs_get_i32(h, "bl_level", &v) == ESP_OK && v >= 0 && v <= 100) {
            level = (int)v;
        }
        nvs_close(h);
    }
    return level;
}

void eeui_port_screensaver_set(bool active)
{
    if (!s_lvgl_mutex || s_display == NULL) return;  // 无屏/未初始化（C3 headless）
    if (active == (s_ss_root != NULL)) return;       // 状态未变，幂等

    if (!lvgl_lock(200)) return;

    if (active) {
        // ---- 进入屏保 ----
        s_ss_brightness_backup = screensaver_load_brightness();
        // 纯黑全屏容器（最顶层，遮住表情/状态）
        s_ss_root = lv_obj_create(lv_scr_act());
        lv_obj_remove_flag(s_ss_root, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_size(s_ss_root, s_screen_width, s_screen_height);
        lv_obj_set_style_bg_color(s_ss_root, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(s_ss_root, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(s_ss_root, 0, 0);
        lv_obj_set_style_pad_all(s_ss_root, 0, 0);
        lv_obj_set_style_radius(s_ss_root, 0, 0);
        lv_obj_move_foreground(s_ss_root);
        // 装饰：时间上方一条细横线（极简设计，避免画面突兀）
        s_ss_deco_line = lv_obj_create(s_ss_root);
        lv_obj_set_size(s_ss_deco_line, 96, 2);
        lv_obj_set_style_bg_color(s_ss_deco_line, lv_color_hex(0x4A4A4A), 0);
        lv_obj_set_style_bg_opa(s_ss_deco_line, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(s_ss_deco_line, 0, 0);
        lv_obj_set_style_radius(s_ss_deco_line, 1, 0);
        lv_obj_align(s_ss_deco_line, LV_ALIGN_CENTER, 0, -60);
        // 大号时间（屏幕中央，48px 数字字体）
        s_ss_time_label = lv_label_create(s_ss_root);
        lv_label_set_text(s_ss_time_label, "--:--");
        lv_obj_set_style_text_font(s_ss_time_label, &lv_font_montserrat_48, 0);
        lv_obj_set_style_text_color(s_ss_time_label, lv_color_hex(0xE8E8E8), 0);
        lv_obj_align(s_ss_time_label, LV_ALIGN_CENTER, 0, -10);
        // 日期 + 星期（时间下方，暗灰色次级信息）
        s_ss_date_label = lv_label_create(s_ss_root);
        lv_obj_set_style_text_font(s_ss_date_label, &font_puhui_16_4, 0);
        lv_obj_set_style_text_color(s_ss_date_label, lv_color_hex(0x6E6E6E), 0);
        lv_obj_align(s_ss_date_label, LV_ALIGN_CENTER, 0, 44);
        // 每秒刷新（时间 + 冒号闪烁）
        s_ss_timer = lv_timer_create(screensaver_tick_cb, 1000, NULL);
        screensaver_tick_cb(s_ss_timer);
        // 背光调暗省电（退出时恢复）
        eeui_port_set_brightness(30);
        ESP_LOGI(TAG, "屏保已启动（黑底时钟，背光 30%%）");
    } else {
        // ---- 退出屏保 ----
        if (s_ss_timer) { lv_timer_delete(s_ss_timer); s_ss_timer = NULL; }
        if (s_ss_root) { lv_obj_delete(s_ss_root); s_ss_root = NULL; }
        s_ss_root = NULL;
        s_ss_time_label = NULL;
        s_ss_date_label = NULL;
        s_ss_deco_line = NULL;
        // 恢复用户设置的亮度
        if (s_ss_brightness_backup > 0) {
            eeui_port_set_brightness(s_ss_brightness_backup);
            s_ss_brightness_backup = -1;
        }
        ESP_LOGI(TAG, "屏保已退出");
    }

    lvgl_unlock();
}

// ==================== 通用卡片渲染（show_card 指令）====================
// 插件下发 JSON 描述的卡片，原生 LVGL 渲染（非 Lua）：
//   - 支持 48px 大号数字字体（mont48）与中文字体（puhui）
//   - 支持天气图标符号（☀☁☂⛅⚡❄，新字体内置）
//   - 卡片对象由系统管理：表情/状态渲染时自动清除（与 Lua 卡片一致）
//
// JSON 协议 v1：
// {
//   "bg": "000000",                                        // 全屏背景色（默认黑，覆盖旧内容）
//   "card": {"x":20,"y":45,"w":200,"h":150,
//            "bg":"1E1E1E","radius":12,"border":"444444"}, // 卡片容器
//   "items": [
//     {"t":"label","text":"☀","x":20,"y":12,"color":"FFD700","font":"puhui"},
//     {"t":"label","text":"30℃","y":8,"color":"FFFFFF","font":"mont48","align":"center"},
//     {"t":"label","text":"北京市","x":52,"y":12,"color":"FFFFFF","font":"puhui"},
//     {"t":"sep","y":86,"color":"3A3A3A"},                  // 容器内水平分隔线
//   ]
// }
// font: "puhui"(16px中文+符号) / "mont48"(48px数字) / 省略=默认14px
// align: "center" 水平居中（x 忽略）

#define MAX_CARD_OBJS 32
static lv_obj_t *s_card_objects[MAX_CARD_OBJS] = {NULL};
static int s_card_object_count = 0;

static void card_track_obj(lv_obj_t *obj)
{
    if (obj && s_card_object_count < MAX_CARD_OBJS) {
        s_card_objects[s_card_object_count++] = obj;
    }
}

static void card_clear_objects(void)
{
    if (s_card_object_count == 0) return;
    for (int i = 0; i < s_card_object_count; i++) {
        if (s_card_objects[i] && lv_obj_is_valid(s_card_objects[i])) {
            lv_obj_delete(s_card_objects[i]);
        }
        s_card_objects[i] = NULL;
    }
    s_card_object_count = 0;
}

static lv_color_t card_color(const char *hex)
{
    if (!hex || strlen(hex) < 6) return lv_color_black();
    unsigned long v = strtoul(hex, NULL, 16);
    return lv_color_make((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF);
}

static const lv_font_t *card_font(const char *font)
{
    if (!font) return LV_FONT_DEFAULT;
    if (strcmp(font, "puhui") == 0) return &font_puhui_16_4;   /* 中文+天气符号 */
    if (strcmp(font, "mont48") == 0) return &lv_font_montserrat_48; /* 大号数字 */
    return LV_FONT_DEFAULT;
}

static lv_coord_t card_num(cJSON *obj, const char *key, lv_coord_t def)
{
    cJSON *v = cJSON_GetObjectItem(obj, key);
    if (v && cJSON_IsNumber(v)) return (lv_coord_t)v->valuedouble;
    return def;
}

void eeui_port_show_card(const char *json_str)
{
    if (!s_lvgl_ready || !json_str || !json_str[0]) {
        ESP_LOGW(TAG, "show_card: 未就绪或无数据 (ready=%d)", s_lvgl_ready);
        return;
    }
    ESP_LOGI(TAG, "show_card 收到: %.120s", json_str);

    cJSON *root = cJSON_Parse(json_str);
    if (!root) {
        ESP_LOGW(TAG, "show_card: JSON 解析失败");
        return;
    }
    if (!lvgl_lock(200)) {
        ESP_LOGW(TAG, "show_card: LVGL 锁获取失败（200ms 超时）");
        cJSON_Delete(root);
        return;
    }

    // 1. 全屏背景（默认黑，覆盖旧卡片/旧 Lua 绘制）
    lv_obj_t *bg = lv_obj_create(lv_scr_act());
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(bg, s_screen_width, s_screen_height);
    lv_obj_set_pos(bg, 0, 0);
    lv_obj_set_style_bg_color(bg, card_color(cJSON_GetStringValue(cJSON_GetObjectItem(root, "bg"))), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(bg, 0, 0);
    lv_obj_set_style_pad_all(bg, 0, 0);
    lv_obj_set_style_radius(bg, 0, 0);
    lv_obj_move_foreground(bg);
    card_track_obj(bg);

    // 2. 卡片容器
    cJSON *card = cJSON_GetObjectItem(root, "card");
    lv_obj_t *container = NULL;
    if (card) {
        lv_coord_t cw = card_num(card, "w", 200);
        lv_coord_t ch = card_num(card, "h", 150);
        container = lv_obj_create(lv_scr_act());
        lv_obj_remove_flag(container, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_size(container, cw, ch);
        lv_obj_set_pos(container, card_num(card, "x", 20), card_num(card, "y", 45));
        lv_obj_set_style_bg_color(container, card_color(cJSON_GetStringValue(cJSON_GetObjectItem(card, "bg"))), 0);
        lv_obj_set_style_bg_opa(container, LV_OPA_COVER, 0);
        lv_obj_set_style_radius(container, card_num(card, "radius", 12), 0);
        lv_obj_set_style_border_width(container, card_num(card, "border_w", 1), 0);
        lv_obj_set_style_border_color(container, card_color(cJSON_GetStringValue(cJSON_GetObjectItem(card, "border"))), 0);
        lv_obj_set_style_pad_all(container, 0, 0);
        card_track_obj(container);
    }

    // 3. items
    cJSON *items = cJSON_GetObjectItem(root, "items");
    if (items && cJSON_IsArray(items)) {
        int n = cJSON_GetArraySize(items);
        for (int i = 0; i < n; i++) {
            cJSON *it = cJSON_GetArrayItem(items, i);
            if (!it) continue;
            const char *t = cJSON_GetStringValue(cJSON_GetObjectItem(it, "t"));
            if (!t) continue;

            if (strcmp(t, "img") == 0) {
                /* 图片元素（天气图标等）：{"t":"img","id":"rain","x":..,"y":..} */
                const char *id = cJSON_GetStringValue(cJSON_GetObjectItem(it, "id"));
                const lv_image_dsc_t *dsc = NULL;
                for (int k = 0; k < weather_icon_count; k++) {
                    if (weather_icon_table[k].id && id &&
                        strcmp(weather_icon_table[k].id, id) == 0) {
                        dsc = weather_icon_table[k].img;
                        break;
                    }
                }
                if (dsc) {
                    lv_obj_t *img = lv_image_create(container ? container : lv_scr_act());
                    lv_image_set_src(img, dsc);
                    lv_obj_set_pos(img, card_num(it, "x", 0), card_num(it, "y", 0));
                    ESP_LOGI(TAG, "show_card img: id=%s @(%d,%d)",
                             id ? id : "?", card_num(it, "x", 0), card_num(it, "y", 0));
                    card_track_obj(img);
                } else {
                    ESP_LOGW(TAG, "show_card img: 未知图标 id=%s", id ? id : "(null)");
                }
                continue;
            }

            if (strcmp(t, "label") == 0) {
                const char *text = cJSON_GetStringValue(cJSON_GetObjectItem(it, "text"));
                const char *font_name = cJSON_GetStringValue(cJSON_GetObjectItem(it, "font"));
                const char *color_hex = cJSON_GetStringValue(cJSON_GetObjectItem(it, "color"));
                const char *align = cJSON_GetStringValue(cJSON_GetObjectItem(it, "align"));
                ESP_LOGI(TAG, "show_card label: text='%s' font=%s color=%s align=%s",
                         text ? text : "(null)", font_name ? font_name : "(默认)",
                         color_hex ? color_hex : "(黑)", align ? align : "left");
                lv_obj_t *lbl = lv_label_create(container ? container : lv_scr_act());
                // 先设置字体再设置文本：确保首次布局就用正确字体（LVGL 9 对
                // 先 text 后 font 的 label 尺寸/渲染可能有顺序依赖）
                lv_obj_set_style_text_font(lbl, card_font(font_name), 0);
                lv_obj_set_style_text_color(lbl, card_color(color_hex), 0);
                lv_label_set_text(lbl, text ? text : "");
                if (align && strcmp(align, "center") == 0) {
                    // 服务端 y 语义 = 距容器顶部的偏移 → 用 TOP_MID 对齐（CENTER 会把
                    // y 当成距卡片中心的偏移，导致元素跑到卡片下部/容器外）
                    lv_obj_align(lbl, LV_ALIGN_TOP_MID, 0, card_num(it, "y", 0));
                } else {
                    lv_obj_set_pos(lbl, card_num(it, "x", 0), card_num(it, "y", 0));
                }
                lv_obj_update_layout(lbl);
                lv_color_t c = card_color(color_hex);
                ESP_LOGI(TAG, "  label诊断: '%s' %dx%d @(%d,%d) 可见=%d 颜色=R%u,G%u,B%u",
                         text ? text : "", lv_obj_get_width(lbl), lv_obj_get_height(lbl),
                         lv_obj_get_x(lbl), lv_obj_get_y(lbl),
                         (int)lv_obj_is_visible(lbl), c.red, c.green, c.blue);
                card_track_obj(lbl);
            } else if (strcmp(t, "sep") == 0 && container) {
                /* 容器内水平分隔线（宽度 = 容器宽 - 2×margin） */
                lv_coord_t margin = card_num(it, "margin", 18);
                lv_obj_t *sep = lv_obj_create(container);
                lv_obj_set_size(sep, (lv_coord_t)lv_obj_get_width(container) - margin * 2, 1);
                lv_obj_set_pos(sep, margin, card_num(it, "y", 0));
                lv_obj_set_style_bg_color(sep, card_color(cJSON_GetStringValue(cJSON_GetObjectItem(it, "color"))), 0);
                lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
                lv_obj_set_style_border_width(sep, 0, 0);
                card_track_obj(sep);
            }
        }
    }

    cJSON_Delete(root);
    lvgl_unlock();
    ESP_LOGI(TAG, "show_card 渲染完成");
}

// 清除 show_card 卡片（会话边界调用：唤醒/会话结束/断线时让卡片让位恢复表情）
// 与 render_emotion 不同：卡片在会话内（TTS 播报等表情变化）保持显示
void eeui_port_clear_cards(void)
{
    if (!s_lvgl_mutex || s_display == NULL) return;  // 无屏/未初始化（C3 headless）
    if (!lvgl_lock(200)) return;
    card_clear_objects();
    lvgl_unlock();
}
