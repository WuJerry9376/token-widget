"""生成 token-widget 应用图标（纯 stdlib：zlib/struct 手写 PNG → 多尺寸 PNG-in-ICO 容器）。

意象：便签风——奶油底便签纸 + 右下卷角（参考 local/m3_preview.png），上方三条"文字线"。
做法：逻辑尺寸 4x 超采样逐像素绘制，盒式降采样抗锯齿，PNG(v3, RGBA) 条目直接封入
ICO（Vista+ 支持 PNG-in-ICO）。产出 sizes = 256/48/32。

用法：python build/icon/make_icon.py [-o build/icon/token-widget.ico]
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

# 调色板（便签风）
TRANSPARENT = (0, 0, 0, 0)
BODY = (251, 242, 211, 255)     # 奶油纸面
EDGE = (224, 208, 158, 255)     # 纸边描线
FLAP = (228, 210, 150, 255)     # 卷角背面（略深）
FLAP_SHADE = (205, 184, 126, 255)  # 卷角折痕
BAR = (168, 157, 122, 255)      # "文字线"
BAR_SOFT = (196, 187, 156, 255)


def _inside_tri(px, py, a, b, c) -> bool:
    """点是否在三角形 abc 内（同侧法）。"""
    def sign(p1, p2, p3):
        return ((p1[0] - p3[0]) * (p2[1] - p3[1])
                - (p2[0] - p3[0]) * (p1[1] - p3[1]))
    s1 = sign((px, py), a, b)
    s2 = sign((px, py), b, c)
    s3 = sign((px, py), c, a)
    has_neg = (s1 < 0) or (s2 < 0) or (s3 < 0)
    has_pos = (s1 > 0) or (s2 > 0) or (s3 > 0)
    return not (has_neg and has_pos)


def draw(n: int) -> tuple[int, bytes]:
    """画 n x n 便签（4n 超采样后降采样），返回 (n, RGBA bytes)。"""
    S = n * 4                      # 超采样边长
    m = round(S * 0.10)            # 外边距
    lo, hi = m, S - m              # 纸面方块范围
    c = round(S * 0.30)            # 卷角切边长
    cx, cy = hi - c, hi - c        # 切角起点
    bw = max(2, round(S * 0.012))  # 描线宽

    a_tri = (cx, hi)
    b_tri = (hi, cy)
    c_tri = (cx, cy)

    bars = [  # (y0_frac, y1_frac, x1_frac) 相对纸面
        (0.22, 0.30, 0.72),
        (0.38, 0.46, 0.64),
        (0.54, 0.62, 0.48),
    ]

    px = bytearray(S * S * 4)

    def put(x, y, rgba):
        o = (y * S + x) * 4
        px[o:o + 4] = bytes(rgba)

    span = hi - lo
    for y in range(lo, hi):
        fy = (y - lo) / span
        for x in range(lo, hi):
            fx = (x - lo) / span
            xp, yp = x - cx, y - cy          # 以切角起点为原点
            in_flap_zone = xp > 0 and yp > 0
            # 右下切角：折线外（xp+yp>c）为透明背景
            if in_flap_zone and xp + yp > c:
                put(x, y, TRANSPARENT)
                continue
            near_edge = (x - lo < bw) or (hi - x <= bw) or (y - lo < bw) or (hi - y <= bw)
            color = BODY
            # 卷角背面：对折回来的三角，贴着折痕线内侧
            if in_flap_zone and _inside_tri(x, y, a_tri, b_tri, c_tri):
                d = abs(xp + yp - c)          # 到折痕线的近似距离
                color = FLAP_SHADE if d <= bw * 2 else FLAP
            else:
                # 文字线条带
                for by0, by1, bx1 in bars:
                    if by0 <= fy <= by1 and fx <= bx1:
                        color = BAR
                        break
                if near_edge:
                    color = EDGE
            put(x, y, color)

    # 盒式降采样 4x4 → 1
    out = bytearray(n * n * 4)
    for oy in range(n):
        for ox in range(n):
            rs = gs = bs = as_ = 0
            for sy in range(4):
                for sx in range(4):
                    o = ((oy * 4 + sy) * S + ox * 4 + sx) * 4
                    rs += px[o]; gs += px[o + 1]; bs += px[o + 2]; as_ += px[o + 3]
            o = (oy * n + ox) * 4
            div = 16
            # 非预乘 alpha 的均值（对透明色做 alpha 加权以免边缘发黑）
            a = as_ // div
            if a:
                out[o] = rs * 255 // as_ if as_ else 0
                out[o + 1] = gs * 255 // as_ if as_ else 0
                out[o + 2] = bs * 255 // as_ if as_ else 0
            out[o + 3] = a
    return n, bytes(out)


def png_bytes(n: int, rgba: bytes) -> bytes:
    """RGBA → PNG（filter 0，zlib level 9）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + rgba[y * n * 4:(y + 1) * n * 4] for y in range(n))
    ihdr = struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico_bytes(pngs: list[tuple[int, bytes]]) -> bytes:
    """多 PNG 条目封装为 ICO（Vista+ PNG-in-ICO）。256 尺寸宽高字节记 0。"""
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries, payload = b"", b""
    for n, png in pngs:
        wb = n % 256
        entries += struct.pack("<BBBBHHII", wb, wb, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    return header + entries + payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(Path(__file__).with_name("token-widget.ico")))
    args = ap.parse_args()
    pngs = []
    for size in (256, 48, 32):
        n, rgba = draw(size)
        pngs.append((n, png_bytes(n, rgba)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ico_bytes(pngs))
    print(f"[icon] wrote {out} ({out.stat().st_size} bytes, sizes: 256/48/32 PNG-in-ICO)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
