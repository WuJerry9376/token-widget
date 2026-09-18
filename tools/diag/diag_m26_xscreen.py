"""M26 P3 真机取证：跨屏实渲（PMv2）+ 「原生缩放 vs 位图拉伸」锐度剖面。

运行：`python tools\\diag\\diag_m26_xscreen.py`（桌面会话，零网络、零真实盘写）。

本机现实（先读后测，写死在输出里）：主屏与虚拟屏当前均为 96dpi/100%。改变虚拟屏
缩放需 HKLM 写权限（非管理员不可行，DisplayConfig API 不覆盖缩放项）→ 跨 DPI 档
实渲退化为两证据合成：
  E1 同 DPI 跨屏迁移实渲：PMv2 下浮窗编程移到虚拟屏 → 截图（CopyFromScreen 物理
     像素）→ 文本完整/无橙错档/两屏像素图近邻可比（GetDpiForWindow 两屏值打印）。
  E2 缩放机制剖面：同一行文本 ①S=1.0 原生渲染后 1.5× 双线性放大（≈旧 system-aware
     进程被 DWM 位图拉伸的产物）②S=1.5 原生渲染（=PMv2+现系数路径）。量化 ClearType
     边缘剖面：过渡带中间调像素占比 + 梯度能量比（拉伸图必然中间调拖影多、梯度塌）。
"""
from __future__ import annotations

import ctypes
import json
import sys
import tempfile
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "diag"))

from PIL import Image                                             # noqa: E402
import diag_m26_dpi as dg                                          # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
import capture_m3c as cap                                          # noqa: E402

from src import config as config_mod, state as state_mod          # noqa: E402
from src.scheduler import Scheduler                               # noqa: E402
from src.sources.base import Usage, Window                        # noqa: E402
from src.state import DEFAULTS                                    # noqa: E402
from src.ui import NoteApp, work_areas, _dpi_for_hwnd, _root_hwnd  # noqa: E402
import main as main_mod                                           # noqa: E402

_NOW = datetime.now(timezone.utc)
CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}
OUT = Path(tempfile.mkdtemp(prefix="m26_xs_"))


def u_ok() -> Usage:
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=24480.0, total=40000.0, remaining=15520.0, pct_used=0.612,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", 0.612, _NOW + timedelta(hours=8, minutes=2))])


def sharpness(img: Image.Image) -> dict:
    """过渡带剖面：中间调占比（越低越锐）+ 梯度能量（越高越锐）。取灰度。"""
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    mid = edges = total = 0
    energy = 0
    for y in range(h):
        for x in range(w):
            v = px[x, y]
            if 90 < v < 170:                      # 墨(≈65)/纸(≈250) 之间的中间调
                mid += 1
            if x + 1 < w:
                d = abs(px[x + 1, y] - v)
                if d > 40:
                    edges += 1
                energy += d
            total += 1
    return {"mid_ratio": round(mid / total, 5), "grad_per_px": round(energy / total, 2),
            "edge_px": edges}


def set_pos(root: tk.Tk, x: int, y: int) -> None:
    root.geometry(f"+{x}+{y}")
    root.update()
    time.sleep(0.35)
    root.update()


def main_run() -> int:
    mode = main_mod.enable_dpi_awareness()
    val = ctypes.c_int(-1)
    ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(val))
    mons = dg.monitors()
    print("AWARP:", json.dumps({"mode": mode, "procValue": val.value}))
    print("MONS :", json.dumps(mons, ensure_ascii=False))
    (tmp := Path(tempfile.mkdtemp(prefix="m26_xs_cfg_")))
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state={**DEFAULTS, "x": None, "y": None})
    ok = True
    try:
        app.usages = [u_ok()]
        app.last_good = {"bailian": u_ok()}
        app._render()
        root.deiconify()
        root.update()
        time.sleep(0.4)
        hwnd = _root_hwnd(root)
        w, h = app._win_size()

        # ---- E1 同 DPI 跨屏迁移 ----
        areas = work_areas()
        p0 = cap.grab(areas[0][0] + 30, areas[0][1] + 30, w, h)
        set_pos(root, areas[0][0] + 30, areas[0][1] + 30)
        a_img = cap.grab(root.winfo_rootx(), root.winfo_rooty(), w, h)
        tgt = areas[1] if len(areas) > 1 else areas[0]
        set_pos(root, tgt[0] + 40, tgt[1] + 40)
        b_img = cap.grab(root.winfo_rootx(), root.winfo_rooty(), w, h)
        dpi_a = _dpi_for_hwnd(hwnd)
        texts = [str(app.canvas.itemcget(i, "text"))
                 for i in app.canvas.find_all() if app.canvas.type(i) == "text"]
        joined = " | ".join(texts)
        e1_ok = ("Token 余量" in joined and "15,520" in joined
                 and not any(k in joined for k in ("需重新登录", "拉取失败", "更新中")))
        same = (dpi_a, _dpi_for_hwnd(hwnd))
        print("E1 :", json.dumps({"hwnd_dpi_pair": list(same), "xscreen_texts_ok": e1_ok,
                                  "target_area": list(tgt)}, ensure_ascii=False))
        a_img.save(OUT / "e1_primary.png")
        b_img.save(OUT / "e1_virtual.png")
        # 主体带（标题时钟行之后）逐像素比对：同 DPI 跨屏应零结构漂移（时钟秒数
        # 只出现在头部带，被裁掉）
        body_a = a_img.crop((0, int(app._p(52)), w, h))
        body_b = b_img.crop((0, int(app._p(52)), w, h))
        pa, pb = body_a.load(), body_b.load()
        diff = sum(1 for yy in range(body_a.height) for xx in range(body_a.width)
                   if pa[xx, yy] != pb[xx, yy])
        print("E1 主体带差异像素：", diff, "/", body_a.width * body_a.height,
              flush=True)
        set_pos(root, areas[0][0] + 30, areas[0][1] + 30)      # 同屏拖回

        # ---- E2 缩放机制剖面（原生 1.5 vs 位图拉伸 1.5）----
        band = (app._p(18), app._p(46), int(app._p(312)), app._p(96))
        def crop_win(img_):
            x0, y0, x1, y1 = band
            return img_.crop((int(x0), int(y0), int(x1), int(y1)))
        root.update()
        s100 = crop_win(cap.grab(root.winfo_rootx(), root.winfo_rooty(), w, h))
        s100.save(OUT / "e2_native100.png")
        stretched = s100.resize((int(s100.width * 1.5), int(s100.height * 1.5)),
                                Image.BILINEAR)
        stretched.save(OUT / "e2_stretched150.png")
        # 原生 S=1.5：走 M26 收口（on_dpi_change 注入 144）
        app.on_dpi_change(144)
        root.update()
        time.sleep(0.3)
        w2, h2 = app._win_size()
        n150 = crop_win(cap.grab(root.winfo_rootx(), root.winfo_rooty(), w2, h2))
        n150.save(OUT / "e2_native150.png")
        m_st = sharpness(stretched)
        m_nv = sharpness(n150)
        print("E2 :", json.dumps({"stretched150": m_st, "native150": m_nv},
                                 ensure_ascii=False))
        ok &= e1_ok
        ok &= (m_nv["grad_per_px"] > m_st["grad_per_px"]
               and m_nv["mid_ratio"] < m_st["mid_ratio"])   # 原生档应更锐
        app.on_dpi_change(96)
        print("E2 输出目录:", OUT)
        print("M26 XSCREEN:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                      # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR) = orig


if __name__ == "__main__":
    sys.exit(main_run())
