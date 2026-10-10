"""数据模型与切片引擎。

核心约定
--------
所有体数据在内部一律规范化为 ``(S, R, T)`` = ``(炮点, 检波器, 时间)``。
二维数据升维为 ``(1, R, T)``，于是二维 / 三维走完全相同的代码路径。

三种标准正交面
--------------
============ ==================== ==========
切片模式      固定                 得到
============ ==================== ==========
共炮点 shot   S = s0               (R, T)
共检波点 recv R = r0               (S, T)
时间切片 time T = t0               (S, R)
============ ==================== ==========
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# 轴角色标识 —— 与界面下拉框的顺序一致
ROLE_SHOT = "shot"
ROLE_RECV = "recv"
ROLE_TIME = "time"

ROLE_LABELS = {
    ROLE_SHOT: "炮点",
    ROLE_RECV: "检波器",
    ROLE_TIME: "时间",
}
LABEL_TO_ROLE = {v: k for k, v in ROLE_LABELS.items()}

SLICE_MODES = ("shot", "recv", "time")
SLICE_LABELS = {"shot": "共炮点", "recv": "共检波点", "time": "时间切片"}


@dataclass
class SeisVolume:
    """一个已规范化为 (S, R, T) 的体数据。"""

    name: str
    data: np.ndarray
    dt: float = 0.001  # 时间采样间隔 (s)
    dx: float = 12.5   # 检波器间距 (m)
    ds: float = 25.0   # 炮点间距 (m)
    meta: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- 尺寸
    @property
    def ns(self) -> int:
        return int(self.data.shape[0])

    @property
    def nr(self) -> int:
        return int(self.data.shape[1])

    @property
    def nt(self) -> int:
        return int(self.data.shape[2])

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.ns, self.nr, self.nt)

    @property
    def is_single_shot(self) -> bool:
        return self.ns == 1

    def extent_of(self, mode: str) -> tuple[float, float, float, float]:
        """返回某一面的物理坐标范围 (x0, x1, y0, y1)。

        横轴为空间轴，纵轴为时间轴（或第二个空间轴）。纵轴的正方向朝上，
        由视图侧翻转 Y 轴来实现"时间向下增大"的地震惯例。
        """
        if mode == "shot":  # 横 R，纵 T
            return (0.0, self.nr * self.dx, 0.0, self.nt * self.dt)
        if mode == "recv":  # 横 S，纵 T
            return (0.0, self.ns * self.ds, 0.0, self.nt * self.dt)
        return (0.0, self.nr * self.dx, 0.0, self.ns * self.ds)  # 横 R，纵 S

    def axis_labels_of(self, mode: str, index: int) -> tuple[str, str, str]:
        """返回 (横轴名, 纵轴名, 标题后缀)。"""
        if mode == "shot":
            return ("检波器 R", "时间 T (s)", f"共炮点  S = {index}")
        if mode == "recv":
            return ("炮点 S", "时间 T (s)", f"共检波点  R = {index}")
        return ("检波器 R", "炮点 S", f"时间切片  T = {index}")

    def is_time_vertical(self, mode: str) -> bool:
        return mode in ("shot", "recv")

    # ---------------------------------------------------------------- 切片
    def slice_index_range(self, mode: str) -> int:
        """该模式下可扫掠的切片数量。"""
        return {"shot": self.ns, "recv": self.nr, "time": self.nt}[mode]

    def take_slice(self, mode: str, index: int) -> np.ndarray:
        """取出一个二维面，**行 = 纵轴、列 = 横轴**。

        返回的数组已保证 C 连续，避免后续跨步访问反复拖慢渲染。
        """
        index = int(np.clip(index, 0, max(0, self.slice_index_range(mode) - 1)))
        if mode == "shot":
            arr = self.data[index, :, :].T         # (R, T) → (T, R)
        elif mode == "recv":
            arr = self.data[:, index, :].T         # (S, T) → (T, S)
        else:
            arr = self.data[:, :, index]           # (S, R)
        return np.ascontiguousarray(arr)

    def take_face(self, mode: str, index: int) -> np.ndarray:
        """取出三维视图中使用的面，**行 = 局部 x（横）、列 = 局部 y（纵）**。

        需要在三维立方体里贴图，坐标轴顺序与二维面板不同，因此单独提供。
        """
        index = int(np.clip(index, 0, max(0, self.slice_index_range(mode) - 1)))
        if mode == "shot":
            arr = self.data[index, :, :]           # (R, T)：x=R, y=T
        elif mode == "recv":
            arr = self.data[:, index, :]           # (S, T)：x=S, y=T
        else:
            arr = self.data[:, :, index].T         # (S, R) → (R, S)：x=R, y=S
        return np.ascontiguousarray(arr)

    def take_trace(self, s: int, r: int) -> np.ndarray:
        """取一条一维道：固定 (S, R)，沿时间轴。"""
        s = int(np.clip(s, 0, self.ns - 1))
        r = int(np.clip(r, 0, self.nr - 1))
        return np.ascontiguousarray(self.data[s, r, :])


# -------------------------------------------------------------------- 抽稀
def decimate(arr: np.ndarray, max_cols: int = 2048, max_rows: int = 2048) -> np.ndarray:
    """按整数步长抽稀到不超过 max_cols / max_rows。

    屏幕只有千余像素宽，几千道的剖面没有必要全画。
    先抽稀再上色，是保证拖动跟手的关键一步。
    """
    r, c = arr.shape
    step_r = max(1, -(-r // max_rows))
    step_c = max(1, -(-c // max_cols))
    if step_r == 1 and step_c == 1:
        return np.ascontiguousarray(arr)
    return np.ascontiguousarray(arr[::step_r, ::step_c])


def downscale_for_texture(arr: np.ndarray, max_side: int = 256) -> np.ndarray:
    """为 3D 面板的贴图降采样：只算 ≤ max_side² 的缩略图，不参与主视图渲染。"""
    return decimate(arr, max_cols=max_side, max_rows=max_side)


# -------------------------------------------------------------------- 增益
def agc(arr: np.ndarray, window: int = 0, axis: int = 0) -> np.ndarray:
    """自动增益控制：沿时间轴做滑动窗口 RMS 归一化。

    深部弱信号和浅部强信号放在同一色标下根本看不见，AGC 是最实用的补救手段。
    ``window<=1`` 时按整道归一化。

    ``axis`` 指明**时间在哪一维**：``take_slice`` 的输出行是时间（axis=0），
    ``take_face`` 的竖直面列是时间（axis=1）。时间切片没有时间轴，不该调它。
    """
    a = np.asarray(arr, dtype=np.float32)
    if a.size == 0:
        return a
    flip = bool(axis)
    if flip:
        a = np.ascontiguousarray(a.T)
    if window is None or window <= 1:
        scale = np.sqrt(np.mean(a * a, axis=0, keepdims=True))
    else:
        w = int(window) | 1                     # 强制奇数，保证下面长度对齐
        pad = (w - 1) // 2
        power = np.pad(a * a, ((pad, pad), (0, 0)), mode="edge")
        cum = np.cumsum(power, axis=0)
        cum = np.vstack([np.zeros((1, cum.shape[1]), cum.dtype), cum])
        scale = np.sqrt(np.maximum((cum[w:] - cum[:-w]) / w, 1e-30))
    scale[scale == 0] = 1.0
    out = (a / scale).astype(np.float32)
    return np.ascontiguousarray(out.T) if flip else out


# -------------------------------------------------------------------- 色标
def compute_clim(arr: np.ndarray, mode: str = "auto", value: float = 1.0,
                 sigma: float = 8.0) -> tuple[float, float]:
    """计算色标上下限。

    auto   —— 中位数 + sigma×MAD。MAD 反映的是数据的"安静部分"（噪声底），
              与个别强反射无关，因此乘一个较大的系数（默认 8）就能让噪声底
              接近色标中性的白色，而反射同相轴依旧被压到饱和，图像最干净。
    robust —— 分位数 2% / 98%
    manual —— 对称取 ±value
    """
    if arr.size == 0:
        return (-1.0, 1.0)
    if mode == "manual":
        return (-abs(value), abs(value))
    sample = arr[:: max(1, arr.size // 200_000)]
    if mode == "robust":
        lo, hi = np.percentile(sample, [2.0, 98.0])
        v = max(abs(float(lo)), abs(float(hi)), 1e-30)
        return (-v, v)
    med = float(np.median(sample))
    mad = float(np.median(np.abs(sample - med)))
    v = 1.4826 * mad * sigma
    if not np.isfinite(v) or v <= 0:
        v = float(np.max(np.abs(sample))) or 1.0
    return (med - v, med + v)


def stats(arr: np.ndarray) -> dict:
    if arr.size == 0:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}
    return {
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "rms": float(np.sqrt(np.mean(arr.astype(np.float64) ** 2))),
    }