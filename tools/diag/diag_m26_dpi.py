"""M26 诊断：显示器枚举 + 每屏 DPI + 进程 awareness + 窗口跨屏几何（stdlib only）。

运行：
    python tools\\diag\\diag_m26_dpi.py monitors           # 枚举屏/工作区/DPI
    python tools\\diag\\diag_m26_dpi.py awareness          # 当前进程 awareness 值
    python tools\\diag\\diag_m26_dpi.py scale --get        # 读虚拟屏缩放（注册表 DpiValue，只读）
    python tools\\diag\\diag_m26_dpi.py scale --set N --device KEY [--apply]
                                                     # 改缩放（默认 dry-run；--apply 才写）

设计注记：WM_DPICHANGED 选型证据链在 tests\\test_m26_dpi.py；本脚本仅做环境取证，
不导入产品代码（避免误设 awareness 影响宿主）。
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys

user32 = ctypes.windll.user32
shcore = ctypes.windll.shcore


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                ("szDevice", ctypes.c_wchar * 32)]


ENUM_CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HMONITOR, wt.HDC,
                             ctypes.POINTER(wt.RECT), wt.LONG)


def monitors() -> list[dict]:
    out: list[dict] = []

    def cb(hmon, hdc, lprc, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return True
        dx, dy = ctypes.c_uint(), ctypes.c_uint()
        hr = shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
        prim = bool(mi.dwFlags & 1)
        out.append({
            "handle": hmon,
            "primary": prim,
            "monitor": [mi.rcMonitor.left, mi.rcMonitor.top,
                        mi.rcMonitor.right, mi.rcMonitor.bottom],
            "work": [mi.rcWork.left, mi.rcWork.top,
                     mi.rcWork.right, mi.rcWork.bottom],
            "dpi": dx.value if hr == 0 else None,
            "scale": round(dx.value / 96.0, 3) if hr == 0 else None,
            "name": mi.szDevice,
        })
        return True

    keep = ENUM_CB(cb)
    user32.EnumDisplayMonitors(0, 0, keep, 0)
    return out


def awareness() -> dict:
    val = ctypes.c_int(-1)
    try:
        hr = shcore.GetProcessDpiAwareness(0, ctypes.byref(val))
    except OSError:
        return {"hr": None, "value": None, "mode": "unknown(no shcore)"}
    mode = {0: "unaware", 1: "system", 2: "per-monitor", 3: "per-monitor-v2"}.get(
        val.value, str(val.value))
    return {"hr": hr, "value": val.value, "mode": mode}


# ---------- 缩放注册表读（HKLM 每显卡驱动键 DpiValue / HKCU 每显示设备） ----------

def _reg_scales() -> list[dict]:
    import winreg
    rows = []
    base = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers\Configuration"
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
    except OSError as e:
        return [{"error": f"HKLM Configuration 不可读：{e!r}"}]
    with k:
        for i in range(winreg.QueryInfoKey(k)[0]):
            cfg = winreg.EnumKey(k, i)
            for j in range(winreg.QueryInfoKey(winreg.OpenKey(k, cfg))[0]):
                path = f"{base}\\{cfg}\\{winreg.EnumKey(winreg.OpenKey(k, cfg), j)}"
                try:
                    sk = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
                except OSError:
                    continue
                with sk:
                    try:
                        dv, _ = winreg.QueryValueEx(sk, "DpiValue")
                    except FileNotFoundError:
                        dv = None
                    try:
                        sx, _ = winreg.QueryValueEx(sk, "XResActive")
                        sy, _ = winreg.QueryValueEx(sk, "YResActive")
                    except FileNotFoundError:
                        sx = sy = None
                    rows.append({"path": path, "DpiValue": dv, "res": (sx, sy)})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["monitors", "awareness", "scale"])
    ap.add_argument("--get", action="store_true")
    ap.add_argument("--set", type=int, default=None, help="目标缩放百分数（100/125/150/200）")
    ap.add_argument("--device", default=None, help="DpiValue 注册表 path 片段过滤")
    ap.add_argument("--apply", action="store_true", help="真正写注册表（默认 dry-run）")
    a = ap.parse_args(argv)
    if a.cmd == "monitors":
        for m in monitors():
            print(json.dumps(m, ensure_ascii=False))
    elif a.cmd == "awareness":
        print(json.dumps(awareness()))
    else:
        if a.set is None:
            print(json.dumps(_reg_scales(), ensure_ascii=False, indent=1,
                             default=str))
            return 0
        print("scale --set 写入路径未启用：默认只做读取与 dry-run 计划打印。")
        want = a.set * 96 // 100
        for r in _reg_scales():
            if "error" in r:
                print(r["error"])
                continue
            hit = a.device is None or a.device in r["path"]
            print(f'{"*" if hit else " "} {r["path"]}  DpiValue={r["DpiValue"]}'
                  f'  res={r["res"]}  -> want {want} dpi ({a.set}%)' if hit else "")
        if not a.apply:
            print("DRY-RUN（未写注册表；--apply 才执行，且需管理员）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
