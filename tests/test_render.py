"""M2 渲染自测：注入假 Usage / 假 error_code，验证各状态渲染不崩 + 拖拽/位置记忆。

运行：`python tests\\test_render.py`（需要可用桌面会话；窗口全程 withdraw 不闪现）。
不触碰真实网络（Scheduler 不 start，直接投喂事件）。
"""
from __future__ import annotations

import sys
import time
import types
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scheduler import Scheduler                      # noqa: E402
from src.sources.base import Usage, Window               # noqa: E402
from src.state import DEFAULTS                           # noqa: E402
from src import state as state_mod                       # noqa: E402
from src.ui import NoteApp, fmt_countdown, fmt_value     # noqa: E402
import main as main_mod                                  # noqa: E402

CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian", "openai"]}

_NOW = datetime.now(timezone.utc)


def u_ok(pct=0.612, with5h=False, addon=1509.0, remaining=17022.0, total=60000.0):
    wins = [Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))]
    if with5h:
        wins.append(Window("5h", 0.42, _NOW + timedelta(hours=1, minutes=20)))
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=total * pct, total=total, remaining=remaining,
                 pct_used=pct, resets_at=wins[0].resets_at, windows=wins,
                 addon_remaining=addon)


def u_err(code, msg="fake"):
    return Usage(provider="bailian", ok=False, error_code=code, error_msg=msg)


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


def run() -> int:
    # state.json 重定向到临时文件，不污染真实位置记忆
    tmp_state = Path(__file__).resolve().parent / "_tmp_state.json"
    orig_path, orig_dir = state_mod.STATE_PATH, state_mod.LOCAL_DIR
    state_mod.STATE_PATH = tmp_state
    state_mod.LOCAL_DIR = tmp_state.parent
    try:
        return _run(tmp_state)
    finally:
        state_mod.STATE_PATH, state_mod.LOCAL_DIR = orig_path, orig_dir


def _run(tmp_state: Path) -> int:
    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    sched = Scheduler([], poll_seconds=300)          # 不 start，纯手动投喂
    app = NoteApp(root, CFG, sched, state=dict(DEFAULTS))
    root.withdraw()                                   # 测试期间保持不可见
    checks = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:160]))

    # 1) 正常数据 / 2) 5h 副行 / 3) 黄 / 4) 红 / 5) 无绝对值(Go 风格)
    case("normal", lambda: feed(app, u_ok()))
    case("5h", lambda: feed(app, u_ok(with5h=True)))
    case("yellow", lambda: feed(app, u_ok(pct=0.88, remaining=5000, total=40000)))
    case("red", lambda: feed(app, u_ok(pct=0.97, remaining=900, total=40000)))
    case("percent_only", lambda: feed(app, Usage(
        provider="opencode_go", ok=True, unit="percent", pct_used=0.4,
        windows=[Window("rolling", 0.4, _NOW + timedelta(hours=3))])))

    # 6) LOGIN_EXPIRED：有最后成功值 → 橙警示 + 灰显旧数据
    case("login_expired_stale", lambda: feed(app, u_err("LOGIN_EXPIRED")))
    # 7) 其他错误：保留旧值灰显
    case("network_stale", lambda: feed(app, u_err("NETWORK", "timed out")))
    # 8) 从未成功过的错误行（不渲染空值假象）
    case("err_no_history", lambda: (setattr(app, "last_good", {}),
                                     feed(app, u_err("WORKSPACE_NOTAUTHORISED"))))
    case("not_configured", lambda: feed(app, Usage(
        provider="openai", ok=False, unit="usd", error_code="not_configured",
        error_msg="占位")))
    # 9) 空供应商列表
    case("empty", lambda: feed(app))

    # 10) 拖拽：合成事件移动窗口并写 state.json（需要窗口可见才能收到事件）
    #     M9 注：释放点若在工作区边缘 28px 内会自吸附（默认位右缘 24px + 拖 50 → 吸右），
    #     判"位置已写 state"改为等吸附动画落定后比对最终位（语义=持久化到实际落点）。
    def drag():
        root.deiconify()
        root.update()
        x0, y0 = root.winfo_x(), root.winfo_y()
        c = app.canvas
        c.event_generate("<ButtonPress-1>", x=40, y=40)
        root.update()
        c.event_generate("<B1-Motion>", x=90, y=80)
        root.update()
        c.event_generate("<ButtonRelease-1>", x=90, y=80)
        t0 = time.time()
        while getattr(app, "_snap_anim", None) is not None and time.time() - t0 < 2.0:
            root.update()
            time.sleep(0.015)
        root.update()
        x1, y1 = root.winfo_x(), root.winfo_y()
        st = state_mod.load_state()
        assert (x1, y1) != (x0, y0), "窗口未随拖拽移动"
        assert st["x"] == x1 and st["y"] == y1, "位置未写入 state.json"
        root.withdraw()

    case("drag_and_persist", drag)

    # 11) 菜单动作：条目齐全（M3 最终项）+ 置顶开关 + 立即刷新
    #     不做真实 post()（Windows 菜单是模态 grab，会卡住无人值守的测试），
    #     改为校验菜单条目与回调存在性 + 直接调用命令。
    def menu():
        assert app.menu.index("end") == 4, "菜单条目数不对"
        labels = [app.menu.entrycget(i, "label") for i in range(5)
                  if app.menu.type(i) != "separator"]
        assert labels == ["立即刷新", "总在最前", "设置…", "退出（保存位置）"], labels
        app.var_top.set(not app.topmost)
        app._toggle_top()
        assert bool(root.attributes("-topmost")) == app.topmost
        app.refresh()
        assert app.fetching

    case("menu_final_items", menu)

    # 11b) M2 审查①：数值自洽 —— 大数字 = Σ分项（floor 后）；C 行不再重复更新时间
    def consistency():
        from src.ui import breakdown_display
        uu = u_ok(remaining=15344.7 + 1509.4, addon=1509.4, total=60000.0)
        feed(app, uu)
        big, left = breakdown_display(uu)
        assert left is not None
        assert big == "16,853", big          # floor(15344.7)=15344 + floor(1509.4)=1509
        assert "15,344" in left and "1,509" in left and "60,000" in left, left
        texts = [app.canvas.itemcget(i, "text")
                 for i in app.canvas.find_all() if app.canvas.type(i) == "text"]
        assert big in texts, "画布大数字与 breakdown 不一致"
        assert any("＋ 加油包" in t for t in texts)
        assert not any(str(t).startswith("更新 ") for t in texts), \
            "C 行更新时间应已删除"
        # M3c 数据口径注记（含加油包 → B 行小字"按周期计"，空间不足自动省略）
        assert any("（按周期计）" in str(t) for t in texts), \
            "进度条旁应有口径小字（本 DPI 下应放得下）"

    case("breakdown_consistency", consistency)

    # 11c) 凭据过期：行内出现可点击「更新登录凭据…」并触发面板
    #      （M7-b 调整：clicks[0] 现为头部刷新图标热区，凭据按钮改为按 cmd 过滤取）
    def cred_button():
        feed(app, u_ok())                      # 先建立 last_good
        called = {"n": 0}
        setattr(app, "open_credentials", lambda: called.__setitem__("n", called["n"] + 1))
        feed(app, u_err("LOGIN_EXPIRED"))      # 渲染时绑定的即是打桩
        assert len([z for z in app.clicks if z[4] != app.refresh]) == 1, \
            "凭据异常行应注册点击区"
        labels = [app.canvas.itemcget(i, "text")
                  for i in app.canvas.find_all() if app.canvas.type(i) == "text"]
        assert any("更新登录凭据…" in str(t) for t in labels), labels
        z = next(z for z in app.clicks if z[4] != app.refresh)
        ev = types.SimpleNamespace(x_root=0, y_root=0,
                                   x=(z[0] + z[2]) / 2, y=(z[1] + z[3]) / 2)
        app._press_xy = (0, 0)                 # 未移动 → 判定为点击
        getattr(app, "_drag_end")(ev)
        assert called["n"] == 1, "点击未触发凭据面板"

    case("credential_button_click", cred_button)

    # 12) tooltip 文本生成
    def tooltip():
        txt = app._tip_text({"u": u_ok(with5h=True), "err": None, "stale": False})
        assert "百炼" in txt and "5h" in txt and "," in txt, txt
        assert "百分比按 7 天周期计" in txt, txt          # M3c 口径裁决唯一文案增项
        txt2 = app._tip_text({"u": u_ok(), "err": u_err("NETWORK"), "stale": True})
        assert "NETWORK" in txt2 and "旧" not in txt2.splitlines()[0]

    case("tooltip_text", tooltip)

    # 13) 格式化断言
    def fmts():
        assert fmt_value(17022) == "17,022"
        assert fmt_value(12.5, "usd") == "$12.50"
        assert fmt_value(None) == "—"
        s = fmt_countdown(datetime.now(timezone.utc) + timedelta(hours=8, minutes=2))
        assert s == "8h02m 后重置", s
        s2 = fmt_countdown(datetime.now(timezone.utc) + timedelta(days=1, hours=5))
        assert s2.startswith("1d05h"), s2
        assert fmt_countdown(datetime.now(timezone.utc) - timedelta(minutes=5)) == "即将重置"
        assert fmt_countdown(None) == "重置时间未知"

    case("formatters", fmts)

    app.quit()
    tmp_state.unlink(missing_ok=True)

    bad = [c for c in checks if not c[1]]
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过；DPI scale={app.S}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(run())
