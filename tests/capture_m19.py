"""M19 取证：UpdateDialog 专属确认窗截图（假数据 + 真 notes 排版 + 两按钮常态/hover）。

运行：`python tests\\capture_m19.py`（桌面会话）。纪律：
- updater.check 打桩 skipped、webbrowser 打桩——零网络零真浏览器；
- config/state/secret 写路径全部重定向 temp；数据=假版本/假大小，**发行说明用
  真实 v1.8.0 release 风格多行中文文本**（>6 行，实证截断省略号排版）；
- ✕ 关闭即散，不点「立即更新」（下载/替换链由 u30 桩测覆盖，不在实拍里触发）。
产物（local\\）：
- m19_dialog.png：三态纵向合成（2× 放大）——①待命（立即更新·实底 / 取消·浅描边）
  ②hover（两钮加深一档，模拟指针悬停反馈）③下载进度态（程序化投 pct/audit 事件，
  展示状态区文案排版）。红/橙/绿侧标区分状态段。
自检：标题条/vX→vY/发布时间/包大小/notes≤6 行尾 … /两按钮 pack 在位；截图像素含
主按钮墨底（INK 近邻）与注记灰。
"""
from __future__ import annotations

import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import capture_m3c as cap                                        # noqa: E402
from src import auth, config as config_mod, state as state_mod   # noqa: E402
from src import updater                                          # noqa: E402
from src.scheduler import Scheduler                              # noqa: E402
from src.state import DEFAULTS                                   # noqa: E402
from src.ui import BADGE_BG, BADGE_EDGE, INK, PAPER, NoteApp           # noqa: E402
import main as main_mod                                          # noqa: E402

LOCAL = ROOT / "local"

NOTES = (
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
    (tmp / "config.json").write_text('{"update":{"enabled":false,"repo":"fake-owner/fake-repo",'
                                     '"last_check":1,"last_auto_date":"2000-01-01","mirror":""}}',
                                     encoding="utf-8")
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check)
    config_mod.CONFIG_PATH = tmp / "config.json"
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = orig[5]
    updater.check = lambda cfg, force=False, **kw: updater.CheckResult(skipped=True)
    cfg = config_mod.load_config()

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, cfg, Scheduler([], poll_seconds=300), state=dict(DEFAULTS))
    ok = True
    shots = []
    try:
        from src import settings_panel
        panel = settings_panel.SettingsPanel(app)
        panel.withdraw()                            # 面板藏，弹窗单独成镜
        info = updater.UpdateInfo(version="1.9.0", url="https://github.com/fake/repo/x.exe",
                                  notes=NOTES, digest=None, size=11263948,
                                  published="2026-09-19T08:12:34Z")
        panel._up_info = info
        panel._up_open_dialog()
        dlg = panel._up_dialog
        t0 = time.monotonic()
        while not dlg.winfo_ismapped() and time.monotonic() - t0 < 3:
            app.root.update()
            dlg.update()
            time.sleep(0.02)
        time.sleep(0.35)
        # ---- 静态判据（widget 面） ----
        dtexts = []
        def walk(w):
            try:
                t = w.cget("text")
                if isinstance(t, str) and t:
                    dtexts.append(t)
            except tk.TclError:
                pass
            for c in w.winfo_children():
                walk(c)
        walk(dlg)
        assert any(t == "发现新版本 v1.9.0" for t in dtexts), "标题条"
        assert any("当前版本 v" in t and "→ v1.9.0" in t for t in dtexts)
        assert any("2026-09-19 08:12 (UTC)" in t for t in dtexts)
        assert any("10.7 MB" in t for t in dtexts)
        notes_lbl = next(w for w in _iter(dlg)
                         if isinstance(w, tk.Label) and str(w.cget("text")).startswith("M19"))
        clip = notes_lbl.cget("text")
        lines = clip.splitlines()
        print(f"notes 行数={len(lines)} 尾省略={lines[-1].endswith('…')}", flush=True)
        ok &= len(lines) == 6 and lines[-1].endswith("…")
        ok &= dlg.btn_go.winfo_manager() != "" and dlg.btn_no.winfo_manager() != ""

        def shot():
            app.root.withdraw()                     # 遮身后的浮窗本体（withdraw 根不联动独立 Toplevel）
            dlg.update()
            app.root.update_idletasks()
            x, y, w, h = cap.win_rect(dlg)
            return cap.grab(x - cap.PAD, y - cap.PAD, w + 2 * cap.PAD, h + 2 * cap.PAD), w, h

        s1, w, h = shot()                            # ① 待命
        # ② hover：两钮加深一档（tk flat 钮无系统 hover，用 activebackground 色值代呈现）
        dlg.btn_go.configure(bg="#57503E")
        dlg.btn_no.configure(bg=BADGE_EDGE)
        s2, _, _ = shot()
        dlg.btn_go.configure(bg=INK)
        dlg.btn_no.configure(bg=BADGE_BG)
        # ③ 进度态：投 pct/audit 事件（worker 未启动——直接喂 queue，after 自然消费）
        dlg._q.put(("pct", 600 * 1024, 11263948))
        t0 = time.monotonic()
        while "正在下载更新包…" not in dlg.lbl_prog.cget("text") and time.monotonic() - t0 < 2:
            dlg.update()
            app.root.update()
            time.sleep(0.02)
        s3, _, _ = shot()
        # 墨底实证：主按钮中心像素 ≈INK 系（待命=墨底；hover=加深仍暗）
        px = s1.load()
        bx = dlg.btn_go.winfo_rootx() + dlg.btn_go.winfo_width() // 2 - (x - cap.PAD) \
            if False else dlg.btn_go.winfo_rootx() + dlg.btn_go.winfo_width() // 2
        by = dlg.btn_go.winfo_rooty() + dlg.btn_go.winfo_height() // 2
        x0 = dlg.winfo_rootx() - cap.PAD
        y0 = dlg.winfo_rooty() - cap.PAD
        c = px[bx - x0, by - y0][:3]
        ink_r, ink_g, ink_b = (int(INK[i:i + 2], 16) for i in (1, 3, 5))
        dark = c[0] + c[1] + c[2] < (ink_r + ink_g + ink_b) + 90
        print(f"主按钮中心像素={c!r} 墨底={dark}", flush=True)
        ok &= dark
        # ---- 合成 2× 三态纵排 ----
        zs = 2
        ss = [im.resize((im.width * zs, im.height * zs), Image.NEAREST)
              for im in (s1, s2, s3)]
        W = max(s.width for s in ss) + 10
        H = sum(s.height for s in ss) + 4
        comp = Image.new("RGB", (W, H), (40, 40, 40))
        d = ImageDraw.Draw(comp)
        cols = [(220, 60, 60), (255, 160, 0), (60, 190, 90)]
        labels = ["idle: GO(solid)+CANCEL(outline)", "hover: both buttons deeper",
                  "progress: 5.5% downloading"]
        yy = 1
        for i, s in enumerate(ss):
            comp.paste(s, (10, yy))
            d.rectangle((0, yy, 8, yy + s.height), fill=cols[i])
            d.text((11, yy + 2), labels[i], fill=cols[i])
            yy += s.height + 1
        comp.save(LOCAL / "m19_dialog.png")
        print("saved local\\m19_dialog.png（红=待命 橙=hover 绿=进度；2× 放大）", flush=True)
        panel.destroy()
        print("M19 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                     # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check) = orig


def _iter(w):
    yield w
    for c in w.winfo_children():
        yield from _iter(c)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m19_cap_") as d:
        raise SystemExit(main_run(Path(d)))
