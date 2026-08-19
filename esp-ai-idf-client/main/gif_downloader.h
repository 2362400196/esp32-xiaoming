/**
 * gif_downloader.h
 * 从服务器下载动图到 PSRAM，替换编译固件中的静态图。
 * 移植自 Arduino 客户端 gif_downloader.h / gif_downloader.cpp
 *
 * 服务器地址: http://GPS_SERVER_IP:PORT/ (如 http://192.168.31.176:8088)
 * 下载流程:
 *   1. WiFi 连接后，调用 download_gifs()
 *   2. 先尝试 API: /api/v1/emos/{device_id}
 *   3. 回退到固定 URL: {GIF_SERVER}/emos/{filename}
 *   4. 下载成功后，eeui_port_render_emotion 优先使用 PSRAM 中的下载数据
 *   5. 下载完成前使用编译器内置的 GIF 作为后备
 */
#pragma once

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

// 动图名称 → 服务器文件名 映射（与 Arduino 一致）
typedef struct {
    const char *name;      // 表情名，如 "快乐"
    const char *filename;  // 服务器文件名，如 "happy.gif"
} gif_map_entry_t;

extern const gif_map_entry_t g_gif_files[];
extern const int g_gif_files_count;

/**
 * @brief 下载所有动图到 PSRAM
 *        在 WiFi 连接后调用，会启动后台下载任务
 *        下载完成前，渲染仍使用固件内置的 GIF
 */
void download_gifs(void);

/**
 * @brief 是否正在下载 GIF 表情（下载期间唤醒模块会禁用唤醒动作）
 * @return true=下载中，false=未下载或已完成
 */
bool gif_download_is_busy(void);

/**
 * @brief 获取已下载的 GIF 图像描述符（优先于内置）
 * @param name  表情名称，如 "说话中"
 * @return lv_img_dsc_t*  下载的 GIF 数据，若未下载或失败返回 NULL
 */
const lv_img_dsc_t *get_downloaded_gif(const char *name);

/**
 * @brief 清除已下载的 GIF 数据并重新下载
 *        服务端切换设备表情包后发送 refresh_emo 指令时调用
 *        会释放旧的 PSRAM 数据，然后启动后台重新下载
 */
void refresh_gifs(void);

#ifdef __cplusplus
}
#endif
