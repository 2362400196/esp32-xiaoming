#include "gifdec.h"
#include "../../misc/lv_log.h"
#include "../../stdlib/lv_mem.h"
#include "../../misc/lv_color.h"
#if LV_USE_GIF

#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include <stdio.h>
#include "esp_heap_caps.h"  /* ESP-IDF：用 heap_caps_malloc 分配内部 RAM，避免 PSRAM Cache error */
#include "esp_log.h"

#define MIN(A, B) ((A) < (B) ? (A) : (B))
#define MAX(A, B) ((A) > (B) ? (A) : (B))

typedef struct Entry {
    uint16_t length;
    uint16_t prefix;
    uint8_t  suffix;
} Entry;

typedef struct Table {
    int bulk;
    int nentries;
    Entry * entries;
} Table;

#if LV_GIF_CACHE_DECODE_DATA
#define LZW_MAXBITS                 12
#define LZW_TABLE_SIZE              (1 << LZW_MAXBITS)
#define LZW_CACHE_SIZE              (LZW_TABLE_SIZE * 4)
#endif

static gd_GIF  * gif_open(gd_GIF * gif);
static bool f_gif_open(gd_GIF * gif, const void * path, bool is_file);
static void f_gif_read(gd_GIF * gif, void * buf, size_t len);
static int f_gif_seek(gd_GIF * gif, size_t pos, int k);
static void f_gif_close(gd_GIF * gif);

#if LV_USE_DRAW_SW_ASM == LV_DRAW_SW_ASM_HELIUM
    #include "gifdec_mve.h"
#endif

static uint16_t
read_num(gd_GIF * gif)
{
    uint8_t bytes[2];

    f_gif_read(gif, bytes, 2);
    return bytes[0] + (((uint16_t) bytes[1]) << 8);
}

gd_GIF *
gd_open_gif_file(const char * fname)
{
    gd_GIF gif_base;
    memset(&gif_base, 0, sizeof(gif_base));

    bool res = f_gif_open(&gif_base, fname, true);
    if(!res) return NULL;

    return gif_open(&gif_base);
}

gd_GIF *
gd_open_gif_data(const void * data, size_t data_size)
{
    gd_GIF gif_base;
    memset(&gif_base, 0, sizeof(gif_base));
    gif_base.data_size = (uint32_t)data_size;

    bool res = f_gif_open(&gif_base, data, false);
    if(!res) return NULL;

    return gif_open(&gif_base);
}

static gd_GIF * gif_open(gd_GIF * gif_base)
{
    uint8_t sigver[3];
    uint16_t width, height, depth;
    uint8_t fdsz, bgidx, aspect;
    uint8_t * bgcolor;
    int gct_sz;
    gd_GIF * gif = NULL;

    /* Header */
    f_gif_read(gif_base, sigver, 3);
    if(memcmp(sigver, "GIF", 3) != 0) {
        LV_LOG_WARN("invalid signature");
        goto fail;
    }
    /* Version */
    f_gif_read(gif_base, sigver, 3);
    if(memcmp(sigver, "89a", 3) != 0) {
        LV_LOG_WARN("invalid version");
        goto fail;
    }
    /* Width x Height */
    width  = read_num(gif_base);
    height = read_num(gif_base);
    /* FDSZ */
    f_gif_read(gif_base, &fdsz, 1);
    /* Presence of GCT */
    if(!(fdsz & 0x80)) {
        LV_LOG_WARN("no global color table");
        goto fail;
    }
    /* Color Space's Depth */
    depth = ((fdsz >> 4) & 7) + 1;
    /* Ignore Sort Flag. */
    /* GCT Size */
    gct_sz = 1 << ((fdsz & 0x07) + 1);
    /* Background Color Index */
    f_gif_read(gif_base, &bgidx, 1);
    /* Aspect Ratio */
    f_gif_read(gif_base, &aspect, 1);
    /* Create gd_GIF Structure. */
    if(0 == width || 0 == height){
        LV_LOG_WARN("Zero size image");
        goto fail;
    }
/* RGB565A8 planar format: canvas(3*w*h) + frame(1*w*h) = 4*w*h
     * Layout: [RGB565 plane: 2*w*h bytes][A8 plane: 1*w*h bytes][frame index: 1*w*h bytes]
     * 与 LVGL 8 的 TRUE_COLOR_ALPHA(16bit) 等效，消除 ARGB8888→RGB565 转换开销
     * 优先内部 RAM（1周期访问），PSRAM 有 cache miss 延迟导致卡顿/花屏 */
    /* 关键修复：将 gd_GIF 结构体分配在内部 RAM，画布数据分配在 PSRAM。
     * 结构体包含 palette/width/height/canvas 指针等关键字段，放在内部 RAM
     * 可避免被 WebSocket/音频/WiFi 等任务的 PSRAM 缓冲区溢出篡改，
     * 从根本上消除 GIF 渲染崩溃问题。
     * 结构体约 1.7KB（含两个 768B 调色板），内部 RAM 有 ~36KB 可用。 */
    #if LV_GIF_CACHE_DECODE_DATA
    if(0 == (INT_MAX - LZW_CACHE_SIZE) / width / height / 4){
        LV_LOG_WARN("Image dimensions are too large");
        goto fail;
    }
    #else
    if(0 == INT_MAX / width / height / 4){
        LV_LOG_WARN("Image dimensions are too large");
        goto fail;
    }
    #endif
    /* 1. 结构体分配在内部 RAM（优先），不足时回退 PSRAM */
    gif = heap_caps_malloc(sizeof(gd_GIF), MALLOC_CAP_INTERNAL);
    if(!gif) gif = heap_caps_malloc(sizeof(gd_GIF), MALLOC_CAP_SPIRAM);
    if(!gif) goto fail;
    /* 2. 画布数据分配在 PSRAM（大块数据，约 4*w*h 字节） */
    #if LV_GIF_CACHE_DECODE_DATA
    uint8_t *canvas_mem = heap_caps_malloc(4 * (size_t)width * height + LZW_CACHE_SIZE, MALLOC_CAP_SPIRAM);
    if(!canvas_mem) canvas_mem = heap_caps_malloc(4 * (size_t)width * height + LZW_CACHE_SIZE, MALLOC_CAP_INTERNAL);
    #else
    uint8_t *canvas_mem = heap_caps_malloc(4 * (size_t)width * height, MALLOC_CAP_SPIRAM);
    if(!canvas_mem) canvas_mem = heap_caps_malloc(4 * (size_t)width * height, MALLOC_CAP_INTERNAL);
    #endif
    if(!canvas_mem) { heap_caps_free(gif); gif = NULL; goto fail; }
    /* 诊断日志（首次分配时输出，后续不再刷屏） */
    static bool s_gif_log_once = false;
    if (!s_gif_log_once) {
        s_gif_log_once = true;
        const char *struct_type = ((uint32_t)gif < 0x3F000000) ? "PSRAM" : "INTERNAL";
        const char *canvas_type = ((uint32_t)canvas_mem < 0x3F000000) ? "PSRAM" : "INTERNAL";
        printf("[gifdec] GIF struct: %d bytes @ %p (%s), canvas: %dx%d alloc=%d bytes @ %p (%s)\n",
               (int)sizeof(gd_GIF), gif, struct_type,
               width, height, (int)(4 * width * height), canvas_mem, canvas_type);
    }
    memcpy(gif, gif_base, sizeof(gd_GIF));
    gif->canvas_alloc = canvas_mem;
    gif->width  = width;
    gif->height = height;
    gif->depth  = depth;
    /* Read GCT */
    gif->gct.size = gct_sz;
    f_gif_read(gif, gif->gct.colors, 3 * gif->gct.size);
    gif->palette = &gif->gct;
    gif->bgindex = bgidx;
    /* RGB565A8 planar layout:
     * canvas[0 .. w*h*2-1]  = RGB565 color plane (2 bytes/pixel)
     * canvas[w*h*2 .. w*h*3-1] = A8 alpha plane (1 byte/pixel)
     * frame[w*h*3 .. w*h*4-1] = frame index buffer (1 byte/pixel)
     */
    gif->canvas = canvas_mem;
    gif->frame = canvas_mem + 3 * (size_t)width * height;
    if(gif->bgindex) {
        memset(gif->frame, gif->bgindex, gif->width * gif->height);
    }
    bgcolor = &gif->palette->colors[gif->bgindex * 3];
    #if LV_GIF_CACHE_DECODE_DATA
    gif->lzw_cache = gif->frame + width * height;
    #endif

    /* 填充背景：RGB565 color plane + A8 alpha plane */
    {
        /* 内联 RGB565 转换，避免 lv_color_make + lv_color_to_u16 函数调用开销 */
        uint8_t r = *(bgcolor + 0);
        uint8_t g = *(bgcolor + 1);
        uint8_t b = *(bgcolor + 2);
        uint16_t bg565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
        int total = gif->width * gif->height;
        uint8_t *color_plane = gif->canvas;
        uint8_t *alpha_plane = gif->canvas + total * 2;
        for(int i = 0; i < total; i++) {
            color_plane[i * 2 + 0] = bg565 & 0xff;
            color_plane[i * 2 + 1] = (bg565 >> 8) & 0xff;
            alpha_plane[i] = 0xff;
        }
    }
    gif->anim_start = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
    gif->loop_count = -1;
    goto ok;
fail:
    f_gif_close(gif_base);
ok:
    return gif;
}

static void
discard_sub_blocks(gd_GIF * gif)
{
    uint8_t size;

    do {
        f_gif_read(gif, &size, 1);
        f_gif_seek(gif, size, LV_FS_SEEK_CUR);
    } while(size);
}

static void
read_plain_text_ext(gd_GIF * gif)
{
    if(gif->plain_text) {
        uint16_t tx, ty, tw, th;
        uint8_t cw, ch, fg, bg;
        size_t sub_block;
        f_gif_seek(gif, 1, LV_FS_SEEK_CUR); /* block size = 12 */
        tx = read_num(gif);
        ty = read_num(gif);
        tw = read_num(gif);
        th = read_num(gif);
        f_gif_read(gif, &cw, 1);
        f_gif_read(gif, &ch, 1);
        f_gif_read(gif, &fg, 1);
        f_gif_read(gif, &bg, 1);
        sub_block = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
        gif->plain_text(gif, tx, ty, tw, th, cw, ch, fg, bg);
        f_gif_seek(gif, sub_block, LV_FS_SEEK_SET);
    }
    else {
        /* Discard plain text metadata. */
        f_gif_seek(gif, 13, LV_FS_SEEK_CUR);
    }
    /* Discard plain text sub-blocks. */
    discard_sub_blocks(gif);
}

static void
read_graphic_control_ext(gd_GIF * gif)
{
    uint8_t rdit;

    /* Discard block size (always 0x04). */
    f_gif_seek(gif, 1, LV_FS_SEEK_CUR);
    f_gif_read(gif, &rdit, 1);
    gif->gce.disposal = (rdit >> 2) & 3;
    gif->gce.input = rdit & 2;
    gif->gce.transparency = rdit & 1;
    gif->gce.delay = read_num(gif);
    f_gif_read(gif, &gif->gce.tindex, 1);
    /* Skip block terminator. */
    f_gif_seek(gif, 1, LV_FS_SEEK_CUR);
}

static void
read_comment_ext(gd_GIF * gif)
{
    if(gif->comment) {
        size_t sub_block = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
        gif->comment(gif);
        f_gif_seek(gif, sub_block, LV_FS_SEEK_SET);
    }
    /* Discard comment sub-blocks. */
    discard_sub_blocks(gif);
}

static void
read_application_ext(gd_GIF * gif)
{
    char app_id[8];
    char app_auth_code[3];
    uint16_t loop_count;

    /* Discard block size (always 0x0B). */
    f_gif_seek(gif, 1, LV_FS_SEEK_CUR);
    /* Application Identifier. */
    f_gif_read(gif, app_id, 8);
    /* Application Authentication Code. */
    f_gif_read(gif, app_auth_code, 3);
    if(!strncmp(app_id, "NETSCAPE", sizeof(app_id))) {
        /* Discard block size (0x03) and constant byte (0x01). */
        f_gif_seek(gif, 2, LV_FS_SEEK_CUR);
        loop_count = read_num(gif);
        if(gif->loop_count < 0) {
            if(loop_count == 0) {
                gif->loop_count = 0;
            }
            else {
                gif->loop_count = loop_count + 1;
            }
        }
        /* Skip block terminator. */
        f_gif_seek(gif, 1, LV_FS_SEEK_CUR);
    }
    else if(gif->application) {
        size_t sub_block = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
        gif->application(gif, app_id, app_auth_code);
        f_gif_seek(gif, sub_block, LV_FS_SEEK_SET);
        discard_sub_blocks(gif);
    }
    else {
        discard_sub_blocks(gif);
    }
}

static void
read_ext(gd_GIF * gif)
{
    uint8_t label;

    f_gif_read(gif, &label, 1);
    switch(label) {
        case 0x01:
            read_plain_text_ext(gif);
            break;
        case 0xF9:
            read_graphic_control_ext(gif);
            break;
        case 0xFE:
            read_comment_ext(gif);
            break;
        case 0xFF:
            read_application_ext(gif);
            break;
        default:
            LV_LOG_WARN("unknown extension: %02X\n", label);
    }
}

static uint16_t
get_key(gd_GIF *gif, int key_size, uint8_t *sub_len, uint8_t *shift, uint8_t *byte)
{
    int bits_read;
    int rpad;
    int frag_size;
    uint16_t key;

    key = 0;
    for (bits_read = 0; bits_read < key_size; bits_read += frag_size) {
        rpad = (*shift + bits_read) % 8;
        if (rpad == 0) {
            /* Update byte. */
            if (*sub_len == 0) {
                f_gif_read(gif, sub_len, 1); /* Must be nonzero! */
                if (*sub_len == 0) return 0x1000;
            }
            f_gif_read(gif, byte, 1);
            (*sub_len)--;
        }
        frag_size = MIN(key_size - bits_read, 8 - rpad);
        key |= ((uint16_t) ((*byte) >> rpad)) << bits_read;
    }
    /* Clear extra bits to the left. */
    key &= (1 << key_size) - 1;
    *shift = (*shift + key_size) % 8;
    return key;
}

#if LV_GIF_CACHE_DECODE_DATA
/* Decompress image pixels.
 * Return 0 on success or -1 on out-of-memory (w.r.t. LZW code table) or parse error. */
static int
read_image_data(gd_GIF *gif, int interlace)
{
    uint8_t sub_len, shift, byte;
    int ret = 0;
    int key_size;
    int y, pass, linesize;
    uint8_t *ptr = NULL;
    uint8_t *ptr_row_start = NULL;
    uint8_t *ptr_base = NULL;
    size_t start, end;
    uint16_t key, clear_code, stop_code, curr_code;
    int frm_off, frm_size,curr_size,top_slot,new_codes,slot;
    /* The first value of the value sequence corresponding to key */
    int first_value;
    int last_key;
    uint8_t *sp = NULL;
    uint8_t *p_stack = NULL;
    uint8_t *p_suffix = NULL;
    uint16_t *p_prefix = NULL;

    /* get initial key size and clear code, stop code */
    f_gif_read(gif, &byte, 1);
    key_size = (int) byte;
    clear_code = 1 << key_size;
    stop_code = clear_code + 1;
    key = 0;

    start = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
    discard_sub_blocks(gif);
    end = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
    f_gif_seek(gif, start, LV_FS_SEEK_SET);

    linesize = gif->width;
    ptr_base = &gif->frame[gif->fy * linesize + gif->fx];
    ptr_row_start = ptr_base;
    ptr = ptr_row_start;
    sub_len = shift = 0;
    /* decoder */
    pass = 0;
    y = 0;
    p_stack = gif->lzw_cache;
    p_suffix = gif->lzw_cache + LZW_TABLE_SIZE;
    p_prefix = (uint16_t*)(gif->lzw_cache + LZW_TABLE_SIZE * 2);
    frm_off = 0;
    frm_size = gif->fw * gif->fh;
    curr_size = key_size + 1;
    top_slot = 1 << curr_size;
    new_codes = clear_code + 2;
    slot = new_codes;
    first_value = -1;
    last_key = -1;
    sp = p_stack;

    while (frm_off < frm_size) {
        /* copy data to frame buffer */
        while (sp > p_stack) {
            if(frm_off >= frm_size){
                LV_LOG_WARN("LZW table token overflows the frame buffer");
                return -1;
            }
            *ptr++ = *(--sp);
            frm_off += 1;
            /* read one line */
            if ((ptr - ptr_row_start) == gif->fw) {
                if (interlace) {
                    switch(pass) {
                    case 0:
                    case 1:
                        y += 8;
                        ptr_row_start += linesize * 8;
                        break;
                    case 2:
                        y += 4;
                        ptr_row_start += linesize * 4;
                        break;
                    case 3:
                        y += 2;
                        ptr_row_start += linesize * 2;
                        break;
                    default:
                        break;
                    }
                    while (y >= gif->fh) {
                        y  = 4 >> pass;
                        ptr_row_start = ptr_base + linesize * y;
                        pass++;
                    }
                } else {
                    ptr_row_start += linesize;
                }
                ptr = ptr_row_start;
            }
        }

        key = get_key(gif, curr_size, &sub_len, &shift, &byte);

        if (key == stop_code || key >= LZW_TABLE_SIZE)
            break;

        if (key == clear_code) {
            curr_size = key_size + 1;
            slot = new_codes;
            top_slot = 1 << curr_size;
            first_value = last_key = -1;
            sp = p_stack;
            continue;
        }

        curr_code = key;
        /*
         * If the current code is a code that will be added to the decoding
         * dictionary, it is composed of the data list corresponding to the
         * previous key and its first data.
         * */
        if (curr_code == slot && first_value >= 0) {
            *sp++ = first_value;
            curr_code = last_key;
        }else if(curr_code >= slot)
            break;

        while (curr_code >= new_codes) {
            *sp++ = p_suffix[curr_code];
            curr_code = p_prefix[curr_code];
        }
        *sp++ = curr_code;

        /* Add code to decoding dictionary */
        if (slot < top_slot && last_key >= 0) {
            p_suffix[slot] = curr_code;
            p_prefix[slot++] = last_key;
        }
        first_value = curr_code;
        last_key = key;
        if (slot >= top_slot) {
            if (curr_size < LZW_MAXBITS) {
                top_slot <<= 1;
                curr_size += 1;
            }
        }
    }

    if (key == stop_code) f_gif_read(gif, &sub_len, 1); /* Must be zero! */
    f_gif_seek(gif, end, LV_FS_SEEK_SET);
    return ret;
}
#else
static Table *
new_table(int key_size)
{
    int key;
    int init_bulk = MAX(1 << (key_size + 1), 0x100);
    Table * table = lv_malloc(sizeof(*table) + sizeof(Entry) * init_bulk);
    if(table) {
        table->bulk = init_bulk;
        table->nentries = (1 << key_size) + 2;
        table->entries = (Entry *) &table[1];
        for(key = 0; key < (1 << key_size); key++)
            table->entries[key] = (Entry) {
            1, 0xFFF, key
        };
    }
    return table;
}

/* Add table entry. Return value:
 *  0 on success
 *  +1 if key size must be incremented after this addition
 *  -1 if could not realloc table */
static int
add_entry(Table ** tablep, uint16_t length, uint16_t prefix, uint8_t suffix)
{
    Table * table = *tablep;
    if(table->nentries == table->bulk) {
        table->bulk *= 2;
        table = lv_realloc(table, sizeof(*table) + sizeof(Entry) * table->bulk);
        if(!table) return -1;
        table->entries = (Entry *) &table[1];
        *tablep = table;
    }
    table->entries[table->nentries] = (Entry) {
        length, prefix, suffix
    };
    table->nentries++;
    if((table->nentries & (table->nentries - 1)) == 0)
        return 1;
    return 0;
}

/* Compute output index of y-th input line, in frame of height h. */
static int
interlaced_line_index(int h, int y)
{
    int p; /* number of lines in current pass */

    p = (h - 1) / 8 + 1;
    if(y < p)  /* pass 1 */
        return y * 8;
    y -= p;
    p = (h - 5) / 8 + 1;
    if(y < p)  /* pass 2 */
        return y * 8 + 4;
    y -= p;
    p = (h - 3) / 4 + 1;
    if(y < p)  /* pass 3 */
        return y * 4 + 2;
    y -= p;
    /* pass 4 */
    return y * 2 + 1;
}

/* Decompress image pixels.
 * Return 0 on success or -1 on out-of-memory (w.r.t. LZW code table) or parse error. */
static int
read_image_data(gd_GIF * gif, int interlace)
{
    uint8_t sub_len, shift, byte;
    int init_key_size, key_size, table_is_full = 0;
    int frm_off, frm_size, str_len = 0, i, p, x, y;
    uint16_t key, clear, stop;
    int ret;
    Table * table;
    Entry entry = {0};
    size_t start, end;

    f_gif_read(gif, &byte, 1);
    key_size = (int) byte;
    start = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
    discard_sub_blocks(gif);
    end = f_gif_seek(gif, 0, LV_FS_SEEK_CUR);
    f_gif_seek(gif, start, LV_FS_SEEK_SET);
    clear = 1 << key_size;
    stop = clear + 1;
    table = new_table(key_size);
    key_size++;
    init_key_size = key_size;
    sub_len = shift = 0;
    key = get_key(gif, key_size, &sub_len, &shift, &byte); /* clear code */
    frm_off = 0;
    ret = 0;
    frm_size = gif->fw * gif->fh;
    while(frm_off < frm_size) {
        if(key == clear) {
            key_size = init_key_size;
            table->nentries = (1 << (key_size - 1)) + 2;
            table_is_full = 0;
        }
        else if(!table_is_full) {
            ret = add_entry(&table, str_len + 1, key, entry.suffix);
            if(ret == -1) {
                lv_free(table);
                return -1;
            }
            if(table->nentries == 0x1000) {
                ret = 0;
                table_is_full = 1;
            }
        }
        key = get_key(gif, key_size, &sub_len, &shift, &byte);
        if(key == clear) continue;
        if(key == stop || key == 0x1000) break;
        if(ret == 1) key_size++;
        entry = table->entries[key];
        str_len = entry.length;
        /* 越界保护：frm_off + str_len == frm_size 是正常的最后一帧，不应拒绝。
         * 只有 > 才是真正的溢出。溢出时截断而非返回 -1，避免 GIF 播放中断。 */
        if(frm_off + str_len > frm_size) {
            ESP_LOGW("gifdec", "LZW overflow: frm_off=%d str_len=%d frm_size=%d (truncating)",
                     frm_off, str_len, frm_size);
            str_len = frm_size - frm_off;
            if(str_len <= 0) break;
        }
        for(i = 0; i < str_len; i++) {
            p = frm_off + str_len - 1 - i;
            x = p % gif->fw;
            y = p / gif->fw;
            if(interlace)
                y = interlaced_line_index((int) gif->fh, y);
            int frame_idx = (gif->fy + y) * gif->width + gif->fx + x;
            if(frame_idx >= 0 && frame_idx < gif->width * gif->height) {
                gif->frame[frame_idx] = entry.suffix;
            }
            if(entry.prefix == 0xFFF)
                break;
            else
                entry = table->entries[entry.prefix];
        }
        frm_off += str_len;
        if(key < table->nentries - 1 && !table_is_full)
            table->entries[table->nentries - 1].suffix = entry.suffix;
    }
    lv_free(table);
    if(key == stop) f_gif_read(gif, &sub_len, 1);  /* Must be zero! */
    f_gif_seek(gif, end, LV_FS_SEEK_SET);
    return 0;
}

#endif

/* Read image.
 * Return 0 on success or -1 on out-of-memory (w.r.t. LZW code table) or parse error. */
static int
read_image(gd_GIF * gif)
{
    uint8_t fisrz;
    int interlace;

    /* Image Descriptor. */
    gif->fx = read_num(gif);
    gif->fy = read_num(gif);
    gif->fw = read_num(gif);
    gif->fh = read_num(gif);
    if(gif->fx + (uint32_t)gif->fw > gif->width || gif->fy + (uint32_t)gif->fh > gif->height){
        LV_LOG_WARN("Frame coordinates out of image bounds");
        return -1;
    }
    f_gif_read(gif, &fisrz, 1);
    interlace = fisrz & 0x40;
    /* Ignore Sort Flag. */
    /* Local Color Table? */
    if(fisrz & 0x80) {
        /* Read LCT */
        gif->lct.size = 1 << ((fisrz & 0x07) + 1);
        f_gif_read(gif, gif->lct.colors, 3 * gif->lct.size);
        gif->palette = &gif->lct;
    }
    else
        gif->palette = &gif->gct;
    /* Image Data. */
    return read_image_data(gif, interlace);
}

static void
render_frame_rect(gd_GIF * gif, uint8_t * buffer)
{
    LV_UNUSED(buffer);
    if(gif == NULL) return;
    /* gd_GIF 结构体现在分配在内部 RAM，所有字段（palette/width/height/canvas/frame）
     * 均不会被 PSRAM 缓冲区溢出篡改。可直接使用，无需 &gif[1] 技巧或指针验证。 */
    if(gif->width == 0 || gif->height == 0 || gif->width > 4096 || gif->height > 4096) return;
    if(gif->canvas == NULL || gif->frame == NULL) return;
    if(gif->palette == NULL) return;
    /* palette 只可能指向 &gif->gct 或 &gif->lct，均在内部 RAM 中 */
    if(gif->palette != &gif->gct && gif->palette != &gif->lct) {
        gif->palette = &gif->gct;
    }

    int total = (int)gif->width * gif->height;
    uint8_t *color_plane = gif->canvas;
    uint8_t *alpha_plane = gif->canvas + (size_t)total * 2;

    /* 帧矩形边界检查 */
    if(gif->fw == 0 || gif->fh == 0) return;
    if((uint32_t)gif->fx + gif->fw > gif->width) return;
    if((uint32_t)gif->fy + gif->fh > gif->height) return;
    int i = gif->fy * gif->width + gif->fx;
    int j, k;
    uint8_t index, * color;

    for(j = 0; j < gif->fh; j++) {
        for(k = 0; k < gif->fw; k++) {
            int write_idx = i + k;
            if(write_idx < 0 || write_idx >= total) break;
            index = gif->frame[write_idx];
            if(index >= gif->palette->size) continue;
            color = &gif->palette->colors[index * 3];
            if(!gif->gce.transparency || index != gif->gce.tindex) {
                uint16_t c565 = ((*(color + 0) & 0xF8) << 8) | ((*(color + 1) & 0xFC) << 3) | (*(color + 2) >> 3);
                color_plane[write_idx * 2 + 0] = c565 & 0xff;
                color_plane[write_idx * 2 + 1] = (c565 >> 8) & 0xff;
                alpha_plane[write_idx] = 0xff;
            }
        }
        i += gif->width;
    }
}

static void
dispose(gd_GIF * gif)
{
    int i;
    uint8_t * bgcolor;
    /* gd_GIF 结构体在内部 RAM，canvas/frame/palette 指针均安全，无需验证 */
    if(gif == NULL || gif->width == 0 || gif->height == 0 || gif->canvas == NULL) return;
    int total = (int)gif->width * gif->height;

    uint8_t *color_plane = gif->canvas;
    uint8_t *alpha_plane = gif->canvas + (size_t)total * 2;

    switch(gif->gce.disposal) {
        case 2: /* Restore to background color. */
            if(gif->palette != &gif->gct && gif->palette != &gif->lct) break;
            /* 帧矩形边界检查 */
            if(gif->fw == 0 || gif->fh == 0) break;
            if((uint32_t)gif->fx + gif->fw > gif->width) break;
            if((uint32_t)gif->fy + gif->fh > gif->height) break;
            bgcolor = &gif->palette->colors[gif->bgindex * 3];

            uint8_t opa = 0xff;
            if(gif->gce.transparency) opa = 0x00;

            uint16_t bg565 = ((*(bgcolor + 0) & 0xF8) << 8) | ((*(bgcolor + 1) & 0xFC) << 3) | (*(bgcolor + 2) >> 3);
            i = gif->fy * gif->width + gif->fx;
            {
                int j, k;
                for(j = 0; j < gif->fh; j++) {
                    for(k = 0; k < gif->fw; k++) {
                        int write_idx = i + k;
                        if(write_idx < 0 || write_idx >= total) break;
                        color_plane[write_idx * 2 + 0] = bg565 & 0xff;
                        color_plane[write_idx * 2 + 1] = (bg565 >> 8) & 0xff;
                        alpha_plane[write_idx] = opa;
                    }
                    i += gif->width;
                }
            }
            break;
        case 3: /* Restore to previous, i.e., don't update canvas.*/
            break;
        default:
            /* Add frame non-transparent pixels to canvas. */
            render_frame_rect(gif, gif->canvas);
    }
}

/* Return 1 if got a frame; 0 if got GIF trailer; -1 if error. */
int
gd_get_frame(gd_GIF * gif)
{
    char sep;

    /* 读位置越界检测：f_rw_p 超过数据范围时重置到 anim_start */
    if(gif->data_size > 0 && gif->f_rw_p >= gif->data_size) {
        printf("[gifdec] f_rw_p=%u >= data_size=%u, rewinding to anim_start=%d\n",
               (unsigned)gif->f_rw_p, (unsigned)gif->data_size, (int)gif->anim_start);
        f_gif_seek(gif, gif->anim_start, LV_FS_SEEK_SET);
    }

    dispose(gif);
    f_gif_read(gif, &sep, 1);
    while(sep != ',') {
        if(sep == ';') {
            f_gif_seek(gif, gif->anim_start, LV_FS_SEEK_SET);
            if(gif->loop_count == 1 || gif->loop_count < 0) {
                return 0;
            }
            else if(gif->loop_count > 1) {
                gif->loop_count--;
            }
        }
        else if(sep == '!')
            read_ext(gif);
        else {
            /* 未知分隔符：可能是数据腐败，尝试 rewind 恢复 */
            printf("[gifdec] unknown sep=0x%02x at pos=%u, rewinding\n",
                   (unsigned char)sep, (unsigned)gif->f_rw_p);
            f_gif_seek(gif, gif->anim_start, LV_FS_SEEK_SET);
            return -1;
        }
        f_gif_read(gif, &sep, 1);
    }
    if(read_image(gif) == -1)
        return -1;
    return 1;
}

void
gd_render_frame(gd_GIF * gif, uint8_t * buffer)
{
    render_frame_rect(gif, buffer);
}

void
gd_rewind(gd_GIF * gif)
{
    gif->loop_count = -1;
    f_gif_seek(gif, gif->anim_start, LV_FS_SEEK_SET);
}

void
gd_close_gif(gd_GIF * gif)
{
    if(gif == NULL) return;
    f_gif_close(gif);
    /* 先释放 PSRAM 画布，再释放内部 RAM 结构体 */
    if(gif->canvas_alloc) {
        heap_caps_free(gif->canvas_alloc);
        gif->canvas_alloc = NULL;
    }
    heap_caps_free(gif);
}

static bool f_gif_open(gd_GIF * gif, const void * path, bool is_file)
{
    gif->f_rw_p = 0;
    gif->data = NULL;
    gif->is_file = is_file;

    if(is_file) {
        lv_fs_res_t res = lv_fs_open(&gif->fd, path, LV_FS_MODE_RD);
        if(res != LV_FS_RES_OK) return false;
        else return true;
    }
    else {
        gif->data = path;
        return true;
    }
}

static void f_gif_read(gd_GIF * gif, void * buf, size_t len)
{
    if(gif->is_file) {
        lv_fs_read(&gif->fd, buf, len, NULL);
    }
    else {
        /* 越界保护：防止 f_rw_p 超出数据范围导致读取 flash 垃圾数据 */
        if(gif->data_size > 0 && gif->f_rw_p + len > gif->data_size) {
            /* 读取超出范围，用 0 填充并钳制位置 */
            size_t avail = (gif->f_rw_p < gif->data_size) ? (gif->data_size - gif->f_rw_p) : 0;
            if(avail > 0) {
                memcpy(buf, &gif->data[gif->f_rw_p], avail);
                memset((uint8_t *)buf + avail, 0, len - avail);
            } else {
                memset(buf, 0, len);
            }
            gif->f_rw_p = gif->data_size;  /* 钳制到末尾 */
        } else {
            memcpy(buf, &gif->data[gif->f_rw_p], len);
            gif->f_rw_p += len;
        }
    }
}

static int f_gif_seek(gd_GIF * gif, size_t pos, int k)
{
    if(gif->is_file) {
        lv_fs_seek(&gif->fd, pos, k);
        uint32_t x;
        lv_fs_tell(&gif->fd, &x);
        return x;
    }
    else {
        if(k == LV_FS_SEEK_CUR) gif->f_rw_p += pos;
        else if(k == LV_FS_SEEK_SET) gif->f_rw_p = pos;
        return gif->f_rw_p;
    }
}

static void f_gif_close(gd_GIF * gif)
{
    if(gif->is_file) {
        lv_fs_close(&gif->fd);
    }
}

#endif /*LV_USE_GIF*/
