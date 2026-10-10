"""二维切片视图：密度图 + wiggle 叠加 + 鼠标取点。

显示方向约定
------------
``ImageItem`` 的第 0 行画在矩形上沿，因此配合 ``invertY(True)`` 让 y=0 位于屏幕
顶部，正好实现"时间向下增大"的地震惯例。

关于 autoDownsample
-------------------
这里**必须关掉** ``autoDownsample``。pyqtgraph 的降采样用的是 ``array.mean()``，
会把 uint8 的 RGBA 图变成 float64，紧接着 ``makeARGB`` 会以
"levels argument is required for float input types" 抛异常，绘制直接中断 ——
表现就是切换切片模式后整块面板全黑，滚动缩放一次（缩放系数回到 1，不再降采样）
才恢复。我们自己已经在 ``volume.decimate`` 里按屏幕像素抽过稀了，不需要它再插一手。

交互
----
* 左键拖动 = 平移，滚轮 = 缩放（用 ``PanMode``；原来的 ``RectMode`` 是"框起来放大"，
  看剖面时更想直接拖着走）；
* 左键"按下-抬起几乎没动"才算取点，否则拖完顺手把单道波形换掉了；
* 双击复位视野。
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

from . import render, style

# 叠加波形的默认颜色：地震剖面上惯用黑色（底色多为白/红/蓝，黑色最跳）
_DEFAULT_WIGGLE_COLOR = (10, 12, 16, 210)

# 判定"点击"（而非拖动）的位移上限，单位像素
_CLICK_SLOP = 4


# 单道波形取自哪一道的提示线用**竖线**（angle=90）。
# 注意 angle=0 是横线，setValue 会去设 y 值 —— 两个轴量纲不同时线会跑到
# 视野外面（之前那根"莫名其妙的绿线"就是这么来的）。
_LINE_PEN = style.OK


class SliceView(pg.PlotWidget):
    """一个切片面的显示控件。"""

    picked = QtCore.Signal(int, int)            # (列号, 行号)，原始数据网格索引
    hovered = QtCore.Signal(int, int)           # (列号, 行号)，原始数据网格索引

    def __init__(self, parent=None):
        super().__init__(parent, background=style.GL_BG)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=True, y=True)

        vb = self.getViewBox()
        vb.setDefaultPadding(0.0)
        vb.invertY(True)
        vb.setMouseMode(pg.ViewBox.PanMode)     # 左键拖动平移，滚轮缩放

        self._img = pg.ImageItem(axisOrder="row-major", autoDownsample=False)
        self.addItem(self._img)

        # 单道波形取自哪一道的提示线：竖线 + 文字标签
        self._wiggles: list[pg.PlotDataItem] = []
        self._line = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen(_LINE_PEN, width=1))
        self._line.setVisible(False)
        self.addItem(self._line, ignoreBounds=True)
        self._tag = pg.TextItem("", color=_LINE_PEN, anchor=(0, 0),
                                fill=pg.mkBrush(11, 14, 20, 170))
        self._tag.setVisible(False)
        self.addItem(self._tag, ignoreBounds=True)

        self._shape = (0, 0)      # (行=纵轴, 列=横轴)，当前显示数组
        self._full = (0, 0)       # 抽稀前的原始网格尺寸
        self._extent = (0.0, 1.0, 0.0, 1.0)
        self._wiggle_color = _DEFAULT_WIGGLE_COLOR
        self._press: QtCore.QPointF | None = None

    # ------------------------------------------------------------ 数据
    def set_slice(self, img: np.ndarray, extent: tuple[float, float, float, float],
                  cmap: str, clim: tuple[float, float],
                  xlabel: str, ylabel: str,
                  full_shape: tuple[int, int] | None = None,
                  wiggle: int = 0, gain: float = 1.0,
                  wiggle_color: tuple[int, int, int, int] | None = None) -> np.ndarray:
        """显示一个切片；``full_shape`` 是抽稀前的原始尺寸，用于把点击位置映射回原网格。"""
        rows, cols = img.shape
        # 几何没变（同一模式换切片、只改色标/AGC/wiggle）时**不能**重置视野，
        # 否则放大看细节时一调参数就被拉回全图。只有换了一整幅几何才复位。
        same_geom = self._extent == extent and self._shape[0] > 0
        self._shape = (rows, cols)
        self._full = full_shape or (rows, cols)
        self._extent = extent
        self._wiggle_color = wiggle_color or _DEFAULT_WIGGLE_COLOR

        rgba = render.to_rgba(img, cmap, clim)
        self._img.setImage(rgba, autoLevels=False, levels=None)
        x0, x1, y0, y1 = extent
        self._img.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))

        if not same_geom:
            self._fit_range()
        self.setLabel("bottom", xlabel)
        self.setLabel("left", ylabel)
        self._update_wiggles(img, wiggle, gain, clim)

    def _fit_range(self) -> None:
        """把视野复位到整幅数据。

        先一次性设好范围限制再 setRange：分两次 setXRange/setYRange 时，
        中间那一瞬间的范围可能不合法（尤其在不同模式之间跨度相差上千倍时），
        会把视图留在错误状态。
        """
        x0, x1, y0, y1 = self._extent
        vb = self.getViewBox()
        vb.setLimits(xMin=x0, xMax=x1, yMin=y0, yMax=y1)
        vb.disableAutoRange()
        vb.setRange(rect=QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), padding=0.0)

    def slice_shape(self) -> tuple[int, int]:
        return self._shape

    def _update_wiggles(self, img: np.ndarray, want: int, gain: float,
                        clim: tuple[float, float]) -> None:
        for item in self._wiggles:
            self.removeItem(item)
        self._wiggles.clear()
        if want <= 0:
            return
        pen = pg.mkPen(self._wiggle_color, width=1)
        for xs, ys in render.wiggle_curves(img, self._extent, clim, want, gain):
            item = pg.PlotDataItem(xs, ys, pen=pen)
            self.addItem(item, ignoreBounds=True)
            self._wiggles.append(item)

    # ------------------------------------------------------------ 交互
    def _to_cell(self, view_pos: QtCore.QPointF) -> tuple[int, int] | None:
        rows, cols = self._full
        if rows == 0 or cols == 0:
            return None
        x0, x1, y0, y1 = self._extent
        fx = (view_pos.x() - x0) / (x1 - x0) if x1 > x0 else 0.0
        fy = (view_pos.y() - y0) / (y1 - y0) if y1 > y0 else 0.0
        col = int(np.clip(fx * cols, 0, cols - 1))
        row = int(np.clip(fy * rows, 0, rows - 1))
        return col, row

    def mouseMoveEvent(self, ev) -> None:
        super().mouseMoveEvent(ev)
        cell = self._to_cell(self.mapToView(ev.position()))
        if cell is not None:
            self.hovered.emit(cell[0], cell[1])

    def mousePressEvent(self, ev) -> None:
        self._press = (ev.position()
                       if ev.button() == QtCore.Qt.MouseButton.LeftButton and self._shape[0]
                       else None)
        super().mousePressEvent(ev)            # 交给 ViewBox 做平移

    def mouseReleaseEvent(self, ev) -> None:
        """左键"按下-抬起几乎没动"才算取点。

        拖动是平移，若在按下时就取点，每次拖完都会顺手把下方单道波形换掉。
        """
        pressed, self._press = self._press, None
        if (pressed is not None
                and ev.button() == QtCore.Qt.MouseButton.LeftButton
                and (ev.position() - pressed).manhattanLength() <= _CLICK_SLOP):
            cell = self._to_cell(self.mapToView(ev.position()))
            if cell is not None:
                self.picked.emit(cell[0], cell[1])
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:
        """双击复位视野（放大看细节之后不用去别处找按钮）。"""
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = None                 # 别让随后的 release 又取一次点
            self._fit_range()
        super().mouseDoubleClickEvent(ev)

    def set_reference(self, value: float | None, text: str | None = None) -> None:
        """在剖面上标出下方单道波形取自哪一道。

        ``value`` 是横轴上的位置，``text`` 是要贴在线上的说明（如 ``S=200 R=200``）。
        传 ``None`` 表示整体隐藏（例如单道面板被收起时）。
        """
        if value is None:
            self._line.setVisible(False)
            self._tag.setVisible(False)
            return
        self._line.setValue(value)
        self._line.setVisible(True)
        if not text:
            self._tag.setVisible(False)
            return
        x0, x1, y0, y1 = self._extent
        self._tag.setText(text)
        self._tag.setPos(value + (x1 - x0) * 0.004, y0 + (y1 - y0) * 0.012)
        self._tag.setVisible(True)

    def reset(self) -> None:
        """清空显示内容。

        注意：这里刻意**不用** ``clear`` 作为方法名 —— ``PlotWidget.__init__`` 会把
        ``plotItem.clear`` 等一批方法直接塞进实例 ``__dict__``，任何子类同名方法都会
        被它遮蔽；而 ``PlotItem.clear()`` 会把已加入的图元从场景中移除且无法再回来。
        """
        self._shape = (0, 0)
        self._img.clear()
        for item in self._wiggles:
            self.removeItem(item)
        self._wiggles.clear()
        self._line.setVisible(False)
        self._tag.setVisible(False)