"""M12 取证：①设置页代理组启用/禁用两态截图；④↻ 图标新旧渲染 10× 并列对比。

运行：`python tests\\capture_m12.py`（桌面会话；config/state/auth 全重定向 temp，
真实 local\\ 不写）。假数据零网络。
产物（local\\）：
- m12_settings_off.png 未启用代理：地址/端口 Entry 融纸禁用、作用域勾选禁用灰字、按钮无描边；
- m12_settings_on.png  启用后整组回常态（ENTRY_BG 输入底、可点勾选、TRACK 底按钮）；
- m12_spin_icon.png    左=新（4× 超采样 PhotoImage，实拍自真实便签头部）、
  右=旧（create_arc+polygon 手绘示意，现绘于同 S 纸底画布——注明：旧图无纸纹垫底）。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import capture_m3c as cap                                        # noqa: E402
from src import auth, config as config_mod, state as state_mod   # noqa: E402
from src.scheduler import Scheduler                              # noqa: E402
from src.state import DEFAULTS                                   # noqa: E402
from src.ui import (HEAD_INK, PAPER, PAPER_TX, NoteApp)          # noqa: E402
import main as main_mod                                          # noqa: E402
from PIL import Image                                            # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False, "enabled_providers": ["codex"],
       "network": {"proxy_enabled": False, "proxy_url": "127.0.0.1:7890",
                   "proxy_targets": ["opencode_go", "codex"]}}
LOCAL = ROOT / "local"


def pump(app, ms: float) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.root.update()
        time.sleep(0.01)


def draw_old_icon(c: tk.Canvas, cx: float, cy: float, S: float) -> None:
    """M12④ 前的旧手绘版（create_arc+polygon，无抗锯齿）——仅供对比示意。"""
    import math
    rr, s = 6.6 * S, 4.6 * S
    lw = max(1, round(S * 1.6))
    a0 = 70
    c.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, style="arc",
                 start=a0, extent=300, outline=HEAD_INK, width=lw)
    a = math.radians(a0)
    px_, py_ = cx + rr * math.cos(a), cy - rr * math.sin(a)
    tx_, ty_ = math.sin(a), math.cos(a)
    nx, ny = math.cos(a), -math.sin(a)
    c.create_polygon(px_ + tx_ * s, py_ + ty_ * s,
                     px_ + nx * s * 0.60, py_ + ny * s * 0.60,
                     px_ - nx * s * 0.60, py_ - ny * s * 0.60,
                     fill=HEAD_INK, outline="")


def main_run(tmp: Path) -> int:
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "no_cookie.dpapi"
    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state=dict(DEFAULTS))
    ok = True
    try:
        # ================= M12① 设置页两态 =================
        from src import settings_panel
        panel = settings_panel.SettingsPanel(app)
        pump(app, 250)
        panel.update()
        time.sleep(0.4)
        x, y, w, h = cap.capture(panel, LOCAL / "m12_settings_off.png")
        print(f"settings_off rect=({x},{y},{w}x{h}) "
              f"entry={str(panel.ent_px_addr.cget('state'))} "
              f"chk={str(panel.chk_px_cx.cget('state'))} "
              f"btn={str(panel.btn_probe.cget('state'))}", flush=True)
        ok &= str(panel.ent_px_addr.cget("state")) == "disabled" \
            and str(panel.btn_probe.cget("state")) == "disabled"
        panel.var_px_on.set(True)
        panel._sync_probe_btn()
        panel.update()
        time.sleep(0.35)
        x2, y2, w2, h2 = cap.capture(panel, LOCAL / "m12_settings_on.png")
        print(f"settings_on  rect=({x2},{y2},{w2}x{h2}) "
              f"entry={str(panel.ent_px_addr.cget('state'))} "
              f"chk={str(panel.chk_px_go.cget('state'))} "
              f"btn={str(panel.btn_probe.cget('state'))}", flush=True)
        ok &= str(panel.ent_px_addr.cget("state")) == "normal" \
            and str(panel.chk_px_go.cget("state")) == "normal"
        panel.destroy()

        # ================= M12④ ↻ 新旧 10× 并列 =================
        import math
        from datetime import datetime, timedelta, timezone
        from src.sources.base import Usage, Window
        _N = datetime.now(timezone.utc)
        app.sched.events.put(("update", [Usage(
            provider="codex", ok=True, spec="plus", unit="percent", pct_used=0.42,
            resets_at=_N + timedelta(hours=2, minutes=1),
            windows=[Window("5h", 0.42, _N + timedelta(hours=2, minutes=1)),
                     Window("周", 0.30, _N + timedelta(days=4, minutes=7))])],
            {"next_delay": 300, "ts": time.time(), "low": False}))
        pump(app, 300)
        app.root.deiconify()
        pump(app, 250)
        app.root.lift()
        pump(app, 350)
        icx, icy, ird = app._refresh_geo
        half = next(iter(app._rot_images().values())).width() // 2
        wx, wy = app.root.winfo_rootx(), app.root.winfo_rooty()
        W = 2 * half + 1
        # 新：实拍（含纸纹垫底）
        shot_new = cap.grab(wx + int(icx) - half, wy + int(icy) - half, W, W)
        # 旧：同 S 纸底现绘示意（无纸纹，注明于报告）
        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.geometry(f"120x80+{max(0, wx - 160)}+{wy + 200}")
        top.configure(bg=PAPER)
        cv = tk.Canvas(top, width=120, height=80, bg=PAPER, highlightthickness=0)
        cv.pack()
        draw_old_icon(cv, 60, 40, app.S)
        t0 = time.monotonic()
        while not top.winfo_ismapped() and time.monotonic() - t0 < 2:
            root.update()
            top.update()
            time.sleep(0.03)
        pump(app, 500)                              # 让 DWM 完成合成再截
        ox, oy = top.winfo_rootx(), top.winfo_rooty()
        shot_old = cap.grab(ox + 60 - half, oy + 40 - half, W, W)
        top.destroy()
        # 旧示意图底为纯 PAPER（无纸纹点阵）——对比点仅笔画抗锯齿，报告注明
        dark_old = sum(1 for yy in range(W) for xx in range(W)
                       if sum(shot_old.getpixel((xx, yy))[:3]) < 600)
        dark_new = sum(1 for yy in range(W) for xx in range(W)
                       if sum(shot_new.getpixel((xx, yy))[:3]) < 600)
        print(f"旧示意墨像素={dark_old}  新实拍墨像素={dark_new}", flush=True)
        ok &= dark_old > 60 and dark_new > 60
        Z = 10
        nw, nh = W * Z, W * Z
        gap = 6 * Z // 3
        comp = Image.new("RGB", (nw * 2 + gap, nh + 2), (217, 199, 158))
        comp.paste(shot_new.resize((nw, nh), Image.NEAREST), (0, 1))
        comp.paste(shot_old.resize((nw, nh), Image.NEAREST), (nw + gap, 1))
        comp.save(LOCAL / "m12_spin_icon.png")
        print(f"icon 对比 {LOCAL.name}\\m12_spin_icon.png：左=新(超采样实拍 "
              f"{W}px@{app.S:.2f}S) 右=旧(手绘示意，同尺寸同底色) 10× 放大", flush=True)
        app.root.withdraw()
        print("M12 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                       # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE) = orig


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m12_cap_") as d:
        raise SystemExit(main_run(Path(d)))
