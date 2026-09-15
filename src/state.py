"""UI 本地状态：token-widget/local/state.json（窗口位置、置顶开关）。

与 config.json 分离：config=用户意图配置（M3 设置页管理），state=程序自动记忆。
写入失败静默（非关键路径），读取失败回默认。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# frozen 时 local/ 落在 exe 同级（与 config.py 同一策略）
if getattr(sys, "frozen", False):
    LOCAL_DIR = Path(sys.executable).resolve().parent / "local"
else:
    LOCAL_DIR = Path(__file__).resolve().parent.parent / "local"
STATE_PATH = LOCAL_DIR / "state.json"

DEFAULTS: dict = {
    "x": None,                 # 窗口左上角物理像素坐标；None=首次启动自动摆位
    "y": None,
    "always_on_top": None,     # None=跟随 config.always_on_top
}


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            s = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(s, dict):
                return {**DEFAULTS, **s}
        except (ValueError, OSError):
            pass
    return dict(DEFAULTS)


def save_state(x: int | None = None, y: int | None = None,
               always_on_top: bool | None = None) -> None:
    s = load_state()
    if x is not None:
        s["x"] = int(x)
    if y is not None:
        s["y"] = int(y)
    if always_on_top is not None:
        s["always_on_top"] = bool(always_on_top)
    try:
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    except OSError:
        pass
