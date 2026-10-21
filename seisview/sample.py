"""内置示例数据：合成一个带双曲时距曲线的 (S, R, T) 体数据。

没有数据在手时也要能立刻看到效果，因此内置一个解析生成的合成记录：
若干倾斜反射层按正常时差（NMO）铺到各炮各道，再叠加绕射点和随机噪声。
"""

from __future__ import annotations

import numpy as np

from .volume import SeisVolume


def _ricker(dt: float, f0: float = 30.0, half_width: float = 0.06) -> np.ndarray:
    n = max(2, int(round(half_width / dt)))
    t = np.arange(-n, n + 1) * dt
    a = (np.pi * f0 * t) ** 2
    return (1.0 - 2.0 * a) * np.exp(-a)


def _add_event(out: np.ndarray, times: np.ndarray, amps: np.ndarray,
               dt: float, wavelet: np.ndarray) -> None:
    """把一组 (走时, 振幅) 脉冲铺到 out 的每一道上，并与子波卷积。

    ``scipy.signal`` 只在真正生成示例数据时才需要 —— 放到函数里 import，
    软件冷启动就不必为它付一秒多的代价。
    """
    from scipy.signal import fftconvolve
    nr, nt = out.shape
    idx = np.clip(times / dt, 0.0, nt - 1.001)
    i0 = np.floor(idx).astype(int)
    frac = idx - i0
    rows = np.arange(nr)
    impulse = np.zeros((nr, nt), dtype=np.float64)
    np.add.at(impulse, (rows, i0), amps * (1.0 - frac))
    np.add.at(impulse, (rows, i0 + 1), amps * frac)
    out += fftconvolve(impulse, wavelet[None, :], mode="same", axes=1)


def make_volume(ns: int = 24, nr: int = 72, nt: int = 700,
                dt: float = 0.002, dx: float = 12.5, ds: float = 25.0,
                seed: int = 20261009, noise: float = 0.05) -> np.ndarray:
    """生成示例体数据数组 (S, R, T)。

    反射层按中点-偏移距模型计算走时 ``t = sqrt((t0 + p·xm)² + (2h/v)²)``。
    炮点沿 S 方向前进时同相轴连续摆动，扫掠播放时最容易看出显示是否正确。
    """
    rng = np.random.default_rng(seed)
    wavelet = _ricker(dt)

    # 反射层：(零偏移时间 t0, 层速度 v, 横向慢度 p (s/m), 振幅)
    layers = [
        (0.26, 1500.0, 1.9e-4, 1.00),
        (0.50, 1800.0, -1.4e-4, -0.75),
        (0.76, 2200.0, 2.4e-4, 0.55),
        (1.02, 2700.0, -0.9e-4, -0.40),
    ]
    # 绕射点：(时间, 世界横坐标, 振幅)
    diffractors = [(0.60, 0.45 * nr * dx, 0.65), (0.92, 0.72 * nr * dx, -0.45)]

    recv_x = np.arange(nr) * dx
    data = np.zeros((ns, nr, nt), dtype=np.float32)

    for s in range(ns):
        shot_x = s * ds
        mid = 0.5 * (shot_x + recv_x)     # 炮检中点
        half = 0.5 * (recv_x - shot_x)    # 半偏移距
        taper = 1.0 - 0.35 * np.abs(half) / max(1e-9, float(np.abs(half).max()))
        shot = np.zeros((nr, nt), dtype=np.float64)
        for t0, vel, p, amp in layers:
            times = np.sqrt((t0 + p * mid) ** 2 + (2.0 * half / vel) ** 2)
            _add_event(shot, times, amp * taper, dt, wavelet)
        for td, xd, amp in diffractors:
            times = np.sqrt(td ** 2 + (np.abs(recv_x - xd) / 1600.0) ** 2)
            _add_event(shot, times, np.full(nr, float(amp)), dt, wavelet)
        data[s] = shot.astype(np.float32)

    if noise > 0:
        data += rng.normal(0.0, noise, data.shape).astype(np.float32)
    return data


def build_sample_volume(ns: int = 24, nr: int = 72, nt: int = 700,
                        dt: float = 0.002, dx: float = 12.5, ds: float = 25.0,
                        seed: int = 20261009) -> SeisVolume:
    """生成示例体数据，已规范化为 (S, R, T)。"""
    data = make_volume(ns=ns, nr=nr, nt=nt, dt=dt, dx=dx, ds=ds, seed=seed)
    return SeisVolume(name="示例数据", data=data, dt=dt, dx=dx, ds=ds)


def make_section(nr: int = 72, nt: int = 700, dt: float = 0.002,
                 dx: float = 12.5, seed: int = 7) -> np.ndarray:
    """生成一张二维剖面 (R, T)，用于演示"只有 2D 数据"时的路径。"""
    return np.asarray(make_volume(ns=1, nr=nr, nt=nt, dt=dt, dx=dx, seed=seed)[0],
                      dtype=np.float32)