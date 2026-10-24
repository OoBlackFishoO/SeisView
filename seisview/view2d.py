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

import re
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import icons, render, style
from .figure_options import ExportFigureOptions

# 叠加波形的默认颜色：地震剖面上惯用黑色（底色多为白/红/蓝，黑色最跳）
_DEFAULT_WIGGLE_COLOR = "#111827"

# 判定"点击"（而非拖动）的位移上限，单位像素
_CLICK_SLOP = 4

# 线型：与「线型」分组里的选项一一对应
_PEN_STYLES = {
    "dash": QtCore.Qt.PenStyle.DashLine,
    "dot": QtCore.Qt.PenStyle.DotLine,
    "dashdot": QtCore.Qt.PenStyle.DashDotLine,
}


def line_pen(style_pair: tuple[str, str], width: float = 1.4):
    """``(颜色, 线型)`` → pyqtgraph 画笔。

    全项目只有这一处把"线型选项"翻译成画笔，保证面板上的曲线、剖面上叠加的
    wiggle、导出图三者看起来完全一致。
    """
    color, dash = style_pair
    pen = pg.mkPen(color, width=width)
    pen.setStyle(_PEN_STYLES.get(dash, QtCore.Qt.PenStyle.SolidLine))
    # 平头笔帽：虚线不会因方头笔帽向两端各伸长半个线宽，空位才是名义上的
    # 4:2 / 1:2 / 4:2:1:2（按线宽计），与传统制图线型一致。
    pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
    return pen


def line_swatch_pixmap(style_pair: tuple[str, str], w: int = 24, h: int = 10):
    """画一条与实际曲线同色同线型的小横线，贴在标题旁边当图例。"""
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    try:
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(line_pen(style_pair, 2.0))
        painter.drawLine(1, h // 2, w - 2, h // 2)
    finally:
        painter.end()
    return pm


# 单道波形取自哪一道的提示线用**竖线**（angle=90）。
# 注意 angle=0 是横线，setValue 会去设 y 值 —— 两个轴量纲不同时线会跑到
# 视野外面（之前那根"莫名其妙的绿线"就是这么来的）。
# 颜色**现取** style.OK，不固化成常量：换主题时 restyle() 会重新刷上。
def _line_pen():
    return pg.mkPen(style.OK, width=1)


def _tag_brush():
    """提示线文字标签的底：当前主题的画布底色 + 一点透明度。"""
    c = QtGui.QColor(style.GL_BG)
    c.setAlpha(190)
    return pg.mkBrush(c)


# 屏幕曲线的颜色：按数据顺序取，与剖面板标题、右上角胶囊用的是同一套
# "数据识别色"，一眼能对上"哪条线是哪份数据"。
# 它**跟着主题走**：深色主题用亮色、浅色主题用深色（`style.SCREEN_LINES`）。
# 注意这和「导出线型」是两回事 —— 导出图（白底论文用图）用用户配的黑/红/蓝线型，
# 见 main_window.line_styles。
def screen_line_colors() -> tuple[str, ...]:
    return tuple(style.SCREEN_LINES)


def screen_line_styles(n: int) -> list[tuple[str, str]]:
    """屏幕要用的 (颜色, 线型)：一律实线，只用颜色区分数据源。"""
    colors = screen_line_colors()
    return [(colors[i % len(colors)], "solid") for i in range(max(0, n))]


class _HoverLabel(QtWidgets.QLabel):
    """剖面右上角的坐标读数。

    关键约束：**文本变化不能改变布局尺寸**。普通 QLabel 的 sizeHint 会随文字长度
    增长，在对比模式下会顶宽当前面板、把旁边的剖面挤窄（鼠标指到哪幅、哪幅就变大）。
    这里把 sizeHint 钉成固定首选宽度、minimumSizeHint 钉成 0，文字过长时自动省略，
    布局就完全不受悬停内容影响。
    """

    PREFERRED_WIDTH = 190

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = "—"
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                          | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.setText("—")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                           QtWidgets.QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QtCore.QSize:                 # noqa: N802
        return QtCore.QSize(self.PREFERRED_WIDTH,
                            self.fontMetrics().height() + 2)

    def minimumSizeHint(self) -> QtCore.QSize:          # noqa: N802
        return QtCore.QSize(0, self.fontMetrics().height() + 2)

    def set_full_text(self, text: str) -> None:
        self._full = str(text)
        self.setToolTip(self._full)
        self._apply_elide()

    def resizeEvent(self, ev) -> None:                  # noqa: N802
        super().resizeEvent(ev)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(0, self.width() - 2)
        text = self.fontMetrics().elidedText(
            self._full, QtCore.Qt.TextElideMode.ElideRight, width)
        if text != self.text():
            self.setText(text)


class SliceView(pg.PlotWidget):
    """一个切片面的显示控件。"""

    picked = QtCore.Signal(int, int)            # (列号, 行号)，原始数据网格索引
    hovered = QtCore.Signal(int, int)           # (列号, 行号)，原始数据网格索引
    hover_left = QtCore.Signal()               # 鼠标离开画面 / 移到复位按钮上
    doubleClicked = QtCore.Signal()            # 双击复位视野（先发信号、再复位）
    referenceDragged = QtCore.Signal(int)      # 拖动绿线：新的横向列号
    traceStepped = QtCore.Signal(int)          # 聚焦时 ←/→：目标道 ±1

    def __init__(self, parent=None):
        super().__init__(parent, background=style.GL_BG)
        self.setMenuEnabled(False)
        self.setMouseEnabled(x=True, y=True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        vb = self.getViewBox()
        vb.setDefaultPadding(0.0)
        vb.invertY(True)
        vb.setMouseMode(pg.ViewBox.PanMode)     # 左键拖动平移，滚轮缩放

        self._img = pg.ImageItem(axisOrder="row-major", autoDownsample=False)
        self.addItem(self._img)

        # 左下角那个 "A" 是 pyqtgraph 自带的自动范围按钮。把它改造成“复位视野”，
        # 并且下面会阻止它被误判成一次取道（绿线错位的根因）。
        self._fit_btn = self.getPlotItem().autoBtn
        try:
            self._fit_btn.setToolTip("复位视野")
            self._fit_btn.clicked.disconnect()
        except (RuntimeError, TypeError):        # pragma: no cover
            pass
        self._fit_btn.clicked.connect(self._fit_range)

        # 单道波形取自哪一道的提示线：竖线 + 文字标签
        self._wiggles: list[pg.PlotDataItem] = []
        self._line = pg.InfiniteLine(angle=90, movable=False, pen=_line_pen())
        self._line.setVisible(False)
        self.addItem(self._line, ignoreBounds=True)
        self._tag = pg.TextItem("", color=style.OK, anchor=(0, 0), fill=_tag_brush())
        self._tag.setVisible(False)
        self.addItem(self._tag, ignoreBounds=True)

        self._shape = (0, 0)      # (行=纵轴, 列=横轴)，当前显示数组
        self._full = (0, 0)       # 抽稀前的原始网格尺寸
        self._extent = (0.0, 1.0, 0.0, 1.0)
        self._press: QtCore.QPointF | None = None
        self._ref_drag = False
        self._ref_last_col: int | None = None
        self._ink = style.TEXT_DIM
        self._grid_on = True
        self._apply_style(grid=True)

    # ------------------------------------------------------------ 数据
    def set_slice(self, img: np.ndarray, extent: tuple[float, float, float, float],
                  cmap: str, clim: tuple[float, float],
                  xlabel: str, ylabel: str,
                  full_shape: tuple[int, int] | None = None,
                  wiggle: int = 0, gain: float = 1.0,
                  wiggle_sets: list | None = None,
                  show_image: bool = True,
                  grid: bool = True) -> np.ndarray:
        """显示一个切片；``full_shape`` 是抽稀前的原始尺寸，用于把点击位置映射回原网格。

        ``show_image=False`` 时只画 wiggle 曲线（"仅显示波形"模式）：密度图隐藏，
        但几何仍按同一范围摆放，视图缩放与取点逻辑不受影响。
        ``wiggle_sets`` 是 ``[(切片, 色标, 幅度缩放, (颜色, 线型)), ...]`` —— 多数据
        对比时把各数据源的曲线按各自颜色叠在同一张剖面上。

        **屏幕永远是深底**：白底"论文用图"由导出的离屏绘图负责（``build_*_figure``），
        不在这条路径上 —— 这样屏上观感统一，也不会出现"屏上白底、导出台面"两套规则。
        """
        rows, cols = img.shape
        # 几何没变（同一模式换切片、只改色标/AGC/wiggle）时**不能**重置视野，
        # 否则放大看细节时一调参数就被拉回全图。只有换了一整幅几何才复位。
        same_geom = self._extent == extent and self._shape[0] > 0
        self._shape = (rows, cols)
        self._full = full_shape or (rows, cols)
        self._extent = extent

        self._apply_style(grid)
        rgba = render.to_rgba(img, cmap, clim)
        self._img.setImage(rgba, autoLevels=False, levels=None)
        self._img.setVisible(show_image)
        x0, x1, y0, y1 = extent
        self._img.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))

        if not same_geom:
            self._fit_range()
        self.setLabel("bottom", xlabel, color=self._ink)
        self.setLabel("left", ylabel, color=self._ink)
        self._update_wiggles(wiggle_sets, wiggle, gain)

    def _apply_style(self, grid: bool) -> None:
        """画布底的外观：底色、网格、坐标轴文字色一次切好。

        颜色必须显式设 —— pyqtgraph 默认前景是黑色，在深色主题里等于看不见；
        浅色主题又反过来需要深色文字。所以这里每次都用**当前**主题色重设一遍。
        """
        self.setBackground(style.GL_BG)
        self._ink = style.TEXT_DIM
        want_grid = bool(grid)
        if want_grid != self._grid_on:
            self._grid_on = want_grid
            self.showGrid(x=want_grid, y=want_grid, alpha=0.14)
        for side in ("bottom", "left"):
            try:
                axis = self.getAxis(side)
                axis.setTextPen(pg.mkPen(self._ink))
                axis.setPen(pg.mkPen(self._ink))
            except Exception:                        # pragma: no cover
                pass

    def restyle(self) -> None:
        """换主题：底色 / 坐标轴 / 提示线与标签全部重刷。

        提示线那一对（``_line`` / ``_tag``）没有单独改色的接口，直接换一对新的，
        可见性与当前值照抄过来，免得换主题把提示线弄丢。
        """
        self._apply_style(self._grid_on)
        line_on, tag_on = self._line.isVisible(), self._tag.isVisible()
        self.removeItem(self._line)
        self.removeItem(self._tag)
        self._line = pg.InfiniteLine(angle=90, movable=False, pen=_line_pen())
        self._tag = pg.TextItem("", color=style.OK, anchor=(0, 0), fill=_tag_brush())
        self.addItem(self._line, ignoreBounds=True)
        self.addItem(self._tag, ignoreBounds=True)
        self._line.setVisible(line_on)
        self._tag.setVisible(tag_on)

    def _fit_range(self) -> None:
        """把视野复位到整幅数据。

        先一次性设好范围限制再 setRange：分两次 setXRange/setYRange 时，
        中间那一瞬间的范围可能不合法（尤其在不同模式之间跨度相差上千倍时），
        会把视图留在错误状态。

        实测 ``setRange`` 的结果与控件当前尺寸无关（它存的是数据坐标范围，
        像素映射是绘制时才换算的），所以这里可以放心在布局完成前调用 ——
        反过来"等尺寸够了再复位"才会留下一帧默认视野，看起来就是抖一下。
        """
        x0, x1, y0, y1 = self._extent
        vb = self.getViewBox()
        vb.setLimits(xMin=x0, xMax=x1, yMin=y0, yMax=y1)
        vb.disableAutoRange()
        vb.setRange(rect=QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), padding=0.0)

    def slice_shape(self) -> tuple[int, int]:
        return self._shape

    def _update_wiggles(self, sets: list | None, want: int, gain: float) -> None:
        """画叠加波形；``sets`` = ``[(切片, 色标, 幅度缩放, (颜色, 线型)), ...]``。

        多数据对比时会有多组 —— 每组用自己的颜色/线型，叠在同一张剖面上，
        和单道波形面板的叠加方式保持一致。
        """
        for item in self._wiggles:
            self.removeItem(item)
        self._wiggles.clear()
        if want <= 0 or not sets:
            return
        for img, clim, scale, style_pair in sets:
            pen = line_pen(style_pair, 1.2)
            for xs, ys in render.wiggle_curves(img, self._extent, clim, want, gain, scale):
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

    def _on_plot_button(self, pos: QtCore.QPointF) -> bool:
        """控件坐标是否落在 pyqtgraph 的复位按钮上（点按钮不能算取道）。

        **不能要求按钮当前可见**：按钮只在鼠标悬停时才显示，按下那一刻可能还没
        来得及显示。几何位置始终固定在左下角，按位置判断才可靠。
        """
        btn = getattr(self, "_fit_btn", None)
        if btn is None:
            return False
        try:
            scene_pt = self.mapToScene(pos.toPoint())
            return btn.contains(btn.mapFromScene(scene_pt))
        except (RuntimeError, TypeError):        # pragma: no cover
            return False

    def _line_pixel_x(self) -> float | None:
        """绿线在控件坐标里的 x；线不可见时返回 None。"""
        if not self._line.isVisible():
            return None
        vb = self.getViewBox()
        y0 = vb.viewRange()[1][0]
        scene = vb.mapViewToScene(QtCore.QPointF(self._line.getXPos(), y0))
        return float(self.mapFromScene(scene).x())

    def _on_reference_line(self, pos: QtCore.QPointF) -> bool:
        x = self._line_pixel_x()
        return x is not None and abs(pos.x() - x) <= 6.0

    def keyPressEvent(self, ev) -> None:                # noqa: N802 （Qt 接口名）
        if (ev.modifiers() == QtCore.Qt.KeyboardModifier.NoModifier
                and ev.key() in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right)
                and self._line.isVisible()):
            self.traceStepped.emit(
                -1 if ev.key() == QtCore.Qt.Key.Key_Left else 1)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._ref_drag:
            cell = self._to_cell(self.mapToView(ev.position()))
            if cell is not None and cell[0] != self._ref_last_col:
                self._ref_last_col = cell[0]
                self.referenceDragged.emit(cell[0])
            return
        super().mouseMoveEvent(ev)
        if self._on_plot_button(ev.position()):
            # 指针停在复位按钮上时没有“剖面坐标”可言，别让右上角读数停在按钮位置
            self.hover_left.emit()
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor
                       if self._on_reference_line(ev.position())
                       else QtCore.Qt.CursorShape.ArrowCursor)
        cell = self._to_cell(self.mapToView(ev.position()))
        if cell is not None:
            self.hovered.emit(cell[0], cell[1])

    def mousePressEvent(self, ev) -> None:
        on_btn = self._on_plot_button(ev.position())
        is_left = ev.button() == QtCore.Qt.MouseButton.LeftButton
        if (is_left and not on_btn and self._on_reference_line(ev.position())):
            # 拖动绿线：不启动视野平移，也不要在松手时被当成一次取道
            self._ref_drag = True
            self._ref_last_col = None
            self._press = None
            self.setFocus()
            return
        self._press = (ev.position()
                       if (is_left and self._shape[0] and not on_btn)
                       else None)
        if on_btn and is_left:
            # 按钮可能还没因悬停而显示出来；这里主动复位一次，保证“按了就复位”，
            # 且绝不会被后面的 release 当成取道。
            self._fit_range()
        if is_left:
            self.setFocus()
        super().mousePressEvent(ev)            # 交给 ViewBox 做平移

    def mouseReleaseEvent(self, ev) -> None:
        """左键"按下-抬起几乎没动"才算取点。

        拖动是平移，若在按下时就取点，每次拖完都会顺手把下方单道波形换掉。
        按在复位按钮上的那次点击不算 —— 否则复位会顺手把绿线挪到左下角。
        """
        if self._ref_drag:
            cell = self._to_cell(self.mapToView(ev.position()))
            self._ref_drag = False
            self._ref_last_col = None
            if cell is not None:
                self.referenceDragged.emit(cell[0])
            return
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
            self.doubleClicked.emit()          # 主窗口据此撤销第一次 release 的取道
            self._fit_range()
        super().mouseDoubleClickEvent(ev)

    def leaveEvent(self, ev) -> None:          # noqa: N802 （Qt 接口名）
        super().leaveEvent(ev)
        self.hover_left.emit()

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
        self._full = (0, 0)
        self._img.clear()
        self._img.setVisible(True)
        for item in self._wiggles:
            self.removeItem(item)
        self._wiggles.clear()
        self._line.setVisible(False)
        self._tag.setVisible(False)
        self.hover_left.emit()


# ==================================================================== 剖面对比面板
class SlicePanel(QtWidgets.QFrame):
    """一个数据集对应的剖面面板：标题行（抓手 + 线型图例 + 数据源名 + 读数）+ 剖面视图。

    多数据对比时并排出现若干块，每块标题带数据源识别色，方便一眼对上哪块是哪份数据。
    单份数据时不显示标题文字（只保留读数），避免和上方面板标题重复。

    标题行 ``header`` 是一个独立控件：主窗口在它上面挂**拖动**监听（拉出为独立窗口 /
    拖到另一块上交换顺序），所以这里不实现任何鼠标逻辑，只负责长这个样子。
    """

    picked = QtCore.Signal(int, int)            # (列号, 行号)
    hovered = QtCore.Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self.header = QtWidgets.QWidget()
        self.header.setMouseTracking(True)
        head = QtWidgets.QHBoxLayout(self.header)
        head.setContentsMargins(2, 0, 2, 0)
        head.setSpacing(6)
        # 抓手：这是"这里能拖"的唯一提示（不加 tooltip、不加状态栏提示）
        self.grab_handle = QtWidgets.QLabel()
        self.grab_handle.setFixedSize(14, 14)
        self.grab_handle.setPixmap(icons.grab(14, style.TEXT_MUTE))
        head.addWidget(self.grab_handle)
        # 线型小图例：一眼看出这块面板上的曲线是用哪种颜色/线型画的
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedSize(24, 10)
        self.swatch.setVisible(False)
        head.addWidget(self.swatch)
        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("PanelTitle")
        head.addWidget(self.title)
        head.addStretch(1)
        self.hover = _HoverLabel()
        self.hover.setObjectName("Value")
        head.addWidget(self.hover)
        lay.addWidget(self.header)

        self.view = SliceView()
        self.view.picked.connect(self.picked)
        self.view.hovered.connect(self.hovered)
        self.view.hover_left.connect(self.reset_hover)
        lay.addWidget(self.view, 1)
        self.set_title("", show=False)
        self.set_reorder_affordance(False)

    def set_title(self, text: str, color: tuple[int, int, int, int] | None = None,
                  show: bool = True,
                  line_style: tuple[str, str] | None = None) -> None:
        self.title.setText(text)
        self.title.setVisible(bool(show) and bool(text))
        if color:
            self.title.setStyleSheet(f"color: rgb({color[0]}, {color[1]}, {color[2]});")
        else:
            self.title.setStyleSheet("")
        if line_style is None:
            self.swatch.setVisible(False)
        else:
            self.swatch.setPixmap(line_swatch_pixmap(line_style))
            self.swatch.setVisible(True)

    def set_hover(self, text: str) -> None:
        self.hover.set_full_text(text)

    def reset_hover(self) -> None:
        """鼠标离开画面：用破折号表示“无坐标”（0 是合法坐标，不能拿来占位）。"""
        self.hover.set_full_text("—")

    def set_reorder_affordance(self, on: bool) -> None:
        """对比模式才显示“换序”抓手；单数据时这里不该出现第二个六点。

        抓手换成 ``⇄`` 图标（而不是六点），明确它只负责交换数据顺序，
        整块移动/拉出统一由上方「剖面」组标题的六点承担。
        """
        if getattr(self, "_reorder_on", None) == bool(on):
            return
        self._reorder_on = bool(on)
        self.grab_handle.setVisible(bool(on))
        if on:
            self.grab_handle.setPixmap(icons.swap(14, style.TEXT_MUTE))
            self.grab_handle.setToolTip("拖动 = 交换对比数据顺序")
            self.header.setToolTip("")
            self.header.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        else:
            self.header.setToolTip("")
            self.header.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

    def reset_view_state(self) -> None:
        """清空数据时把这一块彻底复位：图、叠加曲线、绿线、标题与坐标读数。"""
        self.view.reset()
        self.reset_hover()
        self.set_title("", show=False)

    def restyle(self) -> None:
        """换主题：抓手图标、画布重刷一遍。

        标题色与线型小图例由主窗口在重画时一并写好（它手里才有"这份数据用哪种颜色"），
        这里不重复设，免得和那份状态打架。
        """
        # 单数据时抓手是隐藏的；对比模式下必须保持换序用的 ⇄ 图标，
        # 不能被换主题统一重刷成六点（否则又出现两套一样的抓手）。
        if getattr(self, "_reorder_on", False):
            self.grab_handle.setPixmap(icons.swap(14, style.TEXT_MUTE))
        else:
            self.grab_handle.setPixmap(icons.grab(14, style.TEXT_MUTE))
        self.view.restyle()


# ================================================================ 论文用图导出
# 与屏幕上的交互面板不是一回事：这里**从数据重新画一张图**，白底、深色坐标轴，
# 横纵轴的读数直接用真实的 dt / dx / ds 换算成秒 / 米，导出 PNG（位图）或
# SVG（矢量），可以直接插进论文。
#
# 为什么不在控件上截屏：截屏会带上界面主题的面板底色、工具栏和当前的缩放平移，
# 那是"软件界面截图"，不是"论文用图"。
# **屏幕跟着主题走、导出永远白底**：这套白底配色只给这一节里的离屏绘图用，
# 屏幕上的 SliceView / TraceView 用的是当前主题的画布底色（见 style.GL_BG），
# 换成浅色主题时它们也会变白 —— 但导出图**不受主题影响**，永远是这一套。
_FIG_BG = style.PAPER_BG
_FIG_INK = style.PAPER_INK
# 叠加图里每条曲线的图例名（按数据顺序）。英文：期刊字体一般不保证中文字形。
FIGURE_CODE_LABELS = ["Data 1", "Data 2", "Data 3", "Data 4"]


def _pg_colormap(name: str) -> "pg.ColorMap":
    """把本项目的色带转成 pyqtgraph 的 ColorMap，供色条使用。

    **颜色要按 0–255 传**：pyqtgraph 的 ``ColorMap`` 内部用 ``mkColor`` 解析每个
    颜色，它把序列当成 0–255 的通道值。之前这里先把 uint8 除以 255 变成 0–1，
    再被 pyqtgraph 除一次，结果整条色条都画成了黑色（数值也对不上）。
    """
    lut = render.lut(name, 256)
    return pg.ColorMap(np.linspace(0.0, 1.0, len(lut)), lut[:, :3])


def _figure_background(options: ExportFigureOptions):
    if options.transparent:
        return QtGui.QColor(0, 0, 0, 0)
    return QtGui.QColor(_FIG_BG)


class _PaperAxis(pg.AxisItem):
    """论文图坐标轴：轴标题与刻度数字之间额外留出一段距离。

    pyqtgraph 默认把轴标题紧贴在刻度数字外侧（几乎零间距）。这里在
    自动尺寸的基础上加一段固定留白，标题会继续贴在图幅外沿，中间的空隙
    就是论文插图里常见的那个间隔。

    ``force_edges=True`` 时，在轴的两端各补一个刻度（即使它不落在用户设定的
    刻度间隔上）。自定义间隔（例如 80 m 一档、量程 900 m）最后会停在 880，
    900 就既没有刻度线也没有数字；补上端点后两端的数值一定看得见。
    """

    def __init__(self, orientation: str, *args, label_gap: int = 0,
                 force_edges: bool = False, **kwargs):
        self._label_gap = max(0, int(label_gap))
        self._force_edges = bool(force_edges)
        super().__init__(orientation, *args, **kwargs)

    def _updateHeight(self) -> None:
        super()._updateHeight()
        if (self.fixedHeight is None and self.label is not None
                and self.label.isVisible()):
            h = self.maximumHeight() + self._label_gap
            self.setMaximumHeight(h)
            self.setMinimumHeight(h)

    def _updateWidth(self) -> None:
        super()._updateWidth()
        if (self.fixedWidth is None and self.label is not None
                and self.label.isVisible()):
            w = self.maximumWidth() + self._label_gap
            self.setMaximumWidth(w)
            self.setMinimumWidth(w)

    def tickValues(self, minVal, maxVal, size):
        """补上轴两端的刻度值；已经落在端点上的不重复添加。"""
        levels = super().tickValues(minVal, maxVal, size)
        if not self._force_edges or not levels:
            return levels
        lo, hi = sorted((float(minVal), float(maxVal)))
        if hi <= lo:
            return levels
        spacing, values = levels[0]
        eps = max(1e-9, (hi - lo) * 1e-6)
        extra = [v for v in (lo, hi)
                 if all(abs(v - float(x)) > eps for x in values)]
        if not extra:
            return levels
        vals = sorted([float(x) for x in values] + extra)
        vals = self._drop_crowded(vals, lo, hi, size, spacing)
        levels = list(levels)
        levels[0] = (spacing, vals)
        return levels

    def _drop_crowded(self, vals: list[float], lo: float, hi: float,
                      size: float, spacing: float) -> list[float]:
        """端点刻度挤到相邻刻度时，删掉相邻的那个，避免数字叠在一起。

        是否挤在一起按实际字号量出来，而不是拍一个固定的比例：论文图里
        数字比刻度间距还宽的情况并不少见。
        """
        if size <= 0 or len(vals) < 2:
            return vals
        slot = abs(size / (hi - lo))
        font = self.style.get("tickFont") or QtGui.QFont()
        metrics = QtGui.QFontMetricsF(font)

        def extent(value: float) -> float:
            try:
                text = self.tickStrings(
                    [value], self.autoSIPrefixScale * self.scale, spacing)[0]
            except Exception:                    # pragma: no cover
                return 0.0
            if self.orientation in ("left", "right"):
                return metrics.height()
            return metrics.horizontalAdvance(text)

        def pos(value: float) -> float:
            return (value - lo) * slot

        out = list(vals)
        for edge, inner in ((out[-1], -2), (out[0], 1)):
            while len(out) >= 2:
                neighbor = out[inner]
                if ((abs(neighbor - lo) <= abs(hi - lo) * 1e-6
                     or abs(neighbor - hi) <= abs(hi - lo) * 1e-6)
                        and neighbor != edge):
                    break                        # 另一端也是端点：两个都保留
                limit = (extent(edge) + extent(neighbor)) / 2.0 + 1.0
                if abs(pos(edge) - pos(neighbor)) >= limit:
                    break
                out.pop(inner)
        return out


def _figure_plot(options: ExportFigureOptions, px_w: int,
                 px_h: int) -> pg.PlotWidget:
    """建一个论文图专用的 PlotWidget：四边坐标轴、只保留主刻度。"""
    gap = max(4, int(round(1.5 / 25.4 * options.dpi)))
    axes = {side: _PaperAxis(
                side, label_gap=gap,
                force_edges=(options.x_edge_ticks if side in ("bottom", "top")
                             else options.y_edge_ticks))
            for side in ("left", "right", "top", "bottom")}
    plot = pg.PlotWidget(background=_figure_background(options), axisItems=axes)
    plot.setMenuEnabled(False)
    plot.resize(px_w, px_h)
    _apply_figure_margins(plot, options)
    for side in ("left", "bottom", "top", "right"):
        plot.showAxis(side)
        axis = plot.getAxis(side)
        axis.setStyle(maxTickLevel=0, maxTextLevel=0)
        axis.setZValue(10)                     # 刻度压在图上面，内刻度才看得见
    return plot


def _figure_font(options: ExportFigureOptions, out_fmt: str) -> QtGui.QFont:
    """PNG / SVG 都用像素字号。

    SVG 的用户单位就是场景像素（根节点 viewBox = 目标像素尺寸），
    用磅值会被 QSvgGenerator 再按屏幕 DPI 换算一次，物理字号缩到约 1/3。
    这里统一按 ``font_px``（= pt × DPI / 72）给，落到毫米上才是真正的 font_pt。
    """
    font = QtGui.QFont(options.font_family)
    font.setPixelSize(options.font_px())
    return font


def _figure_css_size(options: ExportFigureOptions, out_fmt: str) -> str:
    """坐标轴标题 / 图例 / 图标题用的字号（场景像素，PNG 与 SVG 同一口径）。"""
    return f"{options.font_px()}px"


def _figure_title_args(options: ExportFigureOptions, out_fmt: str) -> dict:
    return {"color": _FIG_INK, "family": options.font_family,
            "size": _figure_css_size(options, out_fmt)}


def _figure_label_args(options: ExportFigureOptions, out_fmt: str) -> dict:
    """AxisItem 的标签走 CSS，键名必须是带连字符的 CSS 属性名。"""
    return {"color": _FIG_INK, "font-family": options.font_family,
            "font-size": _figure_css_size(options, out_fmt)}


def apply_figure_typography(plot,
                            options: ExportFigureOptions,
                            out_fmt: str = "png") -> None:
    """把字体族与字号应用到坐标轴刻度与图例。

    轴标题与图标题由 ``setLabel`` / ``setTitle`` 的 CSS 参数直接设定 ——
    ``LabelItem`` 内部是一个独立的 ``QGraphicsTextItem``，调用 ``setFont``
    并不会改到它，必须走 HTML 的 ``font-size`` / ``font-family``。
    """
    font = _figure_font(options, out_fmt)
    item = plot.getPlotItem() if hasattr(plot, "getPlotItem") else plot
    for side in ("bottom", "left", "right", "top"):
        try:
            item.getAxis(side).setStyle(tickFont=font)
        except Exception:                        # pragma: no cover
            pass
    try:
        legend = item.legend
        if legend is not None:
            size = _figure_css_size(options, out_fmt)
            # pyqtgraph 的 setLabelTextSize 只改 opts、不重排已有文字，
            # 这里逐条重设一遍，保证图例字号真的变了。
            for _sample, label in legend.items:
                try:
                    label.setText(label.text, size=size, color=_FIG_INK)
                except Exception:                # pragma: no cover
                    pass
    except Exception:                            # pragma: no cover
        pass


_MAX_EXPLICIT_TICKS = 300


def _explicit_tick(step: float, span: float | None) -> float:
    """自定义主刻度间隔；过密（超过 ``_MAX_EXPLICIT_TICKS`` 格）回退自动刻度。

    间隔为 0 / 非法或轴跨度未知时也返回 0（= 交给 pyqtgraph 自动算）。
    """
    try:
        step = float(step or 0.0)
        span = abs(float(span)) if span is not None else 0.0
    except (TypeError, ValueError):              # pragma: no cover
        return 0.0
    if step <= 0 or span <= 0:
        return 0.0
    return step if span / step <= _MAX_EXPLICIT_TICKS else 0.0


def _figure_axes(plot: pg.PlotWidget, xlabel: str, ylabel: str,
                 options: ExportFigureOptions | None = None,
                 out_fmt: str = "png",
                 x_span: float | None = None,
                 y_span: float | None = None) -> None:
    """白底图的坐标轴：文字与刻度一律深色（**不看界面主题**，导出图固定论文白底）。

    同时关掉 pyqtgraph 的自动 SI 前缀 —— 否则会把 0.002 s 显示成「2 (x0.001)」，
    论文图里读者还得自己做乘法，不如直接给带单位的原始数值。

    轴线与刻度线按 DPI 换算成真实线宽 / 长度：pyqtgraph 默认 1 px，
    在 300 DPI 的 180 mm 图里只有 0.085 mm，缩到预览尺寸就完全看不见了。

    ``x_span`` / ``y_span`` 是轴的数值跨度，只用于判断用户的自定义刻度间隔
    会不会画出几百条刻度线；间隔过密时回退自动刻度。
    """
    opt = options or ExportFigureOptions()
    args = _figure_label_args(opt, out_fmt)
    plot.setLabel(opt.xlabel_side, xlabel, **args)
    plot.setLabel(opt.ylabel_side, ylabel, **args)
    axis_pen = pg.mkPen(_FIG_INK, width=max(1.0, opt.line_width_px()))
    raw_len = max(4, int(round(1.2 / 25.4 * opt.dpi)))
    tick_len = -raw_len if opt.ticks_inside else raw_len
    tick_gap = max(3, int(round(1.2 / 25.4 * opt.dpi)))
    # 端点（0 / 最大值）的标签会探出坐标轴矩形；容差必须够大，否则 pyqtgraph
    # 会直接把探出过多的数字丢掉。真正的“别被图幅裁掉”由
    # ``_fit_tick_labels`` 在图幅内补足留白解决，这里只负责让标签先画出来。
    allow = max(16, int(round(opt.font_px() * 3.0)))
    number_sides = (opt.x_numbers_side, opt.y_numbers_side)
    x_tick = _explicit_tick(opt.x_tick_major, x_span)
    y_tick = _explicit_tick(opt.y_tick_major, y_span)
    # pyqtgraph 的 setTitle 把标题行高写死为 30 px；14 pt @300 DPI 有 58 px，
    # 不放开就会把标题上半截裁掉。这里按字号给足行高。
    title_label = plot.getPlotItem().titleLabel
    if title_label.text and title_label.isVisible():
        title_label.setMaximumHeight(
            max(30, int(round(opt.font_px() * 1.6))))
    for side in ("bottom", "left", "top", "right"):
        try:
            axis = plot.getAxis(side)
            axis.setTextPen(pg.mkPen(_FIG_INK))
            axis.setPen(axis_pen)
            axis.setStyle(tickLength=tick_len, tickTextOffset=tick_gap,
                          maxTickLevel=0, maxTextLevel=0,
                          showValues=side in number_sides,
                          hideOverlappingLabels=allow)
            axis.enableAutoSIPrefix(False)
            # 只给一个 level：没有次刻度，只画用户指定的主刻度。
            # 注意不能写成 setTickSpacing(major=…, minor=None) —— 那会生成
            # 一个 spacing=None 的层级，pyqtgraph 计算刻度值时直接报错。
            step = x_tick if side in ("bottom", "top") else y_tick
            if step > 0:
                axis.setTickSpacing(levels=[(step, 0.0)])
        except Exception:                        # pragma: no cover
            pass
    apply_figure_typography(plot, opt, out_fmt)


def _colorbar_gap(options: ExportFigureOptions) -> int:
    """绘图区与色标条之间的留白（约 2.5 mm，按 DPI 换算成像素）。"""
    return max(8, int(round(2.5 / 25.4 * options.dpi)))


def _style_colorbar(cbar: pg.ColorBarItem, label_text: str,
                    options: ExportFigureOptions, out_fmt: str) -> None:
    """给色标条补上正确的字号与标签样式。"""
    args = _figure_label_args(options, out_fmt)
    side = "bottom" if cbar.horizontal else "left"
    try:
        if label_text:
            cbar.getAxis(side).setLabel(label_text, **args)
        raw_len = max(4, int(round(1.2 / 25.4 * options.dpi)))
        cbar.axis.setStyle(
            tickFont=_figure_font(options, out_fmt),
            tickLength=-raw_len if options.ticks_inside else raw_len,
            tickTextOffset=max(3, int(round(0.8 / 25.4 * options.dpi))),
            maxTickLevel=0, maxTextLevel=0)
        # 色标刻度也用原始数值：否则 -0.8 会被显示成 -800 再加一个 (x0.001)。
        # pyqtgraph 的 enableAutoSIPrefix(False) 不会把已缓存的缩放清回 1，
        # 这里连缓存一起复位。
        cbar.axis.enableAutoSIPrefix(False)
        cbar.axis.autoSIPrefixScale = 1.0
        cbar.axis.picture = None
        cbar.axis.update()
        axis_pen = pg.mkPen(_FIG_INK, width=max(1.0, options.line_width_px()))
        for side in ("left", "right", "top", "bottom"):
            axis = cbar.getAxis(side)
            axis.setPen(axis_pen)
            axis.setTextPen(pg.mkPen(_FIG_INK))
        if not cbar.horizontal:
            cbar.axis.setWidth(max(45, options.font_px() * 4))
    except Exception:                            # pragma: no cover
        pass


def _reserve_figure_width(plot: pg.PlotWidget, width: int) -> None:
    """在图幅右侧留一段固定宽度的空白（色标在底部时用来保持绘图区宽高比）。"""
    if width <= 2:
        return
    try:
        lay = plot.getPlotItem().layout
        spacer = QtWidgets.QGraphicsWidget()
        spacer.setMinimumSize(QtCore.QSizeF(width, 0.0))
        spacer.setMaximumSize(QtCore.QSizeF(width, 0.0))
        lay.addItem(spacer, 2, 6)
        lay.activate()
        _refresh_plot_matrices(plot)
    except Exception:                            # pragma: no cover
        pass


def _keep_bottom_colorbar_aspect(plot: pg.PlotWidget) -> None:
    """色标条在底部时，按「没有色标」时的绘图区宽高比收窄绘图区。

    底部色标只会吃掉绘图区高度；若宽度仍铺满，剖面会比无色标时更宽扁。
    这里先让布局按最终尺寸落定，再算出多出来的那截宽度，留到图幅右侧：
    绘图区保持原有比例，色标条也自动与绘图区等宽。
    """
    try:
        _show_offscreen(plot)
        pi = plot.getPlotItem()
        vb = pi.getViewBox()
        width, height = pi.size().width(), pi.size().height()
        lm, tm, rm, bm = pi.layout.getContentsMargins()
        left = pi.getAxis("left").geometry().width()
        right = pi.getAxis("right").geometry().width()
        content_w = max(1.0, width - lm - rm)
        content_h = max(1.0, height - tm - bm)
        full_w = max(1.0, content_w - left - right)
        # 顶部（标题 / 上轴）与下方横轴仍然存在，只是底部色标额外多占了一段；
        # 用「横轴顶边 - 绘图区顶边」还原没有色标时绘图区应有的高度。
        top_used = vb.geometry().top() - tm
        bottom_axis = pi.getAxis("bottom").geometry().height()
        full_h = max(1.0, content_h - top_used - bottom_axis)
        vb_h = vb.geometry().height()
        reserve = full_w * (1.0 - min(1.0, vb_h / full_h))
        _reserve_figure_width(plot, int(round(reserve)))
    except Exception:                            # pragma: no cover
        pass


def _refresh_plot_matrices(plot: pg.PlotWidget) -> None:
    """布局尺寸变化后立刻重算绘图区（含色标条）的坐标变换。

    只调 ``layout.activate()`` 是不够的：PNG 导出要等到下一次绘制才刷新，
    SVG 导出则直接读到旧变换，图像与色条会伸出绘图区。
    """
    pi = plot.getPlotItem()
    pi.getViewBox().updateMatrix()
    for pos in ((5, 1), (2, 5)):
        try:
            cbar = pi.layout.itemAt(*pos)
        except Exception:                        # pragma: no cover
            cbar = None
        if isinstance(cbar, pg.PlotItem):
            cbar.getViewBox().updateMatrix()


def _tick_label_overflows(plot: pg.PlotWidget) -> tuple[float, float, float, float]:
    """算出刻度数字探出图幅四边各多少像素（左、上、右、下）。"""
    pi = plot.getPlotItem()
    width, height = pi.size().width(), pi.size().height()
    over = [0.0, 0.0, 0.0, 0.0]
    picture = QtGui.QPicture()
    painter = QtGui.QPainter(picture)
    try:
        for side in ("left", "right", "top", "bottom"):
            try:
                axis = pi.getAxis(side)
                if not axis.isVisible() or not axis.style.get("showValues"):
                    continue
                specs = axis.generateDrawSpecs(painter)
                if not specs:
                    continue
                for rect, _flags, _text in specs[2]:
                    mapped = axis.mapRectToParent(rect)
                    over[0] = max(over[0], -mapped.left())
                    over[1] = max(over[1], -mapped.top())
                    over[2] = max(over[2], mapped.right() - width)
                    over[3] = max(over[3], mapped.bottom() - height)
            except Exception:                    # pragma: no cover
                continue
    finally:
        painter.end()
    return tuple(max(0.0, v) for v in over)


def _fit_tick_labels(plot: pg.PlotWidget,
                     options: ExportFigureOptions) -> None:
    """把探出图幅的刻度数字留在图内：扩大对应一侧的内部留白。

    **不移动刻度数字**（否则数字与刻度线对不上）。做法是把图幅外框不变、
    绘图区往里收一点，让原本落在图幅外的数字正好落进新增的留白里。
    整幅导出尺寸仍是用户设定的物理尺寸，只是绘图区略窄/略矮。
    """
    try:
        _show_offscreen(plot)
        left, top, right, bottom = _tick_label_overflows(plot)
        if max(left, top, right, bottom) <= 0.5:
            return
        pad = max(2.0, round(0.5 / 25.4 * options.dpi))
        lay = plot.getPlotItem().layout
        lm, tm, rm, bm = lay.getContentsMargins()
        lay.setContentsMargins(
            lm + (left + pad if left > 0.5 else 0.0),
            tm + (top + pad if top > 0.5 else 0.0),
            rm + (right + pad if right > 0.5 else 0.0),
            bm + (bottom + pad if bottom > 0.5 else 0.0))
        lay.activate()
        _refresh_plot_matrices(plot)
    except Exception:                            # pragma: no cover
        pass


def _figure_size(options: ExportFigureOptions, size) -> tuple[int, int]:
    if size is not None:
        return (max(1, int(size[0])), max(1, int(size[1])))
    return options.pixel_size()


def _figure_margin(options: ExportFigureOptions) -> int:
    """图幅四周的留白（约 2 mm）：期刊排版时图不会顶到版心边缘。"""
    return max(4, int(round(2.0 / 25.4 * options.dpi)))


def _apply_figure_margins(plot: pg.PlotWidget,
                          options: ExportFigureOptions) -> None:
    try:
        m = _figure_margin(options)
        plot.getPlotItem().layout.setContentsMargins(m, m, m, m)
    except Exception:                            # pragma: no cover
        pass


def _set_export_range(vb: "pg.ViewBox", x0: float, x1: float,
                      y0: float, y1: float) -> None:
    """把视野钉到数据范围上，并向两端各让一丝（约 1e-9 相对量）。

    pyqtgraph 从视图反算坐标时会引入 1e-17 量级的浮点误差：范围下限变成
    ``6.9e-17`` 而不是 0，刻度起点用 ``ceil`` 一取整就跳到了下一个刻度，
    于是“0”这个刻度整个消失。这里把范围向外扩一个肉眼不可见的量，
    保证 0 落在范围内部、刻度能正常生成。
    """
    ex = max(1e-9, abs(x1 - x0) * 1e-9)
    ey = max(1e-9, abs(y1 - y0) * 1e-9)
    vb.setLimits(xMin=x0 - ex, xMax=x1 + ex, yMin=y0 - ey, yMax=y1 + ey)
    vb.disableAutoRange()
    vb.setRange(rect=QtCore.QRectF(x0 - ex, y0 - ey,
                                   (x1 - x0) + 2 * ex, (y1 - y0) + 2 * ey),
                padding=0.0)


def build_slice_figure(img: np.ndarray, extent: tuple[float, float, float, float],
                       cmap: str, clim: tuple[float, float],
                       xlabel: str, ylabel: str, invert_y: bool = True,
                       colorbar_label: str = "Amplitude", size=None,
                       grid: bool = False,
                       options: ExportFigureOptions | None = None,
                       out_fmt: str = "png", title: str = "") -> pg.PlotWidget:
    """离屏构建一张剖面图（白底、物理坐标轴、可选色条）。

    ``title`` 由用户输入，留空就不画标题；剖面序号 / 目标道号只在设置面板里显示，
    不画进图里。
    """
    opt = options or ExportFigureOptions()
    px_w, px_h = _figure_size(opt, size)
    plot = _figure_plot(opt, px_w, px_h)
    if grid:
        plot.showGrid(x=True, y=True, alpha=0.22)
    vb = plot.getViewBox()
    vb.setDefaultPadding(0.01)
    vb.invertY(bool(invert_y))

    item = pg.ImageItem(axisOrder="row-major", autoDownsample=False)
    missing = (0, 0, 0, 0) if opt.transparent else (255, 255, 255, 255)
    item.setImage(render.to_rgba(img, cmap, clim, missing_color=missing),
                  autoLevels=False, levels=None)
    x0, x1, y0, y1 = (float(v) for v in extent)
    item.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
    plot.addItem(item)
    if title:
        plot.setTitle(title, **_figure_title_args(opt, out_fmt))
    _figure_axes(plot, xlabel, ylabel, opt, out_fmt,
                 x_span=x1 - x0, y_span=y1 - y0)

    if opt.colorbar:
        lo, hi = float(clim[0]), float(clim[1])
        bar_w = max(14, int(round(px_w * 0.022)))
        gap = _colorbar_gap(opt)
        try:
            cbar = pg.ColorBarItem(
                values=(lo, hi), colorMap=_pg_colormap(cmap),
                label=None, interactive=False, width=bar_w,
                orientation=("horizontal" if opt.colorbar_pos == "bottom"
                             else "vertical"))
            # 只把色条插到布局里，**不要** setImageItem：图像已是 RGBA。
            # 间距用"空列 / 空行"的固定尺寸实现（pyqtgraph 自己的插法）；
            # 否则关掉色标文字后色条会直接贴住图像。
            lay = plot.getPlotItem().layout
            if opt.colorbar_pos == "bottom":
                lay.addItem(cbar, 5, 1)          # 底部坐标轴下面两行
                lay.setRowFixedHeight(4, gap)
            else:
                lay.addItem(cbar, 2, 5)          # 右轴右侧
                lay.setColumnFixedWidth(4, gap)
            _style_colorbar(cbar, colorbar_label if opt.colorbar_label else "",
                            opt, out_fmt)
            if opt.colorbar_pos == "bottom":
                # 按色标自身的尺寸提示补足行高：14 pt 时 pyqtgraph 会把
                # 轴标题只按 0.8 倍高度计入，底部一截会伸出图片。
                hint_h = int(round(
                    cbar.sizeHint(QtCore.Qt.SizeHint.PreferredSize).height()))
                extra = int(round(opt.font_px() * 0.4)) + 8
                lay.setRowFixedHeight(5, max(bar_w + opt.font_px() + 12,
                                             hint_h + extra))
        except Exception:                        # pragma: no cover
            pass                                 # 色条失败不影响出图
    assert item.levels is None, "ImageItem 不应被写入 levels（否则导出会洗白）"

    _set_export_range(vb, x0, x1, y0, y1)
    # 先给刻度数字留足图内空间，再按（同样留白下的）无色标比例收窄绘图区，
    # 这样有色标 / 无色标两种出图的剖面比例一致。
    _fit_tick_labels(plot, opt)
    if opt.colorbar and opt.colorbar_pos == "bottom":
        _keep_bottom_colorbar_aspect(plot)
    return plot


def build_wiggle_figure(img: np.ndarray, extent: tuple[float, float, float, float],
                        xlabel: str, ylabel: str, sets: list,
                        n_traces: int = 60, gain: float = 1.0,
                        invert_y: bool = True,
                        labels: list[str] | None = None,
                        size=None,
                        options: ExportFigureOptions | None = None,
                        out_fmt: str = "png", title: str = "") -> pg.PlotWidget:
    """离屏构建一张"只有 wiggle 曲线"的图（白纸、无网格、无密度图）。"""
    opt = options or ExportFigureOptions()
    px_w, px_h = _figure_size(opt, size)
    plot = _figure_plot(opt, px_w, px_h)
    vb = plot.getViewBox()
    vb.setDefaultPadding(0.01)
    vb.invertY(bool(invert_y))

    legend = None
    if opt.legend and len(sets) > 1:
        try:
            legend = plot.addLegend(
                offset=(-14, 12), brush=pg.mkBrush(255, 255, 255, 215),
                pen=pg.mkPen("#BBBBBB"), labelTextColor=_FIG_INK,
                labelTextSize=_figure_css_size(opt, out_fmt))
        except Exception:                        # pragma: no cover
            legend = None
    width = opt.line_width_px()          # 场景像素：SVG 的用户单位也是场景像素
    for i, (src_img, clim, scale, style_pair) in enumerate(sets):
        pen = line_pen(style_pair, width)
        for xs, ys in render.wiggle_curves(src_img, extent, clim, n_traces, gain, scale):
            plot.plot(xs, ys, pen=pen)
        if legend is not None:
            # 图例只登记一条代理线，而不是给几十条曲线各写一行
            legend.addItem(pg.PlotDataItem([], [], pen=line_pen(style_pair, width * 1.8)),
                           (labels[i] if labels and i < len(labels)
                            else FIGURE_CODE_LABELS[i % len(FIGURE_CODE_LABELS)]))

    x0, x1, y0, y1 = (float(v) for v in extent)
    plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                 pen=pg.mkPen("#999999",
                                              width=max(1.0, opt.line_width_px() * 0.6))),
                 ignoreBounds=True)
    if title:
        plot.setTitle(title, **_figure_title_args(opt, out_fmt))
    _figure_axes(plot, xlabel, ylabel, opt, out_fmt,
                 x_span=x1 - x0, y_span=y1 - y0)
    _set_export_range(vb, x0, x1, y0, y1)
    _fit_tick_labels(plot, opt)
    return plot


def _trace_bounds(entries: list, x_range: tuple[float, float] | None):
    """按（可选）时间窗口算出波形图的 x / y 范围，y 留 6% 余量。"""
    arrays = [(np.asarray(t, dtype=float), np.asarray(a, dtype=float))
              for t, a, *_ in entries]
    arrays = [(t, a) for t, a in arrays if t.size and a.size]
    if not arrays:
        return None
    t_min = min(float(t.min()) for t, _ in arrays)
    t_max = max(float(t.max()) for t, _ in arrays)
    lo, hi = t_min, t_max
    if x_range is not None:
        try:
            a, b = (float(v) for v in x_range)
            lo, hi = max(t_min, min(a, b)), min(t_max, max(a, b))
        except (TypeError, ValueError):          # pragma: no cover
            lo, hi = t_min, t_max
        if not (hi > lo):
            lo, hi = t_min, t_max
    vals = [a[(t >= lo) & (t <= hi) & np.isfinite(a)] for t, a in arrays]
    vals = [v for v in vals if v.size]
    if not vals:
        y0, y1 = -1.0, 1.0
    else:
        y0 = min(float(np.min(v)) for v in vals)
        y1 = max(float(np.max(v)) for v in vals)
    pad = (y1 - y0) * 0.06 or 1.0
    return lo, hi, y0 - pad, y1 + pad


def build_trace_figure(entries: list, xlabel: str = "Time T (s)",
                       ylabel: str = "Amplitude", size=None,
                       options: ExportFigureOptions | None = None,
                       out_fmt: str = "png", title: str = "",
                       x_range: tuple[float, float] | None = None) -> pg.PlotWidget:
    """离屏构建一张单道波形图；``x_range`` 选定只导出哪一段（秒）。"""
    opt = options or ExportFigureOptions()
    px_w, px_h = _figure_size(opt, size)
    plot = _figure_plot(opt, px_w, px_h)
    plot.getViewBox().setDefaultPadding(0.02)
    # 图例必须在画曲线**之前**建：pyqtgraph 的图例只登记之后通过 plot(name=…)
    # 加进来的条目，反过来建就会得到一个空白的图例框。
    if opt.legend and len(entries) > 1:
        try:
            plot.addLegend(
                offset=(-14, 12), brush=pg.mkBrush(255, 255, 255, 215),
                pen=pg.mkPen("#BBBBBB"), labelTextColor=_FIG_INK,
                labelTextSize=_figure_css_size(opt, out_fmt))
        except Exception:                        # pragma: no cover
            pass
    width = opt.line_width_px()          # 场景像素：SVG 的用户单位也是场景像素
    for t, amp, style_pair, name in entries:
        plot.plot(t, amp, pen=line_pen(style_pair, width), name=name)
    plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                 pen=pg.mkPen("#999999",
                                              width=max(1.0, opt.line_width_px() * 0.6))),
                 ignoreBounds=True)
    if title:
        plot.setTitle(title, **_figure_title_args(opt, out_fmt))
    bounds = _trace_bounds(entries, x_range)
    _figure_axes(plot, xlabel, ylabel, opt, out_fmt,
                 x_span=(bounds[1] - bounds[0]) if bounds else None,
                 y_span=(bounds[3] - bounds[2]) if bounds else None)

    if bounds is not None:
        _set_export_range(plot.getViewBox(), *bounds)
    else:
        plot.enableAutoRange()
    _fit_tick_labels(plot, opt)
    return plot


def _show_offscreen(plot: pg.PlotWidget) -> None:
    if plot.isVisible():
        return
    plot.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    plot.show()
    QtWidgets.QApplication.processEvents()


def _image_exporter(plot: pg.PlotWidget, options: ExportFigureOptions):
    from pyqtgraph.exporters import ImageExporter
    exporter = ImageExporter(plot.getPlotItem())
    params = exporter.parameters()
    params["antialias"] = True
    bg = _figure_background(options)
    if options.transparent:
        bg.setAlpha(0)
    params["background"] = bg
    px_w, px_h = options.pixel_size()
    params["width"] = px_w
    params["height"] = px_h
    return exporter


def render_figure_image(plot: pg.PlotWidget,
                        options: ExportFigureOptions | None = None) -> QtGui.QImage:
    """把图渲染成 QImage（预览用，不落盘）。"""
    opt = options or ExportFigureOptions()
    _show_offscreen(plot)
    return _image_exporter(plot, opt).export(toBytes=True)


def export_figure(plot: pg.PlotWidget, path: str, fmt: str,
                  options: ExportFigureOptions | None = None) -> str:
    """把构建好的图写出 PNG / SVG（物理尺寸、DPI、透明背景、字体已生效）。"""
    opt = options or ExportFigureOptions()
    _show_offscreen(plot)
    out = str(path)
    fmt = str(fmt).lower()
    if fmt == "svg":
        from pyqtgraph.exporters import SVGExporter
        exporter = SVGExporter(plot.getPlotItem())
        params = exporter.parameters()
        px_w, px_h = opt.pixel_size()
        params["width"] = px_w
        params["height"] = px_h
        bg = _figure_background(opt)
        if opt.transparent:
            bg.setAlpha(0)
        params["background"] = bg
        xml = exporter.export(toBytes=True).decode("utf-8")
        # pyqtgraph 的 SVG 根节点通常只有 viewBox，没有 width/height；
        # 补上物理毫米尺寸，再交给排版软件时才是 1:1 的实际大小。
        match = re.search(r"<svg\b[^>]*>", xml)
        if match is not None:
            tag = match.group(0)
            tag = re.sub(r'\swidth="[^"]*"', "", tag)
            tag = re.sub(r'\sheight="[^"]*"', "", tag)
            tag = (tag[:-1]
                   + f' width="{opt.width_mm:g}mm"'
                   + f' height="{opt.height_mm:g}mm">')
            xml = xml[:match.start()] + tag + xml[match.end():]
        Path(out).write_text(xml, "utf-8")
    elif fmt == "png":
        image = _image_exporter(plot, opt).export(toBytes=True)
        dots = max(1, round(opt.dpi / 0.0254))
        image.setDotsPerMeterX(dots)
        image.setDotsPerMeterY(dots)
        if not image.save(out, "PNG"):
            raise RuntimeError(f"写不出 PNG：{out}")
    else:
        raise RuntimeError(f"不支持的图片格式：{fmt}")
    if not Path(out).exists() or Path(out).stat().st_size == 0:
        raise RuntimeError(f"图片没有成功写出：{out}")
    return out