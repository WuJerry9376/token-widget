"""M18 取证：设置页 foot 行 GitHub 图标 10× 放大截图（含 hover 态）。

运行：`python tests\\capture_m18.py`（桌面会话）。数据真实性：
- config 用真实 local\\config.json 的**只读副本**（update.repo=定仓 slug → 图标显示态）；
- 零网络：updater.check 打桩为 skipped（避免开页触网）；webbrowser.open 打桩（不拉浏览器）；
- 任何写路径（config/state/secret）重定向 temp，✕ 关闭即散。
产物（local\\）：
- m18_ghicon.png：foot 右缘区（图标+版本签名）10× 放大，**上下两段合成**——
  上=常态（FAINT 墨档）、下=hover 态（SOFT 墨档，程序化触发 <Enter> 等价路径）。
自检：①图标 widget 在 lbl_ver 左侧且同行带；②常态段 FAINT 墨迹>15、hover 段
SOFT 墨迹>15 且 FAINT 大减（档切换实证）；③图标宽=高=foot 行高派生（≥12px）。
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
from src.ui import FAINT, SOFT, NoteApp                          # noqa: E402
import main as main_mod                                          # noqa: E402

LOCAL = ROOT / "local"


def rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def ink_count(img, x0, y0, x1, y1, col, tol=70, sum_max=640) -> int:
    n = 0
    f = rgb(col)
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            r, g, b = img.getpixel((xx, yy))[:3]
            if abs(r - f[0]) + abs(g - f[1]) + abs(b - f[2]) < tol and r + g + b < sum_max:
                n += 1
    return n


def main_run(tmp: Path) -> int:
    real_cfg = ROOT / "local" / "config.json"
    seed = real_cfg.read_text(encoding="utf-8") if real_cfg.exists() else "{}"
    cfg_path = tmp / "config.json"
    cfg_path.write_text(seed, encoding="utf-8")
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check)
    config_mod.CONFIG_PATH = cfg_path
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp
    auth.BAILIAN_COOKIE_FILE = orig[4]                  # 只探测存在性，不读值
    updater.check = lambda cfg, force=False, **kw: updater.CheckResult(skipped=True)
    cfg = config_mod.load_config()
    assert updater.parse_repo(cfg["update"].get("repo")), "真实 config 应含定仓 slug（图标显示态）"

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    app = NoteApp(root, cfg, Scheduler([], poll_seconds=cfg.get("poll_seconds", 300)),
                  state=dict(DEFAULTS))
    ok = True
    try:
        from src import settings_panel
        panel = settings_panel.SettingsPanel(app)
        t0 = time.monotonic()
        while not panel.winfo_ismapped() and time.monotonic() - t0 < 3:
            app.root.update()
            panel.update()
            time.sleep(0.02)
        time.sleep(0.4)
        panel.update()
        app.root.update()

        gh, lv = panel.lbl_gh, panel.lbl_ver
        gx, gy = gh.winfo_rootx(), gh.winfo_rooty()
        gw, gh_h = gh.winfo_width(), gh.winfo_height()
        lx = lv.winfo_rootx()
        # ③ 几何：方图、行高派生 ≥12px；① 图标在签名左侧、同一行带
        ok &= gh_h >= 12 and gw == gh_h == panel._gh_px
        ok &= gx < lx and abs((gy + gh_h / 2) - (lv.winfo_rooty() + lv.winfo_height() / 2)) < 6
        # 截取样区：图标+间距+版本签名整块（含左右上下文）
        sx0, sy0 = gx - 6, gy - 4
        sx1, sy1 = lv.winfo_rootx() + lv.winfo_width() + 6, gy + gh_h + 4
        w, h = sx1 - sx0, sy1 - sy0
        shot_a = cap.grab(sx0, sy0, w, h)               # 常态 FAINT
        panel._gh_enter()                               # hover 档（<Enter> 等价路径）
        panel.update()
        time.sleep(0.15)
        shot_b = cap.grab(sx0, sy0, w, h)               # hover SOFT
        panel._gh_leave()
        # ② 像素：图标框内墨迹档切换实证（ix0..ix1 = 图标区，取样图内坐标 +6/-4 偏移）
        ix0, ix1 = 6, 6 + gw
        iy0, iy1 = 4, 4 + gh_h
        faint_a = ink_count(shot_a, ix0, iy0, ix1, iy1, FAINT)
        soft_a = ink_count(shot_a, ix0, iy0, ix1, iy1, SOFT, tol=40)
        soft_b = ink_count(shot_b, ix0, iy0, ix1, iy1, SOFT, tol=40)
        faint_b = ink_count(shot_b, ix0, iy0, ix1, iy1, FAINT)
        print(f"icon {gw}x{gh_h}px  foot px={panel._gh_px}  left_of_ver={gx < lx}", flush=True)
        print(f"常态段 FAINT墨={faint_a} SOFT墨={soft_a}   "
              f"hover段 SOFT墨={soft_b} FAINT墨={faint_b}", flush=True)
        ok &= faint_a > 15 and soft_b > 15 and soft_b > faint_b
        # 合成 10× 放大上下两态（2px 黑分隔线）
        zs = 10
        za, zb = shot_a.resize((w * zs, h * zs), Image.NEAREST), \
            shot_b.resize((w * zs, h * zs), Image.NEAREST)
        comp = Image.new("RGB", (w * zs + 2, h * zs * 2 + 3), (0, 0, 0))
        comp.paste(za, (1, 1))
        comp.paste(zb, (1, h * zs + 2))
        d = ImageDraw.Draw(comp)
        d.rectangle((1, 1, 6 + zs, 6 + zs), outline=(255, 0, 0))     # 红框标注图标位（上段=常态）
        d.rectangle((1, h * zs + 2, 6 + zs, h * zs + 2 + 6 + zs), outline=(255, 140, 0))
        comp.save(LOCAL / "m18_ghicon.png")
        print(f"saved local\\m18_ghicon.png（上=常态 FAINT，下=hover SOFT，10×；红/橙框=图标位）",
              flush=True)
        app.root.withdraw()
        print("M18 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                       # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE, updater.check) = orig


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m18_cap_") as d:
        raise SystemExit(main_run(Path(d)))
