"""单道波形视图：横轴时间、纵轴振幅；对比时按数据顺序叠加。"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6 import QtWidgets

from . import style, view2d


class TraceView(QtWidgets.QWidget):
    """单道波形绘图区：**横轴时间、纵轴振幅**。

    多数据对比时把各数据源对应道叠在一起，颜色由 :mod:`view2d` 里的
    ``screen_line_styles``（数据识别色）按数据顺序分配 —— 深浅随主题走，
    每套主题各配一组"在自家底色上看得清"的颜色。

    **屏幕跟主题、导出固定白底**：屏上这块画布跟着当前主题走（见 `style.GL_BG`）；
    论文里那种"白底 + 黑/红/蓝细线"由导出的 ``build_trace_figure`` 负责。两套规则
    分开，屏上就不会出现"一块白纸飘在深色界面里"，而导出图始终是论文能直接用的样子。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.plot = pg.PlotWidget(background=style.GL_BG)
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.14)
        self.plot.setMinimumHeight(120)
        vb = self.plot.getViewBox()
        vb.setDefaultPadding(0.02)
        self.plot.setLabel("bottom", "时间 T (s)", color=style.TEXT_DIM)
        self.plot.setLabel("left", "振幅", color=style.TEXT_DIM)
        for side in ("bottom", "left"):
            try:
                axis = self.plot.getAxis(side)
                axis.setTextPen(pg.mkPen(style.TEXT_DIM))
                axis.setPen(pg.mkPen(style.TEXT_DIM))
                axis.enableAutoSIPrefix(False)
            except Exception:                        # pragma: no cover
                pass
        # 振幅 0 基准线：横轴是时间，所以这条线是**水平**的
        self._zero = pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                     pen=pg.mkPen(style.LINE_HI, width=1))
        self.plot.addItem(self._zero, ignoreBounds=True)
        # **屏上不画 pyqtgraph 图例**：对比时它又大又盖波形。识别色改由面板
        # 标题行的紧凑图例承担（见 MainWindow._sync_trace_legend）；导出的
        # 论文图另有自己的图例（view2d.build_*_figure），不受这里影响。
        self._curves: list[pg.PlotDataItem] = []
        lay.addWidget(self.plot)

    def set_traces(self, traces: list) -> None:
        """``traces`` = ``[(时间, 振幅, (颜色, 线型), 名称), ...]``，按数据顺序叠加。"""
        while len(self._curves) < len(traces):
            self._curves.append(self.plot.plot())
        for curve, (t, amp, style_pair, _name) in zip(self._curves, traces):
            curve.setData(t, amp)
            curve.setPen(view2d.line_pen(style_pair, 1.4))
        for curve in self._curves[len(traces):]:
            curve.setData([], [])

    def clear(self) -> None:
        for curve in self._curves:
            curve.setData([], [])

    def restyle(self) -> None:
        """换主题：画布底、坐标轴、零基准线重刷（屏上没有图例）。"""
        self.plot.setBackground(style.GL_BG)
        self.plot.setLabel("bottom", "时间 T (s)", color=style.TEXT_DIM)
        self.plot.setLabel("left", "振幅", color=style.TEXT_DIM)
        for side in ("bottom", "left"):
            try:
                axis = self.plot.getAxis(side)
                axis.setTextPen(pg.mkPen(style.TEXT_DIM))
                axis.setPen(pg.mkPen(style.TEXT_DIM))
            except Exception:                        # pragma: no cover
                pass
        self._zero.setPen(pg.mkPen(style.LINE_HI, width=1))


