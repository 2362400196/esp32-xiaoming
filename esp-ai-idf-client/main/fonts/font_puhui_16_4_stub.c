// font_puhui_16_4 空壳版 — 供无显示屏幕的板型（如 ESP32-C3 SuperMini）使用。
// 全量中文字库占 2.1MB flash，无屏设备完全用不到；本文件保持同名符号
// font_puhui_16_4（lv_font_t），cmap_num=0 即查不到任何字形（渲染为空白），
// eeui_port.cpp 等引用处代码无需任何改动，即可为 4MB flash 板型省出 2.1MB。
#include "lvgl.h"

static const lv_font_fmt_txt_dsc_t font_dsc = {
    .glyph_bitmap = NULL,
    .glyph_dsc = NULL,
    .cmaps = NULL,
    .kern_dsc = NULL,
    .kern_scale = 0,
    .cmap_num = 0,
    .bpp = 1,
    .kern_classes = 0,
    .bitmap_format = 0,
#if LVGL_VERSION_MAJOR == 8
    .cache = NULL
#endif
};

const lv_font_t font_puhui_16_4 = {
    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,
    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,
    .line_height = 20,
    .base_line = 5,
    .subpx = LV_FONT_SUBPX_NONE,
    .underline_position = -1,
    .underline_thickness = 1,
    .dsc = &font_dsc,
    .fallback = NULL,
    .user_data = NULL,
};
