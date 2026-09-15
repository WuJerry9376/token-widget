"""开机自启（M3）：HKCU\\...\\Run 下仅管理 "token-widget" 这一个值名。

安全约束（用户机器 Run 下有其他条目）：
- 只 SetValueEx / DeleteValue 名为 VALUE_NAME 的值；绝不新建/删除键、绝不枚举改写其他值；
- Run 键系统必然存在，OpenKey 失败即报错返回，不做 CreateKey（避免权限面扩大）。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "token-widget"


def command_line() -> str:
    """自启命令：优先 pythonw.exe（无控制台窗口）+ main.py 绝对路径；打包后为 exe 自身。"""
    if getattr(sys, "frozen", False):            # M4 PyInstaller
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable).resolve()          # .../python.exe 或 pythonw.exe
    pyw = exe.with_name("pythonw.exe")
    launcher = pyw if pyw.exists() else exe
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{launcher}" "{main_py}"'


def read_current() -> str | None:
    """现有 "token-widget" 值内容；不存在返回 None。只读。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, VALUE_NAME)
        return str(val)
    except FileNotFoundError:
        return None


def enable() -> str:
    """写入/更新本值名的自启命令，返回写入的命令串。"""
    import winreg
    cmd = command_line()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, cmd)
    return cmd


def disable() -> bool:
    """删除本值名（不存在视为已关）。返回是否确有删除动作。"""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def is_enabled() -> bool:
    return read_current() is not None


def dry_run_report() -> str:
    """--autostart-dry-run 输出：展示将写入的值名与命令，不做任何写操作。"""
    cur = read_current()
    lines = [
        "[autostart dry-run] 不会写入注册表，仅展示将执行的内容：",
        f"  键    : HKEY_CURRENT_USER\\{RUN_KEY}",
        f"  值名  : {VALUE_NAME}",
        f"  将写入: {command_line()}",
        f"  现值  : {cur if cur is not None else '（不存在）'}",
        "  影响范围: 仅上述单个值名；Run 键下其他条目不做任何读改写。",
    ]
    return "\n".join(lines)
