"""渲染层：colormap、数组转 RGBA、wiggle 曲线、3D 面贴图。

这里的函数全部是纯函数（numpy 进、numpy 出），与界面无关，可以单独测试。
"""

from __future__ import annotations

import numpy as np

# ==================================================================== colormap
# 用锚点插值定义，避免依赖 matplotlib。
_ANCHORS: dict[str, list[tuple[float, tuple[float, float, float]]]] = {
    "gray": [(0.0, (0, 0, 0)), (1.0, (1, 1, 1))],
    "seismic": [
        (0.00, (0.0, 0.0, 0.30)),
        (0.25, (0.0, 0.0, 1.00)),
        (0.50, (1.0, 1.0, 1.00)),
        (0.75, (1.0, 0.0, 0.00)),
        (1.00, (0.5, 0.0, 0.00)),
    ],
    "jet": [
        (0.000, (0.0, 0.0, 0.50)),
        (0.125, (0.0, 0.0, 1.00)),
        (0.375, (0.0, 1.0, 1.00)),
        (0.625, (1.0, 1.0, 0.00)),
        (0.875, (1.0, 0.0, 0.00)),
        (1.000, (0.5, 0.0, 0.00)),
    ],
    "bone": [
        (0.000, (0.00, 0.00, 0.00)),
        (0.375, (0.28, 0.31, 0.375)),
        (0.750, (0.62, 0.65, 0.70)),
        (1.000, (1.00, 1.00, 1.00)),
    ],
    "hot": [
        (0.000, (0.04, 0.00, 0.00)),
        (0.365, (0.90, 0.00, 0.00)),
        (0.746, (1.00, 0.90, 0.00)),
        (1.000, (1.00, 1.00, 1.00)),
    ],
    "bwr": [(0.0, (0, 0, 1)), (0.5, (1, 1, 1)), (1.0, (1, 0, 0))],
    "cool": [(0.0, (0, 1, 1)), (1.0, (1, 0, 1))],
    "viridis": [
        (0.000, (0.267, 0.005, 0.329)),
        (0.150, (0.283, 0.141, 0.458)),
        (0.300, (0.254, 0.265, 0.530)),
        (0.450, (0.207, 0.372, 0.553)),
        (0.600, (0.164, 0.471, 0.558)),
        (0.750, (0.128, 0.567, 0.551)),
        (0.900, (0.478, 0.821, 0.318)),
        (1.000, (0.993, 0.906, 0.144)),
    ],
}

# 界面显示名 → key
COLORMAP_LABELS: list[tuple[str, str]] = [
    ("灰度", "gray"),
    ("灰度反色", "gray_r"),
    ("红蓝（地震）", "seismic"),
    ("彩虹 jet", "jet"),
    ("骨色 bone", "bone"),
    ("热力 hot", "hot"),
    ("蓝白红 bwr", "bwr"),
    ("青紫 cool", "cool"),
    ("Viridis", "viridis"),
]

_LUT_CACHE: dict[str, np.ndarray] = {}


def lut(name: str, n: int = 256) -> np.ndarray:
    """返回 (n, 4) 的 uint8 查找表。"""
    key = f"{name}:{n}"
    hit = _LUT_CACHE.get(key)
    if hit is not None:
        return hit

    reverse = name.endswith("_r")
    base = name[:-2] if reverse else name
    anchors = _ANCHORS.get(base) or _ANCHORS["gray"]

    pos = np.array([a[0] for a in anchors], dtype=np.float64)
    cols = np.array([a[1] for a in anchors], dtype=np.float64)
    x = np.linspace(0.0, 1.0, n)
    rgb = np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=1)
    if reverse:
        rgb = rgb[::-1]
    out = np.empty((n, 4), dtype=np.uint8)
    out[:, :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[:, 3] = 255
    _LUT_CACHE[key] = out
    return out


def gradient_strip(name: str, width: int = 128) -> np.ndarray:
    """给色带选择器用的 (1, width, 4) 缩略图。"""
    return lut(name, width)[None, :, :]


# ==================================================================== 上色
def to_rgba(arr: np.ndarray, cmap: str, clim: tuple[float, float],
            gamma: float = 1.0) -> np.ndarray:
    """二维数组 → (h, w, 4) uint8。拖动色标时只重算这一步，数据不动。"""
    lo, hi = float(clim[0]), float(clim[1])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        hi = lo + 1e-12
    x = (np.asarray(arr, dtype=np.float32) - lo) / (hi - lo)
    if gamma != 1.0:
        np.clip(x, 0.0, 1.0, out=x)
        x = np.power(x, gamma)
    idx = np.clip(x * 255.0, 0, 255).astype(np.uint8)
    return lut(cmap)[idx]


# ==================================================================== wiggle
def choose_wiggle_traces(ntr: int, want: int) -> np.ndarray:
    """在 ntr 道里均匀挑 want 道，保证首尾都在。"""
    want = int(max(1, min(want, ntr)))
    if want == 1:
        return np.array([ntr // 2], dtype=int)
    return np.unique(np.linspace(0, ntr - 1, want).round().astype(int))


def wiggle_curves(img: np.ndarray, extent: tuple[float, float, float, float],
                  clim: tuple[float, float] = (-1.0, 1.0),
                  n_traces: int = 60, gain: float = 1.0
                  ) -> list[tuple[np.ndarray, np.ndarray]]:
    """生成 wiggle 波形折线（显示坐标系）。

    ``img`` 为 (行, 列) 的二维切片：行是纵轴（时间），列是横轴（道）。
    返回 [(x, y), ...]，每条对应一道，可直接喂给 PlotDataItem。
    """
    rows, cols = img.shape
    x0, x1, y0, y1 = extent
    if cols == 0 or rows == 0:
        return []

    idx = choose_wiggle_traces(cols, n_traces)
    step = (x1 - x0) / max(1, cols - 1) if cols > 1 else (x1 - x0)
    # 每条波形允许的横向摆幅：不超过道间距，避免相互重叠成一团
    half = abs(step) * 0.45 * gain

    lo, hi = float(clim[0]), float(clim[1])
    if hi <= lo:
        hi = lo + 1e-12
    peak = max(abs(lo), abs(hi)) or 1.0

    y = np.linspace(y0, y1, rows)
    curves: list[tuple[np.ndarray, np.ndarray]] = []
    for c in idx:
        base = x0 + step * int(c)
        amp = img[:, int(c)].astype(np.float32) / peak
        curves.append((base + amp * half, y))
    return curves


# ==================================================================== 3D 贴图
def face_texture(img_xy: np.ndarray, cmap: str, clim: tuple[float, float]) -> np.ndarray:
    """生成 3D 面贴图。

    入参 ``img_xy`` 的行对应 GLImageItem 的局部 x（横轴），列对应局部 y（纵轴）。
    返回 C 连续的 uint8 (x, y, 4)。需要"时间向下增大"时由调用方翻转第 1 轴。
    """
    return np.ascontiguousarray(to_rgba(img_xy, cmap, clim))