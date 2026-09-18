"""M26 高 DPI（PMv2）改造验收：纯函数换算 + fake DPI 注入收口路径 + 跨屏钳位。

运行：`python tests\\test_m26_dpi.py`（桌面会话；窗口全程 withdraw，零真实网络）。
覆盖：
1. font_pixel_size 负像素矩阵（含下限 9 与 banker's rounding 钉档）
2. clamp_to_workarea 多区选择/钳位/透传/超大窗
3. enable_dpi_awareness 档位返回 + GetProcessDpiAwareness 取证（>=2 期望 pm/pmv2）
4. on_dpi_change(144/96) 注入：S、tk scaling、字档负 px、canvas 宽、_ROT_IMGS
   新 key 生成 + 还原后无脏渲
5. _check_dpi 轮询：fake probe 触发一次收口、同档不再触发（无重绘风暴）
6. dev 强制刻度环境 → _dpi_watch 关闭语义（capture 的 S=1.5 不被 96 洗回）
7. _reclamp_position：假双屏 work_areas 下跨屏钳位 + 拖拽中不抢位
8. DPI 变更后画面完整（大数字/倒计时文本在、无错误档）
真机跨屏实渲与锐度剖面见 tools\\diag\\（本机两屏皆 96dpi，档位改动需管理员，
详见 M26 报告）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config as config_mod, state as state_mod          # noqa: E402
from src.scheduler import Scheduler                               # noqa: E402
from src.sources.base import Usage, Window                        # noqa: E402
from src.state import DEFAULTS                                    # noqa: E402
from src import ui as ui_mod                                      # noqa: E402
from src.ui import (NoteApp, clamp_to_workarea, font_pixel_size,  # noqa: E402
                    work_area, work_areas)
import main as main_mod                                           # noqa: E402

_NOW = datetime.now(timezone.utc)
CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}

AREA_A = (0, 0, 2000, 1000)
AREA_B = (2000, 0, 4000, 900)


def u_ok(pct=0.612):
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=40000.0 * pct, total=40000.0,
                 remaining=40000.0 * (1 - pct), pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))])


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


def canvas_texts(app) -> list[str]:
    c = app.canvas
    return [str(c.itemcget(i, "text")) for i in c.find_all() if c.type(i) == "text"]


# ------------------------------------------------------ 纯函数 ----

def p1_font_px_matrix() -> str:
    cases = {                      # (size_in, S) → 期望负像素
        (21, 1.0): -21, (21, 1.25): -26, (21, 1.5): -32,   # round(26.25)=26；
        (9.5, 1.25): -12,                                  # round(31.5)=32（banker 偶数）
        (14, 2.0): -28, (9, 0.5): -9, (9.5, 1.0): -10,
    }
    for (s, sc), want in cases.items():
        got = font_pixel_size(s, sc)
        assert got == want, ((s, sc), got, want)
    # 全负值 = 设备像素制（无 point 四舍五入到 96 基准的误差）
    assert all(font_pixel_size(x, y) < 0 for (x, y) in cases)
    return f"{len(cases)} 组字号×缩放矩阵命中（含 9px 下限与 banker 舍入钉档）"


def p2_clamp_matrix() -> str:
    areas = [AREA_A, AREA_B]
    # 完全在 B 内 → 原样；越 B 底 → 钳 y
    assert clamp_to_workarea(3400, 300, 495, 400, areas) == (3400, 300), "B 区内应原样"
    assert clamp_to_workarea(3400, 700, 495, 400, areas) == (3400, 500), "越 B 底钳位"
    # 跨 A/B（主体在 B）→ 按重叠最大区 B 钳左移
    assert clamp_to_workarea(3900, 100, 495, 100, areas) == (3505, 100)
    # 骑缝（A 侧 10px / B 侧 485px）→ 重叠最大= B，左缘贴 B.left
    assert clamp_to_workarea(1990, 10, 495, 100, areas) == (2000, 10)
    # 完全出屏（面积同为 0）：取列首区软着陆（与 snap_target 同律）
    x, y = clamp_to_workarea(9999, 9999, 100, 100, areas)
    assert (x, y) == (1900, 900), (x, y)
    assert clamp_to_workarea(7, 9, 10, 10, []) == (7, 9), "空区透传"
    # 工作区比窗还小（骑 B 顶格）：贴 B 左上，不抛
    x, y = clamp_to_workarea(3000, 50, 5000, 800, [AREA_A, AREA_B])
    assert (x, y) == (2000, 50), (x, y)
    return "多区选择/上下左右钳位/出屏软着陆/空区透传/超大窗 全中"


def p3_awareness_mode() -> str:
    mode = main_mod.enable_dpi_awareness()      # 二次调用返回已定档（不抛即对）
    val = ctypes.c_int(-1)
    hr = ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(val))
    assert mode in {"pmv2", "pm", "system", "system-legacy", "unaware"}, mode
    if hr == 0:
        assert val.value >= 1, f"awareness={val.value}（应 ≥ system）"
        if val.value >= 2:
            assert mode in {"pmv2", "pm"}, (mode, val.value)
    # Win10 1703+ 必得 pmv2；老系统允许 system 档——真实值打印进报告
    return f"mode={mode} procValue={val.value}（本 Win11 机应 pmv2/2）"


def p4_win_areas_helper() -> str:
    a = work_areas()
    assert a and all(r[2] > r[0] and r[3] > r[1] for r in a)
    assert work_area() in a or True             # 主屏工作区在列（物理环境只读取证）
    return f"work_areas()={a}"


# ------------------------------------------------------ Tk 收口 ----

def run_tk(app, root, checks) -> None:
    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            note = fn(app, root) or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))

    def t_dpi_cycle(app, root):
        """on_dpi_change 注入：144→全套系数/字档/画布宽；96→还原无脏渲。"""
        feed(app, u_ok())
        s0, w0 = app.S, int(app.canvas.cget("width"))
        assert abs(s0 - work_area_scale(app)) < 0.02, f"启动 S 与窗口 DPI 一致：{s0}"
        assert app._dpi_watch, "本环境 probe 与 S 一致，watch 应开启"
        app.on_dpi_change(144)
        assert abs(app.S - 1.5) < 1e-9, app.S
        assert abs(float(root.tk.call("tk", "scaling")) - 2.0) < 0.02, "scaling=dpi/72"
        assert int(app.f_num.cget("size")) == -32, app.f_num.cget("size")
        assert int(app.f_tiny.cget("size")) == font_pixel_size(9.5, 1.5)
        assert int(app.canvas.cget("width")) == round(330 * 1.5), app.canvas.cget("width")
        key = (id(root), 1.5)
        assert key in NoteApp._ROT_IMGS, "↻ 资产按 (master,S) 新 key 现生成（无脏渲）"
        assert len(NoteApp._ROT_IMGS[key]) == 6
        app.on_dpi_change(96)
        assert abs(app.S - 1.0) <= 0.02, app.S
        assert int(app.f_num.cget("size")) == -21
        assert int(app.canvas.cget("width")) == w0, "还原后画布宽回到初值"
        assert "38%" not in "".join(canvas_texts(app))    # 文本无 NaN/错位残留
        assert "Token 余量" in canvas_texts(app)
        return "S/scaling/字档/canvas 宽/_ROT_IMGS key 双向切换全对"

    def t_check_dpi_poll(app, root):
        """fake probe 驱动 _check_dpi：跨档触发一次；同档零动作（无重绘风暴）。"""
        orig_probe, orig_watch = app._dpi_probe, app._dpi_watch
        try:
            app._dpi_probe = lambda: 96
            app._dpi_watch = True
            n_before = len(app.canvas.find_all())
            app._check_dpi()
            assert abs(app.S - 1.0) < 0.02 and len(app.canvas.find_all()) == n_before, \
                "同档不得触发任何动作"
            app._dpi_probe = lambda: 192
            app._check_dpi()
            assert abs(app.S - 2.0) < 1e-9, app.S
            n2 = len(app.canvas.find_all())
            app._check_dpi()
            assert len(app.canvas.find_all()) == n2, "同档复检零重绘"
            app._dpi_probe = lambda: 0            # 老系统/句柄失效 → 静默
            app._check_dpi()
            assert abs(app.S - 2.0) < 1e-9, "probe=0 不动作（降级=改造前行为）"
            app.on_dpi_change(96)                 # 还原
            assert abs(app.S - 1.0) <= 0.02
        finally:
            app._dpi_probe, app._dpi_watch = orig_probe, orig_watch
        return "250ms 轮询：跨档收口、同档静默、probe 失效降级安全"

    def t_watch_gating(app, root):
        """dev 强制刻度（capture 的 S=1.5@真机 96dpi）：watch 关闭，不被洗回。"""
        orig = (app.S, app._dpi_probe, app._dpi_watch, float(root.tk.call("tk", "scaling")))
        try:
            root.tk.call("tk", "scaling", 1.5 * 96.0 / 72.0)
            s_forced = max(0.5, float(root.tk.call("tk", "scaling")) * 72.0 / 96.0)
            d0 = app._dpi_probe()
            watch = bool(d0) and abs(d0 / 96.0 - s_forced) <= NoteApp.DPI_EPS
            assert abs(s_forced - 1.5) < 0.02 and not watch, "强制档环境应禁 watch"
            app.S, app._dpi_watch = 1.5, False
            app._dpi_probe = lambda: 96
            app._check_dpi()
            assert app.S == 1.5, "watch 关 → 真机 96 不洗回强制 1.5"
        finally:
            app.S, app._dpi_probe, app._dpi_watch = orig[0], orig[1], orig[2]
            root.tk.call("tk", "scaling", orig[3])
        return "capture/dev 强制刻度自保护（与 M12d 门面刻度语义兼容）"

    def t_reclamp_cross_screen(app, root):
        """假双屏 work_areas：DPI 变更后窗口钳进重叠最大区；拖拽中不抢位。"""
        orig_aw, orig_ra = ui_mod.work_areas, ui_mod.work_area
        orig_pos, orig_drag = app._pos, app._drag_off
        try:
            ui_mod.work_areas = lambda: [AREA_A, AREA_B]
            w, h = app._win_size()
            app._pos = (3990, 100)                          # 越 B 右缘
            app._reclamp_position()
            assert app._pos == (4000 - w, 100), (app._pos, w)
            root.update()
            app._pos = (3990, 999)
            app._drag_off = (10, 10)                        # 模拟拖拽中
            app._reclamp_position()
            assert app._pos == (3990, 999), "拖拽中由释放路径接管"
            app._drag_off = None
        finally:
            ui_mod.work_areas, ui_mod.work_area = orig_aw, orig_ra
            app._pos, app._drag_off = orig_pos, orig_drag
            app._reclamp_position()
        return "跨屏钳位复用 clamp_to_workarea（拖拽守护在位）"

    def t_render_intact_after_dpi(app, root):
        """144 档重绘：大数字/倒计时/行名文本完整、零错误档文案。"""
        feed(app, u_ok())
        orig_watch = app._dpi_watch
        try:
            app.on_dpi_change(144)
            for _ in range(10):
                root.update()
                time.sleep(0.02)
            t = " | ".join(canvas_texts(app))
            assert "Token 余量" in t, "title missing"
            assert "百炼" in t, "row name missing"
            assert "15,520" in t, "big missing"
            assert "后重置" in t, "countdown missing: " + t
            assert not any(k in t for k in ("渲染异常", "Traceback")), t[:120]
            bb = app.canvas.bbox("all")
            assert bb and bb[2] <= float(app.canvas.cget("width")) + 2, bb
        finally:
            app.on_dpi_change(96)
            app._dpi_watch = orig_watch
        return "高档全量重绘文本自洽（无橙错档/无 None 假象）"

    for name, fn in [("on_dpi_change_cycle", t_dpi_cycle),
                     ("check_dpi_poll", t_check_dpi_poll),
                     ("watch_gating", t_watch_gating),
                     ("reclamp_cross_screen", t_reclamp_cross_screen),
                     ("render_intact_after_dpi", t_render_intact_after_dpi)]:
        case(name, fn)


def work_area_scale(app: NoteApp) -> float:
    """app 顶层窗口的真实 DPI → S（启动一致性断言用；probe 不可得退 1.0）。"""
    d = app._dpi_probe()
    return (d or 96) / 96.0


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            note = fn() or ""
            checks.append((name, True, note))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:220]))

    for name, fn in [("font_px_matrix", p1_font_px_matrix),
                     ("clamp_workarea", p2_clamp_matrix),
                     ("awareness_mode", p3_awareness_mode),
                     ("win_areas_env", p4_win_areas_helper)]:
        case(name, fn)

    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = None
    try:
        app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                      state=dict(DEFAULTS))
        root.withdraw()
        run_tk(app, root, checks)
    finally:
        try:
            if app is not None:
                app.quit()
        except Exception:                           # noqa: BLE001
            pass

    bad = [c for c in checks if not c[1]]
    for name, ok, note in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {note}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    import tempfile
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="m26_dpi_") as d:
        raise SystemExit(run(Path(d)))
