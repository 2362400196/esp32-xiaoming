#pragma once

#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 电池检测初始化（板型配置了 battery_adc_gpio 才生效）
 * 周期采样电池电压，更新屏幕电量百分比；通过电压上升趋势判断是否在充电。
 */
void battery_init(void);

/** 当前电量百分比（0-100；-1 = 尚无数据/板型不支持电池检测） */
int battery_get_percent(void);

/** 当前电池电压 mV（-1 = 尚无数据/板型不支持） */
int battery_get_voltage_mv(void);

/** 是否正在充电（USB 供电或电压上升趋势） */
bool battery_is_charging(void);

/** 是否已充满（充电中但已达到满电阈值） */
bool battery_is_full(void);

/** 板型是否支持电池检测 */
bool battery_is_supported(void);

#ifdef __cplusplus
}
#endif
