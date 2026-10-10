"""生成 SeisView 的图标：assets/seisview.ico（多尺寸）与 assets/seisview.png。

用 Pillow 直接画，不依赖外部素材，随时可以重新生成：
    python make_icon.py

图案是四道同相轴（wiggle）——地震道集最直观的符号，小尺寸下也不会糊成一团。
"""

from __future__ import annotations

import math
import os

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")

BG_TOP = (17, 22, 32)
BG_BOTTOM = (8, 11, 17)
GRID = (35, 44, 61)
ACCENT = (56, 189, 248)
ACCENT_DIM = (30, 92, 120)
POS = (248, 113, 113)
NEG = (56, 130, 246)

SS = 4                      # 超采样倍数，画完再缩小，边缘才干净
SIZE = 256


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def draw_icon(size: int = SIZE) -> Image.Image:
    px = size * SS
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角底板 + 竖向渐变（用遮罩把渐变裁成圆角）
    radius = int(px * 0.22)
    grad = Image.new("RGB", (1, px))
    gd = ImageDraw.Draw(grad)
    for y in range(px):
        gd.point((0, y), fill=_lerp(BG_TOP, BG_BOTTOM, y / max(1, px - 1)))
    grad = grad.resize((px, px))
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, px - 1, px - 1), radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # 外描边
    d.rounded_rectangle((0, 0, px - 1, px - 1), radius,
                        outline=ACCENT_DIM, width=max(2, int(px * 0.012)))

    # 背景细网格
    gw = max(1, int(px * 0.006))
    for i in (1, 2, 3):
        y = int(px * 0.25 * i)
        d.line((px * 0.10, y, px * 0.90, y), fill=GRID, width=gw)
    for i in (1, 2, 3):
        x = int(px * 0.25 * i)
        d.line((x, px * 0.10, x, px * 0.90), fill=GRID, width=gw)

    # 四道波形；包络铺满整幅避免两侧拖成横条，越靠下摆幅越小，像一道炮集
    n_tr = 4
    margin = px * 0.14
    span = px - 2 * margin
    amp0 = px * 0.125
    lw = max(2, int(px * 0.026))
    ns = 200
    u = np.linspace(0.0, 1.0, ns)
    env = np.exp(-((u - 0.5) * 1.7) ** 2)
    wave = -env * np.sin(2 * np.pi * 2.0 * u)          # 两个周期的波形
    wave = wave / np.abs(wave).max()
    xs = margin + span * u

    for k in range(n_tr):
        yc = margin + span * (k + 0.5) / n_tr
        ys = yc + amp0 * (1.0 - 0.20 * k) * wave
        if k == 1:
            # 中间那道用"可变面积"配色：向上偏移红、向下偏移蓝 —— 地震剖面经典约定
            d.line((xs[0], yc, xs[-1], yc), fill=GRID, width=max(1, int(px * 0.006)))
            up = wave <= 0
            for sel, color in ((up, POS), (~up, NEG)):
                if sel.sum() > 1:
                    d.line(list(zip(xs[sel], ys[sel])), fill=color,
                           width=lw, joint="curve")
        else:
            d.line(list(zip(xs, ys)), fill=ACCENT, width=lw, joint="curve")

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    base = draw_icon(SIZE)                     # 先画大图，缩小时更干净
    png = os.path.join(OUT, "seisview.png")
    base.save(png)
    ico = os.path.join(OUT, "seisview.ico")
    base.save(ico, format="ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)])
    for f in (png, ico):
        print(f"{f}  {os.path.getsize(f)} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())