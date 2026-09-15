# token-widget M4 一键打包脚本。
#   pwsh -File build\build.ps1              # 完整重建（含图标生成）
#   pwsh -File build\build.ps1 -SkipIcon    # 复用已有 build\icon\token-widget.ico
#   pwsh -File build\build.ps1 -ConsoleVariant  # 附加构建 console 冒烟变体 TokenWidgetConsole.exe
# 产物：dist\TokenWidget.exe（windowed onefile）。详见 build\README.md。
[CmdletBinding()]
param(
    [switch]$SkipIcon,
    [switch]$ConsoleVariant
)
$ErrorActionPreference = 'Stop'
$Root  = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root 'build'
$Dist  = Join-Path $Root 'dist'
$Ico   = Join-Path $Build 'icon\token-widget.ico'
$Spec  = Join-Path $Build 'token-widget.spec'
$Work  = Join-Path $Build '_pyi'   # PyInstaller 中间产物目录（不污染 build 根部）
$Sw    = [System.Diagnostics.Stopwatch]::StartNew()

Write-Host "[build] root = $Root"

# 1) 图标
if (-not $SkipIcon) {
    Write-Host '[build] 生成图标 (make_icon.py)…'
    python (Join-Path $Build 'icon\make_icon.py')
    if ($LASTEXITCODE -ne 0) { throw "make_icon.py 失败 (exit=$LASTEXITCODE)" }
}
if (-not (Test-Path -LiteralPath $Ico)) {
    throw "缺少图标 $Ico 且指定了 -SkipIcon；请先不带 -SkipIcon 跑一次。"
}

# 2) 清空重建
foreach ($d in @($Dist, $Work)) {
    if (Test-Path -LiteralPath $d) {
        Get-ChildItem -LiteralPath $d -Recurse | Out-Null   # 触发一次枚举确认存在
        Remove-Item -LiteralPath $d -Recurse -Force
        Write-Host "[build] 已清空 $d"
    }
}

# 3) PyInstaller
Write-Host '[build] 运行 PyInstaller (onefile/windowed)…'
python -m PyInstaller --noconfirm --distpath $Dist --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败 (exit=$LASTEXITCODE)" }

$Exe = Join-Path $Dist 'TokenWidget.exe'

function Test-PE([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "产物不存在: $Path" }
    $fs = [System.IO.File]::OpenRead($Path)
    try {
        $buf = New-Object byte[] 2
        $fs.Read($buf, 0, 2) | Out-Null
        if ($buf[0] -ne 0x4D -or $buf[1] -ne 0x5A) { throw "非 PE 文件（缺 MZ 头）: $Path" }
        $fs.Position = 0x3C
        $fs.Read($buf, 0, 2) | Out-Null
        $peOff = [BitConverter]::ToInt16($buf, 0)
        $fs.Position = $peOff
        $buf = New-Object byte[] 4
        $fs.Read($buf, 0, 4) | Out-Null
        if (-not ($buf[0] -eq 0x50 -and $buf[1] -eq 0x45 -and $buf[2] -eq 0 -and $buf[3] -eq 0)) {
            throw "PE 签名无效: $Path"
        }
    } finally { $fs.Dispose() }
}

Test-PE $Exe
$Item = Get-Item -LiteralPath $Exe

# 4) 可选 console 冒烟变体（仅调试用：windowed exe 的 stdout 为 devnull，
#    用它验证 --verbose / --autostart-dry-run 的文本输出；不随正式版分发）
if ($ConsoleVariant) {
    Write-Host '[build] 附加构建 console 变体 TokenWidgetConsole.exe…'
    python -m PyInstaller --noconfirm --onefile --console --name TokenWidgetConsole `
        --icon $Ico --distpath $Dist --workpath (Join-Path $Work 'console') `
        --specpath (Join-Path $Work 'console') (Join-Path $Root 'main.py')
    if ($LASTEXITCODE -ne 0) { throw "console 变体构建失败 (exit=$LASTEXITCODE)" }
    Test-PE (Join-Path $Dist 'TokenWidgetConsole.exe')
}

$Sw.Stop()
Write-Host ''
Write-Host '=== 构建完成 ==='
Write-Host ("产物      : {0}" -f $Item.FullName)
Write-Host ("大小      : {0:N1} MB" -f ($Item.Length / 1MB))
Write-Host ("PE 校验   : 通过")
$vi = $Item.VersionInfo
Write-Host ("文件版本  : {0} / 产品 {1} {2}" -f $vi.FileVersion, $vi.ProductName, $vi.ProductVersion)
Write-Host ("构建耗时  : {0:N1} s" -f $Sw.Elapsed.TotalSeconds)
Write-Host ('Python    : ' + (python --version 2>&1))
Write-Host ('PyInstaller: ' + (python -m PyInstaller --version))
