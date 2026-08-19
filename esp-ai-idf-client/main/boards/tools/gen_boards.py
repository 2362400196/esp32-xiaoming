#!/usr/bin/env python3
"""
gen_boards.py - 板型自动生成脚本（1000+ 板型架构）

扫描 boards/defs/ 目录中的 .h 板型定义文件，自动生成：
1. boards/Kconfig.gen  - menuconfig 板型选择选项（按芯片分组）
2. boards/board_select.h - 编译时板型选择

功能：
- 从 @meta 注释提取芯片/厂商/系列元数据
- 校验必填字段（name, description, bin_id）
- 检查 bin_id 唯一性
- 按芯片分组生成 Kconfig（单芯片时为 flat choice）

注意：音频编解码器（ES8311 等）的选择由 Kconfig.projbuild 中的
      AUDIO_CODEC 选择项控制，与本脚本无关。

使用方法：
    python boards/tools/gen_boards.py

添加新板型流程：
    1. 在 boards/defs/ 下创建 <board_name>.h
    2. 运行本脚本
    3. menuconfig 选择新板型
    4. 编译

无需修改任何框架代码。

@meta 注释格式（可选，放在文件头注释中）：
    /// @meta chip=esp32s3 vendor=espressif series=breadboard
    /// @meta display=st7789_240 audio=es8311

无 @meta 时默认 chip=esp32s3。
"""

import os
import re
import glob
import sys

# 脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# boards/ 目录
BOARDS_DIR = os.path.join(SCRIPT_DIR, "..")
# defs/ 目录
DEFS_DIR = os.path.join(BOARDS_DIR, "defs")


def extract_meta(content):
    """从文件内容提取 @meta key=value 注释"""
    meta = {}
    for m in re.finditer(r'///\s*@meta\s+(.+)', content):
        for pair in m.group(1).split():
            if '=' in pair:
                k, v = pair.split('=', 1)
                meta[k.strip()] = v.strip()
    return meta


def extract_board_info(filepath):
    """从板型定义 .h 文件提取完整信息"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取 .name = "xxx"
    name_match = re.search(r'\.name\s*=\s*"([^"]+)"', content)
    name = name_match.group(1) if name_match else os.path.splitext(os.path.basename(filepath))[0]

    # 提取 .description = "xxx"
    desc_match = re.search(r'\.description\s*=\s*"([^"]+)"', content)
    desc = desc_match.group(1) if desc_match else name

    # 提取 .bin_id = "xxx"
    bin_id_match = re.search(r'\.bin_id\s*=\s*"([^"]+)"', content)
    bin_id = bin_id_match.group(1) if bin_id_match else ""

    # 提取 @meta 元数据
    meta = extract_meta(content)
    chip = meta.get("chip", "esp32s3")
    vendor = meta.get("vendor", "")
    series = meta.get("series", "")

    basename = os.path.splitext(os.path.basename(filepath))[0]
    # Kconfig 配置名不能包含点号，将 . 替换为 _
    kconfig_name = "BOARD_" + basename.upper().replace(".", "_")

    return {
        "basename": basename,
        "kconfig_name": kconfig_name,
        "name": name,
        "description": desc,
        "bin_id": bin_id,
        "chip": chip,
        "vendor": vendor,
        "series": series,
        "filepath": filepath,
    }


def validate_boards(boards):
    """校验板型定义，返回错误和警告列表"""
    errors = []
    warnings = []
    bin_ids = {}

    for b in boards:
        # 检查必填字段
        if not b["name"]:
            errors.append("{}: 缺少 .name 字段".format(b["basename"]))
        if not b["description"]:
            warnings.append("{}: 缺少 .description 字段".format(b["basename"]))
        if not b["bin_id"]:
            errors.append("{}: 缺少 .bin_id 字段（OTA 升级必需）".format(b["basename"]))

        # 检查 bin_id 唯一性
        if b["bin_id"]:
            if b["bin_id"] in bin_ids:
                errors.append("{}: bin_id '{}' 与 {} 重复".format(
                    b["basename"], b["bin_id"], bin_ids[b["bin_id"]]))
            else:
                bin_ids[b["bin_id"]] = b["basename"]

        # 检查 @meta 是否存在
        if not b["chip"]:
            warnings.append("{}: 未设置 @meta chip，默认 esp32s3".format(b["basename"]))

    return errors, warnings


def chip_to_target(chip: str) -> str:
    """chip 标识转 Kconfig 目标符号，如 esp32c3 → IDF_TARGET_ESP32C3"""
    return "IDF_TARGET_" + chip.upper().replace("-", "_")


def generate_kconfig(boards):
    """生成 Kconfig.gen - 按芯片分组的 menuconfig"""
    # 按芯片分组
    chip_groups = {}
    for b in boards:
        chip = b["chip"]
        if chip not in chip_groups:
            chip_groups[chip] = []
        chip_groups[chip].append(b)

    lines = []
    lines.append("# =============================================================")
    lines.append("# Kconfig.gen - 板型选择菜单（自动生成，请勿手动编辑）")
    lines.append("# 由 gen_boards.py 扫描 boards/defs/ 目录生成")
    lines.append("# =============================================================")
    lines.append("")

    # 单芯片：flat choice（简单直接）
    if len(chip_groups) == 1:
        chip = list(chip_groups.keys())[0]
        group_boards = chip_groups[chip]
        lines.append("choice BOARD_TYPE")
        lines.append('    prompt "选择开发板型号"')
        lines.append("    default {}".format(group_boards[0]["kconfig_name"]))
        lines.append("")
        for b in group_boards:
            lines.append("    config {}".format(b["kconfig_name"]))
            lines.append('        bool "{} - {}"'.format(b["name"], b["description"]))
            lines.append("        depends on {}".format(chip_to_target(chip)))
            lines.append("")
        lines.append("endchoice")

    # 多芯片：按芯片分组（depends on 让当前目标只显示对应芯片的板型）
    else:
        lines.append("choice BOARD_TYPE")
        lines.append('    prompt "选择开发板型号"')
        lines.append("    default {}".format(boards[0]["kconfig_name"]))
        lines.append("")

        for chip in sorted(chip_groups.keys()):
            group_boards = chip_groups[chip]
            chip_display = chip.upper().replace("-", "-")
            lines.append("    # --- {} ---".format(chip_display))
            for b in group_boards:
                lines.append("    config {}".format(b["kconfig_name"]))
                lines.append('        bool "[{}] {} - {}"'.format(chip_display, b["name"], b["description"]))
                lines.append("        depends on {}".format(chip_to_target(b["chip"])))
                lines.append("")

        lines.append("endchoice")

    return "\n".join(lines) + "\n"


def generate_board_select_h(boards):
    """生成 board_select.h - 编译时板型选择"""
    lines = []
    lines.append("/**")
    lines.append(" * board_select.h - 编译时板型选择（自动生成，请勿手动编辑）")
    lines.append(" *")
    lines.append(" * 由 gen_boards.py 扫描 boards/defs/ 目录生成")
    lines.append(" *")
    lines.append(" * 工作原理：")
    lines.append(" * - menuconfig 选择 CONFIG_BOARD_<NAME> 宏")
    lines.append(" * - 本文件通过 #ifdef 匹配宏，#include 对应板型定义")
    lines.append(" *")
    lines.append(" * 注意：音频编解码器（ES8311 等）的选择由 Kconfig.projbuild")
    lines.append(" *      中的 AUDIO_CODEC 选项控制，与本文件无关。")
    lines.append(" */")
    lines.append("#pragma once")
    lines.append("")

    for b in boards:
        config_name = "CONFIG_" + b["kconfig_name"]
        lines.append("#ifdef {}".format(config_name))
        lines.append('#include "boards/defs/{}.h"'.format(b["basename"]))
        lines.append("#define ACTIVE_BOARD_CONFIG (&BOARD_CONFIG)")
        lines.append("#endif")
        lines.append("")

    lines.append("#ifndef ACTIVE_BOARD_CONFIG")
    lines.append('#error "未选择板型，请在 menuconfig → 选择开发板型号 中设置"')
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def main():
    # 扫描 defs/ 目录（排除 board_templates.h）
    def_files = sorted(glob.glob(os.path.join(DEFS_DIR, "*.h")))
    def_files = [f for f in def_files if not f.endswith("board_templates.h")]

    if not def_files:
        print("[ERROR] boards/defs/ 目录中没有 .h 板型定义文件")
        return 1

    # 提取所有板型信息
    boards = [extract_board_info(f) for f in def_files]

    # 校验
    errors, warnings = validate_boards(boards)

    for w in warnings:
        print("[WARN]  {}".format(w))
    for e in errors:
        print("[ERROR] {}".format(e))

    if errors:
        print("\n[FAIL] 校验发现 {} 个错误，请修复后重试".format(len(errors)))
        return 1

    # 生成 Kconfig.gen
    kconfig_path = os.path.join(BOARDS_DIR, "Kconfig.gen")
    kconfig_content = generate_kconfig(boards)
    with open(kconfig_path, "w", encoding="utf-8") as f:
        f.write(kconfig_content)
    print("[OK] 生成 {} ({} 个板型)".format(kconfig_path, len(boards)))

    # 生成 board_select.h
    select_path = os.path.join(BOARDS_DIR, "board_select.h")
    select_content = generate_board_select_h(boards)
    with open(select_path, "w", encoding="utf-8") as f:
        f.write(select_content)
    print("[OK] 生成 {}".format(select_path))

    # 打印板型列表
    print("\n板型列表：")
    for b in boards:
        chip_tag = "[{}]".format(b["chip"].upper())
        bin_id_short = b["bin_id"][:8] + "..." if len(b["bin_id"]) > 8 else b["bin_id"]
        print("  - {:40s} {} bin_id={}".format(
            b["name"], chip_tag, bin_id_short))

    if warnings:
        print("\n{} 个警告（不影响生成）".format(len(warnings)))

    return 0


if __name__ == "__main__":
    sys.exit(main())
