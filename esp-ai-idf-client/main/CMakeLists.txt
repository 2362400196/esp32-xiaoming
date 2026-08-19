# 自动收集 commands/ 目录中的所有 .c 文件
# 注意：ESP-IDF 组件 CMakeLists 会被 component_get_requirements 以 script 模式解析，
# 该模式不支持 CONFIGURE_DEPENDS，故不能添加；新增 .c 文件后需触发重新配置
# （idf.py reconfigure 或修改本文件）才会被 GLOB 收集到。
file(GLOB COMMAND_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/commands/*.c")

# 部分外设 Lua 驱动模块仅在特定芯片可用，按目标条件加入（S3 保持不变，C3 等自动剔除）：
# - touch:    ESP32 / S2 / S3 / C2 / C6 支持（C3/C5/P4 无 touch 外设）
# - mcpwm:    ESP32 / S2 / S3 / C6 / P4 支持（C3/C2 无 MCPWM 外设）
set(EXTRA_LUA_DRIVER_SRCS)
set(EXTRA_LUA_DRIVER_REQS)
if(IDF_TARGET MATCHES "^(esp32|esp32s2|esp32s3|esp32c2|esp32c6)$")
    list(APPEND EXTRA_LUA_DRIVER_SRCS "lua/modules/lua_driver_touch.c")
    list(APPEND EXTRA_LUA_DRIVER_REQS esp_driver_touch_sens)
endif()
if(IDF_TARGET MATCHES "^(esp32|esp32s2|esp32s3|esp32c6|esp32p4)$")
    list(APPEND EXTRA_LUA_DRIVER_SRCS "lua/modules/lua_driver_mcpwm.c")
    list(APPEND EXTRA_LUA_DRIVER_REQS esp_driver_mcpwm)
endif()

idf_component_register(
    SRCS "main.c" "device_id.c" "wifi.c" "websocket.c" "audio.c" "wakeup.c"
         "provisioning.c"
         "hardware_io.c" "network_audio.c" "ota_update.c"
         "power_manager.c"
         # 板级包核心（board_select.h 自动选择板型，无需手动添加板型源文件）
         "boards/board.c"
         # 显示模块（驱动架构）
         "displays/display.c"
         "displays/display_lcd.cpp"
         "displays/display_uart.c"
         # EEUI 移植层
         "eeui_port.cpp" "gif_downloader.cpp"
         "fonts/font_puhui_16_4.c"
         "fonts/weather_icons.c"
         # 音频编解码器（menuconfig → 音频编解码器 选择，未选 ES8311 时函数不被调用）
         "audio_codec/es8311.c"
         ${COMMAND_SOURCES}
         # Lua 5.4 解释器
         "lua/all.c"
         "lua/runtime/lua_runtime.c"
         "lua/lua_lvgl.c"
        "lua/modules/lua_module_delay.c"
        "lua/modules/lua_module_system.c"
        "lua/modules/lua_module_json.c"
        "lua/modules/lua_module_gpio.c"
        "lua/modules/lua_module_led.c"
        # 新移植模块（触摸/MCPWM 驱动按芯片条件加入）
        "lua/modules/lua_driver_adc.c"
        "lua/modules/lua_driver_pcnt.c"
        ${EXTRA_LUA_DRIVER_SRCS}
        "lua/modules/lua_driver_uart.c"
        "lua/modules/lua_module_ledc.c"
        "lua/modules/lua_module_storage.c"
         # MP3 解码器
         "helix_mp3/mp3dec.c" "helix_mp3/bitstream.c" "helix_mp3/buffers.c"
         "helix_mp3/dct32.c" "helix_mp3/dequant.c" "helix_mp3/dqchan.c"
         "helix_mp3/huffman.c" "helix_mp3/hufftabs.c" "helix_mp3/imdct.c"
         "helix_mp3/mp3tabs.c" "helix_mp3/polyphase.c" "helix_mp3/scalfact.c"
         "helix_mp3/stproc.c" "helix_mp3/subband.c" "helix_mp3/trigtabs.c"
         "helix_mp3/mp3_decoder_wrapper.c"
    INCLUDE_DIRS "." "helix_mp3" "boards" "emos" "fonts" "commands" "displays"
                 "audio_codec"
                 "lua" "lua/include" "lua/runtime" "lua/modules"
    REQUIRES esp_wifi esp_event nvs_flash esp_netif esp_http_client
             esp_websocket_client esp_lcd esp_timer cjson esp-sr bt esp_http_server
             esp_adc app_update spiffs
             esp_driver_gpio esp_driver_i2s esp_driver_spi esp_driver_ledc esp_driver_rmt esp_driver_uart
             ${EXTRA_LUA_DRIVER_REQS} esp_driver_pcnt
            )

# Kconfig.gen 由 gen_boards.py 自动生成，通过 Kconfig.projbuild source 引入

# ==================== 板型定义自动生成 ====================
# 当 boards/defs/ 目录中的板型定义文件变化时，自动重新生成 Kconfig.gen 和 board_select.h
# 添加新板型只需在 defs/ 下创建 .h 文件，然后 idf.py reconfigure 即可
set(GEN_BOARDS_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/boards/tools/gen_boards.py")
file(GLOB BOARD_DEF_FILES "${CMAKE_CURRENT_SOURCE_DIR}/boards/defs/*.h")

add_custom_command(
    OUTPUT "${CMAKE_CURRENT_SOURCE_DIR}/boards/Kconfig.gen"
           "${CMAKE_CURRENT_SOURCE_DIR}/boards/board_select.h"
    COMMAND python ${GEN_BOARDS_SCRIPT}
    DEPENDS ${GEN_BOARDS_SCRIPT} ${BOARD_DEF_FILES}
    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/boards"
    COMMENT "扫描 boards/defs/ 生成 Kconfig.gen 和 board_select.h"
    VERBATIM
)

add_custom_target(gen_boards DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/boards/Kconfig.gen"
    "${CMAKE_CURRENT_SOURCE_DIR}/boards/board_select.h"
)
add_dependencies(${COMPONENT_LIB} gen_boards)