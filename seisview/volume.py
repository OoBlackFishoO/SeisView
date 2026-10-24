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

    @property
    def is_single_trace(self) -> bool:
        """单道/一维数据：只有一个炮点、一个检波点，沿时间轴一条记录。"""
        return self.ns == 1 and self.nr == 1

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


# -------------------------------------------------------------------- 增益
# 滑动 AGC 窗口的下限（再小就只剩几个样点，统计没有意义）
AGC_MIN_WINDOW = 3


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
    # 坏点（NaN / Inf）不参与能量统计，否则一个坏点会把整条道（滑窗时甚至是
    # 半个窗口的道）都算成 NaN，画面上就是一整片空洞。它自己仍然是坏点。
    valid = np.isfinite(a)
    filled = np.where(valid, a, 0.0).astype(np.float32)
    if window is None or window <= 1:
        scale = np.sqrt(np.mean(filled * filled, axis=0, keepdims=True))
    else:
        w = int(window) | 1                     # 强制奇数，保证下面长度对齐
        pad = (w - 1) // 2
        power = np.pad(filled * filled, ((pad, pad), (0, 0)), mode="edge")
        cum = np.cumsum(power, axis=0)
        cum = np.vstack([np.zeros((1, cum.shape[1]), cum.dtype), cum])
        scale = np.sqrt(np.maximum((cum[w:] - cum[:-w]) / w, 1e-30))
    scale[scale == 0] = 1.0
    out = (filled / scale).astype(np.float32)
    if not valid.all():
        out = np.where(valid, out, np.nan).astype(np.float32)
    return np.ascontiguousarray(out.T) if flip else out


def display_face(vol: SeisVolume, mode: str, index: int, *,
                 max_side: int | None = None,
                 agc_window: int | None = None) -> np.ndarray:
    """**二维剖面与三维贴图共用的唯一显示数组入口。**

    固定顺序：取片 ``take_slice`` → 抽稀 → AGC（仅 shot/recv）→ 返回。
    行 = 纵轴、列 = 横轴，与二维面板完全一致；三维贴图只需再转置/翻转。

    ``max_side`` 同时限制行与列（0 / None = 不抽稀）。二维剖面和三维贴图必须
    传同一个值，否则同一片在同一参数下会得到不同的 AGC 统计口径。

    ``mode == "time"``（时间切片）没有时间轴，AGC 在这里**统一挡掉** ——
    不再由界面各自判断。滑动窗口必须是非负奇数（0/1 = 整道归一化）。
    """
    assert mode in SLICE_MODES, f"未知切片方向：{mode}"
    if agc_window is not None and agc_window > 1:
        assert agc_window >= AGC_MIN_WINDOW, \
            f"AGC 窗口至少 {AGC_MIN_WINDOW} 点，收到 {agc_window}"
        assert agc_window % 2 == 1, f"AGC 滑动窗口必须是奇数，收到 {agc_window}"

    img = vol.take_slice(mode, index)
    if max_side:
        img = decimate(img, max_cols=int(max_side), max_rows=int(max_side))
    if agc_window is not None and mode != "time":
        img = agc(img, int(agc_window), axis=0)
    return img


# -------------------------------------------------------------------- 色标
def compute_clim(arr: np.ndarray, mode: str = "auto", value: float = 1.0,
                 sigma: float = 8.0) -> tuple[float, float]:
    """计算色标上下限（对称窗口，中心为中位数）。

    auto   —— ``max(8 × 1.4826 × MAD, P99(|x|))``。
              MAD 反映数据"安静部分"的宽度，对高斯数据给出 8σ 的干净窗口；
              重尾数据上 8×MAD 会过窄，因此用 P99(|x|) 兜底，默认约 1% 样点饱和。
    p95/p98/p99 —— 分别取 ``P95/P98/P99(|x|)``；P95 约 5%、P98 约 2%、
              P99 约 1% 的样点被压成端色。
    manual —— 对称取 ±value（value 是半宽，不是数据最大幅值）。

    NaN / Inf 一律不参与统计：`np.median` 会把中间值本身变成 NaN，一个坏点就能让
    整个窗口失效（整幅图变成一块纯色）。坏点位置交给渲染层单独画成"洞"。
    """
    if arr.size == 0:
        return (-1.0, 1.0)
    if mode == "manual":
        return (-abs(value), abs(value))
    sample = arr[:: max(1, arr.size // 200_000)]
    sample = sample[np.isfinite(sample)]
    if sample.size == 0:                       # 全是坏点：跟空数据一样兜底
        return (-1.0, 1.0)
    med = float(np.median(sample))
    abs_sample = np.abs(sample)
    if mode in ("p95", "p98", "p99"):
        q = {"p95": 95.0, "p98": 98.0, "p99": 99.0}[mode]
        v = float(np.percentile(abs_sample, q))
    else:
        mad = float(np.median(np.abs(sample - med)))
        v = 1.4826 * mad * sigma
        floor = float(np.percentile(abs_sample, 99.0))
        if not np.isfinite(v) or v <= 0:
            v = floor
        v = max(v, floor)
    if not np.isfinite(v) or v <= 0:
        v = float(np.max(abs_sample)) or 1.0
    return (med - v, med + v)


def shared_clim(arrays, mode: str = "auto", value: float = 1.0,
                sigma: float = 8.0) -> tuple[float, float]:
    """把多份二维显示数组合成**同一个**色标窗口（对比模式用）。

    每张图按 ``size // 50_000`` 抽一次样再拼接，统计口径与
    :func:`compute_clim` 完全一致；单份数据时结果与直接调用它相同。
    """
    parts = []
    for arr in arrays:
        a = np.asarray(arr)
        if a.size == 0:
            continue
        step = max(1, a.size // 50_000)
        parts.append(a.ravel()[::step])
    if not parts:
        return (-1.0, 1.0)
    return compute_clim(np.concatenate(parts), mode, value, sigma)


def stats(arr: np.ndarray) -> dict:
    """当前显示数据的四个读数。坏点不算进去，免得整行都显示 nan。"""
    if arr.size == 0:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}
    values = np.asarray(arr, dtype=np.float64).ravel()
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}
    return {
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "rms": float(np.sqrt(np.mean(values ** 2))),
    }