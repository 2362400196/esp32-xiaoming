cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS components)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# GCC 15.2.0 (esp-15.2.0_20251204) 在编译 esp_lcd 组件时 IRA pass 会触发
# "internal compiler error: Segmentation fault"。该选项是社区通用的 workaround。
# 参考: https://gcc.gnu.org/bugzilla (ira share spill slots)
idf_build_set_property(COMPILE_OPTIONS "-fno-ira-share-spill-slots" APPEND)

project(esp-ai-idf-client)

# ── 从 git tag 动态获取固件版本号 ──
# OTA 升级后客户端版本号必须更新，否则会陷入无限升级循环
# 优先使用 git describe --tags，无 git 或无 tag 时回退到默认值
execute_process(
    COMMAND git describe --tags --always --first-parent 2>nul
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    OUTPUT_VARIABLE GIT_FIRMWARE_VERSION
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
    RESULT_VARIABLE GIT_VERSION_RESULT
)
if(GIT_VERSION_RESULT EQUAL 0 AND NOT GIT_FIRMWARE_VERSION STREQUAL "")
    string(STRIP "${GIT_FIRMWARE_VERSION}" GIT_FIRMWARE_VERSION)
    message(STATUS "固件版本 (git): ${GIT_FIRMWARE_VERSION}")
else()
    set(GIT_FIRMWARE_VERSION "1.0.0")
    message(STATUS "固件版本 (默认): ${GIT_FIRMWARE_VERSION}")
endif()
add_definitions(-DFIRMWARE_VERSION="${GIT_FIRMWARE_VERSION}")
