#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 本地音量按键初始化（板型配置了 volume_up_gpio / volume_down_gpio 才生效）
 * 短按步进 10%，长按 700ms 后连续调节，松开时写入 NVS 持久化。
 */
void keys_init(void);

#ifdef __cplusplus
}
#endif
