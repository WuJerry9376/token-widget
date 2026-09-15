"""M9b 取证：真实拉取 usd「余额未知但采集正常」态，截图 + 顶边纯净度。

运行：`python tests\\capture_m9b.py`（真实网络：openai org/costs 走 local 配置
的代理 + 真实 Admin key，实测 used=$0.00、无预算无 grants → remaining=None；
bailian 凭据状态如实呈现，非本案判据）。

- 等待条件：app.usages 中出现 openai ok 行（capture_m3c --real 首包即截，会被
  bailian 的缓存快速失败抢跑，故单独等 openai 真实回包，上限 150s）；
- 复用 capture_m3c 的纯色背景窗与 check_note_purity（顶边外条带判据同源）；
- 证据：local\\m9b_usd_zero.png；config/state 写盘重定向 tmp，真实 local\\ 不动。
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

import capture_m3c as cap                                       # noqa: E402
from src import config as config_mod, state as state_mod        # noqa: E402
from src.registry import active_sources                         # noqa: E402
from src.scheduler import Scheduler                             # noqa: E402
from src.state import DEFAULTS                                  # noqa: E402
from src.ui import NoteApp, breakdown_display, usd_used_mode    # noqa: E402
import main as main_mod                                         # noqa: E402

OUT = ROOT / "local" / "m9b_usd_zero.png"


def run() -> int:
    # 真实配置必须先读（openai 启用 + 代理作用域都在其中；本流程只读不写 config）；
    # state 写盘（退出保存位置）重定向 tmp，真实 local\state.json 不动。
    cfg = config_mod.load_config()
    tmp = Path(tempfile.mkdtemp(prefix="m9b_cap_"))
    orig = (config_mod.CONFIG_PATH, state_mod.STATE_PATH, state_mod.LOCAL_DIR)
    state_mod.STATE_PATH = tmp / "state.json"

    main_mod.enable_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    sched = Scheduler(active_sources(cfg), poll_seconds=cfg["poll_seconds"],
                      low_yellow_pct=cfg["low_yellow_pct"])
    app = NoteApp(root, cfg, sched, state=dict(DEFAULTS))
    code = 1
    try:
        sched.start()
        # 等待 openai 真实成功回包（used 有值 → M9b 分支生效）
        t0 = time.time()
        oai = None
        next_report = 15.0
        while time.time() - t0 < 150:
            root.update()
            time.sleep(0.1)
            oai = next((u for u in app.usages
                        if u.provider == "openai" and u.ok), None)
            if time.time() - t0 > next_report:
                next_report += 15.0
                print(f"  [t+{time.time()-t0:3.0f}s] usages="
                      f"{[(u.provider, u.ok, u.error_code, u.used) for u in app.usages]}",
                      flush=True)
            if oai is not None and oai.used is not None:
                break
        print(f"FINAL usages: {[(u.provider, u.ok, u.error_code, u.used) for u in app.usages]}",
              flush=True)
        if oai is None:
            print("FAIL: 未等到 openai 成功回包", flush=True)
            return 1
        print(f"REAL openai: used={oai.used} remaining={oai.remaining} "
              f"total={oai.total} used_mode={usd_used_mode(oai)} "
              f"display={breakdown_display(oai)}", flush=True)

        # 纯色背景窗（与 capture_m3c 同法）→ 置顶渲染 → 截图 + 纯净度
        bg = tk.Toplevel(root)
        bg.overrideredirect(True)
        bg.attributes("-topmost", True)
        bg.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        bg.configure(bg=cap.BG_COLOR)
        bg.lift()
        root.update()
        time.sleep(0.45)
        root.lift()
        root.update()
        time.sleep(0.45)

        x, y, w, h = cap.capture(app.root, OUT)
        res = cap.check_note_purity(app, x, y, w, h)
        print(f"截图 {OUT}  rect=({x},{y},{w},{h})", flush=True)
        print("PURITY:", res, flush=True)
        ok = (res["outside_paper_top"] == 0 and res["strip_above20"] == 0
              and res["outside_paper_all"] == 0 and res["paper_solid_ok"])
        # 文案实渲染核对（canvas 文本项与纯函数同源）
        ts = [str(app.canvas.itemcget(i, "text")) for i in app.canvas.find_all()
              if app.canvas.type(i) == "text"]
        joined = "".join(ts)
        disp_big, disp_left = breakdown_display(oai)
        txt_ok = disp_big in joined and "近30天已用" in joined \
            and (disp_left is None or disp_left in joined)
        print(f"TEXT: big={disp_big!r} unit_label=近30天已用 "
              f"left={disp_left!r} rendered={txt_ok}", flush=True)
        ok = ok and txt_ok
        print("M9B CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        code = 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                    # noqa: BLE001
            pass
        sched.stop()
        config_mod.CONFIG_PATH, state_mod.STATE_PATH, state_mod.LOCAL_DIR = orig
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
