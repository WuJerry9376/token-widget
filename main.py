"""token-widget M2 浮窗入口。

用法：
    python main.py                      # 正常启动（周期按 local/config.json）
    python main.py --poll 90            # 临时覆盖轮询周期（调试用，不写配置）
    python main.py --quit-after N       # N 秒后干净退出（保存位置；验证用）
    python main.py --print-geometry     # 窗口尺寸变化时打印几何（截图定位用）
    python main.py --open-settings      # 启动后即开设置面板（调试/截图）
    python main.py --autostart-dry-run  # 打印将写入的自启注册表值，不写注册表
    python main.py --verbose            # stdout 输出每轮采集摘要（不含凭据）

DPI：在创建 Tk 窗口前用 ctypes 设进程 awareness（M26 起优先 PER_MONITOR_AWARE_V2，
失败逐级回退 PM→system→经典 API；全部失败也不崩，行为=改造前）。
"""
from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def protect_std_streams() -> None:
    """windowed（noconsole）exe 下 sys.stdout/stderr 可能为 None，print() 会抛
    AttributeError。统一替换为 devnull 写入流（仅防护，不改任何业务逻辑/参数语义；
    console 构建下 stdout 非 None，本函数为 no-op）。"""
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name,
                        open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except OSError:
                class _NullWriter:
                    def write(self, *_a): return 0
                    def flush(self): pass
                    def isatty(self): return False
                setattr(sys, name, _NullWriter())


def enable_dpi_awareness() -> str:
    """M26 PMv2 优先感知链（必须在 Tk() 前调用；返回生效档位供诊断/测试取证）。

    层级：PER_MONITOR_AWARE_V2(ctx=-4, Win10 1703+) → shcore PER_MONITOR(2)
    → shcore SYSTEM(1) → user32.SetProcessDPIAware（经典 system）→ unaware。
    每级失败（老系统无该 API / awareness 已被设定）都安静落到下一级或结束，
    绝不抛异常阻塞启动。重复调用（dev 脚本/测试二次进入）第二次起返回 None 档
    也说明进程 awareness 已由首调用决定。"""
    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "pmv2"
    except (OSError, AttributeError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:   # PER_MONITOR
            return "pm"
    except (OSError, AttributeError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:   # SYSTEM
            return "system"
    except (OSError, AttributeError):
        pass
    try:
        user32.SetProcessDPIAware()
        return "system-legacy"
    except (OSError, AttributeError):
        return "unaware"


def main(argv: list[str] | None = None) -> int:
    protect_std_streams()
    ap = argparse.ArgumentParser(description="token-widget 桌面便笺浮窗")
    ap.add_argument("--poll", type=int, default=None, help="覆盖轮询秒数（调试）")
    ap.add_argument("--quit-after", type=float, default=None, help="N 秒后退出并保存位置")
    ap.add_argument("--print-geometry", action="store_true", help="尺寸变化时打印几何")
    ap.add_argument("--verbose", action="store_true", help="打印每轮采集摘要")
    ap.add_argument("--open-settings", action="store_true",
                    help="启动后即打开设置面板（调试/截图）")
    ap.add_argument("--open-credentials", action="store_true",
                    help="启动后即打开凭据续期面板（调试）")
    ap.add_argument("--autostart-dry-run", action="store_true",
                    help="打印将写入 HKCU Run 的 token-widget 值后退出，不做任何写操作")
    args = ap.parse_args(argv)

    from src import autostart as autostart_mod
    if args.autostart_dry_run:
        print(autostart_mod.dry_run_report(), flush=True)
        return 0

    from src.config import load_config, POLL_MIN_SECONDS
    from src.registry import active_sources
    from src.scheduler import Scheduler
    from src.state import load_state
    from src.ui import NoteApp

    cfg = load_config()
    if args.poll:
        cfg["poll_seconds"] = max(POLL_MIN_SECONDS, args.poll)

    dpi_mode = enable_dpi_awareness()
    if args.verbose:
        print(f"[main] DPI awareness = {dpi_mode}", flush=True)
    import tkinter as tk
    root = tk.Tk()

    sources = active_sources(cfg)
    sched = Scheduler(sources, poll_seconds=cfg["poll_seconds"],
                      low_yellow_pct=cfg["low_yellow_pct"])
    app = NoteApp(root, cfg, sched, state=load_state(),
                  verbose=args.verbose, print_geometry=args.print_geometry)
    sched.start()
    if args.open_settings:
        root.after(600, app.open_settings)
    if args.open_credentials:
        root.after(600, app.open_credentials)
    if args.quit_after:
        root.after(int(args.quit_after * 1000), app.quit)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
