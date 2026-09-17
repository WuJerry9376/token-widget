"""M20-A：GitHub 门面截图墙（dev-only，允许 PIL）。

运行：`python tests\\capture_m20.py`（桌面会话）→ 产物直接落 docs\\screenshots\\：
- feature_note.png      主浮窗正常态（假数据注入渲染层：39,375 系示例数值）
- feature_dualbar.png   Codex 双主条特写（M14）
- feature_snap.png      贴边吸附终态（右缘贴齐工作区）
- feature_settings.png  设置页全组（代理/更新可见，演示态注入）
- feature_dialog.png    更新弹窗（v1.8.1→v1.9.0 示例值 + 真实发行说明排版 ≤6 行截断）

纪律同 capture 系列：零网络（updater.check 打桩 skipped）、config/state/auth 写盘
重定向 temp、src/ 产品代码零改动。刻度：tk scaling 锁 150% 等效（与 demo.gif 同
口径），帧 1:1 无重采样。透明色键区域用纯色 PAPER 背景窗垫底（纸形外=纸色）。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

import capture_m3c as cap                                         # noqa: E402
from src import auth, config as config_mod, state as state_mod    # noqa: E402
from src import updater                                           # noqa: E402
from src.scheduler import Scheduler                               # noqa: E402
from src.state import DEFAULTS                                    # noqa: E402
from src.ui import SNAP_PX, NoteApp, PAPER, snap_target, work_area  # noqa: E402
import main as main_mod                                           # noqa: E402

import make_gif as mg                                             # noqa: E402  复用演示数据构造

OUT = ROOT / "docs" / "screenshots"
PAD = 24

# 发行说明：真实 v1.8.x release 风格多行中文（>6 行 → 实证截断省略号排版）
NOTES_LONG = (
    "M19 发现新版改为专属弹窗确认，内联按钮退役。\r\n"
    "• 设置页 foot 新增 GitHub 剪影图标：点击一键打开仓库页（零 API/零凭据）。\n"
    "• 更新链加入镜像备用源：直连 → 代理 → 镜像三级回退，成功通道在状态行标注。\n"
    "• SHA-256 完整性校验：信任锚=GitHub 官方 API 的 asset.digest；镜像腿缺哈希直接拒收。\n"
    "• 版本信息（检查/哈希）始终只走官方 API，镜像永不参与元数据。\n"
    "• 修复：1.7.1 反馈「发现新版后没有可确认更新的按钮」——现在发现即弹专属确认窗，\n"
    "  展示当前版本→新版本、发布时间、包大小与发行说明，一键立即更新或取消。\n"
    "• 下载进度每 512KB 刷新一次百分比；失败给橙字原因与重试/关闭；目录不可写时提权更新。"
)


def main_run(tmp: Path) -> int:
    (tmp / "config.json").write_text("{}", encoding="utf-8")
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
    root.tk.call("tk", "scaling", mg.SCALE_FACTOR * 96.0 / 72.0)
    cfg = dict(mg.CFG)
    cfg["update"] = dict(mg.CFG["update"])
    app = NoteApp(root, cfg, Scheduler([], poll_seconds=300), state=dict(DEFAULTS))
    ok = True
    saved: list[Path] = []
    try:
        # 纯色 PAPER 背景窗：纸形之外=纸色（“去桌面杂影”）
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        bg.configure(bg=PAPER)
        bg.lift()
        root.update()
        time.sleep(0.4)

        # 假数据注入渲染层（与真数据同路径：usages → _render）
        app.usages = [mg.u_bailian(), mg.u_codex()]
        app.meta = {"next_delay": 300, "ts": time.time(), "low": False}
        app.last_good = {"bailian": app.usages[0], "codex": app.usages[1]}
        app._render()
        app._pos = (120, 60)
        root.geometry(f"+{app._pos[0]}+{app._pos[1]}")
        mg.pump([root], 400)
        root.lift()
        mg.pump([root], 250)

        ts = [str(app.canvas.itemcget(i, "text"))
              for i in app.canvas.find_all() if app.canvas.type(i) == "text"]
        ok &= any(t == "39,375" for t in ts)                 # 主数值实证
        print("大数字 39,375 在位:", ok, flush=True)

        # ---- 1) feature_note.png：主浮窗正常态（精确窗口矩形） ----
        x, y, w, h = cap.win_rect(app.root)
        cap.grab(x, y, w, h).save(OUT / "feature_note.png")
        saved.append(OUT / "feature_note.png")

        # ---- 2) feature_dualbar.png：Codex 双主条行特写（hits 热区即行矩形） ----
        row = next(hh for hh in app.hits
                   if hh[4].get("u") is not None
                   and getattr(hh[4]["u"], "provider", "") == "codex")
        rx0, ry0, rx1, ry1 = row[0], row[1], row[2], row[3]
        cap.grab(x + int(rx0), y + int(ry0) - 8,
                 int(rx1 - rx0), int(ry1 - ry0) + 10).save(OUT / "feature_dualbar.png")
        saved.append(OUT / "feature_dualbar.png")

        # ---- 3) feature_snap.png：右缘吸附终态（snap_target 真算，非手摆） ----
        l, t, r, b = work_area()
        pre = (r - w - 6, 140)                               # 释放位：距右缘 6px ≤ SNAP_PX
        tgt = snap_target(pre, (w, h), [(l, t, r, b)], SNAP_PX * app.S)
        assert tgt is not None and tgt[0] == r - w, f"右缘吸附未命中：{tgt}"
        app._pos = tgt
        root.geometry(f"+{tgt[0]}+{tgt[1]}")
        mg.pump([root], 350)
        root.lift()
        mg.pump([root], 150)
        x2, y2, w2, h2 = cap.win_rect(app.root)
        grab_w = min(r, x2 + w2 + 6) - (x2 - PAD)            # 右侧不过工作区边缘
        cap.grab(x2 - PAD, y2 - PAD, grab_w, h2 + 2 * PAD).save(OUT / "feature_snap.png")
        saved.append(OUT / "feature_snap.png")
        print(f"snap: note=({x2},{y2}) {w2}x{h2}  工作区右缘={r}  间隙={r - (x2 + w2)}",
              flush=True)
        ok &= (x2 + w2) == r

        # ---- 4) feature_settings.png：设置页全组（代理/更新演示态） ----
        app._pos = (120, 60)
        root.geometry(f"+{app._pos[0]}+{app._pos[1]}")
        mg.pump([root], 150)
        app.cfg["network"] = {"proxy_enabled": True, "proxy_url": "127.0.0.1:7890",
                              "proxy_targets": ["openai", "opencode_go"]}
        app.open_settings()
        panel = app._settings
        assert panel is not None, "设置面板未打开"
        assert mg.wait_mapped(panel), "设置面板未映射"
        mg.pump([panel, root], 500)
        panel.lift()
        mg.pump([panel], 200)
        px, py, pw, ph = cap.win_rect(panel)
        cap.grab(px, py, pw, ph).save(OUT / "feature_settings.png")
        saved.append(OUT / "feature_settings.png")
        print(f"settings: {pw}x{ph}", flush=True)

        # ---- 5) feature_dialog.png：更新弹窗（长 notes 实证 ≤6 行 + …） ----
        info = updater.UpdateInfo(version="1.9.0",
                                  url="https://github.com/fake/repo/x.exe",
                                  notes=NOTES_LONG, digest=None, size=11263948,
                                  published="2026-09-19T08:12:34Z")
        panel.withdraw()                                     # 面板藏，弹窗单独成镜（同 m19）
        panel._up_info = info
        panel._up_open_dialog()
        dlg = panel._up_dialog
        assert dlg is not None, "UpdateDialog 未创建"
        assert mg.wait_mapped(dlg), "弹窗未映射"
        mg.pump([dlg, root], 400)
        texts: list[str] = []

        def walk(wd):
            try:
                tx = wd.cget("text")
                if isinstance(tx, str) and tx:
                    texts.append(tx)
            except tk.TclError:
                pass
            for c in wd.winfo_children():
                walk(c)
        walk(dlg)
        nline = next((tx for tx in texts if tx.startswith("M19")), "")
        lines = nline.splitlines()
        ok &= len(lines) == 6 and lines[-1].endswith("…")
        ok &= any("v1.8.1" in tx and "→ v1.9.0" in tx for tx in texts)
        print(f"notes 行数={len(lines)} 尾省略={lines[-1].endswith('…')}", flush=True)
        dlg.lift()
        mg.pump([dlg], 150)
        dx, dy, dw, dh = cap.win_rect(dlg)
        cap.grab(dx - 6, dy - 6, dw + 12, dh + 12).save(OUT / "feature_dialog.png")
        saved.append(OUT / "feature_dialog.png")
        print(f"dialog: {dw}x{dh}", flush=True)
        dlg.destroy()
        panel.close_card()

        for p in saved:
            print(f"saved {p.relative_to(ROOT)}  {p.stat().st_size:,} bytes", flush=True)
        print("M20 WALL:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                      # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, updater.check) = orig


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m20_wall_") as d:
        raise SystemExit(main_run(Path(d)))
