/**
 * sdcard.c - SD 卡挂载（SDMMC 1-bit）
 *
 * AI-VOX3 的 TF 卡座只连了 CLK / CMD / DAT0 三根线（IO39 / IO38 / IO40），
 * 因此使用 SDMMC 外设的 1-bit 模式，比 SPI 模式速度快且不占用额外引脚。
 *
 * 挂载成功后可通过标准 POSIX 接口访问 /sdcard 下的文件（fopen / opendir）。
 * 注意：ESP-IDF 的 FATFS 只支持 FAT12/16/32，exFAT 卡会挂载失败。
 */
#include "sdcard.h"

#include "boards/board_interface.h"

#include "driver/sdmmc_host.h"
#include "esp_log.h"
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"

#include <dirent.h>
#include <string.h>

#define TAG "sdcard"
#define MOUNT_POINT "/sdcard"

static sdmmc_card_t *s_card = NULL;
static bool s_mounted = false;

bool sdcard_is_mounted(void)
{
    return s_mounted;
}

const char *sdcard_mount_point(void)
{
    return MOUNT_POINT;
}

// 列出根目录前 20 项，用于插卡后快速确认可读
static void list_root(void)
{
    DIR *dir = opendir(MOUNT_POINT);
    if (!dir) {
        ESP_LOGW(TAG, "打开根目录失败");
        return;
    }

    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (count == 0) {
            ESP_LOGI(TAG, "根目录内容:");
        }
        ESP_LOGI(TAG, "  %s%s", entry->d_name,
                 entry->d_type == DT_DIR ? "/" : "");
        if (++count >= 20) {
            ESP_LOGI(TAG, "  ...");
            break;
        }
    }
    if (count == 0) {
        ESP_LOGI(TAG, "根目录为空");
    }
    closedir(dir);
}

esp_err_t sdcard_init(void)
{
    const board_config_t *cfg = board_get_config();
    if (!cfg || cfg->sd_clk_gpio < 0 || cfg->sd_cmd_gpio < 0 || cfg->sd_d0_gpio < 0) {
        ESP_LOGI(TAG, "板型未配置 SD 卡，跳过");
        return ESP_ERR_NOT_SUPPORTED;
    }

    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.slot = SDMMC_HOST_SLOT_1;
    host.max_freq_khz = SDMMC_FREQ_DEFAULT;

    // 1-bit 模式：只接 CLK / CMD / DAT0
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width = 1;
    slot.clk = cfg->sd_clk_gpio;
    slot.cmd = cfg->sd_cmd_gpio;
    slot.d0 = cfg->sd_d0_gpio;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;

    esp_vfs_fat_mount_config_t mount_cfg = {
        .format_if_mount_failed = false,
        .max_files = 4,
        .allocation_unit_size = 16 * 1024,
    };

    esp_err_t ret = esp_vfs_fat_sdmmc_mount(MOUNT_POINT, &host, &slot, &mount_cfg, &s_card);
    if (ret != ESP_OK) {
        s_card = NULL;
        ESP_LOGW(TAG, "SD 卡挂载失败(%s)，可能未插卡或不是 FAT32", esp_err_to_name(ret));
        return ret;
    }

    s_mounted = true;
    uint64_t bytes = (uint64_t)s_card->csd.capacity * s_card->csd.sector_size;
    ESP_LOGI(TAG, "SD 卡已挂载: %s, %llu MB, %d kHz, 1-bit (CLK=%d CMD=%d D0=%d)",
             s_card->cid.name, (unsigned long long)(bytes / (1024 * 1024)),
             s_card->real_freq_khz,
             cfg->sd_clk_gpio, cfg->sd_cmd_gpio, cfg->sd_d0_gpio);
    list_root();
    return ESP_OK;
}
