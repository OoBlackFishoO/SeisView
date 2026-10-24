"""左侧设置卡片的构建：数据、剖切、密度、波形、对比与线型。"""

from __future__ import annotations

from PySide6 import QtWidgets

from .volume import SLICE_LABELS
from .widgets import (ColormapCombo, FoldCard, PlayheadTrack,
                      SegmentedControl, SliderRow, VariableTable,
                      WheelSafeComboBox, WheelSafeDoubleSpinBox,
                      WheelSafeSpinBox)
from .workspace import _hdivider

# 扫掠速度：显示名 → 定时器间隔 (ms)
SPEEDS = [("慢", 150), ("中", 70), ("快", 35), ("极快", 16)]
# 抽稀上限：显示名 → 每边最多像素（0 表示不抽稀）
DOWNSAMPLE = [("不抽稀", 0), ("4096", 4096), ("2048", 2048), ("1024", 1024), ("512", 512)]
CLIM_MODES = [("自动", "auto"), ("P95", "p95"), ("P98", "p98"),
              ("P99", "p99"), ("手动", "manual")]
AGC_WINDOWS = [("整道", 0), ("11 点", 11), ("21 点", 21), ("51 点", 51),
               ("101 点", 101), ("201 点", 201), ("301 点", 301),
               ("501 点", 501), ("1001 点", 1001)]


class SettingsCards:
    """每张卡片只负责把控件建出来并赋给宿主；业务逻辑仍在主窗口。"""

    def __init__(self, host) -> None:
        self.host = host

    def _fill_data_card(self, card: FoldCard) -> None:
        """「数据」：数据从哪来、物理标尺是多少。"""
        lay = card.body

        self.host.table = VariableTable()
        self.host.table.setMinimumHeight(86)
        self.host.table.itemSelectionChanged.connect(self.host._on_variable_selected)
        self.host.table.itemDoubleClicked.connect(lambda _i: self.host._load_selected_variable())
        lay.addWidget(self.host.table)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.host.spin_dt = self.host._spin(0.000001, 1.0, 0.001, 6, " s")
        self.host.spin_dx = self.host._spin(0.01, 10000.0, 12.5, 3, " m")
        self.host.spin_ds = self.host._spin(0.01, 10000.0, 25.0, 3, " m")
        for i, (name, w) in enumerate([("采样间隔 dt", self.host.spin_dt),
                                       ("检波器间距 dx", self.host.spin_dx),
                                       ("炮点间距 ds", self.host.spin_ds)]):
            lab = QtWidgets.QLabel(name)
            lab.setObjectName("Hint")
            grid.addWidget(lab, i, 0)
            grid.addWidget(w, i, 1)
        lay.addLayout(grid)
        # 改完立刻生效（原先改了要重新载入才看得出差别），并同步三视图的标尺
        for w in (self.host.spin_dt, self.host.spin_dx, self.host.spin_ds):
            w.editingFinished.connect(self.host._apply_scales)

        self.host.btn_load = QtWidgets.QPushButton("载入所选变量")
        self.host.btn_load.setObjectName("Primary")
        self.host.btn_load.setEnabled(False)
        self.host.btn_load.clicked.connect(self.host._load_selected_variable)
        lay.addWidget(self.host.btn_load)

        self.host.src_info = QtWidgets.QLabel("—")
        self.host.src_info.setObjectName("Hint")
        self.host.src_info.setWordWrap(True)
        lay.addWidget(self.host.src_info)
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
        self.host.dataset_combo = WheelSafeComboBox()
        self.host.dataset_combo.currentIndexChanged.connect(self.host._on_active_changed)
        row.addWidget(lab)
        row.addWidget(self.host.dataset_combo, 1)
        lay.addLayout(row)

        self.host.chk_sync = QtWidgets.QCheckBox("同步剖面参数与目标道")
        self.host.chk_sync.setChecked(True)
        self.host.chk_sync.toggled.connect(self.host._on_sync_toggle)
        lay.addWidget(self.host.chk_sync)

        brow = QtWidgets.QHBoxLayout()
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(6)
        self.host.btn_add = QtWidgets.QPushButton("＋ 添加对比数据")
        self.host.btn_add.clicked.connect(self.host.add_compare_file)
        self.host.btn_remove = QtWidgets.QPushButton("－ 移除当前数据")
        self.host.btn_remove.setObjectName("Ghost")
        self.host.btn_remove.clicked.connect(self.host.remove_dataset)
        brow.addWidget(self.host.btn_add, 1)
        brow.addWidget(self.host.btn_remove, 1)
        lay.addLayout(brow)

        tip = QtWidgets.QLabel("")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        self.host.compare_info = tip
        lay.addWidget(tip)
        return card

    def _fill_cut_card(self, card: FoldCard) -> None:
        """「剖切与播放」：把原来的「切片模式」和「扫掠播放」合成一组。

        两张卡干的本就是同一件事 —— 决定"现在看哪一片"：前者是手动跳，
        后者是自动扫。分在两处时用户总要在两组之间来回找。
        """
        self.host._fill_slice_card(card)
        card.body.addWidget(_hdivider())
        self.host._fill_playback_card(card)

    def _fill_slice_card(self, card: FoldCard) -> None:
        lay = card.body

        self.host.mode_ctl = SegmentedControl(
            [("shot", SLICE_LABELS["shot"]), ("recv", SLICE_LABELS["recv"]),
             ("time", SLICE_LABELS["time"])])
        self.host.mode_ctl.changed.connect(self.host._on_mode)
        lay.addWidget(self.host.mode_ctl)

        self.host.slice_slider = SliderRow("炮点 S")
        self.host.slice_slider.valueChanged.connect(self.host._on_slice_index)
        lay.addWidget(self.host.slice_slider)

        self.host.playhead = PlayheadTrack()
        self.host.playhead.seek.connect(self.host._on_slice_index)
        lay.addWidget(self.host.playhead)

        # 当前剖面序号 + 目标道号：只在这里显示给用户看，不再画进导出图。
        self.host.slice_info = QtWidgets.QLabel("当前：—")
        self.host.slice_info.setObjectName("Hint")
        self.host.slice_info.setWordWrap(True)
        lay.addWidget(self.host.slice_info)

        # 单步精确调整：放在"切片模式"里更合逻辑（原先混在连续播放那组按钮中间，
        # 容易误点成播放）
        step = QtWidgets.QHBoxLayout()
        step.setContentsMargins(0, 0, 0, 0)
        step.setSpacing(6)
        self.host.btn_prev = QtWidgets.QPushButton("◀  上一切片")
        self.host.btn_prev.clicked.connect(lambda: self.host._step(-1))
        self.host.btn_next = QtWidgets.QPushButton("下一切片  ▶")
        self.host.btn_next.clicked.connect(lambda: self.host._step(1))
        step.addWidget(self.host.btn_prev, 1)
        step.addWidget(self.host.btn_next, 1)
        lay.addLayout(step)
        return card

    def _fill_playback_card(self, card: FoldCard) -> None:
        lay = card.body

        self.host.btn_play = QtWidgets.QPushButton("▶  播放")
        self.host.btn_play.setObjectName("Play")
        self.host.btn_play.clicked.connect(self.host._toggle_play)
        lay.addWidget(self.host.btn_play)

        row2 = QtWidgets.QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        lab = QtWidgets.QLabel("速度")
        lab.setObjectName("Hint")
        self.host.speed_combo = WheelSafeComboBox()
        for name, interval in SPEEDS:
            self.host.speed_combo.addItem(name, interval)
        self.host.speed_combo.setCurrentIndex(1)
        # 播放中改速度要立刻生效：定时器起过之后间隔不会自己跟着下拉框变
        self.host.speed_combo.currentIndexChanged.connect(self.host._on_speed)
        self.host.chk_loop = QtWidgets.QCheckBox("循环")
        self.host.chk_loop.setChecked(True)
        row2.addWidget(lab)
        row2.addWidget(self.host.speed_combo, 1)
        row2.addWidget(self.host.chk_loop)
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
        self.host.cmap_combo = ColormapCombo()
        self.host.cmap_combo.setCurrentIndex(2)          # 默认红蓝，地震惯例
        self.host.cmap_combo.currentIndexChanged.connect(self.host._on_cmap)
        r1.addWidget(lab1)
        r1.addWidget(self.host.cmap_combo, 1)
        lay.addLayout(r1)

        r2 = QtWidgets.QHBoxLayout()
        r2.setContentsMargins(0, 0, 0, 0)
        r2.setSpacing(8)
        lab2 = QtWidgets.QLabel("色标上限")
        lab2.setObjectName("Hint")
        self.host.lab_clim = lab2                        # 跟着上面的下拉一起置灰
        self.host.clim_combo = WheelSafeComboBox()
        for name, key in CLIM_MODES:
            self.host.clim_combo.addItem(name, key)
        self.host.clim_combo.currentIndexChanged.connect(self.host._on_clim_mode)
        self.host.spin_manual = self.host._spin(0.000001, 1e9, 1.0, 6, "")
        self.host.spin_manual.setPrefix("± ")
        self.host.spin_manual.setEnabled(False)
        self.host.spin_manual.valueChanged.connect(self.host._on_clim_mode)
        r2.addWidget(lab2)
        r2.addWidget(self.host.clim_combo, 1)
        r2.addWidget(self.host.spin_manual)
        lay.addLayout(r2)

        self.host.contrast = SliderRow("对比度", spin=True, suffix=" %", log=True)
        self.host.contrast.set_range(10, 1000, 100)
        self.host.contrast.valueChanged.connect(self.host._on_contrast)
        self.host.contrast.released.connect(self.host._flush_contrast)
        lay.addWidget(self.host.contrast)

        # ---------------- 增益：AGC 及其窗口
        lay.addWidget(_hdivider())

        self.host.chk_agc = QtWidgets.QCheckBox("自动增益 AGC（按道归一化）")
        self.host.chk_agc.toggled.connect(self.host._on_gate_toggle)
        lay.addWidget(self.host.chk_agc)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab3 = QtWidgets.QLabel("AGC 窗口")
        lab3.setObjectName("Hint")
        self.host.lab_agc = lab3
        self.host.combo_agc = WheelSafeComboBox()
        for name, points in AGC_WINDOWS:
            self.host.combo_agc.addItem(name, points)
        self.host.combo_agc.currentIndexChanged.connect(lambda _i: self.host._refresh_all())
        row.addWidget(lab3)
        row.addWidget(self.host.combo_agc, 1)
        lay.addLayout(row)

        # ---------------- 性能：与「画成什么样」无关，只影响开销
        lay.addWidget(_hdivider())

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab4 = QtWidgets.QLabel("渲染抽稀")
        lab4.setObjectName("Hint")
        self.host.combo_dec = WheelSafeComboBox()
        for name, limit in DOWNSAMPLE:
            self.host.combo_dec.addItem(name, limit)
        self.host.combo_dec.setCurrentIndex(2)
        self.host.combo_dec.currentIndexChanged.connect(lambda _i: self.host._refresh_all())
        row.addWidget(lab4)
        row.addWidget(self.host.combo_dec, 1)
        lay.addLayout(row)
        return card

    def _fill_wave_card(self, card: FoldCard) -> None:
        """「波形」：把原来散在三处的波形设置收拢成一组。

        原「显示」里的波形开关、「线型」三行、「单道波形」的目标道与归一化开关，
        本质是同一件事（画不画波形、画成什么样、取哪一道），拆成三张卡时
        用户调一个波形要在左栏上下跑三趟。
        """
        lay = card.body

        self.host.chk_wiggle = QtWidgets.QCheckBox("叠加波形（wiggle）")
        self.host.chk_wiggle.toggled.connect(self.host._on_gate_toggle)
        lay.addWidget(self.host.chk_wiggle)

        self.host.chk_pure = QtWidgets.QCheckBox("仅显示波形（不画密度图）")
        self.host.chk_pure.toggled.connect(self.host._on_pure_toggle)
        lay.addWidget(self.host.chk_pure)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab5 = QtWidgets.QLabel("波形道数")
        lab5.setObjectName("Hint")
        self.host.lab_wig = lab5
        self.host.spin_wig = WheelSafeSpinBox()
        self.host.spin_wig.setRange(1, 1000)
        self.host.spin_wig.setValue(60)
        self.host.spin_wig.setKeyboardTracking(False)   # 回车/失焦才提交，免得边敲边重绘
        self.host.spin_wig.valueChanged.connect(lambda _v: self.host._refresh_all())
        row.addWidget(lab5)
        row.addWidget(self.host.spin_wig, 1)
        lay.addLayout(row)

        self.host.gain = SliderRow("波形幅度", spin=True, suffix=" %")
        self.host.gain.set_range(10, 250, 100)
        self.host.gain.valueChanged.connect(lambda _v: self.host._refresh_all())
        lay.addWidget(self.host.gain)

        lay.addWidget(_hdivider())
        self.host._fill_trace_card(card)          # 目标道 + 峰值归一化（追加到同一张卡）

    def _fill_trace_card(self, card: FoldCard) -> None:
        lay = card.body

        self.host.chk_norm = QtWidgets.QCheckBox("按峰值归一化（对比时各道各自归一）")
        self.host.chk_norm.setChecked(True)
        self.host.chk_norm.toggled.connect(lambda _c: self.host._refresh_trace())
        lay.addWidget(self.host.chk_norm)
        return card

