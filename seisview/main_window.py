"""主窗口：把读取、切片、三维与显示参数装配成一条完整工作流。

交互主线
--------
打开文件 → 选变量 → 确认轴序 → 体数据入位：
三维面板先给整体印象，剖面面板给剖面细节，波形面板给单道细节；
在三维面上点一下或在剖面上点一下，都能把当前 (S, R, T) 位置传下去。

多数据对比
----------
可同时载入最多三份**形状相同**的数据：中间并排出现两块（或三块）剖面面板，
设置面板里的「多数据对比」卡片负责切换当前数据、决定是否同步剖面参数与目标道；
单道波形面板把各数据源的同一条道用不同颜色叠在一起比较。

面板布局
--------
右栏是"设置面板"：最左边一条**常驻图标轨道**（停靠图标 → 已加入侧边栏的分组图标 →
⇕ 一键收放这些分组 → 齿轮打开「窗口设置」），右边是内容区。收起整栏后只剩轨道，
图标位置不变，本身就是内容的索引；哪些分组出现在这里由齿轮里的勾选决定。

左侧工作区里三块内容面板（剖面 / 单道波形 / 三维）装在同一棵 splitter 树里 ——
开关某一块只是把尺寸插值过去（190ms、绝不 reparent），所以三维的 GL 上下文与剖面的
视野都不会被重置。排版一共**七个具体摆法**：

* **三块全开**时才谈"怎么排"，四套，各自钉住一块：
  ``B 主+侧+底``（**默认**：两块在上排左右并排，单道永远在底部通栏）、
  ``A 左叠右``（两块在左列上下叠放，三维永远在右边一列）、
  ``BT 单道在上``（B 的镜像：单道顶部通栏，两块在下排左右并排）、
  ``AL 三维在左``（A 的镜像：三维在左边一列，两块在右列上下叠放）。
  刻意不做"三段纵向 / 三列并排"：三维挤进细列、波形挤进细列都只会变成一块没法看的东西。
* **只有两块**时方向由"哪两块"直接决定（剖面+三维 → 左右；单道+三维 → 上下、三维在上；
  剖面+单道 → 上下、剖面在上），不再让用户选方向。

入口是工作区**右上角那枚悬浮胶囊**（不占布局高度）：① 单道 ② 剖面 ③ 三维三个图标是
**纯开关**（亮=在显示、暗=已收起，点一下只做这一件事，含义与当前状态无关）；「⇄」
在既定方向里翻转先后（B/BT 里是那一排两块、A/AL 里是那一列两块），钉住的那块不参与；「分屏」键
打开**摆法面板** —— 七张缩略图按"要几块"分两组，点哪张就得到哪张（点另一组会顺便把
块数对齐过去，不置灰、不留死胡同）；每张左上角的 ★ = 把这张设为**默认布局**；
快捷键 1/2/3 独看、Tab 循环。也可以直接把面板
标题行拖到工作区的四条边（右/下 → B，左/上 → A；拖的那块排到可换序的第一位）。

每块的自然尺寸按数据规模估（剖面按切片面的横纵采样数之比、单道是一根扁条、三维取
剖面宽的 42%）；**总窗口尺寸也跟着排版走**：切组合时按当前排版把各块的自然尺寸沿轴
相加，窗口一起变大或变小（见 :meth:`MainWindow._fit_window_to_layout`），不会只剩一块
还被硬撑变形。换摆法时窗口尺寸是**滑过去**的（见 :meth:`_animate_layout_change`），
不是瞬间跳。两条保险：窗口设置里可以关掉跟随排版；某个组合手动调过的尺寸会被记住。

拖动
----
三块面板的标题行左侧都有一个 6 点抓手，按住拖动，结果完全由松手的位置决定：
落在另一块剖面面板内 → 交换剖面顺序；**贴到工作区的左/右/上/下边** → 按那条边对应的
分屏方式重新摆一遍（见上）；拖到主窗口之外 → 拉出为**无边框极简窗口**；其它 → 取消。
浮窗再拖回工作区松手即收回。

拖入文件
--------
把数据文件拖进窗口即导入：还没数据就直接载入；已经有数据时弹一个意图确认框 ——
形状与当前数据相同就给「对比 / 替换 / 取消」，不同就给「替换 / 取消」，
已达对比上限则提示后只给「替换当前激活的一份 / 取消」。一次拖多个文件时，
第一个照流程走，后面同形状的自动追加为对比数据。

主题
----
配色主题（深蓝 / 极夜黑 / 纸白 / 高对比 / 跟随系统）从左侧轨道的齿轮里进
（见 :meth:`MainWindow.open_preferences`）。切换是**运行时**的：装上新调色板、
重装样式表，再把"按当时颜色现画"的东西重刷一遍（图标、pyqtgraph 画布与图例、
三维 GL 底、控件自带的行内样式），见 :meth:`MainWindow._refresh_theme_widgets`。

两条界线在主题里也是硬规则：**屏幕跟着主题走**（含屏幕曲线用的数据识别色 ——
浅色主题配深色线）；**导出图永远是论文白底**，不随主题变（``style.PAPER_*``）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid as _qt_valid

from . import APP_NAME, __version__, export as exporter
from . import icons, loaders, style, view2d
from .loaders import LoadError
from .sample import build_sample_volume
from .view2d import SlicePanel
from .volume import (SLICE_LABELS, SeisVolume, compute_clim, display_face,
                     shared_clim, stats)
from .widgets import (ArrayViewDialog, ColormapCombo, DragLayer, ExportDialog,
                      FloatingPanel, FoldCard, ImportIntentDialog,
                      LAYOUT_GROUP, LAYOUT_KEYS, LAYOUT_TITLE, LayoutPicker,
                      PanelCapsule, PlayheadTrack, PreferencesDialog,
                      SectionLabel, SegmentedControl, SliderRow, THREE_KEYS,
                      THREE_PINNED, ValueLabel, VariableTable, WheelSafeComboBox,
                      WheelSafeDoubleSpinBox, WheelSafeSpinBox, ask_axis_order,
                      make_panel, pair_layout, three_free_pair)

# 扫掠速度：显示名 → 定时器间隔 (ms)
SPEEDS = [("慢", 150), ("中", 70), ("快", 35), ("极快", 16)]
# 抽稀上限：显示名 → 每边最多像素（0 表示不抽稀）
DOWNSAMPLE = [("不抽稀", 0), ("4096", 4096), ("2048", 2048), ("1024", 1024), ("512", 512)]
CLIM_MODES = [("自动", "auto"), ("稳健", "robust"), ("手动", "manual")]
# AGC 滑动窗口预设：显示名 → 点数（0 = 整道归一化）。
# 用列表而不是数字框：整道 / 十几个点到上千点，实际就那几个常用值，
# 点一下选完比敲数字省事，也不会有"范围给了 0~1001 但不知道填多少"的问题。
AGC_WINDOWS = [("整道", 0), ("11 点", 11), ("21 点", 21), ("51 点", 51),
               ("101 点", 101), ("201 点", 201), ("301 点", 301),
               ("501 点", 501), ("1001 点", 1001)]
# 叠加波形的配色不在显示分组里，改由「线型」分组按数据顺序分配（见 LINE_COLORS）
# 线型：颜色 + 线型。对比模式下按"从左到右的数据顺序"分配，因此它同时决定了
# 单道波形面板的曲线、剖面上叠加的 wiggle、以及导出图里的线。
LINE_COLORS = [
    ("黑", "#111827"), ("红", "#D62828"), ("蓝", "#1D4ED8"),
    ("绿", "#15803D"), ("橙", "#C2410C"), ("紫", "#7E22CE"),
    ("青", "#0E7490"), ("灰", "#6B7280"), ("白", "#FFFFFF"),
]
LINE_STYLES = [("实线", "solid"), ("虚线", "dash"), ("点线", "dot"), ("点划线", "dashdot")]
# 默认：数据 1 黑实线 / 数据 2 红实线 / 数据 3 蓝虚线
DEFAULT_LINE_STYLES = [("#111827", "solid"), ("#D62828", "solid"), ("#1D4ED8", "dash")]
MAX_DATASETS = 3
AXIS_TITLES = {"shot": "炮点 S", "recv": "检波器 R", "time": "时间 T"}

# 左栏的收起状态与分组展开状态会被记住（下次启动还原）。
# 设 SEISVIEW_NO_PERSIST=1 可以关掉，方便反复做"全新启动"的测试。
_PERSIST_UI = not os.environ.get("SEISVIEW_NO_PERSIST")

# 胶囊上的图标名 → 内容面板的键；标签用于 tooltip
CAPSULE_KEY = {"trace": "trace", "slice": "slice", "side3d": "right"}
PANEL_LABELS = {"trace": "单道波形", "slice": "剖面", "right": "三维"}
# 面板的固定次序（也是胶囊上 1 → 2 → 3 的顺序）
PANEL_ORDER = ("slice", "trace", "right")
# 排版时的"让位优先级"：空间不够先保剖面，其次单道，最后三维（需求里的 剖面>单道>3D）
PANEL_PRIORITY = {"slice": 3.0, "trace": 2.0, "right": 1.0}

# 分屏摆法：**七个具体摆法**（见 widgets.LAYOUT_KEYS）。三块全开时才谈"怎么排"
# （B/BT：单道永远在底/顶栏；A/AL：三维永远在右/左列）；只有两块时方向由"哪两块"直接决定，
# "⇄" 只在既定方向里翻转先后。三块容器提前建好，切摆法只换把它们装进哪棵 splitter 树。
PRESET_ORDER = LAYOUT_KEYS
PRESET_LABELS = LAYOUT_TITLE
PRESET_TIPS = {
    "B": "剖面与三维在上排左右并排，单道作底部通栏（默认）",
    "A": "剖面与单道在左列上下叠放，三维在右列",
    "BT": "单道作顶部通栏，下面剖面与三维左右并排",
    "AL": "三维在左列，右边剖面与单道上下叠放",
    "SR": "剖面在左、三维在右（左右并排）",
    "TR": "三维在上、单道在下（上下排列）",
    "ST": "剖面在上、单道在下（上下排列）",
}
# 两块摆法对应的两块，以及三块摆法的钉住关系
KEY_PAIR = {"SR": ("slice", "right"), "TR": ("right", "trace"),
            "ST": ("slice", "trace")}
# BT（单道在上）/ AL（三维在左）现在是 widgets 里与 B/A 并列的一等摆法，这里不再各自
# 另立一份表，只把名字留成别名 —— 调用点（GROUP_OF / PINNED_OF）不必跟着改。
GROUP_OF = LAYOUT_GROUP
PINNED_OF = THREE_PINNED
# 贴边感应带占工作区该方向的比例：**和落位预览的区域差不多大**（预览里最窄的一块
# 也在三成上下），而不是原先那条 15px 的窄边 —— 窄边要很精准地贴上去才出提示，
# 实际很难触发。中间那 1/3 是"不贴边"的判定区（拖到那里 = 取消 / 回原位）。
EDGE_FRAC = 1.0 / 3.0


class Workspace(QtWidgets.QWidget):
    """右侧工作区容器：把悬浮胶囊摆到自己的右上角，并在拖动时给出落位预览。

    胶囊和预览都不进布局（是本控件的子控件 + raise_），所以不占高度、也不跟着
    面板收放移动；工作区因此比原来"顶部一整行按钮"多出约 40px 给画面。
    """

    MARGIN = 8
    PREVIEW_PAD = 3         # 预览矩形往内缩一点，边界看得清
    PREVIEW_ALPHA = 0.22    # 半透明：看得见"这块会占哪"，又不挡住下面的波形

    def __init__(self, parent=None):
        super().__init__(parent)
        self.capsule: QtWidgets.QWidget | None = None
        hint = QtWidgets.QFrame(self)
        hint.setObjectName("EdgeHint")
        eff = QtWidgets.QGraphicsOpacityEffect(hint)
        eff.setOpacity(self.PREVIEW_ALPHA)
        hint.setGraphicsEffect(eff)
        hint.hide()
        self._hint = hint
        self._preview: tuple | None = None

    def resizeEvent(self, ev) -> None:                  # noqa: N802 （Qt 接口名）
        super().resizeEvent(ev)
        self.place_capsule()
        if self._preview is not None:
            self.show_drop_preview(self._preview)

    def place_capsule(self) -> None:
        if self.capsule is None:
            return
        self.capsule.adjustSize()
        self.capsule.move(max(0, self.width() - self.capsule.width() - self.MARGIN),
                          self.MARGIN)
        self.capsule.raise_()

    def show_drop_preview(self, rect: tuple | None = None) -> None:
        """落位预览：把"松手后这一块会占据的区域"画成半透明矩形；``None`` 收起。

        ``rect`` 是 0~1 的相对矩形 ``(x, y, w, h)``。用"区域"而不是"贴边一条亮带"：
        看到的形状就是排完之后的形状，不用再靠脑补猜"贴这条边会变成哪种分屏"。
        """
        self._preview = rect
        if rect is None:
            self._hint.hide()
            return
        x, y, w, h = rect
        pad = self.PREVIEW_PAD
        self._hint.setGeometry(
            int(x * self.width()) + pad, int(y * self.height()) + pad,
            max(6, int(w * self.width()) - 2 * pad),
            max(6, int(h * self.height()) - 2 * pad))
        self._hint.show()
        self._hint.raise_()
        if self.capsule is not None:
            self.capsule.raise_()          # 预览压在胶囊下面，别挡住那三个图标


def pane_header(text: str, handle: bool = True):
    """内容面板的标题行：抓手 + 标题，返回 (控件, 水平布局, 标题标签)。

    与设置分组不同，这里的标题行**只有拖动一个手势**（拉出为独立窗口 / 换序），
    没有折叠三角 —— 面板的种类级显隐统一交给右上角的胶囊。这也是为了避免
    再出现"两种三角长得一样、点下去收掉的东西不一样"的老问题。

    剖面区域的**组标题**也带抓手：拖动它移动的是整个剖面区域（含对比时的所有
    剖面面板）；组内单幅剖面的换序另用一个 ``⇄`` 小抓手，两者形状不同，不混淆。
    """
    header = QtWidgets.QWidget()
    header.setMouseTracking(True)
    h = QtWidgets.QHBoxLayout(header)
    h.setContentsMargins(2, 0, 2, 0)
    h.setSpacing(6)
    if handle:
        grab_label = QtWidgets.QLabel()
        grab_label.setObjectName("GrabHandle")      # 换主题时按这个名字统一重画
        grab_label.setFixedSize(14, 14)
        grab_label.setPixmap(icons.grab(14, style.TEXT_MUTE))
        h.addWidget(grab_label)
    label = SectionLabel(text)
    h.addWidget(label)
    h.addStretch(1)
    return header, h, label


def _hdivider() -> QtWidgets.QFrame:
    """面板里的分组横线：把"同一件事"的设置与别的设置隔开。

    颜色是行内样式（不走全局 QSS），所以换主题时要靠 ``HDivider`` 这个名字
    统一重刷，见 :meth:`MainWindow._refresh_theme_widgets`。
    """
    line = QtWidgets.QFrame()
    line.setObjectName("HDivider")
    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;")
    return line


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


class MainWindow(QtWidgets.QMainWindow):
    # 期望尺寸 / 可接受的最小尺寸。实际会按屏幕可用区域收窄，见 _place_window。
    # 开场刻意小一点：这时还没有数据，画面里只有"拖文件进来"的引导；
    # 之后总窗口尺寸由 _fit_window_to_layout 按**当前排版**与数据规模随时重算。
    DESIRED_SIZE = (1080, 740)
    # 可接受的最小尺寸：只是窗口管理器层面的兜底。**自动适配排版时不用它** ——
    # 那里用的是"当前组合真正需要的最小尺寸"，这样窗口才能缩到与数据形状相称的大小。
    MIN_SIZE = (700, 480)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SeisView — 地震数据可视化")

        # ---------------------------------------------------------- 状态
        self.datasets: list[Dataset] = []
        self.active = 0
        self.src_path = ""                  # 变量表里当前列出的文件
        self._base_clims: list[tuple[float, float]] = []
        self._clims: list[tuple[float, float]] = []   # 各数据源当前实际使用的色标
        self._clim = (-1.0, 1.0)            # 当前数据的色标窗口（三维贴图用）
        self._clim_scale = 1.0              # 色标半窗宽的倍数（对比度滑块的换算结果）
        self._stats = {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}
        self.panels: list[SlicePanel] = []
        # 线型按"数据顺序槽位"保存（1→黑实、2→红实、3→蓝虚），与数据份数无关：
        # 删掉中间某份数据后，剩下的会顶到前面的槽位，配色跟着"从左到右"走。
        self.line_styles: list[tuple[str, str]] = list(DEFAULT_LINE_STYLES)
        # 一次刷新周期内缓存各数据源的 (切片, 色标)，供叠加/导出复用
        self._panel_cache: dict[tuple[int, bool], tuple] = {}
        # 抽稀 + AGC 之后、上色之前的原始显示数组（共享色标与面板共用）
        self._raw_cache: dict[tuple[int, bool], tuple[np.ndarray, bool]] = {}
        self._shared_base_cache: tuple[float, float] | None = None
        self._face_clim_cache: dict[tuple, tuple[float, float]] = {}
        # 双击复位的“撤销一次取道”：第一次 release 已经改过位置，双击时还原
        self._pick_undo: dict | None = None
        # 用户手动 resize 后的尺寸锚：切换构图不再主动缩小（见 _fit_window_to_layout）
        self._user_size: tuple[int, int] | None = None
        self._auto_resize_depth = 0        # 程序化改窗口尺寸时加锁，不写入用户锚
        # 最大化 / 全屏前的窗口几何；退出全屏时显式恢复它（见 changeEvent）
        self._pre_big_geometry: QtCore.QRect | None = None
        self._overlay_on = False           # 纯波形叠加模式下只有第 0 块在画
        self._overlay_sizes: list[int] | None = None
        self._region_sizes: dict[str, list[int]] = {}
        # 左栏的收起状态（三维面板的显隐由 _content_shown 统一管）
        self._region_shown: dict[str, bool] = {"left": True}

        # ---- 右侧工作区：三块内容面板（剖面 / 单道波形 / 三维）的显隐状态 + 排版。
        # 胶囊上三个图标是**纯开关**（亮=在显示、暗=已收起），含义与当前状态无关；
        # 「只看一块」由快捷键 1/2/3、Tab 承担。
        # 三块装在同一棵 splitter 树里，开关只是把尺寸插值过去（不 reparent）；
        # 换摆法才重建 splitter 树（三块容器本身不销毁）。
        # ``_pair_order`` 是"可换序那两块"的先后：三块时是没被钉住的两块（B 里
        # 剖面/三维、A 里 剖面/单道），两块时就是这两块；「⇄」只翻转它们。
        self._content_shown: dict[str, bool] = {"slice": True, "trace": False,
                                                "right": False}
        self._pair_order: list[str] = ["slice", "right"]
        self._layout_preset = "B"          # 三块摆法 B / A / BT / AL；两块时由"哪两块"决定
        # ---- 用户配置的**默认布局**（窗口设置里在缩略图上点 ★ 设定；空 = 用内置的那套）
        #   _default3_key   "" | "B" | "A" | "BT" | "AL"（空 = 内置 B）
        #   _default3_order 三块构图里"可换序那两块"的先后（空 = 内置 three_free_pair）
        #   _pair_defaults  两块构图每组合各自的先后，键 "SR"/"TR"/"ST"（缺 = 内置 PAIR_LAYOUT）
        self._default3_key = ""
        self._default3_order: tuple = ()
        self._pair_defaults: dict[str, tuple] = {}
        self._follow_layout = True         # 窗口大小跟着排版自动调整（窗口设置里可关）
        self._show_split_panel = True      # 胶囊上是否显示「分屏」按钮（关掉后摆法面板不弹）
        self._suppress_window_resize = False   # 换摆法时先别动窗口，交给 _animate_layout_change
        self._window_target: tuple[int, int] | None = None    # 最近一次算出的目标窗口尺寸
        self._layout_anim: QtCore.QPropertyAnimation | None = None
        self._three_auto_closed = False    # 三维是被"二维数据"自动收起的
        self._is_2d = False                # 当前数据集是不是二维（ns == 1）
        self._size_anims: dict[int, QtCore.QVariantAnimation] = {}
        # 树里的分割器；三块容器与叶子模态见 _build_work_tree
        self._tree: dict | None = None
        self._tree_splitters: list[QtWidgets.QSplitter] = []
        # 拖动手势：标题行 → 被拖走的面板；以及一次拖动过程中的临时状态
        self._drag_watch: dict[QtWidgets.QWidget, QtWidgets.QWidget] = {}
        self._drag: dict | None = None
        self._import_busy = False          # 拖入导入进行中（读文件 / 弹意图框）
        # 左栏状态（先从本地记的设置里读回来，再建界面）
        self._settings = QtCore.QSettings(APP_NAME, "SeisView")
        self._left_min_w = self.LEFT_MIN_W   # 建完卡片后按内容实测再校正（见 _sync_left_min_width）
        self._group_expanded: dict[str, bool] = dict(self.GROUP_DEFAULT)
        # 加入侧边栏轨道的分组（齿轮里勾选的那几组）；默认全部加入
        self._rail_keys: list[str] = list(self.GROUP_ORDER)
        self._active_group: str | None = None    # 轨道上高亮的那一组（跳转后短暂点亮）
        self._theme_key = "deepblue"        # 主题选择（可为 "system"＝跟随系统）
        self._scheme_hook = None            # "跟随系统"时挂上的 colorSchemeChanged 连接
        self._group_anim: QtCore.QVariantAnimation | None = None
        self._group_anim_busy = False       # 批量收放中（外部驱动，单卡动画让位）
        self._detached: dict[object, FloatingPanel] = {}
        self.panel_holders: list[QtWidgets.QWidget] = []
        # 拖动中的两份瞬时状态（只影响布局推导，不改变真实开关/停靠状态）：
        #   _drag_vis    —— 这一块正在被拖走 ⇒ **当作不在窗口里**，剩下几块立刻按预设铺满
        #   _preview_dock—— 落位预览命中 ⇒ **当作已经停靠**，把它的槽位先占出来画预览
        self._drag_vis: set[str] = set()
        self._preview_dock: set[str] = set()
        self._preview_state: tuple | None = None
        self._preview_cap: dict | None = None      # 预览挤占用的"让位态"各块尺寸（只量一次）
        # 拖动开始时**冻结一次**判定基准（轴 + 区域）：不冻结的话，挤占会改变布局 →
        # 判定区域跟着动 → 光标相对位置变化 → 意图翻转 → 布局再变，来回震荡成"抖动"。
        self._zone_frozen: tuple | None = None

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._place_done = False
        self._load_ui_state()              # 先把上次的左栏状态读回来，再照着建界面
        # 主题也先装上：界面要在**正确的调色板**下建出来，免得开场闪一下默认配色
        style.set_theme(self._theme_key, QtWidgets.QApplication.instance())
        self._build_ui()
        self._sync_color_scheme_hook()     # 选了"跟随系统"就跟着系统深浅走
        self._place_window()

        # 快捷键：键盘党最常用的两个
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+O"), self, self.open_file)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+E"), self, self.export_volume)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------ 便捷访问
    @property
    def vol(self) -> SeisVolume | None:
        """当前（激活的）数据体。"""
        return self.datasets[self.active].vol if self.datasets else None

    @property
    def pos(self) -> dict:
        """当前数据的切片位置。"""
        return self.datasets[self.active].pos if self.datasets else {}

    @property
    def mode(self) -> str:
        return self.datasets[self.active].mode if self.datasets else "shot"

    @mode.setter
    def mode(self, value: str) -> None:
        if self.datasets and value in SLICE_LABELS:
            self.datasets[self.active].mode = value

    def _place_window(self) -> None:
        """按目标屏幕的可用区域定初始尺寸与位置。

        多屏 + 混合缩放的坑：副屏可能只有 1463×866 的逻辑可用区域（1.75 倍缩放），
        一旦写死的初始尺寸比它还大，窗口管理器居中后四条边全在屏幕外，
        标题栏跑到屏幕上方就再也拖不回来了。所以初始尺寸必须按目标屏幕的
        可用区域收窄，并用 setGeometry 显式摆到屏幕内（而不是听天由命）。
        """
        gui = QtGui.QGuiApplication
        screen = (gui.screenAt(QtGui.QCursor.pos())
                  or gui.primaryScreen() or self.screen())
        if screen is None:
            self.resize(*self.DESIRED_SIZE)
            return
        avail = screen.availableGeometry()
        w = min(self.DESIRED_SIZE[0], max(640, int(avail.width() * 0.92)))
        h = min(self.DESIRED_SIZE[1], max(480, int(avail.height() * 0.92)))
        # 最小尺寸也不能超过屏幕，否则照样缩不进屏幕里
        self.setMinimumSize(min(self.MIN_SIZE[0], w), min(self.MIN_SIZE[1], h))
        self._auto_resize_depth += 1
        try:
            self.setGeometry(avail.left() + max(0, (avail.width() - w) // 2),
                             avail.top() + max(0, (avail.height() - h) // 4),
                             w, h)
        finally:
            self._auto_resize_depth -= 1

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if not self._place_done:
            # 标题栏和边框的尺寸只有 show 之后才拿得到，所以此时再精确校正一次
            self._place_done = True
            QtCore.QTimer.singleShot(0, self._first_layout)

    def _first_layout(self) -> None:
        """窗口真正显示之后再来一遍：此时 splitter 的尺寸才是真实像素，
        按它算出来的分栏比例才不会一开场就偏掉（不带动画，免得开场抖一下）。"""
        self._ensure_on_screen()
        self._relayout_content(animate=False)
        # 上次退出时左栏如果是收起的，这里**直接落到收起的终态**（不带动画）。
        # 不能调 _set_region_visible(False)：它开头有"状态没变就直接 return"的短路，
        # 而这里 _region_shown 早就是 False 了 —— 短路之后 left_content 根本没被隐藏，
        # 只被压成十几像素的一条，于是**启动时侧边栏位置会露出半截内容、它的竖向滚动条
        # 还压在图标轨道上**；打开一次设置面板再关掉才恢复正常（用户看到的就是这个）。
        if not self._region_shown.get("left", True):
            self.left_wrap.setMinimumWidth(self.LEFT_RAIL_W)
            self.left_wrap.setMaximumWidth(self.LEFT_RAIL_W)
            self.left_content.setVisible(False)
            self._freeze_content_width(None)
            self._sync_rail()

    def _default_window_size(self) -> tuple[int, int]:
        """刚打开软件时用的窗口尺寸（与 _place_window 同一套屏幕余量口径）。"""
        gui = QtGui.QGuiApplication
        screen = self.screen() or gui.primaryScreen()
        if screen is None:
            return self.DESIRED_SIZE
        avail = screen.availableGeometry()
        w = min(self.DESIRED_SIZE[0], max(640, int(avail.width() * 0.92)))
        h = min(self.DESIRED_SIZE[1], max(480, int(avail.height() * 0.92)))
        return (w, h)

    def _ensure_on_screen(self) -> None:
        """把整个窗口（含标题栏与边框）校正到当前屏幕的可用区域内。"""
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        geo, frame = self.geometry(), self.frameGeometry()
        lm = geo.left() - frame.left()          # 左边框宽
        tm = geo.top() - frame.top()            # 标题栏高
        rm = frame.right() - geo.right()        # 右边框宽
        bm = frame.bottom() - geo.bottom()      # 下边框高
        w = min(geo.width(), max(320, avail.width() - lm - rm))
        h = min(geo.height(), max(240, avail.height() - tm - bm))
        self._auto_resize_depth += 1
        try:
            self.setGeometry(
                max(avail.left() + lm, min(geo.left(), avail.right() - w - rm)),
                max(avail.top() + tm, min(geo.top(), avail.bottom() - h - bm)),
                w, h)
        finally:
            self._auto_resize_depth -= 1

    # --------------------------------------------------- 位置锚点（auto-fit 不搬窗口）
    def _frame_anchor(self) -> QtCore.QPoint:
        """当前窗口**外框**的左上角 —— 改尺寸时以它为锚点。"""
        return self.frameGeometry().topLeft()

    def _client_offset(self) -> QtCore.QPoint:
        """客户区相对外框的偏移（标题栏高度 + 左边框宽度）。"""
        return self.geometry().topLeft() - self.frameGeometry().topLeft()

    def _resize_keeping_anchor(self, w: int, h: int,
                               anchor: QtCore.QPoint | None = None) -> None:
        """改窗口尺寸，但**外框左上角不动**。

        auto-fit 只该改大小，绝不该搬窗口 —— 原先直接调 ``resize``，尺寸一变 Qt 就
        重算外框与客户区的偏移，位置被当成"尺寸的副产品"每帧重算，于是每点一次胶囊
        窗口就往左上挪一个边框宽度（离屏 2px，真机是标题栏+边框），累积成"一步步
        跑到屏幕上方"。这里改成以改尺寸之前的外框左上角为准落回去。
        """
        if anchor is None:
            anchor = self._frame_anchor()
        off = self._client_offset()
        self._auto_resize_depth += 1
        try:
            self.setGeometry(anchor.x() + off.x(), anchor.y() + off.y(),
                             max(1, int(w)), max(1, int(h)))
        finally:
            self._auto_resize_depth -= 1

    def _restore_anchor(self, anchor: QtCore.QPoint | None) -> None:
        """把外框左上角拉回 ``anchor``（改尺寸过程中可能被隐式 resize 挪走）。"""
        if anchor is None or not self.isVisible():
            return
        if self.frameGeometry().topLeft() == anchor:
            return
        off = self._client_offset()
        self._auto_resize_depth += 1
        try:
            self.setGeometry(anchor.x() + off.x(), anchor.y() + off.y(),
                             self.width(), self.height())
        finally:
            self._auto_resize_depth -= 1

    # ================================================================== 界面
    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)
        # 状态栏先建：中间的折叠逻辑在构造期就会往状态栏写提示，得先有它
        statusbar = self._build_statusbar()
        outer.addWidget(self._build_topbar())

        # 结构：左边"设置栏（图标轨道 + 内容区）" ｜ 右侧工作区。
        # 工作区里再按预设自由组合三块内容面板（剖面/单道上下，三维与它们左右）。
        self.body_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.body_split.setChildrenCollapsible(False)
        self.body_split.addWidget(self._build_left())
        self.workspace = self._build_workspace()
        self.body_split.addWidget(self.workspace)
        self.body_split.setStretchFactor(0, 0)
        self.body_split.setStretchFactor(1, 1)
        self.body_split.setSizes([self._left_min_w, 1190])
        outer.addWidget(self.body_split, 1)
        outer.addWidget(statusbar)

        # 初始排版：只有剖面（单道与三维默认收起，不带动画，免得开场抖一下）
        self._relayout_content(animate=False)
        self._sync_panel_chips()
        self._sync_empty_hint()          # 还没有数据：剖面区先显示"拖文件进来"的引导

    # ------------------------------------------------------------ 工作区
    def _build_workspace(self) -> Workspace:
        """右侧工作区 = 三块内容面板的容器 + 悬浮在右上角的胶囊。

        三块容器（剖面 / 单道 / 三维）**先各自建好**，再由 :meth:`_build_work_tree`
        按当前分屏方式把它们装进不同的 splitter 树里。这样切分屏方式只动 splitter，
        容器和里面的视图一律不动（三维的 GL 上下文、剖面面板的视野都不会被重置）。
        """
        wrap = Workspace()
        v = QtWidgets.QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._build_slice()
        self._build_trace()
        self._build_right()
        # 三块容器都允许被压到 0：单视图/分屏切换就是"把尺寸插值到 0"。
        for w in (self.slice_holder, self.slice_wrap,
                  self.trace_holder, self.right_holder):
            w.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                            QtWidgets.QSizePolicy.Policy.Ignored)

        self.work_host = QtWidgets.QWidget()
        self._work_host_layout = QtWidgets.QVBoxLayout(self.work_host)
        self._work_host_layout.setContentsMargins(0, 0, 0, 0)
        self._work_host_layout.setSpacing(0)
        v.addWidget(self.work_host, 1)
        self._build_work_tree()

        # 胶囊：浮层，不进布局
        self.capsule = PanelCapsule(wrap)
        for kind, btn in self.capsule.buttons.items():
            key = CAPSULE_KEY[kind]
            # 单击 = 纯开关（显示↔收起）；右键 = 打开摆法面板
            btn.clicked.connect(lambda _c=False, k=key: self._toggle_content(k))
            btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(self.open_layout_picker)
        self.capsule.swap_btn.clicked.connect(self._swap_main)
        self.capsule.split_btn.clicked.connect(self._toggle_layout_picker)
        self.capsule.split_btn.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.capsule.split_btn.customContextMenuRequested.connect(self.open_layout_picker)
        wrap.capsule = self.capsule
        wrap.place_capsule()
        self._sync_split_entry()     # 按窗口设置决定「分屏」按钮出不出现（启动即生效）

        # 三块面板的标题行都挂上拖动：剖面拖的是**整个剖面区域**（组），
        # 单道/三维拖的是各自的面板。对比时组内每幅剖面另有“只换序”的手势。
        self._watch_drag(self.slice_header, self.slice_wrap)
        self._watch_drag(self.trace_header, self.trace_frame)
        self._watch_drag(self.right_header, self.right_frame)

        # 三块标题行右端各留一个"可伸缩的空白"：右上角那一块要给悬浮胶囊让位，
        # 否则标题行右侧的读数会被盖住（见 _sync_header_pads）。
        self._head_pads: dict[str, QtWidgets.QSpacerItem] = {}
        for key, head in (("slice", self.slice_head), ("trace", self.trace_head),
                          ("right", self.right_head)):
            item = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Policy.Fixed,
                                         QtWidgets.QSizePolicy.Policy.Minimum)
            head.addSpacerItem(item)
            self._head_pads[key] = item
        return wrap

    def _shown_list(self) -> list:
        """当前显示着的块，按 1 → 2 → 3 的固定次序。"""
        return [k for k in PANEL_ORDER if self._content_shown.get(k)]

    def _layout_vis(self) -> list:
        """决定**当前构图**的那份可见集合：几何上真的看得见的那几块。

        与 :meth:`_shown_list`（开关状态）不是一个东西 —— 被拉到独立窗口的那块，槽位
        已经让出来了，构图就该按**剩下的块**重新定。否则把它拖出去后，剩下两块会继续
        沿用三块构图那棵树和那套尺寸：实测拖出剖面后，两块落在 B 的 0.72/0.28 上，
        比例与缩略图对不上，看着就不像设计好的那三种两栏构图。
        """
        eff = self._effective_shown()
        return [k for k in PANEL_ORDER if eff[k]]

    def _layout_key(self) -> str:
        """当前这套排版是"七个具体摆法"里的哪一个（用于面板亮框）。

        只有一块界面时谈不上"排法"，返回空串（面板里就不亮任何一张）。
        """
        vis = self._layout_vis()
        if len(vis) >= 3:
            # 三块时构图由 ``_layout_preset`` 定；万一它还是"两块摆法"的键（例如从两块
            # 构图里又找回一块），退回默认的 B —— 别让三块挤在一行里。
            return self._layout_preset if self._layout_preset in THREE_KEYS else "B"
        if len(vis) == 2:
            return pair_layout(tuple(vis))[0]
        return ""

    def _builtin_order_for(self, key: str) -> tuple:
        """某张摆法的**内置**先后（用户没设过默认时的那一套）。"""
        if GROUP_OF.get(key, 0) >= 3:
            return three_free_pair(PINNED_OF.get(key, "trace"), PANEL_ORDER)
        pair = KEY_PAIR.get(key)
        if pair is None:
            return ("slice", "right")
        return tuple(pair_layout(pair)[2])

    def _thumb_order(self, key: str) -> tuple:
        """某张缩略图该画的先后 —— **就是点它会得到的那一套**。

        三块：用户把这张设成默认（且存了先后）就用存的那套，否则用内置；
        两块：这一组合设过默认就用设的，否则用内置。返回空元组表示"这张不适用"。
        """
        if not key:
            return ()
        if GROUP_OF.get(key, 0) >= 3:
            if self._default3_key == key and len(self._default3_order) == 2:
                return tuple(self._default3_order)
            return self._builtin_order_for(key)
        saved = self._pair_defaults.get(key)
        return tuple(saved) if saved else self._builtin_order_for(key)

    def _free_pair(self) -> tuple:
        """"可换序的那两块"的**默认**先后（不含被钉住的那块）：有用户配置就用配置的。"""
        vis = self._layout_vis()
        if len(vis) >= 3:
            return self._thumb_order(self._layout_key())
        if len(vis) == 2:
            return self._thumb_order(pair_layout(tuple(vis))[0])
        return tuple(vis)

    def _star_keys(self) -> set:
        """哪些缩略图该亮 ★ —— 即"各组合**当前生效**的默认"（含内置）。

        三块组只有一个生效项；两块组每个组合各有一个。
        """
        out = {self._default3_key or "B"}
        for key, pair in KEY_PAIR.items():
            saved = self._pair_defaults.get(key)
            out.add(key if saved else pair_layout(pair)[0])
        return out

    def _is_builtin_default(self) -> bool:
        """三块默认与三种两块默认**全都是内置**的（用来在提示行里写明"内置/自定义"）。"""
        return (not self._default3_key and not self._default3_order
                and not self._pair_defaults)

    def _sync_pair_order(self) -> None:
        """让 ``_pair_order`` 跟"当前可换序的那两块"对齐；换了组合就回到这一对的默认先后。

        默认先后就是需求里定的那三种（剖面+三维 → 左剖面右三维；单道+三维 → 上三维下单道；
        剖面+单道 → 上剖面下单道），**但用户可以在摆法面板里点 ★ 改掉它**。所以"⇄"的翻转
        只在这套组合内有效，换组合即回到该组合的默认。
        """
        want = self._free_pair()
        if len(want) != 2:
            self._pair_order = list(want)
            return
        if sorted(self._pair_order) != sorted(want):
            self._pair_order = list(want)

    def _align_pair_order(self, first: str | None = None) -> None:
        """对齐"可换序那两块"的先后：**集合没变就保序**（不要复位成默认），变了才回默认。

        这是拖动落位要的"按当前位置保序"：例如原来在 B 里用「⇄」把三维换到左边，
        把单道拖走/拖回之后，剩下的"剖面+三维"仍要保持三维在左。``first`` 非空时
        把它提到最前（拖动贴边时用："拖的那块排前面"）。
        """
        want = list(self._free_pair())
        if len(want) == 2:
            if not (len(self._pair_order) == 2
                    and sorted(self._pair_order) == sorted(want)):
                self._pair_order = want
        else:
            self._pair_order = want
        if first and first in self._pair_order:
            self._pair_order = [first] + [k for k in self._pair_order if k != first]

    def _slots(self) -> tuple:
        """三块在树里的**叶子顺序**（可换序的两块在前、钉住/收起的在后）。

        这个顺序同时是"缩略图里谁在左、谁在底"的依据，所以必须跟
        :meth:`_build_work_tree` 真正 addWidget 的顺序一致 —— 尤其是两块摆法，
        方向由这一对固定决定，先后则由「⇄」翻转，不能再按 1→2→3 的固定次序排。
        顺序按 :meth:`_layout_vis` 算：**被拖出去的那块排到最后（占 0 槽位）**，
        这样剩下两块才是那三种设计好的两栏构图。
        """
        vis = self._layout_vis()
        hidden = [k for k in PANEL_ORDER if k not in vis]
        if len(vis) >= 3:
            f1, f2 = self._free_pair()
            if len(self._pair_order) == 2 and set(self._pair_order) == {f1, f2}:
                f1, f2 = self._pair_order
            return (f1, f2, PINNED_OF.get(self._layout_key(), "trace"))
        if len(vis) == 2:
            f1, f2 = self._free_pair()
            if len(self._pair_order) == 2 and set(self._pair_order) == {f1, f2}:
                f1, f2 = self._pair_order
            return (f1, f2, hidden[0])
        return tuple(vis + hidden)

    def _build_work_tree(self) -> None:
        """按当前摆法把三块容器装进 splitter 树。

        五个摆法分两类：
          三块  B → V( H(f1, f2), 单道 )    上排两块左右 + 单道底部通栏（默认）
               A → H( V(f1, f2), 三维 )    左列两块上下 + 三维右列
          两块  H( f1, f2, 收起的一块 )     左右并排
               V( f1, f2, 收起的一块 )     上下排列
        其中 ``f1, f2`` 是 :meth:`_free_pair` 的先后 —— 「⇄」翻转它们即可换"谁在左、
        谁在下"。被钉住的那块（B 的单道 / A 的三维）在树里的位置固定，所以
        "单道永远在底栏、三维永远在右列"是结构保证的，不靠分配器。

        这里重建的是 **splitter 本身**；三块容器只是被插进新的槽位（``setParent(None)``
        后立刻挂到新分割器上，中间没有任何一次事件循环，视图不会被重建）。
        """
        self._stop_all_size_anims()
        leaves = {"slice": self.slice_holder, "trace": self.trace_holder,
                  "right": self.right_holder}
        self._sync_pair_order()
        visit = self._layout_vis()          # 构图按"实际可见"算（被拖出的那块让位）
        old_root = getattr(self, "work_tree", None)
        for w in leaves.values():
            w.setParent(None)              # 先摘出来，免得跟着旧树一起被删
        if old_root is not None:
            for sp in list(self._tree_splitters):
                sp.setParent(None)
                sp.deleteLater()
        self._tree_splitters = []

        def make(orient):
            sp = QtWidgets.QSplitter(orient)
            sp.setChildrenCollapsible(True)
            sp.setHandleWidth(4)
            self._tree_splitters.append(sp)
            return sp

        tree = {}
        preset3 = self._layout_key() if len(visit) >= 3 else None
        if preset3 in ("A", "AL"):
            # 左列（或右列）两块上下叠放 + 三维一列；AL 是 A 的镜像（三维在左）。
            f1, f2 = self._slots()[:2]         # 取**已换过序**的先后（⇄ / 拖动保序都靠它）
            inner = make(QtCore.Qt.Orientation.Vertical)
            inner.addWidget(leaves[f1])
            inner.addWidget(leaves[f2])
            root = make(QtCore.Qt.Orientation.Horizontal)
            if preset3 == "A":
                root.addWidget(inner)
                root.addWidget(leaves["right"])
            else:
                root.addWidget(leaves["right"])
                root.addWidget(inner)
            tree["inner"], tree["free"] = inner, (f1, f2)
        elif preset3 in ("B", "BT"):
            # 上排两块左右并排 + 单道通栏；BT 是 B 的镜像（单道在上）。
            f1, f2 = self._slots()[:2]         # 取**已换过序**的先后（⇄ / 拖动保序都靠它）
            top = make(QtCore.Qt.Orientation.Horizontal)
            top.addWidget(leaves[f1])
            top.addWidget(leaves[f2])
            root = make(QtCore.Qt.Orientation.Vertical)
            if preset3 == "B":
                root.addWidget(top)
                root.addWidget(leaves["trace"])
            else:
                root.addWidget(leaves["trace"])
                root.addWidget(top)
            tree["inner"], tree["free"] = top, (f1, f2)
        else:
            # 两块：方向由"哪两块"决定（就是需求里那三种两栏构图）；
            # 一块：方向无所谓（反正只显示一块），多出来的两块留在树里占 0，
            # 保证所有容器都有父控件。
            slots = self._slots()
            pair = tuple(slots[:2])
            orient = pair_layout(tuple(sorted(pair)))[1] if len(pair) == 2 else "H"
            root = make(QtCore.Qt.Orientation.Horizontal if orient == "H"
                        else QtCore.Qt.Orientation.Vertical)
            for k in slots:
                root.addWidget(leaves[k])
            tree["free"] = None
        tree["preset"] = self._layout_key()
        tree["slots"] = tuple(self._slots())
        tree["root"] = root
        self._tree = tree
        self.work_tree = root
        self._work_host_layout.addWidget(root)

    # ---------------------------------------------------------------- 顶栏
    def _build_topbar(self) -> QtWidgets.QFrame:
        bar, lay = make_panel()
        lay.setContentsMargins(14, 10, 12, 10)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        title = QtWidgets.QLabel("SEISVIEW")
        title.setObjectName("Title")
        # 版本号做成顶栏里一枚小签：截图、bug 报告里一眼能看出是哪个构建
        # （打包时还会把它写进 exe 的 FileVersion，见 seisview.spec / assets/version_info.txt）
        ver = QtWidgets.QLabel(f"v{__version__}")
        ver.setObjectName("Version")
        ver.setToolTip(f"SeisView {__version__}")
        sub = QtWidgets.QLabel("地震数据可视化")
        sub.setObjectName("Hint")
        row.addWidget(title)
        row.addWidget(ver)
        row.addWidget(sub)
        row.addSpacing(10)

        self.file_label = QtWidgets.QLabel("尚未打开文件")
        self.file_label.setObjectName("Status")
        row.addWidget(self.file_label)
        row.addStretch(1)

        self.btn_open = QtWidgets.QPushButton("打开文件")
        self.btn_open.setObjectName("Primary")
        self.btn_open.setMinimumWidth(104)
        self.btn_open.clicked.connect(self.open_file)

        self.btn_sample = QtWidgets.QPushButton("载入示例")
        self.btn_sample.setObjectName("Ghost")
        self.btn_sample.setMinimumWidth(92)
        self.btn_sample.setToolTip(
            "载入程序内置的合成三维体（不读文件）：\n"
            "24 炮 × 72 检波点 × 700 采样，dt=0.002 s，\n"
            "4 个倾斜反射层 + 2 个绕射点 + 噪声。")
        self.btn_sample.clicked.connect(self.load_sample)

        self.btn_clear = QtWidgets.QPushButton("清空数据")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.setMinimumWidth(92)
        self.btn_clear.setEnabled(False)
        self.btn_clear.setToolTip(
            "清空已载入的数据，并把界面还原成「刚打开」的样子：\n"
            "显示设置、面板布局、左栏分组都回到默认。")
        self.btn_clear.clicked.connect(self.clear_data)

        self.btn_export = QtWidgets.QPushButton("导出 / 转换")
        self.btn_export.setObjectName("Ghost")
        self.btn_export.setMinimumWidth(104)
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip(
            "导出整卷 / 逐剖面（可选片层范围）/ 当前剖面图片。　快捷键 Ctrl+E")
        self.btn_export.clicked.connect(self.export_volume)

        row.addWidget(self.btn_open)
        row.addWidget(self.btn_sample)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_export)
        lay.addLayout(row)
        return bar

    # ------------------------------------------------------------ 左侧控制
    # 分组顺序 = 使用链路：拿到数据 → 决定切哪一刀 → 决定怎么画 → 决定怎么比。
    # 「波形」与「对比」属于"要用时才找"的组，默认收起。
    GROUP_ORDER = ("data", "cut", "density", "wave", "compare")
    GROUP_TITLES = {"data": "数据", "cut": "剖切与播放", "density": "密度图",
                    "wave": "波形", "compare": "对比"}
    GROUP_DEFAULT = {"data": True, "cut": False, "density": False,
                     "wave": False, "compare": False}
    # 齿轮里每一组旁边的说明（一行话讲清"这组管什么"）
    GROUP_TIPS = {
        "data": "数据从哪来、物理标尺",
        "cut": "切哪一刀、播放哪一段",
        "density": "怎么上色、对比度与 AGC",
        "wave": "单道波形怎么画、叠加几条",
        "compare": "同时对比几份数据",
    }
    # 左栏最左侧那条常驻图标轨道的宽度
    LEFT_RAIL_W = 38
    # 左栏的宽度下限/上限（下限太窄会让并排的控件把滚动区撑出横向滚动条）
    LEFT_MIN_W = 300
    LEFT_MAX_W = 430
    # 内容宽度 = 左栏宽 − 轨道 − 间距 − 竖向滚动条 − 内容右边距
    # （竖向滚动条按 24 留余量：滚动条宽度随样式变化，多留一点免得贴着边界出横条）
    LEFT_CHROME_W = LEFT_RAIL_W + 6 + 24 + 6

    def _build_left(self) -> QtWidgets.QWidget:
        """左栏 = 常驻图标轨道 + 设置内容区。

        轨道不在被收起的那个容器里，所以整栏收起后它原地留下、图标一个都不挪 ——
        它本身就是内容的索引。内容区才是被压到 0 宽的那块。
        """
        wrap = QtWidgets.QWidget()
        wrap.setMinimumWidth(self.LEFT_MIN_W)     # 建完卡片后按内容实测再校正一次
        wrap.setMaximumWidth(self.LEFT_MAX_W)
        # 横向尺寸策略设成 Ignored：让 splitter 完全说了算。否则左栏内容的
        # minimumSizeHint（约 113px）会在展开动画的前半段把宽度顶住，前几帧
        # 几乎不动、后面突然窜上去 —— 看着就不顺。
        wrap.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                           QtWidgets.QSizePolicy.Policy.Preferred)
        h = QtWidgets.QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(self._build_rail())

        content = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # 侧边栏**不该有横向滚动条**：整栏本来就能收起/展开，横向滚动在这里没有意义，
        # 而且它会随载入过的数据名越来越宽（见 WheelSafeComboBox）。两道保险：
        #   1) 里层横向策略设成 Ignored —— 滚动区就按可视宽度给它，不会要求更宽；
        #   2) 横向滚动条直接关掉。
        # 内容本身放得下由 _sync_left_min_width 保证（它把左栏下限按内容实测钉好）。
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_body = scroll
        inner = QtWidgets.QWidget()
        inner.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                            QtWidgets.QSizePolicy.Policy.Preferred)
        col = QtWidgets.QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(8)

        self.cards: dict[str, FoldCard] = {}
        for key in self.GROUP_ORDER:
            card = FoldCard(self.GROUP_TITLES[key],
                            expanded=self._group_expanded.get(key,
                                                              self.GROUP_DEFAULT[key]),
                            icon_name=key)
            card.toggled.connect(lambda on, k=key: self._on_group_toggled(k, on))
            self.cards[key] = card
            col.addWidget(card)
        self._fill_data_card(self.cards["data"])
        self._fill_cut_card(self.cards["cut"])
        self._fill_density_card(self.cards["density"])
        self._fill_wave_card(self.cards["wave"])
        self._fill_compare_card(self.cards["compare"])
        # 一组都没加入侧边栏时显示的引导文案（平时隐藏，不占位）
        self.left_empty_hint = QtWidgets.QLabel(
            "当前侧边栏里没有加入任何设置项。\n\n"
            "点下面的齿轮打开「窗口设置」，勾选想要加入的设置分组；\n"
            "加入后每组会对应轨道上的一个图标。")
        self.left_empty_hint.setObjectName("EmptyHint")
        self.left_empty_hint.setWordWrap(True)
        self.left_empty_hint.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        self.left_empty_hint.setVisible(False)
        col.addWidget(self.left_empty_hint)
        col.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        h.addWidget(content, 1)

        self.left_content = content
        self.left_wrap = wrap
        self._sync_gated_controls()        # 全部卡片建好后再统一按依赖关系置灰
        self._sync_left_min_width()        # 按卡片实测宽度校正左栏下限（避免横向滚动条）
        self._update_group_summaries()
        self._sync_left_empty_hint()
        self._sync_rail()
        return wrap

    def _sync_left_min_width(self) -> None:
        """把左栏的宽度下限钉成"内容真正需要的宽度"。

        侧边栏里好几行是并排控件（下拉框 + 数字框 + 色块），合起来最宽的那张卡片
        决定内容需要多宽。原先下限写死 300 —— 比内容窄，里层滚动区就被撑宽，
        于是底下凭空多出一条横向滚动条，而且**刚打开、还没有任何数据时就有**。
        这里按卡片实测宽度算：既不长出横条，也不裁切任何一行。
        """
        widest = max((c.minimumSizeHint().width() for c in self.cards.values()),
                     default=0)
        self._left_min_w = max(self.LEFT_MIN_W, widest + self.LEFT_CHROME_W)
        self.left_wrap.setMinimumWidth(self._left_min_w)
        # 上限也要跟着让路：否则内容比上限还宽时，minimum>maximum 会互相打架
        self.left_wrap.setMaximumWidth(max(self.LEFT_MAX_W, self._left_min_w))

    def _sync_left_empty_hint(self) -> None:
        """按 ``_rail_keys`` 决定哪些分组卡片在左栏里出现；一组都没有 → 显示引导文案。"""
        if not hasattr(self, "left_empty_hint"):
            return
        for key, card in self.cards.items():
            card.setVisible(key in self._rail_keys)
        self.left_empty_hint.setVisible(not self._rail_keys)

    def open_preferences(self) -> None:
        """齿轮：打开「窗口设置」。确定后把勾选的分组与主题落盘。

        侧边栏只动"哪些组出现在轨道 / 左栏"，不动各组的收放状态 —— 取消勾选某组时，
        它只是从界面上消失，记在 ``_group_expanded`` 里的收放状态照旧保留，
        下次勾回来还是原来的样子。主题则是**边选边预览**：取消就把进来时的还回去。
        """
        theme_before = self._theme_key
        keys_before = list(self._rail_keys)
        follow_before = self._follow_layout
        split_before = self._show_split_panel
        dlg = PreferencesDialog(self.GROUP_ORDER, self.GROUP_TITLES, self.GROUP_TIPS,
                                keys_before, theme_key=theme_before,
                                on_theme=lambda k: self.apply_theme_key(
                                    k, persist=False, announce=False),
                                follow_layout=follow_before,
                                show_split=split_before, parent=self)
        accepted = dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
        keys = dlg.selected_keys() if accepted else keys_before
        chosen = dlg.theme_key() if accepted else theme_before
        follow = dlg.follow_layout() if accepted else follow_before
        split = dlg.show_split_panel() if accepted else split_before

        # 去掉已不在轨道里的组的"当前高亮组"，免得高亮留在一个看不见的图标上
        if self._active_group not in keys:
            self._active_group = None
        self._rail_keys = keys
        self._sync_left_empty_hint()
        self._sync_rail()
        # 主题：取消时这里会把预览过的配色换回原样；两种结局都落一次盘
        self.apply_theme_key(chosen, persist=True, announce=False)

        if split != split_before:
            self._show_split_panel = split
            self._save_ui_state()
            self._sync_split_entry()
            self.status.setText(
                "胶囊上的「分屏」按钮已显示。" if split
                else "已隐藏「分屏」按钮：摆法面板不再弹出，布局可用拖动与「⇄」调整"
                     "（默认布局照旧生效）。")
        elif follow != follow_before:
            self._follow_layout = follow
            self._save_ui_state()
            if follow:
                self._relayout_content(animate=False)   # 立刻按当前排版重算一次窗口
            self.status.setText(
                "窗口大小已改为" + ("跟随排版自动调整。" if follow
                                    else "只在需要时放大（不自动缩小）。"))
        elif chosen != theme_before:
            self.status.setText(
                f"窗口设置已更新；主题已切换为「{style.theme_label(chosen)}」。")
        elif keys != keys_before:
            self.status.setText("窗口设置已更新。")

    def _build_rail(self) -> QtWidgets.QWidget:
        """左栏最左侧的常驻图标轨道。

        自上而下：停靠图标 → 分隔线 → **已加入侧边栏的分组图标** → 分隔线 → ⇕ → 齿轮。

        图标只是"跳到某一组设置"的入口（点了就展开左栏、展开那一组、滚过去并高亮一下），
        它不代表显隐状态 —— 所以 ⇕（收起/展开已加入的那些组）和齿轮（管哪些组出现）
        各自只干一件事，互不纠缠。
        五个分组的按钮**全部都建**，只是按 `_rail_keys` 决定显不显示：这样齿轮里
        一勾一取消就能立刻生效，不用重建轨道。
        """
        rail = QtWidgets.QFrame()
        rail.setObjectName("Rail")
        rail.setFixedWidth(self.LEFT_RAIL_W)
        v = QtWidgets.QVBoxLayout(rail)
        v.setContentsMargins(5, 8, 5, 8)
        v.setSpacing(4)

        self.btn_left_dock = self._rail_button(28, 28, 22)
        self.btn_left_dock.clicked.connect(
            lambda: self._set_region_visible("left", not self._region_shown["left"]))
        v.addWidget(self.btn_left_dock, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        self._rail_sep_top = self._rail_separator()
        v.addWidget(self._rail_sep_top)

        self.rail_btns: dict[str, QtWidgets.QToolButton] = {}
        for key in self.GROUP_ORDER:
            btn = self._rail_button(28, 26, 18)
            btn.setCheckable(True)
            btn.setToolTip(self.GROUP_TITLES[key])
            btn.clicked.connect(lambda _c=False, k=key: self._goto_group(k))
            v.addWidget(btn, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.rail_btns[key] = btn

        # ⇕ 紧跟在分组图标下面，之间用一条细分隔线把"分组导航 / 全局动作"分开
        v.addWidget(self._rail_separator())

        self.btn_left_all = self._rail_button(28, 26, 18)
        self.btn_left_all.clicked.connect(self._toggle_all_groups)
        v.addWidget(self.btn_left_all, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        # 齿轮：窗口设置（管哪些组出现在侧边栏、外观等）。放在 ⇕ 下面。
        self.btn_prefs = self._rail_button(28, 26, 18)
        self.btn_prefs.setIcon(QtGui.QIcon(icons.gear(18, style.TEXT_DIM)))
        self.btn_prefs.setToolTip("窗口设置")
        self.btn_prefs.clicked.connect(self.open_preferences)
        v.addWidget(self.btn_prefs, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        self.rail = rail
        return rail

    @staticmethod
    def _rail_separator() -> QtWidgets.QFrame:
        sep = QtWidgets.QFrame()
        sep.setObjectName("HDivider")      # 与 _hdivider 同一套"行内样式需重刷"的处理
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;")
        return sep

    @staticmethod
    def _rail_button(w: int, h: int, icon: int) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton()
        btn.setObjectName("RailBtn")
        btn.setIconSize(QtCore.QSize(icon, icon))
        btn.setFixedSize(w, h)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        return btn

    # ---------------------------------------------------- 图标轨道：状态同步
    def _sync_rail(self) -> None:
        """轨道图标跟着当前状态换形换色。

        分组图标**只代表"跳到某一组"**，不代表显隐 —— 所以它们不随分组收放变色，
        只在"刚跳过去"的那一刻点亮一下（``_active_group``）。是否显示由
        ``_rail_keys`` 决定（齿轮里勾了谁就有谁）。
        """
        shown = self._region_shown.get("left", True)
        self.btn_left_dock.setIcon(QtGui.QIcon(icons.dock(
            22, style.TEXT_DIM if shown else style.TEXT_MUTE, style.ACCENT,
            expanded=shown, side="left")))
        self.btn_left_dock.setToolTip("收起设置面板" if shown else "展开设置面板")

        for key, btn in self.rail_btns.items():
            btn.setVisible(key in self._rail_keys)
            on = key == self._active_group
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
            btn.setIcon(QtGui.QIcon(icons.group(
                key, 18, style.ON_ACCENT if on else style.TEXT_MUTE)))
        self._rail_sep_top.setVisible(bool(self._rail_keys))

        # ⇕ 只管"已加入的那些组"：它们全都开着时才提示"全部收起"
        joined = self._rail_keys
        all_on = bool(joined) and all(self.cards[k].is_expanded() for k in joined)
        self.btn_left_all.setIcon(QtGui.QIcon(icons.collapse_all(18, style.TEXT_DIM)))
        self.btn_left_all.setToolTip(
            "没有已加入的设置项" if not joined else ("全部收起" if all_on else "全部展开"))

    def _goto_group(self, key: str) -> None:
        """轨道上的分组图标 = "打开这一组设置并转到它的位置"。

        和"只显示一种设置"不是一回事：这里**不动**别的分组，只保证这一组是展开的，
        然后把它滚到贴顶、标题行闪一下强调色、状态栏报一句 —— 让人明确知道
        "跳到了哪一组"，而不是把界面切换成另一个样子。
        """
        if not self._region_shown.get("left", True):
            self._set_region_visible("left", True)
        card = self.cards[key]
        grew = not card.is_expanded()
        if grew:
            card.set_expanded(True)
        self._active_group = key
        self._after_group_change()
        # 展开有 160ms 的动画：要等它跑完、内容长到最终高度、滚动区真的长出滚动条
        # 之后再滚 —— 否则此刻范围还是 0，怎么设都被夹在顶端，"贴顶"根本没发生。
        self._schedule_scroll_to_card(card, delay=(FoldCard.ANIM_MS + 40) if grew else 0)
        card.flash()
        # 轨道高亮与标题闪烁同步收尾：图标不代表"选中/显隐"，只作一次性的"我跳到了这儿"
        QtCore.QTimer.singleShot(700, self._clear_active_group)
        self.status.setText(f"已跳到「{self.GROUP_TITLES[key]}」设置。")

    def _schedule_scroll_to_card(self, card: QtWidgets.QWidget, delay: int = 0) -> None:
        """滚动到某张卡片贴顶：分两拍做。

        第一拍等展开动画结束，第二拍再等一次布局刷新（滚动条范围要等布局算完才更新）。
        两拍都只是"尽力贴顶"—— 卡片接近底部时 ``setValue`` 会自动夹到能到的最大值。
        """
        def _do() -> None:
            self._scroll_to_card(card)
            QtCore.QTimer.singleShot(0, lambda: self._scroll_to_card(card))
        QtCore.QTimer.singleShot(max(0, int(delay)), _do)

    def _clear_active_group(self) -> None:
        if self._active_group is None:
            return
        self._active_group = None
        self._sync_rail()

    def _scroll_to_card(self, card: QtWidgets.QWidget) -> None:
        inner = self.left_body.widget()
        if inner is None:
            return
        top = card.mapTo(inner, QtCore.QPoint(0, 0)).y()
        self.left_body.verticalScrollBar().setValue(max(0, top - 8))

    def _toggle_all_groups(self) -> None:
        """⇕：把**已加入侧边栏的那些组**一并展开 / 一并收起。

        没加入的组不参与 —— 它们本来就不在界面上，⇕ 去动它们只会让人费解。
        一组都没加入时 ⇕ 无事可做（左栏自己的空状态文案已经指了路）。
        """
        joined = [k for k in self.GROUP_ORDER if k in self._rail_keys]
        if not joined:
            return
        all_on = all(self.cards[k].is_expanded() for k in joined)
        self._set_all_groups(not all_on, keys=joined)

    def _set_all_groups(self, on: bool, keys: list[str] | None = None,
                        animate: bool = True) -> None:
        """把 ``keys`` 里的分组收放到 ``on``（默认 = 已加入侧边栏的那些组）。

        这些卡片共用**一个进度**：每帧只算一次插值、只触发一次布局，比多张卡片各推
        一次顺得多。动画期间还把垂直滚动条钉成"常显"，免得它中途出现/消失把整列
        宽度一起改掉（那会让内容逐帧重排）。
        """
        keys = [k for k in self.GROUP_ORDER
                if (keys is None or k in keys)]
        if not keys:
            self._after_group_change()
            return
        self._group_anim_busy = True
        try:
            spans = [(self.cards[k], self.cards[k].begin_anim(on)) for k in keys]
        finally:
            self._group_anim_busy = False

        if self._group_anim is not None:
            self._group_anim.stop()
            self._group_anim = None

        if not animate:
            for card, (_start, target) in spans:
                card.set_anim_height(target)
                card.end_anim()
            self._after_group_change()
            return

        # 滚动条钉成"常显"：免得它中途出现/消失把整列宽度一起改掉（那会让内容逐帧重排）
        area = self.left_body
        area.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        anim = QtCore.QVariantAnimation(self)
        anim.setDuration(FoldCard.ANIM_MS + 40)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        def _frame(v) -> None:
            for card, (start, target) in spans:
                card.set_anim_height(start + (target - start) * float(v))
            QtWidgets.QApplication.processEvents()      # 让这一帧真的画出来

        def _done() -> None:
            for card, (_start, target) in spans:
                card.set_anim_height(target)
                card.end_anim()
            area.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._group_anim = None
            self._after_group_change()

        anim.valueChanged.connect(_frame)
        anim.finished.connect(_done)
        self._group_anim = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _after_group_change(self, reset_scroll: bool = False) -> None:
        self._update_group_summaries()
        self._sync_rail()
        self._save_ui_state()
        self._sync_left_empty_hint()
        if reset_scroll:
            # 只有“清空数据/回到初始状态”才回顶部；普通展开/收起必须留在原地
            self.left_body.verticalScrollBar().setValue(0)

    def _on_group_toggled(self, key: str, on: bool) -> None:
        """某个分组被收放（点箭头 / 点整行 / 双击标题行）。

        不再有"手风琴"联动：多组可以自由同时展开，一组被收掉不影响其他组 ——
        这里是纯粹的"记状态 + 刷摘要"，把每个分组当成一件独立的事。
        滚动条位置要保住：内容高度变化后按标题行原来的屏幕位置反算，让被点的
        那一行留在原地（允许为容纳内容做最小必要位移）。
        """
        if self._group_anim_busy:
            return                       # 批量动画自己会收尾，这里不插手
        card = self.cards[key]
        bar = self.left_body.verticalScrollBar()
        inner = self.left_body.widget()
        top_before = (card.mapTo(inner, QtCore.QPoint(0, 0)).y() - bar.value()
                      if inner is not None else 0)
        self._after_group_change()

        def _keep_anchor() -> None:
            content = self.left_body.widget()
            if content is None:
                return
            # 让这张卡的标题行回到收放前的视口 y：滚动值 = 内容内 y − 目标视口 y
            target = card.mapTo(content, QtCore.QPoint(0, 0)).y() - top_before
            bar.setValue(max(0, target))

        # 展开动画 160ms；结束后布局才算最终高度，再下一轮事件循环滚动范围才更新
        QtCore.QTimer.singleShot(FoldCard.ANIM_MS + 30, _keep_anchor)
        QtCore.QTimer.singleShot(FoldCard.ANIM_MS + 60, _keep_anchor)

    # ---------------------------------------------------- 分组摘要（收起时显示）
    def _update_group_summaries(self) -> None:
        """给每张卡片的收起态写一行摘要：不展开也知道里面是什么值。

        只写**当前处于收起态**的卡片，并且内容不变就不写 —— 否则每次刷新都改
        一堆隐藏标签的文字，会让左栏反复重排（拖滑块时尤其明显）。
        """
        def put(key: str, text: str) -> None:
            card = self.cards[key]
            if not card.is_expanded() and card.summary_text() != text:
                card.set_summary(text)

        # 摘要刻意写得短：左栏一共三百来像素，太长会把标题行挤变形
        if self.datasets:
            vol = self.vol
            put("data", f"{vol.ns}×{vol.nr}×{vol.nt}")
            n = max(1, vol.slice_index_range(self.mode) - 1)
            put("cut", f"{SLICE_LABELS[self.mode]} {self.pos[self.mode]}/{n}")
        else:
            put("data", "未载入数据")
            put("cut", "无数据")
        cmap = str(self.cmap_combo.currentText()).split("（")[0]
        put("density", f"{cmap} · {self.contrast.value()}% · "
                       f"AGC {'开' if self.chk_agc.isChecked() else '关'}")
        wig = ("仅波形" if self.chk_pure.isChecked()
               else ("叠加" if self.chk_wiggle.isChecked() else "关"))
        put("wave", f"{wig} · {self.spin_wig.value()} 道")
        cnt = len(self.datasets)
        put("compare", f"{cnt}/{MAX_DATASETS}" + (
            " · 已同步" if cnt > 1 and self.chk_sync.isChecked() else ""))

    # ---------------------------------------------------- 左栏状态记忆
    def _load_ui_state(self) -> None:
        """恢复上次的左栏状态；读不到或格式不对就退回默认。

        ``SEISVIEW_NO_PERSIST=1`` 时**读写都不做**（只挡保存不够：测试里会被上次
        留下的状态污染，跑不出"全新启动"的行为）。
        """
        if not _PERSIST_UI:
            self._group_expanded = dict(self.GROUP_DEFAULT)
            self._rail_keys = list(self.GROUP_ORDER)
            self._theme_key = "deepblue"
            self._follow_layout = True
            self._show_split_panel = True
            self._reset_layout_defaults()
            return
        s = self._settings
        self._group_expanded = dict(self.GROUP_DEFAULT)
        self._region_shown["left"] = bool(s.value("ui/left_visible", True, type=bool))
        raw = str(s.value("ui/groups", "", type=str))
        parts = raw.split(",")
        if len(parts) == len(self.GROUP_ORDER) and all(p in ("0", "1") for p in parts):
            self._group_expanded = {k: (v == "1")
                                    for k, v in zip(self.GROUP_ORDER, parts)}
        # 轨道里加入了哪几组。用逗号分隔的一组 key；空串 = 一组都不加（合法状态）。
        raw = str(s.value("ui/rail_keys", ",".join(self.GROUP_ORDER), type=str))
        keys = [k for k in raw.split(",") if k in self.GROUP_ORDER]
        self._rail_keys = keys
        # 主题（含 "system"）。认不出来的键在 style.set_theme 里会退回默认。
        self._theme_key = str(s.value("ui/theme", "deepblue", type=str))
        # 窗口大小是否跟随右侧排版自动调整（默认开）
        self._follow_layout = bool(s.value("ui/follow_layout", True, type=bool))
        # 胶囊上是否显示「分屏」快捷按钮（默认开；关掉后摆法面板不再弹出）
        self._show_split_panel = bool(s.value("ui/show_split_panel", True, type=bool))
        # 默认布局（摆法面板里点 ★ 设定的那几项）
        self._reset_layout_defaults()
        raw = str(s.value("ui/default3", "", type=str))
        if raw in THREE_KEYS:
            self._default3_key = raw
            order = self._parse_pair_order(
                str(s.value("ui/default3_order", "", type=str)),
                self._builtin_order_for(raw))
            if len(order) == 2:
                self._default3_order = order
        for key, pair in KEY_PAIR.items():
            order = self._parse_pair_order(
                str(s.value(f"ui/pair_default_{key}", "", type=str)),
                self._builtin_order_for(key))
            if len(order) == 2:
                self._pair_defaults[key] = order

    def _reset_layout_defaults(self) -> None:
        """把"默认布局"清成内置的那一套（启动 / 无持久化时用）。"""
        self._default3_key = ""
        self._default3_order = ()
        self._pair_defaults = {}

    @staticmethod
    def _parse_pair_order(raw: str, builtin: tuple) -> tuple:
        """把 ``"slice,right"`` 解析成先后元组；**必须**与内置集合一致，否则视为无效（返回空）。

        这一层的校验是必须的：默认先后是要塞给 splitter 树的，集合对不上会让
        `_free_pair()` 返回与当前组合不匹配的两块 → 整个工作区构图错乱。
        """
        keys = tuple(k for k in raw.split(",") if k in PANEL_ORDER)
        if len(keys) != 2 or len(set(keys)) != 2:
            return ()
        return keys if set(keys) == set(builtin) else ()

    def _save_ui_state(self) -> None:
        if not _PERSIST_UI:
            return
        s = self._settings
        s.setValue("ui/left_visible", bool(self._region_shown.get("left", True)))
        s.setValue("ui/groups", ",".join(
            "1" if self.cards[k].is_expanded() else "0" for k in self.GROUP_ORDER))
        s.setValue("ui/rail_keys", ",".join(k for k in self.GROUP_ORDER
                                            if k in self._rail_keys))
        s.setValue("ui/theme", self._theme_key)
        s.setValue("ui/follow_layout", bool(self._follow_layout))
        s.setValue("ui/show_split_panel", bool(self._show_split_panel))
        s.setValue("ui/default3", self._default3_key)
        s.setValue("ui/default3_order", ",".join(self._default3_order))
        for key in KEY_PAIR:
            s.setValue(f"ui/pair_default_{key}",
                       ",".join(self._pair_defaults.get(key, ())))

    # ---------------------------------------------------- 主题切换
    def apply_theme_key(self, key: str, persist: bool = True,
                        announce: bool = True) -> None:
        """切换界面主题（``key`` 可为 ``"system"``＝跟随系统）。

        换主题要动的**不只是样式表**：图标、pyqtgraph 画布底、三维 GL 底色、
        plot 图例、控件自己的行内样式，都是按"当时"的颜色现画的，必须逐个重刷。

        **导出图不在其中** —— 它固定用论文白底，与主题无关（见 style.PAPER_*）。
        """
        style.set_theme(key, QtWidgets.QApplication.instance())
        self._theme_key = style.current_key()
        self._sync_color_scheme_hook()
        self._refresh_theme_widgets()
        if persist:
            self._save_ui_state()
        if not announce:
            return
        label = style.theme_label(self._theme_key)
        if self._theme_key == style.SYSTEM_KEY:
            light = style.current_theme() == "paper"
            label += f"（当前跟随到{'纸白' if light else '极夜黑'}）"
        self.status.setText(f"已切换主题：{label}")

    def _sync_color_scheme_hook(self) -> None:
        """只在"跟随系统"时监听系统深浅变化，换到固定主题就把连接摘掉。"""
        hints = QtGui.QGuiApplication.styleHints()
        if hints is None:                                   # pragma: no cover
            return
        try:
            hints.colorSchemeChanged.disconnect(self._on_system_scheme_changed)
        except Exception:
            pass
        self._scheme_hook = None
        if self._theme_key != style.SYSTEM_KEY:
            return
        try:
            hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
            self._scheme_hook = hints.colorSchemeChanged
        except Exception:                                   # pragma: no cover
            self._scheme_hook = None

    def _on_system_scheme_changed(self, *_args) -> None:
        """系统切了浅色/深色：跟随系统时立刻跟着换（不写回偏好，偏好仍是 system）。"""
        if self._theme_key != style.SYSTEM_KEY:
            return
        self.apply_theme_key(style.SYSTEM_KEY, persist=False)

    def _refresh_theme_widgets(self) -> None:
        """把"按当时颜色现画"的东西全部重刷一遍。

        需要手工补的只有这几类：现画的图标、pyqtgraph 画布/图例、三维 GL 底、
        控件自带的行内样式（分段按钮、分组横线）。其余控件都吃全局 QSS，会自己变。
        """
        self._sync_rail()
        self.btn_prefs.setIcon(QtGui.QIcon(icons.gear(18, style.TEXT_DIM)))
        self.btn_reset.setIcon(QtGui.QIcon(icons.reset_view(18, style.TEXT_DIM)))
        self._sync_panel_chips()
        for lab in self.findChildren(QtWidgets.QLabel, "GrabHandle"):
            lab.setPixmap(icons.grab(14, style.TEXT_MUTE))
        divider = f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;"
        for line in self.findChildren(QtWidgets.QFrame, "HDivider"):
            line.setStyleSheet(divider)
        for card in self.cards.values():
            card.restyle()
        for seg in self.findChildren(SegmentedControl):
            seg.restyle()
        for panel in self.panels:
            panel.restyle()
        self.trace_view.restyle()
        self._sync_trace_legend(force=True)
        if self.view3d is not None:
            self.view3d.restyle()
        for win in list(self._detached.values()):
            win.restyle()
        # 切片图是按当时的底色烘进 RGBA 的，缓存作废重画一遍
        if self.datasets:
            self._refresh_all(sync_controls=False)
        else:
            self._panel_cache.clear()
        self.update()



    def _fill_data_card(self, card: FoldCard) -> None:
        """「数据」：数据从哪来、物理标尺是多少。"""
        lay = card.body

        self.table = VariableTable()
        self.table.setMinimumHeight(86)
        self.table.itemSelectionChanged.connect(self._on_variable_selected)
        self.table.itemDoubleClicked.connect(lambda _i: self._load_selected_variable())
        lay.addWidget(self.table)

        hint = QtWidgets.QLabel("双击变量直接载入当前数据；一维变量看数值与波形。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.spin_dt = self._spin(0.000001, 1.0, 0.001, 6, " s")
        self.spin_dx = self._spin(0.01, 10000.0, 12.5, 3, " m")
        self.spin_ds = self._spin(0.01, 10000.0, 25.0, 3, " m")
        for i, (name, w) in enumerate([("采样间隔 dt", self.spin_dt),
                                       ("检波器间距 dx", self.spin_dx),
                                       ("炮点间距 ds", self.spin_ds)]):
            lab = QtWidgets.QLabel(name)
            lab.setObjectName("Hint")
            grid.addWidget(lab, i, 0)
            grid.addWidget(w, i, 1)
        lay.addLayout(grid)
        # 改完立刻生效（原先改了要重新载入才看得出差别），并同步三视图的标尺
        for w in (self.spin_dt, self.spin_dx, self.spin_ds):
            w.editingFinished.connect(self._apply_scales)
        scale_tip = QtWidgets.QLabel("改完回车即生效（只影响坐标显示）")
        scale_tip.setObjectName("Hint")
        scale_tip.setWordWrap(True)
        lay.addWidget(scale_tip)

        self.btn_load = QtWidgets.QPushButton("载入所选变量")
        self.btn_load.setObjectName("Primary")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._load_selected_variable)
        lay.addWidget(self.btn_load)

        self.src_info = QtWidgets.QLabel("等待数据")
        self.src_info.setObjectName("Hint")
        self.src_info.setWordWrap(True)
        lay.addWidget(self.src_info)
        return card

    @staticmethod
    def _spin(lo: float, hi: float, val: float, decimals: int,
              suffix: str) -> QtWidgets.QDoubleSpinBox:
        box = WheelSafeDoubleSpinBox()          # 滚轮不改值，见 widgets._NoWheelMixin
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setValue(val)
        box.setSuffix(suffix)
        box.setSingleStep(10 ** (-decimals))
        box.setMinimumWidth(96)
        return box

    def _fill_compare_card(self, card: FoldCard) -> None:
        """多数据对比：切换当前数据、决定是否同步剖面参数与目标道。"""
        lay = card.body

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QtWidgets.QLabel("当前数据")
        lab.setObjectName("Hint")
        self.dataset_combo = WheelSafeComboBox()
        self.dataset_combo.setToolTip("切换后，左侧各设置、单道波形与三维面板都跟着这份数据走")
        self.dataset_combo.currentIndexChanged.connect(self._on_active_changed)
        row.addWidget(lab)
        row.addWidget(self.dataset_combo, 1)
        lay.addLayout(row)

        self.chk_sync = QtWidgets.QCheckBox("同步剖面参数与目标道")
        self.chk_sync.setChecked(True)
        self.chk_sync.setToolTip(
            "打开时：切片方向 / 切片位置 / 目标道号在所有数据源之间保持一致，\n"
            "在任一块剖面上点击都会同步改到所有数据源。\n"
            "关闭时：各数据源各调各的。")
        self.chk_sync.toggled.connect(self._on_sync_toggle)
        lay.addWidget(self.chk_sync)

        brow = QtWidgets.QHBoxLayout()
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(6)
        self.btn_add = QtWidgets.QPushButton("＋ 添加对比数据")
        self.btn_add.clicked.connect(self.add_compare_file)
        self.btn_remove = QtWidgets.QPushButton("－ 移除当前数据")
        self.btn_remove.setObjectName("Ghost")
        self.btn_remove.clicked.connect(self.remove_dataset)
        brow.addWidget(self.btn_add, 1)
        brow.addWidget(self.btn_remove, 1)
        lay.addLayout(brow)

        tip = QtWidgets.QLabel("")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        self.compare_info = tip
        lay.addWidget(tip)
        return card

    def _fill_cut_card(self, card: FoldCard) -> None:
        """「剖切与播放」：把原来的「切片模式」和「扫掠播放」合成一组。

        两张卡干的本就是同一件事 —— 决定"现在看哪一片"：前者是手动跳，
        后者是自动扫。分在两处时用户总要在两组之间来回找。
        """
        self._fill_slice_card(card)
        card.body.addWidget(_hdivider())
        self._fill_playback_card(card)

    def _fill_slice_card(self, card: FoldCard) -> None:
        lay = card.body

        self.mode_ctl = SegmentedControl(
            [("shot", SLICE_LABELS["shot"]), ("recv", SLICE_LABELS["recv"]),
             ("time", SLICE_LABELS["time"])])
        self.mode_ctl.changed.connect(self._on_mode)
        lay.addWidget(self.mode_ctl)

        self.slice_slider = SliderRow("炮点 S")
        self.slice_slider.valueChanged.connect(self._on_slice_index)
        lay.addWidget(self.slice_slider)

        self.playhead = PlayheadTrack()
        self.playhead.seek.connect(self._on_slice_index)
        lay.addWidget(self.playhead)

        # 单步精确调整：放在"切片模式"里更合逻辑（原先混在连续播放那组按钮中间，
        # 容易误点成播放）
        step = QtWidgets.QHBoxLayout()
        step.setContentsMargins(0, 0, 0, 0)
        step.setSpacing(6)
        self.btn_prev = QtWidgets.QPushButton("◀  上一切片")
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next = QtWidgets.QPushButton("下一切片  ▶")
        self.btn_next.clicked.connect(lambda: self._step(1))
        step.addWidget(self.btn_prev, 1)
        step.addWidget(self.btn_next, 1)
        lay.addLayout(step)

        tip = QtWidgets.QLabel("点三维上的面、拖轨道，或用按钮单步切换。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    def _fill_playback_card(self, card: FoldCard) -> None:
        lay = card.body

        self.btn_play = QtWidgets.QPushButton("▶  播放")
        self.btn_play.setObjectName("Play")
        self.btn_play.setToolTip("从当前切片开始连续扫掠，看同相轴的横向连续性")
        self.btn_play.clicked.connect(self._toggle_play)
        lay.addWidget(self.btn_play)

        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        lab = QtWidgets.QLabel("速度")
        lab.setObjectName("Hint")
        self.speed_combo = WheelSafeComboBox()
        for name, interval in SPEEDS:
            self.speed_combo.addItem(name, interval)
        self.speed_combo.setCurrentIndex(1)
        # 播放中改速度要立刻生效：定时器起过之后间隔不会自己跟着下拉框变
        self.speed_combo.currentIndexChanged.connect(self._on_speed)
        self.chk_loop = QtWidgets.QCheckBox("循环")
        self.chk_loop.setChecked(True)
        row2.addWidget(lab)
        row2.addWidget(self.speed_combo, 1)
        row2.addWidget(self.chk_loop)
        lay.addLayout(row2)
        return card

    def _fill_density_card(self, card: FoldCard) -> None:
        """「密度图」：只管"怎么上色" —— 色标、对比度、增益、渲染抽稀。

        与「波形」拆开的理由：原来是同一张「显示」卡塞了 11 项，密度图与波形是
        两条独立的显示通道，用户调波形时不需要看见色标。
        """
        lay = card.body

        r1 = QtWidgets.QHBoxLayout()
        r1.setContentsMargins(0, 0, 0, 0)
        r1.setSpacing(8)
        lab1 = QtWidgets.QLabel("色标")
        lab1.setObjectName("Hint")
        self.cmap_combo = ColormapCombo()
        self.cmap_combo.setCurrentIndex(2)          # 默认红蓝，地震惯例
        self.cmap_combo.currentIndexChanged.connect(self._on_cmap)
        r1.addWidget(lab1)
        r1.addWidget(self.cmap_combo, 1)
        lay.addLayout(r1)

        r2 = QtWidgets.QHBoxLayout()
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(8)
        lab2 = QtWidgets.QLabel("色标上限")
        lab2.setObjectName("Hint")
        self.lab_clim = lab2                        # 跟着上面的下拉一起置灰
        self.clim_combo = WheelSafeComboBox()
        for name, key in CLIM_MODES:
            self.clim_combo.addItem(name, key)
        self.clim_combo.currentIndexChanged.connect(self._on_clim_mode)
        self.spin_manual = self._spin(0.000001, 1e9, 1.0, 4, "")
        self.spin_manual.setEnabled(False)
        self.spin_manual.valueChanged.connect(self._on_clim_mode)
        r2.addWidget(lab2)
        r2.addWidget(self.clim_combo, 1)
        r2.addWidget(self.spin_manual)
        lay.addLayout(r2)

        self.contrast = SliderRow("对比度", spin=True, suffix=" %", log=True)
        self.contrast.set_range(10, 1000, 100)
        self.contrast.set_tooltip(
            "对比度倍数：100% 就是基准色标窗口。滑杆为**对数刻度**，"
            "100% 在正中，向两侧每格按比例变化。\n"
            "数值越大 → 窗口越窄 → 被压成纯色（红/蓝）的样点越多、画面越「硬」；\n"
            "200% ≈ 窗口减半，1000% ≈ 窗口缩到 1/10；50% ≈ 窗口加倍，10% ≈ 放大 10 倍。")
        self.contrast.valueChanged.connect(self._on_contrast)
        lay.addWidget(self.contrast)

        # ---------------- 增益：AGC 及其窗口
        lay.addWidget(_hdivider())

        self.chk_agc = QtWidgets.QCheckBox("自动增益 AGC（按道归一化）")
        self.chk_agc.setToolTip(
            "按道做滑动窗口 RMS 归一化，把深浅部的能量拉到同一量级。\n"
            "开启后色标由 AGC 接管（「色标上限」会置灰）；对比度仍可微调。")
        self.chk_agc.toggled.connect(self._on_gate_toggle)
        lay.addWidget(self.chk_agc)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab3 = QtWidgets.QLabel("AGC 窗口")
        lab3.setObjectName("Hint")
        self.lab_agc = lab3
        self.combo_agc = WheelSafeComboBox()
        for name, points in AGC_WINDOWS:
            self.combo_agc.addItem(name, points)
        self.combo_agc.setToolTip(
            "滑动窗口的点数：整道 = 整条道一起归一化。\n"
            "点数越小，深浅部拉得越平，横向对比也越弱。不知道选哪个就先试 101 点。")
        self.combo_agc.currentIndexChanged.connect(lambda _i: self._refresh_all())
        row.addWidget(lab3)
        row.addWidget(self.combo_agc, 1)
        lay.addLayout(row)

        # ---------------- 性能：与「画成什么样」无关，只影响开销
        lay.addWidget(_hdivider())

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab4 = QtWidgets.QLabel("渲染抽稀")
        lab4.setObjectName("Hint")
        self.combo_dec = WheelSafeComboBox()
        for name, limit in DOWNSAMPLE:
            self.combo_dec.addItem(name, limit)
        self.combo_dec.setCurrentIndex(2)
        self.combo_dec.setToolTip("显示时剖面最多用这么多像素绘制（调小更流畅，细节会少一些）")
        self.combo_dec.currentIndexChanged.connect(lambda _i: self._refresh_all())
        row.addWidget(lab4)
        row.addWidget(self.combo_dec, 1)
        lay.addLayout(row)
        return card

    def _fill_wave_card(self, card: FoldCard) -> None:
        """「波形」：把原来散在三处的波形设置收拢成一组。

        原「显示」里的波形开关、「线型」三行、「单道波形」的目标道与归一化开关，
        本质是同一件事（画不画波形、画成什么样、取哪一道），拆成三张卡时
        用户调一个波形要在左栏上下跑三趟。
        """
        lay = card.body

        self.chk_wiggle = QtWidgets.QCheckBox("叠加波形（wiggle）")
        self.chk_wiggle.setToolTip(
            "在剖面上叠加波形曲线，看同相轴的形状与极性。\n"
            "与下面的「仅显示波形」是同一个显示通道：勾了「仅显示波形」就等于强制叠加。")
        self.chk_wiggle.toggled.connect(self._on_gate_toggle)
        lay.addWidget(self.chk_wiggle)

        self.chk_pure = QtWidgets.QCheckBox("仅显示波形（不画密度图）")
        self.chk_pure.setToolTip(
            "只画 wiggle 曲线、隐藏彩色密度图，便于观察波形的相位与形态。\n"
            "多数据对比时会把各数据源的波形**叠加在同一张剖面**上（曲线颜色/线型\n"
            "在下面的「线型」里设置），和单道波形面板的叠加方式一致。\n"
            "开启后波形参数不再置灰。")
        self.chk_pure.toggled.connect(self._on_pure_toggle)
        lay.addWidget(self.chk_pure)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab5 = QtWidgets.QLabel("波形道数")
        lab5.setObjectName("Hint")
        self.lab_wig = lab5
        self.spin_wig = WheelSafeSpinBox()
        self.spin_wig.setRange(1, 1000)
        self.spin_wig.setValue(60)
        self.spin_wig.setKeyboardTracking(False)   # 回车/失焦才提交，免得边敲边重绘
        self.spin_wig.setToolTip(
            "在剖面宽度内「等间隔抽取」这么多道画波形曲线，上限 1000。\n"
            "注意是「最多画多少条」，不是「每几道画一条」：\n"
            "填到超过该方向实际道数就等于不抽稀（每列一条）。\n"
            "道数太大时绘制开销会明显上升，卡的话配合「密度图」里的渲染抽稀一起调。")
        self.spin_wig.valueChanged.connect(lambda _v: self._refresh_all())
        row.addWidget(lab5)
        row.addWidget(self.spin_wig, 1)
        lay.addLayout(row)

        self.gain = SliderRow("波形幅度", spin=True, suffix=" %")
        self.gain.set_range(10, 250, 100)
        self.gain.set_tooltip("叠加波形的横向摆幅，100% 时一条曲线最宽到道间距的九成")
        self.gain.valueChanged.connect(lambda _v: self._refresh_all())
        lay.addWidget(self.gain)

        lay.addWidget(_hdivider())
        self._fill_trace_card(card)          # 目标道 + 峰值归一化（追加到同一张卡）
        lay.addWidget(_hdivider())
        self._fill_lines_card(card)          # 线型三行（追加到同一张卡）

    def _fill_trace_card(self, card: FoldCard) -> None:
        lay = card.body

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.spin_ts = WheelSafeSpinBox()
        self.spin_tr = WheelSafeSpinBox()
        for i, (name, spin) in enumerate([("目标炮点 S", self.spin_ts),
                                          ("目标检波器 R", self.spin_tr)]):
            spin.setRange(0, 0)
            spin.setMinimumWidth(96)
            spin.setToolTip(
                "单道波形取自哪一炮哪一道；「同步剖面参数与目标道」打开时，\n"
                "改一个就会同步改到所有对比数据。在剖面上点一下也会改这里。")
            spin.valueChanged.connect(self._on_target_sr)
            lab = QtWidgets.QLabel(name)
            lab.setObjectName("Hint")
            grid.addWidget(lab, i, 0)
            grid.addWidget(spin, i, 1)
        lay.addLayout(grid)

        self.chk_norm = QtWidgets.QCheckBox("按峰值归一化（对比时各道各自归一）")
        self.chk_norm.setChecked(True)
        self.chk_norm.setToolTip(
            "勾选：每条曲线按自己的峰值归一化，形态最容易对齐 —— 适合看相位、\n"
            "同相轴形态；但**绝对振幅差会被抹掉**，比较噪声强度、能量强弱时会失真。\n"
            "取消：直接画原始振幅，两份数据的量级差别都保留；\n"
            "量级差很大时其中一条会被压得很平，这是正常的。")
        self.chk_norm.toggled.connect(lambda _c: self._refresh_trace())
        lay.addWidget(self.chk_norm)

        tip = QtWidgets.QLabel(
            "在剖面上点一下即取该位置的道；对比模式下用不同颜色叠在一起。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    def _fill_lines_card(self, card: FoldCard) -> None:
        """导出线型：按数据顺序分配**导出图**里每条曲线的颜色与线型。

        刻意与屏幕上的曲线分开：屏上是深底 + 数据识别色（一眼能对上哪份数据），
        这里配的是导出 PNG/SVG（白底论文用图）里的线 —— 黑实线 / 红实线 / 蓝虚线
        那套论文惯例。所以这一组只喂给 ``_export_*``，屏上完全看不到它的效果。
        """
        lay = card.body
        lay.addWidget(SectionLabel("导出线型"))

        tip = QtWidgets.QLabel(
            "只影响导出的 PNG / SVG（白底论文用图），按当前数据顺序分配：\n"
            "数据 1 用第 1 行、数据 2 用第 2 行……\n"
            "屏幕上的曲线用的是数据识别色，不受这里影响。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.line_rows: list[tuple] = []
        for i in range(MAX_DATASETS):
            holder = QtWidgets.QWidget()
            row = QtWidgets.QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lab = QtWidgets.QLabel(f"数据 {i + 1}")
            lab.setObjectName("Hint")
            lab.setFixedWidth(44)
            combo_color = WheelSafeComboBox()
            for name, hexv in LINE_COLORS:
                combo_color.addItem(name, hexv)
            combo_style = WheelSafeComboBox()
            for name, key in LINE_STYLES:
                combo_style.addItem(name, key)
            combo_color.currentIndexChanged.connect(lambda _i, k=i: self._on_line_style(k))
            combo_style.currentIndexChanged.connect(lambda _i, k=i: self._on_line_style(k))
            swatch = QtWidgets.QLabel()
            swatch.setFixedSize(26, 12)
            row.addWidget(lab)
            row.addWidget(combo_color, 1)
            row.addWidget(combo_style, 1)
            row.addWidget(swatch)
            lay.addWidget(holder)
            self.line_rows.append((holder, combo_color, combo_style, swatch))

        btn_reset = QtWidgets.QPushButton("恢复默认")
        btn_reset.setObjectName("Ghost")
        btn_reset.setToolTip("恢复为 数据1 黑实线 / 数据2 红实线 / 数据3 蓝虚线")
        btn_reset.clicked.connect(self._reset_line_styles)
        card.add_header_widget(btn_reset)
        self._push_line_styles_to_widgets()

    # ------------------------------------------------------- 线型（颜色 / 线型）
    # 画笔与图例都交给 view2d 里那一个实现，保证面板 / wiggle / 导出图完全一致
    @staticmethod
    def _line_pen(style_pair: tuple[str, str], width: float = 1.4):
        return view2d.line_pen(style_pair, width)

    @staticmethod
    def _line_swatch(style_pair: tuple[str, str], w: int = 26, h: int = 12):
        """画一条与实际曲线同色同线型的小横线，贴在控件旁边做图例。"""
        return view2d.line_swatch_pixmap(style_pair, w, h)

    def _push_line_styles_to_widgets(self) -> None:
        """把当前线型写回控件（屏蔽信号，避免互相触发），并刷新色块。"""
        for i, (_holder, combo_color, combo_style, swatch) in enumerate(self.line_rows):
            color, dash = self.line_styles[i]
            combo_color.blockSignals(True)
            combo_style.blockSignals(True)
            combo_color.setCurrentIndex(max(0, combo_color.findData(color)))
            combo_style.setCurrentIndex(max(0, combo_style.findData(dash)))
            combo_color.blockSignals(False)
            combo_style.blockSignals(False)
            swatch.setPixmap(self._line_swatch(self.line_styles[i]))
        self._sync_line_row_enabled()

    def _sync_line_row_enabled(self) -> None:
        """没用到的槽位置灰（只改颜色，不改几何，避免左栏抖动）。"""
        n = max(1, len(self.datasets))
        for i, (holder, *_rest) in enumerate(self.line_rows):
            holder.setEnabled(i < n)

    def _reset_line_styles(self) -> None:
        self.line_styles = list(DEFAULT_LINE_STYLES)
        self._push_line_styles_to_widgets()
        if self.datasets:
            self._refresh_all(sync_controls=False)
        self.status.setText("线型已恢复默认：数据1 黑实线 / 数据2 红实线 / 数据3 蓝虚线。")

    def _on_line_style(self, index: int) -> None:
        if not (0 <= index < len(self.line_rows)):
            return
        _holder, combo_color, combo_style, swatch = self.line_rows[index]
        self.line_styles[index] = (combo_color.currentData() or "#111827",
                                   combo_style.currentData() or "solid")
        swatch.setPixmap(self._line_swatch(self.line_styles[index]))
        if self.datasets:
            self._refresh_all(sync_controls=False)

    def _sync_gated_controls(self) -> None:
        """把「当前设置下不参与计算」的控件置灰，让依赖关系看得见。

        置灰而不是隐藏：面板高度不跳，而且能看出这里本来有可调项。
        四处依赖：
          - AGC 窗口：不勾 AGC 时这个窗口点数根本用不上
          - 色标上限：AGC 一开，基准窗口就固定成逐片重算的稳健口径
          - 波形道数 / 颜色 / 幅度：既不叠波形也不走"仅显示波形"时它们不起作用
          - 对比开关：只有一份数据时没有"对比"可言

        这里**只改颜色、绝不改几何**：以前 AGC 下面挂过一行随时显隐的说明文字，
        一开关就整块重排，看上去就是面板「抖一下」。说明改挂到 tooltip 上了。
        """
        # 时间切片没有时间轴：AGC 置灰且不施加（勾选状态保留，切回竖直面自动恢复）
        time_mode = bool(self.datasets) and self.mode == "time"
        agc_on = self.chk_agc.isChecked() and not time_mode
        self.chk_agc.setEnabled(not time_mode)
        self.lab_agc.setEnabled(agc_on)
        self.combo_agc.setEnabled(agc_on)
        self.lab_clim.setEnabled(not agc_on)
        self.clim_combo.setEnabled(not agc_on)
        self.spin_manual.setEnabled(not agc_on and self.clim_combo.currentData() == "manual")

        pure = self.chk_pure.isChecked()
        wig_on = self.chk_wiggle.isChecked() or pure
        self.lab_wig.setEnabled(wig_on)
        self.spin_wig.setEnabled(wig_on)
        self.gain.setEnabled(wig_on)        # SliderRow 会把标题一起灰掉
        # 「仅显示波形」勾上后，叠加开关本身就没意义了（等价于已勾选）
        self.chk_wiggle.setEnabled(not pure)
        self._sync_line_row_enabled()

        n = len(self.datasets)
        self.chk_sync.setEnabled(n > 1)
        self.btn_remove.setEnabled(n > 1)
        self.btn_add.setEnabled(0 < n < MAX_DATASETS or n == 0)
        self.spin_ts.setEnabled(n > 0)
        self.spin_tr.setEnabled(n > 0)

    def _on_gate_toggle(self, _checked: bool = False) -> None:
        """AGC / 叠加波形 开关：先同步置灰状态，再重画。"""
        self._sync_gated_controls()
        self._refresh_all()

    def _on_pure_toggle(self, checked: bool) -> None:
        """「仅显示波形」开关。

        打开后只画 wiggle 曲线、隐藏彩色密度图，也不画网格 —— 曲线用**数据识别色**，
        在**当前主题**的底色上都是看得清的（浅色主题配的就是深色线）。
        对比模式下这一档会把各数据源的波形叠在同一张图上。
        """
        self._sync_gated_controls()
        self._refresh_all()
        if checked and len(self.datasets) > 1:
            self.status.setText("仅显示波形：已把各数据源的波形叠加在同一张剖面上。")

    # -------------------------------------------------------------- 剖面区
    def _build_slice(self) -> None:
        """剖面容器：并排若干块（单数据 1 块，对比时 2~3 块）+ 空状态引导。

        剖面区在布局树里是一个整体：**组标题行**承担“整块移动 / 拉出 / 换分屏”，
        对比时组内的每幅剖面只保留“交换数据顺序”的专用抓手。这样三个界面的
        六点抓手都在各自区域的左上角，语义也一致。
        """
        holder = QtWidgets.QWidget()
        hl = QtWidgets.QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        self.slice_holder = holder

        wrap, lay = make_panel()
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.slice_header, self.slice_head, self.slice_title = pane_header(
            "剖面", handle=True)
        # 操作提示只挂在这根标题行上（别挂在画面上，否则鼠标一停就挡住波形）
        self.slice_header.setToolTip(
            "整块拖动 = 移动 / 拉出独立窗口 / 拖到工作区边缘换分屏方式。\n"
            "画面：左键拖动平移、滚轮缩放、双击复位；点一下取该位置的道。")
        lay.addWidget(self.slice_header)
        self.slice_frame = wrap

        self.slice_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.slice_split.setChildrenCollapsible(False)
        self.slice_split.setHandleWidth(3)
        lay.addWidget(self.slice_split, 1)
        # 没有数据时，这一块换成一段引导文字 —— 空着一块黑面板，新用户不知道能干什么
        self.slice_empty = QtWidgets.QLabel(
            "把地震数据文件拖进这个窗口\n\n"
            "支持 SEG-Y / SU / NumPy(.npy / .npz) / MATLAB(.mat)\n"
            "也可以点右上角「载入示例」先看效果\n\n"
            "右上角的胶囊可以切换「只看一块 / 分屏」，右键换分屏方式")
        self.slice_empty.setObjectName("EmptyHint")
        self.slice_empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.slice_empty.setWordWrap(True)
        lay.addWidget(self.slice_empty, 1)
        self.slice_empty.setVisible(False)
        self.slice_wrap = wrap
        hl.addWidget(wrap)

    # -------------------------------------------------------------- 单道波形
    def _build_trace(self) -> None:
        """单道波形容器。外面套一层：面板被拉出去时容器留下占位（尺寸压到 0），
        这样它在 splitter 里的槽位与顺序都不会因为少了个子控件而错位。"""
        holder = QtWidgets.QWidget()
        th = QtWidgets.QVBoxLayout(holder)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(0)
        wrap2, lay2 = make_panel()
        lay2.setContentsMargins(8, 8, 8, 8)
        lay2.setSpacing(6)
        self.trace_header, self.trace_head, _trace_label = pane_header("单道波形")
        self.trace_header.setToolTip(
            "这条道取自剖面上被点中的位置；对比模式下各数据源用不同颜色叠在一起。\n"
            "画面上：滚轮缩放、左键拖动平移；标题行左端拖动 = 拉出独立窗口 / 换分屏方式。")
        self.trace_info = ValueLabel("—")
        self.trace_head.addWidget(self.trace_info)
        # 紧凑图例：只有对比模式才出现，小色条 + 数据序号，替代屏上那块大图例
        self.trace_legend = QtWidgets.QWidget()
        self._trace_legend_lay = QtWidgets.QHBoxLayout(self.trace_legend)
        self._trace_legend_lay.setContentsMargins(0, 0, 0, 0)
        self._trace_legend_lay.setSpacing(4)
        self.trace_legend.setVisible(False)
        self._trace_legend_key: tuple | None = None
        self.trace_head.addWidget(self.trace_legend)
        self.trace_head.addSpacing(24)     # 给浮窗右上角那颗"收回"按钮留出位置
        lay2.addWidget(self.trace_header)
        self.trace_view = TraceView()
        lay2.addWidget(self.trace_view, 1)
        th.addWidget(wrap2)
        self.trace_frame = wrap2
        self._trace_holder_layout = th     # 收回浮窗时把面板放回这里（不是它自己的布局！）
        self.trace_holder = holder

    # ------------------------------------------------ 内容面板显隐 + 布局预设
    def _is_single(self) -> bool:
        """现在是不是"只看一块"。"""
        return sum(1 for v in self._content_shown.values() if v) == 1

    def _swap_main(self) -> None:
        """「⇄」：把"可换序那两块"的先后对调。

        语义固定、不看当前摆法：三块 B 里是**上排的剖面 ↔ 三维**，三块 A 里是
        **左列的剖面 ↔ 单道**，两块时就是这两块。钉住的那块（B 的单道在底栏、
        A 的三维在右列）不参与，所以"单道永远在底、三维永远在右"不会被打乱。
        """
        if len(self._pair_order) < 2:
            self.status.setText("只有一块界面，没有可交换的对象。")
            return
        f1, f2 = self._pair_order
        self._pair_order = [f2, f1]
        self._suppress_window_resize = True
        try:
            self._build_work_tree()
            self._relayout_content(animate=False)
        finally:
            self._suppress_window_resize = False
        self._animate_layout_change()
        self.status.setText(f"已交换先后：现在是「{PANEL_LABELS[f2]}」在前、"
                            f"「{PANEL_LABELS[f1]}」在后。")

    def _apply_layout(self, key: str, first: str | None = None) -> None:
        """切到某个具体摆法；块数不够/多出来时**顺带对齐块数**（直接跳转，不置灰）。

        * 点三块摆法（A/B）而手上不足三块 → 补齐到三块；
        * 点两块摆法（SR/TR/ST）→ 直接换成它画的那两块；
        * 两块摆法之间互切时，只换"哪两块"，方向由这一对固定决定。

        ``first`` 指定"可换序那两块"里的第一个（拖动贴边时用："拖的那块排前面"）。
        """
        if key not in GROUP_OF:
            return
        want = GROUP_OF[key]
        # 这套构图要用的面板如果有在独立窗口里的，先收回来 —— 否则凑不齐块数，
        # "选了 A 却只排成两块"就是这么来的。
        self._reclaim(PANEL_ORDER if want >= 3 else KEY_PAIR[key])
        if want == 3:
            for k in PANEL_ORDER:
                self._content_shown[k] = True
            self._layout_preset = key
        else:
            pair = KEY_PAIR[key]
            self._content_shown = {k: (k in pair) for k in PANEL_ORDER}
        # 先后**同集合保序**（拖动贴边/拖动落位时不要把用户换过的顺序复位）
        self._align_pair_order(first)
        self._three_auto_closed = False
        if self._content_shown.get("right"):
            self._ensure_view3d()
        self._suppress_window_resize = True          # 窗口尺寸交给动画滑过去
        try:
            self._build_work_tree()
            self._relayout_content(animate=False)
        finally:
            self._suppress_window_resize = False
        self._animate_layout_change()
        self._hide_picker()               # 选完就把面板收起来
        vis = self._shown_list()
        self.status.setText(
            f"摆法 {key}：{PRESET_LABELS.get(key, '（拖动落位）')}"
            f"（{PRESET_TIPS.get(key, '拖动插到工作区一角产生的排布')}）；"
            f"现在显示 " + "、".join(PANEL_LABELS[k] for k in vis) + "。")

    def _sync_layout_for_count(self, force_default: bool = True) -> None:
        """块数一变就让摆法跟着走：三块落到**用户配置的默认三块构图**上，两块落到对应那一对。

        切换是**结构保证**的：B/BT 里单道固定在底/顶栏、A/AL 里三维固定在右/左列，所以块数
        变化只是把位置腾出来/收回去，不会让"单道跑到通栏以外"。

        **变成三块时回到默认构图**（``_default3_key``，没配过就是内置的 B：主+侧+底、单道在
        底栏）—— 这正是需求里说的"用胶囊开到三块时落到默认那一套"；想临时换一种，从摆法面板里
        点那张缩略图即可。
        ``force_default=False`` 用于"拖出 / 收回一块"的路径：那只是几何让位，
        不该顺手把用户当前选的构图改掉。

        可见集合按 :meth:`_layout_vis` 算（被拖出去的那块不算），这样拖出之后剩下两块
        一定落在设计好的那三种两栏构图上。
        """
        vis = self._layout_vis()
        if "right" in vis:
            self._ensure_view3d()
        if force_default:
            # "块数变化 → 回到默认构图"，**连同它的先后**：否则用户以前「⇄」翻过的那套会留着，
            # 看上去就像"默认没生效"（先后也是默认的一部分）。
            if len(vis) >= 3:
                self._layout_preset = self._default3_key or "B"
                self._pair_order = list(self._thumb_order(self._layout_preset))
            elif len(vis) == 2:
                self._pair_order = list(self._thumb_order(pair_layout(tuple(vis))[0]))
        self._sync_pair_order()
        key = self._layout_key()
        need = (self._tree is None or self._tree.get("preset") != key
                or tuple(self._tree.get("slots", ())) != tuple(self._slots()))
        if need:
            self._suppress_window_resize = True
            try:
                self._build_work_tree()
                self._relayout_content(animate=False)
            finally:
                self._suppress_window_resize = False
            self._animate_layout_change()
        else:
            self._relayout_content(animate=True)

    # -------------------------------------------------------------- 复位 / 找回
    def _reclaim(self, kinds) -> None:
        """把指定这几种面板从独立窗口**收回主窗口**。

        换摆法 / 独看 / 重新打开某一块之前必须先收回来：那块还在独立窗口里，主窗口就
        腾不出它的位置 —— 否则点了一张摆法缩略图会"没反应"（明明选了三块构图，实际
        只凑得出两块）。
        """
        want = set(kinds)
        for widget in list(self._detached):
            if self._drag_kind(widget) in want:
                self._close_detached(widget, silent=True)

    def reset_panel_layout(self) -> None:
        """**复位布局 / 找回所有面板**：一键把工作区恢复成"刚导入数据"的样子。

        这是"面板被拉到独立窗口后找不回来"时的兜底出口。它不看当前浮窗状态是否
        正确，而是**强制**做三件事：把所有面板收回主窗口（含状态错乱时的捞回）、
        恢复默认可见性（二维收起三维 / 三维三块全开）、回到**默认构图**
        （``_default3_key``，没配过就是内置的 B）。
        清空数据再导入不一定能救 —— 浮窗状态是独立于数据的一份状态，只有这里会重置它。
        """
        for widget in list(self._detached):
            self._close_detached(widget, silent=True)
        self._reclaim_stray_panels()
        self._clear_drag_layout(relayout=False)   # 万一是拖动中途调用：先撤掉瞬时状态
        two_d = bool(self.datasets) and all(d.vol.is_single_shot for d in self.datasets)
        self._content_shown = {"slice": True, "trace": True, "right": not two_d}
        self._layout_preset = self._default3_key or "B"
        self._pair_order = list(self._free_pair())   # 三块用该构图的默认；二维只有两块时按那一对
        self._three_auto_closed = False
        self._sync_layout_for_count()
        self._hide_picker()
        self.status.setText("已复位布局：面板全部收回主窗口，并恢复默认构图。")

    def _reclaim_stray_panels(self) -> None:
        """把"标记为浮窗里、但已经不在任何浮窗记录里"的面板强行搬回主窗口。

        浮窗状态与真实父节点可能错乱（窗口被系统关掉、记录被提前 pop 掉）。
        这时只看 ``_detached`` 是找不到它们的 —— 所以按面板上的 ``floating`` 属性扫一遍，
        作为最后一道安全网。
        """
        strays = [w for w in (self.slice_wrap, self.trace_frame, self.right_frame)
                  if w.property("floating")]
        for widget in strays:
            self._detached.pop(widget, None)
            self._restore_detached(widget)

    def _sync_panel_chips(self) -> None:
        """胶囊三个图标的状态、「⇄ 交换」与「分屏」键的明暗、剖面块数圆点，全部对齐。"""
        if getattr(self, "capsule", None) is None:
            return
        for kind, btn in self.capsule.buttons.items():
            key = CAPSULE_KEY[kind]
            on = self._content_shown[key]
            btn.setIcon(QtGui.QIcon(icons.kind(
                kind, 20, style.TEXT if on else style.TEXT_MUTE, style.ACCENT, on)))
            btn.setToolTip(self._capsule_tip(key, on))
        n = len(self.panels)
        group_floating = self._is_detached(self.slice_wrap)
        self.capsule.set_slice_dots(n, [group_floating] * n)
        f1, f2 = (self._pair_order + ["", ""])[:2]
        can_swap = bool(f2)
        dim = style.TEXT_DIM
        self.capsule.swap_btn.setIcon(QtGui.QIcon(
            icons.swap(18, dim if can_swap else style.TEXT_MUTE)))
        self.capsule.swap_btn.setEnabled(can_swap)
        self.capsule.swap_btn.setToolTip(
            f"交换前后/左右：「{PANEL_LABELS[f1]}」↔「{PANEL_LABELS[f2]}」" if can_swap
            else "交换先后（现在只有一块界面，没什么可换的）")
        multi = not self._is_single()
        self.capsule.split_btn.setIcon(QtGui.QIcon(
            icons.split_layout(18, style.ACCENT if multi else style.TEXT_MUTE, multi)))
        names = "、".join(PANEL_LABELS[k] for k in PANEL_ORDER if self._content_shown[k])
        key = self._layout_key()
        layout_line = (f"摆法 {key}：{PRESET_LABELS[key]}\n" if key in PRESET_LABELS
                       else "只有一块界面，没什么可排的\n")
        self.capsule.split_btn.setToolTip(
            f"现在显示：{names}\n" + layout_line +
            "点击 = 打开摆法面板（七个具体摆法任选；★ 设默认；底部有「复位布局」）\n"
            "快捷键 1/2/3 独看、Tab 循环")
        self._sync_split_entry()

    def _sync_split_entry(self) -> None:
        """按窗口设置里那一项决定胶囊上「分屏」按钮出不出现。

        关掉时连摆法面板一起收掉（否则会留着一个开着的浮层），并让胶囊重新贴右上角
        —— 按钮挤掉后整条胶囊定位要重算。
        """
        cap = getattr(self, "capsule", None)
        if cap is None:
            return
        vis = bool(self._show_split_panel)
        if getattr(self, "_split_entry_applied", None) == vis:
            return               # 状态没变就别白跑一遍（这个方法挂在每次重排的收尾上）
        self._split_entry_applied = vis
        cap.split_btn.setVisible(vis)
        if not vis:
            self._hide_picker()
        place = getattr(getattr(self, "workspace", None), "place_capsule", None)
        if place is not None:
            place()

    def _capsule_tip(self, key: str, on: bool) -> str:
        name = PANEL_LABELS[key]
        if on:
            rest = "三块至少要留一块" if self._is_single() else "点一下收起"
            return f"{name}　显示中 —— {rest}"
        return f"{name}　已收起 —— 点一下显示出来"

    # ------------------------------------------------------ 胶囊 / 快捷键入口
    def _toggle_content(self, key: str) -> None:
        """胶囊图标：**纯开关**（亮=在显示、暗=已收起），含义与当前状态无关。

        以前同一个点击按状态有三种含义（收起中的=加进来 / 显示中的=只看它 / 唯一的=
        退回上次组合），用户得先记住当前状态才知道点了会怎样 —— 现在只剩"开关"一种。
        "只看这一块"交给快捷键 1/2/3、Tab。
        """
        if key not in PANEL_ORDER:
            return
        name = PANEL_LABELS[key]
        if self._content_shown.get(key):
            if self._is_single():
                self.status.setText(
                    f"三块至少要留一块 —— 现在是「{name}」独看；"
                    "想换一块请按 1/2/3，或点右上角胶囊打开摆法面板。")
                return
            self._content_shown[key] = False
            self.status.setText(f"已收起「{name}」。")
        else:
            self._content_shown[key] = True
            # 点"已收起的块"= 要它显示出来：还在独立窗口里的先收回主窗口，
            # 不然这一下看起来毫无反应（块确实开着，只是还在桌面上飘着）。
            self._reclaim([key])
            self.status.setText(f"已显示「{name}」。")
        if key == "right":
            # 用户自己动了三维面板，就别再让"二维数据自动收起"覆盖他的选择
            self._three_auto_closed = False
            if self._content_shown.get("right"):
                self._ensure_view3d()
        self._sync_layout_for_count()

    def _focus_panel(self, key: str) -> None:
        """快捷键 1 / 2 / 3：只看某一块。"""
        self._solo(key)

    def _cycle_panel(self) -> None:
        """快捷键 Tab：在三块之间循环独看。"""
        cur = next((k for k in PANEL_ORDER if self._content_shown[k]), PANEL_ORDER[0])
        i = PANEL_ORDER.index(cur) if self._is_single() else -1
        self._solo(PANEL_ORDER[(i + 1) % len(PANEL_ORDER)])

    def _solo(self, key: str) -> None:
        """只看一块：另外两块收起。"""
        if key not in PANEL_ORDER:
            return
        # 其余两块要被收起 —— 还在独立窗口里的先收回主窗口，否则那些窗口会继续显示着
        # "已收起"的面板（开关状态与实际显示对不上）。
        self._reclaim(PANEL_ORDER)
        self._content_shown = {k: (k == key) for k in PANEL_ORDER}
        self._three_auto_closed = False
        if key == "right":
            self._ensure_view3d()
        self._relayout_content(animate=True)
        self.status.setText(
            f"已切到「{PANEL_LABELS[key]}」独看（按 1/2/3 或 Tab 换一块；"
            "点右上角胶囊可把别的块再显示出来）。")

    def open_layout_picker(self, *_args) -> None:
        """打开摆法面板：三块四张（主+侧+底 / 左叠右 / 单道在上 / 三维在左）+ 两块三张。

        齿轮里关掉"显示分屏快捷按钮"后这里整体拦掉 —— 三个入口（胶囊右键、分屏按钮
        点击/右键）都走这一个方法，一处拦住就全拦住了。
        """
        if not self._show_split_panel:
            return
        if getattr(self, "_picker", None) is None:
            self._picker = LayoutPicker(LAYOUT_KEYS, LAYOUT_TITLE, self)
            self._picker.presetChosen.connect(self._apply_layout)
            self._picker.resetRequested.connect(self.reset_panel_layout)
            self._picker.defaultRequested.connect(self._on_default_requested)
            self._picker.restoreDefaultsRequested.connect(self._on_restore_builtin_defaults)
            self._picker.closed.connect(self._on_picker_closed)
        self._refresh_picker()
        self._picker.adjustSize()
        anchor = self.capsule.mapToGlobal(QtCore.QPoint(0, self.capsule.height()))
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        x, y = anchor.x(), anchor.y()
        if screen is not None:
            avail = screen.availableGeometry()
            x = min(max(avail.left() + 4, x - self._picker.width()
                        + self.capsule.width() + Workspace.MARGIN),
                    avail.right() - self._picker.width() - 4)
            y = min(y, avail.bottom() - self._picker.height() - 4)
        self._picker.move(int(x), int(y))
        self._picker.show()
        self._picker.raise_()

    def _toggle_layout_picker(self) -> None:
        """点「分屏」键：开着就关、关了就开（开关语义，避免"点了没反应"）。

        面板是 Popup，点外部会自己关掉 —— 那一下点击随后还会落到按钮上，于是按钮
        会看到"已经关了"又把面板重新打开（用户感觉是"关不掉"）。所以记一下**上一次
        关闭的时刻**，紧跟着的这一下点击只当"关闭"，不开。
        """
        if getattr(self, "_picker", None) is not None and self._picker.isVisible():
            self._picker.hide()
            return
        if time.monotonic() - getattr(self, "_picker_closed_at", -9.0) < 0.3:
            return                          # 这一下就是把面板关掉的那一下，别再开
        self.open_layout_picker()

    def _on_picker_closed(self) -> None:
        self._picker_closed_at = time.monotonic()

    def _hide_picker(self) -> None:
        """收起摆法面板（选完自动关）。"""
        if getattr(self, "_picker", None) is not None and self._picker.isVisible():
            self._picker.hide()

    def _refresh_picker(self) -> None:
        """把当前状态刷到摆法面板上（当前摆法亮框 + 每张画"点它会得到的那套" + ★ 位置）。"""
        if getattr(self, "_picker", None) is None:
            return
        # 每张缩略图画的就是"点它会得到什么"：三块用该构图默认的先后、两块用该组合默认的先后。
        orders = {key: self._thumb_order(key) for key in LAYOUT_KEYS}
        # 当前这一张用真实先后（可能已经被「⇄」翻过）
        cur = self._layout_key()
        if cur in orders and len(self._pair_order) == 2:
            orders[cur] = list(self._pair_order)
        vis = self._shown_list()
        if len(vis) >= 3:
            tip = ("现在是三块界面：B 单道在底、BT 单道在上、A 三维在右、AL 三维在左；"
                   "「⇄」换的是没被钉住的那两块。")
        elif len(vis) == 2:
            tip = (f"现在是两块界面（{'、'.join(PANEL_LABELS[k] for k in vis)}）："
                   "方向由这两块固定决定，「⇄」只翻转先后。")
        else:
            tip = (f"现在只有「{PANEL_LABELS[vis[0]]}」一块；点上面任意一张就会"
                   "把需要的块补/收成那张图的样子。")
        # 星标的图例 + 当前默认是谁（内置还是自定义）
        default3 = self._default3_key or "B"
        how = "内置" if self._is_builtin_default() else "自定义"
        tip += (f"\n★ = 生效的默认布局（点 ★ 设置、不切当前画面）："
                f"三块 → {LAYOUT_TITLE.get(default3, default3)}（{how}）；"
                "两块 → 见各自那张的 ★。")
        self._picker.refresh(cur, orders, tip, stars=self._star_keys())

    def _on_default_requested(self, key: str) -> None:
        """点某张缩略图的 ★：把它（**含它当前显示的先后**）设为该组合的默认布局。

        刻意**不**立刻改当前画面 —— 默认只在"载入 / 复位 / 块数变化"时套用；想马上看效果
        就点那张缩略图本身。已经是默认时只给一句提示，避免"点了没反应"的错觉。
        """
        order = self._picker.order_of(key) if getattr(self, "_picker", None) else None
        order = tuple(order) if order else ()
        if GROUP_OF.get(key, 0) >= 3:
            if self._default3_key == key and tuple(self._default3_order) == order:
                self.status.setText(
                    f"「{LAYOUT_TITLE.get(key, key)}」已经是三块的默认布局了。")
                return
            self._default3_key = key
            self._default3_order = order
            what = f"三块默认 → {LAYOUT_TITLE.get(key, key)}"
        else:
            pair = KEY_PAIR.get(key)
            if pair is None:
                return
            if self._pair_defaults.get(key) == order:
                self.status.setText(
                    f"「{LAYOUT_TITLE.get(key, key)}」已经是"
                    f"{PANEL_LABELS[pair[0]]}+{PANEL_LABELS[pair[1]]}的默认先后了。")
                return
            self._pair_defaults[key] = order
            what = (f"{PANEL_LABELS[pair[0]]}+{PANEL_LABELS[pair[1]]} 默认 → "
                    + " → ".join(PANEL_LABELS[k] for k in order))
        self._save_ui_state()
        self._refresh_picker()
        self.status.setText(
            f"已设为默认布局：{what}。将在载入数据 / 复位布局 / 块的显隐变化时生效"
            "（当前画面不变，想马上看效果就点那张缩略图）。")

    def _on_restore_builtin_defaults(self) -> None:
        """「恢复内置默认布局」：清掉自定义的默认，回到内置的 B 与各组合规范先后。"""
        self._default3_key = ""
        self._default3_order = ()
        self._pair_defaults = {}
        self._save_ui_state()
        self._refresh_picker()
        self.status.setText(
            "已恢复内置默认布局：三块 → B（主+侧+底）；两块 → 剖面在左、三维在上、单道在下。")

    # ------------------------------------------------ 排版（预设）与动画
    # 三块容器的"静止最小尺寸"（只在动画结束后生效；动画期间必须放开，
    # 否则"收起到 0"会被最小尺寸顶回来）。上限值见 _panel_metrics 的自然尺寸。
    WS_CENTER_MIN = 320      # 剖面列的最小宽度
    CS_TRACE_MIN = 150       # 单道波形的最小高度

    def _relayout_content(self, animate: bool = True, duration: int = 190) -> None:
        """按当前摆法 + 三块面板的显隐重排右侧工作区。

        **总窗口大小也跟着走**：先按当前排版算一遍"自然尺寸"（见
        :meth:`_fit_window_to_layout`，可以变大也可以变小），再把三块排进这棵
        splitter 树里 —— 三块始终是同一棵树、只是尺寸插值（绝不 reparent，
        所以三维的 GL 上下文、剖面面板的视野都不会被重置）；只有换"摆法"A/B/C/D
        才重建 splitter 树（见 :meth:`_build_work_tree`）。

        每块的自然尺寸按数据规模估（见 :meth:`_panel_metrics`）：剖面按"切片面的横纵
        采样数之比"、单道是一根扁条、三维取剖面宽度的 42%。空间不够时按
        主视图 → 侧栏 / 底栏 → 其它 的优先级让位。
        """
        if self._tree is None or self._tree.get("preset") != self._layout_key():
            self._build_work_tree()
        shown = self._effective_shown()
        # 记下改尺寸**之前**的外框左上角：期间可能因最小尺寸约束触发隐式 resize，
        # 结束（含动画结束）后按它把位置拉回来，auto-fit 就永远不会搬窗口。
        anchor = self._frame_anchor() if self.isVisible() else None
        work_w, work_h = self._fit_window_to_layout(shown)

        # 开始前放开最小尺寸约束，免得"收起到 0"被顶回来（结束时再设回来）
        self._relax_content_min()
        plans = self._compute_targets(shown, work_w, work_h)
        for i, (splitter, total, items) in enumerate(plans):
            sizes = self._distribute(total, items)
            self._set_split_stretch(
                splitter,
                [max(1, int(round(it.get("stretch", 1.0) * 10))) if sizes[k] > 0 else 0
                 for k, it in enumerate(items)])
            last = i == len(plans) - 1
            on_done = None
            if last:
                on_done = (self._hold_content_min if anchor is None
                           else lambda a=anchor: self._hold_content_min(a))
            self._apply_sizes(splitter, sizes, animate, duration, on_done=on_done)
        self._sync_panel_chips()
        self._sync_header_pads()
        self._refresh_picker()             # 摆法面板开着时始终跟着刷（当前框、顺序、提示）
        self._update_references()

    # 剖面画布的"显示比例"下限（宽 / 高）：数据面本身可能很细长（例如 72 道 × 700 采样的
    # 共炮点面，天然比例只有约 0.1），宽度被 400 的下限抬起来后就成了"又高又窄"的竖长条，
    # 会把下方单道波形挤没。这里给高度再夹一个上限：高 ≤ 宽 / 下限（即宽:高 至少 4:5）。
    # 横长的数据面不受影响（那时宽 / 高远大于该下限）。
    SLICE_MIN_DISPLAY_ASPECT = 0.8

    def _panel_metrics(self) -> dict[str, dict]:
        """三块面板的"自然尺寸"与下限（像素），按当前数据的切片面估算。

        剖面的自然高度沿用 :meth:`_fit_window_to_layout` 里那套口径（每道约 1.15px，夹在
        [300, 880]），宽度按该面的横纵采样数之比还原 —— 于是 72 × 700 这种差得很远
        的两个方向也能得到比例正确的画布。单道波形是一根"扁条"，高度按采样点数走
        （夹在 [150, 260]）；三维取剖面宽度的 42%（夹在 [300, 560]）。
        """
        vol = self.vol
        aspect, rows, nt = 1.3, 400.0, 600.0
        if vol is not None:
            mode = self.mode or self._default_mode(vol)
            if mode == "shot":
                cols, rows = vol.nr, vol.nt
            elif mode == "recv":
                cols, rows = vol.ns, vol.nt
            else:
                cols, rows = vol.nr, vol.ns
            aspect = min(5.0, max(0.2, cols / max(1, rows)))
            nt = float(vol.nt)
        s_nat_h = min(880.0, max(300.0, rows * 1.15))
        s_nat_w = min(1200.0, max(400.0, s_nat_h * aspect))
        # 细长竖面：宽度被 400 下限抬起后，再把高度夹到"宽 / 显示比例下限"，
        # 免得剖面变成 400 × 805 这种竖长条（见 SLICE_MIN_DISPLAY_ASPECT 的说明）。
        s_nat_h = min(s_nat_h, s_nat_w / self.SLICE_MIN_DISPLAY_ASPECT)
        # 上面两项是**单幅剖面**的尺寸。对比模式下剖面组里并排 N 幅，整组的自然
        # 宽度必须是 N × 单幅，否则每幅只能拿到 1/N 宽度、画面被拉成竖条 ——
        # “优先保证剖面比例”的规则必须落在每一幅上，而不是整组上。
        n_slice = max(1, len(self.panels))
        gutter = (self.slice_split.handleWidth() * (n_slice - 1)
                  if getattr(self, "slice_split", None) is not None else 0)
        group_nat_w = s_nat_w * n_slice + gutter
        group_min_w = (320.0 if n_slice == 1
                       else max(320.0, 220.0 * n_slice))
        t_nat_h = min(260.0, max(150.0, nt * 0.30))
        r_nat_w = min(560.0, max(300.0, 0.42 * s_nat_w))
        return {
            "slice": {"min_w": group_min_w, "min_h": 180.0, "nat_w": group_nat_w,
                      "nat_h": s_nat_h, "prio": PANEL_PRIORITY["slice"]},
            "trace": {"min_w": 200.0, "min_h": 150.0, "nat_w": 520.0,
                      "nat_h": t_nat_h, "prio": PANEL_PRIORITY["trace"]},
            "right": {"min_w": 300.0, "min_h": 260.0, "nat_w": r_nat_w,
                      "nat_h": min(700.0, max(320.0, s_nat_h)),
                      "prio": PANEL_PRIORITY["right"]},
        }

    # 让位时"后面的项还剩多少可视为下限"：不是它们的最小尺寸，而是一个很小的可见值。
    # 这样高优先级那块能拿满自己的自然尺寸，低优先级那块也不会缩成 0 看不见。
    SQUEEZE_FLOOR_FRAC = 0.4
    SQUEEZE_FLOOR_PX = 64.0

    @staticmethod
    def _distribute(total: int, items: list[dict]) -> list[int]:
        """按**优先级**分配：先满足优先级高的（尽量给足它的自然尺寸），低的让位。

        每一项是 ``{"min","nat","priority","stretch"}``。需求里的优先级是
        **剖面 > 单道波形 > 三维**：空间不够时先保剖面的尺寸合理，其次单道，
        最后才动三维 —— 所以这里不是"大家按比例各让一点"，而是从高到低依次
        "给到自然尺寸"，剩下的才轮到下一块；``priority=0``（收起的那块）恒为 0。
        但让位有个底线：轮到高优先级那一块时，先给它后面的项扣出**各自的最小尺寸**，
        它自己最多缩到"可用空间 − 其它块的最小尺寸" —— 于是低优先级那块不会被压到
        下限以下（连最小尺寸都放不下时才退回"按优先级 × 最小尺寸"的等比例压缩）。
        分配完还有富余时按自然尺寸比例补回去，免得只剩一块时那块被整幅撑满。
        """
        n = len(items)
        if n == 0:
            return []
        if total <= 0:
            return [0] * n
        mins = [max(0.0, float(it.get("min", 0))) for it in items]
        nats = [max(mins[i], float(items[i].get("nat", 0))) for i in range(n)]
        prio = [max(0.0, float(it.get("priority", 1))) for it in items]
        sizes = [0.0] * n
        avail = float(total)
        floor_of = lambda m: max(64.0, 0.4 * float(m))          # noqa: E731
        order = [i for i in range(n) if prio[i] > 0 or mins[i] > 0]
        order.sort(key=lambda i: -prio[i])
        for pos, i in enumerate(order):
            # 给后面的项留出它们的**最小尺寸**（不再是"很小的可视为值"）：高优先级那块
            # 仍然先拿自然尺寸，但不能把低优先级那块压到它自己的下限以下 —— 实测：
            # 剖面拿满 805 后，底部的单道只剩 67px（连它 150 的最小高度都不到），看着
            # 就像"单道被删了"。改成预留后面各项的最小尺寸后，剖面最多让到
            # "可用空间 − 其它块的最小尺寸"；真的连最小值都塞不下时，下面的
            # "按优先级 × 最小尺寸压缩"分支会兜底。
            rest_floor = sum(mins[j] for j in order[pos + 1:])
            give = min(nats[i], max(floor_of(mins[i]), avail - rest_floor))
            sizes[i] = max(0.0, min(give, max(0.0, avail)))
            avail -= sizes[i]
        if order and avail > 0.5:
            # 有富余（窗口比"自然尺寸总和"还大）→ **只补给优先级最低的那一块**。
            # 这条是为"剖面比例优先"服务的：剖面的自然宽高比是按数据面算的，
            # 把富余塞给它就会被拉变形；塞给三维/单道只是让它们的画面更大，不走形。
            # （只有一块时它无处可让，才会自己吃掉富余。）
            #
            # ``order`` 可能为空：某个子分割器里的项**全被收起**（例如"单道独看"时
            # B 的上排 剖面+三维 两块都被隐藏）→ 没有谁该吃这份富余，直接不补。
            sizes[order[-1]] += avail
        out = [int(round(x)) for x in sizes]
        all_min = sum(mins)
        if all_min > total:
            # 连最小尺寸都放不下 → 按"优先级 × 最小尺寸"压缩：高优先级的仍然拿得多，
            # 而不是简单按最小尺寸平分（那样三维会和剖面拿到一样多）。
            weights = [mins[i] * max(1.0, prio[i]) for i in range(n)]
            wsum = sum(weights) or 1.0
            out = [int(round(total * weights[i] / wsum)) for i in range(n)]
        diff = total - sum(out)
        if diff:
            j = max(range(n), key=lambda i: out[i])
            out[j] = max(0, out[j] + diff)
        return out

    def _compute_targets(self, shown: dict, work_w: int, work_h: int):
        """算出每个分割器的目标尺寸；返回 ``[(splitter, total, items), ...]``（先内后外）。

        被钉住的那块（B 的单道在底栏、A 的三维在右列）位置由树结构定，这里只负责
        给出"可换序那两块"的尺寸；顺序与树里的子控件顺序一致。
        """
        tree = self._tree
        m = self._panel_metrics()
        W = max(200, int(work_w))
        H = max(150, int(work_h))
        free = tree.get("free")

        def pi(key: str, axis: str, prio_scale: float = 1.0) -> dict:
            """一块面板在某根轴上的分配项（没显示就整项归零，不占空间）。

            ``priority`` 决定"空间不够时谁先让"：剖面 3 > 单道 2 > 三维 1。
            ``stretch`` 决定窗口变大时多出来的尺寸怎么分（沿用同一套优先级）。
            """
            if not shown.get(key):
                return {"min": 0, "nat": 0, "priority": 0, "stretch": 0}
            d = m[key]
            p = PANEL_PRIORITY[key] * prio_scale
            return {"min": d["min_" + axis], "nat": d["nat_" + axis],
                    "priority": p, "stretch": p}

        plans = []
        if free is not None:
            f1, f2 = free
            on = bool(shown.get(f1)) or bool(shown.get(f2))
            if tree["preset"] in ("B", "BT"):         # 上排两块左右 + 单道一栏（BT 则是单道在上）
                a, b = pi(f1, "h"), pi(f2, "h")
                top = {"min": max(a["min"], b["min"]), "nat": max(a["nat"], b["nat"]),
                       "priority": max(a["priority"], b["priority"]), "stretch": 1.0}
                plans.append((tree["inner"], W, [pi(f1, "w"), pi(f2, "w")]))
                if tree["preset"] == "B":
                    plans.append((tree["root"], H, [top, pi("trace", "h")]))
                else:
                    plans.append((tree["root"], H, [pi("trace", "h"), top]))
            else:                                     # 左列两块上下 + 三维一列（AL 则是三维在左）
                a, b = pi(f1, "h"), pi(f2, "h")
                # 左列的自然宽度取**优先级更高那块**的（不是两者的最大值）：否则
                # 单道那 520 的"自然宽"会把窗口撑宽，反过来让剖面比其它摆法下更宽。
                col_nat = (m[(f1 if PANEL_PRIORITY[f1] >= PANEL_PRIORITY[f2] else f2)]
                           ["nat_w"] if on else 0.0)
                col = {"min": float(self.WS_CENTER_MIN) if on else 0.0,
                       "nat": col_nat,
                       "priority": max(a["priority"], b["priority"]) if on else 0.0,
                       "stretch": 1.0}
                plans.append((tree["inner"], H, [pi(f1, "h"), pi(f2, "h")]))
                if tree["preset"] == "A":
                    plans.append((tree["root"], W, [col, pi("right", "w")]))
                else:
                    plans.append((tree["root"], W, [pi("right", "w"), col]))
            return plans
        # 两块（或一块）：方向由这一对定，第三块留 0 占位
        axis = "w" if self.work_tree.orientation() == QtCore.Qt.Orientation.Horizontal \
            else "h"
        total = W if axis == "w" else H
        plans.append((tree["root"], total,
                      [pi(k, axis) for k in tree["slots"]]))
        return plans

    _LEAF_OF = {"slice": "slice_holder", "trace": "trace_holder", "right": "right_holder"}

    def _prio_of(self, widget, shown: dict, m: dict) -> float:
        """某个容器（或其子树）里最高的让位优先级 —— 0 表示整棵子树都收起了。"""
        if isinstance(widget, QtWidgets.QSplitter):
            vals = [self._prio_of(widget.widget(i), shown, m)
                    for i in range(widget.count())]
            return max(vals) if vals else 0.0
        key = next((k for k, name in self._LEAF_OF.items()
                    if getattr(self, name, None) is widget), None)
        if key is None or not shown.get(key):
            return 0.0
        return float(m[key].get("prio", 1.0))

    @staticmethod
    def _squeeze_floor(min_size) -> float:
        return max(64.0, 0.4 * float(min_size))

    def _extent_along(self, widget, horiz: bool, shown: dict, m: dict,
                      key_name: str) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的"自然"/"最小"尺寸。

        沿**分割器自己的方向**相加（横排一行宽 = 各列之和）；**垂直方向不取最大值，
        而是取"优先级最高的那一块"的尺寸** —— 这是"剖面优先"的关键一环：
        低优先级面板（单道/三维）不该把窗口撑大，它宁可自己被压窄，也不能让剖面
        的尺寸随别块开不开而变化。
        """
        if isinstance(widget, QtWidgets.QSplitter):
            same = ((widget.orientation() == QtCore.Qt.Orientation.Horizontal)
                    == bool(horiz))
            kids = [widget.widget(i) for i in range(widget.count())]
            vals = [self._extent_along(k, horiz, shown, m, key_name) for k in kids]
            if not vals:
                return 0.0
            if same:
                return sum(vals) + widget.handleWidth() * (len(vals) - 1)
            best = max(((self._prio_of(k, shown, m), v) for k, v in zip(kids, vals)),
                       key=lambda pv: (pv[0], pv[1]), default=(0.0, 0.0))
            return best[1]
        key = next((k for k, name in self._LEAF_OF.items()
                    if getattr(self, name, None) is widget), None)
        if key is None or not shown.get(key):
            return 0.0
        axis = "w" if horiz else "h"
        return m[key][f"{key_name}_{axis}"]

    def _min_along(self, widget, horiz: bool, shown: dict, m: dict) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的最小尺寸。"""
        return self._extent_along(widget, horiz, shown, m, "min")

    def _natural_along(self, widget, horiz: bool, shown: dict, m: dict) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的**自然**尺寸（按数据规模估）。"""
        return self._extent_along(widget, horiz, shown, m, "nat")

    def _relax_content_min(self) -> None:
        """动画前放开所有最小尺寸：动画要能把任意一块压到 0。"""
        for sp in self._tree_splitters:
            sp.setMinimumWidth(0)
            sp.setMinimumHeight(0)
        for name in self._LEAF_OF.values():
            w = getattr(self, name, None)
            if w is not None:
                w.setMinimumWidth(0)
                w.setMinimumHeight(0)

    def _hold_content_min(self, anchor: QtCore.QPoint | None = None) -> None:
        """动画结束后设"静止最小尺寸"，让用户拖分割器把手时不会把某块压没。

        空间本来就塞不下时**不设**约束 —— 否则最小尺寸之和超过容器，会被裁掉一块；
        那时退回"按比例挤压"的旧行为，至少不出错。

        ``anchor`` 非空时顺带把外框左上角拉回去：设最小尺寸可能触发一次隐式 resize，
        位置会跟着挪一个边框宽度。
        """
        if self._tree is None:
            self._restore_anchor(anchor)
            return
        shown = self._effective_shown()
        # 这里给的是**可视为下限**（不是各块的最小尺寸）：分配器是按优先级把自然尺寸
        # 给足高优先级那块、低优先级那块吃剩下的；如果这里再把"最小尺寸"设成硬下限，
        # splitter 会把低优先级那块顶回去，高优先级那块就又被挤小了 —— 剖面的大小
        # 就又会随别的面板开不开而变。所以下限统一取"很小的可视为值"。
        raw = self._panel_metrics()
        m = {k: {**v,
                 "min_w": max(64.0, 0.4 * v["min_w"]),
                 "min_h": max(64.0, 0.4 * v["min_h"])}
             for k, v in raw.items()}

        def walk(sp: QtWidgets.QSplitter) -> None:
            horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
            kids = [sp.widget(i) for i in range(sp.count())]
            mins = [self._min_along(k, horiz, shown, m) for k in kids]
            need = sum(mins) + sp.handleWidth() * max(0, len(kids) - 1)
            total = sp.width() if horiz else sp.height()
            fits = total >= need
            for child, base in zip(kids, mins):
                if isinstance(child, QtWidgets.QSplitter):
                    walk(child)
                if horiz:
                    child.setMinimumHeight(0)
                    child.setMinimumWidth(int(base) if fits else 0)
                else:
                    child.setMinimumWidth(0)
                    child.setMinimumHeight(int(base) if fits else 0)
        walk(self.work_tree)
        self._restore_anchor(anchor)

    def _fit_window_to_layout(self, shown: dict) -> tuple[int, int]:
        """**总窗口尺寸跟着当前排版走**；返回分配用的工作区尺寸 ``(W, H)``。

        为什么需要这一步：窗口如果只在"导入数据那一刻"定一次尺寸，之后无论切到
        单块、还是换成别的摆法，窗口都不动 —— 于是三块只能被硬撑进原来的框里，
        宽高比常常离数据的自然比例很远，看着就是"不合理地拉伸"。

        这里改成：每当**面板组合变化**（独看 / 开关一块 / 换摆法 / 换主视图 / 换数据）
        都按当前这棵树，把每块的**自然尺寸**沿轴相加（同 :meth:`_natural_along` 的口径），
        得到一个"刚好合适"的窗口尺寸，再夹进 ``[MIN_SIZE, 屏幕可用区]``。
        与旧版最大的区别是**它也会变小** —— 关掉一块时窗口就收回去，而不是留下空白
        把剩下的块拉变形。

        两条保险：窗口设置里可以关掉这个行为（关掉后退回"只放大"）；用户手动 resize
        过的尺寸成为**锚点**（``_user_size``），换构图只在空间不足时扩容、不主动缩小 ——
        于是"调好的大小"不会因为切一趟别的视图就丢掉。
        """
        if self._tree is None or self.work_tree is None or not self.datasets:
            # 还没有数据时不自作聪明改窗口尺寸：这时三块的"自然尺寸"全是默认值，
            # 算出来只会把开场窗口改小，没有意义。
            return (int(self.work_host.width()), int(self.work_host.height()))
        m = self._panel_metrics()
        # 窗口只按**剖面与单道**的自然尺寸长：三维不拿自然尺寸、只占它的最小值 ——
        # 这正是"剖面 > 单道 > 三维"的优先级：三维不该把窗口撑大。
        mw = {k: dict(v) for k, v in m.items()}
        mw["right"]["nat_w"] = mw["right"]["min_w"]
        mw["right"]["nat_h"] = mw["right"]["min_h"]
        want_w = max(self._natural_along(self.work_tree, True, shown, mw),
                     self._min_along(self.work_tree, True, shown, m))
        want_h = max(self._natural_along(self.work_tree, False, shown, mw),
                     self._min_along(self.work_tree, False, shown, m))
        left_w = (self.left_wrap.width() if self._region_shown.get("left", True)
                  else self.LEFT_RAIL_W)
        # 边框开销用**实测值**：窗口尺寸减掉"左栏 + 工作区"剩下的那部分（外边距与手柄）。
        # 写死的估值差几十像素，会让面板被多出来的那截拉伸 —— 正是"适配数据形状没保持住"
        # 的来源。注意这里**不能再把左栏算进去**（上面已经单独加了 left_w）。
        cw, ch = self.CHROME_W, self.CHROME_H
        if self.work_host.width() > 1 and self.width() > self.work_host.width():
            cw = max(0.0, float(self.width() - self.work_host.width() - left_w))
        if self.work_host.height() > 1 and self.height() > self.work_host.height():
            ch = float(self.height() - self.work_host.height())
        # 当前构图**真正放不下**时的最小窗口（只用于用户尺寸锚的扩容判断）
        min_w = left_w + self._min_along(self.work_tree, True, shown, m) + cw
        min_h = self._min_along(self.work_tree, False, shown, m) + ch

        if self._user_size is not None:
            # 用户手动调过尺寸：它成为锚点，换构图**不主动缩小**；只有这个构图
            # 连最小尺寸都放不下时才扩容。
            win_w = max(float(self._user_size[0]), min_w)
            win_h = max(float(self._user_size[1]), min_h)
            if not self._follow_layout:
                win_w = max(win_w, float(self.width()))
                win_h = max(win_h, float(self.height()))
        else:
            win_w = left_w + want_w + cw
            win_h = want_h + ch
            if not self._follow_layout:
                # 关掉"跟随排版"就退回旧行为：只要不小于现在，绝不缩回去
                win_w = max(win_w, float(self.width()))
                win_h = max(win_h, float(self.height()))

        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            win_w = min(win_w, avail.width() * 0.96)
            win_h = min(win_h, avail.height() * 0.94)
        win_w = max(win_w, float(self.MIN_SIZE[0]))
        win_h = max(win_h, float(self.MIN_SIZE[1]))

        # 全屏 / 最大化下**只重排 splitter，绝不 setGeometry**：否则会退出全屏
        if self.isFullScreen() or self.isMaximized():
            self._window_target = None
            return (max(60, int(self.work_host.width())),
                    max(60, int(self.work_host.height())))

        self._window_target = (int(win_w), int(win_h))

        # **拖动中不改窗口尺寸**：挤占会改变"实际可见集合"，而窗口尺寸又是跟着它算的
        # —— 一改尺寸，工作区几何（以及判定区域）就跟着动，光标相对位置随之变化、意图
        # 来回翻，看上去就是面板在莫名其妙地抖。拖动期间把窗口钉住，只让 splitter 在
        # 窗口内部重新分配；松手后（`_drag` 已清空）再一次性丝滑变成最终尺寸。
        if self._is_dragging_active():
            return (max(60, int(self.work_host.width())),
                    max(60, int(self.work_host.height())))
        if not self._suppress_window_resize and self.isVisible() \
                and self.work_tree.width() > 1 \
                and self._size_changed_enough(win_w, win_h):
            # 只改尺寸、不搬窗口（见 _resize_keeping_anchor）：位置永远由用户说了算
            self._resize_keeping_anchor(int(win_w), int(win_h))
            self._ensure_on_screen()           # 调完别越过屏幕边缘
        # 分配用的工作区尺寸：按"要改成多大"解析地算，而不是读刚 resize 还没走布局的
        # 控件尺寸 —— 否则这一帧会按老尺寸排，看着就是"先跳一下、再重排一次"。
        return (max(60, int(win_w - left_w - cw)), max(60, int(win_h - ch)))

    def _is_dragging_active(self) -> bool:
        """是否正处在一次真正的拖动中 —— 用来冻结窗口尺寸（见 :meth:`_fit_window_to_layout`）。

        拿起那一刻 ``freeze`` 还是 ``False``：让"归位"能**改这一次**窗口尺寸；随后置 ``True``，
        到松手前窗口尺寸恒定，挤占只在窗口内部发生（否则"挤占改变可见集合 → 窗口尺寸跟着算 →
        几何/判定区域跟着动 → 意图翻转"，看上去就是面板在抖）。
        """
        d = getattr(self, "_drag", None)
        return bool(d and d.get("active") and d.get("freeze"))

    # 换摆法时的过渡时长：窗口尺寸从旧值滑到新值（面板按伸缩因子等比例铺开）
    LAYOUT_ANIM_MS = 190

    def _animate_layout_change(self) -> None:
        """换摆法 / 换先后时的"丝滑"过渡：让**总窗口**从旧尺寸滑到新尺寸。

        摆法一换，splitter 的树结构就变了 —— "哪块在左、哪块在底"是结构决定的，
        这一段没法靠补间变形过去（除非把面板搬来搬去，那会丢掉三维的 GL 上下文）。
        但窗口尺寸可以：面板在窗口里是按伸缩因子等比例铺开的，窗口从旧尺寸滑到新
        尺寸时整幅画面一起"呼吸"，就不会出现"内容先跳一下、窗口再跟上"的错位感。
        """
        if self.isFullScreen() or self.isMaximized():
            return                      # 全屏下只重排 splitter，绝不改窗口 geometry
        target = getattr(self, "_window_target", None)
        if target is None or not self.isVisible():
            return
        if self._is_dragging_active():
            return                      # 拖动中钉住窗口尺寸（见 _fit_window_to_layout）
        tw, th = target
        if abs(tw - self.width()) < 8 and abs(th - self.height()) < 8:
            return
        self._stop_layout_anim()
        # 终值也用**外框锚点**算：不能用 self.x()/self.y()（客户区坐标）——
        # 尺寸一变 Qt 就重算外框偏移，拿客户区坐标当落点会让外框每轮挪一个边框宽度。
        anchor, off = self._frame_anchor(), self._client_offset()
        anim = QtCore.QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(self.LAYOUT_ANIM_MS)
        anim.setStartValue(self.geometry())
        anim.setEndValue(QtCore.QRect(anchor.x() + off.x(), anchor.y() + off.y(),
                                      tw, th))
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.finished.connect(self._ensure_on_screen)
        self._layout_anim = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_layout_anim(self) -> None:
        anim = getattr(self, "_layout_anim", None)
        self._layout_anim = None
        if anim is None:
            return
        try:
            if anim.state() == QtCore.QAbstractAnimation.State.Running:
                anim.stop()
        except RuntimeError:                   # DeleteWhenStopped 已经把对象删了
            pass

    def _window_anim_running(self) -> bool:
        """总窗口的尺寸动画是否还在跑（动画帧不该写入用户尺寸锚）。"""
        anim = getattr(self, "_layout_anim", None)
        if anim is None:
            return False
        try:
            return anim.state() == QtCore.QAbstractAnimation.State.Running
        except RuntimeError:                   # pragma: no cover
            return False

    # 窗口尺寸的"边框开销"：左右外边距 + body 手柄 + 顶栏 + 状态栏（估算兜底用；
    # 实测拿得到时优先用实测值，见 _fit_window_to_layout）。
    CHROME_W = 34
    CHROME_H = 105

    def _size_changed_enough(self, win_w: float, win_h: float) -> bool:
        """尺寸变化超过 3% 或 20px 才真的去改窗口 —— 否则每帧微调会让窗口抖。"""
        return (abs(win_w - self.width()) > max(20.0, self.width() * 0.03)
                or abs(win_h - self.height()) > max(20.0, self.height() * 0.03))

    def _layout_animating(self) -> bool:
        """两处 splitter 上是否还有尺寸动画在跑（避免窗口 resize 与动画互相打架）。"""
        for anim in list(self._size_anims.values()):
            try:
                if anim.state() == QtCore.QAbstractAnimation.State.Running:
                    return True
            except RuntimeError:                 # DeleteWhenStopped 已经把对象删了
                pass
        return False

    def changeEvent(self, ev) -> None:           # noqa: N802 （Qt 接口名）
        """最大化 / 全屏切换时显式恢复“进全屏前”的几何。

        Windows 上无边框/自定义布局窗口有时只改了 ``windowState``，几何仍停在
        最大化尺寸，看起来就是“点了还原按钮却没缩小”。这里在状态回到 NoState
        时主动把 normalGeometry 再落一次，保证缩回进全屏前的大小。
        """
        super().changeEvent(ev)
        if ev.type() != QtCore.QEvent.Type.WindowStateChange:
            return
        state = self.windowState()
        if state & (QtCore.Qt.WindowState.WindowMaximized
                    | QtCore.Qt.WindowState.WindowFullScreen):
            geo = self.normalGeometry()
            if geo.isValid() and not geo.isNull():
                self._pre_big_geometry = QtCore.QRect(geo)
            return
        if state & QtCore.Qt.WindowState.WindowMinimized:
            return
        geo, self._pre_big_geometry = self._pre_big_geometry, None
        if geo is None or not geo.isValid() or not self.isVisible():
            return
        self._auto_resize_depth += 1
        try:
            self.setGeometry(geo)
        finally:
            self._auto_resize_depth -= 1
        # 恢复后的尺寸就是用户尺寸锚，后续排版不会把它撑回去
        self._user_size = (geo.width(), geo.height())

    def resizeEvent(self, ev) -> None:           # noqa: N802 （Qt 接口名）
        """窗口尺寸一变，就按新的可用空间重新判定各块的最小尺寸约束。

        空间不够时 ``_hold_content_min`` 会自动放开约束，避免子控件被裁切 ——
        这样"窗口被用户拖小"不会把某一块压出画面。动画进行中不插手。

        同时记录**用户尺寸锚**：只有用户自己拖动窗口（非程序化、非最大化/全屏、
        非换构图动画）才更新 ``_user_size``；换构图只在这个锚点放不下时才扩容。
        """
        super().resizeEvent(ev)
        if (self._auto_resize_depth == 0
                and getattr(self, "_place_done", False)
                and not self._window_anim_running()
                and self.windowState() == QtCore.Qt.WindowState.WindowNoState
                and self.isVisible()):
            self._user_size = (self.width(), self.height())
        # right_holder 是这几块里最晚建出来的，它有 = 工作区各控件都齐了
        if getattr(self, "right_holder", None) is None or self._layout_animating():
            return
        self._hold_content_min()

    def keyPressEvent(self, ev) -> None:         # noqa: N802 （Qt 接口名）
        """键盘入口：1 / 2 / 3 独看三块，Tab 在三块之间循环。

        用 keyPressEvent 而不是 QShortcut：焦点在数字框 / 输入框里时，那些键会被
        控件自己吃掉（根本传不到这里），于是"往抽稀框里敲 4096"不会被当成快捷键 ——
        这正是我们要的。焦点在普通按钮上时才会落到这里。
        """
        mod = ev.modifiers()
        if (ev.key() == QtCore.Qt.Key.Key_Escape
                and mod == QtCore.Qt.KeyboardModifier.NoModifier):
            # Esc 优先级：先收浮窗，再退全屏 / 最大化（避免全屏时误退）
            if self._detached:
                widget = list(self._detached)[-1]
                self._close_detached(widget)
                return
            if self.isFullScreen() or self.isMaximized():
                normal = self.normalGeometry()
                self._auto_resize_depth += 1
                try:
                    self.showNormal()
                    if normal.isValid():
                        self.setGeometry(normal)
                finally:
                    self._auto_resize_depth -= 1
                if normal.isValid():
                    self._user_size = (normal.width(), normal.height())
                return

        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(focus, (QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit,
                              QtWidgets.QComboBox)):
            super().keyPressEvent(ev)
            return
        mod = ev.modifiers()
        if mod == QtCore.Qt.KeyboardModifier.NoModifier:
            key = ev.key()
            if key in (QtCore.Qt.Key.Key_1, QtCore.Qt.Key.Key_2, QtCore.Qt.Key.Key_3):
                # ① 单道 ② 剖面 ③ 三维（按维度 1 → 2 → 3，与胶囊一致）
                self._focus_panel(("trace", "slice", "right")[key - QtCore.Qt.Key.Key_1])
                return
            if key == QtCore.Qt.Key.Key_Tab:
                self._cycle_panel()
                return
        super().keyPressEvent(ev)

    @staticmethod
    def _set_split_stretch(splitter: QtWidgets.QSplitter, weights: list[int]) -> None:
        for i, w in enumerate(weights[:splitter.count()]):
            splitter.setStretchFactor(i, int(w))

    @staticmethod
    def _total(splitter: QtWidgets.QSplitter) -> int:
        return max(1, sum(splitter.sizes()))

    def _apply_sizes(self, splitter: QtWidgets.QSplitter, target: list[int],
                     animate: bool, duration: int = 190, on_done=None) -> None:
        """把 splitter 的尺寸切到目标值；``animate`` 时用缓动插值滑过去。

        动画期间每一帧都调 ``setSizes``，所以剖面会跟着重绘 —— 抽稀之后的图足够快，
        不存在卡顿。动画结束把最终尺寸**钉死**一次（同时跑 ``on_done``，用来恢复
        展开后的 min/max 约束），避免最后一帧的取整误差留下一个悬空的把手。
        """
        n = splitter.count()
        if n == 0:
            if on_done is not None:
                on_done()
            return
        target = (list(target) + [0] * n)[:n]
        self._stop_size_anim(splitter)
        if not animate:
            splitter.setSizes(target)
            if on_done is not None:
                on_done()
            return
        start = (list(splitter.sizes()) + [0] * n)[:n]
        if start == target:
            splitter.setSizes(target)
            if on_done is not None:
                on_done()
            return

        def _finish(sp=splitter, t=target, cb=on_done):
            if not _qt_valid(sp):              # 旧 splitter 已被换摆法销毁
                return
            sp.setSizes(list(t))
            if cb is not None:
                cb()

        def _frame(v, sp=splitter, s=start, t=target):
            if not _qt_valid(sp):
                return
            sp.setSizes([int(round(a + (b - a) * float(v)))
                         for a, b in zip(s, t)])

        anim = QtCore.QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(_frame)
        anim.finished.connect(_finish)
        self._size_anims[id(splitter)] = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_all_size_anims(self) -> None:
        """换树 / 清空数据前停掉所有 splitter 尺寸动画（它们的目标可能马上被销毁）。"""
        for anim in list(self._size_anims.values()):
            try:
                anim.stop()
            except RuntimeError:               # pragma: no cover
                pass
        self._size_anims.clear()

    def _stop_size_anim(self, splitter: QtWidgets.QSplitter) -> None:
        """掐掉同一根 splitter 上还没跑完的上一轮动画，免得两批动画互相抢。"""
        anim = self._size_anims.pop(id(splitter), None)
        if anim is None:
            return
        try:
            anim.stop()
        except RuntimeError:                       # pragma: no cover
            pass                                   # DeleteWhenStopped 已经把对象删了


    def _rebuild_slice_panels(self) -> None:
        """按当前数据份数调整中间的剖面面板：够用的**复用**，多出来的才新建。

        复用而不是每次重建：重建会让每块剖面视图（连同它的视野、提示线）重新
        初始化一遍，载入数据时看上去就是"剖面里的绘图抖了一下"。
        面板通过 ``slot`` 记住自己对应第几份数据 —— 移除中间某份数据时下标会整体
        前移，回调必须按当期下标取，而不是创建时捕获的那个。

        每块面板外面再套一个**容器**：面板被拉到独立窗口时，容器留在 splitter 里
        占住位置（压成 0 宽），这样剩下几块的下标与顺序都不会乱。
        """
        while len(self.panels) > len(self.datasets):
            panel = self.panels.pop()
            holder = self.panel_holders.pop()
            self._close_detached(panel, silent=True)     # 先收回，免得连窗口一起删掉
            panel.setParent(None)
            holder.setParent(None)
            panel.deleteLater()
            holder.deleteLater()
        while len(self.panels) < len(self.datasets):
            holder = QtWidgets.QWidget()
            hl = QtWidgets.QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            panel = SlicePanel()
            panel.slot = 0
            panel.picked.connect(lambda c, r, p=panel: self._on_pick(p.slot, c, r))
            panel.hovered.connect(lambda c, r, p=panel: self._on_hover(p.slot, c, r))
            # 双击复位：第一次 release 可能已经误取道，这里把那次变化撤回去
            panel.view.doubleClicked.connect(
                lambda p=panel: self._on_view_double_click(p.slot))
            # 拖动统一挂到主窗口这一处实现（拉出为独立窗口 / 拖到另一块上换序）
            self._watch_drag(panel.header, panel)
            # 这里**故意不给**剖面面板挂 tooltip：鼠标一停在地震画面上就会冒出一块
            # 半透明提示挡住波形，是纯粹的干扰。操作提示改挂在剖面区域的标题行上
            # （"剖面"那行），要看的时候才看。
            hl.addWidget(panel)
            self.slice_split.addWidget(holder)
            self.panels.append(panel)
            self.panel_holders.append(holder)
        for k, panel in enumerate(self.panels):
            panel.slot = k
            self.slice_split.setStretchFactor(k, 1)
        if self.panels:
            # 显式给一次等分尺寸：不依赖之后某个时机才发生的布局遍历，
            # 免得"先空一帧再出现"看着像闪一下
            self.slice_split.setSizes([1] * len(self.panels))
        self._sync_empty_hint()

    def _sync_empty_hint(self) -> None:
        """没有数据时把剖面区换成引导文字（有数据时换回真正的剖面）。"""
        empty = not self.panels
        self.slice_empty.setVisible(empty)
        self.slice_split.setVisible(not empty)

    # ============================================================== 拖动统一手势
    # 一个手势、三种结果，全部由"松手的位置"决定，不再需要任何小按钮：
    #   · 落在另一块剖面面板内 → **交换剖面顺序**（顺序决定叠加波形/单道波形的配色）
    #   · 落在主窗口之外       → **拉出为极简独立窗口**，落点就是新窗口的位置
    #   · 其它                 → 取消，面板回到原位
    # 已经在独立窗口里的面板再拖，就是搬动那个窗口；拖回主窗口松手即收回。
    # 唯一提示是标题行最左边的 6 点抓手。
    _DRAG_SLOP = 6                       # 小于这个位移算点击，不启动拖动
    def _is_detached(self, widget) -> bool:
        return widget in self._detached

    def _watch_drag(self, header: QtWidgets.QWidget, target: QtWidgets.QWidget) -> None:
        """给某块面板的标题行挂上拖动监听（``target`` 是被拖走的那个控件）。"""
        header.installEventFilter(self)
        header.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self._drag_watch[header] = target

    def eventFilter(self, obj, ev) -> bool:            # noqa: N802 （Qt 接口名）
        target = self._drag_watch.get(obj)
        if target is None:
            return super().eventFilter(obj, ev)
        kind = ev.type()
        if kind == QtCore.QEvent.Type.MouseButtonPress \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._begin_drag(obj, target, ev.globalPosition().toPoint(),
                                ev.modifiers()):
                return True                      # 已交给系统原生拖动，别再往下传
        elif kind == QtCore.QEvent.Type.MouseButtonDblClick \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._toggle_float_maximized(target):
                return True
        elif kind == QtCore.QEvent.Type.MouseMove and self._drag is not None:
            self._move_drag(ev.globalPosition().toPoint())
            return True
        elif kind == QtCore.QEvent.Type.MouseButtonRelease and self._drag is not None \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self._finish_drag(ev.globalPosition().toPoint())
            return True
        return super().eventFilter(obj, ev)

    def _toggle_float_maximized(self, target) -> bool:
        """双击浮窗标题栏 = 全屏 / 还原（与右上角那颗「全屏」按钮同一个动作）。

        Qt 的 FramelessWindowHint 把系统标题栏去掉了，这个习惯动作得自己补；而我们自己
        拖动的路径下标题栏是 HTCLIENT，系统也不会替我们处理双击。
        **用自己实现的全屏，不用系统的最大化**：系统最大化会给"可缩放的无边框窗口"
        补一圈系统边框条（顶部那条偏宽的白条就是它），全屏则一点边都不带。
        返回 ``True`` 表示这次双击被处理掉了。
        """
        win = self._detached.get(target)
        if win is None:
            return False
        # 双击的第一次按下已经起了一次拖动（`_drag`），这里必须把它作废：否则紧跟着的
        # 松手会走 `_finish_drag`，而全屏后的浮窗覆盖在主窗口上 → 被误判成"拖回主窗口"
        # 直接收回去。
        self._drag = None
        win.toggle_fullscreen()
        self.status.setText("浮窗已退出全屏。" if not win.isFullScreen()
                           else "浮窗已全屏（再双击标题栏或点右上角按钮退出）。")
        return True

    def _drag_kind(self, target) -> str:
        if target is self.slice_wrap:
            return "slice"
        if isinstance(target, SlicePanel):
            return "slice"
        if target is self.trace_frame:
            return "trace"
        if target is self.right_frame:
            return "right"
        return "slice"

    # 浮窗最小尺寸：只是"退化尺寸"的兜底（正常情况一律等大搬出去，不做任何缩放）
    MIN_FLOAT = (160, 120)

    # ---------------------------------------------------------------- 开始 / 移动
    def _begin_drag(self, header, target, pos: QtCore.QPoint, modifiers=0) -> bool:
        """开始一次拖动；返回 ``True`` 表示这次按下已经交给系统（不再走我们的拖动）。

        **Alt + 拖浮窗标题栏 = 交给 Windows 做原生拖动**：只有这样才拿得到 Aero Snap
        （拖到屏幕边分屏）、拖到顶部最大化，以及随后可用的 Win+方向键 / Snap Layouts。
        代价是原生拖动期间 Windows 跑自己的模态移动循环，Qt 收不到鼠标移动事件，所以
        这条路径下**没有实时落位预览**；默认（不按 Alt）仍然是我们自己的拖动，预览照旧。
        """
        win = self._detached.get(target)
        if win is not None and modifiers & QtCore.Qt.KeyboardModifier.AltModifier:
            handle = win.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        self.status.setText(
                            "原生拖动中：可拖到屏幕边分屏、拖到顶部最大化。")
                        return True
                except Exception:
                    pass                       # 平台不支持就退回我们自己的拖动
        # 记下**按下那一刻**的尺寸：面板一"离手"就隐藏，它的槽位会被邻居吃掉，
        # 松手时再读宽度已经不是用户看到的那块大小了。
        wrap = getattr(self, "workspace", None)
        if wrap is not None:
            wrap.show_drop_preview(None)   # 上一次拖动万一没收干净（松手事件丢了），兜一下
        self._preview_state = None         # 上一次拖动的预览状态不许影响这一次
        self._preview_cap = None
        self._zone_frozen = None
        kind = self._drag_kind(target)
        # 剖面有两种手势：
        #   · 组标题（slice_wrap）→ 整块移动 / 拉出 / 换分屏；
        #   · 单图标题（SlicePanel）→ 只在对比模式交换数据顺序，绝不拉出。
        group = target is self.slice_wrap
        reorder_only = isinstance(target, SlicePanel)
        slice_sizes = (list(self.slice_split.sizes())
                       if reorder_only and len(self.panels) > 1 else None)
        self._drag = {"header": header, "target": target, "press": pos,
                      "size": target.size(), "slice_sizes": slice_sizes,
                      "window": win, "active": False, "group": group,
                      "reorder_only": reorder_only,
                      "freeze": False, "blocked": False,
                      "offset": None, "intent": None,
                      "layer": None, "ghost": None}
        return False

    def _move_drag(self, pos: QtCore.QPoint) -> None:
        d = self._drag
        if d is None:
            return
        if not d["active"]:
            if (pos - d["press"]).manhattanLength() <= self._DRAG_SLOP:
                return
            kind = self._drag_kind(d["target"])
            if d.get("reorder_only") and len(self.panels) <= 1:
                if not d.get("blocked"):
                    d["blocked"] = True
                    self.status.setText(
                        "单幅剖面不能拖出；整块移动请拖上方「剖面」标题行。")
                return
            # 工作区只剩它这一块时**不允许拖走**（松手回原位）：拖出去会变成空工作区，
            # "让位"也没有别的块可铺。浮窗（本来就在窗外）不受这条限制 —— 拖回来才是它的用途。
            # 对比换序不涉及“把块拖走”，所以不适用这条限制。
            if (d["window"] is None and not d.get("reorder_only")
                    and not self._visible_excluding(kind)):
                if not d.get("blocked"):
                    d["blocked"] = True
                    self.status.setText(
                        "工作区只剩这一块，不能拖出去（先用右上角胶囊同时显示别的面板）。")
                return
            d["active"] = True
            d["freeze"] = False       # 拿起这一次先不冻结窗口：让"归位"能改一次尺寸
            d["header"].setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            self._zone_frozen = None  # 判定基准等"归位"落定后再冻结（见 _zone_side_at）
            if d["window"] is not None:
                d["offset"] = pos - d["window"].frameGeometry().topLeft()
                d["freeze"] = True
            else:
                d["offset"] = pos - d["target"].mapToGlobal(QtCore.QPoint(0, 0))
                # 先抓快照（此时槽位还没变），再让它**立刻让位**（顺带按预设改一次窗口尺寸）
                self._open_drag_layer(d)
                self._enter_drag_layout(kind)
                d["freeze"] = True    # 此后到松手前窗口尺寸恒定，挤占只在内部发生

        # 已经在独立窗口里的面板：拖动就是搬窗口；同时照样算落位（拖回主窗口就会收回）。
        # 以前这里直接 return，于是"拖回时没有亮线指引、落点也不生效"。
        if d["window"] is not None:
            d["window"].move(pos - d["offset"])
            self._update_drop_hint(pos, d, exclude=None)
            return

        if d["layer"] is not None:
            d["layer"].move(pos - d["offset"])
        self._update_drop_hint(pos, d, exclude=d["target"])

    def _update_drop_hint(self, pos: QtCore.QPoint, d: dict, exclude) -> None:
        """按光标位置算出"松手会发生什么"，并把工作区**预先挤占好**、画出落位预览。

        拖窗内面板与拖浮窗走的是**同一套**判定，所以看到什么、松手就是什么。
        """
        kind = self._drag_kind(d["target"])
        intent = self._drop_intent_at(
            pos, kind, exclude,
            group=bool(d.get("group")), reorder=bool(d.get("reorder_only")))
        d["intent"] = intent
        self._apply_drag_preview(kind, intent)

    def _drag_is_reorder(self) -> bool:
        """这次拖动是不是"对比模式下换数据顺序"（拖的是组内某幅剖面）。

        组标题的拖动不算换序：它移动的是整个剖面区域。换序时工作区**不该让位**：
        剖面组还在（别的剖面板占着它的位置），换的只是数据顺序 —— 让位会把整个
        剖面组抽掉，光标底下的目标块跟着跑，判定就全乱了。
        """
        d = self._drag
        return bool(d and d.get("reorder_only") and len(self.panels) > 1)

    def _enter_drag_layout(self, kind: str) -> None:
        """面板一"离手"就**立刻让位**：当作它已经不在窗口里，剩下几块按预设铺满。

        这就是需求里的"窗口内剩余界面自动按预设填充空间、不再保留占位"：原来那块原位
        会留一个虚线占位框（GhostSlot），现在是它的槽位直接消失、邻居立刻吃掉。
        """
        if self._drag_is_reorder():
            return
        self._drag_vis.add(kind)
        self._preview_dock.discard(kind)
        self._preview_state = None
        self._preview_cap = None
        self._sync_layout_for_count(force_default=False)

    def _clear_drag_layout(self, relayout: bool = True) -> None:
        """拖动结束：清掉瞬时的"让位 / 预览停靠"状态（构图由后续落位决定）。

        ``relayout=False`` 用于"马上还要落一次最终构图"的路径，免得先按中间态多排一次。
        """
        wrap = getattr(self, "workspace", None)
        if wrap is not None:
            wrap.show_drop_preview(None)       # **一定要收掉蓝色感应区**（否则会赖着不走）
        self._zone_frozen = None
        if not (self._drag_vis or self._preview_dock):
            return
        self._drag_vis.clear()
        self._preview_dock.clear()
        self._preview_state = None
        self._preview_cap = None
        if relayout:
            self._sync_layout_for_count(force_default=False)

    def _apply_drag_preview(self, kind: str, intent: dict | None) -> None:
        """**实时挤占**：命中落位时，工作区先摆成"松手之后的样子"。

        规则（对应需求里的分类讨论）：
          * 被拖那块当作**已经停靠**，先按结果构图把树建好；
          * "含被拖槽位的那根 splitter"强制成 **1/3 : 2/3**（被拖的那格占三分之一，按判定侧）；
          * 另一根 splitter 恢复"让位态"里的实际尺寸 —— 于是插剖面时单道尺寸位置真的不动，
            插单道 / 三维时其余两块作为整体只被压缩一个方向；
          * 蓝色感应区 = 那块 1/3（由冻结的判定轴 / 区域直接算出，不依赖实时几何）。
        没命中落位时退回"让位"状态（剩下几块铺满）。状态没变就直接返回 ——
        拖动中每一帧都重排会卡。
        """
        wrap = getattr(self, "workspace", None)
        if self._drag_is_reorder():
            # 对比模式换数据顺序：**不让位**，只用面板上的高亮条提示目标块
            if wrap is not None:
                wrap.show_drop_preview(None)
            other = intent.get("panel") if intent else None
            for p in self.panels:
                self._highlight_panel(p, p is other,
                                      intent.get("zone") if other else None)
            return
        target = intent.get("target") if intent else None
        side = intent.get("side") if intent else None
        state = (kind, target, side)
        if state == self._preview_state:
            return
        self._preview_state = state
        # 挤占前先量下"让位态"各块的实际尺寸：命中落位时，不该动的那几块要按它恢复。
        # 只量一次（首次命中时布局已落定，见 _zone_side_at），之后来回换侧都用这份 ——
        # 否则每次换侧都从"正在挤压的中间态"再量一次，几轮下来尺寸会漂。
        if target is None:
            self._preview_cap = None
        elif self._preview_cap is None:
            self._preview_cap = {k: (h.width(), h.height())
                                 for k, h in self._leaf_widgets().items()}
        cap = self._preview_cap or {}
        if target is None:
            # 没命中落位（含"拖到某块剖面上换数据顺序"）：退回让位状态
            self._preview_dock.discard(kind)
            self._drag_vis.add(kind)
            if wrap is not None:
                wrap.show_drop_preview(None)
        else:
            preset, first = target
            self._drag_vis.discard(kind)
            self._preview_dock.add(kind)
            self._content_shown[kind] = True
            if GROUP_OF.get(preset, 0) >= 3:
                self._layout_preset = preset
            self._align_pair_order(first)
        self._sync_layout_for_count(force_default=False)
        if target is not None:
            self._squeeze_drag_preview(kind, cap)
        if wrap is not None:
            wrap.show_drop_preview(self._preview_rect_for_drag(kind, intent))
        other = intent.get("panel") if intent else None
        for p in self.panels:
            self._highlight_panel(p, p is other, intent.get("zone") if other else None)

    def _squeeze_drag_preview(self, kind: str, cap: dict) -> None:
        """占位预览的挤占（见 :meth:`_apply_drag_preview`）。

        * 含被拖槽位的那根 splitter：按判定轴强制 1/3 : 2/3，被拖那格占三分之一；
        * 另一根 splitter：保持"让位态"的实际尺寸（``cap`` 是挤占前量下来的各块宽高）。
        """
        tree = self._tree
        leaf = self._leaf_widgets().get(kind)
        if tree is None or leaf is None:
            return
        inner, root = tree.get("inner"), tree.get("root")
        if inner is not None and leaf.parent() is inner:
            s_drag, other = inner, root
        else:
            s_drag, other = root, inner
        if s_drag is None:
            return
        # 先放开所有硬性最小尺寸：否则上一步按自然尺寸设下的"静止最小尺寸"会把挤压顶回去
        # （实测插剖面时单道被顶得比"让位态"更高，看着就是单道在动）。拖动结束时的
        # 正常重排会重新设回来。
        self._relax_content_min()
        total = self._splitter_span(s_drag)
        n = s_drag.count()
        # 只把 1/3 : 2/3 分给**看得见**的子块：两块构图的树里还挂着第三块（尺寸恒为 0），
        # 按 child 数平均分会让那块收起的面板凭空占走 2/9 —— 那就是"收缩后冒出个空面板"。
        shown = self._effective_shown()
        vis_idx = [i for i in range(n) if self._child_visible(s_drag.widget(i), shown)]
        idx = next((i for i in range(n) if s_drag.widget(i) is leaf), vis_idx[0])
        third = total / 3.0
        rest = (total - third) / max(1, len(vis_idx) - 1)
        sizes = [(third if i == idx else rest) if i in vis_idx else 0.0
                 for i in range(n)]
        self._apply_sizes(s_drag, [int(round(v)) for v in sizes], True)
        if other is not None:
            self._apply_sizes(other, self._hold_sizes(other, cap, kind), True)

    def _child_visible(self, widget, shown: dict) -> bool:
        """子块是不是"看得见"的：叶子看显隐，内置 inner（分割器）视为可见。"""
        if isinstance(widget, QtWidgets.QSplitter):
            return True
        k = self._key_of_widget(widget)
        return bool(k is not None and shown.get(k))

    def _splitter_span(self, sp) -> float:
        """splitter 交给**子块**的总长度（沿它自己的轴，已扣掉把手宽度）。

        Qt 的 ``sizes()`` 之和 = 控件长度 − 把手宽度 ×(n−1)，所以直接拿 work_host 的
        宽/高当总量会多算几个把手，归一化后子块尺寸会差几像素（看着就是"单道动了"）。
        """
        horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
        extent = self.work_host.width() if horiz else self.work_host.height()
        return max(1.0, float(extent) - float(sp.handleWidth()) * max(0, sp.count() - 1))

    def _hold_sizes(self, sp, cap: dict, kind: str) -> list:
        """``sp`` 每个子块保持它在"让位态"里的尺寸（沿它自己的轴）。

        子块若是"内置 inner"（另一根 splitter），它其实是"剩下那几块"整体占的那块区域，
        用"总量减去其它叶子的尺寸"补出来。
        """
        horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
        total = self._splitter_span(sp)
        sizes, leaf_sum, filler = [], 0.0, False
        for i in range(sp.count()):
            k = self._key_of_widget(sp.widget(i))
            if k is not None and k != kind:
                v = float(cap.get(k, (0.0, 0.0))[0 if horiz else 1])
                sizes.append(v)
                leaf_sum += v
            else:
                sizes.append(None)
                filler = True
        if filler:
            fill = max(1.0, total - leaf_sum)
            return [int(round(fill if v is None else max(1.0, v))) for v in sizes]
        return [int(round(max(1.0, v))) for v in sizes]

    def _leaf_widgets(self) -> dict:
        return {k: getattr(self, n) for k, n in self._LEAF_OF.items()}

    def _key_of_widget(self, widget):
        for k, n in self._LEAF_OF.items():
            if getattr(self, n, None) is widget:
                return k
        return None

    def _preview_rect_for_drag(self, kind: str, intent: dict | None) -> tuple | None:
        """落位预览的相对矩形 = 那块 **1/3**（由冻结的判定轴与区域直接算出）。

        不依赖实时几何 —— 排布在动画时也不会画出落在工作区外面的怪矩形，所以
        不再需要"跟着动画刷新"的定时器。
        """
        if not intent or "target" not in intent:
            return None
        side = intent.get("side")
        spec = self._zone_frozen or self._zone_spec(kind)
        if spec is None or side not in ("first", "second"):
            return None
        axis, (rx, ry, rw, rh) = spec
        if axis == "x":
            w = rw / 3.0
            return (rx if side == "first" else rx + rw - w, ry, w, rh)
        h = rh / 3.0
        return (rx, ry if side == "first" else ry + rh - h, rw, h)

    def _drop_intent_at(self, global_pos: QtCore.QPoint, kind: str,
                        exclude=None, *, group: bool = False,
                        reorder: bool = False) -> dict | None:
        """松手会产生的结果；``None`` 表示没有落位（=按"拉出为独立窗口"处理）。

        * ``{"side": …, "target": (摆法键, 第一块)}`` → 插到工作区的某一侧（左/上 或 右/下）
        * ``{"panel": 面板, "zone": "left"/"right"/None}`` → 插到某块剖面旁边 / 与它换位
          （只在**对比模式**、即窗口里有 ≥2 块剖面、且拖的是组内单图时才走这条）

        ``group=True`` 表示拖的是整个剖面区域：它只按工作区边缘落位，永远不走
        “换数据顺序”那一条，否则整组拖动会被面板换序规则吞掉。
        """
        if not group and kind == "slice" and len(self.panels) > 1:
            drop = self._drop_zone_at(global_pos, exclude=exclude)
            if drop is not None:
                return {"panel": drop[0], "zone": drop[1]}
        if reorder:
            # 单图拖动只允许“落到另一幅剖面上换序”，不参与工作区边缘的停靠
            return None
        side = self._zone_side_at(global_pos, kind)
        if side is not None:
            target = self._drop_target(kind, side)
            if target is not None:
                return {"side": side, "target": target}
        return None

    def _visible_excluding(self, kind: str) -> list:
        """**基准**可见集合：几何上真的在窗口里的块，再排除被拖的那块。

        不看拖动中的瞬时状态（``_drag_vis`` / ``_preview_dock``）—— 判定用的是"松手前
        窗口里有几幅图"，也就是需求里分类讨论的那两条。
        """
        out = []
        for k in PANEL_ORDER:
            if k == kind or not self._content_shown.get(k):
                continue
            if k == "slice":
                if self.panels and not self._is_detached(self.slice_wrap):
                    out.append(k)
            elif k == "trace":
                if not self._is_detached(self.trace_frame):
                    out.append(k)
            elif k == "right":
                if not self._is_detached(self.right_frame):
                    out.append(k)
        return out

    def _region_above(self, key: str) -> tuple:
        """某块面板**上方**那一整块的相对区域（0~1）；那块看不见时退回整个工作区。"""
        wrap = getattr(self, "workspace", None)
        holder = {"slice": self.slice_holder, "trace": self.trace_holder,
                  "right": self.right_holder}[key]
        if wrap is None or wrap.height() <= 1 or holder.height() <= 0:
            return (0.0, 0.0, 1.0, 1.0)
        top = wrap.mapFromGlobal(holder.mapToGlobal(QtCore.QPoint(0, 0))).y()
        return (0.0, 0.0, 1.0, max(0.0, min(1.0, top / wrap.height())))

    def _zone_spec(self, kind: str):
        """这一回想"插到哪一侧"的**判定轴**与**判定区域**（相对工作区，0~1）。

        按窗口里除被拖那块以外还剩几幅图分（需求里的分类讨论）：
        * 剩 1 幅 → 结果就是这一对（左右或上下），判定轴 = 这一对的方向，区域 = 整个工作区；
        * 剩 2 幅 → 结果是三块构图，按插入的是哪一块决定轴与区域：
            - 插剖面：与上方的三维**左右**并排，区域 = **单道上方那一整块**；
            - 插单道：与已有两图**上下**叠放，区域 = 整个工作区；
            - 插三维：与已有两图**左右**并排，区域 = 整个工作区。
        没有可插入的余地时返回 ``None``。
        """
        vis = self._visible_excluding(kind)
        if len(vis) == 1:
            axis = "x" if pair_layout(tuple(sorted((kind, vis[0]))))[1] == "H" else "y"
            return axis, (0.0, 0.0, 1.0, 1.0)
        if len(vis) == 2:
            if kind == "slice":
                return "x", self._region_above("trace")
            if kind == "trace":
                return "y", (0.0, 0.0, 1.0, 1.0)
            return "x", (0.0, 0.0, 1.0, 1.0)
        return None

    def _zone_side_at(self, global_pos: QtCore.QPoint, kind: str) -> str | None:
        """光标落在"插入侧"的哪一侧：``first``（前/左/上三分之一）或 ``second``（后/右/下三分之一）。

        判定区域按 :meth:`_zone_spec` 算，两侧各占该区域的 :data:`EDGE_FRAC`；**中间那三分之一
        是不落位区** —— 松手就按"拉出为独立窗口"处理。

        判定基准**在拿起那一刻冻结一次**（``_zone_frozen``），且基准是"拿起、让位**落定之后**
        用户看到的场景" —— 布局还在过渡的那一小会儿先不判定（否则会拿过渡中的几何当基准）。
        一旦冻住就不再变：拖动中布局在挤占，实时重算会让判定区域跟着动、意图来回翻，
        看着就是面板在抖。
        """
        spec = self._zone_frozen
        if spec is None:
            if self._layout_anim_running():
                return None                      # "归位"还没落定，先不判定
            spec = self._zone_frozen = self._zone_spec(kind)
        if spec is None:
            return None
        axis, (rx, ry, rw, rh) = spec
        wrap = getattr(self, "workspace", None)
        if wrap is None or not wrap.isVisible():
            return None
        local = wrap.mapFromGlobal(global_pos)
        if not wrap.rect().contains(local):
            return None
        W, H = max(1, wrap.width()), max(1, wrap.height())
        if axis == "x":
            frac = (local.x() / W - rx) / max(1e-6, rw)
        else:
            frac = (local.y() / H - ry) / max(1e-6, rh)
        if frac <= EDGE_FRAC:
            return "first"
        if frac >= 1.0 - EDGE_FRAC:
            return "second"
        return None

    def _layout_anim_running(self) -> bool:
        """工作区这棵树 / 总窗口是否还有尺寸动画在跑（见 :meth:`_animate_layout_change`）。"""
        anim = getattr(self, "_layout_anim", None)
        try:
            if anim is not None and anim.state() == QtCore.QAbstractAnimation.State.Running:
                return True
        except RuntimeError:                       # DeleteWhenStopped 已经把对象删了
            pass
        return self._layout_animating()

    def _drop_target(self, kind: str, side: str):
        """``side``（first/second）→ ``(构图键, 可换序那两块的第一块)``。

        逐块查表保证"拖到哪就落在哪"。三块构图里有两块是"预设之外的内部构图"
        （BT：单道在上；AL：三维在左），但规则与 A/B 完全镜像，所以仍按同一套处理：
          * 插剖面：B 里它是上排的一块 → first 落在左上、second 落在右上；
          * 插单道：first → BT（单道在上），second → B（底栏通栏）；
          * 插三维：first → AL（三维在左一列），second → A（右列）。
        """
        vis = self._visible_excluding(kind)
        if len(vis) == 1:                       # 只剩一幅 → 结果就是那一对
            other = vis[0]
            key = pair_layout(tuple(sorted((kind, other))))[0]
            return key, (kind if side == "first" else other)
        if len(vis) < 2:
            return None
        if kind == "slice":
            return ("B", "slice") if side == "first" else ("B", "right")
        if kind == "trace":
            return ("BT", "trace") if side == "first" else ("B", "trace")
        return ("AL", "right") if side == "first" else ("A", "right")

    def _open_drag_layer(self, d: dict) -> None:
        """面板"离手"：抓快照并隐藏原面板。

        整组 / 普通面板隐藏后让位（邻居吃掉槽位）；对比换序只让**画面**消失，
        槽位宽度钉住，避免邻居先胀后缩。
        """
        target = d["target"]
        # 快照必须在隐藏**之前**抓，否则拿到的是空白图
        snap = self._panel_snapshot(target)
        if d.get("reorder_only"):
            # 换序时原面板要消失（手上拿着它），但**槽位宽度必须钉住**：
            # 否则邻居会立刻吃掉这块宽度，松手再恢复就成了“面板先缩再弹回来”。
            try:
                holder = self.panel_holders[self.panels.index(target)]
            except (ValueError, IndexError):
                holder = None
            if holder is not None and holder.width() > 1:
                d["pinned_holder"] = holder
                holder.setFixedWidth(holder.width())
        target.setVisible(False)
        layer = DragLayer(snap)
        layer.show()
        d["layer"] = layer

    def _panel_snapshot(self, target: QtWidgets.QWidget) -> QtGui.QPixmap:
        """拖动用的快照。三维那块要单独抓 framebuffer —— QWidget.grab() 抓不到 GL 画面。"""
        snap = target.grab()
        if self.view3d is not None and target.isAncestorOf(self.view3d):
            try:
                fb = self.view3d.grabFramebuffer()
            except Exception:                        # pragma: no cover
                fb = None
            if fb is not None and not fb.isNull():
                top_left = self.view3d.mapTo(target, QtCore.QPoint(0, 0))
                dpr = float(snap.devicePixelRatio() or 1.0)
                p = QtGui.QPainter(snap)
                p.drawImage(
                    QtCore.QRectF(top_left.x() * dpr, top_left.y() * dpr,
                                  self.view3d.width() * dpr,
                                  self.view3d.height() * dpr),
                    fb, QtCore.QRectF(0, 0, fb.width(), fb.height()))
                p.end()
        return snap

    # ---------------------------------------------------------------- 松手
    def _finish_drag(self, pos: QtCore.QPoint) -> None:
        """松手定稿：落在感应区里就插进去；**其它任何位置一律拉出为独立窗口**。

        "其它位置"包括：中间那三分之一、工作区之外的顶栏/左侧栏、以及主窗口外面 ——
        以前落在工作区空白处是"取消拖动、回原位"，现在统一按"拉出"处理（用户明确要求：
        拖出去的那块本来就允许独立存在，不需要"取消"这一档）。占位框已经没有了，
        拖动期间工作区也早就按预设让位好了。
        """
        d, self._drag = self._drag, None
        if d is None:
            return
        d["header"].setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        if not d["active"]:
            self._clear_drag_layout()               # 只是点了一下：还原
            return
        for p in self.panels:
            self._highlight_panel(p, False)

        intent = d.get("intent")
        # 换序发生在浮动组内部时，光标本来就在主窗口外，不能因此拒绝落位
        accept = (intent is not None
                  and (self._inside_main_window(pos)
                       or (d.get("reorder_only") and "panel" in intent)))
        if accept:
            self._discard_drag_layer(d, restore=True)
            self._clear_drag_layout(relayout=False)  # 别多排一次：下面 _apply_intent 会落最终构图
            self._apply_intent(d, intent)
            if "panel" in intent and d.get("slice_sizes"):
                # 换序 = 只换数据顺序：各剖面块必须保持松手前的像素尺寸，
                # 绝不触发 splitter / window geometry 重排。
                sizes = list(d["slice_sizes"])
                QtCore.QTimer.singleShot(
                    0, lambda s=sizes: self.slice_split.setSizes(s))
            return
        if d.get("reorder_only"):
            # 单图拖动只用于换序：没有落到另一幅剖面上就原样回去，绝不拉出/让位
            self._discard_drag_layer(d, restore=True)
            self._clear_drag_layout()
            self.status.setText("拖到另一幅剖面上即可交换数据顺序。")
            return
        self._discard_drag_layer(d, restore=True)
        if d["window"] is not None:
            # 本来就是浮窗、又没命中落位 → 保持独立显示（撤掉拖动中的瞬时状态即可）
            self._clear_drag_layout()
            self.status.setText("浮窗保持独立显示（拖到工作区两侧三分之一可插回主窗口）。")
            return
        self._tear_off(d, pos)

    def _apply_intent(self, d: dict, intent: dict | None) -> None:
        """按落位意图重排 —— 与拖动时**实时挤占**出来的样子完全同源，所见即所得。"""
        if not intent:
            return
        if "target" in intent:
            preset, first = intent["target"]
            self._apply_layout(preset, first=first)
            return
        other = intent.get("panel")
        if other is None:
            return
        zone = intent.get("zone")
        if zone is None:
            self._swap_panel_order(d["target"], other)       # 主体 → 交换
        else:
            self._move_panel_near(d["target"], other, zone)   # 侧边 → 插入

    def _discard_drag_layer(self, d: dict, restore: bool) -> None:
        holder = d.get("pinned_holder")
        if holder is not None:
            # 换序结束：解除宽度钉住，交回 splitter / _sync_holder_widths 管理
            try:
                holder.setMinimumWidth(0)
                holder.setMaximumWidth(16777215)
            except RuntimeError:                # pragma: no cover
                pass
            d["pinned_holder"] = None
        if d.get("ghost") is not None:
            d["ghost"].setParent(None)
            d["ghost"].deleteLater()
            d["ghost"] = None
        if d.get("layer") is not None:
            d["layer"].hide()
            d["layer"].deleteLater()
            d["layer"] = None
        if restore:
            d["target"].setVisible(True)

    def _inside_main_window(self, global_pos: QtCore.QPoint) -> bool:
        return self.frameGeometry().contains(global_pos)

    # ---------------------------------------------------------------- 拉出
    def _tear_off(self, d: dict, pos: QtCore.QPoint) -> None:
        target = d["target"]
        kind = self._drag_kind(target)
        # **全屏 / 最大化下拖出面板 = 自动退出**，并回到进全屏前的窗口几何；
        # 浮窗尺寸用面板在正常窗口里的自然尺寸封顶，避免弹出和屏幕一样大的窗口。
        was_big = self.isFullScreen() or self.isMaximized()
        normal = self.normalGeometry() if was_big else None
        if was_big:
            self._auto_resize_depth += 1
            try:
                self.showNormal()
                if normal is not None and normal.isValid():
                    self.setGeometry(normal)
            finally:
                self._auto_resize_depth -= 1
            if normal is not None and normal.isValid():
                self._user_size = (normal.width(), normal.height())

        self._clear_drag_layout(relayout=False)   # 拉出前先撤掉瞬时的让位/预览状态
        offset = d["offset"] or QtCore.QPoint(0, 0)
        # 尺寸**与窗内一致**：拉出就是"原样搬出去"，不放大也不缩小。
        # 用按下那一刻记下的尺寸，因为面板"离手"后它的槽位已经被邻居吃掉了。
        # 以前按面板种类写死了尺寸，一块剖面拖出来变成 900 宽；三维更明显 ——
        # 窗口一变宽，GL 相机按新宽高比重算，模型看着就"变好大"。
        stamp = d.get("size") or target.size()
        w = max(self.MIN_FLOAT[0], stamp.width())
        h = max(self.MIN_FLOAT[1], stamp.height())
        if was_big:
            metrics = self._panel_metrics().get(kind)
            if metrics:
                w = min(w, max(self.MIN_FLOAT[0], metrics["nat_w"]))
                h = min(h, max(self.MIN_FLOAT[1], metrics["nat_h"]))
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            w, h = min(w, avail.width()), min(h, avail.height())
        size = (w, h)
        self._discard_drag_layer(d, restore=False)

        win = FloatingPanel(target, size, self)
        win.returned.connect(self._close_detached)
        self._detached[target] = win
        win.show()
        # 让光标停在面板里的同一个相对位置 —— 手感才对
        tw = max(1, target.width())
        th = max(1, target.height())
        win.move(pos - QtCore.QPoint(int(offset.x() / tw * win.width()),
                                     int(offset.y() / th * win.height())))
        target.setVisible(True)
        self._sync_holder_widths()
        # 拖出去之后，剩下两块必须**重新落成设计好的两栏构图**（而不是沿用三块构图
        # 的树与尺寸）：走 _sync_layout_for_count 会让它按实际可见集合重建树。
        self._sync_layout_for_count(force_default=False)
        self._sync_panel_chips()
        self.status.setText("已拉出为独立窗口：拖回工作区或点右上角箭头可收回。")

    def _close_detached(self, widget, silent: bool = False) -> None:
        """收回：把面板放回原位，再销毁空掉的浮窗。

        **无条件先还原面板**（即使 ``_detached`` 里已经没有这条记录）：一个面板如果
        既不在主窗口、也不在任何可见浮窗里，就再也找不回来了 —— 这里多还原一次不会
        有副作用，却堵住了"状态错乱 → 面板永久丢失"这条路。
        """
        win = self._detached.pop(widget, None)
        self._restore_detached(widget)
        if win is not None:
            win.hide()
            # 在它自己的信号处理里删窗口会把发送者删掉，所以推迟到下一轮事件循环
            QtCore.QTimer.singleShot(0, win.deleteLater)
        self._sync_holder_widths()
        # 收回后按"实际可见集合"重排：三块要么 A 要么 B，两块落在对应那一对上。
        self._sync_layout_for_count(force_default=False)
        self._sync_panel_chips()
        if not silent:
            self.status.setText("已把面板收回主窗口。")

    def _restore_detached(self, widget) -> None:
        """按控件类型放回它在主窗口里的原位。"""
        FloatingPanel._set_floating(widget, False)
        if widget is self.slice_wrap:
            # 整个剖面区域作为一个浮窗单元收回：放回外层占位容器
            self.slice_holder.layout().addWidget(widget)
            widget.setVisible(True)
            return
        if isinstance(widget, SlicePanel):
            if widget in self.panels:
                self.panel_holders[self.panels.index(widget)].layout().addWidget(widget)
            widget.setVisible(True)
            return
        if widget is self.trace_frame:
            self._trace_holder_layout.insertWidget(0, self.trace_frame)
            widget.setVisible(True)
            return
        if widget is self.right_frame:
            self._right_holder_layout.insertWidget(0, self.right_frame)
            widget.setVisible(True)

    # ---------------------------------------------------------------- 换序
    def _swap_panel_order(self, src, target) -> None:
        i, j = self.panels.index(src), self.panels.index(target)
        self.datasets[i], self.datasets[j] = self.datasets[j], self.datasets[i]
        # 当前"激活的数据"要跟着数据走，而不是跟着位置走
        if self.active == i:
            self.active = j
        elif self.active == j:
            self.active = i
        self._after_order_change()
        self.status.setText(
            f"已交换数据 {i + 1} 与 {j + 1} 的剖面位置（叠加波形配色随之改变）。")

    def _move_panel_near(self, src, target, zone: str) -> None:
        """把 ``src`` 这块剖面挪到 ``target`` 的 ``left`` / ``right`` 一侧。

        挪的是 ``self.datasets`` 的顺序（面板按位置和数据一一对应），所以叠加波形与
        单道波形的配色会跟着新的"从左到右"顺序重排 —— 这正是用户拖动想要的效果。
        激活的数据按**对象**跟过去，而不是按下标，免得算错插入点导致的连带位移。
        """
        i, j = self.panels.index(src), self.panels.index(target)
        if i == j:
            return
        active_ds = self.datasets[self.active]
        item = self.datasets.pop(i)
        insert_at = j if zone == "left" else j + 1
        if i < insert_at:
            insert_at -= 1
        self.datasets.insert(insert_at, item)
        self.active = self.datasets.index(active_ds)
        self._after_order_change()
        self.status.setText(
            f"已把数据 {i + 1} 插到第 {insert_at + 1} 位（叠加波形配色随之重排）。")

    def _after_order_change(self) -> None:
        self._sync_controls()
        self._refresh_all(sync_controls=False)
        self._update_face_info()

    # 拖动时贴着某块剖面面板左右边缘各留一条"感应带"：进感应带 = 插到这个位置，
    # 进面板主体 = 交换。两种意图各有各的提示，所以窗内**不需要**"离原位多远算
    # 拉出"这种距离阈值 —— 窗内只会插入/交换，只有拖到窗口外才是拉出。
    DROP_ZONE = 26

    def _panel_at(self, global_pos: QtCore.QPoint, exclude=None):
        """落在哪一块剖面面板上；已经在独立窗口里的不算。"""
        for panel in self.panels:
            if panel is exclude or self._is_detached(panel):
                continue
            if panel.isVisible() and panel.rect().contains(panel.mapFromGlobal(global_pos)):
                return panel
        return None

    def _drop_zone_at(self, global_pos: QtCore.QPoint, exclude=None):
        """``(面板, 落在哪一侧)``；``None`` 表示落在面板主体（= 交换）。"""
        panel = self._panel_at(global_pos, exclude=exclude)
        if panel is None:
            return None
        local = panel.mapFromGlobal(global_pos)
        if local.x() < self.DROP_ZONE:
            return (panel, "left")
        if local.x() > panel.width() - self.DROP_ZONE:
            return (panel, "right")
        return (panel, None)

    @staticmethod
    def _highlight_panel(panel, on: bool, zone: str | None = None) -> None:
        """落点提示：主体整块高亮 = 会交换；左/右边缘一条亮竖条 = 会插到这里。"""
        panel.setProperty("dropTarget", bool(on and zone is None))
        panel.setProperty("dropLeft", bool(on and zone == "left"))
        panel.setProperty("dropRight", bool(on and zone == "right"))
        panel.style().unpolish(panel)
        panel.style().polish(panel)

    def _sync_holder_widths(self) -> None:
        """剖面面板容器的宽度分配。

        剖面的整组移动/浮窗由外层 `slice_holder` 负责；这里只处理**组内**的
        “仅显示波形叠加”（非第 0 块压到 0 宽）。其余按之前的比例补齐（用
        “压宽度”而不是隐藏控件：QSplitter 重新显示子控件会把尺寸重排）。
        """
        n = len(self.panel_holders)
        if n == 0:
            return
        hidden = [self._overlay_on and k > 0 for k in range(n)]
        for k, holder in enumerate(self.panel_holders):
            holder.setMinimumWidth(0)
            holder.setMaximumWidth(0 if hidden[k] else 16777215)
        if any(hidden):
            self.slice_split.setSizes([0 if hidden[k] else 1 for k in range(n)])
            return
        saved = self._overlay_sizes
        self._overlay_sizes = None
        if saved and len(saved) == n and all(s > 0 for s in saved):
            self.slice_split.setSizes(list(saved))
            # 刚从"宽度上限被压住"的状态回来，这一帧控件的宽度还是 0，
            # QSplitter 可能拒绝这次请求；下一轮事件循环再设一次就稳了。
            QtCore.QTimer.singleShot(
                0, lambda s=list(saved): self.slice_split.setSizes(s))
        else:
            self.slice_split.setSizes([1] * n)

    def _apply_overlay_layout(self, overlay: bool) -> None:
        """「仅显示波形 + 多数据」时把除第 0 块以外的剖面板让位（见 _sync_holder_widths）。"""
        if overlay == self._overlay_on:
            return
        if overlay:
            self._overlay_sizes = list(self.slice_split.sizes())
        self._overlay_on = overlay
        self._sync_holder_widths()

    # ---------------------------------------------------------------- 右侧
    def _build_right(self) -> None:
        """三维容器（同单道波形套一层，拉出后容器留在 splitter 里占位）。

        原来底部占了四行：一行"定位到面"的说明 + 三个方向按钮 + 「复位视角」+
        四行状态说明。其中三个方向按钮是**纯冗余** —— 在三维体上点某一面、或在左栏
        「剖切与播放」里选方向，本来就会切到那一面（见 :meth:`_on_mode` /
        :meth:`_focus_face`）。现在只留**一行**：当前在哪一面的紧凑读数 +
        「复位视角」图标按钮；长说明交给 tooltip（见 :meth:`_update_face_info`）。
        """
        holder = QtWidgets.QWidget()
        holder.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                             QtWidgets.QSizePolicy.Policy.Ignored)
        self.right_holder = holder
        hh = QtWidgets.QVBoxLayout(holder)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(0)

        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.right_header, self.right_head, self.right_title = pane_header("数据体")
        self.right_header.setToolTip(
            "左键拖动旋转、滚轮缩放、中键拖动平移；点某一面 = 切到那个切片方向。\n"
            "标题行左端拖动 = 拉出独立窗口 / 拖到工作区边缘换分屏方式。")
        self.right_head.addSpacing(24)     # 给浮窗右上角那颗"收回"按钮留出位置
        v.addWidget(self.right_header)
        self.right_frame = wrap
        self._right_holder_layout = hh

        card, lay = make_panel()
        self.right_body = card
        self._right_body_layout = lay       # 收回独立窗口时按这个下标插回去
        # **延迟创建三维视图**：打开软件时只建二维界面，省掉 pyqtgraph.opengl
        # 那一秒多的 import。等这块面板真的要显示、或载入三维数据时再建。
        self.view3d = None
        self._view3d_failed = False
        self._view3d_creating = False
        self._view3d_slot = QtWidgets.QWidget()
        self._view3d_slot_lay = QtWidgets.QVBoxLayout(self._view3d_slot)
        self._view3d_slot_lay.setContentsMargins(0, 0, 0, 0)
        self._view3d_slot_lay.setSpacing(0)
        self._view3d_placeholder = QtWidgets.QLabel(
            "三维视图在需要时加载…\n（首次显示三维面板或载入三维数据）")
        self._view3d_placeholder.setObjectName("Hint")
        self._view3d_placeholder.setWordWrap(True)
        self._view3d_placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._view3d_slot_lay.addWidget(self._view3d_placeholder, 1)
        lay.addWidget(self._view3d_slot, 1)

        # 底部一行：当前面的紧凑读数 + 「复位视角」
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.face_info = QtWidgets.QLabel("--")
        self.face_info.setObjectName("Status")
        self.face_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft
                                    | QtCore.Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.face_info, 1)
        self.btn_reset = QtWidgets.QToolButton()
        self.btn_reset.setObjectName("HeadBtn")
        self.btn_reset.setIcon(QtGui.QIcon(icons.reset_view(18, style.TEXT_DIM)))
        self.btn_reset.setIconSize(QtCore.QSize(18, 18))
        self.btn_reset.setFixedSize(24, 24)
        self.btn_reset.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setToolTip("复位三维视角（回到默认的等轴观察角）")
        self.btn_reset.clicked.connect(
            lambda: self.view3d and self.view3d.reset_view())
        row.addWidget(self.btn_reset)
        lay.addLayout(row)

        v.addWidget(card, 1)
        self.right_wrap = wrap
        hh.addWidget(wrap)

    def _ensure_view3d(self):
        """按需创建三维视图；创建失败就在原位给出说明。

        三维面板默认是收起的，启动时没有必要为它 import OpenGL。这里只在
        “面板真的要显示 / 有三维数据要画”时调用一次；之后复用同一个 GL 控件。
        """
        if self.view3d is not None or self._view3d_failed or self._view3d_creating:
            return self.view3d
        self._view3d_creating = True
        self.status.setText("正在准备三维视图…")
        # **不要在这里 processEvents**：那会让右栏先画出“占位文字”，
        # 紧接着又被 GL 控件替换，导入数据时看起来就是闪一下。
        # 同步建好后再一起进布局，事件循环只会看到最终状态。
        try:
            from . import view3d as view3d_mod  # 延迟到此刻才 import OpenGL
            view = view3d_mod.create_view3d()
            if view is None:
                self._view3d_failed = True
                self._view3d_placeholder.setText(
                    "三维视图不可用（未能创建 OpenGL 上下文）。\n"
                    "剖面与波形功能不受影响。")
                self._view3d_placeholder.setVisible(True)
                self.status.setText("三维视图不可用；剖面与波形照常。")
                return None
            self.view3d = view
            view.faceClicked.connect(self._focus_face)
            self._view3d_slot_lay.addWidget(view, 1)
            self._view3d_placeholder.setVisible(False)
            if self.datasets:
                view.set_volume(self.vol)
                view.focus_face(self.mode, animate=False)
                self._refresh_faces()
            return view
        finally:
            self._view3d_creating = False

    def _top_right_owner(self) -> str | None:
        """工作区**右上角**那块面板是谁 —— 悬浮胶囊压在它上面，标题行要给它让位。

        三块构图按"钉住的是谁、在哪个方向"直接查表（``tree["slots"]`` 的前两块就是
        树里真正的先后）：
          * B  → 上排的右边那块（单道收起时上排会顶到最上，仍是它）
          * BT → 顶部通栏的单道
          * A  → 右列的三维
          * AL → 右列的上面那块
        两块 / 一块时退回按树的朝向取"最右"或"最上"。
        """
        if self._tree is None:
            return None
        shown = self._effective_shown()
        slots = self._tree["slots"]
        if not any(shown.get(k) for k in slots):
            return None
        if self._tree.get("inner") is not None and len(slots) >= 3:
            f1, f2 = slots[0], slots[1]
            cands = {"B": (f2, f1, "trace"), "BT": ("trace", f2, f1),
                     "A": ("right", f1, f2), "AL": (f1, f2, "right")}.get(
                         self._tree["preset"])
            if cands:
                for cand in cands:
                    if cand and shown.get(cand):
                        return cand
                return None
        if self.work_tree.orientation() == QtCore.Qt.Orientation.Horizontal:
            for k in reversed(slots):           # 左右排 → 最右那块
                if shown.get(k):
                    return k
        else:
            for k in slots:                     # 上下排 → 最上面那块
                if shown.get(k):
                    return k
        return None

    def _sync_header_pads(self) -> None:
        """给右上角那块面板的标题行在右端留出胶囊的宽度。

        胶囊是浮层（不进布局、不占高度），所以它会压住右上角那块面板的标题行 ——
        标题行右端的内容（比如单道的道号读数）必须让开，否则会被盖住看不全。
        """
        if not getattr(self, "_head_pads", None):
            return
        pad = 0
        cap = getattr(self, "capsule", None)
        if cap is not None:
            pad = int(max(cap.width(), cap.sizeHint().width()) + 2 * Workspace.MARGIN)
        owner = self._top_right_owner()
        for key, item in self._head_pads.items():
            item.changeSize(pad if key == owner else 0, 0,
                            QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Minimum)

    # ------------------------------------------------- 面板显隐（左栏 + 三维）
    def _effective_shown(self) -> dict[str, bool]:
        """当前工作区里**实际**还剩哪些面板要看。

        ``_content_shown`` 是"开关"（面板被拖到独立窗口里仍然算开着），这里再看一层
        几何：被拖走的那块，它的槽位要让出来给别的面板。

        拖动中还叠了两份**瞬时**状态（见 ``__init__``）：正在被拖的那块当作"不在窗口里"
        （剩下几块立刻按预设铺满），落位命中的那块当作"已经停靠"（把槽位先占出来画预览）。
        """
        drag = self._drag_vis
        dock = self._preview_dock
        # 剖面是一个整体：只有整组被拉到独立窗口时才让出主窗口里的槽位
        slice_on = (self._content_shown["slice"]
                    and not self._is_detached(self.slice_wrap))
        return {"slice": (slice_on or "slice" in dock) and "slice" not in drag,
                "trace": ((self._content_shown["trace"]
                           and not self._is_detached(self.trace_frame))
                          or "trace" in dock) and "trace" not in drag,
                "right": ((self._content_shown["right"]
                           and not self._is_detached(self.right_frame))
                          or "right" in dock) and "right" not in drag}

    def _freeze_content_width(self, width: int | None) -> None:
        """侧边栏动画期间把内容区宽度钉住：宽度不变 → 内部不重排，只做裁剪。

        这是"滑出去"能顺的关键 —— 不然每一帧宽度都在变，里面几百个控件要跟着
        重排一遍，还会连带改摘要标签的省略长度。``None`` 表示解冻。
        """
        content = self.left_content
        if width is None:
            content.setMinimumWidth(0)
            content.setMaximumWidth(16777215)
        else:
            content.setFixedWidth(max(0, int(width)))

    def _set_region_visible(self, key: str, on: bool, animate: bool = True) -> None:
        """收起 / 展开**左侧设置面板**：收起后只剩那条常驻图标轨道。

        三维面板由 ``_toggle_content("right")`` 管 —— 它在工作区内部（要和剖面 /
        单道按预设组合），不是一根独立的外侧列。

        收起时**动画期间内容不隐藏**：让它留在原宽度被父容器一点点裁掉，
        看起来才是"被推出去"；等动画结束再真正隐藏（以前是点击瞬间就藏内容，
        于是画面先空一块、再慢慢收窄 —— 那才是"动画不对"）。
        宽度先在动画期间放开，动画结束再钉死 —— 钉住会让中间帧被钳住，
        看起来是"跳"过去而不是滑过去。
        """
        if key != "left":
            self._toggle_content("right")
            return
        if self._region_shown.get("left", True) == bool(on):
            return
        self._region_shown["left"] = bool(on)
        total = self._total(self.body_split)
        old_left = max(self.LEFT_RAIL_W, self.left_wrap.width())
        old_win = self.width()
        old_right = max(1, self.workspace.width())
        chrome = max(0, old_win - old_left - old_right)
        self._sync_rail()

        if not on:
            self._region_sizes["left"] = list(self.body_split.sizes())
            new_left = self.LEFT_RAIL_W
        else:
            saved = self._region_sizes.get("left")
            new_left = (saved[0] if saved and len(saved) == 2 and sum(saved) > 120
                        else self._left_min_w)

        # 侧边栏收起不是“空间不足”，不该让工作区去吸收它让出的宽度：
        # 总窗口等量反向变化，右侧各块维持原来的像素尺寸。
        can_resize_window = not (self.isFullScreen() or self.isMaximized())
        if can_resize_window:
            avail = (self.screen() or QtGui.QGuiApplication.primaryScreen())
            max_w = (avail.availableGeometry().width() if avail is not None else 10 ** 6)
            new_win = min(float(old_win) + (new_left - old_left), max_w)
            new_win = max(new_win, float(self.MIN_SIZE[0]))
            if abs(new_win - old_win) > 1:
                self._resize_keeping_anchor(int(new_win), self.height())
            right_w = max(1, self.width() - new_left - chrome)
            actual_delta = self.width() - old_win
            if self._user_size is not None:
                self._user_size = (max(1, self._user_size[0] + actual_delta),
                                   self._user_size[1])
        else:
            # 全屏 / 最大化：窗口不能动，只能把空间在内部重新分配
            right_w = max(1, total - new_left)

        if not on:
            self.left_wrap.setMinimumWidth(0)
            self.left_wrap.setMaximumWidth(16777215)
            self._freeze_content_width(self.left_content.width())
            self.status.setText("已收起设置面板（点左侧图标轨道展开）。")
            self._apply_sizes(self.body_split, [new_left, right_w],
                              animate, on_done=self._pin_left_rail)
        else:
            self.left_wrap.setMinimumWidth(0)
            self.left_wrap.setMaximumWidth(16777215)
            self.left_content.setVisible(True)
            # 同样先把内容钉在最终宽度上：动画里只有"露出来的部分"在变，内部不重排
            self._freeze_content_width(max(120, new_left - self.LEFT_RAIL_W - 6))
            self.status.setText("已展开设置面板。")
            self._apply_sizes(self.body_split, [new_left, right_w], animate,
                              on_done=self._pin_left_open)
        self._save_ui_state()

    def _pin_left_rail(self) -> None:
        """收起动画结束：这时才真正隐藏内容，再把左栏钉在轨道宽度上。"""
        self.left_content.setVisible(False)
        self._freeze_content_width(None)
        self.left_wrap.setMinimumWidth(self.LEFT_RAIL_W)
        self.left_wrap.setMaximumWidth(self.LEFT_RAIL_W)

    def _pin_left_open(self) -> None:
        """展开动画结束：解冻内容宽度，恢复左栏的可用宽度区间。"""
        self._freeze_content_width(None)
        self.left_wrap.setMinimumWidth(self._left_min_w)
        self.left_wrap.setMaximumWidth(max(self.LEFT_MAX_W, self._left_min_w))

    def _build_statusbar(self) -> QtWidgets.QFrame:
        bar, lay = make_panel()
        lay.setContentsMargins(12, 6, 12, 6)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status = QtWidgets.QLabel("就绪。点击「载入示例」可立即看到效果，或把文件拖进来。")
        self.status.setObjectName("Status")
        row.addWidget(self.status)
        row.addStretch(1)
        self.stats_label = ValueLabel("")
        row.addWidget(self.stats_label)
        lay.addLayout(row)
        return bar

    # ================================================================== 打开
    def open_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开地震数据文件", self._dir_hint(),
            "地震数据 (*.sgy *.segy *.su *.npy *.npz *.mat);;"
            "SEG-Y / SU (*.sgy *.segy *.su);;"
            "NumPy (*.npy *.npz);;MATLAB (*.mat);;所有文件 (*)")
        if path:
            self._open_source(path, reset=True)

    def open_path(self, path: str) -> None:
        """按路径直接打开（命令行参数 / 拖放）：作为主数据载入。"""
        self._open_source(path, reset=True)

    def add_compare_file(self) -> None:
        """再选一份文件载入为对比数据（形状必须与第一份一致）。"""
        if len(self.datasets) >= MAX_DATASETS:
            self._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "添加对比数据", self._dir_hint(),
            "地震数据 (*.sgy *.segy *.su *.npy *.npz *.mat);;所有文件 (*)")
        if path:
            self._open_source(path, reset=False)

    def remove_dataset(self) -> None:
        """移除当前数据；至少保留一份。"""
        if len(self.datasets) <= 1:
            return
        idx = self.active
        self.datasets.pop(idx)
        self._base_clims.pop(idx)
        self.active = max(0, min(idx, len(self.datasets) - 1))
        self._after_dataset_change()
        self.status.setText(f"已移除数据 {idx + 1}。")

    def _dir_hint(self) -> str:
        ds = self.datasets[self.active] if self.datasets else None
        if ds is not None and ds.path:
            return str(Path(ds.path).parent)
        return str(Path.home())

    def _open_source(self, path: str, reset: bool) -> bool:
        """列出文件里的变量并载入第一个。

        ``reset=True`` 替换主数据，``False`` 追加为对比数据。返回是否成功载入。
        """
        if not path or not Path(path).exists():
            self._error("文件不存在", f"找不到 {path}")
            return False
        if not reset and len(self.datasets) >= MAX_DATASETS:
            self._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return False
        try:
            infos = loaders.list_variables(path)
        except LoadError as exc:
            self._error("无法读取文件", str(exc))
            return False
        except Exception as exc:                        # pragma: no cover
            self._error("无法读取文件", f"{type(exc).__name__}: {exc}")
            return False

        self.src_path = path
        p = Path(path)
        self.file_label.setText(f"{p.parent}  ▸  {p.name}")
        self.table.fill(infos)
        self.btn_load.setEnabled(True)
        self.src_info.setText(f"共 {len(infos)} 个可用变量，正在载入第一个…")
        self.status.setText(f"已识别 {len(infos)} 个变量。")
        # 打开即出图：默认载入第一个变量，需要确认轴序时会弹框
        return self.load_variable(infos[0].key, target="reset" if reset else "append")

    def _load_selected_variable(self) -> None:
        info = self.table.current_info()
        if info is not None:
            self.load_variable(info.key)

    def load_variable(self, key: str, target: str | None = None) -> bool:
        """载入 ``key`` 变量。

        ``target`` 为 ``"reset"`` 时替换主数据、``"append"`` 时追加为对比数据、
        ``None``（默认）时替换**当前**数据。返回是否成功。
        """
        if not self.src_path:
            return False
        info = self.table.info_of_key(key)
        if info is None:
            return False
        if len(info.shape) <= 1:
            # 一维/标量：这类变量是采样时间轴、坐标轴、子波之类，
            # 要的是"数值是多少"，直接列表显示，不往体数据里塞。
            return self._show_variable_values(self.src_path, key)
        vol = self._build_variable_vol(self.src_path, key, info)
        if vol is None:
            return False

        if target == "reset":
            return self._install_primary(vol, self.src_path, key)
        if target == "append":
            return self._append_dataset(vol, self.src_path, key)
        return self._replace_active(vol, self.src_path, key)

    def _show_variable_values(self, path: str, key: str) -> bool:
        """一维/标量变量：直接把数值列表显示出来（不进体数据）。"""
        try:
            arr = loaders.load_array(path, key)
        except LoadError as exc:
            self._error("读取失败", str(exc))
            return False
        ArrayViewDialog(f"{Path(path).name}  ▸  {key}", arr, self).exec()
        self.status.setText(f"已查看 {key} 的数值。")
        return True

    def _build_variable_vol(self, path: str, key: str,
                            info=None) -> SeisVolume | None:
        """把 ``path`` 里的 ``key`` 读成规范化 (S,R,T) 体数据（**只读，不装配**）。

        「打开 / 对比 / 替换」三条路径都先经过这里读一次、拿到规范化形状，
        所以拖放导入可以在读完之后、装配之前先问一句"是要对比还是替换"。
        需要确认轴序时会先弹轴序框；取消或出错返回 ``None``。
        """
        if info is None:
            info = self.table.info_of_key(key)
        if info is None:
            return None
        if len(info.shape) <= 1:
            return None
        if len(info.shape) > 3:
            self._error("暂不支持",
                        f"变量 {key} 是 {len(info.shape)} 维，本工具处理一维数值、"
                        "二维剖面或三维体数据（炮点 × 检波器 × 时间）。")
            return None

        fingerprint = f"{loaders.file_fingerprint(path)}:{key}"
        remember = False
        if info.roles:
            # SEG-Y/SU：立方体是按道头现搭的，轴序由构造决定，不必再确认
            roles = list(info.roles)
            self.status.setText(f"已按道头分选出 {key}，正在载入…")
        else:
            initial = loaders.get_axis_memory(fingerprint)
            if initial and len(initial) != len(info.shape):
                initial = None
            answer = ask_axis_order(f"{Path(path).name}  ▸  {key}", info.shape,
                                    initial, self)
            if answer is None:
                self.status.setText("已取消载入。")
                return None
            roles, remember = answer
            if len(roles) != len(info.shape):
                self._error("轴序不完整", "每一个维度都需要指定一个物理含义。")
                return None

        # SEG-Y 的 dt / 道距来自道头；非 SEG-Y 用界面上的当前值做默认
        extra = loaders.load_meta(path, key)
        dt = float(extra.get("dt") or self.spin_dt.value())
        dx = float(extra.get("dx") or self.spin_dx.value())
        ds = float(extra.get("ds") or self.spin_ds.value())

        try:
            arr = loaders.load_array(path, key)
            vol = loaders.build_volume(
                f"{Path(path).stem}·{key}", arr, roles,
                dt=dt, dx=dx, ds=ds, meta=dict(extra.get("meta", {})))
        except LoadError as exc:
            self._error("载入失败", str(exc))
            return None
        except Exception as exc:                        # pragma: no cover
            self._error("载入失败", f"{type(exc).__name__}: {exc}")
            return None

        if remember:
            loaders.set_axis_memory(fingerprint, roles)
        return vol

    def load_sample(self) -> None:
        self.src_path = ""
        self.file_label.setText("内置合成示例（未从文件读取）")
        self.table.fill([])
        self.btn_load.setEnabled(False)
        vol = build_sample_volume()
        self._install_primary(vol, "", "示例")
        self.src_info.setText(
            f"示例数据　{vol.ns} 炮 × {vol.nr} 检波点 × {vol.nt} 采样\n"
            f"dt {vol.dt * 1000:g} ms　4 个反射层 + 2 个绕射点")
        self.status.setText("已载入示例数据。")

    def clear_data(self) -> None:
        """清空已载入的数据，把界面恢复成「刚打开」的样子。

        数据来源、显示设置、切片位置、面板布局、左栏分组全部回到默认。
        **窗口设置**（哪些分组出现在侧边栏、窗口几何）属于"窗口偏好"，这里不动 ——
        那是齿轮里管的事，与"清空数据"不是一回事。
        """
        self._stop()
        self._stop_layout_anim()
        self._stop_all_size_anims()       # 面板/树马上要销毁，别让旧动画继续摸它们
        # 拉出去的浮窗先收回主窗口：否则数据清了，那些窗口还孤零零留在桌面上
        for widget in list(self._detached):
            self._close_detached(widget, silent=True)

        # ---- 数据集合
        # 先把每块面板的图 / 叠加曲线 / 提示线 / 读数显式复位，再移除面板与数据。
        # 只依赖 deleteLater 的话，对比多面板 + 浮窗/缓存的组合下容易留残影。
        for panel in list(self.panels):
            panel.reset_view_state()

        self.datasets = []
        self.active = 0
        self._base_clims = []
        self._clims = []
        self._clim = (-1.0, 1.0)
        self._stats = {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}
        self._panel_cache.clear()
        self._raw_cache.clear()
        self._shared_base_cache = None
        self._face_clim_cache.clear()
        self._pick_undo = None
        # 清空数据 = 回到“刚打开”的状态：用户尺寸锚也要一并清掉，
        # 否则窗口会一直保持清空前那个（可能被对比数据撑大的）尺寸。
        self._user_size = None
        self._window_target = None
        self._overlay_on = False
        self._overlay_sizes = None
        self._is_2d = False
        self._three_auto_closed = False

        # ---- 数据来源
        self.src_path = ""
        self.file_label.setText("尚未打开文件")
        self.table.fill([])
        self.btn_load.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.src_info.setText("等待数据")

        # ---- 显示设置回默认
        self.cmap_combo.setCurrentIndex(2)          # 红蓝（地震惯例）
        self.clim_combo.setCurrentIndex(0)          # 自动
        self.spin_manual.setValue(1.0)
        self.contrast.set_range(10, 1000, 100)
        self._clim_scale = 1.0                      # set_range 不发声，得手动同步内部状态
        self.chk_agc.setChecked(False)
        self.combo_agc.setCurrentIndex(0)
        self.combo_dec.setCurrentIndex(2)
        self.chk_wiggle.setChecked(False)
        self.chk_pure.setChecked(False)
        self.spin_wig.setValue(60)
        self.gain.set_range(10, 250, 100)
        self.chk_sync.setChecked(True)
        self.speed_combo.setCurrentIndex(1)
        self.chk_loop.setChecked(True)
        self.line_styles = list(DEFAULT_LINE_STYLES)
        self._push_line_styles_to_widgets()
        for spin, val in ((self.spin_dt, 0.001), (self.spin_dx, 12.5), (self.spin_ds, 25.0)):
            spin.setValue(val)

        # ---- 切片 / 目标道
        self.mode_ctl.set_enabled_keys({"shot", "recv", "time"})
        self.mode_ctl.set_value("shot")
        self.slice_slider.title.setText(AXIS_TITLES["shot"])
        self.slice_slider.set_range(0, 0, 0)
        self.playhead.set_range(0, 0)
        for spin in (self.spin_ts, self.spin_tr):
            spin.setRange(0, 0)
            spin.setValue(0)
        self.slice_title.setText("剖面")
        self.trace_info.setText("—")
        self.trace_view.clear()
        self._sync_trace_legend(force=True)

        # ---- 面板布局：只开剖面（与刚打开一致），构图回到默认（_default3_key，没配过就是 B）
        self._content_shown = {"slice": True, "trace": False, "right": False}
        self._pair_order = list(pair_layout(("slice", "right"))[2])
        self._layout_preset = self._default3_key or "B"   # _relayout_content 会照着重建 splitter 树
        if self.view3d is not None:
            self.view3d.clear_volume()

        # ---- 左栏分组回到默认（「数据」展开，其余收起）
        self._group_expanded = dict(self.GROUP_DEFAULT)
        self._group_anim_busy = True
        try:
            for key in self.GROUP_ORDER:
                self.cards[key].set_expanded(self.GROUP_DEFAULT[key], animate=False)
        finally:
            self._group_anim_busy = False

        # ---- 统一收尾
        self._rebuild_slice_panels()      # 清掉剖面面板，换回"拖文件进来"的引导
        self._sync_panel_chips()
        self._sync_gated_controls()
        self._sync_compare_controls()
        self._after_group_change(reset_scroll=True)
        # 回到刚打开的窗口尺寸；全屏/最大化时保持窗口状态不变
        if not (self.isFullScreen() or self.isMaximized()):
            w, h = self._default_window_size()
            self._resize_keeping_anchor(w, h)
            self._ensure_on_screen()
        self._relayout_content(animate=True)
        self._update_references()
        self._update_status()
        self.status.setText("已清空数据。可以拖入文件，或点「载入示例」。")

    # ------------------------------------------------------------ 数据集装配
    @staticmethod
    def _default_mode(vol: SeisVolume) -> str:
        """默认落在"成像面积最大"的那一面：二维数据是共炮点面（整幅剖面），
        三维数据也是共炮点面（一个完整炮集），比"第一个可用方向"更自然。"""
        areas = {"shot": vol.nr * vol.nt, "recv": vol.ns * vol.nt,
                 "time": vol.ns * vol.nr}
        return max(areas, key=lambda m: areas[m])

    def _install_primary(self, vol: SeisVolume, path: str, key: str) -> bool:
        """替换整个数据集为这一份数据。"""
        ds = Dataset(vol=vol, path=path, key=key)
        ds.mode = self._default_mode(vol)
        self.datasets = [ds]
        self.active = 0
        self._base_clims = [(-1.0, 1.0)]
        self._recompute_base_clim(0)
        # 刚载入：按数据维度给一次默认排版（二维 → 剖面/单道 上下；三维 → 剖面|三维 左右）
        self._default_view_for(bool(vol.is_single_shot))
        self._is_2d = bool(vol.is_single_shot)
        self._after_dataset_change()          # 收尾里会按新数据重排 + 重算窗口尺寸
        return True

    def _append_dataset(self, vol: SeisVolume, path: str, key: str) -> bool:
        """追加一份对比数据（形状必须与第一份一致）。"""
        if not self.datasets:
            return self._install_primary(vol, path, key)
        base = self.datasets[0].vol
        if tuple(vol.shape) != tuple(base.shape):
            self._error("维度不一致",
                        "对比数据必须与第一份形状相同。\n"
                        f"当前：{base.ns} × {base.nr} × {base.nt}（S × R × T）\n"
                        f"这份：{vol.ns} × {vol.nr} × {vol.nt}")
            return False
        if len(self.datasets) >= MAX_DATASETS:
            self._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return False
        ds = Dataset(vol=vol, path=path, key=key)
        ds.mode = self.datasets[0].mode
        ds.pos = dict(self.datasets[0].pos)
        self.datasets.append(ds)
        self.active = len(self.datasets) - 1
        self._base_clims.append((-1.0, 1.0))
        self._recompute_base_clim(self.active)
        self._after_dataset_change()
        self.status.setText(f"已作为第 {self.active + 1} 份对比数据载入。")
        return True

    def _replace_active(self, vol: SeisVolume, path: str, key: str) -> bool:
        """用新变量替换当前数据；形状一致时保留切片位置。"""
        if not self.datasets:
            return self._install_primary(vol, path, key)
        k = self.active
        old = self.datasets[k]
        ds = Dataset(vol=vol, path=path, key=key)
        if tuple(vol.shape) == tuple(old.vol.shape):
            ds.mode = old.mode
            ds.pos = {"shot": min(old.pos.get("shot", 0), vol.ns - 1),
                      "recv": min(old.pos.get("recv", 0), vol.nr - 1),
                      "time": min(old.pos.get("time", 0), vol.nt - 1)}
        else:
            ds.mode = self._default_mode(vol)
        self.datasets[k] = ds
        self._recompute_base_clim(k)
        self._after_dataset_change()
        return True

    def _after_dataset_change(self) -> None:
        """数据集合发生变化（载入 / 追加 / 移除 / 切换变量）后统一收尾。"""
        self._stop()
        self._rebuild_slice_panels()
        self._sync_panel_chips()           # 剖面块数圆点跟着数据份数走
        self._sync_dimensional_defaults()
        self.mode_ctl.set_enabled_keys({"shot", "recv", "time"})
        self.mode_ctl.set_value(self.mode)
        self.btn_export.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.trace_view.clear()
        if self._content_shown.get("right"):
            self._ensure_view3d()          # 三维数据/三维面板要显示时才建 GL 控件
        if self.view3d is not None:
            self.view3d.set_volume(self.vol)
            self.view3d.focus_face(self.mode, animate=False)
        self._sync_gated_controls()
        self._refresh_all()
        self._update_face_info()
        summary = self.vol.meta.get("summary")     # SEG-Y/SU 带自己的载入摘要
        if summary:
            self.src_info.setText(summary)
        # 数据规模变了 → 三块的自然尺寸与窗口尺寸都要按新数据重算一遍。
        # 窗口尺寸用一次短动画滑过去，避免导入瞬间“跳一下”被看成闪烁。
        self._suppress_window_resize = True
        try:
            self._relayout_content(animate=False)
        finally:
            self._suppress_window_resize = False
        self._animate_layout_change()

    def _default_view_for(self, two_d: bool) -> None:
        """按数据维度给一次**默认排版**。

        二维数据只剩一个竖直面："剖面在上、单道在下"就够了（三维没有必要开），
        先后取"剖面+单道"这一组合的默认。
        三维数据默认**三块全摆出来**，构图取用户配的默认（``_default3_key``，
        没配过就是内置的 B 主+侧+底：上排剖面与三维左右并排、单道在底部通栏）。
        """
        if two_d:
            self._content_shown = {"slice": True, "trace": True, "right": False}
        else:
            self._content_shown = {"slice": True, "trace": True, "right": True}
        self._layout_preset = self._default3_key or "B"
        self._pair_order = list(self._free_pair())   # 三块按默认构图，二维按"剖面+单道"那一对
        self._three_auto_closed = False

    def _sync_dimensional_defaults(self) -> None:
        """二维数据（ns == 1）默认收起三维面板。

        二维体数据只剩一个竖直面，"三维"没有体可看，还会白占一整块。
        只在**数据维度发生变化**时自动切换，而且不覆盖用户自己手动点过的选择；
        换回三维数据时，把上次自动收起的那一次展开回来。
        """
        two_d = bool(self.datasets) and all(d.vol.is_single_shot
                                            for d in self.datasets)
        if two_d == self._is_2d:
            return
        self._is_2d = two_d
        shown = dict(self._content_shown)
        if two_d:
            if not shown.get("right"):
                return
            shown["right"] = False
            if not any(shown.values()):
                shown["slice"] = True
            self._three_auto_closed = True
        elif self._three_auto_closed:
            shown["right"] = True
            self._three_auto_closed = False
        else:
            return
        self._content_shown = shown
        self._sync_layout_for_count()

    def _recompute_base_clim(self, k: int) -> None:
        """重算第 k 份数据的基准色标。

        取三片中位切片做统计，而不是在整卷上跨步采样：惰性（mmap）数据卷上跨步
        采样会把整个文件都翻一遍，等于白惰性了。
        """
        vol = self.datasets[k].vol
        parts = []
        for m in ("shot", "recv", "time"):
            sl = vol.take_slice(m, vol.slice_index_range(m) // 2)
            parts.append(np.asarray(sl, dtype=np.float32).ravel()[::5])
        sample = np.concatenate(parts) if parts else np.zeros(1, np.float32)
        self._base_clims[k] = compute_clim(sample, self.clim_combo.currentData(),
                                          self.spin_manual.value())

    # ============================================================== 导出 / 转换
    def export_volume(self) -> None:
        """导出：整卷数据 / 逐剖面（可范围）/ 当前剖面图片，统一在这一个对话框里。"""
        if not self.datasets:
            self.status.setText("请先打开数据或载入示例，再导出。")
            return
        entries = [{"label": self._dataset_label(k), "vol": ds.vol, "pos": ds.pos}
                   for k, ds in enumerate(self.datasets)]
        active_ds = self.datasets[self.active]
        src = Path(active_ds.path) if active_ds.path else None
        dlg = ExportDialog(entries, self.active,
                           src.parent if src else Path.home(),
                           src.stem if src else "seisview_export", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            self.status.setText("已取消导出。")
            return
        self._run_export(dlg)

    def _run_export(self, dlg) -> None:
        """带进度与取消地跑一次导出。"""
        prog = QtWidgets.QProgressDialog("正在导出…", "取消", 0, 100, self)
        prog.setWindowTitle("导出 / 转换")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)
        # 显示值平滑追赶真实目标：算得出的段给真实百分比，算不出的段（序列化）
        # 停在 99% + 确定性文案。全程只增不减、不跳变。
        chaser = {"shown": 0, "target": 0, "text": ""}

        def tick() -> None:
            shown, target = chaser["shown"], chaser["target"]
            if shown >= target:
                return
            step = max(1, int(np.ceil((target - shown) * 0.25)))
            chaser["shown"] = min(target, shown + step)
            prog.setValue(chaser["shown"])

        timer = QtCore.QTimer(self)
        timer.setInterval(40)
        timer.timeout.connect(tick)
        timer.start()

        def on_progress(frac: float, text: str) -> None:
            pct = int(max(0.0, min(1.0, frac)) * 100)
            chaser["target"] = max(chaser["target"], pct)
            if text != chaser["text"]:
                chaser["text"] = text
                prog.setLabelText(text)
            # 即使百分比没变也要泵事件：序列化写盘期间界面靠这里保持重绘
            QtWidgets.QApplication.processEvents()

        self._stop()
        try:
            content = dlg.content()
            if content in ("slice_image", "wave_image"):
                made = self._export_figures(dlg, on_progress)
                timer.stop()
                prog.setValue(100)
                prog.close()
                self.status.setText(
                    f"已导出波形图 → {made[0]}" if content == "wave_image"
                    else f"已导出 {len(made)} 张剖面图 → {Path(made[0]).parent}")
                return
            if content == "slices":
                made = self._export_slices(dlg, on_progress, prog.wasCanceled)
                timer.stop()
                prog.setValue(100)
                prog.close()
                self.status.setText(
                    f"已逐剖面导出 {len(made)} 个 {exporter.LABEL_OF.get(dlg.fmt(), dlg.fmt())} "
                    f"文件 → {dlg.path()}")
                return
            out = exporter.export(dlg.path(), self.vol.data, dlg.fmt(),
                                  dt_us=dlg.dt_us(), dx=dlg.dx(), ds=dlg.ds(),
                                  with_coords=dlg.with_coords(),
                                  progress=on_progress, cancel=prog.wasCanceled)
        except exporter.ExportError as exc:
            timer.stop()
            prog.close()
            self._error("导出失败", str(exc))
            return
        except Exception as exc:                            # pragma: no cover
            timer.stop()
            prog.close()
            self._error("导出失败", f"{type(exc).__name__}: {exc}")
            return
        timer.stop()
        prog.setValue(100)
        prog.close()
        size = Path(out).stat().st_size
        self.status.setText(
            f"已导出 {exporter.LABEL_OF.get(dlg.fmt(), dlg.fmt())} → {out}"
            f"（{size / 1024 ** 2:.1f} MB）")

    def _export_slices(self, dlg, progress, cancel) -> list[str]:
        """逐剖面导出：按对话框选的数据源 / 方向 / 片层范围逐份写出。"""
        scope_all = dlg.dataset_scope() == "all"
        sel = [k for k in range(len(self.datasets)) if scope_all or k == self.active]
        axis = dlg.slice_axis()
        prefix = dlg.name_prefix()
        multi = len(sel) > 1
        jobs: list[tuple] = []
        for k in sel:
            ds = self.datasets[k]
            if dlg.current_only():
                idx = int(np.clip(ds.pos.get(axis, 0), 0,
                                 ds.vol.slice_index_range(axis) - 1))
                a = b = idx
            else:
                a, b = dlg.slice_range()
                a, b = min(a, b), max(a, b)
            name = prefix if not multi else (f"{prefix}_d{k + 1}" if prefix else f"d{k + 1}")
            jobs.append((ds, a, b, name))
        counts = [max(0, b - a + 1) for _ds, a, b, _n in jobs]
        total = max(1, sum(counts))

        made: list[str] = []
        base_count = 0
        for i, (ds, a, b, name) in enumerate(jobs):
            unit = max(1, counts[i])

            def cb(frac, text, base=base_count, unit=unit, i=i):
                progress((base + max(0.0, min(1.0, frac)) * unit) / total,
                         f"数据 {i + 1}：{text}")

            part = exporter.export_slices(
                dlg.path(), ds.vol.data, dlg.fmt(), mode=axis, name=name,
                start=a, stop=b, progress=cb, cancel=cancel)
            made.extend(part)
            base_count += unit
        return made

    def _figure_labels(self, mode: str) -> tuple[str, str, str]:
        """论文图的坐标轴文字：**带物理单位**，靠设置面板上的 dx / ds / dt 换算。

        返回 ``(横轴, 纵轴, 色条)``。
        """
        if mode == "shot":
            return ("检波器 R (m)", "时间 T (s)", "振幅")
        if mode == "recv":
            return ("炮点 S (m)", "时间 T (s)", "振幅")
        return ("检波器 R (m)", "炮点 S (m)", "振幅")

    def _export_figures(self, dlg, progress) -> list[str]:
        """导出论文用图（白底、物理坐标轴）：剖面图或波形图。"""
        if dlg.content() == "wave_image":
            return [self._export_wave_figure(dlg)]
        return self._export_slice_figures(dlg, progress)

    def _export_slice_figures(self, dlg, progress) -> list[str]:
        """把每份数据的当前剖面重画成一张论文图。

        - 普通模式：灰度 / 红蓝等色标铺满、**不带网格**、右侧带振幅色条；
        - 「仅显示波形」模式：只画波形细线、同样不带网格、坐标轴带物理单位，
          对比时把所有数据源的曲线按各自线型叠在一张图上。
        """
        pure = self.chk_pure.isChecked()
        scope_all = dlg.dataset_scope() == "all"
        sel = [k for k in range(len(self.datasets)) if scope_all or k == self.active]
        if pure and len(self.datasets) > 1:
            sel = list(range(len(self.datasets)))      # 叠加图必然包含全部数据源
        base = Path(dlg.path())
        suffix = ExportDialog.SUFFIX[dlg.fmt()]
        cmap = self.cmap_combo.cmap()
        made: list[str] = []
        # 纯波形 + 对比：所有曲线画进同一张图，不再每份数据各出一张
        overlay = pure and len(sel) > 1
        count = 1 if overlay else max(1, len(sel))
        for i, k in enumerate([0] if overlay else sel):
            ds = self.datasets[k]
            img, clim = self._panel_image(k, full=True)
            xlabel, ylabel, cbar = self._figure_labels(ds.mode)
            invert = ds.vol.is_time_vertical(ds.mode)
            if pure:
                if overlay:
                    if self.chk_norm.isChecked():
                        sets = [self._figure_wiggle_set(j) for j in range(len(self.datasets))]
                    else:
                        shared = max(self._figure_wiggle_set(j)[2]
                                     for j in range(len(self.datasets)))
                        sets = [self._figure_wiggle_set(j, shared)
                                for j in range(len(self.datasets))]
                    labels = [self._dataset_label(j) for j in range(len(self.datasets))]
                else:
                    sets = [self._figure_wiggle_set(k)]
                    labels = [self._dataset_label(k)]
                plot = view2d.build_wiggle_figure(
                    img, ds.vol.extent_of(ds.mode), xlabel, ylabel, sets,
                    n_traces=self.spin_wig.value(),
                    gain=self.gain.value() / 100.0, invert_y=invert,
                    labels=labels)      # 图例写法与单道波形导出图一致
                names = labels[0] if labels else "纯波形"
            else:
                plot = view2d.build_slice_figure(
                    img, ds.vol.extent_of(ds.mode), cmap, clim,
                    xlabel, ylabel, invert_y=invert, colorbar_label=cbar,
                    grid=False)
                names = f"数据 {k + 1}"
            out = (base if count == 1 else
                   base.with_name(f"{base.stem}_d{k + 1}{base.suffix or suffix}"))
            view2d.export_figure(plot, str(out), dlg.fmt(), width=1400)
            plot.close()
            made.append(str(out))
            progress((i + 1) / count, f"绘制第 {i + 1}/{count} 张图：{names}")
        return made

    def _figure_wiggle_set(self, k: int, shared: float | None = None) -> tuple:
        """导出图里用的 wiggle 数据组（全分辨率 + 该数据的色标 + 线型）。"""
        img, clim = self._panel_image(k, full=True)
        scale = float(shared) if shared else (float(np.percentile(np.abs(img), 99)) or 1.0)
        return (img, clim, scale, self.line_styles[k % len(self.line_styles)])

    def _export_wave_figure(self, dlg) -> str:
        """把当前单道波形重画成一张论文图（白底、无网格、坐标轴带单位、带图例）。

        线色/线型用「导出线型」分组的配置（黑实线 / 红实线 / 蓝虚线），
        与屏上的识别色**无关** —— 导出永远是论文那套。
        """
        entries = [(t, amp, self.line_styles[k % len(self.line_styles)], name)
                   for k, (t, amp, _screen_style, name)
                   in enumerate(self._traces()[0])]
        plot = view2d.build_trace_figure(entries, xlabel="时间 T (s)", ylabel="振幅")
        out = str(dlg.path())
        view2d.export_figure(plot, out, dlg.fmt(), width=1200)
        plot.close()
        return out

    # ================================================================== 刷新
    def _refresh_all(self, sync_controls: bool = True) -> None:
        if not self.datasets:
            return
        # 色标缓存与数据份数对齐（载入 / 追加 / 移除之后都从这里归一）
        self._clims = self._clims[:len(self.datasets)]
        while len(self._clims) < len(self.datasets):
            self._clims.append(self._base_clims[len(self._clims)])
        self._panel_cache.clear()          # 每轮刷新重算一次切片，供叠加/统计复用
        self._raw_cache.clear()
        self._shared_base_cache = None
        self._face_clim_cache.clear()
        # 仅显示波形 + 对比时只有第 0 块在画（上面叠了所有数据源的曲线）
        overlay = self.chk_pure.isChecked() and len(self.datasets) > 1
        for k in range(len(self.datasets)):
            if overlay and k > 0:
                continue
            self._refresh_panel(k)
        # 共享色标：即使某一块这轮没重绘（叠层模式），它的导出色标也要跟着一致
        shared = self._scale_window(self._shared_base_clim())
        self._clims = [shared] * len(self.datasets)
        if self.datasets:
            self._clim = self._clims[self.active]
        self._apply_overlay_layout(overlay)
        self._refresh_faces()
        self._refresh_trace()
        if sync_controls:
            self._sync_controls()
        else:
            self.playhead.set_position(self.pos[self.mode])
        self._update_status()
        self._update_group_summaries()

    def _refresh_panel(self, k: int) -> None:
        """画第 k 份数据的剖面；对比时三块共用同一套色标窗口。"""
        ds = self.datasets[k]
        img, clim = self._panel_image(k)
        pure = self.chk_pure.isChecked()
        overlay = pure and len(self.datasets) > 1
        wig_on = self.chk_wiggle.isChecked() or pure

        # 仅显示波形 + 对比：把所有数据源的曲线都画在第 0 块上（叠加），
        # 其余面板让位（见 _apply_overlay_layout）
        sets = None
        if wig_on:
            if overlay:
                if k == 0:
                    sets = self._overlay_sets()
            else:
                sets = [self._wiggle_set(k)]

        xlabel, ylabel, suffix = ds.vol.axis_labels_of(ds.mode, ds.pos[ds.mode])
        self.panels[k].view.set_slice(
            img, ds.vol.extent_of(ds.mode), self.cmap_combo.cmap(), clim,
            xlabel, ylabel,
            full_shape=img.shape,
            wiggle=self.spin_wig.value() if wig_on else 0,
            gain=self.gain.value() / 100.0,
            wiggle_sets=sets, show_image=not pure)
        # 对比面板的小标题带识别色 + 同色小图例，一眼看出这块是哪份数据、
        # 屏上它的曲线是什么颜色（导出用另一套线型，见「导出线型」分组）
        screen_styles = view2d.screen_line_styles(len(self.datasets))
        title_rgb = tuple(QtGui.QColor(
            screen_styles[k % len(screen_styles)][0]).getRgb())
        self.panels[k].set_title(
            f"{ds.vol.name}　{suffix}", title_rgb,
            show=len(self.datasets) > 1,
            line_style=screen_styles[k % len(screen_styles)])
        # 单数据时组内只有一幅：换序抓手隐藏，整块移动统一用上方「剖面」组把手
        self.panels[k].set_reorder_affordance(len(self.datasets) > 1)
        # 记下这一片实际用的色标：导出"论文用图"时要和屏幕上一致
        self._clims[k] = clim
        if k == self.active:
            self._clim = clim
            # 统计量只对抽稀后的图做二次抽样，避免为了一行读数多跑一遍全量数据
            self._stats = stats(np.asarray(img[::4, ::4], dtype=np.float32))
        self._update_reference_panel(k)

    def _agc_window(self, mode: str) -> int | None:
        """当前设置下这一面该用的 AGC 窗口；时间切片没有时间轴，一律 None。"""
        if mode == "time" or not self.chk_agc.isChecked():
            return None
        return int(self.combo_agc.currentData() or 0)

    def _processed_image(self, k: int, full: bool = False):
        """第 k 份数据当前切片 → ``(抽稀/AGC 后的二维数组, 是否施加了 AGC)``。

        只走 ``volume.display_face`` 这一条计算链；面板、wiggle、共享色标、三维
        贴图都从这里取数，禁止在别处再写一份 AGC / 抽稀。
        """
        key = (k, full)
        hit = self._raw_cache.get(key)
        if hit is not None:
            return hit
        ds = self.datasets[k]
        limit = None if full else (self.combo_dec.currentData() or None)
        agc_window = self._agc_window(ds.mode)
        img = display_face(ds.vol, ds.mode, ds.pos[ds.mode],
                           max_side=limit, agc_window=agc_window)
        out = (img, agc_window is not None)
        self._raw_cache[key] = out
        return out

    def _shared_base_clim(self) -> tuple[float, float]:
        """对比模式下三块面板共用的基准色标窗口。

        AGC 开启时按 AGC 后的数据取稳健口径（2%/98%），否则按用户在
        「色标上限」里选的口径；多份数据把样本拼在一起统计，于是三块面板的
        ``中值 ± 半宽`` 完全相同，振幅强弱可以直接比较。
        """
        if self._shared_base_cache is not None:
            return self._shared_base_cache
        if not self.datasets:
            base = (-1.0, 1.0)
        elif len(self.datasets) == 1:
            img, agc_on = self._processed_image(0)
            base = (compute_clim(img, "robust") if agc_on
                    else self._base_clims[0])
        else:
            imgs, agc_any = [], False
            for k in range(len(self.datasets)):
                img, agc_on = self._processed_image(k)
                imgs.append(img)
                agc_any = agc_any or agc_on
            base = shared_clim(
                imgs,
                "robust" if agc_any else self.clim_combo.currentData(),
                self.spin_manual.value())
        self._shared_base_cache = base
        return base

    def _scale_window(self, base: tuple[float, float]) -> tuple[float, float]:
        """把基准窗口按对比度围绕中点对称缩放。"""
        lo, hi = base
        mid = 0.5 * (lo + hi)
        half = max(1e-12, 0.5 * (hi - lo) * self._clim_scale)
        return (mid - half, mid + half)

    def _panel_image(self, k: int, full: bool = False):
        """第 k 份数据当前切片 → ``(显示用数组, 全体共享的色标窗口)``。

        面板显示、wiggle 叠加、导出的论文图都走这一个入口，保证"看到的"和"导出的"
        用的是同一套 AGC / 抽稀 / 色标口径。``full=True`` 时不抽稀（导出图要细节），
        但色标仍与屏幕上的共享窗口一致。
        """
        key = (k, full)
        hit = self._panel_cache.get(key)
        if hit is not None:
            return hit
        img, _agc_on = self._processed_image(k, full)
        clim = self._scale_window(self._shared_base_clim())
        if not full:
            self._panel_cache[key] = (img, clim)
        return img, clim

    def _clim_for_face(self, mode: str) -> tuple[float, float]:
        """三维里**非当前**两个面的色标：同样按共享窗口的口径逐面重算。"""
        if self.datasets and mode == self.mode and self.active < len(self._clims):
            return self._clims[self.active]
        limit = self.combo_dec.currentData() or None
        agc_window = self._agc_window(mode)
        key = (mode,
               tuple(ds.pos[mode] for ds in self.datasets),
               agc_window, self.clim_combo.currentData(),
               float(self.spin_manual.value()), float(self._clim_scale))
        hit = self._face_clim_cache.get(key)
        if hit is not None:
            return hit
        imgs = [display_face(ds.vol, mode, ds.pos[mode],
                             max_side=limit, agc_window=agc_window)
                for ds in self.datasets]
        base = shared_clim(
            imgs,
            "robust" if agc_window is not None else self.clim_combo.currentData(),
            self.spin_manual.value())
        clim = self._scale_window(base)
        if len(self._face_clim_cache) > 48:
            self._face_clim_cache.clear()
        self._face_clim_cache[key] = clim
        return clim

    def _wiggle_set(self, k: int, shared: float | None = None) -> tuple:
        """第 k 份数据在剖面上叠加用的 wiggle 数据组（**屏幕用**）。

        ``(切片, 色标, 幅度分母, (颜色, 线型))``。分母按"能看清"来定：默认取该数据
        自身的 P99（稳健幅度，避免一个极值把整幅波形压平）；``shared`` 是"不归一化"
        时全体共用的分母 —— 这时各数据源的大小关系是真实的，可以比振幅强弱。
        颜色取屏幕调色板（数据识别色），与单道波形面板、面板标题三处一致。
        """
        img, clim = self._panel_image(k)
        scale = float(shared) if shared else (float(np.percentile(np.abs(img), 99)) or 1.0)
        styles = view2d.screen_line_styles(len(self.datasets))
        return (img, clim, scale, styles[k % len(styles)])

    def _overlay_sets(self) -> list:
        """对比叠加（仅显示波形）时的一组 wiggle：按「按峰值归一化」开关决定分母。

        勾选：各数据源各自归一到自己的稳健幅度（形态最容易对齐）；
        取消：全体共用一个分母（保留绝对幅度差，能比噪声强度）。
        """
        n = len(self.datasets)
        if self.chk_norm.isChecked():
            return [self._wiggle_set(j) for j in range(n)]
        shared = max(self._wiggle_set(j)[2] for j in range(n))
        return [self._wiggle_set(j, shared) for j in range(n)]

    def _update_references(self) -> None:
        # 清空数据时面板是先于 datasets 移除的，期间索引必须按两者较小值来走
        for k in range(min(len(self.panels), len(self.datasets))):
            self._update_reference_panel(k)

    def _update_reference_panel(self, k: int) -> None:
        """在第 k 块剖面上标出它的单道波形取自哪一炮哪一道。

        横轴对应哪个物理量取决于切片模式：共炮点面横轴是检波器、共检波点面是
        炮点。弄错就会把线画到别的轴上去（前几版那根"莫名其妙的绿线"就是把
        x 值喂给了横线、又用错了轴）。

        时间切片上**不画**：它是 (炮号, 道号) 索引平面而不是剖面，标"第几道"
        没有物理意义。单道面板看不见时也不画，免得指向一个看不见的面板 ——
        "看不见"既包括在主窗口里被收起，也包括波形区已被拉到独立窗口（那时它
        仍然看得见，提示线就该留着）。
        """
        if k >= len(self.panels):
            return
        if k >= len(self.datasets):
            self.panels[k].view.set_reference(None)
            return
        panel = self.panels[k]
        ds = self.datasets[k]
        vol, mode = ds.vol, ds.mode
        trace_visible = self._effective_shown()["trace"]
        if mode == "time" or not trace_visible:
            panel.view.set_reference(None)
            return
        if mode == "shot":          # 共炮点面：横轴是检波器
            idx, total = ds.pos["recv"], vol.nr
        else:                       # 共检波点面：横轴是炮点
            idx, total = ds.pos["shot"], vol.ns
        x0, x1, _y0, _y1 = vol.extent_of(mode)
        frac = idx / max(1, total - 1)
        s = min(max(ds.pos["shot"], 0), vol.ns - 1)
        r = min(max(ds.pos["recv"], 0), vol.nr - 1)
        panel.view.set_reference(x0 + (x1 - x0) * frac, f"S={s}  R={r}")

    def _refresh_faces(self) -> None:
        """三维三个面：当前面的数组与二维面板**同源**，另外两面按同一口径算。"""
        if not self.datasets:
            return
        if self.view3d is None:
            if self._content_shown.get("right"):
                self._ensure_view3d()
            if self.view3d is None:
                return
        ds = self.datasets[self.active]
        limit = self.combo_dec.currentData() or None
        faces: dict[str, tuple[np.ndarray, tuple[float, float]]] = {}
        for mode in ("shot", "recv", "time"):
            if mode == ds.mode:
                # **直接复用**二维面板这一轮的数组与色标：max|diff| 必须为 0
                img, clim = self._panel_image(self.active)
            else:
                img = display_face(ds.vol, mode, ds.pos[mode],
                                   max_side=limit, agc_window=self._agc_window(mode))
                clim = self._clim_for_face(mode)
            faces[mode] = (img, clim)
        self.view3d.update_faces(self.pos["shot"], self.pos["recv"], self.pos["time"],
                                 faces, self.cmap_combo.cmap())
        self._update_face_info()

    def _traces(self) -> tuple[list, list, tuple[int, int]]:
        """每个数据源一条道：返回 ``(叠加曲线, 各道峰值, 当前数据的 (S, R))``。

        曲线数据是 ``(时间, 显示用振幅, (颜色, 线型), 名称)``。是否按峰值归一化由
        「按峰值归一化」开关决定 —— 打开时形态最易对齐，关闭时保留绝对振幅差。
        """
        normalize = self.chk_norm.isChecked()
        # 屏上按"数据识别色"上色；导出的白底论文图另走 line_styles（见 _export_*）
        screen_styles = view2d.screen_line_styles(len(self.datasets))
        traces, peaks = [], []
        sr = (0, 0)
        for k, ds in enumerate(self.datasets):
            vol = ds.vol
            s = min(max(ds.pos["shot"], 0), vol.ns - 1)
            r = min(max(ds.pos["recv"], 0), vol.nr - 1)
            amp = np.asarray(vol.take_trace(s, r), dtype=np.float32)
            t = np.arange(vol.nt) * vol.dt
            peak = float(np.max(np.abs(amp))) or 1.0
            traces.append((t, amp / (peak if normalize else 1.0),
                           screen_styles[k % len(screen_styles)],
                           self._dataset_label(k)))
            peaks.append(peak)
            if k == self.active:
                sr = (s, r)
        return traces, peaks, sr

    def _sync_trace_legend(self, force: bool = False) -> None:
        """标题行右侧的紧凑图例：小色条 + 数据序号，只有对比模式才显示。

        屏上不再画那块的 pyqtgraph 大图例（它会盖住波形）；导出的论文图仍由
        ``view2d.build_*_figure`` 带完整图例。
        """
        if not hasattr(self, "trace_legend"):
            return
        key = (len(self.datasets), self._theme_key)
        if not force and key == self._trace_legend_key:
            return
        self._trace_legend_key = key
        lay = self._trace_legend_lay
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if len(self.datasets) <= 1:
            self.trace_legend.setVisible(False)
            return
        styles = view2d.screen_line_styles(len(self.datasets))
        for k, (color, _dash) in enumerate(styles):
            swatch = QtWidgets.QLabel()
            swatch.setFixedSize(18, 10)
            swatch.setPixmap(view2d.line_swatch_pixmap((color, "solid"), 18, 10))
            lay.addWidget(swatch)
            name = QtWidgets.QLabel(f"数据{k + 1}")
            name.setStyleSheet(f"color: {color}; font-size: 11px;")
            lay.addWidget(name)
        self.trace_legend.setVisible(True)

    def _refresh_trace(self) -> None:
        """单道波形：每份数据一条曲线，用**屏幕调色板**（数据识别色）叠加。"""
        if not self.datasets:
            return
        traces, peaks, (s, r) = self._traces()
        self.trace_view.set_traces(traces)
        self._sync_trace_legend()
        if len(self.datasets) > 1:
            self.trace_info.setText(
                f"叠加 {len(self.datasets)} 条　当前 数据{self.active + 1}"
                f"  S={s}  R={r}  峰值 {peaks[self.active]:.3g}")
        else:
            self.trace_info.setText(f"S={s}  R={r}  峰值 {peaks[0]:.3g}")

    def _sync_controls(self) -> None:
        """让左侧各控件与**当前数据**的状态对齐（全部屏蔽信号，避免循环触发）。"""
        if not self.datasets:
            return
        vol = self.vol
        mode = self.mode
        count = vol.slice_index_range(mode)
        self.slice_slider.title.setText(AXIS_TITLES[mode])
        self.slice_slider.configure(count - 1, self.pos[mode], f"　/{count - 1}")
        self.playhead.set_range(count, self.pos[mode])
        _x, _y, suffix = vol.axis_labels_of(mode, self.pos[mode])
        self.slice_title.setText(f"剖面　{suffix}")

        for spin, val in ((self.spin_dt, vol.dt), (self.spin_dx, vol.dx),
                          (self.spin_ds, vol.ds)):
            spin.blockSignals(True)
            spin.setValue(float(val))
            spin.blockSignals(False)

        s = min(max(self.pos["shot"], 0), vol.ns - 1)
        r = min(max(self.pos["recv"], 0), vol.nr - 1)
        for spin, hi, val in ((self.spin_ts, vol.ns - 1, s), (self.spin_tr, vol.nr - 1, r)):
            spin.blockSignals(True)
            spin.setRange(0, max(0, int(hi)))
            spin.setValue(int(val))
            spin.blockSignals(False)

        self._sync_compare_controls()

    def _dataset_label(self, k: int) -> str:
        ds = self.datasets[k]
        return f"数据 {k + 1}　{ds.vol.name}" if len(self.datasets) > 1 else ds.vol.name

    def _sync_compare_controls(self) -> None:
        """同步「多数据对比」卡片（数据源下拉、按钮与依赖开关的可用性）。"""
        n = len(self.datasets)
        self.dataset_combo.blockSignals(True)
        self.dataset_combo.clear()
        for k in range(n):
            self.dataset_combo.addItem(self._dataset_label(k), k)
        self.dataset_combo.setCurrentIndex(max(0, min(self.active, n - 1)))
        self.dataset_combo.blockSignals(False)
        self.chk_sync.setEnabled(n > 1)
        self.btn_add.setEnabled(n < MAX_DATASETS)
        self.btn_remove.setEnabled(n > 1)
        self.spin_ts.setEnabled(n > 0)
        self.spin_tr.setEnabled(n > 0)
        # 两行文字固定行数，避免载入 / 移除对比数据时整张卡片高度跳一下
        if n > 1:
            self.compare_info.setText(
                f"已载入 {n} / {MAX_DATASETS} 份同形状数据。\n"
                + ("剖面与目标道已同步。" if self.chk_sync.isChecked()
                   else "各数据源独立调节。"))
        else:
            self.compare_info.setText(
                f"已载入 1 / {MAX_DATASETS} 份同形状数据。\n"
                "点「＋ 添加对比数据」或直接拖文件进来。")

    def _update_status(self) -> None:
        if not self.datasets:
            self.status.setText("就绪。点击「载入示例」可立即看到效果，或把文件拖进来。")
            self.stats_label.setText("")
            return
        vol = self.vol
        mode = self.mode
        s, r, t = self.pos["shot"], self.pos["recv"], self.pos["time"]
        info = self._stats
        prefix = f"数据{self.active + 1}｜" if len(self.datasets) > 1 else ""
        self.status.setText(
            f"{prefix}{SLICE_LABELS[mode]} {self.pos[mode]}/{vol.slice_index_range(mode) - 1}"
            f"　|　S={s}  R={r}  T={t * vol.dt:.3f} s"
            f"　|　时间 {vol.nt * vol.dt:.2f} s　空间 {vol.nr * vol.dx:.0f} m")
        # 三个读数都按固定宽度右对齐：等宽字体下这样每帧占的位置一样，
        # 数值长度变化不会让状态栏里的文字左右挪动（AGC 一开这几个数就全变了）。
        self.stats_label.setText(
            f"min {info['min']:>+8.3g}   max {info['max']:>+8.3g}   rms {info['rms']:>+8.3g}")

    def _update_face_info(self) -> None:
        """三维标题行右侧的一行紧凑读数；长说明放在 tooltip 里（不占布局高度）。

        原来那四行说明有三行与状态栏重复（状态栏已经报了 S/R/T），而底部又摆了
        一行"定位到面"的提示 + 三个按钮 —— 全是冗余：在三维面上点一下、或在左栏
        选切片方向本来就会切到那一面。这里只留"当前在哪一面、序号与物理量"。
        """
        vol = self.vol
        if vol is None:
            self.face_info.setText("--")
            self.face_info.setToolTip("载入数据后可在这里看到当前所在的面。")
            return
        mode = self.mode
        s, r, t = self.pos["shot"], self.pos["recv"], self.pos["time"]
        head = f"数据 {self.active + 1}（{vol.name}）\n" if len(self.datasets) > 1 else ""
        self.face_info.setText(
            f"{SLICE_LABELS[mode]} {self.pos[mode]}／{vol.slice_index_range(mode) - 1}")
        self.face_info.setToolTip(
            head
            + f"共炮点面  S={s}  ({s * vol.ds:.0f} m)\n"
            f"共检波点面  R={r}  ({r * vol.dx:.0f} m)\n"
            f"时间切片  T={t}  ({t * vol.dt:.3f} s)\n"
            "三维与剖面、单道波形一致：时间向下增大；各轴按长度归一化显示。\n"
            "（换面的方式：在三维体上点某一面，或在上面的「剖切与播放」里选方向）")

    # ================================================================== 交互
    def _on_variable_selected(self) -> None:
        info = self.table.current_info()
        if info is not None:
            self.status.setText(
                f"已选中 {info.key}　形状 {' × '.join(str(v) for v in info.shape)}　"
                f"{info.dtype}　{info.size_text}")

    def _on_active_changed(self, index: int) -> None:
        """切换当前数据：三维面板、左侧设置、波形都跟着这份数据走。"""
        if not self.datasets or not (0 <= index < len(self.datasets)):
            return
        self.active = int(index)
        self.mode_ctl.set_value(self.mode)
        if self._content_shown.get("right"):
            self._ensure_view3d()
        if self.view3d is not None:
            self.view3d.set_volume(self.vol)
            self.view3d.focus_face(self.mode, animate=False)
        self._sync_gated_controls()          # 各数据源模式可能不同 → AGC 可用性跟着变
        self._refresh_all()
        self._update_face_info()

    def _on_sync_toggle(self, checked: bool) -> None:
        """打开同步时，把当前数据的选择一次性广播给其余数据。"""
        if checked and self.datasets:
            src = self.datasets[self.active]
            for k, ds in enumerate(self.datasets):
                if k == self.active:
                    continue
                ds.mode = src.mode
                ds.pos = {"shot": min(src.pos["shot"], ds.vol.ns - 1),
                          "recv": min(src.pos["recv"], ds.vol.nr - 1),
                          "time": min(src.pos["time"], ds.vol.nt - 1)}
            self.status.setText("已把当前数据的剖面参数同步到其余数据。")
        self._sync_compare_controls()
        self._sync_gated_controls()
        if self.datasets:
            self._refresh_all()

    def _on_mode(self, key: str) -> None:
        if not self.datasets or key not in self.pos:
            return
        self.mode = key
        if self.chk_sync.isChecked():
            for ds in self.datasets:
                ds.mode = key
        self._sync_gated_controls()      # 时间切片要把 AGC 置灰
        self._refresh_all()
        if self._content_shown.get("right"):
            self._ensure_view3d()
        if self.view3d is not None:
            self.view3d.focus_face(key)

    def _on_slice_index(self, value: int) -> None:
        """切片位置变化。滑杆与播放头都会调用这里，因此必须能安全地双向同步。"""
        if not self.datasets:
            return
        ds = self.datasets[self.active]
        n = ds.vol.slice_index_range(ds.mode)
        new = int(np.clip(value, 0, n - 1))
        changed = new != ds.pos[ds.mode]
        ds.pos[ds.mode] = new
        if changed and self.chk_sync.isChecked():
            for other in self.datasets:
                if other is ds:
                    continue
                m = other.vol.slice_index_range(other.mode)
                other.pos[other.mode] = int(np.clip(new, 0, m - 1))
        if changed:
            self._refresh_all(sync_controls=False)
        else:
            self.playhead.set_position(new)
        if self.slice_slider.value() != new:      # 来自播放头时才需要回写滑杆
            self.slice_slider.set_value(new)

    def _step(self, delta: int) -> None:
        if not self.datasets:
            return
        n = self.vol.slice_index_range(self.mode)
        self._on_slice_index((self.pos[self.mode] + delta) % n)

    def _apply_scales(self) -> None:
        """dt / dx / ds 改完立刻生效，并同步到所有对比数据（标尺要一致才好比较）。"""
        if not self.datasets:
            return
        dt = float(self.spin_dt.value())
        dx = float(self.spin_dx.value())
        ds = float(self.spin_ds.value())
        if all((dt, dx, ds) == (d.vol.dt, d.vol.dx, d.vol.ds) for d in self.datasets):
            return
        for d in self.datasets:
            d.vol.dt, d.vol.dx, d.vol.ds = dt, dx, ds
        self._refresh_all(sync_controls=False)
        self.status.setText(f"标尺已更新：dt {dt:g} s　dx {dx:g} m　ds {ds:g} m")

    def _on_cmap(self) -> None:
        self._refresh_all()

    def _on_clim_mode(self) -> None:
        self._sync_gated_controls()
        if self.datasets:
            for k in range(len(self.datasets)):
                self._recompute_base_clim(k)
            self._refresh_all()

    def _on_contrast(self, value: int) -> None:
        # 方向：数值越大 → 半窗宽越小 → 裁掉的样点越多、画面越「硬」。
        # 也就是 200% 表示窗口减半、对比度翻倍，和滑块名字一致。
        self._clim_scale = 100.0 / max(1, int(value))
        if self.datasets:
            self._refresh_all(sync_controls=False)

    def _on_target_sr(self) -> None:
        """设置面板里的目标道号：改一处即改单道波形取自哪一道。

        同步打开时广播到所有对比数据；因为共炮点/共检波点面里"炮号 / 道号"
        本身就是切片下标，所以这里也顺带把剖面切到对应位置。
        """
        if not self.datasets:
            return
        s = int(self.spin_ts.value())
        r = int(self.spin_tr.value())
        for k, ds in enumerate(self.datasets):
            if k != self.active and not self.chk_sync.isChecked():
                continue
            ds.pos["shot"] = int(np.clip(s, 0, ds.vol.ns - 1))
            ds.pos["recv"] = int(np.clip(r, 0, ds.vol.nr - 1))
        self._refresh_all()

    def _on_pick(self, k: int, col: int, row: int) -> None:
        """剖面点击 → 把位置传给另外两个轴，并更新单道波形。

        多数据对比时，被点的那块升为当前数据；同步打开时把点击位置的物理道
        同步给所有数据源（"对比模式下同步更改所有数据显示的道"）。
        """
        if not self.datasets or not (0 <= k < len(self.datasets)):
            return
        # 双击复位的第一次 release 也会走到这里：先留一份撤销快照，双击时还原
        self._pick_undo = {
            "slot": k,
            "t": time.monotonic(),
            "active": self.active,
            "pos": [dict(d.pos) for d in self.datasets],
        }
        self.active = k
        ds = self.datasets[k]
        vol, mode = ds.vol, ds.mode

        def apply(target: Dataset, tcol: int, trow: int) -> None:
            tv = target.vol
            if mode == "shot":        # 固定 S，横轴 R、纵轴 T
                target.pos["recv"] = int(np.clip(tcol, 0, tv.nr - 1))
                target.pos["time"] = int(np.clip(trow, 0, tv.nt - 1))
            elif mode == "recv":      # 固定 R，横轴 S、纵轴 T
                target.pos["shot"] = int(np.clip(tcol, 0, tv.ns - 1))
                target.pos["time"] = int(np.clip(trow, 0, tv.nt - 1))
            else:                     # 固定 T，横轴 R、纵轴 S
                target.pos["recv"] = int(np.clip(tcol, 0, tv.nr - 1))
                target.pos["shot"] = int(np.clip(trow, 0, tv.ns - 1))

        apply(ds, col, row)
        if self.chk_sync.isChecked():
            for other in self.datasets:
                if other is not ds:
                    apply(other, col, row)
        self._refresh_faces()
        self._refresh_trace()
        self._update_references()
        self._sync_controls()
        self._update_status()

    def _on_view_double_click(self, slot: int) -> None:
        """双击复位视野：把双击手势里第一次 release 造成的取道撤回去。

        双击在 Qt 里是 ``press → release → dblclick → release``，第一个 release
        已经发过 ``picked``。若不在双击时还原，绿线与单道波形会留在双击点，
        看起来就像"复位把绿线挪走了"。
        """
        undo, self._pick_undo = self._pick_undo, None
        if undo is None or undo["slot"] != slot:
            return
        limit = (QtWidgets.QApplication.doubleClickInterval() / 1000.0) * 1.5
        if time.monotonic() - undo["t"] > limit:
            return
        if len(undo["pos"]) != len(self.datasets):
            return
        for ds, pos in zip(self.datasets, undo["pos"]):
            ds.pos = dict(pos)
        self.active = min(max(undo["active"], 0), len(self.datasets) - 1)
        self._refresh_all()
        self._update_face_info()

    def _on_hover(self, k: int, col: int, row: int) -> None:
        if not (0 <= k < len(self.datasets)) or k >= len(self.panels):
            return
        ds = self.datasets[k]
        vol, mode = ds.vol, ds.mode
        if mode == "shot":
            text = f"R={col} ({col * vol.dx:.1f} m)　T={row} ({row * vol.dt:.3f} s)"
        elif mode == "recv":
            text = f"S={col} ({col * vol.ds:.1f} m)　T={row} ({row * vol.dt:.3f} s)"
        else:
            text = f"R={col} ({col * vol.dx:.1f} m)　S={row} ({row * vol.ds:.1f} m)"
        self.panels[k].set_hover(text)

    def _focus_face(self, key: str) -> None:
        """切到某个面的切片模式，并把三维相机转到正视该面的方位。"""
        if not self.datasets:
            return
        self.mode_ctl.set_value(key)
        self._on_mode(key)

    # ================================================================== 播放
    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._stop()
        elif self.datasets:
            self._timer.start(int(self.speed_combo.currentData()))
            self.btn_play.setText("⏸  暂停")

    def _stop(self) -> None:
        self._timer.stop()
        self.btn_play.setText("▶  播放")

    def _on_speed(self) -> None:
        """播放中改速度立刻生效。

        定时器只有在 start() 那一刻取一次间隔，之后下拉框怎么变它都不管 ——
        所以播放中改挡位原先毫无反应，得手动把新间隔塞回去。
        没在播放时不用动：下次 start 会读新值。
        """
        if self._timer.isActive():
            self._timer.setInterval(int(self.speed_combo.currentData()))

    def _tick(self) -> None:
        if not self.datasets:
            return
        n = self.vol.slice_index_range(self.mode)
        nxt = self.pos[self.mode] + 1
        if nxt >= n:
            if not self.chk_loop.isChecked():
                self._stop()
                return
            nxt = 0
        self._on_slice_index(nxt)

    # ============================================================== 拖放导入
    def dragEnterEvent(self, ev) -> None:               # noqa: N802 （Qt 接口名）
        if self._import_busy:
            ev.ignore()          # 上一次导入（弹框 / 读文件）还没结束：忽略后续拖放
            return
        if ev.mimeData().hasUrls() and any(
                self._is_supported(u.toLocalFile()) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:                # noqa: N802 （Qt 接口名）
        if ev.mimeData().hasUrls() and not self._import_busy:
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        """拖入文件即导入。

        拖一个文件 = 打开；一次拖多个 = 依次导入（第一个照流程走，后面同形状的
        自动作为对比数据追加）。

        **载入动作要推迟一帧再做**：拖放事件此时还压在 Windows 的拖放循环里没退干净，
        若在这里直接弹模态框（轴序 / 意图确认），会把整个桌面的拖放输入一起冻住 ——
        表现就是"连资源管理器窗口都拖不动了"。``singleShot(0)`` 让 dropEvent 先返回，
        拖放循环彻底结束，再开始读文件 / 弹框。
        """
        if self._import_busy:
            ev.ignore()
            return
        paths = [u.toLocalFile() for u in ev.mimeData().urls()]
        paths = [p for p in paths if self._is_supported(p)]
        if not paths:
            return                      # 不支持的类型：保持原有的"静默忽略"，不弹意图框
        ev.acceptProposedAction()
        QtCore.QTimer.singleShot(0, lambda items=list(paths): self._import_paths(items))

    def _import_paths(self, paths: list[str]) -> None:
        """按顺序导入一组拖入的文件（每次成功/取消都更新状态栏）。"""
        if not paths:
            return
        # 扫掠播放中先停表：导入会改变切片位置，边播边载必然错乱
        if self._timer.isActive():
            self._stop()
            self.status.setText("已在导入前停止扫掠播放。")
        self._import_busy = True
        try:
            for i, path in enumerate(paths):
                if not self._import_one(path, first=(i == 0)):
                    break
        finally:
            self._import_busy = False

    def _import_one(self, path: str, first: bool = False) -> bool:
        """导入单个文件：读变量 → 拿到规范化形状 → （有数据时）问对比还是替换 → 装配。"""
        if not path or not Path(path).exists():
            self._error("文件不存在", f"找不到 {path}")
            return False
        try:
            infos = loaders.list_variables(path)
        except LoadError as exc:
            self._error("无法读取文件", str(exc))
            return False
        except Exception as exc:                        # pragma: no cover
            self._error("无法读取文件", f"{type(exc).__name__}: {exc}")
            return False
        if not infos:
            self._error("没有可用变量", f"{Path(path).name} 里没有可载入的变量。")
            return False

        p = Path(path)
        self.src_path = path
        self.file_label.setText(f"{p.parent}  ▸  {p.name}")
        self.table.fill(infos)
        self.btn_load.setEnabled(True)
        self.src_info.setText(f"共 {len(infos)} 个可用变量。")
        info = infos[0]
        if len(info.shape) <= 1:
            return self._show_variable_values(path, info.key)   # 一维变量：看数值

        vol = self._build_variable_vol(path, info.key, info)
        if vol is None:
            return False
        if not self.datasets:
            # 没有数据：直接载入，不弹意图框
            return self._install_primary(vol, path, info.key)

        intent = self._ask_import_intent(vol, path, first=first)
        if intent == "compare":
            return self._append_dataset(vol, path, info.key)
        if intent == "replace":
            return self._apply_replace(vol, path, info.key)
        self.status.setText("已取消导入。")
        return False

    @staticmethod
    def _shape_text(vol: SeisVolume) -> str:
        return f"{vol.ns} × {vol.nr} × {vol.nt}（S × R × T）"

    def _ask_import_intent(self, vol: SeisVolume, path: str,
                           first: bool = False) -> str | None:
        """有数据时问一句：与当前数据**对比**还是**替换**。返回 ``"compare"`` /
        ``"replace"`` / ``None``（取消）。

        一次拖多个文件时，第一个照流程问；后续只要形状一致且还没到上限，就直接
        追加为对比数据 —— 不必为同一批文件重复点"对比"。
        """
        base = self.datasets[0].vol
        same = tuple(vol.shape) == tuple(base.shape)
        if not first and same and len(self.datasets) < MAX_DATASETS:
            self.status.setText("形状与当前数据一致，已自动追加为对比数据。")
            return "compare"
        blocked = same and len(self.datasets) >= MAX_DATASETS
        norm = os.path.normcase(os.path.abspath(path))
        dup = any(d.path and os.path.normcase(os.path.abspath(d.path)) == norm
                  for d in self.datasets)
        dlg = ImportIntentDialog(
            Path(path).name, self._shape_text(vol), self._shape_text(base),
            allow_compare=same and not blocked,
            compare_blocked=blocked,
            dup_warning="注意：这个文件之前已经载入过了。" if dup and not blocked else "",
            parent=self)
        dlg.exec()
        return dlg.choice

    def _apply_replace(self, vol: SeisVolume, path: str, key: str) -> bool:
        """「替换」的落地：单份时替换它，对比模式下替换当前激活的那一份。

        形状与当前激活的一份相同 → 沿用它的切片位置与模式（``_replace_active``）；
        不同 → 当作换了一份新数据，重新给默认模式并让窗口自适应（``_install_primary``）。
        """
        if len(self.datasets) <= 1:
            if tuple(vol.shape) == tuple(self.datasets[0].vol.shape):
                return self._replace_active(vol, path, key)
            return self._install_primary(vol, path, key)
        return self._replace_active(vol, path, key)

    @staticmethod
    def _is_supported(path: str) -> bool:
        return bool(path) and Path(path).suffix.lower() in loaders.SUPPORTED_SUFFIXES

    # ================================================================== 杂项
    def _error(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, message)
        self.status.setText(f"{title}：{message}")

    def closeEvent(self, ev) -> None:
        self._stop()
        self._save_ui_state()          # 记住左栏状态，下次启动照着还原
        # 先把拉出去的面板收回主窗口：否则它们归独立窗口（主窗口的子对象）所有，
        # 关窗时被连带销毁，面板的父子关系会处于半清理状态。
        for widget in list(self._detached):
            self._close_detached(widget, silent=True)
        super().closeEvent(ev)
