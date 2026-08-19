"""builtin_tools.py - 已迁移到插件机制（2026-08）保留此文件仅为兼容旧 import。

所有内置工具已按功能域迁移到 src/plugins/ 目录：

  system_basic   时间/待机/音量/亮度（get_current_time, standby, set_volume...）
  media_player   音乐播放（play_music, play_random_music_to_channel）
  device_control 设备控制（execute_lua, stop_lua, clear_screen, test_device）
  alarm          闹钟与提醒（set_alarm, set_reminder, list_alarms...）
  http_tool      HTTP 请求（http_request）
  memory         长期记忆（memory_store, memory_recall...）
  device_config  设备配置读写（read_device_config, write_device_config）
  screen         屏幕控制（set_screen_rotation）
  diary          日记本（read_diary, write_diary, search_diary）

新功能开发请直接创建插件：src/plugins/<插件名>/plugin.py，
热加载：curl -X POST http://<server>:8088/api/v1/plugins/reload
"""
