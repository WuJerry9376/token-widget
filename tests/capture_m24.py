"""M24（用户实测四修后重出）：三供应商「健康态」门面模拟图（dev-only，产物全部落 local\，零 git）。

运行：`python tests\\capture_m24.py`（桌面会话）。同 M22b 纪律（假 Usage 注入渲染层、
零网络、写盘重定向 temp、真实 local\\ 三件哈希守护前后比对）。

与 M22b 的差异（用户令）：**不再产出 hover 版本与两帧 gif**，只出
`preview_m24_note.png` + `preview_m24_settings.png`。M24 未触碰设置面板 →
settings 图按裁决「沿用重命名拷贝」（脚本内拷贝 preview_m22_settings.png 并注明；
若源文件缺失则现渲染设置页兜底）。

门面数据（数值自洽断言保留）：
- 百炼 pro：7d 已用 31.6%（剩 27,360）＋加油包 8,412/20,000 → 大数字 35,772=Σfloor；
  M23 套餐到期后缀「 · 套餐 10-11 到期」灰档保留。
- OpenCode Go（M24B 三主条含日）：5h 62% / 日 35% / 周 18%，大数字=最紧窗剩余 38%。
- Codex plus：5h 41%＋周 8%（M24C 绝对阈：41% 条有内高光、8% 条（23.5px<24px）无——
  与 Go 三窗高光态一起钉双态矩阵）；券×1；大数字 59%。
- ↻ 图标 M24A 层序修复后态：rotbg/rot 两 item 恒在全部纸纹线（dash=(1,6)）之上。

判据：三行 kind 全 full；「周窗」全画面不存在；Go/Codex 条行 label 无「窗」字；
M3c 顶边纯净（strip_above20=0、outside_paper_top=0）+ 四项守护；画面零 ORANGE 像素。
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
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
from src.ui import PAPER, SOFT_TXT, NoteApp                       # noqa: E402
import main as main_mod                                           # noqa: E402

import make_gif as mg                                             # noqa: E402  复用 pump
from src import version as version_mod                            # noqa: E402

LOCAL = ROOT / "local"
OUT = LOCAL
SCALE_FACTOR = 1.5
_GUARD = [LOCAL / "config.json", LOCAL / "state.json", LOCAL / "bailian_cookie.dpapi"]
M22_SETTINGS = LOCAL / "preview_m22_settings.png"

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
    M23 套餐到期后缀保留：plan_end=2026-10-11（>7 天 → 灰档 SOFT_TXT）。"""
    weekly, pct, ar = 40000.0, 0.316, 8412.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_FETCHED + timedelta(days=2, hours=4, minutes=12),
                 windows=[Window("7d", pct, _FETCHED + timedelta(days=2, hours=4, minutes=12))],
                 addon_remaining=ar, fetched_at=_FETCHED,
                 plan_end=datetime(2026, 10, 11, tzinfo=timezone.utc))


def u_go() -> Usage:
    """M24B OpenCode Go 三主条（含日）：5h 62% / 日 35% / 周 18%（source 定稿 label；
    M24C 去波浪号）；大数字=最紧窗（62%）剩余占比 38%。"""
    r5 = _FETCHED + timedelta(hours=3, minutes=5)
    day = _FETCHED + timedelta(hours=17, minutes=40)
    wk = _FETCHED + timedelta(days=4, hours=11)
    return Usage(provider="opencode_go", ok=True, spec=None, unit="percent",
                 pct_used=0.62, resets_at=r5,
                 windows=[Window("5h", 0.62, r5), Window("日", 0.35, day),
                          Window("周", 0.18, wk)],
                 fetched_at=_FETCHED)


def u_codex() -> Usage:
    """Codex plus：5h 41% + 周 8% 双主条；券×1；积分余额 $6.25 走 tooltip。
    M24C：41%（≈121px）画内高光、8%（≈23.5px < 24px 绝对阈）不画——双态同尺。"""
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
    ctypes.windll.user32.SetCursorPos(2260, 1240)
    time.sleep(0.08)


def count_orange(im: Image.Image) -> int:
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
    auth.save_bailian_cookie("login_aliyunid_csrf=m24fake; login_aliyunid_ticket=m24fake",
                             path=auth.BAILIAN_COOKIE_FILE)
    auth.save_secret("opencode_go_key", "go-M24-DEMO-KEY-000000")
    auth.save_secret("codex_access_token", "eyJ-M24-DEMO-TOKEN-000000")

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
        bg.configure(bg="#2E8B57")  # 受控纯色舞台（capture_m3c 纯净度判据同色）
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

        # ---- 渲染断言（数值自洽 + M24 四修） ----
        c = app.canvas
        infos = app._row_infos()
        ok &= len(infos) == 3 and all(i["kind"] == "full" and not i["stale"]
                                      and not i["cred"] for i in infos)
        ts = [str(c.itemcget(i, "text")) for i in c.find_all() if c.type(i) == "text"]
        joined = " | ".join(ts)
        ok &= "35,772" in joined and "27,360" in joined and "8,412" in joined
        ok &= "38%" in joined and "59%" in joined
        # B：Go 三主条含日；codex 块2 去「窗」；画面无「周窗」
        ok &= ("5h · 已用 62.0%" in joined and "日 · 已用 35.0%" in joined
               and "周 · 已用 18.0%" in joined)
        ok &= "周 · 已用 8.0%" in joined and "5h · 已用 41.0%" in joined
        # 禁字扫描范围=多主条行 label（Go 5h/日/周 + Codex 5h/周；百炼通用行
        # 「7d 窗口 · 已用」不在 M24B 裁决范围）
        bar_labels = [t for t in ts if "· 已用" in t
                      and t.startswith(("5h ", "日 ", "周 "))]
        ok &= ("周窗" not in joined and len(bar_labels) == 5
               and all("窗" not in t for t in bar_labels))
        # M24C：Go 窗口标签去波浪号——全画面无 "~5h"、条行 label 零 "~" 字符
        ok &= "~5h" not in joined and all("~" not in t for t in bar_labels)
        if not ok:
            print("B 禁字失败:", bar_labels, "~5h" in joined, flush=True)
        ok &= "券×1" in joined and not any(w in joined for w in FORBIDDEN)
        ok &= app._upd_new is None and not app.fetching
        ok &= 27360 + 8412 == 35772
        # M23 套餐到期后缀保留
        pe = [(str(c.itemcget(i, "text")), str(c.itemcget(i, "fill")))
              for i in c.find_all() if c.type(i) == "text"
              and "套餐" in str(c.itemcget(i, "text"))]
        ok &= (" · 套餐 10-11 到期", SOFT_TXT) in pe
        print("plan_end 项:", pe, flush=True)
        # A：↻ 层序（修复后态）——rotbg/rot 恒在全部纸纹线之上
        alls = c.find_all()
        pos = {i: k for k, i in enumerate(alls)}
        tex = [pos[i] for i in alls if c.type(i) == "line"
               and str(c.itemcget(i, "fill")).lower() == "#eedfb8"
               and str(c.itemcget(i, "dash")).strip("()").replace(" ", "")]
        ic_idx = [pos[i] for tag in ("rotbg", "rot") for i in c.find_withtag(tag)]
        ok &= bool(tex) and bool(ic_idx) and min(ic_idx) > max(tex)
        print(f"A 层序: 纹理 n={len(tex)} max_idx={max(tex)} 图标 idx={sorted(ic_idx)}",
              flush=True)
        # C：高光双态矩阵（6 根 9px 主条：bailian1 + Go3 + Codex2；仅 codex 周 8% 无）
        tracks = sorted((c.bbox(i) for i in alls
                         if c.type(i) == "rectangle"
                         and str(c.itemcget(i, "fill")).lower() == "#e3d3a9"
                         and c.bbox(i)[3] - c.bbox(i)[1] > 8 * app.S),
                        key=lambda b: b[1])
        his = [c.bbox(i) for i in alls if c.type(i) == "line"
               and str(c.itemcget(i, "fill")).lower() == "#fffbEB".lower()]
        hi_by_track = [any(t[1] - 1 <= (b[1] + b[3]) / 2 <= t[3] + 1 for b in his)
                       for t in tracks]
        ok &= len(tracks) == 6 and hi_by_track == [True] * 5 + [False]
        print(f"C 高光矩阵（上→下 6 条）: {hi_by_track}", flush=True)

        x, y, w, h = cap.win_rect(app.root)
        print(f"note = {w}x{h} @ ({x},{y})", flush=True)

        # ---- M3c 顶边纯净复测（受控背景窗下；先挪开鼠标，BitBlt 会把箭头画进快照） ----
        park_cursor()
        res = cap.check_note_purity(app, x, y, w, h)
        print("purity:", res, flush=True)
        ok &= res["strip_above20"] == 0 and res["outside_paper_top"] == 0
        ok &= res["paper_holes"] == 0
        if res["outside_paper_all"]:    # 非顶边区残留（若有）打印坐标供目检定位
            print("NOTE: outside_paper_all =", res["outside_paper_all"],
                  "（顶边判据=0 达成；非顶角区残留见上）", flush=True)

        # ---- 唯一主浮窗截图（用户令：不再出 hover/gif） ----
        park_cursor()
        shot = cap.grab(x, y, w, h)
        n_orange = count_orange(shot)
        ok &= n_orange == 0
        print(f"静置帧 ORANGE 像素={n_orange}（应为 0）", flush=True)
        p1 = OUT / "preview_m24_note.png"
        shot.save(p1)

        # ---- settings：M24 零触碰设置面板 → 沿用重命名拷贝（缺图则现渲染兜底） ----
        p3 = OUT / "preview_m24_settings.png"
        if M22_SETTINGS.exists():
            shutil.copyfile(M22_SETTINGS, p3)
            print("SETTINGS: 沿用 preview_m22_settings.png 重命名拷贝（M24 未改设置面板）",
                  flush=True)
        else:
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
                for ch in wd.winfo_children():
                    walk(ch)
            walk(panel)
            j = " | ".join(texts)
            ok &= j.count("已绑定 · 点击配置") == 3 and "未绑定" not in j
            ok &= f"v{version_mod.APP_VERSION} · by Jerry Wu" in j
            px, py, pw, ph = cap.win_rect(panel)
            park_cursor()
            cap.grab(px, py, pw, ph).save(p3)
            print(f"SETTINGS: 现渲染兜底 {pw}x{ph}", flush=True)
            panel.close_card()

        for p in (p1, p3):
            print(f"saved {p.name}  {p.stat().st_size:,} B", flush=True)
        print("M24 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="m24_cap_") as d:
        raise SystemExit(main_run(Path(d)))
