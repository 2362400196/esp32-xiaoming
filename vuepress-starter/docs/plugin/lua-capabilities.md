# 设备端 Lua 能力

固件内置了一个 **Lua 5.4 解释器**（`esp-ai-idf-client/main/lua/`），插件可以通过 `lua_execute` 把脚本下发到设备执行，读取传感器、控制 GPIO、驱动 LED 灯带、操作屏幕（LVGL）等。本文档是设备端 Lua 运行时的**能力清单**，与 [插件 SDK](./plugin-sdk.md) 中的 `lua_execute` 配套使用。

::: tip 与 SDK 设备 IO 的关系
插件 SDK 里的 `gpio_read()` / `adc_read()` 等读操作，底层就是通过 `execute_lua` 在设备端执行 Lua 实现的。需要更灵活的硬件操作（如传感器时序、组合读写）时，可以直接写 Lua 脚本。
:::

---

## 一、执行机制

### `lua_execute(tool_manager, code, timeout=8.0)`

插件把 Lua 脚本作为字符串下发，设备执行后把 **`print` 输出**回传：

```python
from src.use_cases.sdk.device import lua_execute

result, status, detail = await lua_execute(tool_manager, "return gpio.read(20)", timeout=5.0)
if status == "ok":
    print(f"设备返回: {result}")
```

返回三元组 `(result, status, detail)`，`status` 取值 `ok / offline / timeout / error / busy`。

### print 输出捕获

脚本里的 `print()` 输出会被捕获并作为 `result` 返回：

- **多个参数**用 `\t`（tab）分隔：`print(1, 2)` → `"1\t2"`
- **字符串拼接**推荐用 `string.format` 或 `..`，避免 tab 分隔符干扰解析
- 脚本**没有输出**时返回 `"Lua completed with no output."`
- 输出超长会被截断并追加 `[output truncated]`

### 超时限制（重要）

- 设备端有 **3 秒硬超时**：脚本执行超过 3 秒会被强制终止（`execution exceeded 3s limit`）
- 服务端 `timeout` 参数默认 8 秒，是等待设备回传的超时
- 需要等待的硬件操作（如 DHT11 读取、`delay.delay_ms`）注意控制总时长，避免触发 3 秒限制

### 错误处理

脚本报错时，`result` 会包含错误信息：

- 编译/运行错误 → `result` 以 `[Lua Error]` 或 `ERROR: <msg>` 开头
- 插件侧建议先判断 `status != "ok"`，再检查 `result` 是否以错误标记开头

```python
result, status, detail = await lua_execute(tool_manager, code, timeout=5.0)
if status != "ok":
    return f"执行失败: {detail}"
if (result or "").startswith("[Lua Error]"):
    return f"脚本错误: {result}"
```

### `args` 全局变量

设备端 Lua 解释器提供全局 `args` 表（当前为空 table），供脚本读取外部传入的 JSON 参数（`execute_lua_file` 场景使用）。

---

## 二、可用模块总览

固件启动时注册以下 **20 个模块**（`lua_commands.c` 的 `register_lua_modules`）：

| 模块 | `require` 名 | 能力 |
|------|-------------|------|
| 延时 | `delay` | 毫秒/微秒延时 |
| 系统 | `system` | 运行时间、内存、芯片信息、重启、NVS 读写 |
| JSON | `json` | 编解码 |
| GPIO | `gpio` | 数字引脚读写 |
| LED 灯带 | `led` | WS2812/NeoPixel 灯带（RMT） |
| 屏幕 | `lvgl` | LVGL 对象、样式、控件（标签/按钮/画线） |
| 环境传感器 | `environmental_sensor` | DHT11/DHT22 温湿度读取 |
| 模数转换 | `adc` | ADC 引脚电压采样（mV） |
| LED PWM | `ledc` | 任意引脚 PWM 输出（调光/舵机/蜂鸣器） |
| 文件存储 | `storage` | SPIFFS 文件读写、目录、空间查询 |
| I2C 总线 | `i2c` | I2C 主机总线扫描、读写从设备 |
| 按键 | `button` | GPIO 按键事件（单击/双击/长按等） |
| 串口 | `uart` | UART 串口读写（接串口传感器/GPS/蓝牙模块） |
| 脉冲计数 | `pcnt` | 脉冲计数（流量计、编码器测速） |
| RMT 驱动 | `rmt` | RMT 底层收发（红外/自定义时序） |
| HTTP 服务器 | `http` | 设备端 HTTP 服务器（本地配置页） |
| SCI 显示屏 | `sci` | 基于 I2C 的 SCI 协议显示屏 |
| 多线程 | `thread` | Lua 线程任务与同步原语 |
| 触摸 | `touch` | 电容触摸按键（S3 支持） |
| 电机 PWM | `mcpwm` | MCPWM 电机控制（舵机/直流/无刷） |

::: warning 源码里还有模块文件，但未注册
`main/lua/modules/` 下还有 `display`、`ir`、`knob` 三个模块文件未注册，`require` 会报 `module not found`：
- `display`：底层画图，依赖项目内缺失的 `display_service.h` / `lua_image.h`，且与 `lvgl` 功能重叠
- `ir`：红外收发，依赖 `espressif/ir_encoder` 与 `esp-board-manager` 组件
- `knob`：旋转编码器，依赖 `espressif/knob` 组件

如需使用需先补齐依赖并在固件 `register_lua_modules` 中注册。
:::

---

## 三、模块详解

### 1. `delay` — 延时

```lua
local delay = require("delay")
delay.delay_ms(1000)   -- 延时 1 秒
delay.delay_us(500)    -- 延时 500 微秒
```

| 函数 | 说明 |
|------|------|
| `delay.delay_ms(ms)` | 延时毫秒 |
| `delay.delay_us(us)` | 延时微秒，仅支持 0~1000000（超过会报错，请用 `delay_ms`） |

### 2. `system` — 系统信息

```lua
local sys = require("system")
print(sys.millis())       -- 运行毫秒数
print(sys.free_heap())    -- 剩余堆内存（字节）
print(sys.chip_info())    -- 芯片信息字符串
```

| 函数 | 说明 |
|------|------|
| `sys.millis()` | 开机运行毫秒数 |
| `sys.micros()` | 开机运行微秒数 |
| `sys.free_heap()` | 剩余堆内存（字节） |
| `sys.free_psram()` | 剩余 PSRAM 大小（字节），不支持时返回 0 |
| `sys.chip_info()` | 芯片信息字符串（型号、版本、核心数、WiFi/BLE） |
| `sys.restart()` | 重启设备 |
| `sys.read_nvs(key)` | 读取 NVS 字符串（命名空间 `esp-ai-kv`），不存在返回 `nil` |
| `sys.write_nvs(key, value)` | 写入 NVS 字符串，返回是否成功 |

### 3. `json` — JSON 编解码

```lua
local json = require("json")
local t = json.decode('{"a":1,"b":2}')
print(t.a)              -- 1
local s = json.encode({x = 10, y = 20})
print(s)                -- {"x":10,"y":20}
```

| 函数 | 说明 |
|------|------|
| `json.decode(str)` | JSON 字符串 → Lua table，解析失败抛错 |
| `json.encode(value)` | Lua table → JSON 字符串（紧凑格式） |
| `json.pretty(value)` | Lua table → 格式化 JSON 字符串 |

编码时纯数字键 `1..n` 的 table 会被识别为数组，其余为对象。

### 4. `gpio` — GPIO 读写

```lua
local gpio = require("gpio")
gpio.mode(20, "output")        -- 设为输出
gpio.write(20, 1)              -- 输出高电平
gpio.mode(4, "input_pullup")   -- 设为输入（上拉）
local val = gpio.read(4)       -- 读取电平（0/1）
```

| 函数 | 说明 |
|------|------|
| `gpio.mode(pin, mode)` | 模式：`output` / `input` / `input_pullup` |
| `gpio.write(pin, level)` | 输出电平（0 或 1） |
| `gpio.read(pin)` | 读取电平，返回 0 或 1 |

::: warning GPIO48 已被板载情绪灯占用，不能用作普通 GPIO。
:::

### 5. `led` — WS2812/NeoPixel 灯带

```lua
local led = require("led")
led.init(48, 8)                -- 引脚48，8 个灯
led.set(0, 255, 0, 0)          -- 第 1 个灯红色 (R,G,B)
led.set_hsv(1, 120, 255, 255)  -- 第 2 个灯 HSV 方式（绿色）
led.brightness(50)             -- 亮度 0-255
led.show()                     -- 刷新输出
led.clear()                    -- 清空
led.deinit()                   -- 释放
```

| 函数 | 说明 |
|------|------|
| `led.init(pin, count)` | 初始化灯带（RMT TX，10MHz 分辨率） |
| `led.set(idx, r, g, b)` | 设置第 idx 个灯颜色（0 起始，GRB 顺序） |
| `led.set_hsv(idx, hue, sat, val)` | HSV 方式设置颜色（hue 0-359） |
| `led.show()` | 刷新输出到灯带 |
| `led.clear()` | 清空所有灯 |
| `led.brightness(0-255)` | 设置全局亮度 |
| `led.deinit()` | 释放 RMT 通道 |

### 6. `lvgl` — 屏幕绘制（LVGL）

```lua
local lv = require("lvgl")
local scr = lv.scr_act()
local label = lv.label_create(scr)
lv.obj_set_pos(label, 10, 20)
lv.label_set_text(label, "你好")
lv.set_style_text_color(label, lv.color_hex(0xFFFFFF))
lv.set_style_text_font(label, "puhui")   -- 中文字体
```

| 分类 | 函数 | 说明 |
|------|------|------|
| 运行时 | `lv.scr_act()` | 获取当前活动屏幕对象 |
| | `lv.scr_load(obj)` | 加载屏幕 |
| | `lv.disp_hor_res()` / `lv.disp_ver_res()` | 屏幕宽/高（像素） |
| 对象 | `lv.obj_create(parent)`（别名 `lv.obj`） | 创建容器对象 |
| | `lv.obj_del(obj)` | 删除对象 |
| | `lv.obj_set_pos(obj, x, y)` | 设置位置 |
| | `lv.obj_set_size(obj, w, h)` / `lv.obj_set_width` / `lv.obj_set_height` | 设置尺寸 |
| | `lv.obj_center(obj)` | 居中 |
| 样式 | `lv.set_style_bg_color(obj, color)` | 背景色 |
| | `lv.set_style_radius(obj, r)` | 圆角 |
| | `lv.set_style_border_width(obj, w)` / `lv.set_style_border_color(obj, color)` | 边框 |
| | `lv.set_style_text_color(obj, color)` | 文字颜色 |
| | `lv.set_style_text_font(obj, "puhui")` | 字体（`puhui` = 内置中文字体） |
| | `lv.set_style_bg_opa(obj, opa)` | 背景透明度 |
| | `lv.set_style_pad_all(obj, pad)` | 内边距 |
| | `lv.set_style_line_width` / `lv.set_style_line_color` / `lv.set_style_line_rounded` | 画线样式 |
| | `lv.set_style_text_align(obj, align)` | 文字对齐 |
| 控件 | `lv.label_create(parent)`（别名 `lv.label`） | 创建标签 |
| | `lv.label_set_text(label, text)` | 设置标签文本 |
| | `lv.btn_create(parent)`（别名 `lv.btn`） | 创建按钮 |
| 画线 | `lv.line_create(parent)`（别名 `lv.line`） | 创建线段 |
| | `lv.line_set_points(line, points)` | 设置线段点集 |
| 颜色 | `lv.color_make(r, g, b)` | 由 RGB 生成颜色（返回 `{r,g,b}` 表） |
| | `lv.color_hex(0xRRGGBB)` | 由十六进制生成颜色 |

::: tip 中文字体
Lua 脚本默认字体不含中文字符集，显示中文必须调用 `lv.set_style_text_font(obj, "puhui")` 切换到固件内置中文字体（16px，全量汉字）。
:::

### 7. `environmental_sensor` — 温湿度传感器（DHT）

```lua
local sensor = require("environmental_sensor")
local dht = sensor.new({type = "dht", pin = 20, sensor_type = "dht11"})
local data = dht:read()
print(string.format("%.1f,%.1f", data.temperature, data.humidity))
```

| 函数 | 说明 |
|------|------|
| `sensor.new({type="dht", pin=<gpio>, sensor_type="dht11"})` | 创建 DHT 设备。`sensor_type` 可选，默认 `dht11`；支持 `dht11` / `dht22`（同 `am2301`/`am2302`/`am2321`/`dht21`）/ `si7021` |
| `dht:read()` | 读取，返回 `{temperature=..., humidity=...}`（浮点） |
| `dht:read_temperature()` | 只读温度（浮点） |
| `dht:read_humidity()` | 只读湿度（浮点） |
| `dht:read_raw()` | 读取原始整数（返回温度、湿度两个值） |
| `dht:name()` | 返回 `"dht"` |
| `dht:close()` | 关闭句柄 |

::: warning 读取失败与重试
DHT 单总线偶发校验失败，`read` 系列会抛 Lua 错误。建议用 `pcall` 包裹并重试：

```lua
local ok, data = pcall(function() return dht:read() end)
if not ok then
    delay.delay_ms(500)   -- 等待后重试
end
```

每次读取前驱动会固定等待 200ms（`LUA_MODULE_DHT_PRE_READ_DELAY_US`），多次重试注意 3 秒超时限制。
:::

### 8. `adc` — 模数转换

读取 ADC 引脚电压（毫伏），自动做 eFuse 校准：

```lua
local adc = require("adc")
local ch = adc.new(34)          -- GPIO34 必须是 ADC 引脚（ESP32-S3 为 1-10）
print(ch:read())                -- 电压（mV），如 1520
print(ch:get_gpio())            -- 返回引脚号
ch:close()
```

| 函数 | 说明 |
|------|------|
| `adc.new(gpio)` | 创建 ADC 通道。GPIO 必须是 ADC 引脚，否则报错；衰减 12dB、位宽默认 |
| `ch:read()` | 读取电压，返回毫伏整数 |
| `ch:get_gpio()` | 返回绑定的 GPIO 号 |
| `ch:close()` | 释放通道 |

::: warning 校准要求
`adc.new` 会尝试 eFuse 校准，若芯片 eFuse 未烧录或方案不支持会直接报错。ESP32-S3 的 ADC 引脚为 GPIO1~10，GPIO11~20 不是 ADC 引脚。
:::

### 9. `ledc` — LED PWM（任意引脚）

`ledc` 是通用 PWM 控制器，可用于 LED 调光、舵机、蜂鸣器等。与 `led`（灯带专用）不同，它不依赖固定引脚：

```lua
local ledc = require("ledc")
local pwm = ledc.new({gpio = 4, frequency_hz = 1000, duty_percent = 50})
pwm:start()                     -- 开始输出
pwm:set_duty(80)                -- 占空比 0-100
pwm:set_frequency(5000)         -- 改频率（仅当定时器未被共享时）
pwm:stop()
pwm:close()
```

| 函数 | 说明 |
|------|------|
| `ledc.new({gpio=..., frequency_hz=..., duty_percent=..., duty_resolution_bits=...})` | 创建 PWM。`gpio`、`frequency_hz` 必填；`duty_percent` 默认 50；`duty_resolution_bits` 默认 14（范围 1-14） |
| `pwm:start()` | 按当前占空比开始输出 |
| `pwm:stop()` | 停止输出 |
| `pwm:set_duty(percent)` | 设置占空比（0-100），运行中立即生效 |
| `pwm:set_frequency(hz)` | 修改频率。若定时器被其他句柄共享会报错，需先关闭其他句柄 |
| `pwm:close()` | 释放通道与定时器 |

::: tip 定时器共享
相同频率/分辨率/模式的 PWM 会复用同一个 LEDC 定时器。此时 `set_frequency` 会因定时器被共享而报错，需先 `close` 其他同频句柄。
:::

### 10. `storage` — 文件存储（SPIFFS）

读写设备 flash 上的 SPIFFS 文件系统，根目录为 `/spiffs`：

```lua
local storage = require("storage")
print(storage.get_root_dir())               -- /spiffs
storage.write_file("/spiffs/config.txt", "hello")
print(storage.read_file("/spiffs/config.txt"))  -- hello
print(storage.exists("/spiffs/config.txt"))  -- true
local info = storage.stat("/spiffs/config.txt")
print(info.type, info.size)                 -- file 5
for _, f in ipairs(storage.listdir("/spiffs")) do
    print(f.name, f.type, f.size)
end
local space = storage.get_free_space()
print(space.total, space.free, space.used)
storage.remove("/spiffs/config.txt")
```

| 函数 | 说明 |
|------|------|
| `storage.get_root_dir()` | 返回存储根目录（`/spiffs`） |
| `storage.join_path(...)` | 拼接路径，自动处理分隔符 |
| `storage.exists(path)` | 路径是否存在，返回布尔 |
| `storage.stat(path)` | 返回 `{type, size, mtime, mode}`；不存在返回 `nil, errmsg` |
| `storage.mkdir(path)` | 创建目录（已存在不报错） |
| `storage.write_file(path, content)` | 写入文件（覆盖），返回 `true` |
| `storage.read_file(path)` | 读取文件内容（字符串），文件不存在抛错 |
| `storage.listdir(path)` | 返回目录项数组，每项含 `{name, type, size, mtime, mode}` |
| `storage.remove(path)` | 删除文件/目录 |
| `storage.rename(old, new)` | 重命名/移动 |
| `storage.get_free_space()` | 返回 `{total, free, used}`（字节） |

::: tip 用途
适合缓存配置、记录设备状态、保存离线数据。注意 SPIFFS 空间有限，写入前可用 `get_free_space` 检查剩余空间。
:::

### 11. `i2c` — I2C 总线

I2C 主机总线，可扫描总线并读写从设备（传感器、OLED、EEPROM 等）：

```lua
local i2c = require("i2c")
local bus = i2c.new(0, 21, 22)          -- 端口0，SDA=21，SCL=22，默认 400kHz
local addrs = bus:scan()                -- 扫描到的从设备地址数组
local dev = bus:device(0x28)            -- 从设备地址 0x28
local byte = dev:read_byte(0x00)        -- 读寄存器 0x00 一个字节
local data = dev:read(2, 0x10)          -- 从寄存器 0x10 读 2 字节（字符串）
dev:write_byte(0x01, 0x00)              -- 向寄存器 0x01 写一个字节
dev:write({0x02, 0x03, 0x04})           -- 写一串字节（也支持字符串）
dev:close()
bus:close()
```

| 函数 | 说明 |
|------|------|
| `i2c.new(port, sda, scl, freq)` | 创建总线。`freq` 默认 400000（Hz） |
| `bus:scan()` | 扫描总线，返回已响应从设备地址数组 |
| `bus:device(addr, clk_speed)` | 创建从设备句柄（addr 0-127，clk_speed 可选） |
| `bus:close()` | 释放总线 |
| `dev:read_byte(mem_addr?)` | 读 1 字节；`mem_addr` 省略时按无寄存器地址读 |
| `dev:read(len, mem_addr?)` | 读 `len` 字节（1-1024），返回字符串 |
| `dev:write_byte(value, mem_addr?)` | 写 1 字节（0-255） |
| `dev:write(data, mem_addr?)` | 写数据，`data` 可为字符串或字节数组 |
| `dev:address()` | 返回设备地址 |
| `dev:close()` | 释放设备句柄 |

::: warning 引脚与上拉
I2C 的 SDA/SCL 引脚驱动会启用内部上拉。若总线挂载多个设备或线缆较长，建议外接 4.7kΩ 上拉电阻。
:::

### 12. `button` — 按键

基于 `espressif/button` 组件的 GPIO 按键驱动，支持单击、双击、长按等事件。按键事件通过**事件队列**缓存，需要脚本主动调用 `button.dispatch()` 派发：

```lua
local button = require("button")
local btn = button.new(4, 0)            -- GPIO4，低电平触发（默认）
button.on(btn, "single_click", function(e)
    print("单击", e.event, e.pressed_time_ms)
end)
button.on(btn, "double_click", function(e)
    print("双击")
end)
button.on(btn, "long_press_start", function(e)
    print("长按开始", e.repeat_count)
end)

-- 主循环里轮询派发事件（注意 3 秒超时，可配合多次执行）
button.dispatch()
```

| 函数 | 说明 |
|------|------|
| `button.new(gpio_num, active_level?, long_press_ms?, short_press_ms?)` | 创建按键。`active_level` 默认 0（低电平触发）；`long_press_ms`/`short_press_ms` 默认 0（组件默认值）。最多 8 个句柄 |
| `button.on(handle, event, fn)` | 注册事件回调，回调收到 `{handle, event, repeat_count, pressed_time_ms}` 表 |
| `button.off(handle, event?)` | 注销回调；省略 event 时注销全部 |
| `button.get_key_level(handle)` | 读取当前电平（0/1） |
| `button.dispatch()` | 派发队列中的事件，返回本次派发数量 |
| `button.close(handle)` | 关闭并释放按键 |

支持的事件名：`press_down`、`press_up`、`press_repeat`、`press_repeat_done`、`single_click`、`double_click`、`multiple_click`、`long_press_start`、`long_press_hold`、`long_press_up`、`press_end`。

::: warning 事件派发机制
按键事件由中断回调放入队列，Lua 侧必须调用 `button.dispatch()` 才会执行回调。`dispatch` 是同步非阻塞的，适合在脚本里循环调用；注意 3 秒硬超时，长循环需控制次数。
:::

### 13. `uart` — 串口

UART 串口通信，可接串口传感器、GPS、蓝牙模块等：

```lua
local uart = require("uart")
local u = uart.new(1, 17, 18, 115200)   -- 端口1，TX=17，RX=18，波特率115200
print(u:available())                    -- 可读字节数
local line = u:read_line()              -- 读一行（直到换行）
u:write("AT\r\n")                       -- 发送数据
local buf = u:read(64)                  -- 读最多 64 字节
u:flush_input()                         -- 清空输入缓冲
u:close()
```

| 函数 | 说明 |
|------|------|
| `uart.new(port, tx, rx, baud, {data_bits=8, parity="none", stop_bits=1})` | 打开串口。`port` 0-1；`parity` 取值 `none`/`even`/`odd`；`stop_bits` 1 或 2 |
| `u:read(len)` | 读取最多 `len` 字节，返回字符串 |
| `u:read_line()` | 读取一行（以换行结尾），返回字符串 |
| `u:write(data)` | 发送数据（字符串） |
| `u:available()` | 返回输入缓冲可读字节数 |
| `u:flush_input()` | 清空输入缓冲 |
| `u:close()` | 关闭串口 |

::: tip 接线注意
TX 接对方 RX、RX 接对方 TX（交叉连接）。串口模块通常需共地。
:::

### 14. `pcnt` — 脉冲计数

脉冲计数单元，适合流量计、编码器测速、频率测量：

```lua
local pcnt = require("pcnt")
local unit = pcnt.new({
    low_limit = -100, high_limit = 100,
    glitch_ns = 1000,               -- 毛刺滤波（纳秒）
    edge_gpio = 4,                  -- 脉冲输入引脚
    pos_edge = "increase", neg_edge = "hold",
})
unit:start()
local count = unit:get_count()      -- 当前计数值
unit:clear()                        -- 清零
unit:stop()
unit:close()
```

| 函数 | 说明 |
|------|------|
| `pcnt.new({low_limit, high_limit, accum_count, glitch_ns, edge_gpio, level_gpio, pos_edge, neg_edge, high_level, low_level})` | 创建计数单元。`low_limit` 必须 <0，`high_limit` 必须 >0；`edge_gpio`/`level_gpio` 可选，提供则自动创建初始通道 |
| `unit:add_channel({...})` | 追加计数通道 |
| `unit:start()` / `unit:stop()` | 启动/停止计数 |
| `unit:clear()` | 清零计数 |
| `unit:get_count()` | 返回当前计数值 |
| `unit:close()` | 释放单元 |

边沿动作：`hold`（保持）/ `increase`（加）/ `decrease`（减）；电平动作：`keep`（保持）/ `inverse`（反转）/ `hold`（保持）。

### 15. `rmt` — RMT 底层驱动

RMT 底层收发通道，适合红外、自定义时序信号。`led` 灯带模块已内置 RMT，一般场景无需直接用本模块：

```lua
local rmt = require("rmt")
-- 发送通道
local tx = rmt.tx({gpio = 4, resolution_hz = 1000000, carrier_hz = 38000, carrier_duty = 0.33})
tx:send({{level = 1, duration = 900}, {level = 0, duration = 450}})  -- 符号数组
tx:close()
-- 接收通道
local rx = rmt.rx({gpio = 5, resolution_hz = 1000000})
rx:start()
local data = rx:read()   -- 读取接收到的符号
rx:close()
```

| 函数 | 说明 |
|------|------|
| `rmt.tx({gpio, resolution_hz, mem_block_symbols, trans_queue_depth, carrier_hz, carrier_duty})` | 创建发送通道。`carrier_hz` >0 时启用载波（红外常用 38000Hz） |
| `tx:send(symbols, timeout_ms?)` | 发送符号数组（每项 `{level=0/1, duration=ns}`），阻塞等待完成 |
| `tx:info()` / `tx:close()` | 查询信息 / 释放 |
| `rmt.rx({gpio, resolution_hz, ...})` | 创建接收通道 |
| `rx:receive(...)` / `rx:start()` / `rx:read()` / `rx:info()` / `rx:close()` | 接收相关操作 |

::: warning 与 led 模块共存
`led` 灯带与 `rmt` 都从 ESP-IDF 动态分配 RMT 通道，可同时使用（各占不同通道）。但同一引脚不要同时被两个模块占用。
:::

### 16. `http` — HTTP 服务器

在设备上启动 HTTP 服务器，可做本地配置页、状态页：

```lua
local http = require("http")
local sys = require("system")
local html = string.format(
    "<html><body><h1>ESP-AI</h1><p>Free RAM: %d</p></body></html>",
    sys.free_heap())
http.start(80)                       -- 启动服务器，端口 80
http.set_page("/", html)             -- 根路径返回 HTML
http.set_page("/info", "<html><body>Info</body></html>")
http.set_content_type("/info", "text/html")
print(http.is_running())             -- true
http.stop()                          -- 停止服务器
```

| 函数 | 说明 |
|------|------|
| `http.start(port)` | 启动 HTTP 服务器（后台运行，脚本结束后不停止） |
| `http.set_page(path, html)` | 设置路径返回的内容 |
| `http.set_content_type(path, type)` | 设置路径的 Content-Type |
| `http.is_running()` | 服务器是否在运行 |
| `http.stop()` | 停止服务器 |

### 17. `sci` — SCI 显示屏

基于 I2C 的 SCI 协议显示屏（部分带 OLED 的 LCD 面板），通过 I2C 读写寄存器：

```lua
local sci = require("sci")
local s = sci.new(0, 21, 22)         -- I2C 端口0，SDA=21，SCL=22
print(s:get_version())               -- 固件版本
print(s:get_sku())                   -- 设备型号
local keys = s:get_keys()            -- 按键状态
local vals = s:get_values()          -- 传感器值
s:set_refresh_rate(sci.REFRESH_1S)   -- 刷新率 1 秒
s:oled_on()                          -- 点亮 OLED
s:close()
```

| 函数 | 说明 |
|------|------|
| `sci.new(port, sda, scl, freq_hz?)` | 创建 SCI 设备（I2C 端口 0 或 1） |
| `s:get_version()` / `s:get_sku()` / `s:get_information()` | 查询版本/型号/信息 |
| `s:get_keys()` / `s:get_values()` / `s:get_units()` | 读取按键/数值/单位 |
| `s:get_value(idx)` / `s:get_unit(idx)` | 读取指定通道数值/单位 |
| `s:set_port(port)` / `s:get_port()` | 设置/读取端口（`sci.PORT1`/`PORT2`/`PORT3`/`ALL`） |
| `s:set_refresh_rate(rate)` / `s:get_refresh_rate()` | 设置/读取刷新率（`REFRESH_MS`/`REFRESH_1S`/.../`REFRESH_10MIN`） |
| `s:set_address(addr)` / `s:get_address()` | 设置/读取 I2C 地址（默认 `sci.DEFAULT_ADDR`） |
| `s:enable_record()` / `s:disable_record()` | 启用/关闭记录 |
| `s:oled_on()` / `s:oled_off()` | OLED 开关 |
| `s:get_rtc()` / `s:set_rtc(...)` | 读取/设置 RTC |
| `s:set_timeout(ms)` / `s:reset()` / `s:close()` | 超时/复位/关闭 |

### 18. `thread` — 多线程

Lua 线程任务与同步原语（队列/信号量/锁）。异步作业在独立 FreeRTOS 任务中运行，每次执行使用独立 Lua 状态，可安全并发：

```lua
local thread = require("thread")
-- 任务管理
local id = thread.start("/spiffs/scripts/worker.lua", {n = 10}, {name = "worker"})
print(id)            -- 返回作业 ID，如 "JOB0001"
thread.list()        -- 列出作业（JSON 数组）
thread.get(id)       -- 查询作业状态（JSON，含 output）
thread.stop(id, 1000) -- 停止作业，最多等 1000ms
-- 同步原语
local q = thread.sync.queue_create(4)
thread.sync.queue_send(q, "data")
local msg = thread.sync.queue_recv(q)
thread.sync.queue_delete(q)
local sem = thread.sync.sem_create(1)
thread.sync.sem_take(sem)
thread.sync.sem_give(sem)
thread.sync.sem_delete(sem)
local lock = thread.sync.lock_create()
thread.sync.lock(lock)
thread.sync.unlock(lock)
thread.sync.lock_delete(lock)
```

| 函数 | 说明 |
|------|------|
| `thread.run(path, args?, opts?)` | 同步执行脚本文件，返回 `true, 输出` 或 `nil, 错误` |
| `thread.start(path, args?, opts?)` | 异步执行，返回作业 ID。`opts` 支持 `{name=..., exclusive=..., replace=bool, timeout_ms=...}` |
| `thread.list(status?)` | 列出作业（JSON 数组），`status` 可过滤（queued/running/done/failed/stopped） |
| `thread.get(id_or_name)` | 查询作业（JSON，含 output 字段） |
| `thread.stop(id_or_name, wait_ms?)` | 停止作业并等待其结束 |
| `thread.sync.queue_create/send/recv/delete` | 队列同步 |
| `thread.sync.sem_create/give/take/delete` | 信号量同步 |
| `thread.sync.lock_create/lock/unlock/lock_delete` | 互斥锁同步 |

::: warning 作业限制
- 异步作业受运行时 **3 秒硬超时** 约束，长循环脚本会被强制结束。
- 最多 **4 个并发作业**；`replace=true` 会停止同名旧作业，`exclusive` 会停止同互斥键的其他作业。
- 作业完成/停止后槽位会被后续新作业回收，`thread.get` 只能查询仍在注册表中的作业。
::: 

### 19. `touch` — 触摸按键

电容触摸按键（ESP32-S3 支持），可配置多个触摸 GPIO：

```lua
local touch = require("touch")
local t = touch.new({gpios = {1, 2, 3}, threshold_milli = 500})
local res = t:read()
print(res.count, res.any_pressed, res.pressed_count)  -- 按键数/是否有按下/按下数
for i, k in ipairs(res.keys) do
    print(i, k.gpio, k.pressed, k.smooth, k.delta)
end
print(t:is_pressed(1))   -- 第 1 个按键是否按下
t:close()
```

| 函数 | 说明 |
|------|------|
| `touch.new({gpios={...}, threshold_milli=...})` | 创建触摸设备。`gpios` 为触摸 GPIO 数组（必填），`threshold_milli` 为灵敏度阈值（默认由 menuconfig 配置） |
| `t:read()` | 返回 `{keys={...}, count, any_pressed, pressed_count}`；每个 key 含 `{gpio, channel, pressed, smooth, benchmark, delta, threshold}` |
| `t:is_pressed(index)` | 指定按键（1 起始）是否按下 |
| `t:name()` | 返回设备名 |
| `t:close()` | 释放 |

### 20. `mcpwm` — 电机 PWM

MCPWM 电机控制，支持双路互补输出（舵机、直流电机、无刷电机）：

```lua
local mcpwm = require("mcpwm")
local m = mcpwm.new({
    gpio = 4,                  -- 主输出引脚
    gpio_b = 5,                -- 可选第二路输出
    frequency_hz = 1000,
    duty_percent = 50,
})
m:start()
m:set_duty(80)                 -- 占空比 0-100
m:set_frequency(2000)          -- 改频率
m:set_enabled(false)           -- 禁用输出
m:get_channel_count()          -- 通道数
m:stop()
m:close()
```

| 函数 | 说明 |
|------|------|
| `mcpwm.new({gpio, gpio_b, group_id, resolution_hz, frequency_hz, duty_percent, invert})` | 创建 MCPWM。`gpio` 必填；提供 `gpio_b` 时启用双通道 |
| `m:start()` / `m:stop()` | 启动/停止输出 |
| `m:set_duty(percent)` | 设置占空比（0-100） |
| `m:set_frequency(hz)` | 修改频率 |
| `m:set_enabled(bool)` | 启用/禁用输出 |
| `m:get_channel_count()` | 返回通道数 |
| `m:close()` | 释放 |

---

## 四、注意事项

1. **3 秒硬超时**：设备端脚本执行超过 3 秒会被强制终止，含硬件等待的脚本要控制总时长。
2. **GPIO48 占用**：板载情绪灯使用 GPIO48，不能作为普通 GPIO。
3. **中文字体**：LVGL 显示中文需 `set_style_text_font(obj, "puhui")`。
4. **未注册模块**：`display` / `ir` / `knob` 三个模块文件未注册，`require` 会报 `module not found`。`display` 缺项目内 `display_service.h`/`lua_image.h`，`ir` 缺 `espressif/ir_encoder` 与 `esp-board-manager` 组件，`knob` 缺 `espressif/knob` 组件；如需使用需先补齐依赖并在固件 `register_lua_modules` 中注册。
5. **权限**：插件调用 `lua_execute` 需要在 `manifest.json` 的 `permissions` 中声明 `device`。
6. **固件版本**：`environmental_sensor` 模块需要固件启用 DHT 后端（menuconfig → `LUA_MODULE_ENVIRONMENTAL_SENSOR_BACKEND_DHT`，默认开启）并重新编译烧录。
7. **新模块依赖**：`i2c`/`sci` 依赖 `espressif/i2c_bus`、`button` 依赖 `espressif/button`（v4.x）组件，已在 `idf_component.yml` 声明，编译时自动下载；`touch`/`mcpwm` 仅在支持的芯片上编译（S3 均支持）。使用这些模块需重新编译烧录固件。
8. **HTTP 端口**：`http` 模块启动的服务器默认端口 80，注意与设备其他网络服务端口避免冲突。

---

## 五、完整示例

### 读取 DHT11 温湿度（对应 dht11_sensor 插件）

```python
from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import lua_execute

_DHT_LUA = """\
local sensor = require("environmental_sensor")
local dht = sensor.new({type = "dht", pin = %(pin)d, sensor_type = "dht11"})
for i = 1, 3 do
    local ok, data = pcall(function() return dht:read() end)
    if ok then
        print(string.format("%%.1f,%%.1f", data.temperature, data.humidity))
        return
    end
    delay.delay_ms(500)
end
print("READ_FAILED")
"""

@tool(cache=False)
async def read_dht11(pin: int = 20, tool_manager=None) -> str:
    """读取 DHT11 温湿度传感器数据并播报。"""
    result, status, detail = await lua_execute(tool_manager, _DHT_LUA % {"pin": pin}, timeout=5.0)
    if status != "ok":
        return f"读取失败: {detail}"
    result = (result or "").strip()
    if result == "READ_FAILED" or "," not in result:
        return "读取温湿度失败，请检查 DHT11 接线"
    temp, humi = result.split(",")
    return f"当前温度 {float(temp):.1f}°C，湿度 {float(humi):.1f}%"
```

### 屏幕显示文字

```lua
local lv = require("lvgl")
local scr = lv.scr_act()
local label = lv.label_create(scr)
lv.obj_set_pos(label, 20, 40)
lv.label_set_text(label, "温度 25.0°C")
lv.set_style_text_color(label, lv.color_hex(0xFFFFFF))
lv.set_style_text_font(label, "puhui")
```

### ADC 采样 + PWM 调光

读取电位器电压，按比例控制 LED 亮度：

```lua
local adc = require("adc")
local ledc = require("ledc")
local ch = adc.new(1)                        -- ADC 引脚
local pwm = ledc.new({gpio = 4, frequency_hz = 1000})
pwm:start()
local mv = ch:read()                         -- 0~3300 mV
local percent = math.floor(mv / 3300 * 100)  -- 换算 0-100
pwm:set_duty(percent)
pwm:close()
ch:close()
```

### I2C 读取传感器寄存器

以常见 I2C 传感器为例，扫描总线并读取寄存器数据：

```lua
local i2c = require("i2c")
local bus = i2c.new(0, 21, 22)
local addrs = bus:scan()
if #addrs == 0 then
    print("NO_DEVICE")
else
    local dev = bus:device(addrs[1])
    local id = dev:read_byte(0x00)           -- 读设备 ID 寄存器
    print(string.format("ADDR=%d ID=0x%02X", addrs[1], id))
    dev:close()
end
bus:close()
```

---

## 参考文件

| 文件 | 说明 |
|------|------|
| `esp-ai-idf-client/main/lua/runtime/lua_runtime.c` | Lua 运行时：模块注册、print 捕获、超时钩子 |
| `esp-ai-idf-client/main/lua/modules/` | 各 Lua 模块源码 |
| `esp-ai-idf-client/main/commands/lua_commands.c` | `execute_lua` 指令处理、模块注册入口 |
| `esp-ai-server/src/use_cases/sdk/device.py` | 服务端 `lua_execute` 封装 |
