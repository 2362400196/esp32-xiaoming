/**
 * ota_update.h - ESP32 固件 OTA 升级模块
 *
 * 移植自 Arduino 客户端的 ESPOTAManager + auto_update：
 *   1. 设备启动后查询服务端 GET /sdk/query_new_ota?version=x&bin_id=x
 *   2. 服务端返回 {"success":true,"data":{"latest":false,"bin_url":"http://..."}}
 *   3. 若非最新版本，下载固件并写入 OTA 分区
 *   4. 进度通过 WebSocket 上报，显示在屏幕上
 *   5. 写入完成后重启，Bootloader 验证新固件
 *
 * 分区表已包含 ota_0/ota_1/otadata，并启用 rollback 机制。
 */
#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 检查并执行 OTA 升级
 *
 * 在 WebSocket 连接成功后调用。查询服务端是否有新固件，
 * 若有则下载并写入备用 OTA 分区，完成后重启。
 *
 * @param server_base_url 服务端基础 URL（如 "http://192.168.1.100:8088"）
 * @return ESP_OK：无需更新或更新成功；其他：更新失败
 */
esp_err_t ota_check_and_update(const char *server_base_url);

/**
 * 从指定 URL 直接升级固件（服务端 ota_update 指令入口）
 *
 * 与 ota_check_and_update 的区别：跳过版本比对，直接下载并写入
 * 指定 URL 的固件（管理员强制升级）。完成后重启。
 *
 * @param firmware_url 固件下载地址
 * @return ESP_OK：升级成功（随后重启）；ESP_ERR_INVALID_STATE：已有 OTA 进行中；其他：失败
 */
esp_err_t ota_update_from_url(const char *firmware_url);

/**
 * OTA 是否正在进行中
 */
bool ota_is_updating(void);

/**
 * OTA 是否失败
 */
bool ota_update_failed(void);

#ifdef __cplusplus
}
#endif
