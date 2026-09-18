"""M7 自测：加油包细条（两态+零占位+推导）/ 刷新图标（点击、旋转起停）/ M6 面板抽查。

运行：`python tests\\test_m7.py`。安全红线同前：config/state 重定向 temp；
auth 探测函数打桩（不读真实 opencode auth.json、不触碰真实 local\\ 文件）；
Scheduler 不 start，事件手动投喂，全程无网络。
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

from src import config as config_mod, state as state_mod      # noqa: E402
from src import auth, settings_panel                          # noqa: E402
from src.scheduler import Scheduler                           # noqa: E402
from src.sources.base import Usage, Window                     # noqa: E402
from src.state import DEFAULTS                                # noqa: E402
from src.ui import (ROW_ADDON, NoteApp, ORANGE, RED, SOFT_TXT, addon_bar_state,   # noqa: E402
                    breakdown_display, plan_end_display, plan_end_split,
                    usd_used_mode)
import main as main_mod                                        # noqa: E402

_NOW = datetime.now(timezone.utc)
CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian"]}


def u_with_addon():
    """与质疑示例同口径：weekly=40,000、7d 已用 61.2%、加油包剩 1,508/总 20,000。"""
    weekly, pct, ar = 40000.0, 0.612, 1508.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8))],
                 addon_remaining=ar)


def u_no_addon():
    u = u_with_addon()
    u.addon_remaining = None
    u.total = 40000.0
    u.remaining = 40000 * (1 - 0.612)
    return u


def feed(app, *usages):
    app.sched.events.put(("update", list(usages),
                          {"next_delay": 300, "ts": time.time(), "low": False}))
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)


def texts(app) -> list[str]:
    c = app.canvas
    return [str(c.itemcget(i, "text")) for i in c.find_all() if c.type(i) == "text"]


def run(tmp: Path) -> int:
    checks: list[tuple[str, bool, str]] = []

    def case(name, fn):
        print(f"· {name} …", flush=True)
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            checks.append((name, False, repr(e)[:200]))

    orig_cfg, orig_state, orig_dir = (config_mod.CONFIG_PATH, state_mod.STATE_PATH,
                                      state_mod.LOCAL_DIR)
    config_mod.CONFIG_PATH = tmp / "config.json"
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, dict(CFG), Scheduler([], poll_seconds=300),
                  state=dict(DEFAULTS))
    root.withdraw()

    try:
        # ============ 1) addon_bar_state 纯函数（四态 + floor 同源） ============
        def unit_states():
            show, at, adf = addon_bar_state(u_with_addon())
            assert show and at is not None and abs(at - 20000.0) < 1.0, (show, at)
            assert adf == 1508, adf                       # floor(1508.0)=1508
            # 必修①核心：小数剩余也走 floor，绝不再是四舍五入的 1,509
            uw = u_with_addon()
            uw.addon_remaining = 1508.9
            uw.remaining += 0.9
            show, at, adf = addon_bar_state(uw)
            assert adf == 1508, f"须 floor 不是 round，得 {adf}"
            _b, left = breakdown_display(uw)
            assert "加油包 1,508" in left, (left, adf)
            show, at, adf = addon_bar_state(u_no_addon())
            assert not show and at is None
            u = u_with_addon()                            # 总量可推导→ACTIVE 罄包显示
            u.addon_remaining = 0.0
            show, at, adf = addon_bar_state(u)
            assert show and at and at > 0 and adf == 0
            u = u_with_addon()
            u.addon_remaining = 0.0
            u.pct_used = 0.0                              # 不可推导 + 剩 0 → 不显示
            u.used = 0.0
            assert not addon_bar_state(u)[0]
            u2 = u_with_addon()
            u2.pct_used = 0.0                             # 剩>0 但 pct≈0 → 显示、总量未知
            s2, a2, f2 = addon_bar_state(u2)
            assert s2 and a2 is None and f2 == 1508

        case("addon_state_unit", unit_states)

        # ============ 2) 有包两态渲染 + 零占位高度 ============
        def two_states_height():
            feed(app, u_no_addon())
            base_h = float(app.canvas.cget("height"))
            assert "加油包" not in "".join(texts(app)), "无包不得出现细条"
            feed(app, u_with_addon())
            on_h = float(app.canvas.cget("height"))
            t = "".join(texts(app))
            assert "加油包" in t, "有包须显示细条标签"
            assert "剩 1,508 / 20,000" in t, texts(app)   # M11c③ 细条方向锚「剩」
            # M25：百炼 B 行去「窗口」——「7d · 已用 x%」拼接 + 全画面零「窗口」
            assert "7d · 已用 61.2%" in t, t
            assert "窗口" not in t, f"画面出现「窗口」：{t}"
            assert abs((on_h - base_h) - ROW_ADDON * app.S) <= 2.0, (base_h, on_h)
            # 回到无包：高度精确回落（零占位，不留空行）
            feed(app, u_no_addon())
            assert float(app.canvas.cget("height")) == base_h, "须零占位回落"

        case("addon_bar_two_states", two_states_height)

        # ============ 3) 罄包（剩 0 有总量）与 tooltip 明细 ============
        def depleted_and_tooltip():
            u = u_with_addon()
            u.addon_remaining = 0.0
            feed(app, u)
            t = "".join(texts(app))
            assert "0 / 20,000" in t, texts(app)
            tip = app._tip_text({"u": u, "err": None, "stale": False})
            assert "加油包：剩 0 / 总 20,000" in tip, tip
            assert "合并" in tip

        case("addon_depleted_and_tooltip", depleted_and_tooltip)

        # ============ 4) 刷新图标：热区唯一 + 点击触发 kick 恰一次 ============
        def icon_click():
            feed(app, u_with_addon())
            zones = [z for z in app.clicks if z[4] == app.refresh]
            assert len(zones) == 1, "头部应有且仅有一个刷新图标热区"
            kicks = {"n": 0}
            orig_kick = app.sched.kick
            app.sched.kick = lambda: (kicks.__setitem__("n", kicks["n"] + 1),
                                      orig_kick())[1]
            try:
                z = zones[0]
                ev = types.SimpleNamespace(x_root=0, y_root=0,
                                           x=(z[0] + z[2]) / 2, y=(z[1] + z[3]) / 2)
                app._press_xy = (0, 0)
                app._drag_end(ev)
                assert kicks["n"] == 1, f"应恰触发一次刷新（{kicks['n']}）"
                assert app.fetching is True
                assert app._spin_job is not None, "点击后旋转定时器应运行"
            finally:
                app.sched.kick = orig_kick

        case("refresh_icon_click_once", icon_click)

        # ============ 5) 回包停转 + 图标归位 ============
        def spin_stop():
            feed(app, u_with_addon())               # 上一案已 fetching=True
            assert app.fetching is False
            assert app._spin_job is None, "回包后旋转定时器应停止"
            assert app._rot == 0, "回包后图标应归零"

        case("spin_stops_on_reply", spin_stop)

        # ============ 6) 30s 超时自停（不永转）；tick 自动轮询也起转 ============
        def spin_timeout_and_tick():
            feed(app, u_no_addon())                 # 干净起
            app.sched.events.put(("tick", None, {}))
            for _ in range(25):                     # > _drain 250ms 节律 + 余量
                app.root.update()
                time.sleep(0.02)
            assert app.fetching, "tick 应置 fetching"
            assert app._spin_job is not None, "自动轮询也应起转"
            # M8b 反向锁（用户"倒放"）：步进必须 0→300→240 递减（画布角递减=屏幕顺时针）。
            # 理由：方向只能靠坐标证据锁定，防止又漂回 CCW；先停表做确定性单步。
            app._stop_spin()
            app._rot = 0
            app._spin_deadline = time.monotonic() + 9.0
            app._spin_step()
            assert app._rot == 300, f"反向步进应 0→300，实际 {app._rot}"
            app._spin_step()
            assert app._rot == 240, f"反向步进应 300→240，实际 {app._rot}"
            app._stop_spin()
            app._rot = 0
            app._spin_deadline = time.monotonic() - 1.0     # 伪造超时
            app._spin_step()                                 # 手动走一拍：应停且不重排
            assert app._spin_job is None, "超时后定时器应自停（回包前不再转）"
            feed(app, u_no_addon())                          # 回包收尾

        case("spin_timeout_and_tick", spin_timeout_and_tick)

        # ============ 7) 图标 tooltip 固定文案 + hover 热区在纸形内 ============
        def icon_tooltip():
            feed(app, u_no_addon())
            hits = [z for z in app.hits if "tip" in z[4]]
            assert len(hits) == 1 and hits[0][4]["tip"] == "立即刷新（绕过缓存）"
            z = hits[0]
            h = float(app.canvas.cget("height"))
            assert 0 < z[1] and z[3] < h, "图标热区必须整体在窗口/纸形内（不触条带判据）"

        case("icon_tooltip_and_bounds", icon_tooltip)

        # ============ 8) M6 面板抽查：ProviderKeyPanel 控件齐备 + 视觉同源 ============
        # M11a：openai 面板随 API 侧移除，抽查样本一换二为 Codex 面板（控件语言同源）。
        def key_panels_spot():
            origs = (auth.detect_go_key, auth.has_secret)
            auth.detect_go_key = lambda: "fake-go-key-abcd1234"
            auth.has_secret = lambda name: name == "codex_access_token"
            try:
                p1 = settings_panel.ProviderKeyPanel(app, "codex")
                p1.withdraw()
                t1 = _all_text(p1)
                for want in ("access_token", "保存并验证", "取消", "实验性"):
                    assert any(want in x for x in t1), f"codex 面板缺控件：{want}"
                assert p1.ent_key.cget("show") == "*", "token 输入框必须密文回显"
                ents = _by_class(p1, tk.Entry)
                assert all(e.cget("bg") == settings_panel.ENTRY_BG for e in ents), \
                    "输入框底色应统一 ENTRY_BG（与 CredentialPanel 同源）"
                btns = {str(b.cget("text")) for b in _by_class(p1, tk.Button)}
                assert "取消" in btns
                # 取消键描边与 CredentialPanel 同款
                for b in _by_class(p1, tk.Button):
                    if b.cget("text") == "取消":
                        assert int(b.cget("highlightthickness")) == 1, "取消键浅描边"
                p1.destroy()

                p2 = settings_panel.ProviderKeyPanel(app, "opencode_go")
                p2.withdraw()
                t2 = _all_text(p2)
                for want in ("自动检测：已找到 Go key（…1234）",
                             "使用自动检测（opencode auth.json）",
                             "Go key", "保存并验证"):
                    assert any(want in x for x in t2), f"go 面板缺控件：{want}"
                assert p2.ent_key.cget("show") == "*"
                assert "abcd1234" not in "".join(t2).replace("…1234", ""), \
                    "检测行仅尾 4 位"
                p2.destroy()
            finally:
                auth.detect_go_key, auth.has_secret = origs

        case("provider_key_panels_spot", key_panels_spot)

        # ============ 9) 设置页供应商可勾选 + 旁注三色态（M11a 三家化：去 OpenAI 行，4→3） ============
        def settings_notes():
            origs = (auth.detect_go_key, auth.detect_codex_token, auth.has_secret,
                     auth.BAILIAN_COOKIE_FILE)
            auth.detect_go_key = lambda: None
            auth.detect_codex_token = lambda auth_path=None: None    # M10：codex 检测打桩
            auth.has_secret = lambda name: False
            auth.BAILIAN_COOKIE_FILE = tmp / "no_such_cookie.dpapi"   # 三家全示未绑定
            try:
                s = settings_panel.SettingsPanel(app)
                s.withdraw()
                cbs = _by_class(s, tk.Checkbutton)
                names = [str(c.cget("text")) for c in cbs]
                for want in ("百炼 Token Plan", "OpenCode Go", "Codex"):   # M12② 标签去后缀
                    assert want in names
                assert "OpenAI" not in names, "M11a：OpenAI 供应商行应已移除"
                assert not any("（实验性）" in n for n in names), "M12②"
                for c in cbs:                                   # 百炼唯一同名单据
                    if str(c.cget("text")) == "百炼 Token Plan":
                        assert str(c.cget("state")) == "normal"
                # OpenCode Go/Codex 各出现两处：供应商行（恒可勾）+ 代理作用域
                # （M12①：代理默认关 → 作用域禁用；两处状态分开锁）
                for t in ("OpenCode Go", "Codex"):
                    st = sorted(str(c.cget("state")) for c in cbs
                                if str(c.cget("text")) == t)
                    assert st == ["disabled", "normal"], f"{t} 两处态：{st}"
                notes = [n for n in _by_class(s, tk.Label)
                         if "点击配置" in str(n.cget("text"))]
                assert len(notes) == 3
                assert all(str(n.cget("fg")) == settings_panel.ORANGE for n in notes), \
                    "未绑定旁注=ORANGE"
                s.destroy()
            finally:
                (auth.detect_go_key, auth.detect_codex_token, auth.has_secret,
                 auth.BAILIAN_COOKIE_FILE) = origs

        case("settings_three_toggle_notes", settings_notes)

        # ============ 10) 加油包细条不影响 usd/percent 供应商行 ============
        def non_bailian_unaffected():
            feed(app,
                 Usage(provider="openai", ok=True, unit="usd", used=12.5,
                       total=50.0, remaining=37.5, pct_used=0.25,
                       resets_at=_NOW + timedelta(days=5)),
                 Usage(provider="opencode_go", ok=True, unit="percent",
                       pct_used=0.4,
                       windows=[Window("rolling", 0.4, _NOW + timedelta(hours=5))]))
            t = "".join(texts(app))
            assert "加油包" not in t, "usd/percent 行不得出现加油包条"
        case("addon_strip_only_bailian", non_bailian_unaffected)

        # ============ 11) M7b① 三处对账：细条 == 底行分项 == 大数字−周期项（小数剩余） ============
        def reconcile_three_way():
            import re as _re
            u = u_with_addon()
            u.addon_remaining = 1508.6
            u.remaining = 15520.5 + 1508.6                   # 周期项取 .5：减法可精确回退，避免浮点毛刺
            feed(app, u)
            ts = texts(app)
            assert "17,028" in ts, ts                       # floor(15520.5)+floor(1508.6)
            strip = next(t for t in ts if _re.fullmatch(r"剩 [\d,]+ / [\d,]+", t))  # M11c③ 锚「剩」
            left = next(t for t in ts if "周期" in t and "加油包" in t)
            ad_strip = int(strip.split(" / ")[0].replace("剩 ", "").replace(",", ""))
            ad_left = int(_re.search(r"加油包 ([\d,]+)", left).group(1).replace(",", ""))
            wk_left = int(_re.search(r"剩余 ([\d,]+)（周期）", left).group(1).replace(",", ""))
            assert ad_strip == ad_left == 1508, (strip, left)
            assert wk_left + ad_strip == 17028, (wk_left, ad_strip)

        case("addon_three_way_reconcile", reconcile_three_way)

        # ============ 12) M7b② 细条填充=剩余占比（与文字同向）+ ⑤ 小填充无高光 ============
        def strip_fill_direction():
            u = u_with_addon()
            u.addon_remaining = 15000.0                     # 剩 75% → 条应长 ~75%
            u.remaining = 15520.0 + 15000.0
            feed(app, u)
            c = app.canvas
            band_y = (52 + 70) * app.S                      # 细条带（主条下缘之后）
            fills = [c.bbox(i) for i in c.find_all()
                     if c.type(i) == "rectangle"
                     and str(c.itemcget(i, "fill")).lower() == "#c2a878"
                     and c.bbox(i)[1] > band_y]
            tracks = [c.bbox(i) for i in c.find_all()
                      if c.type(i) == "rectangle"
                      and str(c.itemcget(i, "fill")).lower() == "#e3d3a9"
                      and c.bbox(i)[1] > band_y]
            assert fills and tracks, (fills, tracks)
            wf = max(b[2] - b[0] for b in fills)
            wt = max(b[2] - b[0] for b in tracks)
            assert abs(wf / wt - 0.75) < 0.08, (wf, wt)
            # 小填充（5%）无内高光：细条/主条带不得出现 BAR_HI 线
            u2 = u_with_addon()
            u2.pct_used = 0.05
            u2.used = 40000.0 * 0.05
            feed(app, u2)
            c = app.canvas
            his = [i for i in c.find_all()
                   if c.type(i) == "line"
                   and str(c.itemcget(i, "fill")).lower() == "#fffbEB".lower()]
            assert not his, "小填充上的白高光线应已跳过"

        case("strip_fill_direction_and_hi", strip_fill_direction)

        # ============ 12b) M24C 高光线绝对像素阈：双态矩阵（24 逻辑px 一把尺） ============
        def bar_hi_absolute_px_matrix():
            """M7b⑤ 旧「<15% 轨宽」→ M24C 绝对阈：填充宽 ≥24 逻辑px 才画内高光线。

            矩阵跨旧阈两侧：8%/10% 都 <15% 轨宽，但绝对宽 20.8px/26px 分居 24px
            阈两侧——新规则下无/有；≥15% 恒有；<0 无。双主条并排按同尺判定自然一致。"""
            c = app.canvas
            S = app.S
            tw = 260.0 * S
            def hi_n(pct):
                c.delete("all")
                app.hits.clear()
                app.clicks.clear()
                app._bar(20 * S, 40 * S, tw, 9 * S, pct, "#3bc371")
                return len([i for i in c.find_all()
                            if c.type(i) == "line"
                            and str(c.itemcget(i, "fill")).lower() == "#fffbEB".lower()])
            try:
                assert hi_n(23.5 / 260.0) == 0, "绝对宽 23.5px < 24px：应无高光"
                assert hi_n(0.10) == 1, "26px（8%→20.8px 无、10% 有——均 <15% 旧阈）"
                assert hi_n(25.0 / 260.0) == 1, "25px ≥ 24px：应画"
                assert hi_n(0.41) == 1, "大窗恒有"
                assert hi_n(0.0) == 0, "零填充不画"
            finally:
                feed(app, u_no_addon())          # 还原真实画面（case13 同法）

        case("bar_hi_absolute_px_matrix", bar_hi_absolute_px_matrix)

        # ============ 12c) M24A ↻ 图标族层序恒定：纸纹之上（静置/旋转帧/hover） ============
        def rot_layer_order_stable():
            """缺陷根因锁：under-texture 时代图标在虚线栅格之下，且初始渲染与旋转/
            hover 重绘路径不一致产生层序漂移。M24A 定案：rotbg/rot 两 item 恒在
            全部纹理线（dash=(1,6)）之后（之上）；静置、旋转帧、hover 三态同序。"""
            feed(app, u_no_addon())
            c = app.canvas

            def check(where: str) -> None:
                alls = c.find_all()
                pos = {it: k for k, it in enumerate(alls)}
                tex = [pos[i] for i in alls
                       if c.type(i) == "line"
                       and str(c.itemcget(i, "fill")).lower() == "#eedfb8"
                       and str(c.itemcget(i, "dash")).strip("()").replace(" ", "")]
                assert tex, where + "：未找到纸纹线"
                for tag in ("rotbg", "rot"):
                    its = [pos[i] for i in c.find_withtag(tag)]
                    assert its, f"{where}：{tag} item 缺失"
                    assert min(its) > max(tex), \
                        f"{where}：{tag} 层序不在纸纹之上 {min(its)}<={max(tex)}"
                # 恒序内检：rotbg 在图之下（两 tag 各一枚即可全序比较）
                assert pos[c.find_withtag("rotbg")[0]] < pos[c.find_withtag("rot")[0]], \
                    where + "：rotbg 应在图标 image 之下"

            check("静置态")
            app._rot = 300
            app._repaint_rot()                   # 旋转帧同路（_rot_raise 收口）
            check("旋转帧")
            ic = app._refresh_geo
            ev = types.SimpleNamespace(x=int(ic[0]), y=int(ic[1]), x_root=0, y_root=0)
            app._on_move(ev)                     # hover 进（toggle rotbg，同路不删重绘）
            assert str(c.itemcget(c.find_withtag("rotbg")[0], "state")) == "normal", \
                "hover 应点亮 rotbg"
            check("hover 态")
            app._on_move(types.SimpleNamespace(x=5, y=int(float(c.cget("height"))) - 5,
                                               x_root=0, y_root=0))   # 移出复位
            check("hover 移出复位")

        case("rot_layer_order_stable", rot_layer_order_stable)

        # ============ 13) M7b④ 胶囊描边=单条闭合折线（端点帽根治）+ 实拍右帽轮廓 ============
        def pill_outline_is_single_polygon():
            c = app.canvas
            c.delete("all")
            app._pill(50, 50, 200, 70, fill="#e3d3a9", outline="#cfb98a", width=1)
            polys = [i for i in c.find_all() if c.type(i) == "polygon"]
            outlines = [i for i in polys
                        if str(c.itemcget(i, "fill")) in ("", "none", "None")
                        and str(c.itemcget(i, "outline")).lower() == "#cfb98a"]
            assert len(polys) == 1 and len(outlines) == 1, "描边应为单一闭合折线"
            assert not any(c.type(i) == "arc" and str(c.itemcget(i, "style")) == "arc"
                           for i in c.find_all()), "不得再有独立 arc 描边项"
            app._render()                          # 还原真实画面

        case("pill_outline_single_polygon", pill_outline_is_single_polygon)

        def badge_cap_screen_profile():
            """实拍：Pro 徽章右帽 seam 列（旧竖笔位置）纵向连续边色像素 ≤2；10× 证据图落盘。"""
            import importlib
            cap = importlib.import_module("capture_m3c")
            from PIL import Image
            feed(app, u_with_addon())
            c = app.canvas
            polys = [i for i in c.find_all()
                     if c.type(i) == "polygon"
                     and str(c.itemcget(i, "outline")).lower() == "#dac8a0"]
            assert polys, "badge 描边多边形缺失"
            bx = max((c.bbox(i) for i in polys), key=lambda b: b[2] - b[0])
            x0, y0, x1, y1 = (int(v) for v in bx)
            r = (y1 - y0) / 2.0
            root.deiconify()
            root.update()
            time.sleep(0.35)
            try:
                wx, wy = root.winfo_rootx(), root.winfo_rooty()
                img = cap.grab(wx, wy, root.winfo_width(), root.winfo_height())
                px = img.load()

                def edge(p):
                    return all(abs(a - b) <= 12 for a, b in zip(p, (218, 200, 160)))

                def vrun(col, ylo, yhi):
                    best = cur = 0
                    for yy in range(ylo, yhi + 1):
                        cur = cur + 1 if edge(px[col, yy]) else 0
                        best = max(best, cur)
                    return best

                seam_r = min(x1 - int(r) - 1, img.width - 1)     # 右帽 seam 列（旧桩位）
                seam_l = x0 + int(r) + 1
                run_r, run_l = vrun(seam_r, y0, y1), vrun(seam_l, y0, y1)
                assert run_r <= 2 and run_l <= 2, (run_r, run_l)
                crop = img.crop((x0 - 8, max(0, y0 - 8),
                                 min(img.width, x1 + 10), y1 + 8))
                crop.resize((crop.width * 10, crop.height * 10), Image.NEAREST) \
                    .save(ROOT / "local" / "m7_badge_cap.png")
            finally:
                root.withdraw()

        case("badge_cap_screen_profile", badge_cap_screen_profile)

        # ============ 14) M9b usd 三态：余额未知采集正常 / 红线不造假 / 原「美元剩」回归 ============
        def usd_three_states():
            GUIDE = "未设预算 · 绑定普通 key 可看余额"
            # 态 A：真实 used=0.0、remaining=None、total=None（Admin key 实测形态）
            ua = Usage(provider="openai", ok=True, unit="usd", used=0.0)
            assert usd_used_mode(ua)
            big, left = breakdown_display(ua)
            assert big == "$0.00" and left == GUIDE, (big, left)
            feed(app, ua)
            ts = texts(app)
            assert "$0.00" in ts and GUIDE in ts, ts
            assert "近30天已用" in ts, "单位小字须换成「近30天已用」"
            assert "美元剩" not in ts, "已用态下不得再显「美元剩」"
            assert not any("已用 $0.00 /" in t for t in ts), "副行不得与大数字重复已用"
            # 红线：used=None 且 remaining=None → 大数字维持「—」，绝不渲染 $0.00 假值
            un = Usage(provider="openai", ok=True, unit="usd")
            assert not usd_used_mode(un)
            bign, leftn = breakdown_display(un)
            assert bign == "—" and leftn is None, (bign, leftn)
            feed(app, un)
            assert "$0.00" not in "".join(texts(app)), "None 不得渲染成 $0.00"
            # 态 B：used>0 同型（大数字=已用金额、单位小字、指引）
            ub = Usage(provider="openai", ok=True, unit="usd", used=42.35)
            bigb, leftb = breakdown_display(ub)
            assert bigb == "$42.35" and leftb == GUIDE, (bigb, leftb)
            feed(app, ub)
            tsb = texts(app)
            assert "$42.35" in tsb and "近30天已用" in tsb and "美元剩" not in tsb, tsb
            # 态 C：remaining 有值 → 原「美元剩」+「近30天已用 X / 预算 Y」副行回归锁
            uc = Usage(provider="openai", ok=True, unit="usd", used=1234.56,
                       total=2000.0, remaining=765.44, pct_used=0.617,
                       resets_at=_NOW + timedelta(days=5))
            assert not usd_used_mode(uc)
            bigc, leftc = breakdown_display(uc)
            assert bigc == "$765.44", bigc
            assert leftc == "近30天已用 $1,234.56 / 预算 $2,000.00", leftc
            feed(app, uc)
            tsc = "".join(texts(app))
            assert "美元剩" in tsc, tsc
            assert "近30天已用 $1,234.56 / 预算 $2,000.00" in tsc, tsc
            assert GUIDE not in tsc, "有余额态不得出现指引文案"

        case("usd_three_states_m9b", usd_three_states)

        # ============ M23) 套餐到期：纯函数矩阵（分档/跨年/零占位/宽度守卫） ============
        def plan_end_unit():
            anchor = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

            def pe(dt):
                return Usage(provider="bailian", ok=True, unit="credits",
                             remaining=100.0, total=100.0, pct_used=0.5, plan_end=dt)
            assert plan_end_display(pe(None), anchor) is None        # None→零占位
            t30, c30 = plan_end_display(pe(datetime(2026, 10, 18, 12, 0,
                                                   tzinfo=timezone.utc)), anchor)
            assert t30 == " · 套餐 10-18 到期" and c30 == SOFT_TXT, (t30, c30)
            t7, c7 = plan_end_display(pe(datetime(2026, 9, 25, 12, 0,
                                                  tzinfo=timezone.utc)), anchor)
            assert t7 == " · 套餐 09-25 到期" and c7 == ORANGE, (t7, c7)   # 整 7 天=橙档
            t4, c4 = plan_end_display(pe(datetime(2026, 9, 22, 12, 0,
                                                  tzinfo=timezone.utc)), anchor)
            assert c4 == ORANGE                                       # 4 天仍橙
            t3, c3 = plan_end_display(pe(datetime(2026, 9, 21, 12, 0,
                                                  tzinfo=timezone.utc)), anchor)
            assert c3 == RED                                          # 3 天=红档
            te, ce = plan_end_display(pe(datetime(2026, 9, 10, 12, 0,
                                                  tzinfo=timezone.utc)), anchor)
            assert ce == RED and te == " · 套餐 09-10 到期"            # 已过期按最紧迫
            tx, cx = plan_end_display(pe(datetime(2027, 1, 5, 12, 0,
                                                  tzinfo=timezone.utc)), anchor)
            assert tx == " · 套餐 2027-01-05 到期", tx                 # 跨年显全日期
            # Go/Codex：plan_end 恒 None → 永不显示
            assert plan_end_display(Usage(provider="opencode_go", ok=True,
                                          unit="percent", pct_used=0.2)) is None
            # 宽度守卫三分支（measure=字符数×8px 模拟 f_tiny）
            m8 = lambda s: len(s) * 8
            assert plan_end_split("ABCD", "TAIL", m8, 10 ** 6) == ("ABCD", "TAIL")
            assert plan_end_split("abcdefghij" * 2, "TAIL", m8, 100) == ("abcdefg…", "TAIL")
            assert plan_end_split("abcdefghij" * 2, "TAIL" * 4, m8, 40) \
                == ("abcdefghijabcdefghij", None)                     # 兜不住→后缀不显（降级）
            assert plan_end_split("X", "", m8, 5) == ("X", None)       # 无后缀=原样

        case("plan_end_unit_m23", plan_end_unit)

        # ============ M23) 渲染接线：C 行后缀+色档、stale 随灰、tooltip 全式 ============
        def plan_end_render():
            c = app.canvas
            def tail_item():
                for i in c.find_all():
                    if c.type(i) == "text" and "套餐" in str(c.itemcget(i, "text")):
                        return i
                return None
            # ① 正常近端（剩 2 天→红档）：主文完整 + 独立后缀 item 填 RED
            u = u_with_addon()
            u.plan_end = datetime.now(timezone.utc) + timedelta(days=2, hours=6)
            feed(app, u)
            it = tail_item()
            assert it is not None, texts(app)
            assert str(c.itemcget(it, "fill")).lower() == RED.lower(), c.itemcget(it, "fill")
            assert any(t.startswith("剩余 ") for t in texts(app)), "主文完整（宽度够不截断）"
            tip = app._tip_text({"u": u, "err": None, "stale": False})
            assert "套餐到期：" in tip and "剩 " in tip, tip          # 完整日期+天数行
            # ② 远期：后缀在、色=SOFT_TXT（与 C 行同档）
            u2 = u_with_addon()
            u2.plan_end = datetime.now(timezone.utc) + timedelta(days=40)
            feed(app, u2)
            it2 = tail_item()
            assert it2 is not None and str(c.itemcget(it2, "fill")).lower() == SOFT_TXT.lower()
            # ③ plan_end=None：任何「套餐…到期」文本零出现（且主文无残留分隔符尾巴）
            u3 = u_with_addon()
            feed(app, u3)
            assert tail_item() is None, texts(app)
            assert not any("到期" in t and "套餐" in t for t in texts(app))
            # ④ stale：last_good 带 plan_end 紧急档 → 日期照常显示但随行降灰(FAINT)
            u4 = u_with_addon()
            u4.plan_end = datetime.now(timezone.utc) + timedelta(days=1)
            feed(app, u4)                                             # 先存 last_good
            feed(app, Usage(provider="bailian", ok=False, error_code="NETWORK",
                            error_msg="timed out"))
            it4 = tail_item()
            assert it4 is not None, texts(app)                        # stale 仍带日期
            assert str(c.itemcget(it4, "fill")).lower() == "#b3a582", c.itemcget(it4, "fill")
            assert any("旧数据" in t for t in texts(app)), "确系 stale 灰档行"
            # ⑤ 零占位不扰高：plan_end 有/无两轮 bottom 一致
            feed(app, u_with_addon())
            h0 = [i for i in c.find_all() if c.type(i) == "text"]
            feed(app, u_with_addon())

        case("plan_end_render_m23", plan_end_render)

    finally:
        try:
            app.quit()
        except Exception:                                # noqa: BLE001
            pass
        config_mod.CONFIG_PATH, state_mod.STATE_PATH, state_mod.LOCAL_DIR = \
            orig_cfg, orig_state, orig_dir

    bad = [c for c in checks if not c[1]]
    for name, ok, err in checks:
        print(f"  {'PASS' if ok else 'FAIL':4} {name} {err}")
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 1 if bad else 0


def _by_class(w, cls) -> list:
    out = []
    for ch in w.winfo_children():
        if isinstance(ch, cls):
            out.append(ch)
        out.extend(_by_class(ch, cls))
    return out


def _all_text(w) -> list[str]:
    out = []
    try:
        t = w.cget("text")
        if isinstance(t, str) and t:
            out.append(t)
    except tk.TclError:
        pass
    for child in w.winfo_children():
        out.extend(_all_text(child))
    return out


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="m7_test_") as d:
        raise SystemExit(run(Path(d)))
