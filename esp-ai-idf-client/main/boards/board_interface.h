/**
 * board_interface.h - 板级包接口定义（1000+ 板型架构）
 *
 * 设计理念：
 * - 一个文件定义一个板型（boards/defs/<board_name>.h）
 * - gen_boards.py 自动生成 Kconfig 选项和编译时选择头文件
 * - 组件化配置：音频编解码器、显示屏、扩展硬件均可插拔
 * - 向后兼容：所有原有字段保留，新字段追加在末尾
 *
 * 框架在 app_main() 中调用 board_init()，根据 board_config_t 中的
 * 组件配置自动初始化对应硬件驱动。
 */
#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>   // size_t (board_extra_t.handle_command)

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 音频编解码器类型
 */
typedef enum {
    AUDIO_CODEC_NONE,       // 无外置编解码器（使用 I2S 直连）
    AUDIO_CODEC_ES8388,     // ES8388
    AUDIO_CODEC_PCM5102,    // PCM5102
    AUDIO_CODEC_ES8311,     // ES8311
} audio_codec_type_t;

/**
 * 显示屏类型
 */
typedef enum {
    DISPLAY_TYPE_NONE,      // 无屏幕
    DISPLAY_TYPE_LCD_ST7789,// SPI ST7789 (240x240)
    DISPLAY_TYPE_LCD_ILI9341,// SPI ILI9341 (320x240)
    DISPLAY_TYPE_OLED_SSD1306,// I2C SSD1306 (128x64)
} display_type_t;

/**
 * SPI 总线主机
 */
typedef enum {
    SPI_HOST_UNUSED = -1,
    SPI_HOST_DEFAULT = 0,   // SPI1 (Flash专用，不可用)
    SPI_HOST_2 = 2,         // SPI2 (FSPI, 推荐用于 LCD)
    SPI_HOST_3 = 3,         // SPI3 (HSPI)
} spi_host_id_t;

// ==================== ES8311 编解码器配置 ====================

/**
 * ES8311 专用配置（仅 audio_codec == AUDIO_CODEC_ES8311 时使用）
 * 替代原 Kconfig 中的 CONFIG_AUDIO_ES8311_* 引脚配置
 */
typedef struct {
    int      i2c_port;      // I2C 端口号 (0/1)
    int      i2c_sda;       // I2C SDA 引脚
    int      i2c_scl;       // I2C SCL 引脚
    uint8_t  i2c_addr;      // I2C 地址 (0 = 默认 0x18)
    int      pa_pin;        // PA 功放使能引脚 (-1 = 无功放控制)
    int      mclk_pin;      // MCLK 输出引脚
    uint32_t mclk_freq;     // MCLK 频率 (Hz)，如 4096000
} es8311_config_t;

// ==================== 板级事件类型 ====================

/**
 * 板级事件类型（用于扩展组件的事件回调）
 */
typedef enum {
    BOARD_EVENT_INIT,           // 板级初始化完成
    BOARD_EVENT_DEINIT,         // 板级反初始化
    BOARD_EVENT_WAKEUP,         // 唤醒词或按钮触发
    BOARD_EVENT_AUDIO_START,    // 音频播放开始
    BOARD_EVENT_AUDIO_STOP,     // 音频播放结束
    BOARD_EVENT_NETWORK_UP,     // 网络连接成功
    BOARD_EVENT_NETWORK_DOWN,   // 网络断开
    BOARD_EVENT_OTA_START,      // OTA 升级开始
    BOARD_EVENT_OTA_DONE,       // OTA 升级完成
} board_event_t;

// ==================== 扩展组件接口 ====================

/**
 * 扩展组件描述符（用于触摸屏、LED 灯带、传感器等非核心硬件）
 *
 * 新增硬件类型只需：
 * 1. 定义该硬件的 config 结构体
 * 2. 实现 init/handle_command 函数
 * 3. 在板型定义的 extras 数组中添加条目
 *
 * 无需修改 board_config_t 核心结构
 *
 * 运行时交互：
 * - handle_command: 接收命令字符串，返回 JSON 响应（查询/控制）
 * - on_event: 接收系统事件通知（唤醒/播放/网络等）
 * 两者均可为 NULL（仅 init 的简单组件不需要实现）
 */
typedef struct {
    const char *type;               // 组件类型标识: "touch", "led", "sensor" ...
    const void *config;             // 类型特定配置（组件 init 函数自行解析）
    esp_err_t  (*init)(const void *config);  // 初始化函数
    void       (*deinit)(void);              // 反初始化函数（可为 NULL）

    /**
     * 命令处理器（可为 NULL）
     * @param cmd     命令名称，如 "get_touch" / "set_led"
     * @param args    参数字符串（JSON 或 key=value），可为 NULL
     * @param resp    响应缓冲区
     * @param resp_len 响应缓冲区大小
     * @return ESP_OK 成功, ESP_ERR_NOT_FOUND 命令不支持
     */
    esp_err_t  (*handle_command)(const char *cmd, const char *args,
                                  char *resp, size_t resp_len);

    /**
     * 事件回调（可为 NULL）
     * @param event  事件类型
     * @param data   事件数据（类型取决于事件，可为 NULL）
     */
    void       (*on_event)(board_event_t event, void *data);
} board_extra_t;

// ==================== 板级配置结构体 ====================

/**
 * 板级配置结构体
 *
 * 每个板型定义文件（boards/defs/<name>.h）提供一个 BOARD_CONFIG 实例。
 * gen_boards.py 扫描 defs/ 目录生成 board_select.h，通过 #ifdef 选择当前板型。
 *
 * 字段顺序说明：
 * C++ 指定初始化器（designated initializers）要求按声明顺序赋值。
 * i2s_full_duplex / es8311_cfg 紧跟 audio_codec，确保音频宏展开顺序正确。
 * extras 位于结构体末尾，由 BOARD_EXTRAS_* 宏在板型定义末尾设置。
 */
typedef struct {
    const char *name;           // 板型名称
    const char *description;    // 描述
    const char *bin_id;         // 固件ID（OTA 升级用，每块板型独立）

    // 唤醒按钮
    int wake_button_gpio;       // -1 表示无按钮唤醒

    // 麦克风 I2S
    int mic_i2s_bck;
    int mic_i2s_ws;
    int mic_i2s_data;

    // 扬声器 I2S
    int spk_i2s_bck;
    int spk_i2s_ws;
    int spk_i2s_data;

    // 音频编解码器
    audio_codec_type_t audio_codec;

    // I2S 模式与编解码器配置（紧跟 audio_codec，保证宏展开顺序正确）
    bool i2s_full_duplex;               // true: TX/RX 共享 I2S（ES8311）, false: 独立总线
    const es8311_config_t *es8311_cfg;  // ES8311 配置指针（非 ES8311 时为 NULL）

    // ==================== 显示屏配置 ====================
    display_type_t display_type;    // 显示屏类型
    int display_width;              // 屏幕宽度（0 表示无屏幕）
    int display_height;             // 屏幕高度

    // SPI LCD/OLED 引脚（display_type != NONE 时配置）
    int display_spi_host;           // SPI 主机（SPI2_HOST / SPI3_HOST）
    int display_spi_cs;             // SPI CS 引脚（-1 无效）
    int display_spi_dc;             // SPI DC/数据命令引脚（-1 无效）
    int display_spi_clk;            // SPI CLK 引脚
    int display_spi_mosi;           // SPI MOSI 引脚
    int display_rst;                // 复位引脚（-1 无效）
    int display_bl;                 // 背光引脚（-1 无效）

    // I2C OLED 引脚（可选）
    int display_i2c_sda;            // -1 无效
    int display_i2c_scl;            // -1 无效
    int display_i2c_addr;           // I2C 地址

    // ==================== 服务与表情策略 ====================
    bool official_service;          // true: 默认请求 ESP-AI 官方服务（node.espai.fun）
    bool emotion_builtin_only;      // 已废弃（保留字段兼容既有板型定义）：表情统一从服务器下载

    // ==================== 扩展组件（1000+ 板型架构）====================
    /**
     * 扩展组件数组（NULL 结尾，NULL = 无扩展）
     * 用于触摸屏、LED 灯带、传感器等非核心硬件
     * board_init() 会遍历此数组依次调用各组件的 init 函数
     */
    const board_extra_t *const *extras;

} board_config_t;

// ==================== 公共 API ====================

/**
 * 获取当前板级配置
 * 返回由 board_select.h 选定的 BOARD_CONFIG 实例
 */
const board_config_t *board_get_config(void);

/**
 * 初始化当前板级包
 * 根据配置自动初始化：
 * - 显示屏驱动（LCD/OLED/UART）
 * - ES8311 编解码器（如有）
 * - 扩展组件（如有）
 */
esp_err_t board_init(void);

/**
 * 获取板型信息的 JSON 字符串（用于服务端识别设备能力）
 * 返回静态缓冲区，无需释放
 * 格式: {"name":"...","bin_id":"...","display":"st7789","display_w":240,"display_h":240,"audio_codec":"i2s_direct"}
 */
const char *board_get_info_json(void);

// ==================== 扩展组件运行时 API ====================

/**
 * 向扩展组件分发命令
 * 遍历当前板型的 extras 数组，依次调用 handle_command，
 * 第一个返回 ESP_OK 的组件结果即为最终响应。
 *
 * @param cmd      命令名称
 * @param args     参数（可为 NULL）
 * @param resp     响应缓冲区（可为 NULL，表示不需要响应）
 * @param resp_len 响应缓冲区大小
 * @return ESP_OK 成功, ESP_ERR_NOT_FOUND 无组件处理此命令
 */
esp_err_t board_extra_dispatch(const char *cmd, const char *args,
                                char *resp, size_t resp_len);

/**
 * 向所有扩展组件广播事件
 * 遍历 extras 数组，调用每个组件的 on_event 回调。
 *
 * @param event 事件类型
 * @param data  事件数据（可为 NULL）
 */
void board_extra_broadcast_event(board_event_t event, void *data);

/**
 * 反初始化板级包
 * 遍历 extras 数组调用 deinit，释放扩展组件资源。
 */
void board_deinit(void);

#ifdef __cplusplus
}
#endif
