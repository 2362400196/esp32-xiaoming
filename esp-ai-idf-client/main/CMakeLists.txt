# 自动收集 commands/ 目录中的所有 .c 文件
# 注意：ESP-IDF 组件 CMakeLists 会被 component_get_requirements 以 script 模式解析，
# 该模式不支持 CONFIGURE_DEPENDS，故不能添加；新增 .c 文件后需触发重新配置
# （idf.py reconfigure 或修改本文件）才会被 GLOB 收集到。
file(GLOB COMMAND_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/commands/*.c")

# 部分外设 Lua 驱动模块仅在特定芯片可用，按目标条件加入（S3 保持不变，C3 等自动剔除）：
# - touch:    ESP32 / S2 / S3 / C2 / C6 支持（C3/C5/P4 无 touch 外设）
# - mcpwm:    ESP32 / S2 / S3 / C6 / P4 支持（C3/C2 无 MCPWM 外设）
# - pcnt:     ESP32 / S2 / S3 / P4 支持（C3/C2/C6 无 PCNT 外设）
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
set(LUA_PCNT_SRCS "lua/modules/lua_driver_pcnt.c")
set(LUA_PCNT_REQS esp_driver_pcnt)
if(NOT IDF_TARGET MATCHES "^(esp32|esp32s2|esp32s3|esp32p4)$")
    set(LUA_PCNT_SRCS)
    set(LUA_PCNT_REQS)
endif()

# 中文字库按目标选择：C3（4MB flash、无屏）用空壳版省 2.1MB，其余目标用全量版
if(IDF_TARGET STREQUAL "esp32c3")
    set(FONT_PUHUI_SRC "fonts/font_puhui_16_4_stub.c")
else()
    set(FONT_PUHUI_SRC "fonts/font_puhui_16_4.c")
endif()

idf_component_register(
    SRCS "main.c" "device_id.c" "wifi.c" "websocket.c" "audio.c" "wakeup.c"
         "provisioning.c" "captive_portal.c"
         "hardware_io.c" "network_audio.c" "ota_update.c"
         "power_manager.c"
         # 板级包核心（board_select.h 自动选择板型，无需手动添加板型源文件）
         "boards/board.c"
         # 板级扩展组件（extras，各板型按需挂载到 BOARD_CONFIG.extras）
         "boards/extras/extras_led.c"
         # 显示模块（驱动架构）
         "displays/display.c"
         "displays/display_lcd.cpp"
         "displays/display_uart.c"
         # EEUI 移植层
         "eeui_port.cpp" "gif_downloader.cpp"
         # 中文字库按目标选择：4MB flash 无屏板型（C3）用空壳版省 2.1MB
         ${FONT_PUHUI_SRC}
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
        "lua/modules/lua_module_environmental_sensor.c"
        # 新移植模块（触摸/MCPWM/PCNT 驱动按芯片条件加入）
        "lua/modules/lua_driver_adc.c"
        ${LUA_PCNT_SRCS}
        ${EXTRA_LUA_DRIVER_SRCS}
        "lua/modules/lua_driver_uart.c"
        "lua/modules/lua_module_ledc.c"
        "lua/modules/lua_module_storage.c"
        "lua/modules/lua_driver_i2c.c"
        "lua/modules/lua_module_button.c"
        "lua/modules/lua_driver_rmt.c"
        "lua/modules/lua_module_http.c"
        "lua/modules/lua_module_sci.c"
        "lua/modules/lua_module_thread.c"
        "lua/modules/thread_job.c"
        "lua/modules/thread_sync.c"
        "lua/modules/cap_lua_jobs.c"
         # MP3 解码器
         "helix_mp3/mp3dec.c" "helix_mp3/bitstream.c" "helix_mp3/buffers.c"
         "helix_mp3/dct32.c" "helix_mp3/dequant.c" "helix_mp3/dqchan.c"
         "helix_mp3/huffman.c" "helix_mp3/hufftabs.c" "helix_mp3/imdct.c"
         "helix_mp3/mp3tabs.c" "helix_mp3/polyphase.c" "helix_mp3/scalfact.c"
         "helix_mp3/stproc.c" "helix_mp3/subband.c" "helix_mp3/trigtabs.c"
         "helix_mp3/mp3_decoder_wrapper.c"
    INCLUDE_DIRS "." "helix_mp3" "boards" "boards/extras" "emos" "fonts" "commands" "displays"
                 "audio_codec"
                 "lua" "lua/include" "lua/runtime" "lua/modules"
    REQUIRES esp_wifi esp_event nvs_flash esp_netif esp_http_client
             esp_websocket_client esp_lcd esp_timer cjson esp-sr bt esp_http_server
             esp_adc app_update spiffs
             esp_driver_gpio esp_driver_i2s esp_driver_spi esp_driver_ledc esp_driver_rmt esp_driver_uart
             ${EXTRA_LUA_DRIVER_REQS} ${LUA_PCNT_REQS} esp_driver_i2c
             dht
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

# ==================== bin_id 自动生成 ====================
# bin_id = md5(板卡名 + git commit 短哈希)，编译期注入 BOARD_BIN_ID 宏：
# - 不同板卡 / 不同 commit → 不同 bin_id（OTA 能识别新版本）
# - 同一板卡同一 commit 重复编译 → bin_id 稳定（避免 OTA 无限升级）
execute_process(
    COMMAND git rev-parse --short=12 HEAD
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_COMMIT_SHORT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    RESULT_VARIABLE GIT_COMMIT_RESULT
)
if(NOT GIT_COMMIT_RESULT EQUAL 0 OR GIT_COMMIT_SHORT STREQUAL "")
    set(GIT_COMMIT_SHORT "unknown")
endif()

# 检测当前选中的板卡（CONFIG_BOARD_<NAME>=y）
set(ACTIVE_BOARD_NAME "unknown")
foreach(_def ${BOARD_DEF_FILES})
    get_filename_component(_name ${_def} NAME)
    # 只去掉末尾 .h，保留文件名内部点号（如 esp32s3_breadboard_1.54_lcd）。
    # CMake 4.x 的 NAME_WE 会在第一个点处截断，导致与 Kconfig 符号（点→下划线）不匹配
    string(REGEX REPLACE "\\.h$" "" _base "${_name}")
    string(TOUPPER "${_base}" _base_upper)
    string(REPLACE "." "_" _cfg "${_base_upper}")
    if(CONFIG_BOARD_${_cfg})
        set(ACTIVE_BOARD_NAME "${_base}")
    endif()
endforeach()

# 配网类型参与 bin_id 生成：BLE / WiFi(AP) 版固件 bin_id 不同，
# 服务端 OTA 按类型分槽激活，互不干扰
if(CONFIG_PROV_TYPE_AP)
    set(PROV_TAG "wifi")
else()
    set(PROV_TAG "ble")
endif()

string(MD5 BOARD_BIN_ID "${ACTIVE_BOARD_NAME}_${PROV_TAG}_${GIT_COMMIT_SHORT}")
message(STATUS "固件 bin_id (自动生成): ${BOARD_BIN_ID} (板卡=${ACTIVE_BOARD_NAME}, 配网=${PROV_TAG}, commit=${GIT_COMMIT_SHORT})")
add_definitions(-DBOARD_BIN_ID="${BOARD_BIN_ID}")

# ==================== 固件结构化签名（esp-ai-fw:）====================
# 编译期注入签名串 "esp-ai-fw:prov=wifi;board=xxx;display=st7789_240;ver=062438e-dirty"，
# 服务端收到上传的固件 bin 后直接扫描二进制提取标识，不再依赖文件名——
# 用户用 idf.py 自己编译的产物（esp-ai-idf-client.bin）上传后也能正确归入
# BLE/WiFi 激活槽位并自动登记版本号。
# 可扩展：将来加屏幕型号之外的标识（音频芯片、flash 大小等）直接追加 ;key=value，
# 服务端按 k=v 解析、未知键原样保留，向后兼容。
# 显示型号标识：从激活板卡 def 文件的 BOARD_DISPLAY_* 宏推断
set(FW_DISPLAY_TAG "none")
foreach(_def ${BOARD_DEF_FILES})
    get_filename_component(_name ${_def} NAME)
    string(REGEX REPLACE "\\.h$" "" _base "${_name}")
    if(_base STREQUAL ACTIVE_BOARD_NAME)
        file(READ "${_def}" _def_content)
        if(_def_content MATCHES "BOARD_DISPLAY_ST7789")
            set(FW_DISPLAY_TAG "st7789_240")
        elseif(_def_content MATCHES "BOARD_DISPLAY_ILI9341")
            set(FW_DISPLAY_TAG "ili9341_320x240")
        elseif(_def_content MATCHES "BOARD_DISPLAY_SSD1306")
            set(FW_DISPLAY_TAG "ssd1306_128x64")
        endif()
        break()
    endif()
endforeach()
# 完整版本号（git describe，与设备 OTA 上报的 FIRMWARE_VERSION 口径一致；失败回退 commit 短哈希）
execute_process(
    COMMAND git describe --tags --always --dirty
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_DESCRIBE
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    RESULT_VARIABLE GIT_DESCRIBE_RESULT
)
if(NOT GIT_DESCRIBE_RESULT EQUAL 0 OR GIT_DESCRIBE STREQUAL "")
    set(GIT_DESCRIBE "${GIT_COMMIT_SHORT}")
endif()
set(ESP_AI_FW_SIG "esp-ai-fw:prov=${PROV_TAG};board=${ACTIVE_BOARD_NAME};display=${FW_DISPLAY_TAG};ver=${GIT_DESCRIBE}")
message(STATUS "固件签名: ${ESP_AI_FW_SIG}")
# 签名串中的 ';' 是 CMake 的 list 分隔符，必须转义后才能传入 add_definitions，
# 否则编译命令行被拆散、后续编译参数被当成源文件名导致 cc1 fatal error
string(REPLACE ";" "\\;" ESP_AI_FW_SIG_ESC "${ESP_AI_FW_SIG}")
add_definitions("-DESP_AI_FW_SIG=\"${ESP_AI_FW_SIG_ESC}\"")