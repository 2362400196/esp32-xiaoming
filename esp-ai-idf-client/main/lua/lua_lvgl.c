/**
 * lua_lvgl.c — LVGL 8.4 Lua binding（完整 userdata + 类型检查）
 *
 * 从 esp-claw lua_module_lvgl 借鉴设计思路：
 *   - 使用 lua_newuserdata + metatable 替代 lua_pushlightuserdata
 *   - 所有操作函数通过 luaL_checkudata 做类型验证
 *   - 传错类型时抛 Lua 错误而非崩溃
 *   - 所有 LVGL 操作都通过 eeui_port_lvgl_lock/unlock 加锁保护
 *   - 创建的容器对象默认全屏白色背景，覆盖整个屏幕
 */
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
#include "lvgl.h"
#include "esp_task_wdt.h"
#include "esp_log.h"
#include "eeui_port.h"
#include "config.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

/* 固件内置中文字体（16px，来自 fonts/font_puhui_16_4.c），
 * 供 lv.set_style_text_font(obj, "puhui") 使用——Lua 脚本默认字体无中文字符集 */
extern const lv_font_t font_puhui_16_4;

/* 元表名称（用于类型检查） */
#define LVGL_UD_MT "lvgl.obj"

/* Lua 脚本执行标志：执行中禁止 lua_lvgl_reset 清理对象（竞态保护） */
static volatile int s_lua_executing = 0;

void lua_lvgl_set_executing(bool executing)
{
    s_lua_executing = executing ? 1 : 0;
}

/* LVGL 锁保护宏：自动加锁/解锁，获取失败时跳过操作 */
#define LVGL_LOCK()   eeui_port_lvgl_lock(2000)
#define LVGL_UNLOCK() eeui_port_lvgl_unlock()

/* 跟踪所有 Lua 创建的 LVGL 对象，用于清理 */
#define MAX_LUA_OBJS 256
static lv_obj_t *s_lua_objects[MAX_LUA_OBJS];
static int s_lua_object_count = 0;

/* 注册一个 Lua 创建的 LVGL 对象 */
void lua_lvgl_track_obj(lv_obj_t *obj)
{
    if (obj && s_lua_object_count < MAX_LUA_OBJS) {
        s_lua_objects[s_lua_object_count++] = obj;
    }
}

/* 从跟踪数组中移除已删除的对象（l_obj_del 调用） */
void lua_lvgl_untrack_obj(lv_obj_t *obj)
{
    for (int i = 0; i < s_lua_object_count; i++) {
        if (s_lua_objects[i] == obj) {
            s_lua_objects[i] = NULL;
            break;
        }
    }
}

/* 删除所有 Lua 创建的 LVGL 对象，恢复屏幕 */
void lua_lvgl_reset(void)
{
    static const char *TAG = "lua_lvgl";

    // 竞态保护：Lua 脚本执行中不清理（脚本可能在操作刚创建的对象），
    // 由调用方（lua_commands.c）在执行前后置位
    if (s_lua_executing) {
        ESP_LOGI(TAG, "Lua 脚本执行中，跳过对象清理");
        return;
    }

    if (s_lua_object_count == 0) {
        ESP_LOGD(TAG, "无 Lua 对象需要清理");
        return;
    }

    ESP_LOGI(TAG, "开始清理 %d 个 Lua LVGL 对象", s_lua_object_count);

    if (!LVGL_LOCK()) {
        ESP_LOGW(TAG, "LVGL 锁获取失败（2s 超时），无法清理对象");
        return;
    }

    int deleted = 0;
    for (int i = 0; i < s_lua_object_count; i++) {
        if (s_lua_objects[i] && lv_obj_is_valid(s_lua_objects[i])) {
            lv_obj_del(s_lua_objects[i]);
            deleted++;
        }
        s_lua_objects[i] = NULL;
        /* 每删 5 个对象喂一次狗 */
        if (i > 0 && i % 5 == 0) {
            esp_task_wdt_reset();
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
    s_lua_object_count = 0;

    /* 刷新屏幕，恢复 EEUI 底层显示 */
    lv_obj_invalidate(lv_scr_act());

    LVGL_UNLOCK();

    ESP_LOGI(TAG, "已删除 %d 个对象，恢复 EEUI 显示", deleted);

    /* 强制恢复 EEUI 表情和状态显示 */
    vTaskDelay(pdMS_TO_TICKS(50));
    display_show_emotion("休息中");
    display_show_status("等待唤醒...");
}

/* ==================== 工具函数 ==================== */

static lv_obj_t *lvgl_check_obj(lua_State *L, int index)
{
    void *ud = luaL_checkudata(L, index, LVGL_UD_MT);
    return *(lv_obj_t **)ud;
}

static void lvgl_push_obj(lua_State *L, lv_obj_t *obj)
{
    lv_obj_t **ud = (lv_obj_t **)lua_newuserdata(L, sizeof(lv_obj_t *));
    *ud = obj;
    luaL_setmetatable(L, LVGL_UD_MT);
}

/* 从 {r,g,b} table 提取 lv_color_t */
static lv_color_t lvgl_check_color(lua_State *L, int index)
{
    if (!lua_istable(L, index)) {
        return lv_color_make(0, 0, 0);
    }
    lua_rawgeti(L, index, 1); uint8_t r = (uint8_t)lua_tointeger(L, -1); lua_pop(L, 1);
    lua_rawgeti(L, index, 2); uint8_t g = (uint8_t)lua_tointeger(L, -1); lua_pop(L, 1);
    lua_rawgeti(L, index, 3); uint8_t b = (uint8_t)lua_tointeger(L, -1); lua_pop(L, 1);
    return lv_color_make(r, g, b);
}

/* ==================== 运行时函数 ==================== */

static int l_scr_act(lua_State *L)
{
    lvgl_push_obj(L, lv_scr_act());
    return 1;
}

static int l_scr_load(lua_State *L)
{
    lv_obj_t *scr = lvgl_check_obj(L, 1);
    if (LVGL_LOCK()) {
        lv_scr_load(scr);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_disp_hor_res(lua_State *L)
{
    lua_pushinteger(L, lv_disp_get_hor_res(NULL));
    return 1;
}

static int l_disp_ver_res(lua_State *L)
{
    lua_pushinteger(L, lv_disp_get_ver_res(NULL));
    return 1;
}

/* ==================== 对象操作 ==================== */

static int l_obj_create(lua_State *L)
{
    lv_obj_t *parent;
    if (lua_isnoneornil(L, 1)) {
        parent = lv_scr_act();
    } else {
        parent = lvgl_check_obj(L, 1);
    }

    lv_obj_t *obj = NULL;
    if (LVGL_LOCK()) {
        obj = lv_obj_create(parent);
        if (obj) {
            /* 全屏白色背景，覆盖整个屏幕 */
            lv_coord_t w = lv_disp_get_hor_res(NULL);
            lv_coord_t h = lv_disp_get_ver_res(NULL);
            lv_obj_set_size(obj, w, h);
            lv_obj_set_pos(obj, 0, 0);
            lv_obj_set_style_bg_color(obj, lv_color_white(), 0);
            lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(obj, 0, 0);
            lv_obj_set_style_radius(obj, 0, 0);
            lv_obj_set_style_pad_all(obj, 0, 0);
            lv_obj_clear_flag(obj, LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_move_foreground(obj);
        }
        LVGL_UNLOCK();
    }

    if (!obj) {
        lua_pushnil(L);
        return 1;
    }
    lua_lvgl_track_obj(obj);
    lvgl_push_obj(L, obj);
    return 1;
}

static int l_obj_del(lua_State *L)
{
    lvgl_check_obj(L, 1);
    lv_obj_t *obj = *(lv_obj_t **)lua_touserdata(L, 1);
    if (obj) {
        if (LVGL_LOCK()) {
            if (lv_obj_is_valid(obj)) {
                lv_obj_del(obj);
            }
            LVGL_UNLOCK();
        }
        lua_lvgl_untrack_obj(obj);
        *(lv_obj_t **)lua_touserdata(L, 1) = NULL;
    }
    return 0;
}

/* obj_clean 已移除 — 清屏会误删 EEUI 内部控件导致崩溃 */
/* 如需清理，使用 obj_del 逐个删除自己创建的对象 */

static int l_obj_set_pos(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t x = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_coord_t y = (lv_coord_t)luaL_checkinteger(L, 3);
    if (LVGL_LOCK()) {
        lv_obj_set_pos(obj, x, y);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_obj_set_size(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t w = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_coord_t h = (lv_coord_t)luaL_checkinteger(L, 3);
    if (LVGL_LOCK()) {
        lv_obj_set_size(obj, w, h);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_obj_set_width(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t w = (lv_coord_t)luaL_checkinteger(L, 2);
    if (LVGL_LOCK()) {
        lv_obj_set_width(obj, w);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_obj_set_height(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t h = (lv_coord_t)luaL_checkinteger(L, 2);
    if (LVGL_LOCK()) {
        lv_obj_set_height(obj, h);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_obj_center(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    if (LVGL_LOCK()) {
        lv_obj_center(obj);
        LVGL_UNLOCK();
    }
    return 0;
}

/* ==================== 样式 ==================== */

static int l_set_style_bg_color(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_color_t color = lvgl_check_color(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_bg_color(obj, color, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_radius(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t radius = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_radius(obj, radius, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_border_width(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t w = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_border_width(obj, w, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_border_color(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_color_t color = lvgl_check_color(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_border_color(obj, color, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_text_color(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_color_t color = lvgl_check_color(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_text_color(obj, color, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

/* 设置文本字体：lv.set_style_text_font(obj, "puhui") 使用固件内置中文字体，
 * 其他名称/空值使用默认字体（ASCII）。解决 Lua 脚本无法显示中文的问题。 */
static int l_set_style_text_font(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    const char *font_name = luaL_optstring(L, 2, "default");
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    const lv_font_t *font = LV_FONT_DEFAULT;
    if (font_name && strcmp(font_name, "puhui") == 0) {
        font = &font_puhui_16_4;   /* 固件内置中文字体（16px） */
    }
    if (LVGL_LOCK()) {
        lv_obj_set_style_text_font(obj, font, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_bg_opa(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_opa_t opa = (lv_opa_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_bg_opa(obj, opa, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_pad_all(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t pad = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_pad_all(obj, pad, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_line_width(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_coord_t w = (lv_coord_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_line_width(obj, w, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_line_color(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_color_t color = lvgl_check_color(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_line_color(obj, color, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_line_rounded(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    bool rounded = lua_toboolean(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_line_rounded(obj, rounded, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_set_style_text_align(lua_State *L)
{
    lv_obj_t *obj = lvgl_check_obj(L, 1);
    lv_text_align_t align = (lv_text_align_t)luaL_checkinteger(L, 2);
    lv_style_selector_t sel = (lv_style_selector_t)luaL_optinteger(L, 3, 0);
    if (LVGL_LOCK()) {
        lv_obj_set_style_text_align(obj, align, sel);
        LVGL_UNLOCK();
    }
    return 0;
}

/* ==================== 控件 ==================== */

static int l_label_create(lua_State *L)
{
    lv_obj_t *parent = lua_isnoneornil(L, 1) ? lv_scr_act() : lvgl_check_obj(L, 1);
    lv_obj_t *obj = NULL;
    if (LVGL_LOCK()) {
        obj = lv_label_create(parent);
        LVGL_UNLOCK();
    }
    if (!obj) { lua_pushnil(L); return 1; }
    lua_lvgl_track_obj(obj);
    lvgl_push_obj(L, obj);
    return 1;
}

static int l_label_set_text(lua_State *L)
{
    lv_obj_t *label = lvgl_check_obj(L, 1);
    const char *text = luaL_checkstring(L, 2);
    if (LVGL_LOCK()) {
        lv_label_set_text(label, text);
        LVGL_UNLOCK();
    }
    return 0;
}

static int l_btn_create(lua_State *L)
{
    lv_obj_t *parent = lua_isnoneornil(L, 1) ? lv_scr_act() : lvgl_check_obj(L, 1);
    lv_obj_t *obj = NULL;
    if (LVGL_LOCK()) {
        obj = lv_btn_create(parent);
        LVGL_UNLOCK();
    }
    if (!obj) { lua_pushnil(L); return 1; }
    lua_lvgl_track_obj(obj);
    lvgl_push_obj(L, obj);
    return 1;
}

/* ==================== 画线 ==================== */

static int l_line_create(lua_State *L)
{
    lv_obj_t *parent = lua_isnoneornil(L, 1) ? lv_scr_act() : lvgl_check_obj(L, 1);
    lv_obj_t *obj = NULL;
    if (LVGL_LOCK()) {
        obj = lv_line_create(parent);
        LVGL_UNLOCK();
    }
    if (!obj) { lua_pushnil(L); return 1; }
    lua_lvgl_track_obj(obj);
    lvgl_push_obj(L, obj);
    return 1;
}

static int l_line_set_points(lua_State *L)
{
    lv_obj_t *line = lvgl_check_obj(L, 1);
    if (!lua_istable(L, 2)) return 0;

    int n = (int)lua_rawlen(L, 2);
    if (n < 2) return 0;

    lv_point_precise_t *points = (lv_point_precise_t *)malloc(n * sizeof(lv_point_precise_t));
    if (!points) return luaL_error(L, "out of memory");

    for (int i = 1; i <= n; i++) {
        lua_rawgeti(L, 2, i);
        if (lua_istable(L, -1)) {
            /* 支持两种格式：
             *   {x=40, y=100}  — 命名索引（推荐）
             *   {40, 100}      — 数字索引（兼容） */
            lua_getfield(L, -1, "x");
            if (lua_isnil(L, -1)) {
                lua_pop(L, 1);
                lua_rawgeti(L, -1, 1);
            }
            points[i-1].x = (lv_coord_t)lua_tointeger(L, -1);
            lua_pop(L, 1);

            lua_getfield(L, -1, "y");
            if (lua_isnil(L, -1)) {
                lua_pop(L, 1);
                lua_rawgeti(L, -1, 2);
            }
            points[i-1].y = (lv_coord_t)lua_tointeger(L, -1);
            lua_pop(L, 1);
        }
        lua_pop(L, 1);
    }

    if (LVGL_LOCK()) {
        lv_line_set_points(line, points, n);
        LVGL_UNLOCK();
    }
    free(points);
    return 0;
}

/* ==================== 颜色 ==================== */

static int l_color_make(lua_State *L)
{
    uint8_t r = (uint8_t)luaL_checkinteger(L, 1);
    uint8_t g = (uint8_t)luaL_checkinteger(L, 2);
    uint8_t b = (uint8_t)luaL_checkinteger(L, 3);
    lua_createtable(L, 3, 0);
    lua_pushinteger(L, r); lua_rawseti(L, -2, 1);
    lua_pushinteger(L, g); lua_rawseti(L, -2, 2);
    lua_pushinteger(L, b); lua_rawseti(L, -2, 3);
    return 1;
}

static int l_color_hex(lua_State *L)
{
    uint32_t hex = (uint32_t)luaL_checkinteger(L, 1);
    /* lv_color_hex 接受 0xRRGGBB 格式，直接拆解 */
    uint8_t r = (hex >> 16) & 0xFF;
    uint8_t g = (hex >> 8) & 0xFF;
    uint8_t b = hex & 0xFF;
    lua_createtable(L, 3, 0);
    lua_pushinteger(L, r); lua_rawseti(L, -2, 1);
    lua_pushinteger(L, g); lua_rawseti(L, -2, 2);
    lua_pushinteger(L, b); lua_rawseti(L, -2, 3);
    return 1;
}

/* ==================== 模块注册 ==================== */

static const struct luaL_Reg lvgl_funcs[] = {
    /* 运行时 */
    {"scr_act", l_scr_act},
    {"scr_load", l_scr_load},
    {"disp_hor_res", l_disp_hor_res},
    {"disp_ver_res", l_disp_ver_res},
    /* 对象 */
    {"obj_create", l_obj_create},
    {"obj", l_obj_create},
    {"obj_del", l_obj_del},
    {"obj_set_pos", l_obj_set_pos},
    {"obj_set_size", l_obj_set_size},
    {"obj_set_width", l_obj_set_width},
    {"obj_set_height", l_obj_set_height},
    {"obj_center", l_obj_center},
    /* 样式 */
    {"set_style_bg_color", l_set_style_bg_color},
    {"set_style_radius", l_set_style_radius},
    {"set_style_border_width", l_set_style_border_width},
    {"set_style_border_color", l_set_style_border_color},
    {"set_style_text_color", l_set_style_text_color},
    {"set_style_text_font", l_set_style_text_font},
    {"set_style_bg_opa", l_set_style_bg_opa},
    {"set_style_pad_all", l_set_style_pad_all},
    {"set_style_line_width", l_set_style_line_width},
    {"set_style_line_color", l_set_style_line_color},
    {"set_style_line_rounded", l_set_style_line_rounded},
    {"set_style_text_align", l_set_style_text_align},
    /* 控件 */
    {"label_create", l_label_create},
    {"label", l_label_create},
    {"label_set_text", l_label_set_text},
    {"btn_create", l_btn_create},
    {"btn", l_btn_create},
    /* 画线 */
    {"line_create", l_line_create},
    {"line", l_line_create},
    {"line_set_points", l_line_set_points},
    /* 颜色 */
    {"color_make", l_color_make},
    {"color_hex", l_color_hex},
    {NULL, NULL}
};

int luaopen_lvgl(lua_State *L)
{
    /* 创建元表 "lvgl.obj" */
    luaL_newmetatable(L, LVGL_UD_MT);
    /* 元表.__index = 自身（让 userdata.method 语法可用，暂不实现） */
    lua_pushvalue(L, -1);
    lua_setfield(L, -2, "__index");
    lua_pop(L, 1);

    /* 创建模块表 */
    lua_newtable(L);
    luaL_setfuncs(L, lvgl_funcs, 0);

    /* 常量 */
    lua_pushinteger(L, LV_TEXT_ALIGN_LEFT);   lua_setfield(L, -2, "LEFT");
    lua_pushinteger(L, LV_TEXT_ALIGN_CENTER); lua_setfield(L, -2, "CENTER");
    lua_pushinteger(L, LV_TEXT_ALIGN_RIGHT);  lua_setfield(L, -2, "RIGHT");

    return 1;
}
