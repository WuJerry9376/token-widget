"""M20-A：README 门面主图 docs/screenshots/demo.gif 生成器（dev-only，允许 PIL）。

用法：
    python tools\\make_gif.py                 # 现场实拍 7 帧 + 合成 gif（需桌面会话）
    python tools\\make_gif.py --compose-only  # 仅用 docs/screenshots/src/ 现有帧重合成（确定性）

渲染刻度：启动前把 tk scaling 设为 150% 等效（S=1.5，产品原生支持的 DPI 档位），
便笺 495×435、弹窗 599×330、tooltip 等同屏元素同刻度，全部帧 1:1 截取无重采样，
成品 620×540（宽 ≤660 达成）。

帧序列（200ms/帧，无限循环）：
    f1 静置两行（百炼 39,375 系假数据 + Codex 双主条）
    f2 发现新版橙点亮起（真实 _upd_new → _render 支路）
    f3 悬停 tooltip（真实 _tip_show 渲染，仅事件坐标为合成）
    f4 更新弹窗展开（SettingsPanel._up_open_dialog → UpdateDialog 真实构造）
    f5 弹窗「立即更新」hover 加深一档（同 m19 证据手法）
    f6 下载进度 38.0%（真实 _q("pct") → _poll 事件路径）
    f7 下载进度 71.0%

纪律：src/ 产品代码零改动；假数据只注入渲染层（app.usages + _render，与真数据
同一路径）；updater.check 打桩 skipped、零网络；config/state/auth 写盘全部重定向
temp；色键外区域用纯色 PAPER 背景窗垫底——透明处即纸色（“透明色键按 PAPER 底处理”）。
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PIL import Image                                             # noqa: E402

import capture_m3c as cap                                         # noqa: E402
from src import auth, config as config_mod, state as state_mod    # noqa: E402
from src import updater                                           # noqa: E402
from src.scheduler import Scheduler                               # noqa: E402
from src.sources.base import Usage, Window                        # noqa: E402
from src.state import DEFAULTS                                    # noqa: E402
from src.ui import BADGE_BG, BADGE_EDGE, INK, NoteApp, PAPER             # noqa: E402
import main as main_mod                                           # noqa: E402

SRC_DIR = ROOT / "docs" / "screenshots" / "src"
GIF_PATH = ROOT / "docs" / "screenshots" / "demo.gif"

# 舞台：物理 620×540（S=1.5），成品宽 ≤660。所有帧同一矩形，屏幕坐标固定。
STAGE = (40, 24, 620, 540)
NOTE_OFF = (62, 10)                        # 便笺左上角相对舞台（水平居中 495 宽）
SCALE_FACTOR = 1.5                         # 强制渲染刻度（150% DPI 等效）
DUR_MS = 200

_NOW = datetime.now(timezone.utc)
CFG = {"poll_seconds": 300, "low_yellow_pct": 0.15, "low_red_pct": 0.05,
       "always_on_top": True, "autostart": False,
       "enabled_providers": ["bailian", "codex"],
       "update": {"enabled": True, "repo": "WuJerry9376/token-widget",
                  "mirror": "", "last_check": time.time(),
                  "last_auto_date": "2000-01-01"}}

# GIF 内弹窗演示用短 notes（保证弹窗宽 ≤ 舞台 330px；feature_dialog.png 才用长 notes
# 实证 ≤6 行截断排版）。
NOTES_GIF = (
    "• 发现新版改为专属弹窗确认\n"
    "• 下载进度百分比实时显示\n"
    "• 安装前校验 SHA-256 完整性"
)
TOTAL_BYTES = 11263948                     # 示例包大小 10.7 MB


def u_bailian() -> Usage:
    """演示数据：7d 周期 40,000 已用 51.6%（剩 19,375）＋ 加油包 20,000 → 大数字 39,375。"""
    weekly, pct, ar = 40000.0, 0.515625, 20000.0
    return Usage(provider="bailian", ok=True, spec="pro", unit="credits",
                 used=weekly * pct, total=60000.0,
                 remaining=weekly * (1 - pct) + ar, pct_used=pct,
                 resets_at=_NOW + timedelta(hours=8, minutes=2),
                 windows=[Window("7d", pct, _NOW + timedelta(hours=8, minutes=2))],
                 addon_remaining=ar)


def u_codex() -> Usage:
    """演示数据：5h 主条 62%（绿）+ 周主条 30%（M14 双主条）+ 券×1 角标。"""
    return Usage(provider="codex", ok=True, spec="plus", unit="percent",
                 pct_used=0.62, resets_at=_NOW + timedelta(hours=2, minutes=1),
                 windows=[Window("5h", 0.62, _NOW + timedelta(hours=2, minutes=1)),
                          Window("周", 0.30, _NOW + timedelta(days=4, minutes=7))],
                 addon_remaining=12.345, note="窗口重置券：可用 1")


def make_info() -> updater.UpdateInfo:
    return updater.UpdateInfo(version="1.9.0", url="https://github.com/fake/repo/x.exe",
                              notes=NOTES_GIF, digest=None, size=TOTAL_BYTES,
                              published="2026-09-19T08:12:34Z")


def pump(widgets, ms: float) -> None:
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        for wd in widgets:
            try:
                wd.update()
            except tk.TclError:
                pass
        time.sleep(0.01)


def wait_mapped(win: tk.Misc, timeout: float = 3.0) -> bool:
    t0 = time.monotonic()
    while not win.winfo_ismapped() and time.monotonic() - t0 < timeout:
        win.update()
        time.sleep(0.02)
    return win.winfo_ismapped()


def shot() -> Image.Image:
    return cap.grab(*STAGE)


def capture_frames(src_dir: Path) -> list[Path]:
    """现场实拍 7 帧（2× NEAREST PNG），返回文件列表（f1..f7 顺序）。"""
    src_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="m20_gif_"))
    (tmp / "config.json").write_text('{"update": ' + __import__("json").dumps(CFG["update"])
                                     + '}', encoding="utf-8")
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, updater.check)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp
    updater.check = lambda cfg, force=False, **kw: updater.CheckResult(skipped=True)

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    root.tk.call("tk", "scaling", SCALE_FACTOR * 96.0 / 72.0)   # NoteApp 构建前锁定刻度
    cfg = dict(CFG)
    cfg["update"] = dict(CFG["update"])
    app = NoteApp(root, cfg, Scheduler([], poll_seconds=300), state=dict(DEFAULTS))
    paths: list[Path] = []
    sx, sy, sw, sh = STAGE
    try:
        # 纯色 PAPER 背景窗垫在色键浮窗之后：纸形/卡片之外 = 纸色底
        scr_w, scr_h = root.winfo_screenwidth(), root.winfo_screenheight()
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{scr_w}x{scr_h}+0+0")
        bg.configure(bg=PAPER)
        bg.lift()
        root.update()
        time.sleep(0.4)

        # ---- f1 静置两行（渲染层注入假 Usage，与真数据同路径） ----
        app.usages = [u_bailian(), u_codex()]
        app.meta = {"next_delay": 300, "ts": time.time(), "low": False}
        app.last_good = {"bailian": app.usages[0], "codex": app.usages[1]}
        app._render()
        app._pos = (sx + NOTE_OFF[0], sy + NOTE_OFF[1])         # 记账位先行（_sync_size 用它回写）
        root.geometry(f"+{app._pos[0]}+{app._pos[1]}")
        pump([root], 400)
        root.lift()
        pump([root], 250)
        nw, nh = app.canvas.winfo_width(), app.canvas.winfo_height()
        print(f"note size = {nw}x{nh}  stage = {sw}x{sh}", flush=True)
        paths.append(_save(shot(), src_dir, "m20_f1_idle.png"))

        # ---- f2 橙点亮起（真实 _upd_new → _render 支路） ----
        info = make_info()
        app._upd_new = info
        app._render()
        pump([root], 250)
        root.lift()
        pump([root], 150)
        dot = [h for h in app.hits if h[4].get("tip", "").startswith("发现新版本")]
        assert dot, "橙点热区未注册"
        paths.append(_save(shot(), src_dir, "m20_f2_dot.png"))

        # ---- f3 悬停 tooltip（真实 _tip_show；事件坐标为合成，避免溢出舞台） ----
        app._tip_show(dot[0][4], SimpleNamespace(x_root=sx + 120, y_root=sy + 300))
        pump([root, app._tip], 300)
        app._tip.lift()
        pump([root], 150)
        paths.append(_save(shot(), src_dir, "m20_f3_tip.png"))
        app._tip_hide()
        pump([root], 100)

        # ---- f4 更新弹窗（真实 SettingsPanel._up_open_dialog 链路） ----
        from src import settings_panel
        panel = settings_panel.SettingsPanel(app)
        wait_mapped(panel)
        pump([panel], 250)
        panel.withdraw()                       # 面板藏，弹窗承接主镜（同 m19）
        panel._up_info = info
        panel._up_open_dialog()
        dlg = panel._up_dialog
        assert dlg is not None, "UpdateDialog 未创建"
        wait_mapped(dlg)
        pump([dlg, root], 350)
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        dx = sx + (sw - dw) // 2
        dy = sy + (sh - dh) // 2
        print(f"dialog size = {dw}x{dh}", flush=True)
        assert dw <= sw and dy + dh <= sy + sh, f"弹窗超出舞台：{dw}x{dh} @ +{dx}+{dy}"
        dlg.geometry(f"+{dx}+{dy}")
        pump([dlg, root], 200)
        dlg.lift()
        pump([dlg, root], 200)
        paths.append(_save(shot(), src_dir, "m20_f4_dialog.png"))

        # ---- f5 hover：两钮加深一档（tk flat 钮无系统 hover，用 active 色值代呈现） ----
        dlg.btn_go.configure(bg="#57503E")
        dlg.btn_no.configure(bg=BADGE_EDGE)
        pump([dlg], 150)
        paths.append(_save(shot(), src_dir, "m20_f5_hover.png"))
        dlg.btn_go.configure(bg=INK)
        dlg.btn_no.configure(bg=BADGE_BG)
        pump([dlg], 100)

        # ---- f6/f7 下载进度 38% → 71%（真实 _q("pct") → _poll 消费路径） ----
        for tag, frac in (("f6_pct38", 0.38), ("f7_pct71", 0.71)):
            done = int(round(TOTAL_BYTES * frac))
            dlg._q.put(("pct", done, TOTAL_BYTES))
            want = f"{done / TOTAL_BYTES * 100:.1f}%"
            t0 = time.monotonic()
            while want not in dlg.lbl_prog.cget("text") and time.monotonic() - t0 < 3:
                pump([dlg, root], 50)
            assert want in dlg.lbl_prog.cget("text"), f"{tag} 进度文案未更新"
            dlg.lift()
            pump([dlg], 100)
            paths.append(_save(shot(), src_dir, f"m20_{tag}.png"))
            print(f"{tag}: {dlg.lbl_prog.cget('text')!r}", flush=True)

        dlg.destroy()
        panel.destroy()
        return paths
    finally:
        try:
            app.quit()
        except Exception:                                      # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, updater.check) = orig


def _save(im: Image.Image, d: Path, name: str) -> Path:
    p = d / name
    im.save(p)
    return p


def compose(src_dir: Path, out: Path) -> None:
    names = ["m20_f1_idle", "m20_f2_dot", "m20_f3_tip", "m20_f4_dialog",
             "m20_f5_hover", "m20_f6_pct38", "m20_f7_pct71"]
    ims = []
    for n in names:
        p = src_dir / f"{n}.png"
        if not p.exists():
            raise SystemExit(f"缺帧图 {p}（先不带 --compose-only 跑一次实拍）")
        ims.append(Image.open(p).convert("RGB"))
    w, h = ims[0].size
    assert all(im.size == (w, h) for im in ims), "帧尺寸不一致"
    base = ims[0].quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
    frames = [base] + [im.quantize(palette=base, dither=Image.NONE) for im in ims[1:]]
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=DUR_MS, loop=0, optimize=True, disposal=1)
    size = out.stat().st_size
    print(f"demo.gif: {w}x{h}  {len(frames)} frames  {size:,} bytes"
          f"  ({size / 1048576:.2f} MB)", flush=True)
    assert size < 2 * 1048576, "gif 超 2MB"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose-only", action="store_true",
                    help="跳过实拍，仅用 src/ 现有帧重合成 gif")
    a = ap.parse_args()
    if not a.compose_only:
        capture_frames(SRC_DIR)
    compose(SRC_DIR, GIF_PATH)
    print("OK:", GIF_PATH, flush=True)
