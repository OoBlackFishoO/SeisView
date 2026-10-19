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

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import icons, render, style

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
        self._img.setVisible(True)
        for item in self._wiggles:
            self.removeItem(item)
        self._wiggles.clear()
        self._line.setVisible(False)
        self._tag.setVisible(False)


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
        self.hover = QtWidgets.QLabel("--")
        self.hover.setObjectName("Value")
        self.hover.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                | QtCore.Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.hover)
        lay.addWidget(self.header)

        self.view = SliceView()
        self.view.picked.connect(self.picked)
        self.view.hovered.connect(self.hovered)
        lay.addWidget(self.view, 1)
        self.set_title("", show=False)

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
        self.hover.setText(text)

    def restyle(self) -> None:
        """换主题：抓手图标、画布重刷一遍。

        标题色与线型小图例由主窗口在重画时一并写好（它手里才有"这份数据用哪种颜色"），
        这里不重复设，免得和那份状态打架。
        """
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
# 叠加图里每条曲线的图例名（按数据顺序）
FIGURE_CODE_LABELS = ["数据 1", "数据 2", "数据 3", "数据 4"]


def _pg_colormap(name: str) -> "pg.ColorMap":
    """把本项目的色带转成 pyqtgraph 的 ColorMap，供色条使用。

    **颜色要按 0–255 传**：pyqtgraph 的 ``ColorMap`` 内部用 ``mkColor`` 解析每个
    颜色，它把序列当成 0–255 的通道值。之前这里先把 uint8 除以 255 变成 0–1，
    再被 pyqtgraph 除一次，结果整条色条都画成了黑色（数值也对不上）。
    """
    lut = render.lut(name, 256)
    return pg.ColorMap(np.linspace(0.0, 1.0, len(lut)), lut[:, :3])


def _figure_axes(plot: pg.PlotWidget, xlabel: str, ylabel: str) -> None:
    """白底图的坐标轴：文字与刻度一律深色（**不看界面主题**，导出图固定论文白底）。

    同时关掉 pyqtgraph 的自动 SI 前缀 —— 否则会把 0.002 s 显示成「2 (x0.001)」，
    论文图里读者还得自己做乘法，不如直接给带单位的原始数值。
    """
    plot.setLabel("bottom", xlabel, color=_FIG_INK)
    plot.setLabel("left", ylabel, color=_FIG_INK)
    for side in ("bottom", "left"):
        try:
            axis = plot.getAxis(side)
            axis.setTextPen(pg.mkPen(_FIG_INK))
            axis.setPen(pg.mkPen(_FIG_INK))
            axis.enableAutoSIPrefix(False)
        except Exception:                        # pragma: no cover
            pass


def build_slice_figure(img: np.ndarray, extent: tuple[float, float, float, float],
                       cmap: str, clim: tuple[float, float],
                       xlabel: str, ylabel: str, invert_y: bool = True,
                       colorbar_label: str = "振幅", size=(1000, 760),
                       grid: bool = False) -> pg.PlotWidget:
    """离屏构建一张剖面图（白底、物理坐标轴、带色条）。

    ``img`` 的行是纵轴、列是横轴，与 ``extent`` 一一对应。
    默认**不画网格** —— 地震剖面图里网格只会盖在同相轴上，论文用图不需要。
    """
    plot = pg.PlotWidget(background=_FIG_BG)
    plot.setMenuEnabled(False)
    plot.resize(int(size[0]), int(size[1]))
    if grid:
        plot.showGrid(x=True, y=True, alpha=0.22)
    vb = plot.getViewBox()
    vb.setDefaultPadding(0.01)
    vb.invertY(bool(invert_y))

    item = pg.ImageItem(axisOrder="row-major", autoDownsample=False)
    # 坏点在白底图上要填成白色，否则会变成一块块暗斑
    item.setImage(render.to_rgba(img, cmap, clim, missing_rgba=(255, 255, 255, 255)),
                  autoLevels=False, levels=None)
    x0, x1, y0, y1 = (float(v) for v in extent)
    item.setRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
    plot.addItem(item)
    _figure_axes(plot, xlabel, ylabel)

    lo, hi = float(clim[0]), float(clim[1])
    try:
        cbar = pg.ColorBarItem(values=(lo, hi), colorMap=_pg_colormap(cmap),
                               label=colorbar_label, interactive=False, width=14)
        # 只把它插到右侧布局，**不要**调 setImageItem 把图像托管给色条 ——
        # ColorBarItem 会把 values 写回 ImageItem.levels，而这里塞进去的已经是
        # 上过色的 RGBA，再被 levels 处理一遍等于"给颜色再上一次色"，结果几乎
        # 所有样点被推到纯白：导出图看起来"没有噪声、比屏幕干净"。
        # 色条自己的渐变来自 colorMap、刻度来自 values，根本不需要托管图像。
        lay = plot.getPlotItem().layout
        lay.addItem(cbar, 2, 5)
        lay.setColumnFixedWidth(4, 5)
    except Exception:                            # pragma: no cover
        pass                                    # 色条只是锦上添花，失败不影响出图
    assert item.levels is None, "ImageItem 不应被写入 levels（否则导出会洗白）"

    vb.setLimits(xMin=x0, xMax=x1, yMin=y0, yMax=y1)
    vb.disableAutoRange()
    vb.setRange(rect=QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), padding=0.01)
    return plot


def build_wiggle_figure(img: np.ndarray, extent: tuple[float, float, float, float],
                        xlabel: str, ylabel: str, sets: list,
                        n_traces: int = 60, gain: float = 1.0,
                        invert_y: bool = True,
                        labels: list[str] | None = None,
                        size=(1000, 760)) -> pg.PlotWidget:
    """离屏构建一张"只有 wiggle 曲线"的图（白纸、无网格、无密度图）。

    ``sets`` = ``[(切片, 色标, 幅度缩放, (颜色, 线型)), ...]``；多组就把多份数据的
    波形叠在同一张图上（对比模式），并给出每份数据一条图例。
    ``labels`` 是图例文字（与单道波形导出图用同一套写法，见 main_window
    ``_dataset_label``）；省略时退回"数据 1 / 数据 2"。
    """
    plot = pg.PlotWidget(background=_FIG_BG)
    plot.setMenuEnabled(False)
    plot.resize(int(size[0]), int(size[1]))
    vb = plot.getViewBox()
    vb.setDefaultPadding(0.01)
    vb.invertY(bool(invert_y))

    legend = None
    if len(sets) > 1:
        try:
            legend = plot.addLegend(offset=(-14, 12), brush=pg.mkBrush(255, 255, 255, 215),
                                    pen=pg.mkPen("#BBBBBB"), labelTextColor=_FIG_INK)
        except Exception:                        # pragma: no cover
            legend = None
    for i, (src_img, clim, scale, style_pair) in enumerate(sets):
        pen = line_pen(style_pair, 1.0)
        for xs, ys in render.wiggle_curves(src_img, extent, clim, n_traces, gain, scale):
            plot.plot(xs, ys, pen=pen)
        if legend is not None:
            # 图例只登记一条代理线，而不是给几十条曲线各写一行
            legend.addItem(pg.PlotDataItem([], [], pen=line_pen(style_pair, 1.8)),
                           (labels[i] if labels and i < len(labels)
                            else FIGURE_CODE_LABELS[i % len(FIGURE_CODE_LABELS)]))

    x0, x1, y0, y1 = (float(v) for v in extent)
    plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                 pen=pg.mkPen("#999999", width=1)),
                 ignoreBounds=True)
    _figure_axes(plot, xlabel, ylabel)
    vb.setLimits(xMin=x0, xMax=x1, yMin=y0, yMax=y1)
    vb.disableAutoRange()
    vb.setRange(rect=QtCore.QRectF(x0, y0, x1 - x0, y1 - y0), padding=0.01)
    return plot


def build_trace_figure(entries: list, xlabel: str = "时间 T (s)",
                       ylabel: str = "振幅", size=(1000, 520)) -> pg.PlotWidget:
    """离屏构建一张单道波形图。

    ``entries`` = ``[(时间, 振幅, (颜色, 线型), 曲线名), ...]``；不画网格，
    和导出的剖面对齐成同一套"论文用图"风格。
    """
    plot = pg.PlotWidget(background=_FIG_BG)
    plot.setMenuEnabled(False)
    plot.resize(int(size[0]), int(size[1]))
    plot.getViewBox().setDefaultPadding(0.02)
    # 图例必须在画曲线**之前**建：pyqtgraph 的图例只登记之后通过 plot(name=…)
    # 加进来的条目，反过来建就会得到一个空白的图例框。
    if len(entries) > 1:
        try:
            plot.addLegend(offset=(-14, 12), brush=pg.mkBrush(255, 255, 255, 215),
                           pen=pg.mkPen("#BBBBBB"), labelTextColor=_FIG_INK)
        except Exception:                        # pragma: no cover
            pass
    for t, amp, style_pair, name in entries:
        plot.plot(t, amp, pen=line_pen(style_pair, 1.6), name=name)
    plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                 pen=pg.mkPen("#999999", width=1)),
                 ignoreBounds=True)
    _figure_axes(plot, xlabel, ylabel)
    plot.enableAutoRange()
    return plot


def export_figure(plot: pg.PlotWidget, path: str, fmt: str,
                  width: int | None = None) -> str:
    """把上面构建的图写出 PNG / SVG（走 pyqtgraph 自带的导出器）。

    用 ``ImageExporter`` / ``SVGExporter`` 而不是截屏：导出器按图元的包围盒重新
    渲染，PNG 是白底的干净位图，SVG 是真正的矢量（坐标轴、文字都可缩放）。

    **必须先让控件"走完一次显示流程"**：控件从没 show 过时，场景里的文字还没被
    解析，导出会得到满屏"口口口"方框（若干次试出来的）。这里用
    ``WA_DontShowOnScreen`` 让它完成 show / 布局 / 绘制，但不会真的弹到屏幕上。

    **格式由参数决定、不看扩展名**：``ImageExporter`` 默认按文件后缀推断格式，
    后缀不认识（例如把 PNG 存成 ``.svg``）时它会静默不写文件 —— 所以这里拿到
    QImage 后自己用 "PNG" 保存，并在最后确认文件确实落盘。
    """
    from pyqtgraph.exporters import ImageExporter, SVGExporter
    if not plot.isVisible():
        plot.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        plot.show()
        QtWidgets.QApplication.processEvents()

    out = str(path)
    fmt = str(fmt).lower()
    if fmt == "svg":
        SVGExporter(plot.getPlotItem()).export(out)
    elif fmt == "png":
        exporter = ImageExporter(plot.getPlotItem())
        params = exporter.parameters()
        params["antialias"] = True
        if width:
            params["width"] = int(width)
        image = exporter.export(toBytes=True)
        if not image.save(out, "PNG"):
            raise RuntimeError(f"写不出 PNG：{out}")
    else:
        raise RuntimeError(f"不支持的图片格式：{fmt}")
    if not Path(out).exists() or Path(out).stat().st_size == 0:
        raise RuntimeError(f"图片没有成功写出：{out}")
    return out