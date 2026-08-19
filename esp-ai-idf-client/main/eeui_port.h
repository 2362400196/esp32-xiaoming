/**
 * eeui_port.h - EEUI 表情显示移植接口（C 接口）
 *
 * 移植自 Arduino esp-ai-emo-ui 库（eeui.h / eeui.cpp）
 * 将 LVGL 8.4 + TFT_eSPI 实现移植为 ESP-IDF + esp_lcd 实现
 *
 * C 代码（display.c 等）通过这些 extern "C" 接口调用 C++ 实现的 EEUI 功能
 */
#pragma once

#include "esp_err.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * 初始化 EEUI 显示系统
 * 内部完成: LVGL 初始化、显示驱动注册、LVGL 任务创建、根容器创建
 * @return ESP_OK 或错误码
 */
esp_err_t eeui_port_init(void);

/**
 * 渲染表情（按名称，对应 Arduino eeui.render_gif_by_name）
 * @param name 表情名称: "联网中"/"聆听中"/"说话中"/"休息中"/"快乐"/"伤心"/"愤怒" 等
 */
void eeui_port_render_emotion(const char *name);

/**
 * 设置顶部状态文字（对应 Arduino eeui.set_status_text）
 * @param text 状态文字，如 "休息中"、"聆听中"
 * @param need_ani 是否需要滑入动画
 * @param align 对齐方式: "top_left" 或 "bottom_center"
 */
void eeui_port_set_status_text(const char *text, bool need_ani, const char *align);

/**
 * 设置底部滚动字幕（对应 Arduino eeui.set_bottom_scrolling_text）
 * 用于显示 ASR 文本、LLM 回复、歌词
 * @param text 字幕文本
 */
void eeui_port_set_bottom_text(const char *text);

/**
 * 设置背光亮度（对应 Arduino set_brightness / ledcWrite）
 * @param percent 0-100
 */
void eeui_port_set_brightness(int percent);

/**
 * 渲染电量图标
 * @param percent 0-100
 */
void eeui_port_render_battery(int percent);

/**
 * 隐藏电量图标
 */
void eeui_port_hide_battery(void);

/**
 * 渲染音量条
 * @param volume 0.0-1.0
 */
void eeui_port_render_volume(float volume);

/**
 * 渲染信号强度
 * @param strength 0-3
 */
void eeui_port_render_signal(int strength);

/**
 * 等待 LVGL 初始化完成
 */
void eeui_port_wait_init(void);

/**
 * 设置工具状态文字（底部，与字幕同位置但独立标签）
 * 显示时覆盖字幕区域，不影响字幕数据
 * @param text 工具状态文字，如 "正在调用xx工具..."
 */
void eeui_port_set_tool_status_text(const char *text);

/**
 * 清除工具状态文字（字幕恢复可见）
 */
void eeui_port_clear_tool_status(void);

/**
 * 渲染 OTA 升级圆形进度条（对应 Arduino eeui.render_ota_percent）
 * 使用 LVGL arc 控件创建圆形进度环 + 百分比文字
 * @param percent 0-100
 */
void eeui_port_render_ota_percent(int percent);

/**
 * 清除 OTA 进度条（升级完成或失败后调用）
 */
void eeui_port_clear_ota_progress(void);

/**
 * 显示音乐播放器覆盖层（白色全屏，音符 + "正在播放音乐"）
 * 播放网络音乐时调用
 */
void eeui_port_show_music_player(void);

/**
 * 隐藏音乐播放器覆盖层
 * 停止播放网络音乐时调用
 */
void eeui_port_hide_music_player(void);

/**
 * 音乐播放器 UI - 设置歌曲信息和艺术家
 * @param song 歌曲名
 * @param artist 艺术家名
 */
void eeui_port_music_set_song_info(const char *song, const char *artist);

/**
 * 音乐播放器 UI - 更新歌词（当前行 + 下一行）
 * @param current_lyric 当前歌词（可见）
 * @param next_lyric 下一句歌词（灰色）
 */
void eeui_port_music_update_lyrics(const char *current_lyric, const char *next_lyric);

/**
 * 音乐播放器 UI - 更新播放进度
 * @param current_ms 当前播放位置（毫秒）
 * @param total_ms 总时长（毫秒）
 */
void eeui_port_music_update_progress(uint32_t current_ms, uint32_t total_ms);

/**
 * 音乐播放器 UI - 销毁覆盖层（彻底清理）
 */
void eeui_port_music_destroy(void);

/**
 * 显示表情下载中全屏提示
 * 下载表情包时调用，覆盖整个屏幕显示"表情下载中..."文字
 */
void eeui_port_show_emo_downloading(void);

/**
 * 隐藏表情下载中提示，恢复之前的表情状态
 */
void eeui_port_hide_emo_downloading(void);

/**
 * 获取 LVGL 互斥锁（供外部模块如 Lua 脚本安全操作 LVGL）
 * @param timeout_ms 超时毫秒
 * @return true=获取成功, false=超时
 */
bool eeui_port_lvgl_lock(uint32_t timeout_ms);

/**
 * 获取 LVGL 显示设备句柄，用于屏幕旋转等操作
 */
void *eeui_port_get_display(void);
void *eeui_port_get_lcd_panel(void);
void *eeui_port_get_panel_io(void);

/**
 * 释放 LVGL 互斥锁
 */
void eeui_port_lvgl_unlock(void);

/**
 * 屏保开关（省电模式时钟）
 * @param active true=进入屏保（纯黑 + 居中时间 + 背光调暗），false=退出恢复
 * 由 power_manager 待机/活跃状态切换时调用；无屏板型（C3 headless）自动忽略
 */
void eeui_port_screensaver_set(bool active);

/**
 * 通用卡片渲染（show_card 指令）
 * @param json_str JSON 描述的卡片（协议见 eeui_port.cpp show_card 模块注释）
 * 原生 LVGL 渲染，支持大号数字字体/中文字体/天气符号；
 * 卡片在会话边界（唤醒/会话结束）由 eeui_port_clear_cards 清除。无屏板型自动忽略。
 */
void eeui_port_show_card(const char *json_str);

/**
 * 清除 show_card 卡片（会话边界调用：唤醒/会话结束/断线时恢复表情显示）
 * 会话内（TTS 播报等表情变化）卡片保持显示，不会被清除
 */
void eeui_port_clear_cards(void);

#ifdef __cplusplus
}
#endif
