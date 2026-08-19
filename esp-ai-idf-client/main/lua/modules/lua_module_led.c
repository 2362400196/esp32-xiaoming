/**
 * lua_module_led.c — Lua LED 灯带模块 (WS2812/NeoPixel)
 *
 * 使用 ESP-IDF v6.0 新版 RMT TX API 驱动 WS2812
 *
 * Lua 用法:
 *   local led = require("led")
 *   led.init(48, 8)          -- 引脚48，8个灯
 *   led.set(0, 255, 0, 0)    -- 第1个灯红色 (R,G,B)
 *   led.set(1, 0, 255, 0)    -- 第2个灯绿色
 *   led.show()               -- 刷新
 *   led.set_hsv(0, 120, 255, 255)  -- HSV方式
 *   led.clear()              -- 清空
 *   led.brightness(50)       -- 亮度0-255
 *   led.deinit()             -- 释放
 */
#include "lua_module_led.h"
#include "lauxlib.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/rmt_tx.h"
#include "driver/rmt_encoder.h"
#include "esp_err.h"

#define LED_RMT_RESOLUTION 10000000  /* 10MHz = 100ns */
#define T0H 8    /* 0.8us */
#define T0L 22   /* 2.2us */
#define T1H 16   /* 1.6us */
#define T1L 14   /* 1.4us */
#define RESET 800 /* >280us 复位 */

static rmt_channel_handle_t s_led_chan = NULL;
static rmt_encoder_handle_t s_led_encoder = NULL;
static uint8_t *s_led_data = NULL;
static int s_led_count = 0;
static uint8_t s_led_brightness = 255;
static bool s_led_owned = false;  /* true=归我们管理，deinit 时删除通道 */

static int l_led_init(lua_State *L)
{
    int pin = luaL_checkinteger(L, 1);
    int count = luaL_checkinteger(L, 2);

    /* 清理旧状态 */
    if (s_led_chan) {
        if (s_led_owned) {
            rmt_del_channel(s_led_chan);
        }
        s_led_chan = NULL;
        s_led_encoder = NULL;
        s_led_owned = false;
    }

    s_led_count = count;
    s_led_data = (uint8_t *)realloc(s_led_data, count * 3);
    if (!s_led_data) return luaL_error(L, "led: no memory");
    memset(s_led_data, 0, count * 3);
    s_led_brightness = 255;

    /* 创建 RMT TX 通道 */
    rmt_tx_channel_config_t tx_chan_config = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .gpio_num = pin,
        .mem_block_symbols = 64,
        .resolution_hz = LED_RMT_RESOLUTION,
        .trans_queue_depth = 1,
        .flags.invert_out = false,
        .flags.with_dma = false,
    };
    esp_err_t err = rmt_new_tx_channel(&tx_chan_config, &s_led_chan);
    if (err == ESP_ERR_INVALID_STATE) {
        /* RMT 已被系统占用（如情绪灯），复用即可 */
        s_led_chan = NULL;
        s_led_owned = false;
    } else if (err != ESP_OK) {
        return luaL_error(L, "led: RMT TX channel create failed");
    } else {
        /* 创建 copy 编码器 */
        rmt_copy_encoder_config_t copy_enc_cfg = {};
        err = rmt_new_copy_encoder(&copy_enc_cfg, &s_led_encoder);
        if (err != ESP_OK) {
            rmt_del_channel(s_led_chan);
            s_led_chan = NULL;
            return luaL_error(L, "led: copy encoder create failed");
        }
        err = rmt_enable(s_led_chan);
        if (err != ESP_OK) {
            rmt_del_channel(s_led_chan);
            rmt_del_encoder(s_led_encoder);
            s_led_chan = NULL;
            s_led_encoder = NULL;
            return luaL_error(L, "led: RMT enable failed");
        }
        s_led_owned = true;
    }
    return 0;
}

static int l_led_deinit(lua_State *L)
{
    if (s_led_chan && s_led_owned) {
        rmt_disable(s_led_chan);
        rmt_del_channel(s_led_chan);
    }
    if (s_led_encoder && s_led_owned) {
        rmt_del_encoder(s_led_encoder);
    }
    s_led_chan = NULL;
    s_led_encoder = NULL;
    s_led_owned = false;
    s_led_count = 0;
    if (s_led_data) {
        free(s_led_data);
        s_led_data = NULL;
    }
    return 0;
}

static int l_led_set(lua_State *L)
{
    int idx = luaL_checkinteger(L, 1);
    int r = luaL_checkinteger(L, 2);
    int g = luaL_checkinteger(L, 3);
    int b = luaL_checkinteger(L, 4);

    if (!s_led_data || idx < 0 || idx >= s_led_count) return 0;
    /* WS2812: GRB 顺序 */
    s_led_data[idx * 3 + 0] = (uint8_t)g;
    s_led_data[idx * 3 + 1] = (uint8_t)r;
    s_led_data[idx * 3 + 2] = (uint8_t)b;
    return 0;
}

static int l_led_set_hsv(lua_State *L)
{
    int idx = luaL_checkinteger(L, 1);
    int hue = luaL_checkinteger(L, 2) % 360;
    int sat = luaL_checkinteger(L, 3);
    int val = luaL_checkinteger(L, 4);

    if (!s_led_data || idx < 0 || idx >= s_led_count) return 0;

    uint32_t r = 0, g = 0, b = 0, region, rem, p, q, t;
    if (sat == 0) { r = g = b = val; }
    else {
        region = hue / 60; rem = ((hue % 60) * 255) / 60;
        p = (val * (255 - sat)) / 255;
        q = (val * (255 - ((sat * rem) / 255))) / 255;
        t = (val * (255 - ((sat * (255 - rem)) / 255))) / 255;
        switch (region) {
            case 0: r=val; g=t;   b=p;   break;
            case 1: r=q;   g=val; b=p;   break;
            case 2: r=p;   g=val; b=t;   break;
            case 3: r=p;   g=q;   b=val; break;
            case 4: r=t;   g=p;   b=val; break;
            case 5: r=val; g=p;   b=q;   break;
        }
    }
    s_led_data[idx * 3 + 0] = (uint8_t)g;
    s_led_data[idx * 3 + 1] = (uint8_t)r;
    s_led_data[idx * 3 + 2] = (uint8_t)b;
    return 0;
}

/* 构建 RMT 符号数据（新版 rmt_symbol_word_t） */
static int ws2812_build_symbols(rmt_symbol_word_t *symbols, int n_bytes)
{
    int idx = 0;
    for (int i = 0; i < n_bytes; i++) {
        uint8_t byte = s_led_data[i];
        for (int bit = 7; bit >= 0; bit--) {
            if (byte & (1 << bit)) {
                symbols[idx].level0 = 1; symbols[idx].duration0 = T1H;
                symbols[idx].level1 = 0; symbols[idx].duration1 = T1L;
            } else {
                symbols[idx].level0 = 1; symbols[idx].duration0 = T0H;
                symbols[idx].level1 = 0; symbols[idx].duration1 = T0L;
            }
            idx++;
        }
    }
    /* 复位信号 */
    symbols[idx].level0 = 0; symbols[idx].duration0 = RESET;
    symbols[idx].level1 = 0; symbols[idx].duration1 = 0;
    return idx + 1;
}

static int l_led_show(lua_State *L)
{
    if (!s_led_chan || !s_led_owned || !s_led_data || s_led_count == 0) return 0;

    int total_bits = s_led_count * 24;
    int total_symbols = total_bits + 1;  /* +1 复位 */
    size_t sym_size = total_symbols * sizeof(rmt_symbol_word_t);
    rmt_symbol_word_t *symbols = (rmt_symbol_word_t *)malloc(sym_size);
    if (!symbols) return 0;

    /* 应用亮度 */
    uint8_t *bright_data = (uint8_t *)malloc(s_led_count * 3);
    if (!bright_data) { free(symbols); return 0; }
    for (int i = 0; i < s_led_count * 3; i++) {
        bright_data[i] = (uint8_t)(((uint32_t)s_led_data[i] * s_led_brightness) / 255);
    }

    uint8_t *old = s_led_data;
    s_led_data = bright_data;

    int sym_count = ws2812_build_symbols(symbols, s_led_count * 3);

    rmt_transmit_config_t tx_config = {
        .loop_count = 0,
        .flags.eot_level = 0,
    };
    rmt_transmit(s_led_chan, s_led_encoder, symbols, sym_count * sizeof(rmt_symbol_word_t), &tx_config);
    rmt_tx_wait_all_done(s_led_chan, pdMS_TO_TICKS(100));

    s_led_data = old;
    free(bright_data);
    free(symbols);
    return 0;
}

static int l_led_clear(lua_State *L)
{
    if (s_led_data) memset(s_led_data, 0, s_led_count * 3);
    return 0;
}

static int l_led_brightness(lua_State *L)
{
    int b = luaL_checkinteger(L, 1);
    if (b < 0) b = 0;
    if (b > 255) b = 255;
    s_led_brightness = (uint8_t)b;
    return 0;
}

int luaopen_led(lua_State *L)
{
    static const luaL_Reg funcs[] = {
        {"init",       l_led_init},
        {"deinit",     l_led_deinit},
        {"set",        l_led_set},
        {"set_hsv",    l_led_set_hsv},
        {"show",       l_led_show},
        {"clear",      l_led_clear},
        {"brightness", l_led_brightness},
        {NULL, NULL}
    };

    lua_newtable(L);
    luaL_setfuncs(L, funcs, 0);
    return 1;
}
