"""界面里的小图标：全部用 QPainter 现画。

为什么不用图片资源
------------------
图标要跟着状态换色换形（面板在 / 已收起、打开 / 已拉出、分组图标要跟识别色走），
代码绘制像随手调画笔一样方便，也不用维护一堆分辨率的位图文件。
这与 ``view2d.line_swatch_pixmap`` 是同一套思路，风格天然统一。

坐标系
------
所有图形按 18×18 的设计框绘制，再按请求的像素尺寸等比缩放 ——
所以线宽、圆角在不同尺寸下比例一致，不会"小图标线太粗"。

图标分工（避免用户混用）
------------------------
* ``dock``   —— 面板级：方框 + 一侧实心竖条。竖条在哪侧 = 面板停在哪侧；
                展开是宽条、收起只剩一条细线（正好映射真实的"细轨"）。
* ``group``  —— 分组级：方框 + 类型图形，只出现在左栏每个设置分组上。
* ``kind``   —— 面板类型级：给右侧悬浮胶囊用，三种面板各有识别色。
* ``collapse_all`` / ``grab`` —— 批量折叠、拖动抓手。
"""

from __future__ import annotations

import math

from PySide6 import QtCore, QtGui

from . import style

DESIGN = 18.0            # 设计框边长（所有绘制都用这套坐标）
_DPR = 2.0               # 统一 2 倍渲染再交给 Qt 缩放，1x 屏上也是清晰的

# 左栏分组的图标名，与 main_window 里的分组键一一对应
GROUP_ICONS = ("data", "cut", "density", "wave", "compare")
# 右侧胶囊的三种面板图标（按维度 1 → 2 → 3 排）
KIND_ICONS = ("trace", "slice", "side3d")

_BAND_W = 4.0            # 展开态竖条宽度
_BAND_THIN = 1.5         # 收起态细轨宽度


def _begin(size: int) -> tuple[QtGui.QPixmap, QtGui.QPainter]:
    px = max(2, int(round(size * _DPR)))
    # 注意：**先画、后标 devicePixelRatio**。QPainter 在已经标了 dpr 的 pixmap 上
    # 会自己再乘一次 dpr，若我们再乘一遍就是双重缩放 —— 早先的图标只画出左上角
    # 那一小块就是这个原因。画完再标，行为就是确定的。
    pm = QtGui.QPixmap(px, px)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    p.scale(px / DESIGN, px / DESIGN)
    return pm, p


def _end(p: QtGui.QPainter, pm: QtGui.QPixmap) -> QtGui.QPixmap:
    p.end()
    pm.setDevicePixelRatio(_DPR)
    return pm


def _col(color, alpha: float = 1.0) -> QtGui.QColor:
    c = QtGui.QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _pen(color, width: float = 1.4) -> QtGui.QPen:
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
    return pen


def _poly(*pts: tuple[float, float]) -> QtGui.QPolygonF:
    return QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts])


def _frame(p: QtGui.QPainter, pen: QtGui.QPen) -> None:
    """所有图标共用的"方框"底：圆角矩形，只描边不填充。"""
    p.setPen(pen)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QtCore.QRectF(1.6, 2.6, 14.8, 12.8), 3.0, 3.0)


def _band_rect(side: str, width: float) -> QtCore.QRectF:
    """竖条的位置：贴着方框的那一侧内缘。"""
    x = 3.2 if side != "right" else 16.4 - 1.6 - width
    return QtCore.QRectF(x, 5.0, width, 8.0)


# ============================================================== 面板级：停靠
def dock(size: int = 18, ink=None, band=None,
         expanded: bool = True, side: str = "left") -> QtGui.QPixmap:
    """面板显隐用的"停靠"图标：方框 + 一侧竖条。

    ``expanded=True`` 竖条是宽的实心条（面板开着）；``False`` 只剩一条细轨。
    ``side`` 指明面板停靠在哪一侧，竖条就画在哪一侧 —— 与真实的收起方向一致。
    """
    # 颜色默认值一律写 None、进函数再取 style.*：写成 ``ink=style.TEXT_DIM``
    # 会在**定义时**就把当时的颜色固化住，换主题后默认色不会跟着变。
    ink = style.TEXT_DIM if ink is None else ink
    band = style.ACCENT if band is None else band
    pm, p = _begin(size)
    _frame(p, _pen(_col(ink, 1.0 if expanded else 0.6), 1.4))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    if expanded:
        p.setBrush(QtGui.QColor(band))
        p.drawRoundedRect(_band_rect(side, _BAND_W), 1.1, 1.1)
    else:
        p.setBrush(_col(band, 0.5))
        p.drawRoundedRect(_band_rect(side, _BAND_THIN), 0.7, 0.7)
    return _end(p, pm)


# ============================================================== 分组级：图标
def group(name: str, size: int = 16, ink=None) -> QtGui.QPixmap:
    """左栏每个设置分组标题行上的小图标。"""
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    _frame(p, _pen(ink, 1.4))
    mark = _pen(ink, 1.2)
    p.setPen(mark)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)

    if name == "data":                      # 表格：三条横纹
        p.drawLine(QtCore.QPointF(4.4, 6.6), QtCore.QPointF(13.6, 6.6))
        p.drawLine(QtCore.QPointF(4.4, 9.0), QtCore.QPointF(13.6, 9.0))
        p.drawLine(QtCore.QPointF(4.4, 11.4), QtCore.QPointF(9.8, 11.4))
    elif name == "cut":                     # 剖切：一道切线 + 播放三角
        p.drawLine(QtCore.QPointF(9.0, 3.6), QtCore.QPointF(9.0, 14.4))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(ink))
        p.drawPolygon(_poly((11.6, 6.8), (14.2, 9.0), (11.6, 11.2)))
    elif name == "density":                 # 密度图：高度递增的四条竖纹
        p.setPen(_pen(ink, 1.8))
        for x, top in ((4.8, 6.6), (7.4, 7.8), (10.0, 9.0), (12.6, 10.2)):
            p.drawLine(QtCore.QPointF(x, 12.2), QtCore.QPointF(x, top))
    elif name == "wave":                    # 波形：一条尖峰折线
        p.drawPolyline(_poly((4.4, 9.0), (6.4, 9.0), (7.4, 5.6), (8.4, 12.6),
                             (9.4, 7.4), (10.8, 9.0), (13.4, 9.0)))
    elif name == "compare":                 # 对比：两块不等高的数据块
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(_col(ink, 0.85))
        p.drawRoundedRect(QtCore.QRectF(4.4, 6.4, 3.6, 6.4), 1.1, 1.1)
        p.setBrush(_col(ink, 0.45))
        p.drawRoundedRect(QtCore.QRectF(9.6, 8.2, 3.6, 4.6), 1.1, 1.1)
    else:                                   # 兜底：画个点，别给出空白图标
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(_col(ink, 0.7))
        p.drawEllipse(QtCore.QPointF(9.0, 9.0), 2.2, 2.2)
    return _end(p, pm)


# ============================================================== 面板类型图标
def kind(name: str, size: int = 22, ink=None, band=None,
         on: bool = True) -> QtGui.QPixmap:
    """右侧悬浮胶囊上的面板图标：左侧停靠条（亮 = 打开，细线 = 已收起）+ 类型图形。"""
    ink = style.TEXT_DIM if ink is None else ink
    band = style.ACCENT if band is None else band
    pm, p = _begin(size)
    _frame(p, _pen(ink if on else _col(ink, 0.5), 1.4))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    if on:
        p.setBrush(QtGui.QColor(band))
        p.drawRoundedRect(_band_rect("left", _BAND_W), 1.1, 1.1)
    else:
        p.setBrush(_col(band, 0.45))
        p.drawRoundedRect(_band_rect("left", _BAND_THIN), 0.7, 0.7)

    mark = ink if on else _col(ink, 0.45)
    p.setPen(_pen(mark, 1.2))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    if name == "trace":                     # 1 维：一条道
        p.drawPolyline(_poly((7.6, 9.0), (9.0, 9.0), (9.8, 6.4), (10.6, 11.6),
                             (11.4, 7.6), (12.6, 9.0), (15.2, 9.0)))
    elif name == "slice":                   # 2 维：两条同相轴
        path = QtGui.QPainterPath()
        path.moveTo(7.6, 7.2)
        path.quadTo(10.8, 5.6, 15.4, 8.0)
        path.moveTo(7.6, 11.2)
        path.quadTo(10.8, 9.6, 15.4, 12.0)
        p.drawPath(path)
    elif name == "side3d":                  # 3 维：线框立方体
        p.drawRect(QtCore.QRectF(8.6, 8.2, 4.6, 5.2))
        p.drawRect(QtCore.QRectF(10.2, 6.8, 4.6, 5.2))
        p.drawLine(QtCore.QPointF(8.6, 8.2), QtCore.QPointF(10.2, 6.8))
        p.drawLine(QtCore.QPointF(13.2, 8.2), QtCore.QPointF(14.8, 6.8))
        p.drawLine(QtCore.QPointF(13.2, 13.4), QtCore.QPointF(14.8, 12.0))
        p.drawLine(QtCore.QPointF(8.6, 13.4), QtCore.QPointF(10.2, 12.0))
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(_col(mark, 0.7))
        p.drawEllipse(QtCore.QPointF(11.5, 9.0), 2.2, 2.2)
    return _end(p, pm)


# ============================================================== 批量折叠 / 抓手
def collapse_all(size: int = 18, ink=None) -> QtGui.QPixmap:
    """左栏轨道底部的"全部折叠 / 全部展开"：一对对向小箭头。"""
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.4))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawPolyline(_poly((5.0, 6.4), (9.0, 2.6), (13.0, 6.4)))
    p.drawPolyline(_poly((5.0, 11.6), (9.0, 15.4), (13.0, 11.6)))
    return _end(p, pm)


def chevron(size: int = 12, ink=None, down: bool = True) -> QtGui.QPixmap:
    """分组折叠用的**细线条箭头**：展开指向下、收起指向右。

    刻意与"面板级"的停靠图标长得完全不一样（细线条 vs 方框+实心条），
    这样"收掉一个分组"和"收掉整块面板"不会再被混为一谈。
    """
    ink = style.TEXT_MUTE if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.6))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    if down:
        p.drawPolyline(_poly((4.0, 6.6), (9.0, 11.6), (14.0, 6.6)))
    else:
        p.drawPolyline(_poly((6.6, 4.0), (11.6, 9.0), (6.6, 14.0)))
    return _end(p, pm)


def panel_back(size: int = 16, ink=None) -> QtGui.QPixmap:
    """独立窗口上那颗"收回主窗口"的小图标：一条竖杠 + 指过去的箭头。"""
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.5))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawLine(QtCore.QPointF(4.6, 5.0), QtCore.QPointF(4.6, 13.0))
    p.drawLine(QtCore.QPointF(15.0, 9.0), QtCore.QPointF(6.0, 9.0))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ink))
    p.drawPolygon(_poly((8.6, 6.4), (4.6, 9.0), (8.6, 11.6)))
    return _end(p, pm)


def expand(size: int = 16, ink=None, restore: bool = False) -> QtGui.QPixmap:
    """独立窗口上那颗「全屏 / 还原」图标：四个角括号。

    ``restore=False``：角括号**朝外**（像把画面推向四角）= 进入全屏；
    ``restore=True`` ：角括号**朝内**（像把画面收拢回来）= 退出全屏。
    与"收回主窗口"的箭头（:func:`panel_back`）刻意做成完全不同的形状 —— 一个是把
    窗口铺满屏幕，一个是把面板放回主窗口，混在一起点错代价很高。
    """
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.6))
    c = DESIGN / 2.0                      # 9：设计框正中
    outer = 2.8                           # 角括号离外沿的距离
    inner = 2.6                           # 还原态的角离中线的距离
    arm = 4.6
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        if restore:
            x, y = c + sx * inner, c + sy * inner
            ex, ey = x + sx * arm, y + sy * arm          # 臂朝外
        else:
            x = outer if sx < 0 else DESIGN - outer
            y = outer if sy < 0 else DESIGN - outer
            ex, ey = x - sx * arm, y - sy * arm          # 臂朝内
        p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(ex, y))
        p.drawLine(QtCore.QPointF(x, y), QtCore.QPointF(x, ey))
    return _end(p, pm)


def gear(size: int = 18, ink=None) -> QtGui.QPixmap:
    """齿轮：窗口设置的总入口（管哪些设置出现在侧边栏、外观等）。

    "齿轮 = 设置"是通用语言，不需要额外说明；它和旁边那些"跳到某一组"的图标
    在职责上完全不同，所以造型也刻意区分开。
    """
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.3))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    cx, cy, r_out, r_in = size / 2.0, size / 2.0, size * 0.36, size * 0.18
    for i in range(8):                                   # 8 颗齿
        ang = i * math.pi / 4.0
        p.drawLine(QtCore.QPointF(cx + math.cos(ang) * r_out,
                                  cy + math.sin(ang) * r_out),
                   QtCore.QPointF(cx + math.cos(ang) * (r_out + size * 0.10),
                                  cy + math.sin(ang) * (r_out + size * 0.10)))
    p.drawEllipse(QtCore.QPointF(cx, cy), r_out * 0.86, r_out * 0.86)
    p.drawEllipse(QtCore.QPointF(cx, cy), r_in, r_in)
    return _end(p, pm)


def split_layout(size: int = 18, ink=None, on: bool = False) -> QtGui.QPixmap:
    """工作区胶囊上那颗「分屏」：一个方框被竖线一分为二。

    ``on`` 时右半边填成强调色 —— 一眼看出"现在是分屏"，而不是靠记住按钮状态。
    """
    ink = style.TEXT_DIM if ink is None else ink
    band = style.ACCENT if ink is None else ink
    pm, p = _begin(size)
    _frame(p, _pen(ink if on else _col(ink, 0.8), 1.4))
    if on:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(_col(band, 0.55))
        p.drawRect(QtCore.QRectF(9.6, 3.4, 6.2, 11.2))
    p.setPen(_pen(ink, 1.3))
    p.drawLine(QtCore.QPointF(9.0, 3.4), QtCore.QPointF(9.0, 14.6))
    return _end(p, pm)


def reset_view(size: int = 18, ink=None) -> QtGui.QPixmap:
    """「复位视角」：一圈带箭头的回转弧。挂在三维标题行右侧。"""
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.5))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawArc(QtCore.QRectF(4.0, 4.0, 10.0, 10.0),
              int(70 * 16), int(250 * 16))
    a = math.radians(70.0)                    # 箭头放在弧的起点（70°）
    cx = 9.0 + math.cos(a) * 5.0
    cy = 9.0 - math.sin(a) * 5.0
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ink))
    p.drawPolygon(_poly((cx + 0.4, cy - 2.0), (cx + 2.2, cy + 1.4), (cx - 1.9, cy + 1.0)))
    return _end(p, pm)


def swap(size: int = 14, ink=None) -> QtGui.QPixmap:
    """摆法缩略图角上的「换谁当大的」：一对反向箭头。"""
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(_pen(ink, 1.4))
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    p.drawLine(QtCore.QPointF(3.2, 6.4), QtCore.QPointF(14.8, 6.4))
    p.drawLine(QtCore.QPointF(14.8, 11.6), QtCore.QPointF(3.2, 11.6))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ink))
    p.drawPolygon(_poly((13.2, 3.9), (13.2, 8.9), (16.2, 6.4)))
    p.drawPolygon(_poly((4.8, 9.1), (4.8, 14.1), (1.8, 11.6)))
    return _end(p, pm)


def grab(size: int = 14, ink=None) -> QtGui.QPixmap:
    """面板标题栏最左侧的 6 点抓手：唯一的一个"这里能拖"提示。

    不用文字 tooltip / 状态栏提示 —— 抓手本身就是可拖动控件的通用语言，
    鼠标移上去还会变成握手光标（由控件自己设）。
    """
    ink = style.TEXT_DIM if ink is None else ink
    pm, p = _begin(size)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(ink))
    for x in (6.7, 11.3):
        for y in (6.0, 9.0, 12.0):
            p.drawEllipse(QtCore.QPointF(x, y), 1.25, 1.25)
    return _end(p, pm)
