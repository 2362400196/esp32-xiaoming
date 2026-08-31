# 切换开发板

本文介绍 esp-ai-idf-client 内置的 4 种板型、差异与切换方法。**同一块硬件(1.54 寸 LCD 板)可互刷不同板型固件,引脚完全一致**。

## 板型总览

项目通过编译期配置选择板型,内置 4 种:

| 选项 | 说明 | 适用场景 |
|------|------|---------|
| `面包板无屏幕 (esp32s3_breadboard)` | ESP32-S3 面包板(无屏幕) | 低成本方案,无显示需求 |
| `面包板 1.54寸 LCD (esp32s3_breadboard_1.54_lcd)` | ESP32-S3 面包板 + 1.54 寸 TFT 屏幕 | **连自定义服务(自建 esp-ai-server)推荐**,`sdkconfig.defaults` 默认选择 |
| `面包板 1.54寸 LCD 官方服务版 (esp32s3_breadboard_1.54_lcd_official)` | 同上硬件,官方服务适配 | **连官方服务(espai.fun)推荐** |
| `ESP32-C3 SuperMini (esp32c3_supermini)` | **不同芯片**(ESP32-C3),单核无 PSRAM,无屏,ES8311 全双工 | 低成本 C3 板,需先 `idf.py set-target esp32c3` |

## 板型差异

| 差异点 | 普通板 `esp32s3_breadboard_1.54_lcd` | 官方服务版 `esp32s3_breadboard_1.54_lcd_official` |
|--------|-----------------------------|-------------------------------------------|
| 默认服务器 | 无配置时连本地默认地址 | 无配置时连官方 `node.espai.fun` |
| 表情 | 可下载服务端表情包(下载失败回退内置) | 只用编译内置表情,忽略 `refresh_emo` |
| 音乐播放 | HTTP 流式(`network_audio`) | 官方 WS 推流(play_audio + `play_music`) |
| 流控上报 | 剩余空间语义 | 已缓冲字节语义 |
| OTA bin_id | 普通板 ID | 官方板独立 ID |

> **选择建议**:用**自定义服务(自建 esp-ai-server)就编译普通板 `esp32s3_breadboard_1.54_lcd`**——自定义服务是完整适配重点,表情可下载、行为与 Arduino 官方客户端一致;用官方云服务(espai.fun)才需要官方服务版。两块板型连自定义服务时都能正常对话,差异仅在表情下载与 OTA 标识。

## ESP32-C3 板型说明（跨芯片切换）

`esp32c3_supermini` 是**不同芯片**（ESP32-C3，单核 160MHz、无 PSRAM、4MB Flash），与其他 S3 板型不能直接互刷：

```bash
# 切到 C3
idf.py set-target esp32c3      # 会同时把 sdkconfig 切到 C3（sdkconfig.defaults.esp32c3 生效：4MB 分区、ES8311、无屏）
idf.py menuconfig              # 选择开发板型号 → [ESP32C3] esp32c3_supermini
idf.py build flash

# 切回 S3
idf.py set-target esp32s3
idf.py menuconfig              # 选择开发板型号 → S3 板型
idf.py build flash
```

C3 板型的限制：

- **音频必须 ES8311 全双工**（C3 只有 I2S0，I2S 直连方案在 C3 上不可用）
- **无屏幕**（UART 串口输出状态），表情/GIF 自动跳过
- **4MB Flash、工厂单槽分区，无 OTA 双槽**（固件约 3.4MB，分区剩余约 4%）
- 内存偏紧（无 PSRAM），核心对话/唤醒可用，Lua/音乐等重功能不建议启用

> **注意**:`sdkconfig` 是项目级共享的,`set-target` 会改写它。切回 S3 后记得 `idf.py set-target esp32s3` 恢复,否则 S3 板型无法编译。

## 切换方法

### 方式一:menuconfig(可视化,推荐)

```bash
idf.py menuconfig
```

进入 `选择开发板型号`,用**方向键**选择,回车确认,按 `S` 保存,按 `Q` 退出。

### 方式二:直接改 `sdkconfig`

编辑 `sdkconfig`(或 `sdkconfig.board`),把板型配置换成目标板。例如从官方服务版切回普通板:

```
# CONFIG_BOARD_ESP32S3_BREADBOARD_1_54_LCD_OFFICIAL is not set
CONFIG_BOARD_ESP32S3_BREADBOARD_1_54_LCD=y
```

### 方式三:删除 `sdkconfig` 重新生成

`sdkconfig.defaults` 默认就是普通板,删掉再编译即可:

```bash
rm sdkconfig        # Windows: Remove-Item sdkconfig
idf.py build
```

切换板型后重新编译:

```bash
idf.py reconfigure
idf.py build
```

> **注意**:板型选择是**编译期**配置——固件连哪个服务由配网时的服务器配置决定(官方服务版配网填 `ext4/ext5/ext6` 也可连自定义服务),板型只影响默认地址、表情策略等编译期行为。

## 配网切换服务端

烧录后配网时选择服务类型:

| 配网选项 | 填写内容 | 效果 |
|----------|---------|------|
| 使用开放平台服务 | 开放平台 API Key(ext1) | 连官方服务 |
| 使用自定义服务 | `ext4`=协议、`ext5`=地址、`ext6`=端口 | 连自建 esp-ai-server |

> 自定义服务必须三个字段都填写,否则会 fall 到默认服务器分支。
