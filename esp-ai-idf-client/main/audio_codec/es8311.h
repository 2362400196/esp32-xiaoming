/**
 * es8311.h - ES8311 音频编解码器驱动（IDF 版）
 *
 * 移植自 arduino-audio-driver 的 es8311.c（乐鑫官方驱动），
 * 适配 ESP-IDF v6 的 i2c_master 新驱动 API。
 * 只保留本项目需要的功能：初始化（时钟/采样率/格式/解静音）。
 *
 * ES8311 方案（menuconfig → 音频编解码器 → ES8311）：
 *   - I2S 数据：ESP32 I2S_NUM_0 全双工，TX→ES8311 DACDATA，RX←ES8311 ADCDATA
 *   - MCLK：由 I2S TX 输出（16kHz × 256 = 4.096MHz，对齐 xiaozhi）
 *   - 控制：I2C 写寄存器；NS4150B 功放使能脚拉高
 */
#pragma once

#include "esp_err.h"
#include "driver/i2c_master.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 提前创建 I2C 总线和设备（在 WiFi 之前调用）
 *
 * 对齐 xiaozhi-esp32 的 InitializeI2c()：I2C 总线在 WiFi 之前
 * 创建一次，之后永不删除/重建。es8311_init() 会跳过已创建的总线。
 *
 * @param port I2C 端口号
 * @param sda  I2C SDA 引脚
 * @param scl  I2C SCL 引脚
 * @param addr ES8311 I2C 地址（0 = 默认 0x18）
 * @return ESP_OK 或错误码
 */
esp_err_t es8311_i2c_init(i2c_port_num_t port, int sda, int scl, uint8_t addr);

/**
 * @brief 初始化 ES8311 编解码器寄存器
 *
 * 若 es8311_i2c_init() 已提前调用，则跳过总线创建，仅写寄存器。
 *
 * @param port     I2C 端口号
 * @param sda      I2C SDA 引脚
 * @param scl      I2C SCL 引脚
 * @param addr     ES8311 I2C 地址（默认 0x18）
 * @param mclk_fre 输入 MCLK 频率（Hz），如 4096000
 * @param sample_rate ADC/DAC 采样率（本项目固定 16000）
 * @return esp_err_t
 */
esp_err_t es8311_init(i2c_port_num_t port, int sda, int scl, uint8_t addr,
                      uint32_t mclk_fre, uint32_t sample_rate);

/**
 * @brief 配置 I2S 数据格式（16bit / 标准 I2S）
 */
esp_err_t es8311_set_format_16bit_i2s(void);

/**
 * @brief 运行期切换 ADC/DAC 采样率（配合 I2S 时钟重配使用）
 *
 * MCLK 取 256×sample_rate（对齐 xiaozhi: 16k→4.096MHz）。
 *
 * @param sample_rate 目标采样率（Hz），如 16000 / 44100 / 48000
 * @return ESP_OK 或错误码（coeff 表无匹配时 ESP_ERR_NOT_SUPPORTED）
 */
esp_err_t es8311_set_sample_rate(uint32_t sample_rate);

/**
 * @brief 查询 MCLK/采样率组合是否在 ES8311 时钟分频表内（audio.c 选 I2S mclk_multiple 用）
 */
bool es8311_check_clock(uint32_t mclk_fre, uint32_t sample_rate);

/**
 * @brief 解除 DAC 静音并设置输出音量（0~100）
 */
esp_err_t es8311_set_volume(int volume);

/**
 * @brief ADC/DAC 上电 + 解静音（幂等，可重复调用）
 *
 * 对齐 esp_codec_dev es8311_start(CODEC_MODE_BOTH) 的寄存器序列。
 * I2S 时钟重配（MCLK stop/start）可能导致 ES8311 失锁，重配完成后
 * 再次调用本函数可让 DAC/ADC 重新恢复工作。
 */
esp_err_t es8311_power_up(void);

/**
 * @brief 设置 ADC 麦克风增益（dB：0/6/12/18/24/30）
 */
esp_err_t es8311_set_mic_gain(int gain_db);

/**
 * @brief 回读并打印关键寄存器状态（REG 诊断）
 *
 * 用于运行时区分"I2C 未写入 vs 寄存器被干扰写坏 vs 时钟未锁定"。
 * 麦克风失效自愈（wakeup.c 看门狗）后调用，便于确认根因。
 */
void es8311_dump_regs(void);

/**
 * @brief 使能/禁用 DAC 输出（静音控制）
 *
 * 功耗管理接口：通过寄存器 0x31 bit5 控制 DAC 静音。
 * 禁用时 DAC 输出静音，配合 PA 关闭可显著降低待机功耗。
 *
 * @param enabled true=解静音 DAC, false=静音 DAC
 * @return ESP_OK 或错误码
 */
esp_err_t es8311_set_output_enabled(bool enabled);

/**
 * @brief 空闲关闭后恢复 DAC 输出（长时间 mute 后仅解静音可能不够）
 *
 * 重新确认 DAC 上电/使能/模拟电源并解静音；不修改音量与采样率配置。
 */
esp_err_t es8311_restore_output(void);

/**
 * @brief 使能/禁用 ADC 输入（麦克风）
 *
 * 功耗管理接口：通过寄存器 0x12 控制 ADC 电源。
 * 注意：全双工 I2S 方案下 ADC 始终需要工作（唤醒词检测），通常不单独禁用。
 *
 * @param enabled true=使能 ADC, false=禁用 ADC
 * @return ESP_OK 或错误码
 */
esp_err_t es8311_set_input_enabled(bool enabled);

/**
 * @brief 查询 ES8311 是否已成功初始化
 *
 * 其他模块应通过本函数判断是否可安全调用 ES8311 I2C 操作。
 *
 * @return true=已初始化可正常使用, false=初始化失败勿调用 I2C 操作
 */
bool es8311_is_initialized(void);

#ifdef __cplusplus
}
#endif
