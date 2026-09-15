"""M3c/M7 截图 + 便笺蒙版纯净度证据（开发工具，允许 PIL；不触碰真实网络/cookie/注册表写入）。

运行：`python tests\\capture_m3c.py [--outdir DIR] [--prefix m3c] [--real]
       [--shots preview,settings,credential,hover,spin,noaddon,badge,key_openai,key_opencode_go]`
- preview/settings：浮窗+面板截图（--real 用真实 config+cookie+网络，写盘仍进 tmp）；
- 浮窗置于纯色背景窗之上截图，逐像素统计「纸形蒙版外」非背景像素数（纯净度判据，应为 0）；
- hover/spin（M7b⑦）：↻ 图标 hover 底色帧与 60° 步进旋转中间帧；
- noaddon（M7b⑥）：addon=None 场景行高回落 + 细条带零残影像素扫描；
- badge（M7b④）：Pro 徽章 10× 放大裁剪证据图。
"""
from __future__ import annotations

import argparse
import math
import shutil
import sys
import tempfile
import time
import ctypes
import ctypes.wintypes as wt
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image                                       # noqa: E402  仅 dev 工具依赖

from src import config as config_mod, state as state_mod    # noqa: E402
from src.scheduler import Scheduler                         # noqa: E402
from src.sources.base import Usage, Window                  # noqa: E402
from src.state import DEFAULTS                              # noqa: E402
from src.ui import NoteApp, R_IN, FOLD_IN, M_IN             # noqa: E402
import main as main_mod                                     # noqa: E402

BG_COLOR = "#2e8b57"          # 纯色壁纸替身（与任何便笺配色都远）
BG_RGB = (46, 139, 87)
PAD = 22                      # 窗口外留白（含顶边外 20px 条带）
CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False, "enabled_providers": ["bailian"]}
_NOW = datetime.now(timezone.utc)


def u_ok_demo() -> Usage:
    """与审查质疑同口径：7d 周期 40,000，已用 24,853 → 62.1%；加油包剩 15,000/总 20,000。"""
    period_total, period_left = 40000.0, 15147.0
    addon = 15000.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=period_total - period_left, total=60000.0,
                 remaining=period_left + addon,
                 pct_used=(period_total - period_left) / period_total,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", (period_total - period_left) / period_total,
                                 _NOW + timedelta(hours=8, minutes=2))],
                 addon_remaining=addon)


def u_noaddon_demo() -> Usage:
    """M7b⑥ 零占位对照：同周期数字、无加油包（addon_remaining=None）。"""
    period_total, period_left = 40000.0, 15147.0
    pct = (period_total - period_left) / period_total
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=period_total - period_left, total=period_total,
                 remaining=period_left, pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))],
                 addon_remaining=None)


# ---------- Win32 屏幕抓取 ----------

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def grab(x: int, y: int, w: int, h: int) -> Image.Image:
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    hdc = u.GetDC(0)
    mem = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mem, bmp)
    g.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)  # SRCCOPY
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(bih)
    bih.biWidth, bih.biHeight = w, -h               # 负高 = top-down
    bih.biPlanes, bih.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bih), 0)
    img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")
    g.DeleteObject(bmp)
    g.DeleteDC(mem)
    u.ReleaseDC(0, hdc)
    return img


def win_rect(win: tk.Misc) -> tuple[int, int, int, int]:
    win.update_idletasks()
    return win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()


def capture(win: tk.Misc, path: Path) -> tuple[int, int, int, int]:
    x, y, w, h = win_rect(win)
    img = grab(x - PAD, y - PAD, w + 2 * PAD, h + 2 * PAD)
    img.save(path)
    return x, y, w, h


# ---------- 蒙版纯净度检测 ----------

def check_note_purity(app: NoteApp, x: int, y: int, w: int, h: int) -> dict:
    """纸形蒙版外（含 fold 切口）必须全部为背景色；顶边外 20px 条带同查。"""
    S = app.S
    r = R_IN * S
    fr = FOLD_IN * S
    img = grab(x - PAD, y - PAD, w + 2 * PAD, h + 2 * PAD)
    _px = img.load()
    if _px is None:
        raise RuntimeError("PIL img.load() returned None")
    px: Any = _px

    def pix(wx: int, wy: int):                    # 窗口坐标 → 图像坐标
        return px[wx + PAD, wy + PAD]

    def is_bg(c, tol=2):
        return all(abs(a - b) <= tol for a, b in zip(c, BG_RGB))

    def outside_paper(wx: float, wy: float) -> bool:
        if wx < r and wy < r:
            return (wx - r) ** 2 + (wy - r) ** 2 > r * r
        if wx > w - r and wy < r:
            return (wx - (w - r)) ** 2 + (wy - r) ** 2 > r * r
        if wx < r and wy > h - r:
            return (wx - r) ** 2 + (wy - (h - r)) ** 2 > r * r
        if wx > w - fr and wy > h - fr:            # 右下卷边：对角线外 = 透明切口
            return wx + wy > w + h - fr + 1.0      # 色键三角填充区内侧（留 1px 描边带）
        return False

    def fold_diagonal_band(wx: float, wy: float) -> bool:
        """卷边切口对角线 ±1px 带：描边/填充几何交界，不参与「纸面实心」判定。"""
        return (wx > w - fr and wy > h - fr
                and abs(wx + wy - (w + h - fr)) <= 1.0)

    def arc_judgment_zone(wx: float, wy: float) -> bool:
        """四角圆弧边界内侧 1.2px 带：canvas 图元栅格化与像素中心测试的固有
        判定差（≤1px，肉眼为纸缘极限像素，非透明残留），不参与实心判定。
        「蒙版外零残留」仍按严格判据 dist>r（outside_paper），不放宽。"""
        for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
            if abs(math.hypot(wx - cx, wy - cy) - r) < 1.2:
                return True
        return False

    stray_top = 0
    stray_all = 0
    for yy in range(h):
        for xx in range(w):
            if outside_paper(xx + 0.5, yy + 0.5):
                if not is_bg(pix(xx, yy)):
                    stray_all += 1
                    if yy < r * 2:                 # 顶边区（含两上角）
                        stray_top += 1
    strip_above = sum(1 for yy in range(PAD - 20, PAD) for xx in range(w + 2 * PAD)
                      if not is_bg(px[xx, yy]))
    holes: list[tuple[int, int]] = []
    paper_hole = sum(1 for yy in range(h) for xx in range(w)
                     if not outside_paper(xx + 0.5, yy + 0.5)
                     and not fold_diagonal_band(xx + 0.5, yy + 0.5)
                     and not arc_judgment_zone(xx + 0.5, yy + 0.5)
                     and is_bg(pix(xx, yy)) and holes.append((xx, yy)) is None)
    if holes:
        print("HOLES:", holes[:24], f"(w={w} h={h} r={r:.1f} fr={fr:.1f} S={app.S:.3f})")
    return {"outside_paper_all": stray_all, "outside_paper_top": stray_top,
            "strip_above20": strip_above, "paper_solid_ok": paper_hole == 0,
            "paper_holes": paper_hole}


# ---------- 主流程 ----------

def run(outdir: Path, prefix: str, real: bool = False,
        shots: set[str] | None = None) -> int:
    shots = shots or {"preview", "settings", "credential"}
    outdir.mkdir(parents=True, exist_ok=True)
    if real:
        # 真实配置必须在写盘重定向到 tmp 之前读（只读；cookie 由源自行加载，不落写）
        real_cfg = config_mod.load_config()
    else:
        real_cfg = None
    tmp = Path(tempfile.mkdtemp(prefix="m3c_cap_"))
    orig_cfg, orig_state, orig_dir = config_mod.CONFIG_PATH, state_mod.STATE_PATH, state_mod.LOCAL_DIR
    config_mod.CONFIG_PATH = tmp / "config.json"
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    if real:
        # 真实数据：读真实 config/cookie（只读），跑真实 Scheduler；写盘全进 tmp
        cfg = config_mod.load_config()
        from src.registry import active_sources
        sched = Scheduler(active_sources(cfg), poll_seconds=cfg["poll_seconds"],
                          low_yellow_pct=cfg["low_yellow_pct"])
        app = NoteApp(root, cfg, sched, state=dict(DEFAULTS))
        sched.start()
    else:
        sched = Scheduler([], poll_seconds=300)
        app = NoteApp(root, dict(CFG), sched, state=dict(DEFAULTS))

    # 纯色背景窗（覆盖整个主屏工作区）
    scr_w = root.winfo_screenwidth()
    scr_h = root.winfo_screenheight()
    bg = tk.Toplevel(root)
    bg.overrideredirect(True)
    bg.attributes("-topmost", True)
    bg.geometry(f"{scr_w}x{scr_h}+0+0")
    bg.configure(bg=BG_COLOR)
    bg.lift()
    root.update()
    time.sleep(0.45)

    if real:
        t0 = time.time()
        while not app.usages and time.time() - t0 < 35:
            root.update()
            time.sleep(0.1)
        print(f"REAL usages: "
              f"{[(u.provider, u.ok, u.error_code) for u in app.usages]}", flush=True)
    else:
        app.usages = [u_ok_demo()]
        app.meta = {"next_delay": 300, "ts": time.time(), "low": False}
        app.last_good = {"bailian": app.usages[0]}
        app._render()
    root.lift()
    root.update()
    time.sleep(0.45)

    res = {}
    if "preview" in shots:
        x, y, w, h = capture(app.root, outdir / f"{prefix}_preview.png")
        res["preview"] = check_note_purity(app, x, y, w, h)
        print("PREVIEW purity:", res["preview"], flush=True)

    # ---- M7b⑦ 图标 hover 帧（真实 <Motion> 分发） ----
    if "hover" in shots:
        ic = app._refresh_geo
        if ic is None:
            raise RuntimeError("refresh icon not rendered")
        app.canvas.event_generate("<Motion>", x=int(ic[0]), y=int(ic[1]))
        root.update()
        time.sleep(0.25)
        app._tip_hide()                       # 只拍 hover 底色帧（tooltip 是 Motion 副产物）
        root.update()
        x, y, w, h = capture(app.root, outdir / f"{prefix}_hover.png")
        img = Image.open(outdir / f"{prefix}_hover.png").convert("RGB")
        px0 = img.load()
        PAPERISH = [(0xFB, 0xF3, 0xDF), (0xE3, 0xD3, 0xA9)]   # 纸底/主轨：hover 圆内不应有
        cx, cy, rad = ic[0] + PAD, ic[1] + PAD, ic[2]
        n_tx = sum(1 for yy in range(int(cy - 3), int(cy + 4))
                   for xx in range(int(cx - 3), int(cx + 4))
                   if all(abs(a - b) <= 4 for a, b in zip(px0[xx, yy], (238, 223, 184))))
        print("HOVER rotbg PAPER_TX 像素数（中心区，应 >0）:", n_tx, flush=True)
        app.canvas.event_generate("<Motion>", x=5, y=h - 5)   # 移出复位
        root.update()

    # ---- M7b⑦ 旋转中间帧（tick → fetching → 60° 步进） ----
    if "spin" in shots:
        app.sched.events.put(("tick", None, {}))
        t0 = time.time()
        while app._rot < 120 and time.time() - t0 < 6:
            root.update()
            time.sleep(0.02)
        print("SPIN rot =", app._rot, "job running =", app._spin_job is not None, flush=True)
        capture(app.root, outdir / f"{prefix}_spin.png")
        app.sched.events.put(("update", app.usages,
                              {"next_delay": 300, "ts": time.time(), "low": False}))
        for _ in range(20):
            root.update()
            time.sleep(0.02)

    # ---- M7b⑥ 零占位闭环：行高回落精确 + 细条带像素扫描无残留 ----
    if "noaddon" in shots:
        from src.ui import ROW_ADDON, ADDON_FILL, TRACK, TRACK_EDGE
        def hx(col: str) -> tuple[int, ...]:
            s = col.lstrip("#")
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))

        app.usages = [u_ok_demo()]
        app._render()
        root.update()
        h_addon = int(app.canvas.cget("height"))
        app.usages = [u_noaddon_demo()]
        app._render()
        root.update()
        time.sleep(0.3)
        x, y, w, h = capture(app.root, outdir / f"{prefix}_noaddon.png")
        h_no = int(app.canvas.cget("height"))
        delta = h_addon - h_no
        img = Image.open(outdir / f"{prefix}_noaddon.png").convert("RGB")
        pxy = img.load()
        band = [hx(ADDON_FILL), hx(TRACK), hx(TRACK_EDGE)]
        y0 = int(52 + 70 + PAD)                       # 主条下缘(y+69)起，覆盖细条原占位带
        stray = sum(1 for yy in range(y0, y0 + int(ROW_ADDON * app.S) + 4)
                    for xx in range(18 + PAD, w - 18 + PAD)
                    if any(all(abs(a - b) <= 3 for a, b in zip(pxy[xx, yy], t)) for t in band))
        print(f"NOADDON h_addon={h_addon} h_no={h_no} delta={delta}"
              f"（期望≈{round(ROW_ADDON * app.S)}） 细条带残影像素={stray}", flush=True)
        res["noaddon"] = {"delta": delta, "stray_band": stray}

    # ---- M7b④ Pro 徽章 10× 证据图 ----
    if "badge" in shots:
        app.usages = [u_ok_demo()]
        app._render()
        root.update()
        time.sleep(0.2)
        c = app.canvas
        tb = [c.bbox(i) for i in c.find_all()
              if c.type(i) == "text" and c.itemcget(i, "text") == "Pro"]
        if not tb:
            raise RuntimeError("Pro badge text not found")
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty()
        bx = tb[0]
        img = grab(x + bx[0] - 14, y + bx[1] - 12, (bx[2] - bx[0]) + 34, 46)
        img.resize((img.width * 10, img.height * 10), Image.NEAREST) \
           .save(outdir / f"{prefix}_badge.png")

    if "settings" in shots:
        app.open_settings()
        root.update()
        time.sleep(0.5)
        panel = app._settings
        if panel is None:
            raise RuntimeError("settings panel did not open")
        capture(panel, outdir / f"{prefix}_settings.png")
        panel.close_card()

    if "settings_on" in shots:
        # M8 视觉轮①演示态：勾选启用 + 预填 127.0.0.1 / 7890（仅入内存 cfg 渲染，
        # 不点击「测试连通」、不发网络请求；config 写盘本就重定向 tmp）
        app.cfg["network"] = {"proxy_enabled": True, "proxy_url": "127.0.0.1:7890",
                              "proxy_targets": ["openai", "opencode_go"]}
        app.open_settings()
        root.update()
        time.sleep(0.5)
        panel = app._settings
        if panel is None:
            raise RuntimeError("settings panel did not open (on)")
        capture(panel, outdir / f"{prefix}_settings_on.png")
        panel.close_card()

    if "credential" in shots:
        app.open_credentials()
        root.update()
        time.sleep(0.5)
        cred = app._cred_panel
        if cred is None:
            raise RuntimeError("credential panel did not open")
        capture(cred, outdir / f"{prefix}_credential.png")
        cred.close_card()

    for prov in ("openai", "opencode_go"):
        if f"key_{prov}" not in shots:
            continue
        app.open_key_panel(prov)
        root.update()
        time.sleep(0.5)
        kp = app._key_panels.get(prov)
        if kp is None:
            raise RuntimeError(f"key panel {prov} did not open")
        capture(kp, outdir / f"{prefix}_key_{prov}.png")
        kp.close_card()

    app.quit()
    if real:
        sched.stop()
    shutil.rmtree(tmp, ignore_errors=True)

    ok = True
    if "preview" in shots:
        p = res["preview"]
        ok = (p["outside_paper_all"] == 0 and p["outside_paper_top"] == 0
              and p["strip_above20"] == 0 and p["paper_solid_ok"])
    if "noaddon" in shots:
        from src.ui import ROW_ADDON
        na = res["noaddon"]
        ok = ok and na["stray_band"] == 0 and abs(na["delta"] - round(ROW_ADDON * app.S)) <= 1
    print("PURITY:", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=str(ROOT / "local"))
    ap.add_argument("--prefix", default="m3c")
    ap.add_argument("--real", action="store_true",
                    help="真实 config+cookie+网络数据截图（写盘仍进 tmp；state.json 例外允许落真实位置）")
    ap.add_argument("--shots", default="preview,settings,credential",
                    help="逗号分隔：preview,settings,settings_on,credential,hover,spin,"
                         "noaddon,badge,key_openai,key_opencode_go")
    a = ap.parse_args()
    raise SystemExit(run(Path(a.outdir), a.prefix, real=a.real,
                         shots=set(s.strip() for s in a.shots.split(","))))
