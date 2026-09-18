"""M5 验收 B 组（B1/B3 多显示器钳制逻辑；B2 双屏实机项）。

运行：`python tests\\test_geometry.py`。
钳制真身实现于 `src/ui.py NoteApp._place_initial`（state.py 无钳制、逻辑内联于 ui），
本测试 monkeypatch `ui.work_area` 伪造工作区尺寸 + 伪造 state 坐标，**直调真实方法**
（非复刻算法）。落盘重定向 temp（同 test_render 机制），真实 local/state.json 不写。
"""
from __future__ import annotations

import ctypes
import re
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config as config_mod                     # noqa: E402
from src import state as state_mod                       # noqa: E402
from src import ui as ui_mod                             # noqa: E402
from src.state import DEFAULTS, load_state, save_state   # noqa: E402
from src.ui import NoteApp                               # noqa: E402
from src.scheduler import Scheduler                      # noqa: E402
import main as main_mod                                   # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}


def place(app, wa, x, y, scale=1.0):
    """伪造工作区 + 伪造 state 坐标 → 调真实 _place_initial 钳制路径。

    M26：钳位改按 work_areas()（重叠最大区），伪造时两口径同步单区。"""
    ui_mod.work_area = lambda: wa
    ui_mod.work_areas = lambda: [wa]
    app.S = scale
    app._dpi_watch = False        # M26：伪造刻度期间关 watch（防 _drain 轮询洗回）
    app.init_state = {"x": x, "y": y, "always_on_top": None}
    app._place_initial()


def assert_inside_work_area(app, wa, label=""):
    w, h = app._win_w(), int(app.canvas.winfo_reqheight())
    l, t, r, b = wa
    x, y = app._pos
    assert l <= x <= max(l, r - w), f"{label}: x={x} 越界 [{l}, {max(l, r-w)}]"
    assert t <= y <= max(t, b - h), f"{label}: y={y} 越界 [{t}, {max(t, b-h)}]"
    # 几何字符串与内部记账一致（重启后按此恢复）
    geo = app.root.geometry()
    m = re.search(r"([+-]\d+)([+-]\d+)$", geo)
    assert m and (int(m.group(1)), int(m.group(2))) == (x, y), geo


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:200]))

    # 落盘重定向（同 test_render 机制）：state/config 全进 temp
    orig = (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR)
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    orig_wa = ui_mod.work_area
    orig_was = ui_mod.work_areas

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300), state=dict(DEFAULTS))
    root.withdraw()
    try:
        # ============ B3：负坐标 / 越界 / 非数 → 启动钳回合法位置 ============
        def b3_negative():
            wa = (0, 0, 1920, 1080)
            place(app, wa, -640, -320)             # 手改 state.json 的负坐标
            assert app._pos == (0, 0), app._pos    # 钳到工作区左上角
            assert_inside_work_area(app, wa, "B3 负坐标")

        case("B3_negative_coords", b3_negative)

        def b3_far_offscreen():
            wa = (0, 0, 1920, 1080)
            place(app, wa, 99999, 99999)
            w, h = app._win_w(), int(app.canvas.winfo_reqheight())
            assert app._pos == (1920 - w, 1080 - h), app._pos
            assert_inside_work_area(app, wa, "B3 越界")

        case("B3_far_offscreen", b3_far_offscreen)

        def b3_in_range_untouched():
            wa = (0, 0, 1920, 1080)
            place(app, wa, 500, 300)
            assert app._pos == (500, 300), "合法坐标不应被移动"

        case("B3_in_range_untouched", b3_in_range_untouched)

        def b3_taskbar_offset_area():
            wa = (0, 40, 1920, 1040)               # 非零 top 的工作区（多屏副区）
            place(app, wa, -100, -100)
            assert app._pos == (0, 40), app._pos
            place(app, wa, 10, 99999)
            assert_inside_work_area(app, wa, "B3 非零原点")

        case("B3_nonzero_origin", b3_taskbar_offset_area)

        def b3_tiny_workarea():
            wa = (0, 0, 200, 150)                  # 工作区比窗口还小 → 钳到右下极限，不崩
            place(app, wa, 5000, 5000)
            w, h = app._win_w(), int(app.canvas.winfo_reqheight())
            assert app._pos == (max(0, 200 - w), max(0, 150 - h)), app._pos
            assert_inside_work_area(app, wa, "B3 超小工作区")

        case("B3_tiny_workarea", b3_tiny_workarea)

        def b3_nonnumeric_state():
            wa = (0, 0, 1920, 1080)
            place(app, wa, "abc", None)            # 脏 state → 走默认摆位，不抛
            x, y = app._pos
            assert_inside_work_area(app, wa, "B3 脏值默认位")
            assert (x, y) == (1920 - app._win_w() - 24, 24), (x, y)

        case("B3_nonnumeric_default_place", b3_nonnumeric_state)

        # ============ B3+：state.json 往返（手改越界 → 重启钳回） ============
        def b3_state_roundtrip():
            save_state(x=99999, y=-50)             # 模拟"手改 state.json"（temp 内）
            st = load_state()
            assert st["x"] == 99999 and st["y"] == -50
            wa = (0, 0, 1920, 1080)
            place(app, wa, st["x"], st["y"])        # 重启读 state → 钳制
            assert_inside_work_area(app, wa, "B3 state往返")

        case("B3_state_roundtrip", b3_state_roundtrip)

        # ============ B1：副屏(2560×1440 @150%)拖拽 → 主屏(1920×1080 @100%)重启 ============
        def b1_cross_screen_restart():
            wide = (0, 0, 2560, 1440)
            place(app, wide, 2560 - app._win_w() - 10, 1440 - 30, scale=1.5)
            assert_inside_work_area(app, wide, "B1 副屏落位")
            saved_x, saved_y = app._pos            # 拖拽后写入 state 的坐标
            main_screen = (0, 0, 1920, 1080)
            place(app, main_screen, saved_x, saved_y, scale=1.0)   # 重启回主屏
            assert_inside_work_area(app, main_screen, "B1 主屏恢复")
            w, h = app._win_w(), int(app.canvas.winfo_reqheight())
            assert saved_x > 1920 - w, "测试前提：原坐标确实在主屏外"
            assert app._pos[0] == 1920 - w, app._pos

        case("B1_cross_screen_clamp", b1_cross_screen_restart)

        def b1_dpi_awareness_active():
            # 每启动 SetProcessDpiAwareness 生效（本函数已在 run() 前被调用）
            val = ctypes.c_int(-1)
            try:
                hr = ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(val))
            except (AttributeError, OSError):
                print("   （GetProcessDpiAwareness 不可用，跳过）")
                return
            assert hr == 0 and val.value >= 1, f"DPI awareness={val.value}"

        case("B1_dpi_awareness_set", b1_dpi_awareness_active)

        print("· B2（拔副屏后启动钳回主屏）→ 未验（无双屏），按清单以 B3 伪造坐标钳制替代")
    finally:
        ui_mod.work_area = orig_wa
        ui_mod.work_areas = orig_was
        try:
            app.quit()
        except Exception:                           # noqa: BLE001
            pass
        (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         config_mod.CONFIG_PATH, config_mod.LOCAL_DIR) = orig

    bad = [c for c in checks if not c[1]]
    print()
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"  SKIP B2_dual_monitor        未验（无双屏实机）")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过（B2 未验）")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m5b_") as d:
        raise SystemExit(run(Path(d)))
