"""M9 视觉自证：真实释放路径把窗吸到右边缘 / 右下角，截图留证。

运行：`python tests\\capture_m9.py`（需可用桌面会话）。
- 注入手法：合成事件对象直驱真实 _drag_start/_drag_move/_drag_end（同 test_m7 注入
  约定，绝对坐标字段给足）；不用 SendInput——不劫持用户真实鼠标，拖拽语义等价。
- 吸附全程用**真实** work_areas()（EnumDisplayMonitors），非伪造。
- state/config 重定向 temp：真实 local\\state.json 不动；结束把窗口复位到启动原位。
- 证据：每案打印 窗 rect vs 工作区边界 数值并断言 0 间距（贴边列像素因圆角/卷边
  是色键透出桌面，像素判据不可靠，故以几何 rect 判据为准，截图为视觉佐证）。
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from src import config as config_mod, state as state_mod      # noqa: E402
from src.scheduler import Scheduler                           # noqa: E402
from src.sources.base import Usage, Window                    # noqa: E402
from src.state import DEFAULTS                                # noqa: E402
from src import ui as ui_mod                                  # noqa: E402
from src.ui import NoteApp                                    # noqa: E402
import capture_m3c as cap                                     # noqa: E402
import main as main_mod                                       # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}
_NOW = datetime.now(timezone.utc)


def u_ok() -> Usage:
    weekly, pct, ar = 40000.0, 0.612, 1508.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))],
                 addon_remaining=ar)


def pump(app, ms: float) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.root.update()
        time.sleep(0.01)


def settle_snap(app, timeout_ms: float = 800.0) -> None:
    t0 = time.monotonic()
    while app._snap_anim is not None and (time.monotonic() - t0) * 1000 < timeout_ms:
        app.root.update()
        time.sleep(0.01)
    pump(app, 60)                       # 收尾几拍，让 WM 落位
    app.root.update()


def snap_drag(app, nx: int, ny: int) -> None:
    """真实拖拽释放路径：按下→位移→松开（终点让窗左上角落在 (nx,ny)）。"""
    app.root.update_idletasks()
    ox, oy = app.root.winfo_x(), app.root.winfo_y()

    def ev(xr, yr):
        return types.SimpleNamespace(x_root=xr, y_root=yr, x=60.0, y=30.0)

    app._drag_start(ev(ox + 60, oy + 30))
    app._drag_move(ev(nx + 60, ny + 30))
    app._drag_end(ev(nx + 60, ny + 30))


def win_rect(root: tk.Tk) -> tuple[int, int, int, int]:
    root.update_idletasks()
    root.update()
    return (root.winfo_rootx(), root.winfo_rooty(),
            root.winfo_width(), root.winfo_height())


def grab_note(app, path: Path, extra_right: int, extra_bottom: int) -> tuple:
    """抓窗体 + 外沿（extra 为越过屏/任务栏界的多采宽度，自动截到虚拟屏内）。"""
    x, y, w, h = win_rect(app.root)
    scr_w = app.root.winfo_screenwidth()
    x1 = min(x + w + extra_right, 4000)
    y1 = y + h + extra_bottom
    gx, gy = x - 32, y - 32
    gw, gh = (x1 - gx), (y1 - gy)
    img = cap.grab(max(0, gx), max(0, gy), gw, gh)
    img.save(path)
    print(f"   截图 {path.name}: 窗 rect=({x},{y},{x + w},{y + h}) 图 {img.size}")
    return (x, y, x + w, y + h)


def run(tmp: Path) -> int:
    orig = (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR)
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state=dict(DEFAULTS))
    start_pos = app._pos
    fails = 0
    try:
        # 数据投喂 + 上屏
        app.sched.events.put(("update", [u_ok()],
                              {"next_delay": 300, "ts": time.time(), "low": False}))
        pump(app, 400)
        root.deiconify()
        root.attributes("-topmost", True)
        pump(app, 300)

        areas = ui_mod.work_areas()
        wa = areas[0]
        print(f"真实工作区（列首屏）: {wa}；显示器数={len(areas)}；S={app.S:.3f}")
        l, t, r, b = wa

        # ---- 案 A：拖到右缘阈值内松手 → 吸右（y 远离上下界，只横轴吸）----
        _, _, w, h = win_rect(root)
        drag_x, drag_y = r - w - 12, t + 160
        snap_drag(app, drag_x, drag_y)
        settle_snap(app)
        rect = grab_note(app, ROOT / "local" / "m9_snap_right.png", 32, 0)
        ok_a = rect[2] == r and rect[1] == t + 160
        print(f"  A 右吸: rect={rect} 工作区右界={r} → {'PASS 贴齐(0间距)' if ok_a else 'FAIL'}")
        st = state_mod.load_state()
        print(f"     state.json 终值: x={st['x']} y={st['y']}（应 = {r - w},{t + 160}）")
        ok_a = ok_a and st["x"] == rect[2] - w and st["y"] == rect[1]

        # ---- 案 B：拖到右下角阈值内松手 → 横纵双吸 = 贴角 ----
        pump(app, 150)
        snap_drag(app, r - w - 10, b - h - 6)
        settle_snap(app)
        rect = grab_note(app, ROOT / "local" / "m9_snap_corner.png", 32, 30)
        ok_b = rect[2] == r and rect[3] == b
        print(f"  B 角吸: rect={rect} 工作区右下角=({r},{b}) → "
              f"{'PASS 双轴贴齐' if ok_b else 'FAIL'}")
        fails += (not ok_a) + (not ok_b)

        # ---- 复位：回到启动时位置（真实 state.json 全程未写）----
        app._pos = start_pos
        root.geometry(f"+{start_pos[0]}+{start_pos[1]}")
        pump(app, 120)
        root.withdraw()
        print(f"已复位到启动原位 {start_pos}；真实 local/state.json 未触碰")
    finally:
        try:
            app.quit()
        except Exception:                                # noqa: BLE001
            pass
        (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         config_mod.CONFIG_PATH, config_mod.LOCAL_DIR) = orig

    print("\nM9 视觉自证:", "ALL PASS" if fails == 0 else f"{fails} 案失败")
    return 1 if fails else 0


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m9_cap_") as d:
        raise SystemExit(run(Path(d)))
