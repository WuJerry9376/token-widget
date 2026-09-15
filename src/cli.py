"""M1 采集层 CLI：加载配置 → 遍历 active sources → 打印对齐表格。

用法：`python cli.py`（项目根兼容入口）或 `python -m src.cli`。
"""
from __future__ import annotations

import io
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # 直接以脚本运行时补包上下文
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "src"

from .config import load_config
from .registry import active_sources
from .sources.base import Usage


# ---- CJK 宽度感知对齐 ----
def _dwidth(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W") else 1 for c in s)


def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _dwidth(s))


def _fmt_num(v) -> str:
    return "—" if v is None else f"{v:,.0f}"


def _fmt_val(v, unit: str) -> str:
    """M6：表格同步两 unit 渲染（usd 两位小数带 $；其余千分位整数）。"""
    if v is None:
        return "—"
    return f"${v:,.2f}" if unit == "usd" else f"{v:,.0f}"


def _fmt_pct(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def _fmt_countdown(dt) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (dt - datetime.now(timezone.utc)).total_seconds()
    if secs <= 0:
        return "已到期"
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"


def _row(u: Usage) -> list[str]:
    if not u.ok:
        return [u.provider, "—", "—", "—", "—", "—", f"{u.error_code or 'ERROR'}"]
    status = "GREEN"
    if u.addon_remaining is not None:
        if u.provider == "codex":     # M10 实验性：codex 复用位=积分余额（USD），非加油包
            status += f" · credits ${u.addon_remaining:,.2f}"
        else:
            status += f" · addon {_fmt_num(u.addon_remaining)}"
    if u.windows:
        status += " · " + "/".join(w.label for w in u.windows)
    if u.unit == "percent":   # 无绝对额语义：剩余=主窗剩余占比，总量=100%
        rem = "—" if u.pct_used is None else f"{(1 - u.pct_used) * 100:.0f}%"
        tot = "100%"
    else:
        rem = _fmt_val(u.remaining, u.unit)
        tot = _fmt_val(u.total, u.unit)
    return [u.provider, u.spec or "—", rem, tot,
            _fmt_pct(u.pct_used), _fmt_countdown(u.resets_at), status]


_HEADERS = ["供应商", "档位", "剩余", "总量", "已用%", "重置倒计时", "状态"]


def main() -> int:
    _out = sys.stdout
    if isinstance(_out, io.TextIOWrapper):  # Windows 控制台编码兜底
        _out.reconfigure(encoding="utf-8", errors="replace")
    cfg = load_config()
    sources = active_sources(cfg)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== Token 用量采集（poll={cfg['poll_seconds']}s · 本地时间 {now}）===")
    if not sources:
        print("（enabled_providers 为空，无启用的供应商）")
        return 0

    rows, total_credits, any_err = [], 0.0, False
    for src in sources:
        try:
            u = src.fetch()
        except Exception as e:  # source 契约是返回 Usage，兜底防崩
            from .sources.base import Usage as _U
            u = _U(provider=src.name, ok=False, error_code="SOURCE_EXCEPTION",
                   error_msg=str(e)[:200])
        rows.append(_row(u))
        if u.ok and u.unit == "credits" and u.remaining is not None:
            total_credits += u.remaining
        if not u.ok:
            any_err = True
            print(f"[{u.provider}] {u.error_code}: {u.error_msg}")

    widths = [max(_dwidth(_HEADERS[i]), *( _dwidth(r[i]) for r in rows)) for i in range(len(_HEADERS))]
    print("  ".join(_pad(h, widths[i]) for i, h in enumerate(_HEADERS)))
    for r in rows:
        print("  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))
    print(f"\n合计可用 Credits：{total_credits:,.0f}")
    return 1 if any_err and total_credits == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
