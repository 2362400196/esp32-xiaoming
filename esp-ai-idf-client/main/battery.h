#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 电池检测初始化（板型配置了 battery_adc_gpio 才生效）
 * 周期采样电池电压，更新屏幕电量百分比；通过电压上升趋势判断是否在充电。
 */
void battery_init(void);

#ifdef __cplusplus
}
#endif
