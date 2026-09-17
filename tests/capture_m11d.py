"""M11d 视觉证据：固定槽位——5h 空闲 0% 仍在主条（上），周已用 80% 落副细条（下）。

旧"最紧者=主条"规则下本案周会在上；新规则位置与松紧解耦（5h 恒上、缺位递补），
大数字随主条=100%（5h 剩余，所见即所得），周的紧迫由副条 80% 长 + 倒计时自证。
假数据零网络；config/state 重定向 temp。产物 local\\m11d_order.png。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
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
       "always_on_top": True, "autostart": False, "enabled_providers": ["codex"]}
_NOW = datetime.now(timezone.utc)


def pump(app, ms: float) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.root.update()
        time.sleep(0.01)


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
    try:
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        bg.configure(bg=cap.BG_COLOR)
        bg.lift()
        root.update()

        # 判据案例：5h 全空（0%）、周 80%——旧规则周（最紧）在上，新规则 5h 必在上
        u = Usage(provider="codex", ok=True, spec="plus", unit="percent",
                  pct_used=0.80,            # source 层口径仍=最紧窗（周），不改
                  resets_at=_NOW + timedelta(days=3, hours=20),
                  windows=[Window("周", 0.80, _NOW + timedelta(days=3, hours=20)),
                           Window("5h", 0.0, _NOW + timedelta(hours=5))])
        app.sched.events.put(("update", [u],
                              {"next_delay": 300, "ts": time.time(), "low": False}))
        pump(app, 300)
        root.deiconify()
        pump(app, 250)
        root.lift()
        pump(app, 350)
        x, y, w, h = cap.capture(app.root, ROOT / "local" / "m11d_order.png")
        ts = [str(app.canvas.itemcget(i, "text")) for i in app.canvas.find_all()
              if app.canvas.type(i) == "text"]
        main_txt = "5h · 已用 0.0%" in " | ".join(ts)
        strip_ok = "周窗 · 已用 80.0%" in " | ".join(ts)     # M14：周等尺寸主条块
        big_ok = "100%" in ts and "20%" not in "".join(ts)
        # 槽位顺序证据：主条行（5h）中心必在副细条行（周 label）之上
        c = app.canvas

        def midy(txt_start):
            it = next(i for i in c.find_all() if c.type(i) == "text"
                      and str(c.itemcget(i, "text")).startswith(txt_start))
            bb = c.bbox(it)
            return (bb[1] + bb[3]) / 2

        order_ok = midy("5h · 已用") < midy("周")
        ok = main_txt and strip_ok and big_ok and order_ok
        print(f"rect=({x},{y},{w}x{h}) 主条=5h(0%)上:{main_txt} 副条=周(80%)下:{strip_ok} "
              f"大数字随主条100%:{big_ok} 槽序y:{order_ok}", flush=True)
        print("M11D CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        root.withdraw()
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
    with tempfile.TemporaryDirectory(prefix="m11d_cap_") as d:
        raise SystemExit(main_run(Path(d)))
