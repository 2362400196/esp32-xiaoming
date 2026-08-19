/**
 * lua_module_gpio.c — Lua GPIO 模块
 * 
 * Lua 用法:
 *   local gpio = require("gpio")
 *   gpio.mode(2, "output")   -- 设置 GPIO2 为输出
 *   gpio.write(2, 1)          -- GPIO2 输出高电平
 *   gpio.write(2, 0)          -- GPIO2 输出低电平
 *   gpio.mode(4, "input")    -- 设置 GPIO4 为输入
 *   local val = gpio.read(4) -- 读取 GPIO4 电平
 */
#include "lua_module_gpio.h"
#include <string.h>
#include "lauxlib.h"
#include "driver/gpio.h"

static int l_gpio_mode(lua_State *L)
{
    gpio_num_t pin = (gpio_num_t)luaL_checkinteger(L, 1);
    const char *mode_str = luaL_checkstring(L, 2);
    gpio_mode_t mode;

    if (strcmp(mode_str, "output") == 0) {
        mode = GPIO_MODE_OUTPUT;
    } else if (strcmp(mode_str, "input") == 0) {
        mode = GPIO_MODE_INPUT;
    } else if (strcmp(mode_str, "input_pullup") == 0) {
        mode = GPIO_MODE_INPUT;
        gpio_set_pull_mode(pin, GPIO_PULLUP_ONLY);
    } else {
        return luaL_error(L, "invalid gpio mode: %s (use output/input/input_pullup)", mode_str);
    }

    gpio_set_direction(pin, mode);
    return 0;
}

static int l_gpio_write(lua_State *L)
{
    gpio_num_t pin = (gpio_num_t)luaL_checkinteger(L, 1);
    int level = lua_toboolean(L, 2) ? 1 : 0;
    gpio_set_level(pin, level);
    return 0;
}

static int l_gpio_read(lua_State *L)
{
    gpio_num_t pin = (gpio_num_t)luaL_checkinteger(L, 1);
    lua_pushinteger(L, gpio_get_level(pin));
    return 1;
}

int luaopen_gpio(lua_State *L)
{
    static const luaL_Reg funcs[] = {
        {"mode",  l_gpio_mode},
        {"write", l_gpio_write},
        {"read",  l_gpio_read},
        {NULL, NULL}
    };

    lua_newtable(L);
    luaL_setfuncs(L, funcs, 0);
    return 1;
}
