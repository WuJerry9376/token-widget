"""M11b 取证：真实链路（bailian+codex）渲染 codex 双条行，截图特写 + 顶边条带纯净复测。

运行：`python tests\\capture_m11.py`（真实网络：codex 走 local 配置代理 + 真实 token，
等价 main.py --quit-after 40 的真实链路，只是把渲染进程留在本脚本内以便：
① 等 codex 真实回包再截；② 铺纯色背景窗跑 check_note_purity（条带判据需受控背景）；
③ 精确裁剪 codex 行特写）。
- config 只读真实 local\\；state 写盘重定向 tmp，真实 local\\state.json 不动；
- 判据：codex ok 且 windows 含知名窗；文案「5h 窗口 · 已用」「周」+细条+（有券时）券角标；
  purity 四项 0（M3c 锁）；输出 local\\m11_window.png（全景）+ local\\m11_codex_row.png（特写）。
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
from src.ui import ROW_5H, NoteApp, codex_bars, codex_ticket_count, codex_win_caption  # noqa: E402
import main as main_mod                                         # noqa: E402

OUT_FULL = ROOT / "local" / "m14_window.png"
OUT_ROW = ROOT / "local" / "m14_codex_dual.png"
WAIT_SECONDS = 40.0          # 与 --quit-after 40 同预算


def run() -> int:
    cfg = config_mod.load_config()               # 真实 config 只读
    tmp = Path(tempfile.mkdtemp(prefix="m11_cap_"))
    orig = (state_mod.STATE_PATH, state_mod.LOCAL_DIR)
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
        t0 = time.time()
        cx = None
        next_report = 10.0
        while time.time() - t0 < WAIT_SECONDS:
            root.update()
            time.sleep(0.1)
            cx = next((u for u in app.usages if u.provider == "codex" and u.ok), None)
            if time.time() - t0 > next_report:
                next_report += 10.0
                print(f"  [t+{time.time()-t0:3.0f}s] "
                      f"{[(u.provider, u.ok, u.error_code) for u in app.usages]}",
                      flush=True)
            if cx is not None:
                break
        print(f"FINAL usages: {[(u.provider, u.ok, u.error_code) for u in app.usages]}",
              flush=True)
        if cx is None:
            print("FAIL: 未等到 codex 成功回包（行形态无从取证）", flush=True)
            return 1
        main_bar, sec_bar = codex_bars(cx)
        print(f"REAL codex: pct={cx.pct_used} windows={[(w.label, w.pct_used) for w in cx.windows]}"
              f" note={cx.note!r} 主条={main_bar.label if main_bar else None}"
              f" 副条={sec_bar.label if sec_bar else None}"
              f" 券={codex_ticket_count(cx)}", flush=True)
        if main_bar is None:
            print("FAIL: 真实回包无知名窗（5h/周），双条分支未生效", flush=True)
            return 1

        # 纯色背景窗（capture_m3c 同法）→ 置顶渲染 → 全景截图 + 纯净度
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

        x, y, w, h = cap.capture(app.root, OUT_FULL)
        res = cap.check_note_purity(app, x, y, w, h)
        print(f"全景 {OUT_FULL.name} rect=({x},{y},{w}x{h})", flush=True)
        print("PURITY:", res, flush=True)
        ok_p = (res["outside_paper_top"] == 0 and res["strip_above20"] == 0
                and res["outside_paper_all"] == 0 and res["paper_solid_ok"])

        # codex 行特写：末行顶缘（图像坐标）= PAD + 画布高 −（行高+8）·S；上留 26px 语境
        from PIL import Image
        infos = app._row_infos()
        last_h = app._row_h(infos[-1])
        top = int(max(0, cap.PAD + h - (last_h + 8) * app.S - 26))
        img = Image.open(OUT_FULL)
        crop = img.crop((cap.PAD, top, w + cap.PAD, h + cap.PAD))
        crop.save(OUT_ROW)
        print(f"特写 {OUT_ROW.name}: {crop.size}（codex 行高={last_h:.0f} 逻辑px，"
              f"上含 {'百炼' if len(infos) > 1 else '头部'} 语境）", flush=True)

        ts = [str(app.canvas.itemcget(i, "text")) for i in app.canvas.find_all()
              if app.canvas.type(i) == "text"]
        joined = " | ".join(ts)
        ok_txt = ("Codex" in joined and f"{codex_win_caption(main_bar.label)} · 已用" in joined
                  and (sec_bar is None
                       or f"{codex_win_caption(sec_bar.label)} · 已用" in joined))
        ntk = codex_ticket_count(cx)
        ok_txt = ok_txt and ((f"券×{ntk}" in ts) if ntk else
                             not any(t.startswith("券×") for t in ts))
        print(f"TEXT: 主条 label+已用 在={f'{codex_win_caption(main_bar.label)} · 已用' in joined} "
              f"副条={'有' if sec_bar else '无'} 券角标={ntk} rendered_ok={ok_txt}",
              flush=True)
        # 行高对照报数（358 → 新值，全景高）
        print(f"NOTE H: 全窗 {w}x{h}（画布逻辑高 {float(app.canvas.cget('height'))/app.S:.0f}）"
              f" 单行增量对照 ROW_5H={ROW_5H} → 副条 14", flush=True)
        ok = ok_p and ok_txt
        print("M11B CAPTURE:", "PASS" if ok else "FAIL", flush=True)
        code = 0 if ok else 1
    finally:
        try:
            app.quit()
        except Exception:                                     # noqa: BLE001
            pass
        sched.stop()
        (state_mod.STATE_PATH, state_mod.LOCAL_DIR) = orig
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
