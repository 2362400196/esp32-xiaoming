#pragma once
// Captive Portal（强制门户）：
// 手机连接免密热点后系统会认为"无互联网"而继续走蜂窝数据，导致配网请求发不到设备。
// 本组件做两件事解决这个问题：
//   1. DNS 劫持：设备上开 UDP 53 服务，把手机的一切域名查询解析到 192.168.4.1
//   2. 配合 httpd 对系统联网探测 URL 返回 302（注册在 provisioning.c）
// 手机系统识别到 Captive Portal 后会自动弹出配网页并提示"保持连接"。

#include "esp_err.h"

esp_err_t captive_portal_start(void);
void captive_portal_stop(void);
