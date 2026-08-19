# ES8311 开发指南

> 面向开发者的 ES8311 音频模块使用指南：如何在 esp-ai-idf-client 中正确配置 ES8311，实现清晰的麦克风收音（唤醒词 + ASR）与喇叭播放（TTS），避免杂音、无声、变调等常见问题。

## 模块架构

```
ESP32-S3 (I2S master)                    ES8311 (I2S slave)
  MCLK  ──────────────────────────────►   CLK   (4.096MHz = 16000×256)
  BCLK  ──►                            ──   SCK
  WS    ──►                            ──   LRCK
  DIN   ──► (播放数据 TX)              ──   DAC SDIN
  DOUT  ◄── (收音数据 RX)              ──   ADC SDOUT
  SDA/SCL (I2C 控制)  ◄──────────────►   SDA/SCL (0x18)
```

- **采样率固定 16kHz**：与 WakeNet 唤醒词一致；ES8311 硬件时钟 256× → MCLK=4.096MHz
- **I2S 全双工**：`I2S_NUM_0` 单总线同时承载 TX（播放）与 RX（收音），BCLK/WS 共享
- **相关文件**：
  - `main/audio_codec/es8311.c/.h` — ES8311 寄存器驱动（初始化/音量/静音/时钟）
  - `main/wakeup.c` — 全双工 I2S 通道创建 + MCLK 启动 + 时钟锁存
  - `main/audio.c` — MP3 解码 + 软件重采样 + 播放写入（spk_task）/ 收音发送（mic_task）
  - `main/power_manager.c` — 空闲 15s DAC 静音省电
  - `main/main.c` — 初始化顺序编排（es8311_init 在 WiFi 之前）

## 收音（麦克风 / ADC）

**唤醒词检测**（WakeNet）：`wakeup.c` 创建全双工 I2S RX 通道（16kHz/16bit/mono），`wakenet_task` 从 RX 读音频喂给 AFE+WakeNet。

**ASR 录音**：会话中 `audio_mic_start()` 启动 `mic_task`，从**同一个共享 RX 句柄**（`wakeup_get_mic_handle()`）读取并发送到服务端。

```c
// 收音链路（共享同一 RX 通道，二者通过 s_i2s_mutex 互斥，交替使用）
wakenet_task:  i2s_channel_read(rx, feed_buf, ..., 50ms) → AFE.feed() → WakeNet
mic_task:      i2s_channel_read(rx, buffer, 1024, 100ms)  → websocket_send_binary()
```

- 麦克风增益用 `es8311_set_mic_gain()`（0/6/12/18/24/30dB），默认 12dB
- I2S_NUM_0 只有一个 RX 通道，**收音与唤醒必须共享句柄**，不可重复创建

## 播放（喇叭 / DAC）

`spk_task`（`audio.c`）播放链路：

```
服务端音频帧 → 待播放缓冲 → MP3 解码 → 软件重采样(→16k) → i2s_channel_write(TX)
```

- **ES8311 硬件固定 16kHz**，TTS 通常是 24kHz——必须**软件重采样到 16kHz**（`resample_to_16k`，Catmull-Rom 三次插值），不要运行期切换 I2S 时钟
- 16kHz 音频走 `memcpy` 快速路径，不经重采样
- 播放/收音用同一 I2S 控制器全双工，写入 TX 不影响 RX 收音

## 正确的初始化顺序（避免杂音 / 无声的关键）

初始化顺序是实测验证的，**不要颠倒**：

```
1. es8311_i2c_init()         # I2C 总线创建（WiFi 之前）
2. es8311_init(寄存器配置)    # 配 ADC/DAC/时钟（MCLK 尚未运行）
3. WiFi 初始化
4. wakeup_init() 创建 I2S 通道
5. i2s_channel_enable()      # MCLK 开始稳定输出
6. es8311_power_up()         # MCLK 稳定后锁存时钟 + 上电 ADC/DAC + 解静音
```

::: warning 为什么必须这样
- MCLK 未运行时写 ES8311 时钟寄存器，CSM 无法锁存（REG00 读回 0xFF → master 模式）
- 与 ESP32 I2S master 冲突 → DAC 时钟错乱 → **巨大电流声 / 无收音**
- 因此 `es8311_init`（配寄存器）在 MCLK 前，`es8311_power_up`（锁存）在 MCLK 稳定后
:::

## 避免杂音的关键寄存器

| REG | 写法 | 说明 |
|-----|------|------|
| REG00 | `0x80` | CSM 使能 + slave 模式（**必须 slave**，读到 0xFF 会变 master → 杂音） |
| REG06 | 保留位 | **read-modify-write**：清 bit5（BCLK 不反转），直写会清掉 tri-state 等保留位 → 巨大电流声 |
| REG31 | mute 位 | DAC 静音控制（bit5/6）；空闲省电用，播放前解静音 |
| REG32 | 对数映射 | 音量 0-100 → -49.5dB~0dB（0x00~0xBF）；**不要线性到 0xFF(+32dB)** → 本底噪声被放大 32dB → 嘶嘶声 |
| REG44 | **`0x08`** | 内部参考信号**关闭**；写 `0x58`（bit6=1）会只剩微弱杂音无语音 |

## 时钟与采样率配置

- MCLK = sample_rate × 256（16k → 4.096MHz），由 I2S TX 输出
- coeff 分频表（16k@4.096M）：`{4096000,16000, 0x01,0x00, 0x01,0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20}`
- `es8311_set_sample_rate()` 用 `es8311_check_clock()` 匹配 512/256 倍率，时钟寄存器一律 read-modify-write

## 功耗管理（避免空闲噪音 / 省电）

`power_manager.c`：**空闲 15s 无输出 → DAC 静音**（REG31），播放时自动解静音：

```c
// 空闲关闭
es8311_set_output_enabled(false);   // REG31 置 mute 位
// 恢复播放
es8311_set_output_enabled(true);    // REG31 清 mute 位
```

若长时间 mute 后解静音仍无声，可调用 `es8311_restore_output()`（重新确认 DAC 上电/使能/模拟电源）。

## 运行时健壮性（自愈看门狗）

WiFi 射频会干扰 I2C，ES8311 寄存器可能偶发被写坏 → ADC 失锁 → 收音变静音。`wakeup.c` 内置**麦克风健康看门狗**自动恢复：

- 连续约 2s 读取失败/无数据，或连续约 30s 读到全零 → 判定收音失效
- 自动重跑 `es8311_power_up()`（重锁时钟 + 重上电 ADC/DAC + 解静音），并打印 `[REG诊断]`
- 30s 冷却，仅 ES8311 方案编译生效

## 常用 API 速查

```c
// 初始化（WiFi 之前）
esp_err_t es8311_i2c_init(i2c_port_num_t port, int sda, int scl, uint8_t addr);   // 0x18
esp_err_t es8311_init(i2c_port_num_t port, int sda, int scl, uint8_t addr,
                      uint32_t mclk_fre, uint32_t sample_rate);                   // 4096000, 16000

// 播放
esp_err_t es8311_set_volume(int volume);        // 0-100，对数映射
esp_err_t es8311_set_output_enabled(bool en);   // DAC 静音/解静音
esp_err_t es8311_restore_output(void);          // 长时间 mute 后恢复

// 收音
esp_err_t es8311_set_mic_gain(int gain_db);     // 0/6/12/18/24/30dB
esp_err_t es8311_set_input_enabled(bool en);    // ADC 电源（全双工下通常不关）

// 时钟
esp_err_t es8311_set_sample_rate(uint32_t rate);
bool     es8311_check_clock(uint32_t mclk_fre, uint32_t sample_rate);

// 其他
esp_err_t es8311_power_up(void);        // MCLK 稳定后锁存时钟（幂等，可重复调）
bool     es8311_is_initialized(void);
void     es8311_dump_regs(void);        // 打印 REG 诊断，排障用
```

## 最佳实践清单

1. 先确认板型 `audio_codec` 与 `menuconfig → 音频编解码器` 都选 **ES8311**（选 I2S 直连会收音全静音）
2. I2C 用 100kHz + 读写带重试（400kHz 在 WiFi 运行时不稳定）
3. `es8311_init()` 放在 WiFi 初始化**之前**
4. 先配寄存器 → 再启 MCLK → MCLK 稳定后 `es8311_power_up()`
5. 时钟寄存器一律 read-modify-write，保留位不清零
6. REG44 写 `0x08`，REG32 音量对数映射
7. 非 16kHz 音频软件重采样到 16kHz，不要运行期切 I2S 时钟
8. 全双工 I2S 下收音/唤醒共享 RX 句柄，用互斥锁交替访问

## 相关

- [适配自己的开发板](./idf-board-adaptation) — 板型与音频方案的配置
