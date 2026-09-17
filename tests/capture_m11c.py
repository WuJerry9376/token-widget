"""M11c 视觉闭环：细条方向语义双槽同屏 + 券角标两态（hover/无券对照）。假数据零网络。

运行：`python tests\\capture_m11c.py`（桌面会话；config/state 重定向 temp）。
产物（local\\）：
- m11c_semon_dual.png   加油包细条「剩 X / Y」剩余向 + codex 副细条「已用 x%」已用向，
                        两槽同屏、方向锚字齐备（M11c③ 定案证据）；
- m11c_ticket_hover.png 券×1 角标 + 其 hover 说明 tooltip 实拍（_tip_show 直驱=悬停态）；
- m11c_ticket_none.png  无券对照（角标完全不占位，徽章位仅剩 PLUS）。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import capture_m3c as cap                                        # noqa: E402
from src import config as config_mod, state as state_mod         # noqa: E402
from src.scheduler import Scheduler                              # noqa: E402
from src.sources.base import Usage, Window                       # noqa: E402
from src.state import DEFAULTS                                   # noqa: E402
from src.ui import NoteApp                                       # noqa: E402
import main as main_mod                                          # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian", "codex"]}
_NOW = datetime.now(timezone.utc)
LOCAL = ROOT / "local"


def u_bailian() -> Usage:
    """7d 已用 61.2% + 加油包剩 6,000/总 20,000（细条 30% 剩余向·卡其）。"""
    weekly, pct, ar = 40000.0, 0.612, 6000.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))],
                 addon_remaining=ar)


def u_codex(note: str | None) -> Usage:
    """5h 主条 62%（绿）+ 周副细条 30% 已用向（>0%，M11c③ 主角）+（可选）券×1。"""
    return Usage(provider="codex", ok=True, spec="plus", unit="percent",
                 pct_used=0.62, resets_at=_NOW + timedelta(hours=2, minutes=1),
                 windows=[Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1)),
                          Window("周", 0.30, _NOW + timedelta(days=4, minutes=7))],
                 addon_remaining=12.345, note=note)


def pump(app, ms: float) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.root.update()
        time.sleep(0.01)


def feed(app, *us: Usage) -> None:
    app.sched.events.put(("update", list(us),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    pump(app, 300)


def canvas_texts(app) -> list[str]:
    c = app.canvas
    return [str(c.itemcget(i, "text")) for i in c.find_all() if c.type(i) == "text"]


def main_run(tmp: Path) -> int:
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state=dict(DEFAULTS))
    ok = True
    try:
        # 纯色背景（M3c/m9b 同法）：截图判读干净
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        bg.configure(bg=cap.BG_COLOR)
        bg.lift()
        root.update()

        # ---- 图1：双槽细条同屏（加油包「剩」剩余向 × codex 副条「已用」已用向）----
        feed(app, u_bailian(), u_codex(note="窗口重置券：可用 1"))
        root.deiconify()
        pump(app, 250)
        root.lift()
        pump(app, 350)
        x, y, w, h = cap.capture(app.root, LOCAL / "m11c_semon_dual.png")
        ts = canvas_texts(app)
        chk1 = any(t.startswith("剩 6,000 / 20,000") for t in ts) \
            and "周窗 · 已用 30.0%" in " | ".join(ts)     # M14：codex 周为等尺寸主条块
        print(f"图1 双槽同屏 rect=({x},{y},{w}x{h}) 锚字齐备={chk1}", flush=True)
        ok &= chk1

        # ---- 图2：券×1 hover（_tip_show 直驱=悬停说明态）----
        tk_hit = next(z for z in app.hits if "重置券" in z[4].get("tip", ""))
        cx_root = root.winfo_rootx() + (tk_hit[0] + tk_hit[2]) / 2
        cy_root = root.winfo_rooty() + (tk_hit[1] + tk_hit[3]) / 2
        app._tip_show(tk_hit[4], types.SimpleNamespace(
            x_root=int(cx_root), y_root=int(cy_root)))
        pump(app, 350)
        tip = app._tip
        tx, ty = tip.winfo_rootx(), tip.winfo_rooty()
        tw, th = tip.winfo_width(), tip.winfo_height()
        gx, gy = min(x - 10, tx - 10), min(y - 10, ty - 10)
        g1 = max(x + w, tx + tw) + 10
        g2 = max(y + h, ty + th) + 10
        img = cap.grab(gx, gy, g1 - gx, g2 - gy)
        img.save(LOCAL / "m11c_ticket_hover.png")
        tip_txt = app._tip_text(tk_hit[4])
        lbl = app._tip_lbl.cget("text") if app._tip_lbl else ""
        chk2 = "券 ×1" in str(lbl) and str(lbl) == tip_txt
        print(f"图2 hover tooltip 实拍 {LOCAL.name}\\m11c_ticket_hover.png "
              f"tip={str(lbl)[:40]!r}… 与热区文案同源={chk2}", flush=True)
        ok &= chk2
        app._tip_hide()
        pump(app, 80)

        # ---- 图3：无券对照（角标零占位，与图2 同窗位同数据仅去 note）----
        feed(app, u_bailian(), u_codex(note=None))
        pump(app, 250)
        x3, y3, w3, h3 = cap.capture(app.root, LOCAL / "m11c_ticket_none.png")
        ts3 = canvas_texts(app)
        chk3 = not any(t.startswith("券×") for t in ts3) and (h3 == h)
        print(f"图3 无券对照 rect=({x3},{y3},{w3}x{h3}) 零占位={chk3}", flush=True)
        ok &= chk3

        root.withdraw()
        print("M11C CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                       # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR) = orig


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m11c_cap_") as d:
        raise SystemExit(main_run(Path(d)))
