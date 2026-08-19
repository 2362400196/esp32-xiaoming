/*
 * SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include "display_hal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "display_service.h"
#include "display_dirty.h"
#include "esp_attr.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_ops.h"
#include "esp_log.h"
#include "esp_painter_font.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "display_hal";

#define DISPLAY_HAL_FRAMEBUFFER_COUNT_MAX 2
#define DISPLAY_HAL_PI                    3.14159265358979323846f
typedef struct {
    SemaphoreHandle_t lock;
    display_service_session_handle_t session;
    esp_lcd_panel_handle_t panel;
    esp_lcd_panel_io_handle_t io;
    display_hal_panel_if_t panel_if;
    display_hal_pixel_format_t pixel_format;
    size_t bytes_per_pixel;
    bool clip_enabled;
    int clip_x;
    int clip_y;
    int clip_width;
    int clip_height;
    int width;
    int height;
    size_t framebuffer_bytes;
    uint8_t *framebuffers[DISPLAY_HAL_FRAMEBUFFER_COUNT_MAX];
    uint8_t framebuffer_count;
    uint8_t draw_framebuffer_index;
    uint8_t visible_framebuffer_index;
    bool frame_active;
    bool framebuffer_initialized;
    display_dirty_rect_t dirty;
    uint8_t *submit_swap_buffer;
    size_t submit_swap_buffer_pixels;
} display_hal_state_t;

static display_hal_state_t s_state;

size_t display_hal_pixel_format_bytes(display_hal_pixel_format_t format)
{
    switch (format) {
    case DISPLAY_HAL_PIXEL_FORMAT_RGB565:
        return 2;
    case DISPLAY_HAL_PIXEL_FORMAT_RGB888:
        return 3;
    default:
        return 0;
    }
}

display_hal_pixel_format_t display_hal_get_pixel_format(void)
{
    /* No lock needed: the value is stable between create/destroy calls and readers
       tolerate the default when the HAL has not been created yet. */
    return s_state.pixel_format;
}

static void display_hal_clear_clip_locked(void);
static bool display_hal_clip_rect_to_screen_locked(int *x, int *y, int *width, int *height);

static esp_err_t display_hal_checked_framebuffer_bytes(int width, int height,
                                                       size_t bytes_per_pixel,
                                                       size_t *out_bytes)
{
    size_t pixels;

    if (out_bytes == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    *out_bytes = 0;
    if (width <= 0 || height <= 0 || bytes_per_pixel == 0 ||
            (size_t)width > SIZE_MAX / (size_t)height) {
        ESP_LOGE(TAG, "invalid display size: %dx%d (bpp=%u)",
                 width, height, (unsigned)bytes_per_pixel);
        return ESP_ERR_INVALID_SIZE;
    }
    pixels = (size_t)width * (size_t)height;
    if (pixels > SIZE_MAX / bytes_per_pixel) {
        ESP_LOGE(TAG, "display framebuffer size overflow: %dx%d bpp=%u",
                 width, height, (unsigned)bytes_per_pixel);
        return ESP_ERR_INVALID_SIZE;
    }
    *out_bytes = pixels * bytes_per_pixel;
    return ESP_OK;
}

/* bswap16 is meaningful only for RGB565: SPI LCD controllers expect the pixel
   in big-endian byte order, and this HAL keeps the framebuffer in native
   little-endian. RGB888 input is converted to native BGR when pixels enter
   the framebuffer or direct-submit buffer. */
static bool display_hal_pixels_need_swap(display_hal_pixel_format_t pixel_format, display_hal_panel_if_t panel_if)
{
    return pixel_format == DISPLAY_HAL_PIXEL_FORMAT_RGB565 && panel_if == DISPLAY_HAL_PANEL_IF_IO;
}

static void display_hal_bswap16_into(uint8_t *dst, const uint8_t *src, size_t pixel_count)
{
    const uint16_t *src16 = (const uint16_t *)src;
    uint16_t *dst16 = (uint16_t *)dst;
    for (size_t i = 0; i < pixel_count; ++i) {
        dst16[i] = __builtin_bswap16(src16[i]);
    }
}

static inline uint32_t display_hal_rgb888_read(const uint8_t *pixel)
{
    return ((uint32_t)pixel[0] << 16) | ((uint32_t)pixel[1] << 8) | (uint32_t)pixel[2];
}

static inline void display_hal_rgb888_write(uint8_t *pixel, uint8_t r, uint8_t g, uint8_t b)
{
    pixel[0] = b;
    pixel[1] = g;
    pixel[2] = r;
}

static inline void display_hal_rgb888_write_value(uint8_t *pixel, uint32_t rgb)
{
    pixel[0] = (uint8_t)((rgb >> 16) & 0xFF);
    pixel[1] = (uint8_t)((rgb >> 8) & 0xFF);
    pixel[2] = (uint8_t)(rgb & 0xFF);
}

static void display_hal_copy_rgb888_to_native(uint8_t *dst, const uint8_t *src, size_t pixel_count)
{
    for (size_t i = 0; i < pixel_count; ++i) {
        const uint8_t *s = src + i * 3;
        uint8_t *d = dst + i * 3;
        uint8_t r = s[0];
        uint8_t g = s[1];
        uint8_t b = s[2];
        d[0] = b;
        d[1] = g;
        d[2] = r;
    }
}

static inline uint8_t *display_hal_pixel_ptr(uint8_t *fb, int x, int y)
{
    return fb + ((size_t)y * (size_t)s_state.width + (size_t)x) * s_state.bytes_per_pixel;
}

static inline const uint8_t *display_hal_src_pixel_ptr(const uint8_t *buf, int src_width,
                                                       int x, int y, size_t bpp)
{
    return buf + ((size_t)y * (size_t)src_width + (size_t)x) * bpp;
}

static void display_hal_pixel_blend(uint8_t *pixel, display_color_t color)
{
    if (s_state.pixel_format == DISPLAY_HAL_PIXEL_FORMAT_RGB565) {
        uint16_t value = (uint16_t)(pixel[0] | ((uint16_t)pixel[1] << 8));
        value = display_color_blend_rgb565(value, color);
        pixel[0] = (uint8_t)(value & 0xFF);
        pixel[1] = (uint8_t)((value >> 8) & 0xFF);
    } else {
        uint32_t dst = display_hal_rgb888_read(pixel);
        uint32_t out = display_color_blend_rgb888(dst, color);
        display_hal_rgb888_write_value(pixel, out);
    }
}

static void display_hal_fill_row(uint8_t *row, display_color_t color, int count, bool blend)
{
    if (count <= 0) {
        return;
    }
    if (s_state.pixel_format == DISPLAY_HAL_PIXEL_FORMAT_RGB565) {
        uint16_t *dst = (uint16_t *)row;
        if (blend) {
            for (int i = 0; i < count; ++i) {
                dst[i] = display_color_blend_rgb565(dst[i], color);
            }
        } else {
            uint16_t value = display_color_to_rgb565(color);
            for (int i = 0; i < count; ++i) {
                dst[i] = value;
            }
        }
    } else {
        if (blend) {
            for (int i = 0; i < count; ++i) {
                display_hal_pixel_blend(row + (size_t)i * 3, color);
            }
        } else {
            for (int i = 0; i < count; ++i) {
                uint8_t *p = row + (size_t)i * 3;
                display_hal_rgb888_write(p, color.r, color.g, color.b);
            }
        }
    }
}

static esp_err_t display_hal_lock(void)
{
    if (!s_state.lock) {
        s_state.lock = xSemaphoreCreateMutex();
    }
    ESP_RETURN_ON_FALSE(s_state.lock != NULL, ESP_ERR_NO_MEM, TAG, "create mutex failed");
    ESP_RETURN_ON_FALSE(xSemaphoreTake(s_state.lock, pdMS_TO_TICKS(1000)) == pdTRUE,
                        ESP_ERR_TIMEOUT, TAG, "mutex timeout");
    return ESP_OK;
}

static void display_hal_unlock(void)
{
    if (s_state.lock) {
        xSemaphoreGive(s_state.lock);
    }
}

static esp_err_t display_hal_require_created_locked(void)
{
    bool handles_ready = s_state.panel != NULL &&
                         s_state.width > 0 && s_state.height > 0;

    if (s_state.panel_if == DISPLAY_HAL_PANEL_IF_IO) {
        handles_ready = handles_ready && (s_state.io != NULL);
    }

    ESP_RETURN_ON_FALSE(handles_ready,
                        ESP_ERR_INVALID_STATE, TAG, "display not created");
    return ESP_OK;
}

static esp_err_t display_hal_ensure_display_locked(void)
{
    return display_hal_require_created_locked();
}

esp_err_t display_hal_create(display_service_session_handle_t session,
                             esp_lcd_panel_handle_t panel_handle,
                             esp_lcd_panel_io_handle_t io_handle,
                             display_hal_panel_if_t panel_if,
                             display_hal_pixel_format_t pixel_format,
                             int lcd_width,
                             int lcd_height)
{
    esp_err_t ret = display_hal_lock();
    size_t bytes_per_pixel = display_hal_pixel_format_bytes(pixel_format);

    if (ret != ESP_OK) {
        return ret;
    }

    ESP_GOTO_ON_FALSE(panel_handle != NULL, ESP_ERR_INVALID_ARG, fail, TAG, "panel handle missing");
    ESP_GOTO_ON_FALSE(display_service_session_is_valid(session), ESP_ERR_INVALID_ARG, fail, TAG, "invalid display session");
    ESP_GOTO_ON_FALSE(panel_if >= DISPLAY_HAL_PANEL_IF_IO &&
                      panel_if <= DISPLAY_HAL_PANEL_IF_MIPI_DSI,
                      ESP_ERR_INVALID_ARG, fail, TAG, "invalid panel interface");
    ESP_GOTO_ON_FALSE(bytes_per_pixel != 0, ESP_ERR_INVALID_ARG, fail, TAG,
                      "unsupported pixel format: %d", (int)pixel_format);
    if (panel_if == DISPLAY_HAL_PANEL_IF_IO) {
        ESP_GOTO_ON_FALSE(io_handle != NULL, ESP_ERR_INVALID_ARG, fail, TAG, "io handle missing");
    }
    ESP_GOTO_ON_FALSE(lcd_width > 0 && lcd_height > 0, ESP_ERR_INVALID_ARG,
                      fail, TAG, "invalid lcd size");

    /* pixel_format is part of the identity for the no-op reinit check: switching
       formats must reallocate framebuffers and the swap buffer at the new bpp. */
    bool swap_needed = display_hal_pixels_need_swap(pixel_format, panel_if);
    if (s_state.panel == panel_handle &&
            s_state.io == io_handle &&
            s_state.panel_if == panel_if &&
            s_state.pixel_format == pixel_format &&
            s_state.session == session &&
            s_state.width == lcd_width &&
            s_state.height == lcd_height &&
            (!swap_needed || s_state.submit_swap_buffer != NULL)) {
        ESP_LOGD(TAG, "display_hal_create: already initialized with matching params, no-op");
        ret = ESP_OK;
        goto fail;
    }

    if (s_state.submit_swap_buffer) {
        ESP_LOGW(TAG, "display_hal_create: freeing leftover swap buffer (%u px)",
                 (unsigned)s_state.submit_swap_buffer_pixels);
        heap_caps_free(s_state.submit_swap_buffer);
        s_state.submit_swap_buffer = NULL;
        s_state.submit_swap_buffer_pixels = 0;
    }
    s_state.panel = panel_handle;
    s_state.session = session;
    s_state.io = io_handle;
    s_state.panel_if = panel_if;
    s_state.pixel_format = pixel_format;
    s_state.bytes_per_pixel = bytes_per_pixel;
    s_state.width = lcd_width;
    s_state.height = lcd_height;
    ESP_GOTO_ON_ERROR(display_hal_checked_framebuffer_bytes(lcd_width, lcd_height,
                                                            bytes_per_pixel,
                                                            &s_state.framebuffer_bytes),
                      fail, TAG, "invalid framebuffer size");
    s_state.framebuffer_count = 0;
    s_state.draw_framebuffer_index = 0;
    s_state.visible_framebuffer_index = 0;
    s_state.frame_active = false;
    s_state.framebuffer_initialized = false;
    display_dirty_clear(&s_state.dirty);
    if (display_hal_pixels_need_swap(s_state.pixel_format, s_state.panel_if)) {
        size_t swap_bytes = s_state.framebuffer_bytes;
        s_state.submit_swap_buffer = heap_caps_aligned_alloc(16, swap_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        ESP_GOTO_ON_FALSE(s_state.submit_swap_buffer != NULL, ESP_ERR_NO_MEM, fail, TAG, "alloc submit swap buffer failed");
        s_state.submit_swap_buffer_pixels = (size_t)lcd_width * (size_t)lcd_height;
    }
    display_hal_clear_clip_locked();

fail:
    if (ret != ESP_OK) {
        heap_caps_free(s_state.submit_swap_buffer);
        s_state.submit_swap_buffer = NULL;
        s_state.submit_swap_buffer_pixels = 0;
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_destroy(void)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }

    for (size_t i = 0; i < DISPLAY_HAL_FRAMEBUFFER_COUNT_MAX; ++i) {
        heap_caps_free(s_state.framebuffers[i]);
        s_state.framebuffers[i] = NULL;
    }

    s_state.panel = NULL;
    s_state.session = NULL;
    s_state.io = NULL;
    s_state.panel_if = DISPLAY_HAL_PANEL_IF_IO;
    s_state.pixel_format = DISPLAY_HAL_PIXEL_FORMAT_RGB565;
    s_state.bytes_per_pixel = 0;
    s_state.width = 0;
    s_state.height = 0;
    s_state.framebuffer_bytes = 0;
    s_state.framebuffer_count = 0;
    s_state.draw_framebuffer_index = 0;
    s_state.visible_framebuffer_index = 0;
    s_state.frame_active = false;
    s_state.framebuffer_initialized = false;
    display_dirty_clear(&s_state.dirty);
    s_state.clip_enabled = false;
    s_state.clip_x = 0;
    s_state.clip_y = 0;
    s_state.clip_width = 0;
    s_state.clip_height = 0;
    heap_caps_free(s_state.submit_swap_buffer);
    s_state.submit_swap_buffer = NULL;
    s_state.submit_swap_buffer_pixels = 0;

    /* Keep the HAL mutex alive across destroy/create cycles so concurrent callers cannot block on or acquire a deleted semaphore. */
    display_hal_unlock();
    return ESP_OK;
}

static void display_hal_clear_clip_locked(void)
{
    s_state.clip_enabled = false;
    s_state.clip_x = 0;
    s_state.clip_y = 0;
    s_state.clip_width = s_state.width;
    s_state.clip_height = s_state.height;
}

static uint8_t *display_hal_get_draw_framebuffer_locked(void)
{
    if (s_state.framebuffer_count == 0) {
        return NULL;
    }
    return s_state.framebuffers[s_state.draw_framebuffer_index];
}

static uint8_t *display_hal_get_visible_framebuffer_locked(void)
{
    if (s_state.framebuffer_count == 0) {
        return NULL;
    }
    return s_state.framebuffers[s_state.visible_framebuffer_index];
}

static esp_err_t display_hal_alloc_framebuffer_locked(size_t index)
{
    if (index >= DISPLAY_HAL_FRAMEBUFFER_COUNT_MAX) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_state.framebuffers[index]) {
        return ESP_OK;
    }

    s_state.framebuffers[index] = heap_caps_aligned_alloc(
        16, s_state.framebuffer_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    ESP_RETURN_ON_FALSE(s_state.framebuffers[index] != NULL, ESP_ERR_NO_MEM, TAG,
                        "framebuffer alloc failed");
    memset(s_state.framebuffers[index], 0, s_state.framebuffer_bytes);
    return ESP_OK;
}

static esp_err_t display_hal_ensure_framebuffer_locked(void)
{
    if (s_state.framebuffer_count > 0) {
        return ESP_OK;
    }

    ESP_RETURN_ON_ERROR(display_hal_alloc_framebuffer_locked(0), TAG, "alloc framebuffer 0 failed");
    s_state.framebuffer_count = 1;
    s_state.draw_framebuffer_index = 0;
    s_state.visible_framebuffer_index = 0;

    if (display_hal_alloc_framebuffer_locked(1) == ESP_OK) {
        s_state.framebuffer_count = 2;
    }

    s_state.framebuffer_initialized = true;
    return ESP_OK;
}

static void display_hal_fill_framebuffer_locked(uint8_t *framebuffer, display_color_t color)
{
    if (!framebuffer) {
        return;
    }
    if (display_color_is_transparent(color)) {
        return;
    }

    /* fill_row handles both formats and opaque/alpha paths; treating the whole
       framebuffer as a single wide row keeps it a single dispatch. */
    int pixels = s_state.width * s_state.height;
    display_hal_fill_row(framebuffer, color, pixels, !display_color_is_opaque(color));
}

static bool display_hal_get_clip_bounds_locked(int *left, int *top, int *right, int *bottom)
{
    int clip_left = 0;
    int clip_top = 0;
    int clip_right = s_state.width;
    int clip_bottom = s_state.height;

    if (s_state.clip_enabled) {
        clip_left = s_state.clip_x;
        clip_top = s_state.clip_y;
        clip_right = s_state.clip_x + s_state.clip_width;
        clip_bottom = s_state.clip_y + s_state.clip_height;

        if (clip_left < 0) {
            clip_left = 0;
        }
        if (clip_top < 0) {
            clip_top = 0;
        }
        if (clip_right > s_state.width) {
            clip_right = s_state.width;
        }
        if (clip_bottom > s_state.height) {
            clip_bottom = s_state.height;
        }
    }

    if (left) {
        *left = clip_left;
    }
    if (top) {
        *top = clip_top;
    }
    if (right) {
        *right = clip_right;
    }
    if (bottom) {
        *bottom = clip_bottom;
    }
    return clip_right > clip_left && clip_bottom > clip_top;
}

static bool display_hal_clip_rect_locked(int *x, int *y, int *width, int *height,
                                         int *src_x, int *src_y)
{
    int clip_left = 0;
    int clip_top = 0;
    int clip_right = 0;
    int clip_bottom = 0;
    int dst_x = 0;
    int dst_y = 0;
    int dst_w = 0;
    int dst_h = 0;
    int dst_right = 0;
    int dst_bottom = 0;

    if (!x || !y || !width || !height || *width <= 0 || *height <= 0) {
        return false;
    }
    if (!display_hal_get_clip_bounds_locked(&clip_left, &clip_top, &clip_right, &clip_bottom)) {
        return false;
    }

    dst_x = *x;
    dst_y = *y;
    dst_w = *width;
    dst_h = *height;
    dst_right = dst_x + dst_w;
    dst_bottom = dst_y + dst_h;

    if (dst_x < clip_left) {
        int delta = clip_left - dst_x;
        if (src_x) {
            *src_x += delta;
        }
        dst_x = clip_left;
    }
    if (dst_y < clip_top) {
        int delta = clip_top - dst_y;
        if (src_y) {
            *src_y += delta;
        }
        dst_y = clip_top;
    }
    if (dst_right > clip_right) {
        dst_right = clip_right;
    }
    if (dst_bottom > clip_bottom) {
        dst_bottom = clip_bottom;
    }

    dst_w = dst_right - dst_x;
    dst_h = dst_bottom - dst_y;
    if (dst_w <= 0 || dst_h <= 0) {
        return false;
    }

    *x = dst_x;
    *y = dst_y;
    *width = dst_w;
    *height = dst_h;
    return true;
}

static bool display_hal_clip_rect_to_screen_locked(int *x, int *y, int *width, int *height)
{
    int dst_x = 0;
    int dst_y = 0;
    int dst_right = 0;
    int dst_bottom = 0;

    if (!x || !y || !width || !height || *width <= 0 || *height <= 0) {
        return false;
    }

    dst_x = *x;
    dst_y = *y;
    dst_right = dst_x + *width;
    dst_bottom = dst_y + *height;

    if (dst_x < 0) {
        dst_x = 0;
    }
    if (dst_y < 0) {
        dst_y = 0;
    }
    if (dst_right > s_state.width) {
        dst_right = s_state.width;
    }
    if (dst_bottom > s_state.height) {
        dst_bottom = s_state.height;
    }

    *x = dst_x;
    *y = dst_y;
    *width = dst_right - dst_x;
    *height = dst_bottom - dst_y;
    return *width > 0 && *height > 0;
}

static float display_hal_normalize_degrees(float degrees)
{
    while (degrees < 0.0f) {
        degrees += 360.0f;
    }
    while (degrees >= 360.0f) {
        degrees -= 360.0f;
    }
    return degrees;
}

static bool display_hal_arc_is_full_sweep(float start_deg, float end_deg)
{
    float sweep = end_deg - start_deg;

    if (fabsf(sweep) >= 359.999f) {
        return true;
    }

    return fabsf(display_hal_normalize_degrees(start_deg) -
                 display_hal_normalize_degrees(end_deg)) < 0.001f;
}

static float display_hal_arc_sweep_degrees(float start_deg, float end_deg)
{
    float start = display_hal_normalize_degrees(start_deg);
    float end = display_hal_normalize_degrees(end_deg);
    float sweep = end - start;

    if (sweep < 0.0f) {
        sweep += 360.0f;
    }
    return sweep;
}

static float display_hal_point_angle_degrees(int dx, int dy)
{
    float degrees = atan2f((float)dy, (float)dx) * (180.0f / DISPLAY_HAL_PI);

    if (degrees < 0.0f) {
        degrees += 360.0f;
    }
    return degrees;
}

static bool display_hal_angle_in_arc(float angle_deg, float start_deg, float end_deg)
{
    float start = display_hal_normalize_degrees(start_deg);
    float end = display_hal_normalize_degrees(end_deg);
    float angle = display_hal_normalize_degrees(angle_deg);

    if (display_hal_arc_is_full_sweep(start_deg, end_deg)) {
        return true;
    }
    if (start <= end) {
        return angle >= start && angle <= end;
    }
    return angle >= start || angle <= end;
}

/*
 * All submissions go through the active display_service raw session with wait=true.
 * The service (via the LVGL adapter) blocks until the panel has consumed the
 * caller's buffer, so the caller can rotate framebuffers or reuse memory as
 * soon as this function returns. There is no async flush state to track.
 */
static esp_err_t display_hal_submit_bitmap_locked(int x_start, int y_start,
                                                  int x_end, int y_end,
                                                  const void *pixels,
                                                  int pending_framebuffer_index)
{
    const void *submit_pixels = pixels;
    esp_err_t ret;

    if (display_hal_pixels_need_swap(s_state.pixel_format, s_state.panel_if)) {
        size_t pixel_count = (size_t)(x_end - x_start) * (size_t)(y_end - y_start);
        ESP_RETURN_ON_FALSE(s_state.submit_swap_buffer != NULL, ESP_ERR_INVALID_STATE, TAG, "submit swap buffer missing");
        display_hal_bswap16_into(s_state.submit_swap_buffer, (const uint8_t *)pixels, pixel_count);
        submit_pixels = s_state.submit_swap_buffer;
    }

    ESP_RETURN_ON_FALSE(s_state.session != NULL, ESP_ERR_INVALID_STATE, TAG, "display session missing");
    ret = display_service_session_raw_blit(s_state.session, &(display_service_raw_blit_t) {
        .x_start = x_start,
        .y_start = y_start,
        .x_end = x_end,
        .y_end = y_end,
        .frame_buffer = submit_pixels,
        .wait = true,
    });
    if (ret != ESP_OK) {
        return ret;
    }

    if (pending_framebuffer_index >= 0) {
        s_state.visible_framebuffer_index = (uint8_t)pending_framebuffer_index;
    }
    return ESP_OK;
}

static const esp_painter_basic_font_t *display_hal_get_font(uint8_t font_size)
{
    switch (font_size) {
#if CONFIG_ESP_PAINTER_BASIC_FONT_12
    case 12:
        return &esp_painter_basic_font_12;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_16
    case 16:
        return &esp_painter_basic_font_16;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_20
    case 20:
        return &esp_painter_basic_font_20;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_24
    case 0:
    case 24:
        return &esp_painter_basic_font_24;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_28
    case 28:
        return &esp_painter_basic_font_28;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_32
    case 32:
        return &esp_painter_basic_font_32;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_36
    case 36:
        return &esp_painter_basic_font_36;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_40
    case 40:
        return &esp_painter_basic_font_40;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_44
    case 44:
        return &esp_painter_basic_font_44;
#endif
#if CONFIG_ESP_PAINTER_BASIC_FONT_48
    case 48:
        return &esp_painter_basic_font_48;
#endif
    default:
        break;
    }

#if CONFIG_ESP_PAINTER_BASIC_FONT_24
    return &esp_painter_basic_font_24;
#elif CONFIG_ESP_PAINTER_BASIC_FONT_20
    return &esp_painter_basic_font_20;
#elif CONFIG_ESP_PAINTER_BASIC_FONT_16
    return &esp_painter_basic_font_16;
#elif CONFIG_ESP_PAINTER_BASIC_FONT_12
    return &esp_painter_basic_font_12;
#else
    return NULL;
#endif
}

static void display_hal_measure_text_raw(const char *text, const esp_painter_basic_font_t *font,
                                         uint16_t *out_width, uint16_t *out_height)
{
    uint16_t max_cols = 0;
    uint16_t cols = 0;
    uint16_t lines = 1;

    if (!text || !font) {
        if (out_width) {
            *out_width = 0;
        }
        if (out_height) {
            *out_height = 0;
        }
        return;
    }

    for (const char *p = text; *p; ++p) {
        if (*p == '\n') {
            if (cols > max_cols) {
                max_cols = cols;
            }
            cols = 0;
            lines++;
        } else if (*p != '\r') {
            cols++;
        }
    }
    if (cols > max_cols) {
        max_cols = cols;
    }

    if (out_width) {
        *out_width = (uint16_t)(max_cols * font->width);
    }
    if (out_height) {
        *out_height = (uint16_t)(lines * font->height);
    }
}

static esp_err_t display_hal_fill_rect_locked(int x, int y, int width, int height, display_color_t color)
{
    uint8_t *framebuffer = display_hal_get_draw_framebuffer_locked();
    bool blend = !display_color_is_opaque(color);

    if (display_color_is_transparent(color)) {
        return ESP_OK;
    }

    if (!display_hal_clip_rect_locked(&x, &y, &width, &height, NULL, NULL)) {
        return ESP_OK;
    }

    if (s_state.frame_active && framebuffer) {
        for (int row = 0; row < height; ++row) {
            uint8_t *dst = display_hal_pixel_ptr(framebuffer, x, y + row);
            display_hal_fill_row(dst, color, width, blend);
        }
        display_dirty_mark(&s_state.dirty, x, y, width, height);
        return ESP_OK;
    }

    if (blend) {
        ESP_LOGE(TAG, "alpha drawing requires an active framebuffer");
        return ESP_ERR_INVALID_STATE;
    }

    /* No active framebuffer: build a single opaque scanline once and stream it
       into the panel row by row via draw_bitmap. */
    size_t line_bytes = (size_t)width * s_state.bytes_per_pixel;
    uint8_t *line = malloc(line_bytes);
    ESP_RETURN_ON_FALSE(line != NULL, ESP_ERR_NO_MEM, TAG, "line alloc failed");
    display_hal_fill_row(line, color, width, false);
    for (int row = 0; row < height; ++row) {
        esp_err_t ret = display_hal_submit_bitmap_locked(x, y + row, x + width, y + row + 1, line, -1);
        if (ret != ESP_OK) {
            free(line);
            return ret;
        }
    }
    free(line);
    return ESP_OK;
}

static esp_err_t display_hal_draw_pixel_locked(int x, int y, display_color_t color)
{
    return display_hal_fill_rect_locked(x, y, 1, 1, color);
}

static esp_err_t display_hal_draw_hline_locked(int x, int y, int width, display_color_t color)
{
    return display_hal_fill_rect_locked(x, y, width, 1, color);
}

static esp_err_t display_hal_draw_vline_locked(int x, int y, int height, display_color_t color)
{
    return display_hal_fill_rect_locked(x, y, 1, height, color);
}

static esp_err_t display_hal_draw_line_locked(int x0, int y0, int x1, int y1, display_color_t color)
{
    if (y0 == y1) {
        int x = x0 < x1 ? x0 : x1;
        return display_hal_draw_hline_locked(x, y0, abs(x1 - x0) + 1, color);
    }
    if (x0 == x1) {
        int y = y0 < y1 ? y0 : y1;
        return display_hal_draw_vline_locked(x0, y, abs(y1 - y0) + 1, color);
    }

    int dx = abs(x1 - x0);
    int sx = x0 < x1 ? 1 : -1;
    int dy = -abs(y1 - y0);
    int sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;

    while (true) {
        esp_err_t ret = display_hal_draw_pixel_locked(x0, y0, color);
        if (ret != ESP_OK) {
            return ret;
        }
        if (x0 == x1 && y0 == y1) {
            break;
        }
        int e2 = err * 2;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
    return ESP_OK;
}

static esp_err_t display_hal_draw_rect_locked(int x, int y, int width, int height, display_color_t color)
{
    if (width <= 0 || height <= 0) {
        return ESP_OK;
    }
    if (width == 1) {
        return display_hal_draw_vline_locked(x, y, height, color);
    }
    if (height == 1) {
        return display_hal_draw_hline_locked(x, y, width, color);
    }

    ESP_RETURN_ON_ERROR(display_hal_draw_hline_locked(x, y, width, color), TAG, "draw top failed");
    ESP_RETURN_ON_ERROR(display_hal_draw_hline_locked(x, y + height - 1, width, color), TAG,
                        "draw bottom failed");
    ESP_RETURN_ON_ERROR(display_hal_draw_vline_locked(x, y + 1, height - 2, color), TAG,
                        "draw left failed");
    return display_hal_draw_vline_locked(x + width - 1, y + 1, height - 2, color);
}

static esp_err_t display_hal_check_src_format_locked(display_hal_pixel_format_t src_format)
{
    if (src_format != s_state.pixel_format) {
        ESP_LOGE(TAG, "bitmap src format %d does not match panel format %d",
                 (int)src_format, (int)s_state.pixel_format);
        return ESP_ERR_INVALID_ARG;
    }
    return ESP_OK;
}

static esp_err_t display_hal_draw_bitmap_crop_locked(int x, int y,
                                                     int src_x, int src_y,
                                                     int w, int h,
                                                     int src_width, int src_height,
                                                     const void *pixels,
                                                     display_hal_pixel_format_t src_format,
                                                     bool src_native)
{
    size_t src_bpp = 0;
    const uint8_t *src_bytes = (const uint8_t *)pixels;

    if (!pixels || src_width <= 0 || src_height <= 0 || w <= 0 || h <= 0) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(display_hal_check_src_format_locked(src_format), TAG, "src format check failed");
    src_bpp = s_state.bytes_per_pixel;

    if (src_x < 0) {
        x -= src_x;
        w += src_x;
        src_x = 0;
    }
    if (src_y < 0) {
        y -= src_y;
        h += src_y;
        src_y = 0;
    }
    if (src_x + w > src_width) {
        w = src_width - src_x;
    }
    if (src_y + h > src_height) {
        h = src_height - src_y;
    }
    if (w <= 0 || h <= 0) {
        return ESP_OK;
    }

    if (!display_hal_clip_rect_locked(&x, &y, &w, &h, &src_x, &src_y)) {
        return ESP_OK;
    }

    uint8_t *framebuffer = display_hal_get_draw_framebuffer_locked();
    if (s_state.frame_active && framebuffer) {
        for (int row = 0; row < h; ++row) {
            const uint8_t *src = display_hal_src_pixel_ptr(src_bytes, src_width,
                                                           src_x, src_y + row, src_bpp);
            uint8_t *dst = display_hal_pixel_ptr(framebuffer, x, y + row);
            if (src_format == DISPLAY_HAL_PIXEL_FORMAT_RGB888 && !src_native) {
                display_hal_copy_rgb888_to_native(dst, src, (size_t)w);
            } else {
                memcpy(dst, src, (size_t)w * src_bpp);
            }
        }
        display_dirty_mark(&s_state.dirty, x, y, w, h);
        return ESP_OK;
    }

    if (src_format == DISPLAY_HAL_PIXEL_FORMAT_RGB888 && !src_native) {
        size_t row_bytes = (size_t)w * src_bpp;
        uint8_t *row_buf = malloc(row_bytes);
        ESP_RETURN_ON_FALSE(row_buf != NULL, ESP_ERR_NO_MEM, TAG, "native row order buffer alloc failed");
        for (int row = 0; row < h; ++row) {
            const uint8_t *row_ptr = display_hal_src_pixel_ptr(src_bytes, src_width, src_x, src_y + row, src_bpp);
            display_hal_copy_rgb888_to_native(row_buf, row_ptr, (size_t)w);
            esp_err_t ret = display_hal_submit_bitmap_locked(x, y + row, x + w, y + row + 1, row_buf, -1);
            if (ret != ESP_OK) {
                free(row_buf);
                return ret;
            }
        }
        free(row_buf);
        return ESP_OK;
    }

    if (src_x == 0 && w == src_width) {
        const uint8_t *start = display_hal_src_pixel_ptr(src_bytes, src_width, 0, src_y, src_bpp);
        return display_hal_submit_bitmap_locked(x, y, x + w, y + h, start, -1);
    }

    for (int row = 0; row < h; ++row) {
        const uint8_t *row_ptr = display_hal_src_pixel_ptr(src_bytes, src_width,
                                                           src_x, src_y + row, src_bpp);
        ESP_RETURN_ON_ERROR(
            display_hal_submit_bitmap_locked(x, y + row, x + w, y + row + 1, row_ptr, -1),
            TAG, "submit bitmap row failed");
    }
    return ESP_OK;
}

static esp_err_t display_hal_draw_bitmap_locked(int x, int y, int w, int h,
                                                const void *pixels,
                                                display_hal_pixel_format_t src_format,
                                                bool src_native)
{
    return display_hal_draw_bitmap_crop_locked(x, y, 0, 0, w, h, w, h, pixels, src_format, src_native);
}

static esp_err_t display_hal_present_full_locked(void)
{
    uint8_t *framebuffer = display_hal_get_draw_framebuffer_locked();

    if (!framebuffer || !s_state.frame_active) {
        return ESP_ERR_INVALID_STATE;
    }

    ESP_RETURN_ON_ERROR(
        display_hal_submit_bitmap_locked(
            0, 0, s_state.width, s_state.height,
            framebuffer, (int)s_state.draw_framebuffer_index),
        TAG, "present failed");

    if (s_state.framebuffer_count > 1) {
        uint8_t *prev_draw_fb = framebuffer;
        s_state.draw_framebuffer_index = (uint8_t)((s_state.draw_framebuffer_index + 1) %
                                                   s_state.framebuffer_count);
        uint8_t *new_draw_fb = display_hal_get_draw_framebuffer_locked();
        if (new_draw_fb && new_draw_fb != prev_draw_fb) {
            memcpy(new_draw_fb, prev_draw_fb, s_state.framebuffer_bytes);
        }
    }
    display_dirty_clear(&s_state.dirty);
    return ESP_OK;
}

static esp_err_t display_hal_present_rect_locked(int x, int y, int width, int height)
{
    uint8_t *draw_fb = display_hal_get_draw_framebuffer_locked();
    uint8_t *visible_fb = display_hal_get_visible_framebuffer_locked();

    if (!draw_fb || !s_state.frame_active) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!display_hal_clip_rect_to_screen_locked(&x, &y, &width, &height)) {
        return ESP_OK;
    }

    size_t row_bytes = (size_t)width * s_state.bytes_per_pixel;
    if (width == s_state.width) {
        const uint8_t *start = display_hal_pixel_ptr(draw_fb, 0, y);
        ESP_RETURN_ON_ERROR(
            display_hal_submit_bitmap_locked(x, y, x + width, y + height, start, -1),
            TAG, "present rect failed");
    } else {
        for (int row = 0; row < height; ++row) {
            const uint8_t *row_ptr = display_hal_pixel_ptr(draw_fb, x, y + row);
            ESP_RETURN_ON_ERROR(
                display_hal_submit_bitmap_locked(
                    x, y + row, x + width, y + row + 1, row_ptr, -1),
                TAG, "present rect row failed");
        }
    }

    if (visible_fb && visible_fb != draw_fb) {
        for (int row = 0; row < height; ++row) {
            const uint8_t *src = display_hal_pixel_ptr(draw_fb, x, y + row);
            uint8_t *dst = display_hal_pixel_ptr(visible_fb, x, y + row);
            memcpy(dst, src, row_bytes);
        }
    }
    return ESP_OK;
}

static esp_err_t display_hal_present_locked(void)
{
    if (!display_hal_get_draw_framebuffer_locked() || !s_state.frame_active) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!display_dirty_is_valid(&s_state.dirty)) {
        return ESP_OK;
    }

    display_dirty_rect_t dirty = s_state.dirty;
    ESP_RETURN_ON_ERROR(display_hal_present_rect_locked(dirty.x, dirty.y, dirty.width, dirty.height),
                        TAG, "present dirty rect failed");
    display_dirty_clear(&s_state.dirty);
    return ESP_OK;
}

static void display_hal_sort_vertices_by_y(int *x1, int *y1, int *x2, int *y2, int *x3, int *y3)
{
    if (*y1 > *y2) {
        int tx = *x1;
        int ty = *y1;
        *x1 = *x2;
        *y1 = *y2;
        *x2 = tx;
        *y2 = ty;
    }
    if (*y2 > *y3) {
        int tx = *x2;
        int ty = *y2;
        *x2 = *x3;
        *y2 = *y3;
        *x3 = tx;
        *y3 = ty;
    }
    if (*y1 > *y2) {
        int tx = *x1;
        int ty = *y1;
        *x1 = *x2;
        *y1 = *y2;
        *x2 = tx;
        *y2 = ty;
    }
}

static esp_err_t display_hal_scale_pixels(const void *src, int src_w, int src_h,
                                          int dst_w, int dst_h, size_t bpp, void **dst_out)
{
    if (!src || src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0 ||
            !dst_out || bpp == 0) {
        return ESP_ERR_INVALID_ARG;
    }
    size_t dst_bytes = (size_t)dst_w * (size_t)dst_h * bpp;
    uint8_t *dst = malloc(dst_bytes);
    ESP_RETURN_ON_FALSE(dst != NULL, ESP_ERR_NO_MEM, TAG, "scale buffer alloc failed");

    const uint8_t *src_bytes = (const uint8_t *)src;
    if (bpp == 2) {
        for (int y = 0; y < dst_h; ++y) {
            int src_y = (y * src_h) / dst_h;
            const uint16_t *src_row = (const uint16_t *)(src_bytes + (size_t)src_y * src_w * 2);
            uint16_t *dst_row = (uint16_t *)(dst + (size_t)y * dst_w * 2);
            for (int x = 0; x < dst_w; ++x) {
                int src_x = (x * src_w) / dst_w;
                dst_row[x] = src_row[src_x];
            }
        }
    } else {
        for (int y = 0; y < dst_h; ++y) {
            int src_y = (y * src_h) / dst_h;
            const uint8_t *src_row = src_bytes + (size_t)src_y * src_w * bpp;
            uint8_t *dst_row = dst + (size_t)y * dst_w * bpp;
            for (int x = 0; x < dst_w; ++x) {
                int src_x = (x * src_w) / dst_w;
                memcpy(dst_row + (size_t)x * bpp, src_row + (size_t)src_x * bpp, bpp);
            }
        }
    }

    *dst_out = dst;
    return ESP_OK;
}

int display_hal_width(void)
{
    return s_state.width;
}

int display_hal_height(void)
{
    return s_state.height;
}

esp_err_t display_hal_begin_frame(bool clear, display_color_t color)
{
    esp_err_t ret = display_hal_lock();
    uint8_t *draw_fb = NULL;
    uint8_t *visible_fb = NULL;

    if (ret != ESP_OK) {
        return ret;
    }

    ret = display_hal_ensure_display_locked();
    if (ret == ESP_OK) {
        ret = display_hal_ensure_framebuffer_locked();
    }
    if (ret == ESP_OK) {
        s_state.frame_active = true;
        display_hal_clear_clip_locked();
        draw_fb = display_hal_get_draw_framebuffer_locked();
        visible_fb = display_hal_get_visible_framebuffer_locked();
        if (clear || !s_state.framebuffer_initialized) {
            display_hal_fill_framebuffer_locked(draw_fb, color);
            if (!display_color_is_transparent(color)) {
                display_dirty_mark(&s_state.dirty, 0, 0, s_state.width, s_state.height);
            }
            s_state.framebuffer_initialized = true;
        } else if (draw_fb && visible_fb && draw_fb != visible_fb) {
            memcpy(draw_fb, visible_fb, s_state.framebuffer_bytes);
        }
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_present(void)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_present_locked();
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_present_full(void)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_present_full_locked();
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_end_frame(void)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (display_dirty_is_valid(&s_state.dirty)) {
        ESP_LOGD(TAG, "ending frame with unpresented dirty rect");
    }
    s_state.frame_active = false;
    display_hal_clear_clip_locked();
    display_hal_unlock();
    return ret;
}

bool display_hal_is_frame_active(void)
{
    bool active = false;

    if (display_hal_lock() == ESP_OK) {
        active = s_state.frame_active;
        display_hal_unlock();
    }
    return active;
}

esp_err_t display_hal_get_animation_info(display_hal_animation_info_t *info)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (!info) {
        display_hal_unlock();
        return ESP_ERR_INVALID_ARG;
    }
    ret = display_hal_ensure_display_locked();
    if (ret == ESP_OK) {
        ret = display_hal_ensure_framebuffer_locked();
    }
    if (ret == ESP_OK) {
        info->framebuffer_count = s_state.framebuffer_count;
        info->double_buffered = s_state.framebuffer_count > 1;
        info->frame_active = s_state.frame_active;
        /* All submits are synchronous; there is never an in-flight flush. */
        info->flush_in_flight = false;
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_clear(display_color_t color)
{
    return display_hal_fill_rect(0, 0, display_hal_width(), display_hal_height(), color);
}

esp_err_t display_hal_set_clip_rect(int x, int y, int width, int height)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    ret = display_hal_require_created_locked();
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }
    if (width <= 0 || height <= 0) {
        display_hal_unlock();
        return ESP_ERR_INVALID_ARG;
    }
    s_state.clip_enabled = true;
    s_state.clip_x = x;
    s_state.clip_y = y;
    s_state.clip_width = width;
    s_state.clip_height = height;
    display_hal_unlock();
    return ESP_OK;
}

esp_err_t display_hal_clear_clip_rect(void)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    display_hal_clear_clip_locked();
    display_hal_unlock();
    return ESP_OK;
}

esp_err_t display_hal_fill_rect(int x, int y, int width, int height, display_color_t color)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_fill_rect_locked(x, y, width, height, color);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_line(int x0, int y0, int x1, int y1, display_color_t color)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_line_locked(x0, y0, x1, y1, color);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_rect(int x, int y, int width, int height, display_color_t color)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_rect_locked(x, y, width, height, color);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_pixel(int x, int y, display_color_t color)
{
    return display_hal_fill_rect(x, y, 1, 1, color);
}

esp_err_t display_hal_set_backlight(bool on)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = esp_lcd_panel_disp_on_off(s_state.panel, on);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_fill_circle(int cx, int cy, int r, display_color_t color)
{
    if (r <= 0) {
        return ESP_OK;
    }
    if (display_color_is_transparent(color)) {
        return ESP_OK;
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    for (int dy = -r; dy <= r && ret == ESP_OK; ++dy) {
        int dx = (int)sqrtf((float)(r * r - dy * dy));
        ret = display_hal_draw_hline_locked(cx - dx, cy + dy, dx * 2 + 1, color);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_circle(int cx, int cy, int r, display_color_t color)
{
    if (r <= 0) {
        return display_hal_draw_pixel(cx, cy, color);
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    int x = 0;
    int y = r;
    int d = 1 - r;

    while (x <= y) {
        const int pts[8][2] = {
            {cx + x, cy + y}, {cx - x, cy + y},
            {cx + x, cy - y}, {cx - x, cy - y},
            {cx + y, cy + x}, {cx - y, cy + x},
            {cx + y, cy - x}, {cx - y, cy - x},
        };
        for (int i = 0; i < 8 && ret == ESP_OK; ++i) {
            ret = display_hal_draw_pixel_locked(pts[i][0], pts[i][1], color);
        }
        if (d < 0) {
            d += 2 * x + 3;
        } else {
            d += 2 * (x - y) + 5;
            y--;
        }
        x++;
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_arc(int cx, int cy, int radius,
                               float start_deg, float end_deg, display_color_t color)
{
    if (radius <= 0) {
        return display_hal_draw_pixel(cx, cy, color);
    }
    if (display_hal_arc_is_full_sweep(start_deg, end_deg)) {
        return display_hal_draw_circle(cx, cy, radius, color);
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    float start = display_hal_normalize_degrees(start_deg);
    float sweep = display_hal_arc_sweep_degrees(start_deg, end_deg);
    int steps = (int)ceilf(((sweep * DISPLAY_HAL_PI) / 180.0f) * (float)radius);
    if (steps < 8) {
        steps = 8;
    }

    int prev_x = cx + (int)lroundf(cosf(start * DISPLAY_HAL_PI / 180.0f) * (float)radius);
    int prev_y = cy + (int)lroundf(sinf(start * DISPLAY_HAL_PI / 180.0f) * (float)radius);

    for (int i = 1; i <= steps && ret == ESP_OK; ++i) {
        float angle = start + (sweep * (float)i / (float)steps);
        float rad = angle * DISPLAY_HAL_PI / 180.0f;
        int x = cx + (int)lroundf(cosf(rad) * (float)radius);
        int y = cy + (int)lroundf(sinf(rad) * (float)radius);
        ret = display_hal_draw_line_locked(prev_x, prev_y, x, y, color);
        prev_x = x;
        prev_y = y;
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_fill_arc(int cx, int cy, int inner_radius, int outer_radius,
                               float start_deg, float end_deg, display_color_t color)
{
    if (outer_radius < 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (outer_radius == 0) {
        return display_hal_draw_pixel(cx, cy, color);
    }
    if (inner_radius < 0) {
        inner_radius = 0;
    }
    if (inner_radius > outer_radius) {
        int tmp = inner_radius;
        inner_radius = outer_radius;
        outer_radius = tmp;
    }
    if (display_hal_arc_is_full_sweep(start_deg, end_deg) && inner_radius == 0) {
        return display_hal_fill_circle(cx, cy, outer_radius, color);
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    int clip_left = 0;
    int clip_top = 0;
    int clip_right = s_state.width;
    int clip_bottom = s_state.height;
    if (!display_hal_get_clip_bounds_locked(&clip_left, &clip_top, &clip_right, &clip_bottom)) {
        display_hal_unlock();
        return ESP_OK;
    }

    int outer_sq = outer_radius * outer_radius;
    int inner_sq = inner_radius * inner_radius;
    int y_start = cy - outer_radius;
    int y_end = cy + outer_radius;
    if (y_start < clip_top) {
        y_start = clip_top;
    }
    if (y_end >= clip_bottom) {
        y_end = clip_bottom - 1;
    }

    for (int y = y_start; y <= y_end && ret == ESP_OK; ++y) {
        int span_start = -1;
        int x_start = cx - outer_radius;
        int x_end = cx + outer_radius;
        if (x_start < clip_left) {
            x_start = clip_left;
        }
        if (x_end >= clip_right) {
            x_end = clip_right - 1;
        }

        for (int x = x_start; x <= x_end; ++x) {
            int dx = x - cx;
            int dy = y - cy;
            int dist_sq = dx * dx + dy * dy;
            bool inside = dist_sq <= outer_sq && dist_sq >= inner_sq;

            if (inside && !display_hal_arc_is_full_sweep(start_deg, end_deg)) {
                inside = display_hal_angle_in_arc(display_hal_point_angle_degrees(dx, dy), start_deg, end_deg);
            }

            if (inside) {
                if (span_start < 0) {
                    span_start = x;
                }
            } else if (span_start >= 0) {
                ret = display_hal_draw_hline_locked(span_start, y, x - span_start, color);
                span_start = -1;
            }
        }

        if (span_start >= 0 && ret == ESP_OK) {
            ret = display_hal_draw_hline_locked(span_start, y, x_end - span_start + 1, color);
        }
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_ellipse(int cx, int cy, int radius_x, int radius_y,
                                   display_color_t color)
{
    if (radius_x < 0 || radius_y < 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (radius_x == 0 && radius_y == 0) {
        return display_hal_draw_pixel(cx, cy, color);
    }
    if (radius_x == 0) {
        return display_hal_draw_line(cx, cy - radius_y, cx, cy + radius_y, color);
    }
    if (radius_y == 0) {
        return display_hal_draw_line(cx - radius_x, cy, cx + radius_x, cy, color);
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    float perimeter = DISPLAY_HAL_PI *
                      (3.0f * (radius_x + radius_y) -
                       sqrtf((float)((3 * radius_x + radius_y) * (radius_x + 3 * radius_y))));
    int steps = (int)ceilf(perimeter);
    if (steps < 16) {
        steps = 16;
    }

    int prev_x = cx + radius_x;
    int prev_y = cy;
    for (int i = 1; i <= steps && ret == ESP_OK; ++i) {
        float angle = ((float)i / (float)steps) * 2.0f * DISPLAY_HAL_PI;
        int x = cx + (int)lroundf(cosf(angle) * (float)radius_x);
        int y = cy + (int)lroundf(sinf(angle) * (float)radius_y);
        ret = display_hal_draw_line_locked(prev_x, prev_y, x, y, color);
        prev_x = x;
        prev_y = y;
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_fill_ellipse(int cx, int cy, int radius_x, int radius_y,
                                   display_color_t color)
{
    if (radius_x < 0 || radius_y < 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (radius_x == 0 && radius_y == 0) {
        return display_hal_draw_pixel(cx, cy, color);
    }
    if (radius_x == 0) {
        return display_hal_fill_rect(cx, cy - radius_y, 1, radius_y * 2 + 1, color);
    }
    if (radius_y == 0) {
        return display_hal_fill_rect(cx - radius_x, cy, radius_x * 2 + 1, 1, color);
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    int clip_left = 0;
    int clip_top = 0;
    int clip_right = s_state.width;
    int clip_bottom = s_state.height;
    if (!display_hal_get_clip_bounds_locked(&clip_left, &clip_top, &clip_right, &clip_bottom)) {
        display_hal_unlock();
        return ESP_OK;
    }

    int y_start = cy - radius_y;
    int y_end = cy + radius_y;
    if (y_start < clip_top) {
        y_start = clip_top;
    }
    if (y_end >= clip_bottom) {
        y_end = clip_bottom - 1;
    }

    for (int y = y_start; y <= y_end && ret == ESP_OK; ++y) {
        float dy = (float)(y - cy) / (float)radius_y;
        float dx = (float)radius_x * sqrtf(fmaxf(0.0f, 1.0f - (dy * dy)));
        int span = (int)lroundf(dx);
        int x0 = cx - span;
        int x1 = cx + span;

        if (x0 < clip_left) {
            x0 = clip_left;
        }
        if (x1 >= clip_right) {
            x1 = clip_right - 1;
        }
        if (x1 >= x0) {
            ret = display_hal_draw_hline_locked(x0, y, x1 - x0 + 1, color);
        }
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_round_rect(int x, int y, int width, int height,
                                      int radius, display_color_t color)
{
    if (width <= 0 || height <= 0) {
        return ESP_OK;
    }

    int max_radius = (width < height ? width : height) / 2;
    if (radius <= 0 || max_radius <= 0) {
        return display_hal_draw_rect(x, y, width, height, color);
    }
    if (radius > max_radius) {
        radius = max_radius;
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    ret = display_hal_draw_hline_locked(x + radius, y, width - (radius * 2), color);
    if (ret == ESP_OK) {
        ret = display_hal_draw_hline_locked(x + radius, y + height - 1, width - (radius * 2), color);
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_vline_locked(x, y + radius, height - (radius * 2), color);
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_vline_locked(x + width - 1, y + radius, height - (radius * 2), color);
    }

    for (int row = 0; row < radius && ret == ESP_OK; ++row) {
        int off = radius - row - 1;
        int dx = (int)sqrtf((float)(radius * radius - off * off));
        int inset = radius - dx;
        ret = display_hal_draw_pixel_locked(x + inset, y + row, color);
        if (ret == ESP_OK) {
            ret = display_hal_draw_pixel_locked(x + width - 1 - inset, y + row, color);
        }
        if (ret == ESP_OK) {
            ret = display_hal_draw_pixel_locked(x + inset, y + height - 1 - row, color);
        }
        if (ret == ESP_OK) {
            ret = display_hal_draw_pixel_locked(x + width - 1 - inset, y + height - 1 - row, color);
        }
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_fill_round_rect(int x, int y, int width, int height,
                                      int radius, display_color_t color)
{
    if (width <= 0 || height <= 0) {
        return ESP_OK;
    }

    int max_radius = (width < height ? width : height) / 2;
    if (radius <= 0 || max_radius <= 0) {
        return display_hal_fill_rect(x, y, width, height, color);
    }
    if (radius > max_radius) {
        radius = max_radius;
    }

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    ret = display_hal_fill_rect_locked(x + radius, y, width - (radius * 2), height, color);
    for (int row = 0; row < radius && ret == ESP_OK; ++row) {
        int off = radius - row - 1;
        int dx = (int)sqrtf((float)(radius * radius - off * off));
        int inset = radius - dx;
        int span_w = width - (inset * 2);
        ret = display_hal_draw_hline_locked(x + inset, y + row, span_w, color);
        if (ret == ESP_OK) {
            ret = display_hal_draw_hline_locked(x + inset, y + height - 1 - row, span_w, color);
        }
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_triangle(int x1, int y1, int x2, int y2,
                                    int x3, int y3, display_color_t color)
{
    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_line_locked(x1, y1, x2, y2, color);
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_line_locked(x2, y2, x3, y3, color);
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_line_locked(x3, y3, x1, y1, color);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_fill_triangle(int x1, int y1, int x2, int y2,
                                    int x3, int y3, display_color_t color)
{
    display_hal_sort_vertices_by_y(&x1, &y1, &x2, &y2, &x3, &y3);

    esp_err_t ret = display_hal_lock();
    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret != ESP_OK) {
        display_hal_unlock();
        return ret;
    }

    if (y1 == y3) {
        int min_x = x1;
        int max_x = x1;
        if (x2 < min_x) {
            min_x = x2;
        }
        if (x3 < min_x) {
            min_x = x3;
        }
        if (x2 > max_x) {
            max_x = x2;
        }
        if (x3 > max_x) {
            max_x = x3;
        }
        ret = display_hal_draw_hline_locked(min_x, y1, max_x - min_x + 1, color);
        display_hal_unlock();
        return ret;
    }

    for (int y = y1; y <= y3 && ret == ESP_OK; ++y) {
        float alpha = (y3 == y1) ? 0.0f : (float)(y - y1) / (float)(y3 - y1);
        float beta = 0.0f;
        int ax = x1 + (int)lroundf((x3 - x1) * alpha);
        int bx = 0;

        if (y < y2) {
            beta = (y2 == y1) ? 0.0f : (float)(y - y1) / (float)(y2 - y1);
            bx = x1 + (int)lroundf((x2 - x1) * beta);
        } else {
            beta = (y3 == y2) ? 0.0f : (float)(y - y2) / (float)(y3 - y2);
            bx = x2 + (int)lroundf((x3 - x2) * beta);
        }

        if (ax > bx) {
            int tmp = ax;
            ax = bx;
            bx = tmp;
        }
        ret = display_hal_draw_hline_locked(ax, y, bx - ax + 1, color);
    }

    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_measure_text(const char *text, uint8_t font_size,
                                   uint16_t *out_width, uint16_t *out_height)
{
    const esp_painter_basic_font_t *font = display_hal_get_font(font_size);

    ESP_RETURN_ON_FALSE(font != NULL, ESP_ERR_NOT_SUPPORTED, TAG, "font size %u unavailable", font_size);
    display_hal_measure_text_raw(text, font, out_width, out_height);
    return ESP_OK;
}

static esp_err_t display_hal_draw_text_bitmap_locked(int x, int y, const char *text,
                                                     const esp_painter_basic_font_t *font,
                                                     display_color_t text_color)
{
    int cursor_x = x;
    int cursor_y = y;
    int bytes_per_row = (font->width + 7) / 8;

    if (display_color_is_transparent(text_color)) {
        return ESP_OK;
    }

    while (*text) {
        unsigned char ch = (unsigned char)*text++;
        if (ch == '\n') {
            cursor_x = x;
            cursor_y += font->height;
            continue;
        }
        if (ch == '\r') {
            cursor_x = x;
            continue;
        }
        if (ch == '\t') {
            cursor_x += font->width * 4;
            continue;
        }
        if (ch < 32 || ch > 126) {
            ESP_LOGE(TAG, "unsupported text character: 0x%02x", ch);
            return ESP_ERR_INVALID_ARG;
        }

        const uint8_t *bitmap = font->bitmap + ((size_t)(ch - 32) * font->height * bytes_per_row);
        for (int dy = 0; dy < font->height; ++dy) {
            for (int dx = 0; dx < font->width; ++dx) {
                uint8_t bits = bitmap[(size_t)dy * bytes_per_row + dx / 8];
                if ((bits & (0x80 >> (dx % 8))) == 0) {
                    continue;
                }
                esp_err_t ret = display_hal_draw_pixel_locked(cursor_x + dx, cursor_y + dy, text_color);
                if (ret != ESP_OK) {
                    return ret;
                }
            }
        }
        cursor_x += font->width;
    }
    return ESP_OK;
}

esp_err_t display_hal_draw_text(int x, int y, const char *text, uint8_t font_size,
                                display_color_t text_color, bool has_bg, display_color_t bg_color)
{
    const esp_painter_basic_font_t *font = NULL;
    uint16_t text_w = 0;
    uint16_t text_h = 0;
    bool text_needs_alpha = false;
    bool bg_needs_alpha = false;
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    ESP_GOTO_ON_FALSE(text != NULL, ESP_ERR_INVALID_ARG, fail, TAG, "text is NULL");
    if (text[0] == '\0') {
        ret = ESP_OK;
        goto fail;
    }

    ret = display_hal_ensure_display_locked();
    if (ret != ESP_OK) {
        goto fail;
    }
    text_needs_alpha = !display_color_is_transparent(text_color) && !display_color_is_opaque(text_color);
    bg_needs_alpha = has_bg && !display_color_is_transparent(bg_color) && !display_color_is_opaque(bg_color);
    if ((text_needs_alpha || bg_needs_alpha) && (!s_state.frame_active || !display_hal_get_draw_framebuffer_locked())) {
        ESP_LOGE(TAG, "text alpha drawing requires an active framebuffer");
        ret = ESP_ERR_INVALID_STATE;
        goto fail;
    }

    font = display_hal_get_font(font_size);
    ESP_GOTO_ON_FALSE(font != NULL, ESP_ERR_NOT_SUPPORTED, fail, TAG, "font size %u unavailable", font_size);
    display_hal_measure_text_raw(text, font, &text_w, &text_h);
    if (text_w == 0 || text_h == 0) {
        ret = ESP_OK;
        goto fail;
    }

    if (has_bg) {
        ret = display_hal_fill_rect_locked(x, y, (int)text_w, (int)text_h, bg_color);
        if (ret != ESP_OK) {
            goto fail;
        }
    }
    ret = display_hal_draw_text_bitmap_locked(x, y, text, font, text_color);

fail:
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_text_aligned(int x, int y, int width, int height,
                                        const char *text, uint8_t font_size,
                                        display_color_t text_color, bool has_bg, display_color_t bg_color,
                                        display_hal_text_align_t align,
                                        display_hal_text_valign_t valign)
{
    uint16_t text_w = 0;
    uint16_t text_h = 0;
    ESP_RETURN_ON_ERROR(display_hal_measure_text(text, font_size, &text_w, &text_h), TAG,
                        "measure text failed");

    int draw_x = x;
    int draw_y = y;

    if (width > 0) {
        if (align == DISPLAY_HAL_TEXT_ALIGN_CENTER) {
            draw_x = x + (width - (int)text_w) / 2;
        } else if (align == DISPLAY_HAL_TEXT_ALIGN_RIGHT) {
            draw_x = x + width - (int)text_w;
        }
    }
    if (height > 0) {
        if (valign == DISPLAY_HAL_TEXT_VALIGN_MIDDLE) {
            draw_y = y + (height - (int)text_h) / 2;
        } else if (valign == DISPLAY_HAL_TEXT_VALIGN_BOTTOM) {
            draw_y = y + height - (int)text_h;
        }
    }

    return display_hal_draw_text(draw_x, draw_y, text, font_size, text_color, has_bg, bg_color);
}

esp_err_t display_hal_draw_bitmap(int x, int y, int w, int h,
                                  const void *pixels,
                                  display_hal_pixel_format_t src_format)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap_locked(x, y, w, h, pixels, src_format, false);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_bitmap_native(int x, int y, int w, int h,
                                         const void *pixels,
                                         display_hal_pixel_format_t src_format)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap_locked(x, y, w, h, pixels, src_format, true);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_bitmap_crop(int x, int y,
                                       int src_x, int src_y,
                                       int w, int h,
                                       int src_width, int src_height,
                                       const void *pixels,
                                       display_hal_pixel_format_t src_format)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap_crop_locked(x, y, src_x, src_y, w, h,
                                                  src_width, src_height, pixels, src_format, false);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_bitmap_crop_native(int x, int y,
                                              int src_x, int src_y,
                                              int w, int h,
                                              int src_width, int src_height,
                                              const void *pixels,
                                              display_hal_pixel_format_t src_format)
{
    esp_err_t ret = display_hal_lock();

    if (ret != ESP_OK) {
        return ret;
    }
    if (ret == ESP_OK) {
        ret = display_hal_ensure_display_locked();
    }
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap_crop_locked(x, y, src_x, src_y, w, h,
                                                  src_width, src_height, pixels, src_format, true);
    }
    display_hal_unlock();
    return ret;
}

esp_err_t display_hal_draw_bitmap_scaled(int x, int y,
                                         const void *pixels,
                                         int src_width, int src_height,
                                         int scale_w, int scale_h,
                                         display_hal_pixel_format_t src_format,
                                         int *out_w, int *out_h)
{
    void *scaled = NULL;
    esp_err_t ret = ESP_OK;
    size_t bpp = display_hal_pixel_format_bytes(src_format);

    if (!pixels || src_width <= 0 || src_height <= 0 || scale_w <= 0 || scale_h <= 0 || bpp == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    ret = display_hal_scale_pixels(pixels, src_width, src_height, scale_w, scale_h, bpp, &scaled);
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap(x, y, scale_w, scale_h, scaled, src_format);
    }
    if (out_w) {
        *out_w = scale_w;
    }
    if (out_h) {
        *out_h = scale_h;
    }
    free(scaled);
    return ret;
}

esp_err_t display_hal_draw_bitmap_scaled_native(int x, int y,
                                                const void *pixels,
                                                int src_width, int src_height,
                                                int scale_w, int scale_h,
                                                display_hal_pixel_format_t src_format,
                                                int *out_w, int *out_h)
{
    void *scaled = NULL;
    esp_err_t ret = ESP_OK;
    size_t bpp = display_hal_pixel_format_bytes(src_format);

    if (!pixels || src_width <= 0 || src_height <= 0 || scale_w <= 0 || scale_h <= 0 || bpp == 0) {
        return ESP_ERR_INVALID_ARG;
    }

    ret = display_hal_scale_pixels(pixels, src_width, src_height, scale_w, scale_h, bpp, &scaled);
    if (ret == ESP_OK) {
        ret = display_hal_draw_bitmap_native(x, y, scale_w, scale_h, scaled, src_format);
    }
    if (out_w) {
        *out_w = scale_w;
    }
    if (out_h) {
        *out_h = scale_h;
    }
    free(scaled);
    return ret;
}
