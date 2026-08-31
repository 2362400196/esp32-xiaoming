#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
esp-ai-idf-client 固件构建脚本

一次编译同时产出两种固件：
  1. 全量固件  {chip}-{name}-{commit}-flash-all.bin
     合并 bootloader + 分区表 + OTA 初始数据 + 唤醒词模型 + app，
     用于整片烧录（首次烧录 / 发给别人）。
  2. OTA 固件  {chip}-{name}-{commit}.bin
     纯 app 二进制，用于服务端 OTA 升级下发。

用法：
  python build_firmware.py                 # 编译 + 打包
  python build_firmware.py --no-build      # 只打包（编译已完成时）
  python build_firmware.py --target esp32c3
  python build_firmware.py --name myboard
  python build_firmware.py --out dist

说明：
  - 环境与 build.ps1 保持一致（ESP-IDF 6.0.2，D:\\idf\\.espressif\\v6.0.2）。
  - OTA 分区为 6MB，app 固件超过该大小会写失败，脚本会做大小检查。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent

# ESP-IDF 6.0.2 环境（与 build.ps1 保持一致）
IDF6_ROOT = Path(r"D:\idf\.espressif\v6.0.2")
IDF6_PATH = IDF6_ROOT / "esp-idf"
IDF6_VENV = IDF6_ROOT / "tools" / "python" / "v6.0.2" / "venv"
IDF6_XTENSA = IDF6_ROOT / "tools" / "xtensa-esp-elf" / "esp-15.2.0_20251204" / "xtensa-esp-elf" / "bin"
IDF6_CMAKE = IDF6_ROOT / "tools" / "cmake" / "4.0.3" / "bin"
NINJA = Path(r"C:\Espressif\tools\ninja\1.12.1")
CCACHE = Path(r"C:\Espressif\tools\ccache\4.12.1\ccache-4.12.1-windows-x86_64")

# 需要从 PATH 中剔除的旧工具链片段（避免混入 5.5.4 环境）
_PATH_BLOCK_RE = re.compile(
    r"xtensa-esp-elf|riscv32-esp-elf|esp-clang|idf5\.5|python_env\\idf5|frameworks\\esp-idf-v5",
    re.IGNORECASE,
)

# app 二进制名（CMakeLists.txt 中 project() 定义）
APP_BIN = "esp-ai-idf-client.bin"

# OTA 分区大小上限（partitions.csv: ota_0/ota_1 各 6MB）
OTA_PARTITION_MAX = 6 * 1024 * 1024

# 各目标芯片的全量固件合并布局（偏移, 相对 build 目录的文件）
MERGE_LAYOUT = {
    "esp32s3": [
        (0x0, "bootloader/bootloader.bin"),
        (0x8000, "partition_table/partition-table.bin"),
        (0xD000, "ota_data_initial.bin"),
        (0x10000, "srmodels/srmodels.bin"),
        (0x100000, APP_BIN),
    ],
    "esp32c3": [
        (0x0, "bootloader/bootloader.bin"),
        (0x8000, "partition_table/partition-table.bin"),
        (0x10000, "srmodels/srmodels.bin"),
        (0x60000, APP_BIN),
    ],
}


# ──────────────────────────────────────────────
# 环境
# ──────────────────────────────────────────────
def build_env() -> dict:
    """构造 ESP-IDF 6.0.2 编译环境（与 build.ps1 一致）。"""
    for p in (IDF6_PATH, IDF6_VENV, IDF6_XTENSA, IDF6_CMAKE, NINJA):
        if not p.exists():
            raise FileNotFoundError(f"ESP-IDF 路径不存在: {p}")

    env = os.environ.copy()
    env["IDF_PATH"] = str(IDF6_PATH)
    env["IDF_TOOLS_PATH"] = str(IDF6_ROOT)
    env["IDF_PYTHON_ENV_PATH"] = str(IDF6_VENV)
    env["IDF_CCACHE_ENABLE"] = "0"

    clean = [p for p in env.get("PATH", "").split(";") if p and not _PATH_BLOCK_RE.search(p)]
    env["PATH"] = ";".join(
        [str(IDF6_VENV / "Scripts"), str(IDF6_XTENSA), str(IDF6_CMAKE), str(NINJA), str(CCACHE)]
        + clean
    )
    return env


def git_short_commit() -> str:
    """当前 git 短提交号，用于固件命名。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_DIR, capture_output=True, text=True, timeout=10,
        )
        commit = out.stdout.strip()
        if commit:
            return commit
    except Exception:
        pass
    return "unknown"


def detect_target() -> str:
    """从 sdkconfig 读取目标芯片。"""
    sdkconfig = PROJECT_DIR / "sdkconfig"
    if sdkconfig.exists():
        for line in sdkconfig.read_text(encoding="utf-8").splitlines():
            m = re.match(r"CONFIG_IDF_TARGET_(\w+)=y", line.strip())
            if m and not m.group(1).startswith("ARCH"):
                return m.group(1).lower()
    raise RuntimeError("无法从 sdkconfig 识别目标芯片，请用 --target 指定")


# ──────────────────────────────────────────────
# 构建
# ──────────────────────────────────────────────
def run_build(env: dict) -> None:
    """执行 idf.py build。"""
    python_exe = IDF6_VENV / "Scripts" / "python.exe"
    idf_py = IDF6_PATH / "tools" / "idf.py"
    cmd = [str(python_exe), str(idf_py), "build"]
    print(f"[build] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=PROJECT_DIR, env=env, check=True)


# ──────────────────────────────────────────────
# 打包
# ──────────────────────────────────────────────
def package(target: str, name: str, out_dir: Path, env: dict) -> tuple[Path, Path]:
    """生成 OTA 固件与全量固件，返回 (ota_path, full_path)。"""
    build_dir = PROJECT_DIR / "build"
    app_bin = build_dir / APP_BIN
    if not app_bin.exists():
        raise FileNotFoundError(f"未找到 app 固件: {app_bin}，请先编译（或去掉 --no-build）")

    # OTA 固件大小检查（分区 6MB 上限）
    app_size = app_bin.stat().st_size
    if app_size > OTA_PARTITION_MAX:
        print(f"[warn] app 固件 {app_size / 1024 / 1024:.2f}MB 超过 OTA 分区上限 "
              f"{OTA_PARTITION_MAX / 1024 / 1024:.0f}MB，OTA 升级可能写失败！")

    commit = git_short_commit()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) OTA 固件：纯 app 二进制
    ota_path = out_dir / f"{target}-{name}-{commit}.bin"
    shutil.copy2(app_bin, ota_path)
    print(f"[ota ] {ota_path}  ({app_size / 1024 / 1024:.2f}MB)")

    # 2) 全量固件：esptool merge-bin 合并
    layout = MERGE_LAYOUT.get(target)
    if layout is None:
        raise ValueError(f"不支持的芯片: {target}，可用: {list(MERGE_LAYOUT)}")

    full_path = out_dir / f"{target}-{name}-{commit}-flash-all.bin"
    python_exe = IDF6_VENV / "Scripts" / "python.exe"
    cmd = [str(python_exe), "-m", "esptool", "--chip", target, "merge-bin", "-o", str(full_path)]
    missing = []
    for offset, rel in layout:
        src = build_dir / rel
        if not src.exists():
            missing.append(rel)
            continue
        cmd += [f"0x{offset:x}", str(src)]
    if missing:
        print(f"[warn] 以下合并项缺失，已跳过: {', '.join(missing)}")
    if len(cmd) <= 6:  # 只有 esptool 基础参数，没有任何输入文件
        raise FileNotFoundError("没有可合并的固件文件，无法生成全量固件")

    print(f"[full] 合并全量固件: {' '.join(cmd[6:])}")
    subprocess.run(cmd, cwd=PROJECT_DIR, env=env, check=True)
    full_size = full_path.stat().st_size
    print(f"[full] {full_path}  ({full_size / 1024 / 1024:.2f}MB)")

    return ota_path, full_path


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="构建 esp-ai-idf-client 固件，同时生成全量固件与 OTA 升级固件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--target", choices=list(MERGE_LAYOUT), default=None,
                        help="目标芯片（默认从 sdkconfig 读取）")
    parser.add_argument("--name", default="xiaoming",
                        help="固件名称（默认 xiaoming，输出为 {chip}-{name}-{commit}.bin）")
    parser.add_argument("--out", default="dist",
                        help="输出目录（默认 dist）")
    parser.add_argument("--no-build", action="store_true",
                        help="跳过编译，只打包已构建的产物")
    args = parser.parse_args()

    env = build_env()
    target = args.target or detect_target()
    out_dir = (PROJECT_DIR / args.out).resolve()

    print("=" * 60)
    print(f"  目标芯片 : {target}")
    print(f"  固件名称 : {args.name}")
    print(f"  输出目录 : {out_dir}")
    print("=" * 60)

    if not args.no_build:
        run_build(env)
    else:
        print("[skip] 跳过编译（--no-build）")

    ota_path, full_path = package(target, args.name, out_dir, env)

    print("-" * 60)
    print(f"OTA 升级固件 : {ota_path}")
    print(f"全量烧录固件 : {full_path}")
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
