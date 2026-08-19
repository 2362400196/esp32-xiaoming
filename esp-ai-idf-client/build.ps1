# ============================================================
# esp-ai-idf-client build script (ESP-IDF 6.0.2)
#
# Usage:
#   .\build.ps1                # build
#   .\build.ps1 flash          # build + flash (default COM3)
#   .\build.ps1 -p COM5 flash
#   .\build.ps1 monitor
#
# This machine has two ESP-IDF installs:
#   - C:\Espressif\...            (5.5.4, GCC 14.2.0)  OLD, has picolibc.specs bug
#   - D:\idf\.espressif\v6.0.2    (6.0.2, GCC 15.2.0)  USED BY THIS PROJECT
# This script activates the 6.0.2 environment only.
# ============================================================

$ErrorActionPreference = "Stop"

# --- IDF 6.0.2 paths ---
$IDF6_ROOT   = "D:\idf\.espressif\v6.0.2"
$IDF6_PATH   = "$IDF6_ROOT\esp-idf"
$IDF6_VENV   = "$IDF6_ROOT\tools\python\v6.0.2\venv"
$IDF6_XTENSA = "$IDF6_ROOT\tools\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin"
$IDF6_CMAKE  = "$IDF6_ROOT\tools\cmake\4.0.3\bin"
# ninja/ccache reused from C:\Espressif (versions match what 6.0.2 expects: 1.12.1 / 4.12.1)
$NINJA       = "C:\Espressif\tools\ninja\1.12.1"
$CCACHE      = "C:\Espressif\tools\ccache\4.12.1\ccache-4.12.1-windows-x86_64"

# --- sanity checks ---
foreach ($p in @($IDF6_PATH, $IDF6_VENV, $IDF6_XTENSA, $IDF6_CMAKE, $NINJA)) {
    if (-not (Test-Path $p)) { Write-Host "[ERROR] Path not found: $p" -ForegroundColor Red; exit 1 }
}

# --- set environment ---
$env:IDF_PATH = $IDF6_PATH
$env:IDF_TOOLS_PATH = $IDF6_ROOT
$env:IDF_PYTHON_ENV_PATH = $IDF6_VENV
$env:IDF_CCACHE_ENABLE = "0"

# Build a clean PATH: drop 5.5.4 toolchain entries, prepend 6.0.2 ones
$clean = $env:PATH -split ';' | Where-Object {
    $_ -and $_ -notmatch 'xtensa-esp-elf|riscv32-esp-elf|esp-clang|idf5\.5|python_env\\idf5|frameworks\\esp-idf-v5'
}
$env:PATH = (
    "$IDF6_VENV\Scripts;" +
    "$IDF6_XTENSA;" +
    "$IDF6_CMAKE;" +
    "$NINJA;" +
    "$CCACHE;" +
    ($clean -join ';')
)

# --- parse args (support -p port) ---
$idfPy = "$IDF6_PATH\tools\idf.py"
$pythonExe = "$IDF6_VENV\Scripts\python.exe"

$port = "COM3"
$argsList = @()
$i = 0
while ($i -lt $args.Count) {
    if ($args[$i] -eq "-p" -and ($i + 1) -lt $args.Count) { $port = $args[$i + 1]; $i += 2; continue }
    $argsList += $args[$i]
    $i++
}
if ($argsList.Count -eq 0) { $argsList = @("build") }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  ESP-IDF: 6.0.2  (D:\idf\.espressif\v6.0.2)" -ForegroundColor Cyan
Write-Host "  Toolchain: xtensa-esp-elf 15.2.0" -ForegroundColor Cyan
Write-Host "  CMake: 4.0.3 | Ninja: 1.12.1" -ForegroundColor Cyan
Write-Host "  Port: $port" -ForegroundColor Cyan
Write-Host "  Command: idf.py $($argsList -join ' ')" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

if ($argsList -contains "flash") {
    & $pythonExe $idfPy -p $port @argsList
} else {
    & $pythonExe $idfPy @argsList
}

exit $LASTEXITCODE
