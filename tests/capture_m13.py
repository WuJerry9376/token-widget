"""M13 取证：设置页右下角版本签名截图（真实数据）。

运行：`python tests\\capture_m13.py`（桌面会话）。数据真实性：
- config 用真实 local\\config.json 的**只读副本**渲染（供应商勾选/代理回显=现状）；
- 凭据探测走真实只读路径（百炼 cookie 存在性、Go/Codex 自动检测），旁注真实；
- 任何写路径（config/state/secret）重定向 temp，零网络，✕ 关闭即散。
产物（local\\）：
- m13_settings_footer.png：设置页全幅，右下「改动即时生效并保存 …… v1.6.4 · by Jerry Wu」。
自检：①签名 Label 右缘贴 body 右缘（侧隙=16px 纸框内边距）；②底行基线不高于状态行；
③隐藏 lbl_ver 前后 reqheight 相等（面板高度零增长，报实值）；④截图像素中 FAINT 墨迹>30。
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

import capture_m3c as cap                                        # noqa: E402
from src import auth, config as config_mod, state as state_mod   # noqa: E402
from src import version as version_mod                           # noqa: E402
from src.scheduler import Scheduler                              # noqa: E402
from src.state import DEFAULTS                                   # noqa: E402
from src.ui import FAINT, NoteApp                                # noqa: E402
import main as main_mod                                          # noqa: E402

LOCAL = ROOT / "local"


def rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def main_run(tmp: Path) -> int:
    # 真实 config 只读副本 → tmp；写路径全部离开真实 local\
    real_cfg = ROOT / "local" / "config.json"
    seed = real_cfg.read_text(encoding="utf-8") if real_cfg.exists() else "{}"
    cfg_path = tmp / "config.json"
    cfg_path.write_text(seed, encoding="utf-8")
    orig = (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
            state_mod.STATE_PATH, state_mod.LOCAL_DIR,
            auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE)
    config_mod.CONFIG_PATH = cfg_path
    config_mod.LOCAL_DIR = tmp
    state_mod.STATE_PATH = tmp / "state.json"
    state_mod.LOCAL_DIR = tmp
    auth.LOCAL_DIR = tmp                       # 绝不可能把 secret 写进真实 local\
    auth.BAILIAN_COOKIE_FILE = orig[5]         # 旁注真实性：只探测存在性，不读值
    cfg = config_mod.load_config()

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

        # ③ 高度零增长实证：藏/显 lbl_ver 前后 reqheight 必须相等
        h_with = panel.winfo_reqheight()
        w_with = panel.winfo_reqwidth()
        panel.lbl_ver.pack_forget()
        panel.update_idletasks()
        h_wo = panel.winfo_reqheight()
        panel.lbl_ver.pack(side="right")
        panel.update()                                  # 完整渲染周期，布局尺寸才可信
        app.root.update()
        dh = h_with - h_wo
        print(f"req {w_with}x{h_with}  藏签名后高 {h_wo}  Δ高度={dh:+d}px", flush=True)
        ok &= dh == 0

        x, y, w, h = cap.capture(panel, LOCAL / "m13_settings_footer.png")
        # ①② 几何：签名右缘 / 底缘相对窗口（capture 含 PAD 画框，widget 坐标按窗口原点折算）
        t0 = time.monotonic()
        while panel.lbl_ver.winfo_width() <= 1 and time.monotonic() - t0 < 2:
            panel.update()
            time.sleep(0.02)
        lx = panel.lbl_ver.winfo_rootx() - x
        ly = panel.lbl_ver.winfo_rooty() - y
        lw, lh = panel.lbl_ver.winfo_width(), panel.lbl_ver.winfo_height()
        gap_r = w - (lx + lw)
        gap_b = h - (ly + lh)
        print(f"footer rect=({x},{y}) {w}x{h}  lbl_ver=({lx},{ly},{lw}x{lh}) "
              f"右隙={gap_r} 下隙={gap_b}", flush=True)
        ok &= 10 <= gap_r <= 22 and 6 <= gap_b <= 20
        # ④ 像素实证：签名区域内 FAINT 墨迹（距 FAINT<60 且明显离开纸色）
        img = cap.grab(x - cap.PAD, y - cap.PAD, w + 2 * cap.PAD, h + 2 * cap.PAD)
        f = rgb(FAINT)
        ink = 0
        for yy in range(ly + cap.PAD, ly + lh + cap.PAD):
            for xx in range(lx + cap.PAD, lx + lw + cap.PAD):
                r, g, b = img.getpixel((xx, yy))[:3]
                if abs(r - f[0]) + abs(g - f[1]) + abs(b - f[2]) < 90 and r + g + b < 640:
                    ink += 1
        print(f"FAINT 墨像素={ink}  文本={panel.lbl_ver.cget('text')!r}", flush=True)
        ok &= ink > 30
        assert panel.lbl_ver.cget("text") == f"v{version_mod.APP_VERSION} · by Jerry Wu"
        app.root.withdraw()
        print("M13 CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        return 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                       # noqa: BLE001
            pass
        (config_mod.CONFIG_PATH, config_mod.LOCAL_DIR,
         state_mod.STATE_PATH, state_mod.LOCAL_DIR,
         auth.LOCAL_DIR, auth.BAILIAN_COOKIE_FILE) = orig


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="m13_cap_") as d:
        raise SystemExit(main_run(Path(d)))
