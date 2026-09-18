"""M22b（M25/M26 后同步 v1.9.0 真态）：三供应商「健康态」门面模拟图（dev-only，产物全部落 local\，不上 GitHub）。

运行：`python tests\\capture_m22.py`（桌面会话）。数据=随机但语义真实的演示值
（与 M20-A 同口径：假 Usage 注入渲染层，与真数据同一条 usages→_render 路径）：
- 百炼 pro：7d 已用 31.6%（剩 27,360）＋加油包 8,412/20,000 → 大数字 35,772=Σfloor；
  重置 2d04h；**M23 套餐到期：plan_end=2026-10-11（>7 天 → 灰档 SOFT_TXT），
  C 行尾追加「 · 套餐 10-11 到期」（canvas 项文本+色双断言）**。
- OpenCode Go（M24B 三主条含日；M24C 去波浪号）：5h 62% / 日 35% / 周 18%，
  大数字=最紧窗剩余 38%；三根等尺寸条，行高第 3 窗 +28（与 M24 门面同账）。
- Codex plus：5h 41%＋周 8% 双主条（M24B 短名去「窗」；大数字 59%）＋券×1 角标；积分余额进 tooltip。
三家 fetched_at 同值 → 标题行更新时间一致；↻ 静止；_upd_new=None（无橙点）。

产物（local\，gitignored）：preview_m22_note.png / preview_m22_note_hover.png /
preview_m22_settings.png / preview_m22.gif（静置↔hover 两帧）。

纪律：零网络（updater.check 打桩 skipped）；config/state/auth 写盘与凭据探测文件
全部重定向 temp（真实 local 目录三件哈希前后必须一致，报告打印）；不新增产品代码；
git 零动作。渲染断言：三行 kind 全 full/stale=False/cred=False；大数字/分项自洽；
**M25 全画面零「窗口」、条行 label 零「窗」/「~」（与 capture_m24 同一禁字基准）**；
foot=动态 v{APP_VERSION}（M25 后不再钉死具体版本）；画面无 ORANGE 像素残留。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import sys
import tempfile
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from PIL import Image                                             # noqa: E402

import capture_m3c as cap                                         # noqa: E402
from src import auth, config as config_mod, state as state_mod    # noqa: E402
from src import updater                                           # noqa: E402
from src.scheduler import Scheduler                               # noqa: E402
from src.sources.base import Usage, Window                        # noqa: E402
from src.state import DEFAULTS                                    # noqa: E402
from src.ui import PAPER, SOFT_TXT, NoteApp               # noqa: E402
import main as main_mod                                           # noqa: E402

import make_gif as mg                                             # noqa: E402  复用 pump/wait_mapped
from src import version as version_mod                            # noqa: E402

LOCAL = ROOT / "local"
OUT = LOCAL
SCALE_FACTOR = 1.5
_GUARD = [LOCAL / "config.json", LOCAL / "state.json", LOCAL / "bailian_cookie.dpapi"]

# 固定"更新时间"（三源同一时刻采集成功，标题行 HH:MM:SS 一致）
_FETCHED = datetime.now(timezone.utc).replace(microsecond=0)


def sha(p: Path) -> str:
    if not p.exists():
        return "MISSING"
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()[:16]


# ---------- 演示 Usage（语义正确、数值互相自洽） ----------

def u_bailian() -> Usage:
    """pro；7d=40,000 已用 31.6%→剩 27,360；加油包 8,412/20,000；大数字 35,772。
    M23：plan_end=2026-10-11（距拍摄日 >7 天 → C 行后缀「 · 套餐 10-11 到期」灰档）。"""
    weekly, pct, ar = 40000.0, 0.316, 8412.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_FETCHED + timedelta(days=2, hours=4, minutes=12),
                 windows=[Window("7d", pct, _FETCHED + timedelta(days=2, hours=4, minutes=12))],
                 addon_remaining=ar, fetched_at=_FETCHED,
                 plan_end=datetime(2026, 10, 11, tzinfo=timezone.utc))


def u_go() -> Usage:
    """M24B OpenCode Go 三主条（含日；M24C 去波浪号）：5h 62% / 日 35% / 周 18%
    （source 定稿 label，与 capture_m24 门面同一数据基准）；大数字=最紧窗剩余 38%。"""
    r5 = _FETCHED + timedelta(hours=3, minutes=5)
    day = _FETCHED + timedelta(hours=17, minutes=40)
    wk = _FETCHED + timedelta(days=4, hours=11)
    return Usage(provider="opencode_go", ok=True, spec=None, unit="percent",
                 pct_used=0.62, resets_at=r5,
                 windows=[Window("5h", 0.62, r5), Window("日", 0.35, day),
                          Window("周", 0.18, wk)],
                 fetched_at=_FETCHED)


def u_codex() -> Usage:
    """Codex plus：5h 41% + 周 8% 双主条；券×1；积分余额 $6.25 走 tooltip。"""
    r5, wk = _FETCHED + timedelta(hours=2, minutes=18), _FETCHED + timedelta(days=3, hours=7)
    return Usage(provider="codex", ok=True, spec="plus", unit="percent",
                 pct_used=0.41, resets_at=r5,
                 windows=[Window("5h", 0.41, r5), Window("周", 0.08, wk)],
                 addon_remaining=6.25, note="窗口重置券：可用 1", fetched_at=_FETCHED)


CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian", "opencode_go", "codex"],
       "network": {"proxy_enabled": True, "proxy_url": "127.0.0.1:7890",
                   "proxy_targets": ["opencode_go", "codex"]},
       "update": {"enabled": True, "repo": "WuJerry9376/token-widget",
                  "mirror": "", "last_check": time.time(),
                  "last_auto_date": "2000-01-01"}}

FORBIDDEN = ("需重新登录", "凭据", "旧数据", "拉取失败", "未配置", "更新中",
             "尚未", "地区受限", "登录已过期")


def park_cursor() -> None:
    """把物理鼠标挪到舞台与常见截取区之外（BitBlt 会把鼠标箭头画进快照）。"""
    ctypes.windll.user32.SetCursorPos(2260, 1240)
    time.sleep(0.08)


def count_orange(im: Image.Image) -> int:
    """真·橙元素像素（凭据警示/橙点/更新中标题）。tol=20：ClearType 文本边缘的
    橙蓝纹边最近距离实测 ≥35（如 (193,125,40) vs #D9782E），不会误报；而产品
    ORANGE 平涂（文字笔画/圆点）必留下 dist<20 的实心像素。"""
    o = (217, 120, 46)
    n = 0
    for cnt, c in im.getcolors(maxcolors=1 << 24) or []:
        if abs(c[0] - o[0]) + abs(c[1] - o[1]) + abs(c[2] - o[2]) < 20:
            n += cnt
    return n


def main_run(tmp: Path) -> int:
    guard_before = {p.name: sha(p) for p in _GUARD}
    (tmp / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = tmp / "bailian_cookie.dpapi"
    updater.check = lambda cfg, force=False, **kw: updater.CheckResult(skipped=True)
    # 假凭据（全在 tmp）：设置页三源旁注=绿色「已绑定」
    auth.save_bailian_cookie("login_aliyunid_csrf=m22fake; login_aliyunid_ticket=m22fake",
                             path=auth.BAILIAN_COOKIE_FILE)
    auth.save_secret("opencode_go_key", "go-M22-DEMO-KEY-000000")
    auth.save_secret("codex_access_token", "eyJ-M22-DEMO-TOKEN-000000")

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.tk.call("tk", "scaling", SCALE_FACTOR * 96.0 / 72.0)
    cfg = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
           for k, v in CFG.items()}
    app = NoteApp(root, cfg, Scheduler([], poll_seconds=300), state=dict(DEFAULTS))
    ok = True
    try:
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        bg.configure(bg=PAPER)
        bg.lift()
        root.update()
        time.sleep(0.4)

        app.usages = [u_bailian(), u_go(), u_codex()]
        app.meta = {"next_delay": 300, "ts": time.time(), "low": False}
        app.last_good = {u.provider: u for u in app.usages}
        app._render()
        app._pos = (150, 100)
        root.geometry(f"+{app._pos[0]}+{app._pos[1]}")
        mg.pump([root], 400)
        root.lift()
        mg.pump([root], 250)

        # ---- 渲染断言 ----
        infos = app._row_infos()
        ok &= len(infos) == 3 and all(i["kind"] == "full" and not i["stale"]
                                      and not i["cred"] for i in infos)
        ts = [str(app.canvas.itemcget(i, "text"))
              for i in app.canvas.find_all() if app.canvas.type(i) == "text"]
        joined = " | ".join(ts)
        ok &= "35,772" in joined and "27,360" in joined and "8,412" in joined
        ok &= "38%" in joined and "59%" in joined                  # Go/Codex 大数字
        ok &= "周 · 已用 8.0%" in joined and "5h · 已用 41.0%" in joined   # M24B：去「窗」
        # M24B 三主条（含日）/M24C 去波浪号：Go=5h·日·周 三条文案锁（capture_m24 同基准）
        ok &= ("5h · 已用 62.0%" in joined and "日 · 已用 35.0%" in joined
               and "周 · 已用 18.0%" in joined)
        # M25：全画面零「窗口」；条行 label（Go5h/日/周+Codex5h/周+百炼 7d）零「窗」、零「~」
        bar_labels = [t for t in ts if "· 已用" in t
                      and t.startswith(("5h ", "日 ", "周 ", "7d "))]
        ok &= (len(bar_labels) == 6 and "周窗" not in joined and "窗口" not in joined
               and "~5h" not in joined
               and all("窗" not in t and "~" not in t for t in bar_labels))
        if not ok:
            print("禁字失败:", bar_labels, flush=True)
        ok &= "券×1" in joined
        ok &= not any(w in joined for w in FORBIDDEN)
        ok &= app._upd_new is None and not app.fetching
        ok &= 27360 + 8412 == 35772
        # ---- M23：套餐到期后缀断言（独立 canvas 文本项，>7 天=SOFT_TXT 灰档） ----
        c = app.canvas
        pe_items = [(str(c.itemcget(i, "text")), str(c.itemcget(i, "fill")))
                    for i in c.find_all() if c.type(i) == "text"
                    and "套餐" in str(c.itemcget(i, "text"))]
        print("plan_end 项:", pe_items, flush=True)
        ok &= (" · 套餐 10-11 到期", SOFT_TXT) in pe_items
        ok &= " · 套餐 10-11 到期" in joined
        print("row_infos:", [(i["u"].provider, i["kind"], i["stale"], i["cred"])
                             for i in infos], flush=True)

        x, y, w, h = cap.win_rect(app.root)
        print(f"note = {w}x{h} @ ({x},{y})", flush=True)
        # M24B 三主条高度账（本机 scaling=1.5 实值，与 capture_m24 note 495x639 同账）
        size_ok = (w, h) == (495, 639)   # Go 第 3 窗 +28 账；异常时打印不中断截图
        if not size_ok:
            print(f"NOTE: note 应 495x639（M24 三主条账），得 {w}x{h}", flush=True)
        ok &= size_ok

        # ---- 1) 静置主浮窗 ----
        park_cursor()
        shot = cap.grab(x, y, w, h)
        n_orange = count_orange(shot)
        ok &= n_orange == 0
        print(f"静置帧 ORANGE 像素={n_orange}（应为 0）", flush=True)
        p1 = OUT / "preview_m22_note.png"
        shot.save(p1)

        # ---- 2) hover：真实 <Motion> 到 ↻ → rotbg 微亮 + 其 tooltip ----
        ic = app._refresh_geo
        assert ic is not None
        app.canvas.event_generate("<Motion>", x=int(ic[0]), y=int(ic[1]))
        mg.pump([root], 250)
        if app._tip is not None:
            app._tip.lift()
        mg.pump([root], 150)
        # 联合舞台（便笺 ∪ tooltip），两帧同矩形供 gif
        tw = th = 0
        if app._tip is not None and app._tip.winfo_ismapped():
            tw = app._tip.winfo_rootx() - x + app._tip.winfo_width()
            th = app._tip.winfo_rooty() - y + app._tip.winfo_height()
        stg_w = max(w, tw + 20)
        stg_h = max(h, th + 20)
        park_cursor()
        hover = cap.grab(x, y, stg_w, stg_h)
        p2 = OUT / "preview_m22_note_hover.png"
        hover.save(p2)                                     # 含完整 tooltip（舞台矩形）
        app._tip_hide()
        app.canvas.event_generate("<Motion>", x=5, y=h - 5)   # 移出复位（↻ 底色恢复）
        mg.pump([root], 200)
        park_cursor()
        idle_full = cap.grab(x, y, stg_w, stg_h)             # 同矩形静置帧

        # ---- 4) 两帧 gif（静置↔hover）----
        base = idle_full.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
        fr2 = hover.quantize(palette=base, dither=Image.NONE)
        p4 = OUT / "preview_m22.gif"
        base.save(p4, save_all=True, append_images=[fr2], duration=800, loop=0,
                  optimize=True, disposal=1)

        # ---- 3) 设置页：三源全勾+绿已绑定 / 代理 127.0.0.1:7890 / 自动更新勾选 ----
        app.open_settings()
        panel = app._settings
        assert panel is not None and mg.wait_mapped(panel)
        mg.pump([panel, root], 500)
        panel.lift()
        mg.pump([panel], 200)
        texts: list[str] = []

        def walk(wd):
            try:
                t = wd.cget("text")
                if isinstance(t, str) and t:
                    texts.append(t)
                if isinstance(wd, tk.Checkbutton):
                    v = wd.cget("variable")
                    if v:
                        texts.append(f"__CHK__{t}__{int(wd.getvar(v))}")
            except (tk.TclError, ValueError):
                pass
            for c in wd.winfo_children():
                walk(c)
        walk(panel)
        j = " | ".join(texts)
        ok &= j.count("已绑定 · 点击配置") == 3 and "未绑定" not in j
        ok &= ("__CHK__自动更新__1" in j) and ("__CHK__启用代理（境外源）__1" in j)
        ok &= ("__CHK__百炼 Token Plan__1" in j and "__CHK__OpenCode Go__1" in j
               and "__CHK__Codex__1" in j)
        ok &= "127.0.0.1" in j and "7890" in j
        ok &= f"v{version_mod.APP_VERSION} · by Jerry Wu" in j   # 动态版本锁（M25 后不钉死）
        px_panel, py_panel, pw, ph = cap.win_rect(panel)
        park_cursor()
        cap.grab(px_panel, py_panel, pw, ph).save(OUT / "preview_m22_settings.png")
        print(f"settings = {pw}x{ph}；foot={version_mod.APP_VERSION}；已绑定×3", flush=True)
        panel.close_card()

        for p in (p1, p2, OUT / "preview_m22_settings.png", p4):
            print(f"saved {p.name}  {p.stat().st_size:,} B", flush=True)
        print("M22 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                      # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check) = orig
        guard_after = {p.name: sha(p) for p in _GUARD}
        for k in guard_before:
            same = "IDENTICAL" if guard_before[k] == guard_after[k] else "!!!CHANGED!!!"
            print(f"HASH-GUARD {k}: before={guard_before[k]} after={guard_after[k]} {same}",
                  flush=True)
        assert guard_before == guard_after, "真实 local\\ 文件被触碰！"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m22_cap_") as d:
        raise SystemExit(main_run(Path(d)))
