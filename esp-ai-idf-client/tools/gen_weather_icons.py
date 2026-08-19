#!/usr/bin/env python3
"""生成天气图标 C 数组（LVGL ARGB8565，带透明通道）。
用法: python tools/gen_weather_icons.py > main/fonts/weather_icons.c
图标: sun 晴 / sun_cloud 晴间多云 / cloud 多云 / overcast 阴 /
      rain 雨 / storm 雷阵雨 / snow 雪 / fog 雾"""
from PIL import Image, ImageDraw
import math, sys

SIZE = 48   # 绘制画布
OUT = 32    # 输出尺寸

SUN    = (255, 211, 77, 255)     # 暖金
CLOUD  = (200, 204, 212, 255)    # 浅灰
CDARK  = (154, 160, 168, 255)    # 深灰（阴）
RAIN   = (91, 141, 239, 255)     # 蓝
SNOW   = (232, 236, 242, 255)    # 白
FOG    = (138, 143, 152, 255)    # 雾灰

def new_canvas():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)

def draw_sun(d, cx, cy, r, color):
    for i in range(8):
        a = math.radians(i * 45)
        d.line([(cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3)),
                (cx + math.cos(a) * (r + 10), cy + math.sin(a) * (r + 10))],
               fill=color, width=3)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

def draw_cloud(d, x, y, w, h, color):
    d.rounded_rectangle([x, y + h // 3, x + w, y + h], radius=h // 3, fill=color)
    d.ellipse([x + w // 4 - 3, y - h // 4, x + w // 2 + 2, y + h // 2], fill=color)
    d.ellipse([x + w // 3, y - h // 2, x + w // 3 + w // 2, y + h // 2 + 2], fill=color)

def draw_rain(d, x, y, color):
    for dx, dy in [(5, 0), (13, 3), (21, 0)]:
        d.line([(x + dx, y + dy), (x + dx - 2, y + dy + 7)], fill=color, width=2)
        d.line([(x + dx - 2, y + dy + 7), (x + dx - 3, y + dy + 10)], fill=color, width=2)

def draw_bolt(d, cx, cy, color):
    d.polygon([(cx + 4, cy - 11), (cx - 5, cy + 3), (cx - 1, cy + 3),
               (cx - 4, cy + 11), (cx + 5, cy - 2), (cx + 1, cy - 2)], fill=color)

def draw_snow(d, x, y, color):
    for dx, dy in [(0, 0), (11, 1), (22, 0), (6, 5), (17, 5)]:
        d.ellipse([x + dx - 2, y + dy - 2, x + dx + 2, y + dy + 2], fill=color)

def draw_fog(d, x, y, w, color):
    d.line([(x, y), (x + w, y)], fill=color, width=3)
    d.line([(x + w // 5, y + 6), (x + w, y + 6)], fill=color, width=3)

icons = {}

img, d = new_canvas()
draw_sun(d, 24, 22, 9, SUN); icons["sun"] = img

img, d = new_canvas()
draw_sun(d, 18, 20, 7, SUN)
draw_cloud(d, 17, 20, 25, 14, CLOUD); icons["sun_cloud"] = img

img, d = new_canvas()
draw_cloud(d, 10, 14, 28, 17, CLOUD); icons["cloud"] = img

img, d = new_canvas()
draw_cloud(d, 10, 14, 28, 17, CDARK); icons["overcast"] = img

img, d = new_canvas()
draw_cloud(d, 8, 10, 30, 17, CLOUD)
draw_rain(d, 15, 31, RAIN); icons["rain"] = img

img, d = new_canvas()
draw_cloud(d, 6, 8, 32, 17, CDARK)
draw_bolt(d, 24, 32, SUN); icons["storm"] = img

img, d = new_canvas()
draw_cloud(d, 8, 10, 30, 17, CLOUD)
draw_snow(d, 11, 33, SNOW); icons["snow"] = img

img, d = new_canvas()
draw_cloud(d, 10, 10, 28, 15, CLOUD)
draw_fog(d, 10, 34, 28, FOG); icons["fog"] = img

def to_argb8565(img, size):
    img = img.resize((size, size), Image.LANCZOS).convert("RGBA")
    px = img.load()
    out = []
    for y in range(size):
        for x in range(size):
            r, g, b, a = px[x, y]
            v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out.append(a)            # alpha
            out.append(v & 0xFF)     # 565 低字节
            out.append(v >> 8)       # 565 高字节
    return out

lines = ['#include "lvgl.h"', '']
for name, img in icons.items():
    data = to_argb8565(img, OUT)
    lines.append(f'/* {name} */')
    lines.append(f'static const uint8_t weather_icon_{name}_data[] = {{')
    for i in range(0, len(data), 12):
        lines.append('    ' + ', '.join(f'0x{v:02X}' for v in data[i:i+12]) + ',')
    lines.append('};')
    lines.append(f'static const lv_image_dsc_t weather_icon_{name} = {{')
    lines.append(f'    .header = {{.magic = LV_IMAGE_HEADER_MAGIC, .cf = LV_COLOR_FORMAT_ARGB8565, .w = {OUT}, .h = {OUT}, .stride = {OUT * 3}}},')
    lines.append(f'    .data_size = {OUT * OUT * 3},')
    lines.append(f'    .data = weather_icon_{name}_data,')
    lines.append('};')
    lines.append('')

lines.append('typedef struct { const char *id; const lv_image_dsc_t *img; } weather_icon_entry_t;')
lines.append('')
lines.append('const weather_icon_entry_t weather_icon_table[] = {')
for name in icons:
    lines.append(f'    {{"{name}", &weather_icon_{name}}},')
lines.append('};')
lines.append('')
lines.append('const int weather_icon_count = %d;' % len(icons))
print('\n'.join(lines))
