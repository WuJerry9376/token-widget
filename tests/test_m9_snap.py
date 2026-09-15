"""M9 屏幕边缘自吸附自测：snap_target 纯判定 + 拖拽释放真路径（动画/接管/落盘）。

运行：`python tests\\test_m9_snap.py`。安全红线同前：零真实网络（Scheduler 不 start）、
config/state 重定向 temp（真实 local\\state.json 不写）、伪造 work_areas 覆盖多屏，
仅「真实冒烟」一案用真实显示器几何。app 驱动全部走真实 _drag_start/_move/_end 方法。
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config as config_mod                      # noqa: E402
from src import state as state_mod                        # noqa: E402
from src import ui as ui_mod                              # noqa: E402
from src.scheduler import Scheduler                       # noqa: E402
from src.state import DEFAULTS, load_state                # noqa: E402
from src.ui import SNAP_PX, NoteApp, snap_target          # noqa: E402
import main as main_mod                                   # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}

WA = (0, 0, 1920, 1080)           # 伪造主屏工作区（物理 px，下同）
M1 = (0, 0, 1920, 1080)
M2 = (1920, 0, 3840, 1080)        # 伪造副屏（右拼）
SIZE = (330, 200)
THR = 28.0


def ev(x_root, y_root, x=40.0, y=40.0):
    """合成事件（同 test_m7 注入手法：直调真实 handler，字段给足 x/x_root）。"""
    return types.SimpleNamespace(x_root=x_root, y_root=y_root, x=x, y=y)


def drag_release(app, nx, ny):
    """真实拖拽路径：按下(现位+40) → 位移到左上角 (nx,ny) → 松开。

    偏移自洽：_drag_off 由按下事件与 winfo 原点算出，press 按 ox+40 取值
    恒得 off=(40,40)，故落点 = (nx, ny) 与 winfo 实际钳位无关。"""
    app.root.update_idletasks()
    ox, oy = app.root.winfo_x(), app.root.winfo_y()
    app._drag_start(ev(ox + 40, oy + 40))
    app._drag_move(ev(nx + 40, ny + 40))
    app._drag_end(ev(nx + 40, ny + 40))


def settle(app, timeout=1.5):
    """泵事件让吸附动画走完。"""
    t0 = time.time()
    while app._snap_anim is not None and time.time() - t0 < timeout:
        app.root.update()
        time.sleep(0.015)
    app.root.update()


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:200]))

    orig = (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            config_mod.CONFIG_PATH, config_mod.LOCAL_DIR, ui_mod.work_areas)
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state=dict(DEFAULTS))

    try:
        # ============ ① 右吸：阈值内贴右边 / 阈值外不吸（纯函数） ============
        def right_in_out():
            w, h = SIZE
            # 右边距 20 ≤ 28 → x 贴齐 1920-330=1590，y 不动
            assert snap_target((1570, 400), SIZE, [WA], THR) == (1590, 400)
            # 恰在阈值 28 → 吸（判定为 ≤）
            assert snap_target((1562, 400), SIZE, [WA], THR) == (1590, 400)
            # 阈值外 40 → 不吸
            assert snap_target((1550, 400), SIZE, [WA], THR) is None
            # 屏幕中央 → 四边都不达标，不动
            assert snap_target((795, 440), SIZE, [WA], THR) is None
            # 已贴齐（终值==原位）→ None，不白启动画
            assert snap_target((1590, 400), SIZE, [WA], THR) is None

        case("snap_right_threshold_pure", right_in_out)

        # ============ ② 角吸附：横纵独立判定，可同吸成贴角 ============
        def corner():
            # 右距 15、下距 20 → 双轴同吸 = 右下角贴齐 (1590, 880)
            assert snap_target((1575, 860), SIZE, [WA], THR) == (1590, 880)
            # 只右达标（下距 120）→ 仅横轴吸
            assert snap_target((1575, 760), SIZE, [WA], THR) == (1590, 760)

        case("snap_corner_pure", corner)

        # ============ ③ 左/顶同理 + 越过屏边（负边距）软着陆 + 非零原点 ============
        def left_top():
            assert snap_target((10, 400), SIZE, [WA], THR) == (0, 400)     # 左吸
            assert snap_target((500, 12), SIZE, [WA], THR) == (500, 0)     # 顶吸工作区顶
            assert snap_target((-50, 400), SIZE, [WA], THR) == (0, 400)    # 越过左边 → 拉回贴齐
            wa = (0, 40, 1920, 1040)              # 非零原点（顶缘=任务栏下工作区顶）
            assert snap_target((500, 45), SIZE, [wa], THR) == (500, 40)
            assert snap_target((500, 850), SIZE, [wa], THR) == (500, 840)  # 底吸=1040-200

        case("snap_left_top_pure", left_top)

        # ============ ④ 多屏：目标=窗口重叠面积最大的那块屏 ============
        def multi_monitor():
            w = SIZE[0]
            # 窗口主体在副屏、距副屏右缘 12 → 吸到副屏右界；若误用主屏会得 None/错值
            assert snap_target((3840 - w - 12, 400), SIZE, [M1, M2], THR) == (3840 - w, 400)
            # 骑缝窗：x=1580 → 主屏重叠 120×h vs 副屏 210×h？(1580..1910 全在主屏)
            #   主屏满重叠、副屏 0 → 必须吸主屏右界 1590（若选错副屏 dl=-340 会吸到 1920）
            assert snap_target((1580, 400), SIZE, [M1, M2], THR) == (1590, 400)
            # 完全出屏（坐标悬空）：重叠面积全 0 打平 → 取列首屏（真实枚举列首=主屏）
            # 软着陆拉回其右缘贴齐；副屏真断开时列表只剩主屏，同样落主屏
            assert snap_target((5000, 400), SIZE, [M1, M2], THR) == (1920 - w, 400)
            # 极端：工作区比窗口窄，双边都达标 → 取 |边距| 更小者（左 20 < 右 200）
            assert snap_target((20, 400), (330, 100), [(0, 0, 150, 900)], THR) == (0, 400)
            # 副屏列表为空/单屏 = 旧行为（主屏四边照常）
            assert snap_target((10, 400), SIZE, [WA], THR) == (0, 400)

        case("snap_multi_monitor_pure", multi_monitor)

        # ============ ⑤+⑥ 拖拽释放真路径：动画分帧滑到贴边，终值即刻落盘 ============
        root.deiconify()
        root.update()

        def drag_snap_end_to_end():
            ui_mod.work_areas = lambda: [WA]
            w, h = app._win_size()
            thr = app._p(SNAP_PX)
            tx = WA[2] - w                          # 贴右 = 1920-330·S 取整
            ty = 400
            drag_release(app, tx - int(thr / 2), ty)     # 阈值内松手
            target = (tx, ty)
            assert app._snap_target == target, (app._snap_target, target)
            # ⑥ 落盘终值：释放瞬间 state.json 已是吸附位（不等动画）
            st = load_state()
            assert (st["x"], st["y"]) == target, (st, target)
            # ⑤ 动画在途：第 1 帧在起点与终点之间（非直落）
            first = app._pos
            assert app._snap_anim is not None, "释放后动画应在途"
            assert first != target and first[0] > tx - int(thr / 2), first
            settle(app)
            assert app._pos == target, (app._pos, target)
            assert app._snap_anim is None and app._snap_job is None
            assert app.root.winfo_x() + app.root.winfo_width() >= min(
                tx + w, WA[2]), "窗口实体应贴到工作区右界附近"

        case("drag_snap_anim_and_persist", drag_snap_end_to_end)

        # ============ ⑤b 动画期间新拖拽 → 立即终止接管 ============
        def anim_takeover():
            ui_mod.work_areas = lambda: [WA]
            w, _h = app._win_size()
            thr = app._p(SNAP_PX)
            drag_release(app, WA[2] - w - int(thr / 2), 500)
            assert app._snap_job is not None, "应有待走的帧定时器"
            mid = app._pos
            # 新按下：动画必须即刻停（after 取消 + 状态清零 + 旧终值不作废跟随）
            app._drag_start(ev(mid[0] + 40, mid[1] + 40))
            assert app._snap_job is None and app._snap_anim is None, "接管未终止动画"
            assert app._snap_target is None, "接管后旧终值应清空"
            for _ in range(15):                     # 泵 200ms：位置不得再被旧动画推动
                root.update()
                time.sleep(0.015)
            assert app._pos == mid, (app._pos, mid)
            app._drag_off = None                    # 收尾：拖离边缘释放，不吸，状态干净

            drag_release(app, 600, 500)
            assert app._snap_target is None and load_state()["x"] == 600

        case("snap_anim_takeover_on_new_drag", anim_takeover)

        # ============ ⑦ 点击释放（位移 ≤4px）不触发吸附 ============
        def click_no_snap():
            ui_mod.work_areas = lambda: [WA]
            w, h = app._win_size()
            thr = app._p(SNAP_PX)
            pos = (WA[2] - w - int(thr / 2), 400)    # 停在阈值内（若触发必吸）
            app._pos = pos
            root.geometry(f"+{pos[0]}+{pos[1]}")
            root.update()
            ox, oy = root.winfo_x(), root.winfo_y()
            p = ev(ox + 40, oy + 40, x=w / 2, y=h - 8)   # 原地松开：中心偏下，避开刷新热区
            fetching_before = app.fetching
            app._drag_start(p)
            app._drag_end(ev(ox + 40, oy + 40, x=w / 2, y=h - 8))
            assert app._snap_target is None and app._snap_anim is None, "点击不得吸附"
            assert app._pos == pos, app._pos
            assert load_state()["x"] == pos[0], "state 应记释放原位"
            assert app.fetching is fetching_before, "点击位不应误触刷新"

        case("click_release_no_snap", click_no_snap)

        # ============ ⑧ 真实显示器冒烟：work_areas 真数据 + 贴右缘证据 ============
        def real_monitor_smoke():
            ui_mod.work_areas = orig[4]              # 还原真实 EnumDisplayMonitors
            areas = ui_mod.work_areas()
            assert areas and all(a[2] > a[0] and a[3] > a[1] for a in areas), areas
            w, h = app._win_size()
            thr = app._p(SNAP_PX)
            # 选窗口当前重叠最大的屏（=吸附会选的同一块）作期望值
            exp = snap_target((areas[0][2] - w - int(thr / 2), areas[0][1] + 200),
                              (w, h), areas, thr)
            drag_release(app, areas[0][2] - w - int(thr / 2), areas[0][1] + 200)
            assert exp is not None, exp
            settle(app)
            assert app._pos == exp, (app._pos, exp)
            st = load_state()
            assert (st["x"], st["y"]) == exp, st     # 真实路径落盘同为终值
            # 贴齐证据：内部记账的窗右缘 == 工作区右界（0 间距）
            assert exp[0] + w == areas[0][2] or exp[0] + app._win_w() == areas[0][2]

        case("real_monitor_snap_smoke", real_monitor_smoke)

    finally:
        root.withdraw()
        ui_mod.work_areas = orig[4]
        try:
            app.quit()
        except Exception:                            # noqa: BLE001
            pass
        (state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         config_mod.CONFIG_PATH, config_mod.LOCAL_DIR, ui_mod.work_areas) = orig

    bad = [c for c in checks if not c[1]]
    print()
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m9_test_") as d:
        raise SystemExit(run(Path(d)))
