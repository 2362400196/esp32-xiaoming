"""DHT11 温湿度传感器插件：通过设备端 environmental_sensor Lua 模块读取温湿度。

安装后 LLM 自动获得 read_dht11 工具（用户问温度/湿度/温湿度/室内环境时调用）：
  - 设备端 Lua 调用 environmental_sensor 模块的 DHT 后端（GPIO 单总线）
  - 返回中文文本，LLM 直接播报

接线：DHT11 的 DATA 引脚接设备 GPIO（默认 20，可通过工具参数指定），
VCC 接 3.3V，GND 接 GND。DATA 线需接一个 4.7k~10k 上拉电阻到 VCC
（多数 DHT11 模块已内置，裸传感器需外接）。固件需启用 environmental_sensor
模块（DHT 后端）。"""

from src.use_cases.sdk.tools import tool
from src.use_cases.sdk.device import lua_execute

# DHT 读取脚本：带 3 次重试（DHT11 单总线偶发校验失败时自动重试）
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
    """读取 DHT11 温湿度传感器数据并播报。
    只要用户询问当前温度、湿度、温湿度、室内环境等需要实时传感器数据的问题，
    就调用此工具获取最新读数，不要用记忆或猜测回答。
    参数 pin: DHT11 的 DATA 引脚连接的 GPIO 编号，默认 20。"""
    lua_code = _DHT_LUA % {"pin": pin}
    result, status, detail = await lua_execute(tool_manager, lua_code, timeout=5.0)
    if status != "ok":
        if status == "offline":
            return "设备不在线，无法读取温湿度"
        if status == "timeout":
            return "读取温湿度超时，请检查 DHT11 接线"
        return f"读取温湿度失败: {detail}"
    result = (result or "").strip()
    if result.startswith("[Lua Error]"):
        return "读取温湿度失败，请检查 DHT11 接线（DATA 引脚是否接对、供电是否正常）"
    if result == "READ_FAILED" or "," not in result:
        return "读取温湿度失败，请检查 DHT11 接线后重试"
    try:
        temp, humi = result.split(",")
        return f"当前温度 {float(temp):.1f}°C，湿度 {float(humi):.1f}%"
    except ValueError:
        return f"读取温湿度数据异常: {result}"
