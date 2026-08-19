/**
 * es8311.c - ES8311 音频编解码器驱动（IDF 版）
 *
 * 移植自 arduino-audio-driver 的 es8311.c（乐鑫官方驱动，MIT 许可），
 * 适配 ESP-IDF v6 i2c_master 新 API。仅保留本项目所需功能。
 *
 * 设计原则（对齐 xiaozhi-esp32）：
 *   - I2C 总线在 WiFi 之前通过 es8311_i2c_init() 创建一次，永不删除/重建
 *   - 不做 GPIO 总线恢复（xiaozhi 不需要，恢复反而干扰 I2C 驱动引脚配置）
 *   - 不做重试/验证/探测（xiaozhi 用 ESP_ERROR_CHECK，失败即 abort）
 *   - I2C 速率 400kHz（与 xiaozhi I2cDevice 一致）
 *   - 功耗管理仅通过 PA GPIO 控制（不写 I2C 寄存器）
 */

#include "es8311.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

#define TAG "es8311"

/* ==================== ES8311 寄存器地址 ==================== */
#define ES8311_RESET_REG00      0x00  /* reset digital,csm,clock manager */
#define ES8311_CLK_MANAGER_REG01 0x01 /* clk src for mclk, enable clock */
#define ES8311_CLK_MANAGER_REG02 0x02 /* clk divider and multiplier */
#define ES8311_CLK_MANAGER_REG03 0x03 /* adc fsmode and osr */
#define ES8311_CLK_MANAGER_REG04 0x04 /* dac osr */
#define ES8311_CLK_MANAGER_REG05 0x05 /* clk divider for adc and dac */
#define ES8311_CLK_MANAGER_REG06 0x06 /* bclk inverter and divider */
#define ES8311_CLK_MANAGER_REG07 0x07 /* lrck divider */
#define ES8311_CLK_MANAGER_REG08 0x08 /* lrck divider */
#define ES8311_SDPIN_REG09      0x09  /* dac serial digital port */
#define ES8311_SDPOUT_REG0A     0x0A  /* adc serial digital port */
#define ES8311_SYSTEM_REG0B     0x0B
#define ES8311_SYSTEM_REG0C     0x0C
#define ES8311_SYSTEM_REG0D     0x0D
#define ES8311_SYSTEM_REG0E     0x0E
#define ES8311_SYSTEM_REG0F     0x0F
#define ES8311_SYSTEM_REG10     0x10
#define ES8311_SYSTEM_REG11     0x11
#define ES8311_SYSTEM_REG12     0x12 /* Enable DAC */
#define ES8311_SYSTEM_REG13     0x13
#define ES8311_SYSTEM_REG14     0x14 /* select DMIC, analog pga gain */
#define ES8311_ADC_REG15        0x15
#define ES8311_ADC_REG16        0x16
#define ES8311_ADC_REG17        0x17 /* ADC volume */
#define ES8311_ADC_REG1B        0x1B /* ADC hpf s1 */
#define ES8311_ADC_REG1C        0x1C /* ADC hpf s2 */
#define ES8311_DAC_REG31        0x31 /* DAC mute */
#define ES8311_DAC_REG32        0x32 /* DAC volume */
#define ES8311_DAC_REG37        0x37 /* DAC ramprate */
#define ES8311_GPIO_REG44       0x44 /* GPIO, 内部参考信号路由 (esp_codec_dev 写 0x08) */
#define ES8311_GP_REG45         0x45

#define ES8311_ADDR_DEFAULT     0x18
#define ES8311_MCLK_DIV_FRE     256   /* mclk = fs * 256 (对齐 xiaozhi: 16k→4.096MHz) */

/* ==================== 时钟系数表（coeff_div） ==================== */
/*
 * 注意：字段顺序必须与乐鑫官方驱动一致（lrck_h/lrck_l/bclk_div 在 adc_osr/dac_osr 之前）！
 * 此前移植版把这两个位置调换，但表数据是按官方顺序拷贝的，导致 REG03/04/06/07/08
 * 全部错位写入（16k@8.192MHz 时 REG03=0x00 而官方应为 0x10、REG04=0xFF 而官方应为 0x10…），
 * ADC/DAC 时钟分频错误 → ES8311 无法正常工作（无声 + 无收音）。
 */
struct coeff_div {
    uint32_t mclk;
    uint32_t rate;
    uint8_t pre_div;
    uint8_t pre_multi;
    uint8_t adc_div;
    uint8_t dac_div;
    uint8_t fs_mode;
    uint8_t lrck_h;
    uint8_t lrck_l;
    uint8_t bclk_div;
    uint8_t adc_osr;
    uint8_t dac_osr;
};

static const struct coeff_div coeff_div[] = {
    /* 8k */
    {12288000, 8000, 0x06, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {18432000, 8000, 0x03, 0x02, 0x03, 0x03, 0x00, 0x05, 0xff, 0x18, 0x10, 0x20},
    {16384000, 8000, 0x08, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {8192000, 8000, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {6144000, 8000, 0x03, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {4096000, 8000, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {3072000, 8000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {2048000, 8000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {1536000, 8000, 0x03, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {1024000, 8000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},

    /* 11.025k */
    {11289600, 11025, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {5644800, 11025, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {2822400, 11025, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1411200, 11025, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 12k */
    {12288000, 12000, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {6144000, 12000, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {3072000, 12000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1536000, 12000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 16k */
    {12288000, 16000, 0x03, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {18432000, 16000, 0x03, 0x02, 0x03, 0x03, 0x00, 0x02, 0xff, 0x0c, 0x10, 0x20},
    {16384000, 16000, 0x04, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {8192000, 16000, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {6144000, 16000, 0x03, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {4096000, 16000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {3072000, 16000, 0x03, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {2048000, 16000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {1536000, 16000, 0x03, 0x08, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},
    {1024000, 16000, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x20},

    /* 22.05k */
    {11289600, 22050, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {5644800, 22050, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {2822400, 22050, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1411200, 22050, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 24k */
    {12288000, 24000, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {18432000, 24000, 0x03, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {6144000, 24000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {3072000, 24000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1536000, 24000, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 32k */
    {12288000, 32000, 0x03, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {18432000, 32000, 0x03, 0x04, 0x03, 0x03, 0x00, 0x02, 0xff, 0x0c, 0x10, 0x10},
    {16384000, 32000, 0x02, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {8192000, 32000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {6144000, 32000, 0x03, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {4096000, 32000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {3072000, 32000, 0x03, 0x08, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {2048000, 32000, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1536000, 32000, 0x03, 0x08, 0x01, 0x01, 0x01, 0x00, 0x7f, 0x02, 0x10, 0x10},
    {1024000, 32000, 0x01, 0x08, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 44.1k */
    {11289600, 44100, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {5644800, 44100, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {2822400, 44100, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1411200, 44100, 0x01, 0x08, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},

    /* 48k */
    {12288000, 48000, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {18432000, 48000, 0x03, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {6144000, 48000, 0x01, 0x02, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {3072000, 48000, 0x01, 0x04, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
    {1536000, 48000, 0x01, 0x08, 0x01, 0x01, 0x00, 0x00, 0xff, 0x04, 0x10, 0x10},
};

static i2c_master_bus_handle_t s_i2c_bus = NULL;
static i2c_master_dev_handle_t s_dev = NULL;
static bool s_initialized = false;

/* I2C 传输超时：100ms */
#define ES8311_I2C_TIMEOUT_MS  100

/* I2C 重试次数：WiFi 射频可能干扰 I2C，导致偶发超时。
 * 重试可显著提高寄存器配置成功率（避免 REG00=0xFF → master 模式 → 杂音）。 */
#define ES8311_I2C_RETRY       3

/* I2C 时钟速率：100kHz（比 400kHz 更抗干扰）。
 * 实测 400kHz 在 WiFi 运行后偶发 I2C transaction timeout（REG 读回 0xFF → 时钟错乱 → 杂音），
 * 降到 100kHz 可显著改善稳定性。 */
#define ES8311_I2C_SPEED_HZ    100000

static esp_err_t es8311_write_reg(uint8_t reg_addr, uint8_t data)
{
    uint8_t buf[2] = { reg_addr, data };
    if (!s_dev) return ESP_ERR_INVALID_STATE;
    esp_err_t err = ESP_ERR_TIMEOUT;
    for (int i = 0; i < ES8311_I2C_RETRY; i++) {
        err = i2c_master_transmit(s_dev, buf, sizeof(buf), pdMS_TO_TICKS(ES8311_I2C_TIMEOUT_MS));
        if (err == ESP_OK) {
            return ESP_OK;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return err;
}

static int es8311_read_reg(uint8_t reg_addr)
{
    uint8_t data = 0;
    if (!s_dev) return -1;
    for (int i = 0; i < ES8311_I2C_RETRY; i++) {
        if (i2c_master_transmit_receive(s_dev, &reg_addr, 1, &data, 1, pdMS_TO_TICKS(ES8311_I2C_TIMEOUT_MS)) == ESP_OK) {
            return (int)data;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return -1;
}

static int get_coeff(uint32_t mclk, uint32_t rate)
{
    for (unsigned i = 0; i < sizeof(coeff_div) / sizeof(coeff_div[0]); i++) {
        if (coeff_div[i].rate == rate && coeff_div[i].mclk == mclk) {
            return i;
        }
    }
    return -1;
}

/**
 * 按 MCLK/采样率写入时钟分频寄存器（coeff_div 表），供 init 和运行期切换采样率复用
 *
 * 对齐 esp_codec_dev es8311_config_sample()：使用 read-modify-write，
 * 保留各寄存器的未用位（REG02[2:0], REG03[7], REG04[7], REG06[7:5], REG07[7:6]），
 * 这些位可能含 BCLK 反转 / tri-state / 保留控制，直写清 0 会导致时钟错乱（巨大电流杂音）。
 */
static esp_err_t es8311_config_clock(uint32_t mclk_fre, uint32_t sample_rate)
{
    int coeff = get_coeff(mclk_fre, sample_rate);
    if (coeff < 0) {
        ESP_LOGE(TAG, "无法匹配 %dHz 采样率与 %dHz MCLK", sample_rate, mclk_fre);
        return ESP_ERR_NOT_SUPPORTED;
    }

    uint8_t datmp = 0;
    switch (coeff_div[coeff].pre_multi) {
        case 1:  datmp = 0; break;
        case 2:  datmp = 1; break;
        case 4:  datmp = 2; break;
        case 8:  datmp = 3; break;
        default: break;
    }

    /* 逐个计算寄存器完整值（读回失败时保留位按 0 处理，不引入 -1 污染） */
    uint8_t val_reg02, val_reg03, val_reg04, val_reg05, val_reg06, val_reg07, val_reg08;

    int rd02 = es8311_read_reg(ES8311_CLK_MANAGER_REG02);
    val_reg02 = (rd02 >= 0 ? (uint8_t)rd02 : 0x00) & 0x07;
    val_reg02 |= (coeff_div[coeff].pre_div - 1) << 5;
    val_reg02 |= (datmp) << 3;

    val_reg05 = 0x00;
    val_reg05 |= (coeff_div[coeff].adc_div - 1) << 4;
    val_reg05 |= (coeff_div[coeff].dac_div - 1) << 0;

    int rd03 = es8311_read_reg(ES8311_CLK_MANAGER_REG03);
    val_reg03 = (rd03 >= 0 ? (uint8_t)rd03 : 0x00) & 0x80;
    val_reg03 |= coeff_div[coeff].fs_mode << 6;
    val_reg03 |= coeff_div[coeff].adc_osr << 0;

    int rd04 = es8311_read_reg(ES8311_CLK_MANAGER_REG04);
    val_reg04 = (rd04 >= 0 ? (uint8_t)rd04 : 0x00) & 0x80;
    val_reg04 |= coeff_div[coeff].dac_osr << 0;

    int rd07 = es8311_read_reg(ES8311_CLK_MANAGER_REG07);
    val_reg07 = (rd07 >= 0 ? (uint8_t)rd07 : 0x00) & 0xC0;
    val_reg07 |= coeff_div[coeff].lrck_h << 0;

    val_reg08 = coeff_div[coeff].lrck_l;

    int rd06 = es8311_read_reg(ES8311_CLK_MANAGER_REG06);
    val_reg06 = (rd06 >= 0 ? (uint8_t)rd06 : 0x00) & 0xE0;
    if (coeff_div[coeff].bclk_div < 19) {
        val_reg06 |= (coeff_div[coeff].bclk_div - 1) << 0;
    } else {
        val_reg06 |= coeff_div[coeff].bclk_div << 0;
    }

    /* 写入 */
    es8311_write_reg(ES8311_CLK_MANAGER_REG02, val_reg02);
    es8311_write_reg(ES8311_CLK_MANAGER_REG05, val_reg05);
    es8311_write_reg(ES8311_CLK_MANAGER_REG03, val_reg03);
    es8311_write_reg(ES8311_CLK_MANAGER_REG04, val_reg04);
    es8311_write_reg(ES8311_CLK_MANAGER_REG07, val_reg07);
    es8311_write_reg(ES8311_CLK_MANAGER_REG08, val_reg08);
    es8311_write_reg(ES8311_CLK_MANAGER_REG06, val_reg06);

    return ESP_OK;
}

/**
 * 查询给定 MCLK/采样率组合是否在 coeff_div 表内（audio.c 选 I2S mclk_multiple 用）
 */
bool es8311_check_clock(uint32_t mclk_fre, uint32_t sample_rate)
{
    return get_coeff(mclk_fre, sample_rate) >= 0;
}

/**
 * 运行期切换采样率：I2S 时钟重配后调用，同步 ES8311 内部时钟分频
 *
 * MCLK 取 256×sample_rate（对齐 xiaozhi: 16k→4.096MHz, 24k→6.144MHz）。
 */
esp_err_t es8311_set_sample_rate(uint32_t sample_rate)
{
    uint32_t mclk_fre = sample_rate * ES8311_MCLK_DIV_FRE;  /* 256 倍 */
    if (get_coeff(mclk_fre, sample_rate) < 0) {
        mclk_fre = sample_rate * 256;
    }
    esp_err_t err = es8311_config_clock(mclk_fre, sample_rate);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "ES8311 采样率切换: %dHz, MCLK=%dHz", sample_rate, mclk_fre);
    }
    return err;
}

/**
 * @brief 提前创建 I2C 总线和设备（在 WiFi 之前调用）
 *
 * 对齐 xiaozhi-esp32 的 InitializeI2c()：I2C 总线在板级构造函数中
 * （WiFi 之前）创建一次，之后永不删除/重建。
 *
 * 必须在 es8311_init() 之前调用。es8311_init() 会跳过已创建的总线，
 * 仅执行寄存器配置。
 *
 * @param port I2C 端口号
 * @param sda  I2C SDA 引脚
 * @param scl  I2C SCL 引脚
 * @param addr ES8311 I2C 地址（0 = 默认 0x18）
 * @return ESP_OK 或错误码
 */
esp_err_t es8311_i2c_init(i2c_port_num_t port, int sda, int scl, uint8_t addr)
{
    if (addr == 0) addr = ES8311_ADDR_DEFAULT;

    /* 总线只创建一次（对齐 xiaozhi：InitializeI2c 中 ESP_ERROR_CHECK 一次性创建） */
    if (s_i2c_bus == NULL) {
        i2c_master_bus_config_t bus_cfg = {
            .i2c_port = port,
            .sda_io_num = sda,
            .scl_io_num = scl,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .flags = { .enable_internal_pullup = true },
        };
        esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_i2c_bus);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "I2C 总线创建失败: %s", esp_err_to_name(err));
            return err;
        }
        ESP_LOGI(TAG, "I2C 总线创建成功: port=%d, SDA=%d, SCL=%d, %dkHz",
                 port, sda, scl, ES8311_I2C_SPEED_HZ / 1000);
    }

    /* 设备只添加一次 */
    if (s_dev == NULL) {
        i2c_device_config_t dev_cfg = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = addr,
            .scl_speed_hz = ES8311_I2C_SPEED_HZ,
        };
        esp_err_t err = i2c_master_bus_add_device(s_i2c_bus, &dev_cfg, &s_dev);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "ES8311 设备添加失败: %s", esp_err_to_name(err));
            return err;
        }
    }

    return ESP_OK;
}

esp_err_t es8311_init(i2c_port_num_t port, int sda, int scl, uint8_t addr,
                      uint32_t mclk_fre, uint32_t sample_rate)
{
    if (addr == 0) addr = ES8311_ADDR_DEFAULT;

    s_initialized = false;

    /* 确保总线和设备已创建（若 es8311_i2c_init() 已提前调用则跳过） */
    if (s_i2c_bus == NULL || s_dev == NULL) {
        esp_err_t err = es8311_i2c_init(port, sda, scl, addr);
        if (err != ESP_OK) return err;
    }

    /* ==== 初始化寄存器序列（对齐 esp_codec_dev es8311_open）==== */

    /* 软件复位（对齐 xiaozhi ResetCodec）：写 0x1F 到 REG00，延时 5ms */
    es8311_write_reg(ES8311_RESET_REG00, 0x1F);
    vTaskDelay(pdMS_TO_TICKS(5));

    /* 对齐 esp_codec_dev es8311_open：先确保 ADC/DAC 下电态（REG0D=0xFA），
     * 避免从残留上电态直接配置导致时钟错乱 */
    {
        int reg0d = es8311_read_reg(ES8311_SYSTEM_REG0D);
        if (reg0d != 0xFA) {
            es8311_write_reg(ES8311_SYSTEM_REG0D, 0xFA);
        }
    }

    /* REG44: I2C 抗扰增强（对齐 esp_codec_dev，先写两次 0x08） */
    es8311_write_reg(ES8311_GPIO_REG44, 0x08);
    vTaskDelay(pdMS_TO_TICKS(5));
    es8311_write_reg(ES8311_GPIO_REG44, 0x08);

    /* 时钟管理器初始配置 */
    es8311_write_reg(ES8311_CLK_MANAGER_REG01, 0x30);  /* 开启 MCLK 和 BCLK 时钟控制 */
    es8311_write_reg(ES8311_CLK_MANAGER_REG02, 0x00);
    es8311_write_reg(ES8311_CLK_MANAGER_REG03, 0x10);
    es8311_write_reg(ES8311_ADC_REG16, 0x24);
    es8311_write_reg(ES8311_CLK_MANAGER_REG04, 0x10);
    es8311_write_reg(ES8311_CLK_MANAGER_REG05, 0x00);
    es8311_write_reg(ES8311_SYSTEM_REG0B, 0x00);
    es8311_write_reg(ES8311_SYSTEM_REG0C, 0x00);
    es8311_write_reg(ES8311_SYSTEM_REG10, 0x1F);
    es8311_write_reg(ES8311_SYSTEM_REG11, 0x7F);

    /* 使能 CSM（Clock State Machine），Slave 模式（ESP32 为 I2S master） */
    es8311_write_reg(ES8311_RESET_REG00, 0x80);
    vTaskDelay(pdMS_TO_TICKS(5));

    /* 对齐 esp_codec_dev es8311_open：读回 REG00 并设为 Slave 模式（清 bit6） */
    {
        int reg00 = es8311_read_reg(ES8311_RESET_REG00);
        if (reg00 >= 0) {
            es8311_write_reg(ES8311_RESET_REG00, (uint8_t)reg00 & 0xBF);
        }
    }

    /* 0x3F = 所有时钟使能 + on 频率分频；use_mclk=true 时清 bit7（MCLK 引脚做时钟源） */
    es8311_write_reg(ES8311_CLK_MANAGER_REG01, 0x3F);

    /* 对齐 esp_codec_dev es8311_open：读 REG06 清 bit5（SCLK/BCLK 不反转）。
     * 若 BCLK 反转，I2S 数据在时钟沿采错位 → 巨大电流杂音。 */
    {
        int reg06 = es8311_read_reg(ES8311_CLK_MANAGER_REG06);
        if (reg06 >= 0) {
            es8311_write_reg(ES8311_CLK_MANAGER_REG06, (uint8_t)reg06 & ~0x20);
        }
    }

    /* 时钟分频（coeff_div），按 MCLK/采样率匹配（read-modify-write 保留未用位） */
    esp_err_t clk_err = es8311_config_clock(mclk_fre, sample_rate);
    if (clk_err != ESP_OK) {
        return clk_err;
    }

    es8311_write_reg(ES8311_SYSTEM_REG13, 0x10);
    es8311_write_reg(ES8311_ADC_REG1B, 0x0A);
    es8311_write_reg(ES8311_ADC_REG1C, 0x6A);

    /* REG44: 内部参考信号。
     * 注意：esp_codec_dev 默认 no_dac_ref=false 写 0x58（bit6=1，启用 DAC 内部参考），
     * 但实测本模块写 0x58 后只有微弱杂音无语音（REG44=0x58），
     * 保持 bit6=0 写 0x08 时语音正常。故此处用 no_dac_ref=true 的 0x08。 */
    es8311_write_reg(ES8311_GPIO_REG44, 0x08);

    /* 16bit / 标准 I2S 格式 */
    es8311_set_format_16bit_i2s();

    /* ADC/DAC 上电 + 解静音 */
    es8311_power_up();

    s_initialized = true;
    ESP_LOGI(TAG, "ES8311 初始化完成: %dHz, MCLK=%dHz, addr=0x%02X", sample_rate, mclk_fre, addr);

    /* 诊断：回读关键寄存器，确认写入生效（区分 I2C 未写入 vs 时钟未锁定） */
    es8311_dump_regs();
    return ESP_OK;
}

void es8311_dump_regs(void)
{
    ESP_LOGI(TAG, "[REG诊断] 00=%02X 01=%02X 02=%02X 03=%02X 04=%02X 05=%02X 06=%02X 07=%02X 08=%02X",
             (uint8_t)es8311_read_reg(0x00), (uint8_t)es8311_read_reg(0x01),
             (uint8_t)es8311_read_reg(0x02), (uint8_t)es8311_read_reg(0x03),
             (uint8_t)es8311_read_reg(0x04), (uint8_t)es8311_read_reg(0x05),
             (uint8_t)es8311_read_reg(0x06), (uint8_t)es8311_read_reg(0x07),
             (uint8_t)es8311_read_reg(0x08));
    ESP_LOGI(TAG, "[REG诊断] 09=%02X 0A=%02X 0D=%02X 0E=%02X 12=%02X 14=%02X 16=%02X 17=%02X 31=%02X 32=%02X 44=%02X",
             (uint8_t)es8311_read_reg(0x09), (uint8_t)es8311_read_reg(0x0A),
             (uint8_t)es8311_read_reg(0x0D), (uint8_t)es8311_read_reg(0x0E),
             (uint8_t)es8311_read_reg(0x12), (uint8_t)es8311_read_reg(0x14),
             (uint8_t)es8311_read_reg(0x16), (uint8_t)es8311_read_reg(0x17),
             (uint8_t)es8311_read_reg(0x31), (uint8_t)es8311_read_reg(0x32),
             (uint8_t)es8311_read_reg(0x44));
}

bool es8311_is_initialized(void)
{
    return s_initialized;
}

esp_err_t es8311_set_format_16bit_i2s(void)
{
    /*
     * 对齐 esp_codec_dev es8311_set_bits_per_sample(16) + es8311_config_fmt(I2S_NORMAL)：
     * 读回 REG09/0A，清 bit1:0（标准 I2S），置 bit3:2（16bit），保留其他位。
     * 直接写 0x0c 会覆盖 bit7/5/4 等保留/功能位。
     */
    int dac_iface = es8311_read_reg(ES8311_SDPIN_REG09);
    int adc_iface = es8311_read_reg(ES8311_SDPOUT_REG0A);
    if (dac_iface >= 0) {
        uint8_t dac = ((uint8_t)dac_iface & 0xFC) | 0x0c;
        es8311_write_reg(ES8311_SDPIN_REG09, dac);
    }
    if (adc_iface >= 0) {
        uint8_t adc = ((uint8_t)adc_iface & 0xFC) | 0x0c;
        es8311_write_reg(ES8311_SDPOUT_REG0A, adc);
    }
    return ESP_OK;
}

esp_err_t es8311_set_volume(int volume)
{
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    /* 解静音：读取失败用 0x00（安全默认值） */
    int reg31_raw = es8311_read_reg(ES8311_DAC_REG31);
    uint8_t regv = (reg31_raw >= 0) ? ((uint8_t)reg31_raw & 0x9f) : 0x00;
    es8311_write_reg(ES8311_SYSTEM_REG12, 0x00);
    es8311_write_reg(ES8311_DAC_REG31, regv);

    /*
     * 音量映射（对齐 esp_codec_dev 官方）：
     *   REG32 范围：0x00 = -95.5dB, 0xBF = 0dB, 0xFF = +32dB
     *   官方 volume 0-100 → -49.5dB ~ 0dB（0.5dB/步进）
     *   即 volume=100 → 0dB → REG32=0xBF（绝不能到 0xFF=+32dB，
     *   否则 DAC 量化/本底噪声被放大 32dB → 嘶嘶声与音频同幅）
     *   volume=0 → -96dB（静音）
     */
    float db = 0.0f;
    if (volume <= 0) {
        db = -96.0f;                          /* 静音 */
    } else {
        db = -49.5f + (float)volume * 0.5f;   /* 1~100 → -49.5~0dB */
    }
    /* dB → REG32 线性插值：-95.5dB↔0x00, +32dB↔0xFF */
    uint8_t vol_reg = 0;
    if (db <= -95.5f) {
        vol_reg = 0x00;
    } else if (db >= 32.0f) {
        vol_reg = 0xFF;
    } else {
        vol_reg = (uint8_t)((db + 95.5f) / 127.5f * 255.0f);
    }
    es8311_write_reg(ES8311_DAC_REG32, vol_reg);
    es8311_write_reg(ES8311_DAC_REG37, 0x08);
    ESP_LOGI(TAG, "DAC 音量: %d%% → %0.1fdB (REG32=0x%02X)", volume, db, vol_reg);
    return ESP_OK;
}

/**
 * ADC/DAC 上电 + 解静音（移植自 esp_codec_dev es8311_start, CODEC_MODE_BOTH）
 *
 * 幂等，可重复调用：I2S 时钟重配会 stop/start MCLK，可能导致 ES8311 失锁，
 * 重配完成后再次调用可让 DAC/ADC 重新恢复工作。
 */
esp_err_t es8311_power_up(void)
{
    /* 重新确认 Slave 模式（REG00 bit6=0）。
     * 对齐 esp_codec_dev es8311_start()：每次 enable 都重写 REG00=0x80(slave)。
     * MCLK 未运行时（main.c 中 init）REG00 配置可能未生效，读回为 0xFF(master)，
     * 与 ESP32 I2S master 冲突 → DAC 时钟错乱 → 无声。此处 MCLK 稳定后必须重写。 */
    es8311_write_reg(ES8311_RESET_REG00, 0x80);
    vTaskDelay(pdMS_TO_TICKS(2));
    {
        int reg00 = es8311_read_reg(ES8311_RESET_REG00);
        if (reg00 >= 0) {
            es8311_write_reg(ES8311_RESET_REG00, (uint8_t)reg00 & 0xBF);  /* 清 bit6 → slave */
        }
    }

    /* DAC/ADC 数据通路解静音: REG09/0A 清 bit6 (SDP_MUTE)
     * 对齐 esp_codec_dev es8311_start()：读回清 bit6，保留格式/其他位 */
    int dac_iface = es8311_read_reg(ES8311_SDPIN_REG09);
    int adc_iface = es8311_read_reg(ES8311_SDPOUT_REG0A);
    if (dac_iface >= 0) {
        es8311_write_reg(ES8311_SDPIN_REG09, (uint8_t)dac_iface & ~0x40);
    }
    if (adc_iface >= 0) {
        es8311_write_reg(ES8311_SDPOUT_REG0A, (uint8_t)adc_iface & ~0x40);
    }

    es8311_write_reg(ES8311_ADC_REG17, 0xBF);      /* ADC 音量 */
    es8311_write_reg(ES8311_SYSTEM_REG0E, 0x02);   /* DAC 上电 */
    es8311_write_reg(ES8311_SYSTEM_REG12, 0x00);   /* DAC 使能 (REG12 bit1=PDN_DAC=0) */
    es8311_write_reg(ES8311_SYSTEM_REG14, 0x1A);   /* ADC 使能 + PGA 增益 + 模拟麦(bit6=0) */
    es8311_write_reg(ES8311_SYSTEM_REG0D, 0x01);   /* ADC 模拟上电 + DAC Vref */
    es8311_write_reg(ES8311_ADC_REG15, 0x40);      /* ADC 控制 */
    es8311_write_reg(ES8311_DAC_REG37, 0x08);      /* DAC ramprate/EQ bypass */
    es8311_write_reg(ES8311_GP_REG45, 0x00);       /* GPIO 控制 */

    /* 解静音 + 默认音量 */
    es8311_set_volume(75);
    return ESP_OK;
}

esp_err_t es8311_set_mic_gain(int gain_db)
{
    /*
     * 对齐 esp_codec_dev es8311_set_mic_gain()：
     * MIC 增益写在 REG16 (ADC_REG16)，值为 ES8311_MIC_GAIN_* 枚举（0~7）。
     * 注意：REG14 是 DMIC/PGA 选择寄存器，不可用于 mic 增益（会破坏 ADC 配置）。
     */
    uint8_t regv;
    switch (gain_db) {
        case 0:  regv = 0x00; break;  /* 0dB  */
        case 6:  regv = 0x01; break;  /* 6dB  */
        case 12: regv = 0x02; break;  /* 12dB */
        case 18: regv = 0x03; break;  /* 18dB */
        case 24: regv = 0x04; break;  /* 24dB */
        case 30: regv = 0x05; break;  /* 30dB */
        case 36: regv = 0x06; break;  /* 36dB */
        case 42: regv = 0x07; break;  /* 42dB */
        default: regv = 0x02; break;  /* 12dB 默认 */
    }
    es8311_write_reg(ES8311_ADC_REG16, regv);
    ESP_LOGI(TAG, "MIC 增益: %ddB (REG16=0x%02X)", gain_db, regv);
    return ESP_OK;
}

/* ==================== 功耗管理接口 ==================== */

esp_err_t es8311_set_output_enabled(bool enabled)
{
    /*
     * DAC 静音控制：REG31 (0x31) bit5/bit6
     *   bit5 = 1 → DAC 静音（mute）
     *   bit5 = 0 → DAC 正常输出（unmute）
     * 对齐 esp_codec_dev es8311_mute()：读回 REG31，&0x9f 保留 bit4:0，
     * mute 时置 bit6|bit5（0x60），unmute 时清 bit5。
     */
    uint8_t regv;
    if (!enabled) {
        int reg31_raw = es8311_read_reg(ES8311_DAC_REG31);
        regv = (reg31_raw >= 0) ? ((uint8_t)reg31_raw & 0x9f) | 0x60 : 0x60;
        ESP_LOGI(TAG, "DAC 静音 (REG31=0x%02X)", regv);
    } else {
        int reg31_raw = es8311_read_reg(ES8311_DAC_REG31);
        if (reg31_raw < 0) {
            regv = 0x00;
            ESP_LOGW(TAG, "DAC 解静音: I2C 读取失败，使用默认值 0x%02X", regv);
        } else {
            regv = (uint8_t)reg31_raw & 0x9f;
            ESP_LOGI(TAG, "DAC 解静音 (REG31=0x%02X)", regv);
        }
    }
    return es8311_write_reg(ES8311_DAC_REG31, regv);
}

esp_err_t es8311_restore_output(void)
{
    /*
     * 空闲关闭后恢复输出：重新确认 DAC 上电/使能/模拟电源 + 解静音。
     * 不碰 REG09/0A(数据格式)、REG32(音量)与采样率配置。
     */
    int reg31_raw = es8311_read_reg(ES8311_DAC_REG31);
    bool i2c_read_ok = (reg31_raw >= 0);
    uint8_t regv = i2c_read_ok ? ((uint8_t)reg31_raw & ~0x20) : 0x00;

    es8311_write_reg(ES8311_SYSTEM_REG0E, 0x02);   /* DAC 上电 */
    es8311_write_reg(ES8311_SYSTEM_REG12, 0x00);   /* DAC 使能 */
    es8311_write_reg(ES8311_SYSTEM_REG0D, 0x01);   /* 模拟电源上电 */
    es8311_write_reg(ES8311_DAC_REG37, 0x08);      /* DAC ramprate/EQ bypass */
    es8311_write_reg(ES8311_DAC_REG31, regv);      /* 解静音 */

    ESP_LOGI(TAG, "DAC 恢复输出: REG31 rd=0x%02X(%s) wr=0x%02X",
             (uint8_t)reg31_raw, i2c_read_ok ? "OK" : "FAIL", regv);
    return ESP_OK;
}

esp_err_t es8311_set_input_enabled(bool enabled)
{
    /*
     * ADC 电源控制：REG12 (0x12)
     *   bit3 = 1 → ADC power down
     *   bit3 = 0 → ADC 正常工作
     */
    int reg12_raw = es8311_read_reg(ES8311_SYSTEM_REG12);
    uint8_t regv;
    if (reg12_raw < 0) {
        regv = enabled ? 0x00 : 0x08;
        ESP_LOGW(TAG, "ADC %s: I2C 读取失败，使用默认值 0x%02X", enabled ? "使能" : "禁用", regv);
    } else {
        regv = (uint8_t)reg12_raw;
        if (enabled) {
            regv &= ~(1 << 3);  /* 清 bit3 → ADC 上电 */
        } else {
            regv |= (1 << 3);   /* 置 bit3 → ADC 断电 */
        }
        ESP_LOGI(TAG, "ADC %s (REG12=0x%02X)", enabled ? "使能" : "禁用", regv);
    }
    es8311_write_reg(ES8311_SYSTEM_REG12, regv);
    return ESP_OK;
}
