# 默认接线

接线只有 **三种情况**，取决于「板型 + 音频方案」的组合。先在下表选一种方案，然后只看那一节，照着图接线即可。屏幕和按钮是三种方案共用的外设，放在文末。

| 方案 | 组合 | 需要准备 | 接线量 | 推荐度 |
|------|------|----------|--------|--------|
| 方案一 | ESP32-S3 + ES8311 | S3 开发板、ES8311 模块、NS4150B 功放 + 喇叭、模拟麦克风 | 8 根 | ✅ **推荐（默认）** |
| 方案二 | ESP32-S3 + I2S 直连 | S3 开发板、INMP441 数字麦、MAX98357A 功放 | 6 根（两个模块） | 可选 |
| 方案三 | ESP32-C3 + ES8311 | C3 SuperMini、ES8311 模块、NS4150B 功放 + 喇叭、模拟麦克风 | 8 根 | 精简 |

::: tip 我该选哪个
- **不知道选哪个 → 方案一**。功能最全：有屏、全双工（唤醒与播放同时在线）、支持亮度调节，也是固件的默认板型配置。
- **想省掉编解码器、链路全数字 → 方案二**。代价是要接两个模块、两路 I2S，且 GPIO16 与屏幕背光抢脚。
- **手上只有 C3 / 要最小体积 → 方案三**。C3 只有这一种音频方案可选，并且没有屏幕。
:::

::: warning 三种方案互斥
一个固件同时只跑一种音频方案。换方案必须重新 `menuconfig` 并重新烧录，引脚也不要混接——例如方案一的 GPIO41/42 在方案二里并不存在。
:::

## 方案一：ESP32-S3 + ES8311（推荐）

**适用场景**：面包板默认板型，要屏幕表情动画，要全双工语音。

| 配置项 | 取值 |
|--------|------|
| 板型配置 | `main/boards/defs/esp32s3_breadboard_1.54_lcd.h` |
| 音频选项 | `menuconfig → 音频编解码器` → **ES8311** |
| 屏幕 | 1.54 寸 ST7789 · 240×240（接线见 [屏幕](#屏幕-方案一、二共用)） |

**ES8311** 是单芯片低功耗音频编解码器：ADC（麦克风）与 DAC（喇叭）共用一组 I2S 总线全双工工作，ESP32 作为 I2S 主设备输出时钟。

### 接线图

<svg class="wiring" viewBox="0 0 760 412" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ESP32-S3 与 ES8311 接线图">
  <defs>
    <marker id="wmk-s3" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
    <marker id="wmk-s3b" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk-b" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
    <marker id="wmk-s3a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk-a" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
  </defs>
  <rect class="bg" x="0.5" y="0.5" width="759" height="411" rx="14"/>
  <text class="cap" x="26" y="31">ESP32-S3 → ES8311 · 全双工 I2S</text>
  <text class="cap" x="734" y="31" text-anchor="end">方案一 · 推荐</text>

  <rect class="box-b" x="24" y="56" width="196" height="292" rx="12"/>
  <text class="t f-b" x="122" y="86" text-anchor="middle">ESP32-S3</text>
  <text class="s" x="122" y="104" text-anchor="middle">I2S 主机 · I2C 主机</text>
  <text class="pin" x="40" y="140">GPIO41</text>
  <text class="sig" x="204" y="140" text-anchor="end">SDA</text>
  <text class="pin" x="40" y="167">GPIO42</text>
  <text class="sig" x="204" y="167" text-anchor="end">SCL</text>
  <text class="pin" x="40" y="194">GPIO5</text>
  <text class="sig" x="204" y="194" text-anchor="end">MCLK</text>
  <text class="pin" x="40" y="221">GPIO6</text>
  <text class="sig" x="204" y="221" text-anchor="end">BCLK</text>
  <text class="pin" x="40" y="248">GPIO4</text>
  <text class="sig" x="204" y="248" text-anchor="end">LRCK</text>
  <text class="pin" x="40" y="275">GPIO15</text>
  <text class="sig" x="204" y="275" text-anchor="end">DIN</text>
  <text class="pin" x="40" y="302">GPIO17</text>
  <text class="sig" x="204" y="302" text-anchor="end">DOUT</text>
  <text class="pin" x="40" y="329">5V</text>
  <text class="sig" x="204" y="329" text-anchor="end">电源</text>

  <rect class="box-b" x="296" y="56" width="186" height="292" rx="12"/>
  <text class="t f-b" x="389" y="86" text-anchor="middle">ES8311</text>
  <text class="s" x="389" y="104" text-anchor="middle">编解码器 · I2C 0x18</text>
  <text class="pin" x="312" y="140">SDA</text>
  <text class="pin" x="312" y="167">SCL</text>
  <text class="pin" x="312" y="194">MCLK</text>
  <text class="pin" x="312" y="221">BCLK</text>
  <text class="pin" x="312" y="248">LRCK</text>
  <text class="pin" x="312" y="275">DIN</text>
  <text class="pin" x="312" y="302">DOUT</text>
  <text class="pin" x="312" y="329">5V</text>

  <line class="ln" x1="220" y1="136" x2="294" y2="136"/>
  <line class="ln" x1="220" y1="163" x2="294" y2="163"/>
  <line class="ln-b" x1="220" y1="190" x2="294" y2="190" marker-end="url(#wmk-s3b)"/>
  <line class="ln-b" x1="220" y1="217" x2="294" y2="217" marker-end="url(#wmk-s3b)"/>
  <line class="ln-b" x1="220" y1="244" x2="294" y2="244" marker-end="url(#wmk-s3b)"/>
  <line class="ln-b" x1="220" y1="271" x2="294" y2="271" marker-end="url(#wmk-s3b)"/>
  <line class="ln-b" x1="294" y1="298" x2="222" y2="298" marker-end="url(#wmk-s3b)"/>
  <line class="ln-p" x1="220" y1="325" x2="294" y2="325" marker-end="url(#wmk-s3)"/>

  <line class="ln-a" x1="482" y1="176" x2="556" y2="176" marker-end="url(#wmk-s3a)"/>
  <text class="s" x="519" y="168" text-anchor="middle">DAC</text>
  <line class="ln-a" x1="556" y1="318" x2="484" y2="318" marker-end="url(#wmk-s3a)"/>
  <text class="s" x="519" y="310" text-anchor="middle">ADC</text>

  <rect class="box-a" x="558" y="104" width="178" height="140" rx="12"/>
  <text class="t f-a" x="647" y="132" text-anchor="middle">NS4150B</text>
  <text class="s" x="647" y="150" text-anchor="middle">3W D 类功放</text>
  <text class="s" x="572" y="182">DAC 输出</text>
  <text class="s" x="572" y="204">EN 硬件上拉 · 常通</text>
  <text class="s" x="572" y="226">OUT → 喇叭</text>

  <rect class="box-a" x="558" y="252" width="178" height="100" rx="12"/>
  <text class="t f-a" x="647" y="280" text-anchor="middle">MIC</text>
  <text class="s" x="647" y="298" text-anchor="middle">模拟麦克风</text>
  <text class="s" x="572" y="322">ADC 输入</text>

  <line class="ln-b" x1="28" y1="382" x2="58" y2="382" marker-end="url(#wmk-s3b)"/>
  <text class="lg" x="68" y="386">I2S 音频 / 时钟</text>
  <line class="ln" x1="200" y1="382" x2="230" y2="382"/>
  <text class="lg" x="240" y="386">I2C 控制（双向）</text>
  <line class="ln-p" x1="370" y1="382" x2="400" y2="382"/>
  <text class="lg" x="410" y="386">电源</text>
  <line class="ln-a" x1="480" y1="382" x2="510" y2="382"/>
  <text class="lg" x="520" y="386">模拟音频</text>
</svg>

### 接线表

| ES8311 引脚 | 信号 | 接到 ESP32-S3 | 说明 |
|-------------|------|---------------|------|
| SDA | I2C 数据 | GPIO41 | 编解码器地址 0x18 |
| SCL | I2C 时钟 | GPIO42 | 与 SDA 同一路 I2C |
| MCLK | 主时钟 | GPIO5 | 4.096MHz，由 ESP32 输出 |
| BCLK | 位时钟 | GPIO6 | 播放与录音共用 |
| LRCK | 帧时钟（WS） | GPIO4 | 播放与录音共用 |
| DIN | DAC 数据输入 | GPIO15 | ESP32 → ES8311 → 喇叭 |
| DOUT | ADC 数据输出 | GPIO17 | 麦克风 → ES8311 → ESP32 |
| 5V | 电源 | 5V | 模块板载 LDO 降压到 3.3V |

另外两根不走 GPIO：ES8311 的 `DAC` 输出接 NS4150B 的 `IN`，`ADC` 输入接模拟麦克风；喇叭接 NS4150B 输出。

屏幕（1.54 寸 ST7789）与本方案音频引脚不冲突，接线见 [屏幕](#屏幕-方案一、二共用)，接上即可。

## 方案二：ESP32-S3 + I2S 直连

**适用场景**：不想用编解码器，麦克风与喇叭全数字直连。板子仍是 ESP32-S3，只换音频部分。

| 配置项 | 取值 |
|--------|------|
| 板型配置 | `main/boards/defs/esp32s3_breadboard_1.54_lcd.h` |
| 音频选项 | `menuconfig → 音频编解码器` → **I2S 直连** |
| 屏幕 | 可用，但**背光脚要改**，见下方警告 |

**INMP441**：I2S 数字输出麦克风，单声道，内置 ADC，采样率 16kHz（支持 8k~48kHz）。
**MAX98357A**：I2S 输入 D 类功放，3.2W，内置 DAC，直接驱动喇叭。

两路总线完全独立，麦克风与喇叭不共享时钟；喇叭侧使用 `I2S_NUM_1`，PA 使能同样由硬件上拉常通。

### 接线图

<svg class="wiring" viewBox="0 0 760 428" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ESP32-S3 与 INMP441、MAX98357A 接线图">
  <defs>
    <marker id="wmk-i2s" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
    <marker id="wmk-i2sb" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk-b" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
  </defs>
  <rect class="bg" x="0.5" y="0.5" width="759" height="427" rx="14"/>
  <text class="cap" x="26" y="31">ESP32-S3 → INMP441 + MAX98357A · 两路独立 I2S</text>
  <text class="cap" x="734" y="31" text-anchor="end">方案二 · 仅 ESP32-S3</text>

  <rect class="box-b" x="24" y="56" width="196" height="324" rx="12"/>
  <text class="t f-b" x="122" y="86" text-anchor="middle">ESP32-S3</text>
  <text class="s" x="122" y="104" text-anchor="middle">两路独立 I2S 主机</text>
  <text class="pin" x="40" y="144">GPIO4</text>
  <text class="sig" x="204" y="144" text-anchor="end">BCLK</text>
  <text class="pin" x="40" y="170">GPIO5</text>
  <text class="sig" x="204" y="170" text-anchor="end">WS</text>
  <text class="pin" x="40" y="196">GPIO6</text>
  <text class="sig" x="204" y="196" text-anchor="end">DIN</text>
  <text class="pin" x="40" y="316">GPIO16</text>
  <text class="sig" x="204" y="316" text-anchor="end">BCLK</text>
  <text class="pin" x="40" y="342">GPIO17</text>
  <text class="sig" x="204" y="342" text-anchor="end">WS</text>
  <text class="pin" x="40" y="368">GPIO15</text>
  <text class="sig" x="204" y="368" text-anchor="end">DOUT</text>

  <text class="lg" x="230" y="130">麦克风总线</text>
  <line class="ln" x1="220" y1="140" x2="428" y2="140" marker-end="url(#wmk-i2sb)"/>
  <line class="ln" x1="220" y1="166" x2="428" y2="166" marker-end="url(#wmk-i2sb)"/>
  <line class="ln" x1="428" y1="192" x2="222" y2="192" marker-end="url(#wmk-i2sb)"/>

  <text class="lg" x="230" y="302">喇叭总线 · I2S_NUM_1</text>
  <line class="ln" x1="220" y1="312" x2="428" y2="312" marker-end="url(#wmk-i2sb)"/>
  <line class="ln" x1="220" y1="338" x2="428" y2="338" marker-end="url(#wmk-i2sb)"/>
  <line class="ln" x1="220" y1="364" x2="428" y2="364" marker-end="url(#wmk-i2sb)"/>

  <rect class="box-a" x="430" y="64" width="210" height="140" rx="12"/>
  <text class="t f-a" x="535" y="92" text-anchor="middle">INMP441</text>
  <text class="s" x="535" y="110" text-anchor="middle">I2S 数字麦克风 · 单声道</text>
  <text class="pin" x="444" y="144">BCLK</text>
  <text class="pin" x="444" y="170">WS</text>
  <text class="pin" x="444" y="196">DIN</text>

  <rect class="box-a" x="430" y="236" width="210" height="140" rx="12"/>
  <text class="t f-a" x="535" y="264" text-anchor="middle">MAX98357A</text>
  <text class="s" x="535" y="282" text-anchor="middle">I2S D 类功放 · 3.2W</text>
  <text class="pin" x="444" y="316">BCLK</text>
  <text class="pin" x="444" y="342">WS</text>
  <text class="pin" x="444" y="368">DOUT</text>

  <text class="lg" x="26" y="410">两路 I2S 互不共享时钟：麦克风一条总线，喇叭另一条（I2S_NUM_1），PA 使能由硬件上拉常通。</text>
</svg>

### 接线表

| 模块 | 引脚 | 信号 | 接到 ESP32-S3 | 说明 |
|------|------|------|---------------|------|
| INMP441 | BCLK | 位时钟 | GPIO4 | 麦克风总线 |
| INMP441 | WS | 帧时钟 | GPIO5 | 左右声道选择 |
| INMP441 | DIN | 数据输入 | GPIO6 | 麦克风 → ESP32 |
| MAX98357A | BCLK | 位时钟 | GPIO16 | 喇叭总线 · `I2S_NUM_1` |
| MAX98357A | WS | 帧时钟 | GPIO17 | 左右声道选择 |
| MAX98357A | DOUT | 数据输出 | GPIO15 | ESP32 → 功放 |

屏幕（1.54 寸 ST7789）接线见 [屏幕](#屏幕-方案一、二共用)。**注意：本方案的喇叭 BCLK 占用 GPIO16，与屏幕默认背光脚冲突，用屏必须换脚**，见下方警告。

### 注意点

::: warning 用屏就必须给背光换脚
I2S 直连的 BCLK 占了 GPIO16，而 GPIO16 也是 ST7789 的默认背光脚。同时用屏 + 方案二时，改 `main/boards/defs/esp32s3_breadboard_1.54_lcd.h` 里 `BOARD_DISPLAY_ST7789_240_BL(9, 13, 38, 39, 16)` 的最后一个参数（背光脚）。
:::

- 与方案一相比，方案二少一个编解码器、少两根线，但要多接一个模块，且没有 ES8311 的模拟增益链路（增益靠 INMP441 自身与软件）。
- `I2S_NUM_1` 是硬性依赖，这也是 C3 用不了本方案的原因（见方案三）。

## 方案三：ESP32-C3 + ES8311

**适用场景**：手上是 C3 SuperMini、想做到最小体积；不要屏幕。

| 配置项 | 取值 |
|--------|------|
| 板型配置 | `main/boards/defs/esp32c3_supermini.h` |
| 音频选项 | `menuconfig → 音频编解码器` → **ES8311**（C3 唯一可选，编译期已约束） |
| 屏幕 | 不支持（headless） |

C3 只有 `I2S_NUM_0`，音频必须走 ES8311 全双工；方案二的 `I2S_NUM_1` 在 C3 上不存在。开发板规格：单核 160MHz、4MB Flash、**无 PSRAM**。

### 接线图

<svg class="wiring" viewBox="0 0 760 412" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ESP32-C3 与 ES8311 接线图">
  <defs>
    <marker id="wmk-c3" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
    <marker id="wmk-c3b" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk-b" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
    <marker id="wmk-c3a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto"><path class="mk-a" d="M0.5,1 L7,4 L0.5,7 Z"/></marker>
  </defs>
  <rect class="bg" x="0.5" y="0.5" width="759" height="411" rx="14"/>
  <text class="cap" x="26" y="31">ESP32-C3 → ES8311 · 全双工 I2S</text>
  <text class="cap" x="734" y="31" text-anchor="end">方案三 · SuperMini</text>

  <rect class="box-b" x="24" y="56" width="196" height="292" rx="12"/>
  <text class="t f-b" x="122" y="86" text-anchor="middle">ESP32-C3</text>
  <text class="s" x="122" y="104" text-anchor="middle">I2S 主机 · I2C 主机</text>
  <text class="pin" x="40" y="140">GPIO4</text>
  <text class="sig" x="204" y="140" text-anchor="end">SDA</text>
  <text class="pin" x="40" y="167">GPIO5</text>
  <text class="sig" x="204" y="167" text-anchor="end">SCL</text>
  <text class="pin" x="40" y="194">GPIO1</text>
  <text class="sig" x="204" y="194" text-anchor="end">CLK</text>
  <text class="pin" x="40" y="221">GPIO3</text>
  <text class="sig" x="204" y="221" text-anchor="end">SCK</text>
  <text class="pin" x="40" y="248">GPIO6</text>
  <text class="sig" x="204" y="248" text-anchor="end">LRCK</text>
  <text class="pin" x="40" y="275">GPIO7</text>
  <text class="sig" x="204" y="275" text-anchor="end">SDIN</text>
  <text class="pin" x="40" y="302">GPIO10</text>
  <text class="sig" x="204" y="302" text-anchor="end">SDOUT</text>
  <text class="pin" x="40" y="329">5V</text>
  <text class="sig" x="204" y="329" text-anchor="end">电源</text>

  <rect class="box-b" x="296" y="56" width="186" height="292" rx="12"/>
  <text class="t f-b" x="389" y="86" text-anchor="middle">ES8311</text>
  <text class="s" x="389" y="104" text-anchor="middle">编解码器 · I2C 0x18</text>
  <text class="pin" x="312" y="140">SDA</text>
  <text class="pin" x="312" y="167">SCL</text>
  <text class="pin" x="312" y="194">CLK</text>
  <text class="pin" x="312" y="221">SCK</text>
  <text class="pin" x="312" y="248">LRCK</text>
  <text class="pin" x="312" y="275">SDIN</text>
  <text class="pin" x="312" y="302">SDOUT</text>
  <text class="pin" x="312" y="329">5V</text>

  <line class="ln" x1="220" y1="136" x2="294" y2="136"/>
  <line class="ln" x1="220" y1="163" x2="294" y2="163"/>
  <line class="ln-b" x1="220" y1="190" x2="294" y2="190" marker-end="url(#wmk-c3b)"/>
  <line class="ln-b" x1="220" y1="217" x2="294" y2="217" marker-end="url(#wmk-c3b)"/>
  <line class="ln-b" x1="220" y1="244" x2="294" y2="244" marker-end="url(#wmk-c3b)"/>
  <line class="ln-b" x1="220" y1="271" x2="294" y2="271" marker-end="url(#wmk-c3b)"/>
  <line class="ln-b" x1="294" y1="298" x2="222" y2="298" marker-end="url(#wmk-c3b)"/>
  <line class="ln-p" x1="220" y1="325" x2="294" y2="325" marker-end="url(#wmk-c3)"/>

  <line class="ln-a" x1="482" y1="176" x2="556" y2="176" marker-end="url(#wmk-c3a)"/>
  <text class="s" x="519" y="168" text-anchor="middle">DAC</text>
  <line class="ln-a" x1="556" y1="318" x2="484" y2="318" marker-end="url(#wmk-c3a)"/>
  <text class="s" x="519" y="310" text-anchor="middle">ADC</text>

  <rect class="box-a" x="558" y="104" width="178" height="140" rx="12"/>
  <text class="t f-a" x="647" y="132" text-anchor="middle">NS4150B</text>
  <text class="s" x="647" y="150" text-anchor="middle">3W D 类功放</text>
  <text class="s" x="572" y="182">DAC 输出</text>
  <text class="s" x="572" y="204">EN 硬件上拉 · 常通</text>
  <text class="s" x="572" y="226">OUT → 喇叭</text>

  <rect class="box-a" x="558" y="252" width="178" height="100" rx="12"/>
  <text class="t f-a" x="647" y="280" text-anchor="middle">MIC</text>
  <text class="s" x="647" y="298" text-anchor="middle">模拟麦克风</text>
  <text class="s" x="572" y="322">ADC 输入</text>

  <line class="ln-b" x1="28" y1="382" x2="58" y2="382" marker-end="url(#wmk-c3b)"/>
  <text class="lg" x="68" y="386">I2S 音频 / 时钟</text>
  <line class="ln" x1="200" y1="382" x2="230" y2="382"/>
  <text class="lg" x="240" y="386">I2C 控制（双向）</text>
  <line class="ln-p" x1="370" y1="382" x2="400" y2="382"/>
  <text class="lg" x="410" y="386">电源</text>
  <line class="ln-a" x1="480" y1="382" x2="510" y2="382"/>
  <text class="lg" x="520" y="386">模拟音频</text>
</svg>

### 接线表

| ES8311 引脚 | 信号 | 接到 ESP32-C3 | 说明 |
|-------------|------|---------------|------|
| SDA | I2C 数据 | GPIO4 | 编解码器地址 0x18 |
| SCL | I2C 时钟 | GPIO5 | 与 SDA 同一路 I2C |
| CLK | 主时钟 MCLK | GPIO1 | 4.096MHz，由 ESP32 输出 |
| SCK | 位时钟 BCLK | GPIO3 | 播放与录音共用 |
| LRCK | 帧时钟 WS | GPIO6 | 播放与录音共用 |
| DAC SDIN | DAC 数据输入 | GPIO7 | ESP32 → ES8311 → 喇叭 |
| ADC SDOUT | ADC 数据输出 | GPIO10 | 麦克风 → ES8311 → ESP32 |
| 5V | 电源 | 5V | 模块板载 LDO 降压到 3.3V |

音频链路与方案一相同（ES8311 全双工），只是引脚号不同。

### 注意点

::: tip C3 的内存账
无 PSRAM，固件已做针对性优化（唤醒词引擎会话期间销毁/重建、MP3 解码器按需分配、WebSocket 提前初始化、WiFi/LWIP 缓冲收紧），正常对话流程可稳定运行。无屏幕（headless），状态/表情/字幕以 `[状态] [表情] [字幕]` 文本输出到串口。
:::

## 屏幕（方案一、二共用）

**ST7789**：1.54 寸 TFT 彩色液晶，240×240，SPI 接口，由 ESP-IDF `esp_lcd` 组件 + LVGL 驱动渲染表情动画。方案三（C3）不支持屏幕。

| 屏幕丝印 | 引脚 | GPIO | 说明 |
|----------|------|------|------|
| SDA | MOSI | GPIO39 | SPI 数据输出 |
| SCL | SCLK | GPIO38 | SPI 时钟 |
| SC | CS | GPIO9 | 片选 |
| DC | DC | GPIO13 | 数据 / 命令选择 |
| RES | RST | 接 3V3 | 高电平 = 正常工作，悬空会黑屏 |
| BCLK | BL | GPIO16 | 背光，LEDC PWM 调亮度；方案二需换脚，见表内警告 |

::: warning 屏幕不亮？按顺序排查
1. **背光**：默认板型已配背光脚 `display_bl = GPIO16`（LEDC PWM，开机 100%），`BCLK` 接 GPIO16 可点亮并支持亮度调节（服务端 `set_brightness`，0–100）。不需要调亮度时 `BCLK` 接 3V3 也能常亮，但固件 PWM 输出悬空、亮度不可调。
2. **复位（实测必接）**：`RES` 悬空时多数 ST7789 模块会卡在复位状态，SPI 命令被忽略、黑屏无响应，**RES 必须接 3V3**。固件在无硬件复位脚时会补发软件复位（0x01），配合 RES=3V3 即可正常驱动。
3. **丝印**：`SCL / SDA` 是 SPI 的 `SCLK / MOSI`，**不是** I2C 信号，别与 ES8311 的 SDA/SCL 混淆。常见模块丝印即 `SCL / SDA / RES / DC / SC / BCLK`。
:::

## 唤醒按钮（三种方案通用）

| 方案 | 按钮 | 说明 |
|------|------|------|
| 方案一 / 方案二（ESP32-S3） | GPIO0 | 单击唤醒对话；**2 秒内连按 4 次**清除 WiFi 配置进入配网模式 |
| 方案三（ESP32-C3） | GPIO9（板载 BOOT 键） | 同上，无需外接按钮（GPIO9 即 C3 的 BOOT 引脚） |

::: tip 配网方式
通过 **BLE（NimBLE）** 广播，手机 App 搜索设备完成配网。蓝牙控制器只在配网模式初始化，正常运行不占内存。
:::

## 引脚速查

按方案汇总，方便检查是否撞脚。具体以 `main/boards/defs/<board>.h` 为准。

| 方案 | 音频引脚 | 屏幕引脚 | 按钮 |
|------|----------|----------|------|
| 方案一 · S3 + ES8311 | 4 / 5 / 6 / 15 / 17 / 41 / 42 | 9 / 13 / 16（背光）/ 38 / 39 | 0 |
| 方案二 · S3 + I2S 直连 | 麦克风 4 / 5 / 6，喇叭 15 / 16 / 17 | 9 / 13 / 38 / 39（背光需另选） | 0 |
| 方案三 · C3 + ES8311 | 1 / 3 / 4 / 5 / 6 / 7 / 10 | — | 9（板载） |

<style>
.wiring {
  --w-bg: #ffffff;
  --w-panel: #f6f6f9;
  --w-border: #e5e5ec;
  --w-text: #1d1d1f;
  --w-muted: #8a8a92;
  --w-brand: #7c3aed;
  --w-brand-bg: #f5f1ff;
  --w-brand-line: #a78bfa;
  --w-amber: #b45309;
  --w-amber-bg: #fff8ec;
  --w-amber-line: #e9a13b;
  display: block;
  margin: 18px 0 10px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
}
[data-theme="dark"] .wiring,
html.dark .wiring {
  --w-bg: #1b1b21;
  --w-panel: #242429;
  --w-border: #3a3a44;
  --w-text: #ececf2;
  --w-muted: #9a9aa4;
  --w-brand: #b49aff;
  --w-brand-bg: #282140;
  --w-brand-line: #8b6ce0;
  --w-amber: #f2b972;
  --w-amber-bg: #33291a;
  --w-amber-line: #b07a33;
}
.wiring .bg { fill: var(--w-bg); stroke: var(--w-border); }
.wiring .box-b { fill: var(--w-brand-bg); stroke: var(--w-brand-line); }
.wiring .box-a { fill: var(--w-amber-bg); stroke: var(--w-amber-line); }
.wiring text { fill: var(--w-text); }
.wiring .cap { font-size: 12.5px; font-weight: 600; fill: var(--w-muted); }
.wiring .t { font-size: 13.5px; font-weight: 600; }
.wiring .s { font-size: 10.5px; fill: var(--w-muted); }
.wiring .pin { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; }
.wiring .sig { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 11px; fill: var(--w-muted); }
.wiring .lg { font-size: 10.5px; fill: var(--w-muted); }
.wiring .f-b { fill: var(--w-brand); }
.wiring .f-a { fill: var(--w-amber); }
.wiring .ln { stroke: var(--w-muted); stroke-width: 1.2; }
.wiring .ln-b { stroke: var(--w-brand-line); stroke-width: 1.6; }
.wiring .ln-a { stroke: var(--w-amber-line); stroke-width: 1.4; }
.wiring .ln-p { stroke: var(--w-muted); stroke-width: 1.2; stroke-dasharray: 5 4; }
.wiring .mk { fill: var(--w-muted); }
.wiring .mk-b { fill: var(--w-brand-line); }
.wiring .mk-a { fill: var(--w-amber-line); }
</style>
