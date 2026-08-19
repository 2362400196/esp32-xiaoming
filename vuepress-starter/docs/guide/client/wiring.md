# 默认接线

本页覆盖两种板型，接线按 **音频 / 屏幕 / 按钮** 分类，每类下按板型给出引脚表：

| 板型 | 芯片 | 屏幕 | 音频方案 | 板级配置文件 |
|------|------|------|----------|--------------|
| 面包板方案（默认）| ESP32-S3 | 1.54 寸 ST7789 | ES8311（默认）/ I2S 直连 | `main/boards/defs/breadboard_1.54_lcd.h` |
| SuperMini 方案 | ESP32-C3 | 无（串口输出）| **仅 ES8311** | `main/boards/defs/esp32c3_supermini.h` |

**音频方案由 menuconfig → 音频编解码器 二选一**（与板型独立）：

| 方案 | 麦克风 | 喇叭 | 特点 |
|------|--------|------|------|
| **ES8311** | ES8311 编解码器（ADC） | ES8311 + NS4150B 功放 | 全双工 I2S，单芯片编解码，支持语音唤醒+播放同链路 |
| **I2S 直连** | INMP441 数字麦 | MAX98357A 数字功放 | 全数字直连，无需编解码器 |

> **板型限制**：I2S 直连方案依赖 I2S_NUM_1，**仅 ESP32-S3 可用**；ESP32-C3 只有 I2S_NUM_0，音频必须使用 ES8311 全双工方案。

<style>
:root {
  --surface: #ffffff;
  --surface-muted: #f5f5f7;
  --border: #e5e5ea;
  --text-primary: #1d1d1f;
  --text-muted: #86868b;
  --brand: #7c3aed;
  --brand-light: #ede9fe;
  --accent: #f59e0b;
  --accent-light: #fef3c7;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", Monaco, Consolas, monospace;
}
</style>

## 音频

### ES8311 编解码方案（全双工 I2S，推荐）

**ES8311** 是单芯片低功耗音频编解码器，ADC（麦克风）与 DAC（喇叭）共用同一组 I2S 总线（全双工），ESP32 作为 I2S 主设备提供时钟。

两个板型共用的固件行为：
- MCLK 倍率固定 **256×**（对齐 xiaozhi-esp32），采样率固定 **16kHz**
- 非 16kHz 音频（如服务端 24kHz TTS）由固件在软件中重采样到 16kHz
- 麦克风输入增益默认 12dB（`es8311_set_mic_gain(12)`）
- 两个板型 `pa_pin = -1`，NS4150B 功放由硬件自行上拉保持常通（无外部 PA 控制脚）

#### ESP32-S3 接线

<svg viewBox="0 0 720 330" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--text-muted)"/>
    </marker>
    <marker id="arr2" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
      <path d="M1,1 L7,4 L1,7 Z" fill="var(--brand)"/>
    </marker>
  </defs>
  <rect width="720" height="330" fill="var(--surface)" rx="12"/>
  <text x="20" y="28" font-family="var(--font-sans)" font-size="13" font-weight="600" fill="var(--text-muted)">ES8311 全双工接线（GPIO 均无冲突）</text>
  <line x1="20" y1="34" x2="340" y2="34" stroke="var(--border)"/>
  <!-- ESP32-S3 -->
  <rect x="24" y="60" width="170" height="260" fill="var(--brand-light)" stroke="var(--brand)" rx="10"/>
  <text x="109" y="86" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">ESP32-S3</text>
  <text x="109" y="104" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">I2S Master</text>
  <text x="42" y="132" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO41  SDA</text>
  <text x="42" y="154" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO42  SCL</text>
  <text x="42" y="176" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO5   MCLK</text>
  <text x="42" y="198" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO6   BCLK</text>
  <text x="42" y="220" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO4   LRCK</text>
  <text x="42" y="242" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO15  DIN→</text>
  <text x="42" y="264" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">GPIO17  DOUT←</text>
  <text x="42" y="286" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">5V      电源</text>
  <!-- ES8311 -->
  <rect x="300" y="60" width="170" height="260" fill="var(--brand-light)" stroke="var(--brand)" rx="10"/>
  <text x="385" y="86" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="var(--brand)" text-anchor="middle">ES8311 (0x18)</text>
  <text x="385" y="104" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">I2S Slave + 编解码</text>
  <text x="318" y="132" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">SDA</text>
  <text x="318" y="154" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">SCL</text>
  <text x="318" y="176" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">MCLK</text>
  <text x="318" y="198" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">BCLK</text>
  <text x="318" y="220" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">LRCK</text>
  <text x="318" y="242" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">DIN</text>
  <text x="318" y="264" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">DOUT</text>
  <text x="318" y="286" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">5V</text>
  <!-- 连线 -->
  <line x1="194" y1="128" x2="298" y2="128" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="194" y1="150" x2="298" y2="150" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="194" y1="172" x2="298" y2="172" stroke="var(--brand)" marker-end="url(#arr2)"/>
  <line x1="194" y1="194" x2="298" y2="194" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="194" y1="216" x2="298" y2="216" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="194" y1="238" x2="298" y2="238" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="298" y1="260" x2="194" y2="260" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <line x1="194" y1="282" x2="298" y2="282" stroke="var(--text-muted)" marker-end="url(#arr)"/>
  <!-- 功放 -->
  <rect x="560" y="60" width="136" height="100" fill="var(--accent-light)" stroke="var(--accent)" rx="10"/>
  <text x="628" y="86" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="#92400e" text-anchor="middle">NS4150B</text>
  <text x="628" y="104" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">3W D 类功放</text>
  <text x="574" y="128" font-family="var(--font-mono)" font-size="11" fill="var(--text-primary)">IN  ← 喇叭信号</text>
  <text x="574" y="146" font-family="var(--font-mono)" font-size="11" fill="#92400e">EN  常通(未受控)</text>
  <!-- 麦克风 -->
  <rect x="560" y="200" width="136" height="100" fill="var(--accent-light)" stroke="var(--accent)" rx="10"/>
  <text x="628" y="226" font-family="var(--font-sans)" font-size="14" font-weight="600" fill="#92400e" text-anchor="middle">MIC</text>
  <text x="628" y="246" font-family="var(--font-sans)" font-size="11" fill="var(--text-muted)" text-anchor="middle">模拟麦克风</text>
  <line x1="470" y1="110" x2="558" y2="110" stroke="var(--accent)" marker-end="url(#arr)"/>
  <line x1="470" y1="250" x2="558" y2="250" stroke="var(--accent)" marker-end="url(#arr)"/>
  <text x="505" y="98" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">DAC 输出</text>
  <text x="505" y="268" font-family="var(--font-sans)" font-size="10" fill="var(--text-muted)" text-anchor="middle">ADC 输入</text>
</svg>

| ES8311 模块引脚 | ESP32-S3 GPIO | 说明 |
|------|------|------|
| SDA | GPIO41 | I2C 数据 |
| SCL | GPIO42 | I2C 时钟（地址 0x18）|
| MCLK | GPIO5 | 主时钟，16kHz × 256 = **4.096MHz** |
| BCLK（共享）| GPIO6 | 位时钟，麦克风与喇叭共用 |
| LRCK（共享）| GPIO4 | 帧时钟（WS），麦克风与喇叭共用 |
| DIN | GPIO15 | DAC 数据输入（ESP32 → ES8311 → 喇叭）|
| DOUT | GPIO17 | ADC 数据输出（麦克风 → ES8311 → ESP32）|
| 5V | 5V | 模块电源（板载 LDO 降压至 3.3V）|

#### ESP32-C3 接线（C3 唯一可选方案）

ESP32-C3 SuperMini 开发板（单核 160MHz，**无 PSRAM**，4MB Flash）。C3 只有 I2S_NUM_0，音频必须使用 ES8311 全双工方案；I2S 直连方案在 C3 上不可用（编译期由板型配置约束）。

| ES8311 模块引脚 | ESP32-C3 GPIO | 说明 |
|------|------|------|
| SDA | GPIO4 | I2C 数据 |
| SCL | GPIO5 | I2C 时钟（地址 0x18）|
| CLK | GPIO1 | 主时钟 MCLK，16kHz × 256 = **4.096MHz** |
| SCK | GPIO3 | 位时钟 BCLK（麦克风与喇叭共用）|
| LRCK | GPIO6 | 帧时钟 WS（麦克风与喇叭共用）|
| DAC SDIN | GPIO7 | DAC 数据输入（ESP32 → ES8311 → 喇叭）|
| ADC SDOUT | GPIO10 | ADC 数据输出（麦克风 → ES8311 → ESP32）|
| 5V | 5V | 模块电源（板载 LDO 降压至 3.3V）|

> **C3 内存提示**：无 PSRAM，固件已做针对性优化（唤醒词引擎会话期间销毁/重建、MP3 解码器按需分配、WebSocket 提前初始化、WiFi/LWIP 缓冲收紧），正常对话流程可稳定运行；无屏幕（headless），状态/表情/字幕以 `[状态] [表情] [字幕]` 文本输出到串口。

### I2S 直连方案（INMP441 + MAX98357A，仅 ESP32-S3）

**麦克风：INMP441** —— I2S 数字输出麦克风，单声道，无需外置 ADC，采样率 16kHz（支持 8k~48kHz）。

| 引脚 | GPIO | 说明 |
|------|------|------|
| BCLK | GPIO4 | 位时钟 |
| WS | GPIO5 | 帧时钟（左右声道）|
| DIN | GPIO6 | 数据输入（来自麦克风）|

> 该方案为独立 I2S 总线，麦克风与喇叭互不共享时钟。

**喇叭：MAX98357A** —— I2S 输入 D 类功放，3.2W 输出，内置 DAC，可直接驱动喇叭。

| 引脚 | GPIO | 说明 |
|------|------|------|
| BCLK | GPIO16 | 位时钟 |
| WS | GPIO17 | 帧时钟（左右声道）|
| DOUT | GPIO15 | 数据输出（至功放）|

> 该方案 I2S 喇叭使用独立的 I2S_NUM_1 通道，PA 使能脚同样由硬件自行上拉保持常通。

## 屏幕（仅 ESP32-S3）

**型号：ST7789** —— 1.54 寸 TFT 彩色液晶屏，分辨率 240×240，SPI 接口，搭配 LVGL 显示表情动画。

采用 **ESP-IDF esp_lcd 组件 + LVGL 驱动**，SPI 接口（ST7789）：

| 屏幕丝印 | 引脚 | GPIO | 说明 |
|------|------|------|------|
| SDA | MOSI | GPIO39 | SPI 主输出从输入 |
| SCL | SCLK | GPIO38 | SPI 时钟 |
| SC | CS | GPIO9 | 片选 |
| DC | DC | GPIO13 | 数据/命令选择 |
| RES | RST | **接 3V3** | 见下方"屏幕不亮？"说明 |
| BCLK | BL | **GPIO16** | 背光控制（LEDC PWM 调亮度），见下方说明 |

> **屏幕不亮？** 按顺序排查：
>
> 1. **背光**：默认板型已配置背光引脚 `display_bl = GPIO16`（LEDC PWM 驱动，开机默认 100%），把 `BCLK`（背光）接到 **GPIO16** 即可点亮并支持亮度调节（服务端 `set_brightness` 指令，0-100）；若不需要调亮度，`BCLK` 接 3V3 也可常亮，但此时固件 PWM 输出悬空、亮度不可调。
> 2. **复位（实测必接）**：`RES` 悬空时多数 ST7789 模块会卡在复位状态（SPI 命令被忽略，屏幕无响应黑屏），**RES 必须接 3V3**（高电平 = 正常工作）。固件在无硬件复位脚时会自动发软件复位命令（0x01），配合硬件 RES=3V3 即可正常驱动。
> 3. 若仍黑屏，核对丝印：`SCL/SDA` 是 SPI 的 `SCLK/MOSI`，**不是** I2C 信号（别与 ES8311 的 SDA/SCL 混淆）。
>
> 屏幕丝印列对应常见 ST7789 屏幕模块上标注的引脚名（如 `SCL/SDA/RES/DC/SC/BCLK`）。
>
> 背光引脚如需更换（如与其他外设冲突），修改板型配置 `main/boards/defs/breadboard_1.54_lcd.h` 中的 `BOARD_DISPLAY_ST7789_240_BL(9, 13, 38, 39, 16)` 最后一个参数即可。

## 唤醒按钮

| 板型 | 按钮 GPIO | 说明 |
|------|------|------|
| ESP32-S3 面包板 | GPIO0 | 单击唤醒对话；**2 秒内连按 4 次**清除 WiFi 配置进入配网模式 |
| ESP32-C3 SuperMini | GPIO9（板载 BOOT 键）| 同上，无需外接按钮（GPIO9 即 C3 的 BOOT 引脚）|

> 配网通过 **BLE（NimBLE）**：手机 App 搜索设备蓝牙广播完成配网。蓝牙控制器仅在配网模式才初始化，正常运行不影响内存余量。
>
> 不同板型的引脚可能不同，具体以对应板级的配置文件（`main/boards/defs/<board>.h`）为准。
