# -*- mode: python ; coding: utf-8 -*-
"""token-widget M4 打包 spec：onefile + windowed（noconsole），name=TokenWidget。

由 build/build.ps1 调用（不建议手动跑）。数据文件（local/config.json、state.json、
cookie）**刻意不打包**：datas 为空，凭据/配置必须留在文件系统外部（见 build/README.md
"部署目录结构"）。frozen 下 local/ 解析已由 orchestrator 修复（config/state/auth 三
头部 sys.frozen→exe 同级），部署形态 = exe + 同级 local\\ 文件夹，M4 收口与 M5 换装
均已实证。
"""
import os

# 本 spec 位于 <project>/build/，项目根为上一级
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ICON = os.path.join(SPECPATH, "icon", "token-widget.ico")

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],                      # 绝不打包 local/、cookie、config
    hiddenimports=[
        "tkinter",
        "tkinter.font",            # ui.py 使用 tkfont
        "tkinter.ttk",
        "winreg",                  # autostart.py 函数内 import
        "ctypes",
        "ctypes.wintypes",
        "urllib.request",          # sources/bailian_gateway.py 走 https
        "urllib.error",
        "urllib.parse",
        "ssl",
        "socket",
        "select",
        "json",
        "uuid",
        "unicodedata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 源码里未用到的重依赖，防止间接被拉进来
        "matplotlib", "numpy", "scipy", "pandas", "PIL",
        "test", "unittest", "pydoc_data",
        "httpx", "requests",       # 业务只用 urllib.request（注意：不能排除 http，
                                   # urllib.request 依赖 http.client）
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TokenWidget",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                     # 不 UPX 压缩：降低杀软误报面
    upx_exclude=[],
    runtime_tmpdir=None,           # onefile：解到 %TEMP%\_MEIxxxx（随进程删除）
    console=False,                 # windowed / noconsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON] if os.path.exists(ICON) else None,
    version=os.path.join(SPECPATH, "version_info.txt"),   # E4：exe 属性含版本/产品名
)
