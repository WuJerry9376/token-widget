"""M21：设置页 foot GitHub 图标资产生成（官方 Invertocat → 两态×四档烘焙 PNG）。

用法（dev-only，允许第三方 PIL；产物是纯 PNG，运行时零依赖不变）：
    python tools\\make_gh_assets.py            # 生成/覆盖 assets\\gh_{faint,soft}_{16,20,24,32}.png
脚本幂等可重跑（全量覆盖）。

源素材（共享资产目录，AGENTS.md「GitHub 跳转图标资产」规则所列，**只读引用、
绝不修改原文件**）：
    C:\\Users\\OpenClaw\\Documents\\Default Project\\GitHub-logo\\GitHub_Invertocat_Black.png
    （294×288 RGBA；本 UI 纸色浅底 → 选 **Black**，深底场景才用 White。）

规格（与 M18 自绘剪影的色彩层级/尺寸语义完全一致）：
- 四档物理高度 = 16/20/24/32 px ≈ P(16)@S∈{1.0,1.25,1.5,2.0}，宽按墨迹 bbox 等比；
- 两态着色：normal=FAINT(#B3A582)、hover=SOFT(#8B7F65)——RGBA alpha 蒙版乘色后
  **烘焙到 PAPER(#FBF3DF) 底**（不透明）：Tk 8.6 PhotoImage 无 per-pixel alpha，且
  低分辨率无平滑缩放——预烘焙规避两坑；源图 294px ≥ 目标 4× 即超采样源，LANCZOS
  降采样一步到位。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(r"C:\Users\OpenClaw\Documents\Default Project\GitHub-logo\GitHub_Invertocat_Black.png")
OUT = ROOT / "assets"

# 色档与 settings_panel/ui 同源（手抄防 import tk 链；改色需两处同步，u26 有尺寸断言兜底）
INKS = {"faint": (0xB3, 0xA5, 0x82),      # FAINT：foot 文字同级（normal）
        "soft": (0x8B, 0x7F, 0x65)}       # SOFT：hover 一档加深
PAPER = (0xFB, 0xF3, 0xDF)               # PAPER 底（烘焙，杜绝透明合成）
TIERS = (16, 20, 24, 32)                 # 物理高 px @ S=1.0/1.25/1.5/2.0


def main() -> int:
    if not SRC.is_file():
        print(f"[gh-assets] 源图不可达：{SRC}", file=sys.stderr)
        return 1
    src = Image.open(SRC).convert("RGBA")
    bb = src.getbbox() or (0, 0, src.width, src.height)
    ink = src.crop(bb)
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for h in TIERS:
        w = max(1, round(h * ink.width / ink.height))     # 等比宽
        down = ink.resize((w, h), Image.LANCZOS)          # 294→16..32：源即 ≥4× 超采样
        alpha = down.split()[-1]
        for name, col in INKS.items():
            tint = Image.new("RGBA", (w, h), col + (255,))
            canvas = Image.new("RGB", (w, h), PAPER)      # 烘焙 PAPER 底（不透明产物）
            canvas.paste(tint.convert("RGB"), (0, 0), alpha)
            f = OUT / f"gh_{name}_{h}.png"
            canvas.save(f)
            n += 1
            print(f"[gh-assets] {f.name:22} {w}x{h} {col!r} on PAPER")
    print(f"[gh-assets] 完成：{n} 张 → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
