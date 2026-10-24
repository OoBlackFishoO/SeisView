"""数据模型：一份已载入的数据及其切片状态。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .volume import SLICE_LABELS, SeisVolume


@dataclass
class Dataset:
    """一份已载入的数据：体数据 + 它自己的剖面状态。

    多数据对比时每份数据各有一套 ``mode``（切片方向）与 ``pos``（三个轴的当前位置），
    「同步」打开时由主窗口把当前数据的选择广播给其余数据。
    """

    vol: SeisVolume
    path: str = ""
    key: str = ""
    mode: str = "shot"
    pos: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in SLICE_LABELS:
            self.mode = "shot"
        self.reset_pos()

    def reset_pos(self) -> None:
        self.pos = {"shot": self.vol.ns // 2,
                    "recv": self.vol.nr // 2,
                    "time": max(0, self.vol.nt // 4)}
