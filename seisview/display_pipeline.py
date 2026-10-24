"""显示管线：切片 → 抽稀/AGC → 色标 → 上色前的二维数组。

这里只做计算与缓存，不碰 Qt 控件、不碰面板。二维剖面、wiggle、共享色标、
三维贴图与导出图都从这一个对象取数，保证同参数下口径完全一致。
"""

from __future__ import annotations

import numpy as np

from .app_state import DisplaySettings
from .volume import (SeisVolume, compute_clim, display_face, shared_clim,
                     stats as compute_stats)

_EMPTY_STATS = {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}


class DisplayPipeline:
    """显示计算与缓存。调用方负责把当前数据与设置快照传进来。"""

    def __init__(self) -> None:
        self.base_clims: list[tuple[float, float]] = []
        self.clims: list[tuple[float, float]] = []
        self.active_clim: tuple[float, float] = (-1.0, 1.0)
        self.raw_cache: dict[tuple[int, bool], tuple[np.ndarray, bool]] = {}
        self.panel_cache: dict[tuple[int, bool],
                                  tuple[np.ndarray, tuple[float, float]]] = {}
        self.shared_base_cache: tuple[float, float] | None = None
        self.face_clim_cache: dict[tuple, tuple[float, float]] = {}
        self.stats: dict[str, float] = dict(_EMPTY_STATS)

    # ------------------------------------------------------------ 生命周期
    def reset(self) -> None:
        """清空数据时彻底复位：色标、统计与全部缓存。"""
        self.base_clims = []
        self.clims = []
        self.active_clim = (-1.0, 1.0)
        self.stats = dict(_EMPTY_STATS)
        self.invalidate_slices()

    def invalidate_slices(self) -> None:
        """切片/AGC/抽稀变了：数组、共享色标与三维面色标都要重算。"""
        self.panel_cache.clear()
        self.raw_cache.clear()
        self.shared_base_cache = None
        self.face_clim_cache.clear()

    def invalidate_color(self) -> None:
        """只改对比度/色标：切片数组与基准色标保留，只重做上色相关缓存。"""
        self.panel_cache.clear()
        self.face_clim_cache.clear()

    # ------------------------------------------------------------ 基准色标
    def set_base_clims(self, values: list[tuple[float, float]]) -> None:
        self.base_clims = list(values)

    def append_base_clim(self, value: tuple[float, float] = (-1.0, 1.0)) -> None:
        self.base_clims.append(value)

    def pop_base_clim(self, index: int) -> None:
        self.base_clims.pop(index)

    @staticmethod
    def base_sample(vol: SeisVolume) -> np.ndarray:
        """估计基准色标用的代表样本：三片中位切片，避免惰性数据整卷扫描。"""
        parts = []
        for mode in ("shot", "recv", "time"):
            sl = vol.take_slice(mode, vol.slice_index_range(mode) // 2)
            parts.append(np.asarray(sl, dtype=np.float32).ravel()[::5])
        return np.concatenate(parts) if parts else np.zeros(1, np.float32)

    def recompute_base_clim(self, k: int, vol: SeisVolume,
                            settings: DisplaySettings) -> None:
        while len(self.base_clims) <= k:
            self.base_clims.append((-1.0, 1.0))
        self.base_clims[k] = compute_clim(
            self.base_sample(vol), settings.clim_mode, settings.manual_halfwidth)

    def recommended_manual_halfwidth(self, datasets) -> float | None:
        if not datasets:
            return None
        parts = [self.base_sample(ds.vol) for ds in datasets]
        sample = np.concatenate(parts)
        sample = sample[np.isfinite(sample)]
        if sample.size == 0:
            return None
        value = float(np.percentile(np.abs(sample), 98.0))
        return value if np.isfinite(value) and value > 0 else None

    # ------------------------------------------------------------ 数组
    def agc_window(self, mode: str, settings: DisplaySettings) -> int | None:
        return settings.agc_window_for(mode)

    def processed_image(self, k: int, datasets, settings: DisplaySettings,
                        full: bool = False):
        """第 k 份数据当前切片 → ``(抽稀/AGC 后的数组, 是否施加了 AGC)``。"""
        key = (k, full)
        hit = self.raw_cache.get(key)
        if hit is not None:
            return hit
        ds = datasets[k]
        limit = None if full else settings.decimation
        agc_window = settings.agc_window_for(ds.mode)
        img = display_face(ds.vol, ds.mode, ds.pos[ds.mode],
                           max_side=limit, agc_window=agc_window)
        out = (img, agc_window is not None)
        self.raw_cache[key] = out
        return out

    def shared_base_clim(self, datasets, settings: DisplaySettings):
        """对比模式下所有面板共用的基准色标窗口。"""
        if self.shared_base_cache is not None:
            return self.shared_base_cache
        if not datasets:
            base = (-1.0, 1.0)
        elif len(datasets) == 1:
            img, agc_on = self.processed_image(0, datasets, settings)
            base = (compute_clim(img, "p98") if agc_on
                    else self.base_clims[0])
        else:
            imgs, agc_any = [], False
            for k in range(len(datasets)):
                img, agc_on = self.processed_image(k, datasets, settings)
                imgs.append(img)
                agc_any = agc_any or agc_on
            base = shared_clim(
                imgs,
                "p98" if agc_any else settings.clim_mode,
                settings.manual_halfwidth)
        self.shared_base_cache = base
        return base

    @staticmethod
    def scale_window(base: tuple[float, float],
                     settings: DisplaySettings) -> tuple[float, float]:
        """把基准窗口按对比度围绕中点对称缩放。"""
        lo, hi = base
        mid = 0.5 * (lo + hi)
        half = max(1e-12, 0.5 * (hi - lo) * settings.contrast)
        return (mid - half, mid + half)

    def panel_image(self, k: int, datasets, settings: DisplaySettings,
                    full: bool = False):
        """第 k 份数据 → ``(显示用数组, 全体共享的色标窗口)``。"""
        key = (k, full)
        hit = self.panel_cache.get(key)
        if hit is not None:
            return hit
        img, _agc_on = self.processed_image(k, datasets, settings, full)
        clim = self.scale_window(self.shared_base_clim(datasets, settings), settings)
        if not full:
            self.panel_cache[key] = (img, clim)
        return img, clim

    def clim_for_face(self, datasets, mode: str, settings: DisplaySettings,
                      active: int, active_mode: str):
        """三维里非当前面的色标；当前面直接复用二维面板的窗口。"""
        if datasets and mode == active_mode and active < len(self.clims):
            return self.clims[active]
        limit = settings.decimation
        agc_window = settings.agc_window_for(mode)
        key = (mode,
               tuple(ds.pos[mode] for ds in datasets),
               agc_window, settings.clim_mode,
               float(settings.manual_halfwidth), float(settings.contrast))
        hit = self.face_clim_cache.get(key)
        if hit is not None:
            return hit
        imgs = [display_face(ds.vol, mode, ds.pos[mode],
                             max_side=limit, agc_window=agc_window)
                for ds in datasets]
        base = shared_clim(
            imgs,
            "p98" if agc_window is not None else settings.clim_mode,
            settings.manual_halfwidth)
        clim = self.scale_window(base, settings)
        if len(self.face_clim_cache) > 48:
            self.face_clim_cache.clear()
        self.face_clim_cache[key] = clim
        return clim

    # ------------------------------------------------------------ wiggle / 单道
    def wiggle_set(self, k: int, datasets, settings: DisplaySettings,
                   screen_styles, shared: float | None = None) -> tuple:
        img, clim = self.panel_image(k, datasets, settings)
        finite = np.abs(img[np.isfinite(img)]) if img.size else np.empty(0)
        scale = (float(shared) if shared
                 else (float(np.percentile(finite, 99)) if finite.size else 0.0))
        return (img, clim, scale or 1.0, screen_styles[k % len(screen_styles)])

    def traces(self, datasets, active: int, settings: DisplaySettings,
               screen_styles, labels) -> tuple[list, list, tuple[int, int]]:
        traces, peaks = [], []
        sr = (0, 0)
        for k, ds in enumerate(datasets):
            vol = ds.vol
            s = min(max(ds.pos["shot"], 0), vol.ns - 1)
            r = min(max(ds.pos["recv"], 0), vol.nr - 1)
            amp = np.asarray(vol.take_trace(s, r), dtype=np.float32)
            t = np.arange(vol.nt) * vol.dt
            finite = amp[np.isfinite(amp)]
            peak = float(np.max(np.abs(finite))) if finite.size else 0.0
            peak = peak or 1.0
            traces.append((t, amp / (peak if settings.normalize_traces else 1.0),
                           screen_styles[k % len(screen_styles)], labels[k]))
            peaks.append(peak)
            if k == active:
                sr = (s, r)
        return traces, peaks, sr

    # ------------------------------------------------------------ 色标数组管理
    def ensure_clim_count(self, n: int) -> None:
        """让当前色标列表与数据份数对齐（载入/追加/移除之后）。"""
        self.clims = self.clims[:n]
        while len(self.clims) < n:
            self.clims.append(self.base_clims[len(self.clims)])

    def set_shared_clim(self, shared: tuple[float, float], active: int) -> None:
        self.clims = [shared] * len(self.clims)
        if self.clims:
            self.active_clim = self.clims[active]

    def set_panel_clim(self, k: int, clim: tuple[float, float],
                       active: int) -> None:
        while len(self.clims) <= k:
            self.clims.append(clim)
        self.clims[k] = clim
        if k == active:
            self.active_clim = clim

    def set_stats(self, img: np.ndarray) -> None:
        # 统计量只对抽稀后的图做二次抽样，避免为了一行读数多跑一遍全量数据
        self.stats = compute_stats(np.asarray(img[::4, ::4], dtype=np.float32))
