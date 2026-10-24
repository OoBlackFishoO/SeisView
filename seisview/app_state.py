"""应用状态对象：把“控件当前值”与“工作区布局状态”从计算逻辑里分离出来。

这些是纯数据类，不依赖 Qt。控制器在每轮刷新开始时读取一次快照，后续计算
统一使用快照，避免同一次刷新过程中反复访问控件、出现前后不一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DisplaySettings:
    """一轮刷新/导出使用的显示参数快照。"""

    cmap: str
    clim_mode: str                 # auto / p95 / p98 / p99 / manual
    manual_halfwidth: float
    contrast: float                # 1.0 = 100%
    agc_on: bool
    agc_window: int                # 0 = 整道归一化
    decimation: int | None
    wiggle_on: bool
    pure_waveform: bool
    wiggle_traces: int
    wiggle_gain: float
    normalize_traces: bool

    def agc_window_for(self, mode: str) -> int | None:
        """时间切片没有时间轴，AGC 一律不施加。"""
        if mode == "time" or not self.agc_on:
            return None
        return self.agc_window


@dataclass
class WorkspaceState:
    """工作区布局与面板停靠状态。逐步从 MainWindow 的散落字段迁入。"""

    content_shown: dict[str, bool]
    pair_order: list[str]
    layout_preset: str
    default3_key: str = ""
    default3_order: tuple[str, ...] = ()
    pair_defaults: dict[str, tuple[str, ...]] = field(default_factory=dict)
    follow_layout: bool = True
    user_size: tuple[int, int] | None = None
    window_target: tuple[int, int] | None = None
    region_shown: dict[str, bool] = field(default_factory=lambda: {"left": True})
    three_auto_closed: bool = False
    is_2d: bool = False
    is_1d: bool = False
    detached: dict = field(default_factory=dict)
    drag_vis: set[str] = field(default_factory=set)
    preview_dock: set[str] = field(default_factory=set)
