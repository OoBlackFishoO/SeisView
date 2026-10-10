"""主窗口：把读取、切片、三维与显示参数装配成一条完整工作流。

交互主线
--------
打开文件 → 选变量 → 确认轴序 → 体数据入位：
三维面板先给整体印象，切片面板给剖面细节，波形面板给单道细节；
在三维面上点一下或在剖面上点一下，都能把当前 (S, R, T) 位置传下去。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import loaders, style, view3d
from .loaders import LoadError
from .sample import build_sample_volume
from .view2d import SliceView
from .volume import (SLICE_LABELS, SeisVolume, agc, compute_clim, decimate, stats)
from .widgets import (ArrayViewDialog, ChevronButton, ColormapCombo, PlayheadTrack,
                      SectionLabel, SegmentedControl, SliderRow, ValueLabel,
                      VariableTable, ask_axis_order, make_panel)

# 扫掠速度：显示名 → 定时器间隔 (ms)
SPEEDS = [("慢", 150), ("中", 70), ("快", 35), ("极快", 16)]
# 抽稀上限：显示名 → 每边最多像素（0 表示不抽稀）
DOWNSAMPLE = [("不抽稀", 0), ("4096", 4096), ("2048", 2048), ("1024", 1024), ("512", 512)]
CLIM_MODES = [("自动", "auto"), ("稳健", "robust"), ("手动", "manual")]
# 叠加波形颜色：底色随色标变化很大，单一白色在浅底（红蓝/彩虹）上几乎看不见，
# 所以给几个可直接切换的选项，默认用地震剖面惯用的黑色。
WIGGLE_COLORS = [
    ("黑", (10, 12, 16, 210)),
    ("白", (255, 255, 255, 220)),
    ("青", (56, 189, 248, 235)),
    ("黄", (250, 204, 21, 235)),
]
AXIS_TITLES = {"shot": "炮点 S", "recv": "检波器 R", "time": "时间 T"}


class TraceView(QtWidgets.QWidget):
    """单道波形绘图区：横轴振幅、纵轴时间（向下增大），与剖面方向一致。

    标题栏不在这里 —— 它由主窗口放在面板层，这样折叠时可以只收起绘图区，
    标题栏（连同折叠按钮）保留在面板顶部。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.plot = pg.PlotWidget(background=style.GL_BG)
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.setMinimumHeight(120)
        vb = self.plot.getViewBox()
        vb.setDefaultPadding(0.02)
        vb.invertY(True)
        self.plot.setLabel("bottom", "振幅")
        self.plot.setLabel("left", "时间 T (s)")
        self.curve = self.plot.plot(pen=pg.mkPen(style.ACCENT, width=1))
        self._zero = pg.InfiniteLine(pos=0.0, angle=90, movable=False,
                                     pen=pg.mkPen(style.LINE_HI, width=1))
        self.plot.addItem(self._zero, ignoreBounds=True)
        lay.addWidget(self.plot)

    def set_trace(self, t: np.ndarray, amp: np.ndarray) -> None:
        self.curve.setData(amp, t)

    def clear(self) -> None:
        self.curve.setData([], [])


class MainWindow(QtWidgets.QMainWindow):
    # 期望尺寸 / 可接受的最小尺寸。实际会按屏幕可用区域收窄，见 _place_window。
    DESIRED_SIZE = (1520, 900)
    MIN_SIZE = (960, 580)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SeisView — 地震数据可视化")

        # ---------------------------------------------------------- 状态
        self.path: str = ""
        self.vol: SeisVolume | None = None
        self.mode = "shot"
        self.pos = {"shot": 0, "recv": 0, "time": 0}
        self.trace = (0, 0)                 # (炮点, 检波器)
        self._base_clim = (-1.0, 1.0)
        self._clim = (-1.0, 1.0)
        self._contrast = 1.0
        self._stats = {"min": 0.0, "max": 0.0, "mean": 0.0, "rms": 0.0}

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._place_done = False
        self._build_ui()
        self._place_window()

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
        self.setGeometry(avail.left() + max(0, (avail.width() - w) // 2),
                         avail.top() + max(0, (avail.height() - h) // 4),
                         w, h)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if not self._place_done:
            # 标题栏和边框的尺寸只有 show 之后才拿得到，所以此时再精确校正一次
            self._place_done = True
            QtCore.QTimer.singleShot(0, self._ensure_on_screen)

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
        self.setGeometry(
            max(avail.left() + lm, min(geo.left(), avail.right() - w - rm)),
            max(avail.top() + tm, min(geo.top(), avail.bottom() - h - bm)),
            w, h)

    # ================================================================== 界面
    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)
        outer.addWidget(self._build_topbar())

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 850, 380])
        outer.addWidget(splitter, 1)
        outer.addWidget(self._build_statusbar())

    # ---------------------------------------------------------------- 顶栏
    def _build_topbar(self) -> QtWidgets.QFrame:
        bar, lay = make_panel()
        lay.setContentsMargins(14, 10, 12, 10)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        title = QtWidgets.QLabel("SEISVIEW")
        title.setObjectName("Title")
        sub = QtWidgets.QLabel("地震数据可视化")
        sub.setObjectName("Hint")
        row.addWidget(title)
        row.addWidget(sub)
        row.addSpacing(14)

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
            "4 个倾斜反射层 + 2 个绕射点 + 噪声。\n"
            "sample_data/ 里的 .npz/.npy/.mat 请用「打开文件」。")
        self.btn_sample.clicked.connect(self.load_sample)

        row.addWidget(self.btn_open)
        row.addWidget(self.btn_sample)
        lay.addLayout(row)
        return bar

    # ------------------------------------------------------------ 左侧控制
    def _build_left(self) -> QtWidgets.QScrollArea:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(430)

        inner = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(8)
        col.addWidget(self._card_source())
        col.addWidget(self._card_slice())
        col.addWidget(self._card_playback())
        col.addWidget(self._card_display())
        col.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    def _card_source(self) -> QtWidgets.QFrame:
        card, lay = make_panel("数据源")

        self.table = VariableTable()
        self.table.setMinimumHeight(104)
        self.table.itemSelectionChanged.connect(self._on_variable_selected)
        self.table.itemDoubleClicked.connect(lambda _i: self._load_selected_variable())
        lay.addWidget(self.table)

        hint = QtWidgets.QLabel("双击变量直接载入；一维变量可看数值与波形，二维/三维作为体数据展示。")
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
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setValue(val)
        box.setSuffix(suffix)
        box.setSingleStep(10 ** (-decimals))
        box.setMinimumWidth(96)
        return box

    def _card_slice(self) -> QtWidgets.QFrame:
        card, lay = make_panel("切片模式")

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

        tip = QtWidgets.QLabel("在三维立方体上点击某个面，或直接拖动上面这条轨道扫掠。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    def _card_playback(self) -> QtWidgets.QFrame:
        card, lay = make_panel("扫掠播放")

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.btn_prev = QtWidgets.QPushButton("◀")
        self.btn_prev.setFixedWidth(38)
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next = QtWidgets.QPushButton("▶")
        self.btn_next.setFixedWidth(38)
        self.btn_next.clicked.connect(lambda: self._step(1))
        self.btn_play = QtWidgets.QPushButton("▶  播放")
        self.btn_play.setObjectName("Play")
        self.btn_play.clicked.connect(self._toggle_play)
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_play, 1)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        lab = QtWidgets.QLabel("速度")
        lab.setObjectName("Hint")
        self.speed_combo = QtWidgets.QComboBox()
        for name, interval in SPEEDS:
            self.speed_combo.addItem(name, interval)
        self.speed_combo.setCurrentIndex(1)
        self.chk_loop = QtWidgets.QCheckBox("循环")
        self.chk_loop.setChecked(True)
        row2.addWidget(lab)
        row2.addWidget(self.speed_combo, 1)
        row2.addWidget(self.chk_loop)
        lay.addLayout(row2)
        return card

    def _card_display(self) -> QtWidgets.QFrame:
        card, lay = make_panel("显示")

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
        self.clim_combo = QtWidgets.QComboBox()
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

        self.contrast = SliderRow("对比度")
        self.contrast.slider.setRange(20, 400)
        self.contrast.slider.setValue(100)
        self.contrast.valueChanged.connect(self._on_contrast)
        lay.addWidget(self.contrast)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;")
        lay.addWidget(line)

        self.chk_agc = QtWidgets.QCheckBox("自动增益 AGC（按道归一化）")
        self.chk_agc.setToolTip("按道做滑动窗口 RMS 归一化，把深浅部的能量拉到同一量级")
        self.chk_agc.toggled.connect(lambda _v: self._refresh_all())
        lay.addWidget(self.chk_agc)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab3 = QtWidgets.QLabel("AGC 窗口")
        lab3.setObjectName("Hint")
        self.spin_agc = QtWidgets.QSpinBox()
        self.spin_agc.setRange(0, 1001)
        self.spin_agc.setValue(0)
        self.spin_agc.setSpecialValueText("整道")
        self.spin_agc.setSingleStep(20)     # 默认步长 1 要点上百下，直接给 20
        self.spin_agc.setSuffix(" 点")
        self.spin_agc.setToolTip(
            "滑动窗口的点数，直接键入即可（奇数点，偶数会自动 +1）。\n"
            "0 = 整道归一化。常用 21 / 51 / 101 / 201 点。")
        self.spin_agc.valueChanged.connect(lambda _v: self._refresh_all())
        row.addWidget(lab3)
        row.addWidget(self.spin_agc, 1)
        lay.addLayout(row)

        self.chk_wiggle = QtWidgets.QCheckBox("叠加波形（wiggle）")
        self.chk_wiggle.toggled.connect(lambda _v: self._refresh_all())
        lay.addWidget(self.chk_wiggle)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab5 = QtWidgets.QLabel("波形道数")
        lab5.setObjectName("Hint")
        self.spin_wig = QtWidgets.QSpinBox()
        self.spin_wig.setRange(1, 300)
        self.spin_wig.setValue(60)
        self.spin_wig.valueChanged.connect(lambda _v: self._refresh_all())
        row.addWidget(lab5)
        row.addWidget(self.spin_wig, 1)
        lab5b = QtWidgets.QLabel("颜色")
        lab5b.setObjectName("Hint")
        self.combo_wig_color = QtWidgets.QComboBox()
        for name, rgba in WIGGLE_COLORS:
            self.combo_wig_color.addItem(name, rgba)
        self.combo_wig_color.setToolTip(
            "叠加曲线的颜色要和底色拉开：\n"
            "红蓝/彩虹等浅底色用黑色；灰度底色改用青色或黄色。")
        self.combo_wig_color.currentIndexChanged.connect(lambda _i: self._refresh_all())
        row.addWidget(lab5b)
        row.addWidget(self.combo_wig_color)
        lay.addLayout(row)

        self.gain = SliderRow("波形幅度")
        self.gain.slider.setRange(10, 250)
        self.gain.slider.setValue(100)
        self.gain.valueChanged.connect(lambda _v: self._refresh_all())
        lay.addWidget(self.gain)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab4 = QtWidgets.QLabel("渲染抽稀")
        lab4.setObjectName("Hint")
        self.combo_dec = QtWidgets.QComboBox()
        for name, limit in DOWNSAMPLE:
            self.combo_dec.addItem(name, limit)
        self.combo_dec.setCurrentIndex(2)
        self.combo_dec.setToolTip("上色前先把剖面按整数步长抽稀到不超过这个像素数")
        self.combo_dec.currentIndexChanged.connect(lambda _i: self._refresh_all())
        row.addWidget(lab4)
        row.addWidget(self.combo_dec, 1)
        lay.addLayout(row)
        return card

    # -------------------------------------------------------------- 中间
    def _build_center(self) -> QtWidgets.QSplitter:
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        # 允许把子面板压到 0 高：折叠靠的就是这个，否则 splitter 会拿
        # 控件的最小高度把空间顶回去。
        split.setChildrenCollapsible(True)
        self.center_split = split

        wrap, lay = make_panel()
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        self.slice_title = SectionLabel("剖面")
        head.addWidget(self.slice_title)
        head.addStretch(1)
        self.hover_label = ValueLabel("--")
        head.addWidget(self.hover_label)
        btn_slice = ChevronButton()
        btn_slice.clicked.connect(lambda: self._toggle_collapse(0))
        head.addWidget(btn_slice)
        lay.addLayout(head)

        self.slice_view = SliceView()
        self.slice_view.picked.connect(self._on_pick)
        self.slice_view.hovered.connect(self._on_hover)
        lay.addWidget(self.slice_view, 1)
        split.addWidget(wrap)

        wrap2, lay2 = make_panel()
        lay2.setContentsMargins(8, 8, 8, 8)
        lay2.setSpacing(6)
        head2 = QtWidgets.QHBoxLayout()
        head2.setContentsMargins(2, 0, 2, 0)
        head2.addWidget(SectionLabel("单道波形"))
        head2.addStretch(1)
        self.trace_info = ValueLabel("--")
        head2.addWidget(self.trace_info)
        btn_trace = ChevronButton()
        btn_trace.clicked.connect(lambda: self._toggle_collapse(1))
        head2.addWidget(btn_trace)
        lay2.addLayout(head2)
        self.trace_view = TraceView()
        lay2.addWidget(self.trace_view, 1)
        split.addWidget(wrap2)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([620, 210])

        # 折叠时只藏内容、保留标题栏，否则连展开按钮一起消失就回不来了。
        self._collapsible = {0: self.slice_view, 1: self.trace_view}
        self._collapse_btns = {0: btn_slice, 1: btn_trace}
        self._center_sizes: list[int] | None = None
        return split

    def _toggle_collapse(self, index: int) -> None:
        """折叠/展开剖面或单道面板。

        两个坑：
        1. ``QSplitter.setSizes`` 会按比例把多余空间补回去，收缩时两个尺寸之和
           必须等于空间总量；
        2. 内容控件带 ``minimumHeight``（单道绘图区是 120），splitter 会拿它当
           最小高度把面板顶回去。所以这里把面板的 min/max 高度都钉在
           "标题栏 + 边距"上，既缩得下去，又保证标题栏和折叠按钮还看得见、点得到。
        """
        content = self._collapsible[index]
        btn = self._collapse_btns[index]
        panel = self.center_split.widget(index)
        other = 1 - index
        collapsing = content.isVisible()
        total = max(1, sum(self.center_split.sizes()))
        if collapsing:
            self._center_sizes = self.center_split.sizes()
            # 保留的高度 = 面板高度 - 内容高度，也就是标题栏 + 边距。
            keep = max(30, panel.height() - content.height())
            content.setVisible(False)
            panel.setMinimumHeight(keep)
            panel.setMaximumHeight(keep)
            # 注意这里请求的是 keep 而不是 0：请求 0 会触发 splitter 的
            # "可折叠"特判，直接把面板压成 0 高，标题栏和按钮就都没了。
            sizes = [0, 0]
            sizes[index] = keep
            sizes[other] = max(0, total - keep)
            self.center_split.setSizes(sizes)
        else:
            panel.setMinimumHeight(0)
            panel.setMaximumHeight(16777215)
            content.setVisible(True)
            if self._center_sizes:
                self.center_split.setSizes(self._center_sizes)
            else:
                self.center_split.setSizes([total if i == 0 else 0 for i in range(2)])
        btn.set_expanded(not collapsing)
        self._update_reference()          # 单道面板收起时同步收起提示线
        self.status.setText("已折叠面板，点 ▸ 展开。" if collapsing else "已展开面板。")

    # ---------------------------------------------------------------- 右侧
    def _build_right(self) -> QtWidgets.QFrame:
        card, lay = make_panel("数据体")
        card.setMinimumWidth(300)
        card.setMaximumWidth(520)

        self.view3d = view3d.create_view3d()
        if self.view3d is not None:
            self.view3d.setMinimumHeight(320)
            self.view3d.faceClicked.connect(self._focus_face)
            lay.addWidget(self.view3d, 1)
        else:
            fallback = QtWidgets.QLabel(
                "三维视图不可用（未能创建 OpenGL 上下文）。\n"
                "剖面与波形功能不受影响。")
            fallback.setObjectName("Hint")
            fallback.setWordWrap(True)
            fallback.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            fallback.setMinimumHeight(320)
            lay.addWidget(fallback, 1)

        lab = QtWidgets.QLabel("定位到面（同时切换切片模式）")
        lab.setObjectName("Hint")
        lay.addWidget(lab)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for key in ("shot", "recv", "time"):
            btn = QtWidgets.QPushButton(SLICE_LABELS[key])
            btn.setObjectName("Ghost")
            btn.clicked.connect(lambda _c=False, k=key: self._focus_face(k))
            row.addWidget(btn)
        lay.addLayout(row)

        self.btn_reset = QtWidgets.QPushButton("复位视角")
        self.btn_reset.clicked.connect(
            lambda: self.view3d and self.view3d.reset_view())
        lay.addWidget(self.btn_reset)

        self.face_info = QtWidgets.QLabel("--")
        self.face_info.setObjectName("Status")
        self.face_info.setWordWrap(True)
        lay.addWidget(self.face_info)
        return card

    def _build_statusbar(self) -> QtWidgets.QFrame:
        bar, lay = make_panel()
        lay.setContentsMargins(12, 6, 12, 6)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status = QtWidgets.QLabel("就绪。点击「载入示例」可立即看到效果。")
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
            self, "打开地震数据文件", self.path or "",
            "地震数据 (*.sgy *.segy *.su *.npy *.npz *.mat);;"
            "SEG-Y / SU (*.sgy *.segy *.su);;"
            "NumPy (*.npy *.npz);;MATLAB (*.mat);;所有文件 (*)")
        if not path:
            return
        try:
            infos = loaders.list_variables(path)
        except LoadError as exc:
            self._error("无法读取文件", str(exc))
            return
        except Exception as exc:                        # pragma: no cover
            self._error("无法读取文件", f"{type(exc).__name__}: {exc}")
            return

        self.path = path
        p = Path(path)
        self.file_label.setText(f"{p.parent}  ▸  {p.name}")
        self.table.fill(infos)
        self.btn_load.setEnabled(True)
        self.src_info.setText(f"共 {len(infos)} 个可用变量，正在载入第一个…")
        self.status.setText(f"已识别 {len(infos)} 个变量。")

        # 打开即出图：默认载入第一个变量，需要确认轴序时会弹框
        self.load_variable(infos[0].key)

    def open_path(self, path: str) -> None:
        """按路径直接打开（命令行参数 / 拖放用）。"""
        if not path or not Path(path).exists():
            self._error("文件不存在", f"找不到 {path}")
            return
        try:
            infos = loaders.list_variables(path)
        except Exception as exc:
            self._error("无法读取文件", str(exc))
            return
        self.path = path
        p = Path(path)
        self.file_label.setText(f"{p.parent}  ▸  {p.name}")
        self.table.fill(infos)
        self.btn_load.setEnabled(True)
        self.load_variable(infos[0].key)

    def _load_selected_variable(self) -> None:
        info = self.table.current_info()
        if info is not None:
            self.load_variable(info.key)

    def load_variable(self, key: str) -> None:
        if not self.path:
            return
        info = self.table.info_of_key(key)
        if info is None:
            return
        if len(info.shape) <= 1:
            # 一维/标量：这类变量是采样时间轴、坐标轴、子波之类，
            # 要的是"数值是多少"，直接列表显示，不往体数据里塞。
            try:
                arr = loaders.load_array(self.path, key)
            except LoadError as exc:
                self._error("读取失败", str(exc))
                return
            ArrayViewDialog(f"{Path(self.path).name}  ▸  {key}", arr, self).exec()
            self.status.setText(f"已查看 {key} 的数值。")
            return
        if len(info.shape) > 3:
            self._error("暂不支持",
                        f"变量 {key} 是 {len(info.shape)} 维，本工具处理一维数值、"
                        "二维剖面或三维体数据（炮点 × 检波器 × 时间）。")
            return

        fingerprint = f"{loaders.file_fingerprint(self.path)}:{key}"
        remember = False
        if info.roles:
            # SEG-Y/SU：立方体是按道头现搭的，轴序由构造决定，不必再确认
            roles = list(info.roles)
            self.status.setText(f"已按道头分选出 {key}，正在载入…")
        else:
            initial = loaders.get_axis_memory(fingerprint)
            if initial and len(initial) != len(info.shape):
                initial = None
            answer = ask_axis_order(f"{Path(self.path).name}  ▸  {key}", info.shape,
                                    initial, self)
            if answer is None:
                self.status.setText("已取消载入。")
                return
            roles, remember = answer
            if len(roles) != len(info.shape):
                self._error("轴序不完整", "每一个维度都需要指定一个物理含义。")
                return

        # SEG-Y 的 dt / 道距来自道头，直接覆盖界面默认值，让读数与文件一致
        extra = loaders.load_meta(self.path, key)
        for spin, name in ((self.spin_dt, "dt"), (self.spin_dx, "dx"), (self.spin_ds, "ds")):
            if extra.get(name):
                spin.setValue(float(extra[name]))

        try:
            arr = loaders.load_array(self.path, key)
            vol = loaders.build_volume(
                f"{Path(self.path).stem}·{key}", arr, roles,
                dt=extra.get("dt", self.spin_dt.value()),
                dx=extra.get("dx", self.spin_dx.value()),
                ds=extra.get("ds", self.spin_ds.value()),
                meta=dict(extra.get("meta", {})))
        except LoadError as exc:
            self._error("载入失败", str(exc))
            return
        except Exception as exc:                        # pragma: no cover
            self._error("载入失败", f"{type(exc).__name__}: {exc}")
            return

        if remember:
            loaders.set_axis_memory(fingerprint, roles)
        self._set_volume(vol)
        if not vol.meta.get("summary"):
            self.src_info.setText(
                f"当前：{vol.name}\n"
                f"{vol.ns} 炮 × {vol.nr} 检波点 × {vol.nt} 采样　"
                f"时长 {vol.nt * vol.dt:.2f} s")

    def load_sample(self) -> None:
        self.path = ""
        self.file_label.setText("内置合成示例（未从文件读取）")
        self.table.fill([])
        self.btn_load.setEnabled(False)
        self.spin_dt.setValue(0.002)
        self.spin_dx.setValue(12.5)
        self.spin_ds.setValue(25.0)
        vol = build_sample_volume()
        self._set_volume(vol)
        self.src_info.setText(
            f"当前：{vol.name}\n{vol.ns} 炮 × {vol.nr} 检波点 × {vol.nt} 采样\n"
            f"4 个反射层 + 2 个绕射点，可检验显示是否正确。")
        self.status.setText("已载入示例数据。")

    # ================================================================== 装配
    def _set_volume(self, vol: SeisVolume) -> None:
        self._stop()
        self.vol = vol
        self.pos = {"shot": vol.ns // 2, "recv": vol.nr // 2, "time": max(0, vol.nt // 4)}
        self.trace = (self.pos["shot"], self.pos["recv"])
        # 只有一个切片可选的方向没有扫掠意义，直接禁用；默认落在第一个可用的方向
        usable = [m for m in ("shot", "recv", "time") if vol.slice_index_range(m) > 1]
        self.mode = usable[0] if usable else "time"
        self.mode_ctl.set_enabled_keys(set(usable))
        self.mode_ctl.set_value(self.mode)

        self._recompute_base_clim()
        if self.view3d is not None:
            self.view3d.set_volume(vol)
            self.view3d.focus_face(self.mode, animate=False)
        self.slice_view.reset()
        self.trace_view.clear()
        self._refresh_all()
        self._update_face_info()
        summary = vol.meta.get("summary")     # SEG-Y/SU 带自己的载入摘要
        if summary:
            self.src_info.setText(summary)

    def _recompute_base_clim(self) -> None:
        vol = self.vol
        if vol is None:
            return
        # 取三片中位切片做统计，而不是在整卷上跨步采样：
        # 惰性（mmap）数据卷上跨步采样会把整个文件都翻一遍，等于白惰性了
        parts = []
        for m in ("shot", "recv", "time"):
            sl = vol.take_slice(m, vol.slice_index_range(m) // 2)
            parts.append(np.asarray(sl, dtype=np.float32).ravel()[::5])
        sample = np.concatenate(parts) if parts else np.zeros(1, np.float32)
        self._base_clim = compute_clim(sample, self.clim_combo.currentData(),
                                      self.spin_manual.value())

    def _scaled_clim(self) -> tuple[float, float]:
        lo, hi = self._base_clim
        mid = 0.5 * (lo + hi)
        half = max(1e-12, 0.5 * (hi - lo) * self._contrast)
        return (mid - half, mid + half)

    # ================================================================== 刷新
    def _refresh_all(self, sync_controls: bool = True) -> None:
        if self.vol is None:
            return
        self._refresh_slice()
        self._refresh_faces()
        self._refresh_trace()
        if sync_controls:
            self._sync_controls()
        else:
            self.playhead.set_position(self.pos[self.mode])
        self._update_status()

    def _refresh_slice(self) -> None:
        vol = self.vol
        mode = self.mode
        index = self.pos[mode]

        img_full = vol.take_slice(mode, index)
        limit = self.combo_dec.currentData() or 10 ** 9
        img = decimate(img_full, max_cols=limit, max_rows=limit)

        if self.chk_agc.isChecked():
            img = agc(img, self.spin_agc.value())
            clim = compute_clim(img, "robust")
        else:
            clim = self._scaled_clim()
        self._clim = clim
        # 统计量只对抽稀后的图做二次抽样，避免为了一行读数多跑一遍全量数据
        self._stats = stats(np.asarray(img[::4, ::4], dtype=np.float32))

        xlabel, ylabel, suffix = vol.axis_labels_of(mode, index)
        self.slice_title.setText(f"剖面　{suffix}")
        wig = self.spin_wig.value() if self.chk_wiggle.isChecked() else 0
        self.slice_view.set_slice(img, vol.extent_of(mode), self.cmap_combo.cmap(),
                                  clim, xlabel, ylabel,
                                  full_shape=img_full.shape,
                                  wiggle=wig, gain=self.gain.value() / 100.0,
                                  wiggle_color=self.combo_wig_color.currentData())

        # 标出下方单道波形取自哪一炮哪一道
        self._update_reference()

    def _update_reference(self) -> None:
        """在剖面上标出下方单道波形取自哪一炮哪一道。

        横轴对应哪个物理量取决于切片模式：共炮点面横轴是检波器、共检波点面是
        炮点。弄错就会把线画到别的轴上去（前几版那根"莫名其妙的绿线"就是把
        x 值喂给了横线、又用错了轴）。

        时间切片上**不画**：它是 (炮号, 道号) 索引平面而不是剖面，标"第几道"
        没有物理意义。单道面板收起时也不画，免得指向一个看不见的面板。
        """
        vol = self.vol
        if vol is None or self.mode == "time" or not self.trace_view.isVisible():
            self.slice_view.set_reference(None)
            return
        if self.mode == "shot":          # 共炮点面：横轴是检波器
            idx, total = self.pos["recv"], vol.nr
        else:                            # 共检波点面：横轴是炮点
            idx, total = self.pos["shot"], vol.ns
        x0, x1, _y0, _y1 = vol.extent_of(self.mode)
        frac = idx / max(1, total - 1)
        s = min(max(self.pos["shot"], 0), vol.ns - 1)
        r = min(max(self.pos["recv"], 0), vol.nr - 1)
        self.slice_view.set_reference(x0 + (x1 - x0) * frac, f"S={s}  R={r}")

    def _refresh_faces(self) -> None:
        if self.view3d is None or self.vol is None:
            return
        agc_window = self.spin_agc.value() if self.chk_agc.isChecked() else None
        self.view3d.update_faces(self.pos["shot"], self.pos["recv"], self.pos["time"],
                                 self.cmap_combo.cmap(), self._clim,
                                 agc_window=agc_window)
        self._update_face_info()

    def _refresh_trace(self) -> None:
        vol = self.vol
        s = min(max(self.pos["shot"], 0), vol.ns - 1)
        r = min(max(self.pos["recv"], 0), vol.nr - 1)
        self.trace = (s, r)
        amp = np.asarray(vol.take_trace(s, r), dtype=np.float32)
        t = np.arange(vol.nt) * vol.dt
        peak = float(np.max(np.abs(amp))) or 1.0
        self.trace_view.set_trace(t, amp / peak)
        self.trace_info.setText(f"S={s}  R={r}  峰值 {peak:.3g}")

    def _sync_controls(self) -> None:
        vol = self.vol
        mode = self.mode
        count = vol.slice_index_range(mode)
        self.slice_slider.title.setText(AXIS_TITLES[mode])
        self.slice_slider.configure(count - 1, self.pos[mode],
                                    f"　/{count - 1}")
        self.playhead.set_range(count, self.pos[mode])

    def _update_status(self) -> None:
        vol = self.vol
        mode = self.mode
        s, r, t = self.pos["shot"], self.pos["recv"], self.pos["time"]
        info = self._stats
        self.status.setText(
            f"{SLICE_LABELS[mode]} {self.pos[mode]}/{vol.slice_index_range(mode) - 1}"
            f"　|　S={s}  R={r}  T={t * vol.dt:.3f} s"
            f"　|　时间 {vol.nt * vol.dt:.2f} s　空间 {vol.nr * vol.dx:.0f} m")
        self.stats_label.setText(
            f"min {info['min']:+.3g}   max {info['max']:+.3g}   rms {info['rms']:.3g}")

    def _update_face_info(self) -> None:
        vol = self.vol
        if vol is None:
            return
        s, r, t = self.pos["shot"], self.pos["recv"], self.pos["time"]
        self.face_info.setText(
            f"共炮点面  S={s}  ({s * vol.ds:.0f} m)\n"
            f"共检波点面  R={r}  ({r * vol.dx:.0f} m)\n"
            f"时间切片  T={t}  ({t * vol.dt:.3f} s)\n"
            "三维与剖面、单道波形一致：时间向下增大；各轴按长度归一化显示。")

    # ================================================================== 交互
    def _on_variable_selected(self) -> None:
        info = self.table.current_info()
        if info is not None:
            self.status.setText(
                f"已选中 {info.key}　形状 {' × '.join(str(v) for v in info.shape)}　"
                f"{info.dtype}　{info.size_text}")

    def _on_mode(self, key: str) -> None:
        if self.vol is None or key not in self.pos:
            return
        self.mode = key
        self._refresh_all()
        if self.view3d is not None:
            self.view3d.focus_face(key)

    def _on_slice_index(self, value: int) -> None:
        """切片位置变化。滑杆与播放头都会调用这里，因此必须能安全地双向同步。"""
        if self.vol is None:
            return
        n = self.vol.slice_index_range(self.mode)
        new = int(np.clip(value, 0, n - 1))
        changed = new != self.pos[self.mode]
        self.pos[self.mode] = new
        if changed:
            self._refresh_all(sync_controls=False)
        else:
            self.playhead.set_position(new)
        if self.slice_slider.value() != new:      # 来自播放头时才需要回写滑杆
            self.slice_slider.set_value(new)

    def _step(self, delta: int) -> None:
        if self.vol is None:
            return
        n = self.vol.slice_index_range(self.mode)
        self._on_slice_index((self.pos[self.mode] + delta) % n)

    def _on_cmap(self) -> None:
        self._refresh_all()

    def _on_clim_mode(self) -> None:
        self.spin_manual.setEnabled(self.clim_combo.currentData() == "manual")
        if self.vol is not None:
            self._recompute_base_clim()
            self._refresh_all()

    def _on_contrast(self, value: int) -> None:
        self._contrast = value / 100.0
        if self.vol is not None:
            self._refresh_all(sync_controls=False)

    def _on_pick(self, col: int, row: int) -> None:
        """剖面点击 → 把位置传给另外两个轴，并更新单道波形。"""
        if self.vol is None:
            return
        vol = self.vol
        if self.mode == "shot":        # 固定 S，横轴 R、纵轴 T
            self.pos["recv"] = int(np.clip(col, 0, vol.nr - 1))
            self.pos["time"] = int(np.clip(row, 0, vol.nt - 1))
        elif self.mode == "recv":      # 固定 R，横轴 S、纵轴 T
            self.pos["shot"] = int(np.clip(col, 0, vol.ns - 1))
            self.pos["time"] = int(np.clip(row, 0, vol.nt - 1))
        else:                          # 固定 T，横轴 R、纵轴 S
            self.pos["recv"] = int(np.clip(col, 0, vol.nr - 1))
            self.pos["shot"] = int(np.clip(row, 0, vol.ns - 1))
        self._refresh_faces()
        self._refresh_trace()
        self._update_reference()
        self._update_status()

    def _on_hover(self, col: int, row: int) -> None:
        if self.vol is None:
            return
        vol = self.vol
        if self.mode == "shot":
            text = f"R={col} ({col * vol.dx:.1f} m)　T={row} ({row * vol.dt:.3f} s)"
        elif self.mode == "recv":
            text = f"S={col} ({col * vol.ds:.1f} m)　T={row} ({row * vol.dt:.3f} s)"
        else:
            text = f"R={col} ({col * vol.dx:.1f} m)　S={row} ({row * vol.ds:.1f} m)"
        self.hover_label.setText(text)

    def _focus_face(self, key: str) -> None:
        """切到某个面的切片模式，并把三维相机转到正视该面的方位。"""
        if self.vol is None:
            return
        self.mode_ctl.set_value(key)
        self._on_mode(key)

    # ================================================================== 播放
    def _toggle_play(self) -> None:
        if self._timer.isActive():
            self._stop()
        elif self.vol is not None:
            self._timer.start(int(self.speed_combo.currentData()))
            self.btn_play.setText("⏸  暂停")

    def _stop(self) -> None:
        self._timer.stop()
        self.btn_play.setText("▶  播放")

    def _tick(self) -> None:
        vol = self.vol
        if vol is None:
            return
        n = vol.slice_index_range(self.mode)
        nxt = self.pos[self.mode] + 1
        if nxt >= n:
            if not self.chk_loop.isChecked():
                self._stop()
                return
            nxt = 0
        self.pos[self.mode] = nxt
        self._refresh_all()

    # ================================================================== 杂项
    def _error(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, title, message)
        self.status.setText(f"{title}：{message}")

    def closeEvent(self, ev) -> None:
        self._stop()
        super().closeEvent(ev)