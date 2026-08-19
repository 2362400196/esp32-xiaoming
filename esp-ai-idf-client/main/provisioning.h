#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>

// ==================== 设备绑定回调（与 esp-ai-client 的 onBindDeviceCb 一致） ====================
// 收到 BLE 配网数据并成功连接 WiFi 后调用。
// data_json: 配网收到的完整 JSON 字符串（含 wifi_name, wifi_pwd 及自定义字段）
// 返回值 JSON 字符串（调用者需 free）：
//   {"success":true, "message":"..."}  绑定成功
//   {"success":false,"message":"..."}  绑定失败
typedef char *(*provisioning_on_bind_cb_t)(const char *data_json);

// 注册设备绑定回调（与 esp-ai-client 的 onBindDeviceCb 一致）
void provisioning_set_on_bind_cb(provisioning_on_bind_cb_t cb);

// ==================== BLE 错误消息（与 esp-ai-client 的 ESP_AI_BLE_ERR 一致） ====================
// 设置 BLE 错误消息，会在下次 BLE 启动时通过 characteristic 发送给客户端。
void provisioning_ble_set_err(const char *err_msg);

// 检查设备是否已配网（NVS中是否有WiFi凭据）
bool provisioning_is_provisioned(void);

// 从NVS获取已保存的WiFi凭据
esp_err_t provisioning_get_credentials(char *ssid, size_t ssid_len,
                                        char *password, size_t password_len);

// 保存WiFi凭据到NVS
esp_err_t provisioning_save_credentials(const char *ssid, const char *password);

// ==================== BLE 配网后连接 WiFi（与 esp-ai-client 的 ble_connect_wifi 一致） ====================
// 当 NVS 中存在 _ble_temp_ = "1" 时调用此函数：
//   1. 读取 wifi_name/wifi_pwd 尝试连接 WiFi（带状态回调，约 7.5s 超时）
//   2. 连接成功后调用 on_bind_device_cb
//   3. 绑定成功则清除 _ble_temp_ 标记并重启
//   4. 绑定失败或 WiFi 失败则清除所有数据并重启（回到配网模式）
void provisioning_ble_connect_wifi(void);

// 启动配网流程（根据Kconfig选择BLE或AP方式）
esp_err_t provisioning_start(void);

// 停止配网流程，释放资源
void provisioning_stop(void);

// 清除所有本地配置数据（WiFi凭据、API Key等），重启后进入配网模式
void provisioning_clear_all(void);
