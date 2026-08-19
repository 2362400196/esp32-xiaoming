/**
 * hardware_io.h - 硬件 IO 控制（移植自 Arduino esp-ai 客户端的 hardware-fns 指令）
 *
 * 对应 Arduino webSocketEvent 中的 "hardware-fns" 消息处理:
 *   - pinMode:        配置引脚模式 (OUTPUT/INPUT/INPUT_PULLUP/INPUT_PULLDOWN/LEDC)
 *   - digitalWrite:   数字写 (HIGH/LOW)
 *   - digitalRead:    数字读（加入定时上报列表）
 *   - analogWrite:    模拟写 (LEDC PWM)
 *   - analogRead:     模拟读（加入定时上报列表）
 *   - ledcWrite:      LEDC 舵机控制（角度 → 占空比）
 *
 * 消息格式 (服务端下发):
 *   { "type":"hardware-fns", "pin":12, "fn_name":"digitalWrite", "str_val":"HIGH" }
 *   { "type":"hardware-fns", "pin":12, "fn_name":"pinMode", "str_val":"OUTPUT" }
 *   { "type":"hardware-fns", "pin":12, "fn_name":"analogWrite", "num_val":512 }
 *   { "type":"hardware-fns", "pin":12, "fn_name":"ledcWrite", "channel":0, "deg":90 }
 */
#pragma once

#include "esp_err.h"
#include "cJSON.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 处理 hardware-fns 指令
 * @param json 完整的 JSON 消息对象（包含 pin/fn_name/str_val/num_val 等字段）
 * @return ESP_OK 或错误码
 */
esp_err_t hardware_io_handle_fns(cJSON *json);

/**
 * 定时上报数字/模拟读取的引脚值（由主循环调用）
 * @return ESP_OK
 */
esp_err_t hardware_io_report_readings(void);

#ifdef __cplusplus
}
#endif
