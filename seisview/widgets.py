"""自定义控件：分段选择、参数滑杆、播放头轨道、变量表、轴序确认框、数组数值查看。"""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import export as exporter
from . import icons, render, style
from .loaders import VariableInfo, guess_roles, role_options
from .volume import ROLE_LABELS, ROLE_RECV, ROLE_SHOT, ROLE_TIME


# ============================================================ 滚轮安全控件
class _NoWheelMixin:
    """禁止用滚轮改值。

    左栏是滚动区，鼠标扫过下拉框/数字框时很容易顺手把参数改掉（尤其是抽稀、
    AGC 窗口这种一改就重绘的项）。这里用 ``ev.ignore()`` 让事件继续往上传给
    父控件 —— 滚动区照常滚动，而值不变；直接"吞掉"事件会让滚轮在控件上失灵，
    体验反而更差。
    """

    def wheelEvent(self, ev) -> None:                        # noqa: N802 (Qt 命名)
        ev.ignore()


class WheelSafeComboBox(_NoWheelMixin, QtWidgets.QComboBox):
    """下拉框：滚轮不改值；并且**不让"最长的条目"当硬性最小宽度**。

    后者是个很坑的默认行为：QComboBox 的 minimumSizeHint 会取最长的候选项，
    而左侧设置栏里的下拉框一旦放进很长的数据名（"数据 1　xxx·data"），这个下限
    就被撑大，而且**清空条目也不会缩回来**。侧边栏的宽度是有限的，于是底下凭空
    长出一条横向滚动条（而且会随载入过的数据名越来越宽）。
    这里给一个保守的下限，需要多宽交给 preferred 尺寸和布局的伸缩去决定。
    """

    def minimumSizeHint(self) -> QtCore.QSize:          # noqa: N802 （Qt 接口名）
        base = super().minimumSizeHint()
        w = max(self.minimumWidth(), 72)
        return QtCore.QSize(min(base.width(), w), base.height())


class WheelSafeSpinBox(_NoWheelMixin, QtWidgets.QSpinBox):
    """整数框：滚轮不改值。"""


class WheelSafeDoubleSpinBox(_NoWheelMixin, QtWidgets.QDoubleSpinBox):
    """浮点框：滚轮不改值。"""


class WheelSafeSlider(_NoWheelMixin, QtWidgets.QSlider):
    """滑杆：滚轮不改值。

    左栏本来就有好几条滑杆（切片位置、对比度、波形幅度），鼠标扫过时很容易
    被滚轮顺手拖走 —— 而且滑杆的"滚动"没有任何视觉提示，比下拉框更隐蔽。
    """

# ==================================================================== 小标题
class SectionLabel(QtWidgets.QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionTitle")


class ValueLabel(QtWidgets.QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Value")
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)


class ElidedLabel(QtWidgets.QLabel):
    """放不下就在**末尾省略**的标签。

    用于分组收起后那行摘要：数据名或色标名可能很长，直接放会把标题行挤爆
    （实测会把右边的"恢复默认"按钮顶掉）。这里按当前宽度重算一次省略文本，
    所以窗口或左栏宽度变了以后也会重新算，而不是一开始就固定截断。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__("", parent)
        self._full = ""
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                           QtWidgets.QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setText(text)

    def full_text(self) -> str:
        """完整文本（供外部比较用，避免和省略后的显示文本对不上）。"""
        return self._full

    # 关键：尺寸提示必须按**完整文本**算，而不是按当前显示的那段省略文字。
    # 否则会形成正反馈 —— 宽度变小 → 省略更狠 → 尺寸提示更小 → 宽度更小，
    # 最后整行摘要缩成 0 宽、什么都看不见。
    def sizeHint(self) -> QtCore.QSize:                  # noqa: N802 （Qt 接口名）
        fm = self.fontMetrics()
        return QtCore.QSize(fm.horizontalAdvance(self._full), fm.height())

    def minimumSizeHint(self) -> QtCore.QSize:           # noqa: N802 （Qt 接口名）
        return QtCore.QSize(0, self.fontMetrics().height())

    def setText(self, text: str) -> None:           # noqa: N802 （Qt 接口名）
        self._full = str(text)
        self.updateGeometry()
        self._apply()

    def resizeEvent(self, ev) -> None:              # noqa: N802 （Qt 接口名）
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        width = max(0, self.width() - 2)
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, QtCore.Qt.TextElideMode.ElideRight,
                                      width) if width else self._full)


# ==================================================================== 分段控件
def _seg_qss() -> str:
    """分段按钮的样式：**现取**主题色（写死的话换主题时这一块颜色不变）。"""
    return f"""
QPushButton#Seg {{
    background: {style.PANEL};
    border: 1px solid {style.LINE};
    color: {style.TEXT_DIM};
    padding: 5px 4px;
    font-size: 12px;
}}
QPushButton#Seg:checked {{
    background: {style.ACCENT_DIM};
    border-color: {style.ACCENT};
    color: {style.ON_ACCENT};
    font-weight: 600;
}}
QPushButton#Seg:hover:!checked {{
    background: {style.CARD};
    color: {style.TEXT};
}}
"""


class SegmentedControl(QtWidgets.QWidget):
    """等宽分段按钮，替代下拉框，视觉上更像仪器面板。"""

    changed = QtCore.Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._keys: list[str] = []
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)
        for i, (key, label) in enumerate(options):
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName("Seg")
            btn.setCheckable(True)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.setProperty("segIndex", i)
            self._group.addButton(btn, i)
            lay.addWidget(btn)
            self._keys.append(key)
        self.setStyleSheet(_seg_qss())
        self._group.idClicked.connect(self._on_clicked)
        if self._keys:
            self.set_value(self._keys[0])

    def restyle(self) -> None:
        """换主题：控件自己的样式表（不跟着 app 的全局 QSS 走）要重拼一遍。"""
        self.setStyleSheet(_seg_qss())

    def _on_clicked(self, idx: int) -> None:
        self.changed.emit(self._keys[idx])

    def value(self) -> str:
        idx = self._group.checkedId()
        return self._keys[idx] if 0 <= idx < len(self._keys) else ""

    def set_value(self, key: str) -> None:
        if key not in self._keys:
            return
        self._group.button(self._keys.index(key)).setChecked(True)

    def set_enabled_keys(self, enabled: set[str]) -> None:
        for i, key in enumerate(self._keys):
            self._group.button(i).setEnabled(key in enabled)


# ==================================================================== 滑杆行
class SliderRow(QtWidgets.QWidget):
    """标题 + 滑杆（可选精细输入框）。

    ``spin=True`` 时在滑杆**左侧**给一个可键入的数字框：滑杆拖不准，尤其
    对比度、波形幅度这类要精确复现的设定，有个能敲数值的地方顺手得多。
    两者双向同步，改动任一边都会发 ``valueChanged``。
    """

    valueChanged = QtCore.Signal(int)
    released = QtCore.Signal(int)

    def __init__(self, title: str, parent=None, *, spin: bool = False,
                 suffix: str = ""):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("Hint")
        self.readout = ValueLabel("0")
        self.readout.setFont(style.mono_font(9))
        head.addWidget(self.title)
        head.addStretch(1)
        # 有精细输入框时不再单占一行读数：两个同值的数字只会显得啰嗦
        if not spin:
            head.addWidget(self.readout)
        lay.addLayout(head)

        self._suffix = suffix
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.editor: WheelSafeSpinBox | None = None
        if spin:
            self.editor = WheelSafeSpinBox()
            self.editor.setRange(0, 0)
            self.editor.setSuffix(suffix)
            self.editor.setFixedWidth(70)
            self.editor.setKeyboardTracking(False)   # 回车/失焦才提交，免得边敲边重绘
            self.editor.valueChanged.connect(self._on_editor)
            row.addWidget(self.editor)
        self.slider = WheelSafeSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        row.addWidget(self.slider, 1)
        lay.addLayout(row)
        self._sync_editor(0)

    def _sync_editor(self, v: int) -> None:
        if self.editor is None:
            return
        self.editor.blockSignals(True)
        self.editor.setValue(int(v))
        self.editor.blockSignals(False)

    def set_tooltip(self, text: str) -> None:
        """整行设置提示。

        这一行由标题、滑杆（可能还有数字框）拼成，鼠标通常落在子控件上；
        只对自己的空白处设提示基本看不到，所以逐个设一遍。
        """
        for w in (self, self.title, self.slider, self.editor):
            if w is not None:
                w.setToolTip(text)

    def _on_editor(self, v: int) -> None:
        if self.slider.value() != v:
            self.slider.blockSignals(True)
            self.slider.setValue(int(v))
            self.slider.blockSignals(False)
        self.readout.setText(str(int(v)) + self._suffix)
        self.valueChanged.emit(int(v))

    def _on_change(self, v: int) -> None:
        self.readout.setText(str(v) + self._suffix)
        self._sync_editor(v)
        self.valueChanged.emit(v)

    def set_range(self, lo: int, hi: int, value: int | None = None) -> None:
        """设定范围（滑杆与输入框一起）并可选设初值。不主动发信号。"""
        lo, hi = int(lo), max(int(lo), int(hi))
        self.slider.blockSignals(True)
        self.slider.setRange(lo, hi)
        if value is not None:
            self.slider.setValue(int(max(lo, min(int(value), hi))))
        self.slider.blockSignals(False)
        if self.editor is not None:
            self.editor.blockSignals(True)
            self.editor.setRange(lo, hi)
            self.editor.setValue(self.slider.value())
            self.editor.blockSignals(False)
        self.readout.setText(str(self.slider.value()) + self._suffix)

    def configure(self, maximum: int, value: int = 0, suffix: str = "") -> None:
        self._suffix = suffix
        if self.editor is not None:
            self.editor.setSuffix(suffix)
        self.set_range(0, max(0, maximum), max(0, min(value, max(0, maximum))))

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int) -> None:
        """程序化赋值：屏蔽信号，避免与外部状态互相触发。"""
        self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self.slider.blockSignals(False)
        self._on_change(self.slider.value())


# ==================================================================== 播放头
class PlayheadTrack(QtWidgets.QWidget):
    """细轨道 + 刻度 + 游标，支持点击与拖动定位。"""

    seek = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._count = 0
        self._pos = 0
        self._hover = -1
        self._dragging = False

    def set_range(self, count: int, pos: int = 0) -> None:
        self._count = max(0, int(count))
        self._pos = max(0, min(int(pos), max(0, self._count - 1)))
        self.update()

    def set_position(self, pos: int) -> None:
        pos = max(0, min(int(pos), max(0, self._count - 1)))
        if pos != self._pos:
            self._pos = pos
            self.update()

    def position(self) -> int:
        return self._pos

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, ev) -> None:
        if self._count <= 0:
            # **没有数据时什么都不画**：只画一条空轨道的话，看起来就是一个"空进度条"，
            # 用户会以为软件卡在某个进度上（软件刚打开时那条就是它）。高度保持不变，
            # 免得载入数据时左侧面板跳一下。
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        mid = h * 0.5

        p.setPen(QtGui.QPen(QtGui.QColor(style.LINE_HI), 1))
        p.drawLine(2, int(mid), w - 2, int(mid))

        if self._count > 0:
            # 每 1/10 一格刻度，首尾加粗
            step = max(1, self._count // 10)
            p.setPen(QtGui.QPen(QtGui.QColor(style.LINE_HI), 1))
            for i in range(0, self._count, step):
                x = self._x_of(i, w)
                p.drawLine(int(x), int(mid - 3), int(x), int(mid + 3))

            if 0 <= self._hover < self._count:
                xh = self._x_of(self._hover, w)
                p.setPen(QtGui.QPen(QtGui.QColor(style.TEXT_MUTE), 1))
                p.drawLine(int(xh), int(mid - 6), int(xh), int(mid + 6))

            x = self._x_of(self._pos, w)
            p.setPen(QtGui.QPen(QtGui.QColor(style.ACCENT), 1))
            p.drawLine(int(x), 4, int(x), h - 4)
            p.setBrush(QtGui.QColor(style.ACCENT))
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.drawEllipse(QtCore.QPointF(x, mid), 3.5, 3.5)

    def _x_of(self, index: int, w: int) -> float:
        if self._count <= 1:
            return w * 0.5
        return 2 + (w - 4) * (index / (self._count - 1))

    def _index_of(self, x: float) -> int:
        if self._count <= 1:
            return 0
        w = self.width()
        frac = (x - 2) / max(1.0, w - 4)
        return int(round(max(0.0, min(1.0, frac)) * (self._count - 1)))

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, ev) -> None:
        if ev.button() == QtCore.Qt.MouseButton.LeftButton and self._count > 0:
            self._dragging = True
            self.seek.emit(self._index_of(ev.position().x()))

    def mouseMoveEvent(self, ev) -> None:
        idx = self._index_of(ev.position().x())
        if idx != self._hover:
            self._hover = idx
            self.update()
        if self._dragging:
            self.seek.emit(idx)

    def mouseReleaseEvent(self, ev) -> None:
        self._dragging = False
        self.update()

    def leaveEvent(self, ev) -> None:
        self._hover = -1
        self.update()


# ==================================================================== 色带选择
class ColormapCombo(WheelSafeComboBox):
    """下拉项带渐变缩略图，比纯文字更容易选。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QtCore.QSize(64, 12))
        for label, key in render.COLORMAP_LABELS:
            self.addItem(self._gradient_icon(key), label, key)

    @staticmethod
    def _gradient_icon(key: str) -> QtGui.QIcon:
        strip = render.lut(key, 64)[None, :, :]
        img = QtGui.QImage(strip.tobytes(), 64, 1, 64 * 4,
                           QtGui.QImage.Format.Format_RGBA8888).copy()
        return QtGui.QIcon(QtGui.QPixmap.fromImage(img))

    def cmap(self) -> str:
        return self.currentData() or "gray"

    def set_cmap(self, key: str) -> None:
        for i in range(self.count()):
            if self.itemData(i) == key:
                self.setCurrentIndex(i)
                return


# ==================================================================== 变量表
class VariableTable(QtWidgets.QTableWidget):
    # 列不要太多：左栏一共才三百来像素，把"读取方式"并进大小列，
    # 否则最后一列会被挤掉、看不见。
    HEADERS = ("变量", "形状", "dtype", "大小")

    def __init__(self, parent=None):
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(self.HEADERS)):
            hh.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self._infos: list[VariableInfo] = []

    def fill(self, infos: list[VariableInfo]) -> None:
        self._infos = infos
        self.setRowCount(len(infos))
        for r, info in enumerate(infos):
            # 表格列宽紧张，形状用紧凑写法（×两侧不留空格），完整信息放在提示里
            shape = "×".join(str(v) for v in info.shape) or "标量"
            size = info.size_text + (f" · {info.note}" if info.note else "")
            cells = (info.key, shape, info.dtype, size)
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if c >= 1:
                    item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(f"{info.key}\n形状 {' × '.join(str(v) for v in info.shape) or '标量'}"
                                f"\n类型 {info.dtype}\n大小 {info.size_text}"
                                + (f"\n读取方式 {info.note}" if info.note else ""))
                self.setItem(r, c, item)
        if infos:
            self.selectRow(0)

    def keys(self) -> list[str]:
        return [i.key for i in self._infos]

    def info_of(self, row: int) -> VariableInfo | None:
        return self._infos[row] if 0 <= row < len(self._infos) else None

    def current_info(self) -> VariableInfo | None:
        return self.info_of(self.currentRow())

    def info_of_key(self, key: str) -> VariableInfo | None:
        return next((i for i in self._infos if i.key == key), None)


# ==================================================================== 轴序确认
_ROLE_ORDER = (ROLE_SHOT, ROLE_RECV, ROLE_TIME)


class _AutoHideLabel(QtWidgets.QLabel):
    """没话说时自动收起来的标签。

    一直摆着的空 QLabel 会被全局样式刷上一层比面板底色更暗的背景，看着就是
    「一个一直用不到的框」（错误区、格式说明都踩过这个坑）。这里让 setText 顺带
    管显隐，调用方照旧只管 setText。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setVisible(bool(text))                  # 构造时就按有没有话说定显隐

    def setText(self, text: str) -> None:            # noqa: N802 （Qt 接口名）
        super().setText(text)
        self.setVisible(bool(text))


class AxisOrderDialog(QtWidgets.QDialog):
    """轴序人工确认。自动猜测只作为默认值，必须由用户过目。"""

    def __init__(self, filename: str, shape: tuple[int, ...], roles: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认数据轴序")
        self.setModal(True)
        self.setMinimumWidth(430)
        self._shape = shape
        self._boxes: list[QtWidgets.QComboBox] = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        title = QtWidgets.QLabel(filename)
        title.setObjectName("Title")
        root.addWidget(title)

        hint = QtWidgets.QLabel(
            f"数据形状：{' × '.join(str(v) for v in shape)}\n"
            "轴序没有通用约定（MATLAB 常为 时间×道，Python 常为 道×时间），\n"
            "请核对每一维的物理含义。长度通常能帮你判断哪一维是时间。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        opts = role_options()
        for i, n in enumerate(shape):
            lab = QtWidgets.QLabel(f"轴 {i}")
            lab.setObjectName("Hint")
            length = QtWidgets.QLabel(f"长度 {n}")
            length.setObjectName("Value")
            box = WheelSafeComboBox()
            box.addItems(opts)
            if i < len(roles):
                box.setCurrentText(ROLE_LABELS.get(roles[i], "忽略"))
            grid.addWidget(lab, i, 0)
            grid.addWidget(length, i, 1)
            grid.addWidget(box, i, 2)
            self._boxes.append(box)
        root.addLayout(grid)

        self.remember = QtWidgets.QCheckBox("记住此文件的选择（下次自动套用）")
        self.remember.setChecked(True)
        root.addWidget(self.remember)

        self.error = _AutoHideLabel("")
        self.error.setStyleSheet(f"color: {style.ERR};")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("确定")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _validate(self) -> None:
        roles = self.roles()
        if roles.count(ROLE_SHOT) > 1 or roles.count(ROLE_RECV) > 1 or roles.count(ROLE_TIME) > 1:
            self.error.setText("同一个物理维度被指定了多次，请重新分配。")
            return
        if ROLE_TIME not in roles:
            self.error.setText("必须指定哪一维是「时间」。")
            return
        need = 3 if len(self._shape) >= 3 else 2 if len(self._shape) == 2 else 1
        used = sum(1 for r in roles if r != "ignore")
        if used < need:
            self.error.setText(f"{len(self._shape)} 维数据需要指定 {need} 个物理维度。")
            return
        self.accept()

    def roles(self) -> list[str]:
        return [_role_of(b.currentText()) for b in self._boxes]

    def should_remember(self) -> bool:
        return self.remember.isChecked()


def _role_of(label: str) -> str:
    from .loaders import label_to_role
    return label_to_role(label)


def ask_axis_order(filename: str, shape: tuple[int, ...],
                   initial: list[str] | None = None, parent=None
                   ) -> tuple[list[str], bool] | None:
    """弹出轴序确认框，返回 ``(roles, 是否记住)`` 或 None（用户取消）。"""
    roles = list(initial) if initial else guess_roles(shape)
    roles += ["ignore"] * (len(shape) - len(roles))
    dlg = AxisOrderDialog(filename, shape, roles, parent)
    if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        return dlg.roles(), dlg.should_remember()
    return None


# ==================================================================== 折叠按钮
class ChevronButton(QtWidgets.QToolButton):
    """面板标题栏上的折叠/展开按钮。

    ``direction`` 决定箭头朝向，与面板的收缩方向一致：
    ``down`` 上下收（剖面 / 单道面板），``left`` 向左收（左侧设置面板），
    ``right`` 向右收（右侧三维面板）。
    """

    _GLYPH = {"down": ("▾", "▸"), "left": ("◀", "▶"), "right": ("▶", "◀")}

    def __init__(self, parent=None, direction: str = "down"):
        super().__init__(parent)
        self.setObjectName("Chevron")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self._direction = direction if direction in self._GLYPH else "down"
        self._expanded = True
        self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        on, off = self._GLYPH[self._direction]
        self.setText(on if self._expanded else off)
        self.setToolTip("折叠此面板" if self._expanded else "展开此面板")


# ==================================================================== 数组数值
class ArrayViewDialog(QtWidgets.QDialog):
    """查看一维（或标量）数组：既能读具体数值，也能看波形。

    这类变量往往是采样时间轴、坐标轴、单道记录或子波 —— 有时要"数值是多少"，
    有时要"波形长什么样"，所以上面给一张曲线、下面给一张数值表。
    """

    MAX_ROWS = 50000

    def __init__(self, title: str, arr, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查看一维数据")
        self.setModal(True)
        self.resize(510, 660)
        self._values = np.asarray(arr).ravel()

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)

        head = QtWidgets.QLabel(title)
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        info = QtWidgets.QLabel(self._summary(arr))
        info.setObjectName("Hint")
        info.setWordWrap(True)
        root.addWidget(info)

        if self._values.size >= 2:
            root.addWidget(self._make_plot(), 2)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("序号", "数值"))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFont(style.mono_font(9))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._fill_table()

        n = self._values.size
        if n > self.MAX_ROWS:
            note = QtWidgets.QLabel(
                f"数值较多，表格只显示前 {self.MAX_ROWS} 个；"
                "「复制全部」会复制完整内容。")
            note.setObjectName("Hint")
            note.setWordWrap(True)
            root.addWidget(note)
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("Hint")
        row.addWidget(self.status, 1)
        btn_copy = QtWidgets.QPushButton("复制全部")
        btn_copy.setObjectName("Primary")
        btn_copy.clicked.connect(self._copy_all)
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_copy)
        row.addWidget(btn_close)
        root.addLayout(row)

    def _make_plot(self) -> QtWidgets.QWidget:
        """数值曲线：单道记录、子波这类数据一眼就能看出波形。"""
        plot = pg.PlotWidget(background=style.GL_BG)
        plot.setMenuEnabled(False)
        plot.showGrid(x=True, y=True, alpha=0.12)
        plot.setMinimumHeight(150)
        plot.setLabel("bottom", "序号")
        plot.setLabel("left", "数值")
        vals = self._values
        if vals.size <= 200_000:
            plot.plot(np.arange(vals.size), vals.astype(np.float64),
                      pen=pg.mkPen(style.ACCENT, width=1))
        else:
            step = max(1, vals.size // 200_000)
            plot.plot(np.arange(0, vals.size, step),
                      vals[::step].astype(np.float64),
                      pen=pg.mkPen(style.ACCENT, width=1), downsampleMethod="subsample")
        plot.addItem(pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                     pen=pg.mkPen(style.LINE_HI, width=1)),
                     ignoreBounds=True)
        return plot

    @staticmethod
    def _summary(arr) -> str:
        a = np.asarray(arr)
        vals = np.asarray(a).ravel()
        text = f"形状 {' × '.join(str(v) for v in a.shape) if a.shape else '标量'}　" \
               f"类型 {a.dtype}　个数 {vals.size}"
        if vals.size:
            finite = vals[np.isfinite(vals)] if vals.dtype.kind == "f" else vals
            if finite.size:
                text += (f"\n最小 {float(np.min(finite)):.6g}　"
                         f"最大 {float(np.max(finite)):.6g}　"
                         f"均值 {float(np.mean(finite)):.6g}")
        return text

    def _fill_table(self) -> None:
        n = min(self._values.size, self.MAX_ROWS)
        self.table.setRowCount(n)
        for i in range(n):
            idx = QtWidgets.QTableWidgetItem(str(i))
            val = QtWidgets.QTableWidgetItem(self._fmt(self._values[i]))
            val.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                 | QtCore.Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 0, idx)
            self.table.setItem(i, 1, val)

    @staticmethod
    def _fmt(v) -> str:
        if isinstance(v, (np.floating, float)):
            return f"{float(v):.6g}"
        return str(v)

    def _copy_all(self) -> None:
        lines = []
        for v in self._values:
            if isinstance(v, (np.floating, float)):
                lines.append(repr(float(v)))       # 完整精度
            else:
                lines.append(str(v))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        self.status.setText(f"已复制 {len(lines)} 个数值到剪贴板")


# ==================================================================== 导出对话框
class ExportDialog(QtWidgets.QDialog):
    """导出 / 转换：一个对话框里按「导出内容」分层组织四种动作。

    四种内容的性质差别很大，所以先用分段控件选「导出什么」，下面再给对应的设置：

    * **整卷数据** —— 写出整卷 (S,R,T) 矩阵（.npy / .npz / .mat），或合成一套最小
      但正确的道头写成 SEG-Y / SU；
    * **逐剖面** —— 沿一个方向切开，每片一个文件；**可选片层范围**（起点 / 终点），
      还能一键切到「只导出当前显示的剖面」；对比模式下可一次导出全部数据源；
    * **剖面图** —— 把当前剖面**重画**成一张论文用图（白底、坐标轴按 dt/dx/ds 标出
      秒 / 米、带色条），PNG 或 SVG；
    * **波形图** —— 同理，把当前单道波形重画成论文用图。

    入口只保留这一个（顶栏按钮 / Ctrl+E）：自定义导出、部分片层、剖面/波形图片导出
    都在这里分层，不再散落到多处。
    """

    CONTENT_MODES = [("整卷数据", "volume"), ("逐剖面", "slices"),
                     ("剖面图", "slice_image"), ("波形图", "wave_image")]
    FORMATS = {
        "volume": [("NumPy 单文件 (.npy)", "npy"), ("NumPy 容器 (.npz)", "npz"),
                   ("MATLAB (.mat)", "mat"), ("SEG-Y (.sgy)", "sgy"),
                   ("Seismic Unix (.su)", "su")],
        "slices": [("NumPy 单文件 (.npy)", "npy"), ("NumPy 容器 (.npz)", "npz"),
                   ("MATLAB (.mat)", "mat")],
        "slice_image": [("PNG 位图 (.png)", "png"), ("SVG 矢量 (.svg)", "svg")],
        "wave_image": [("PNG 位图 (.png)", "png"), ("SVG 矢量 (.svg)", "svg")],
    }
    IMAGE_MODES = ("slice_image", "wave_image")
    SUFFIX = {"npy": ".npy", "npz": ".npz", "mat": ".mat", "sgy": ".sgy",
              "su": ".su", "png": ".png", "svg": ".svg"}

    def __init__(self, entries, active: int, default_dir, default_stem: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出 / 转换")
        self.setModal(True)
        self.setMinimumWidth(560)
        # entries: [{"label", "vol", "pos"}] —— 已载入的数据集（含各自的当前切片位置）
        self._entries = list(entries)
        self._active = max(0, min(int(active), len(self._entries) - 1))
        self._vol = self._entries[self._active]["vol"]
        self._dir = str(default_dir)
        self._stem = default_stem
        self._fitted = False                        # 首次弹出时统一一次尺寸

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QtWidgets.QLabel(f"导出数据　{self._vol.name}")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        # ---- 导出内容：三种动作在这里分层
        self.content_ctl = SegmentedControl(
            [(key, name) for name, key in self.CONTENT_MODES])
        self.content_ctl.set_value("volume")
        self.content_ctl.changed.connect(self._on_content)
        root.addWidget(self.content_ctl)

        # ---- 数据源（只有对比模式、且内容不是整卷时才出现）
        self.scope_row = QtWidgets.QWidget()
        srow = QtWidgets.QHBoxLayout(self.scope_row)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(8)
        slab = QtWidgets.QLabel("数据源")
        slab.setObjectName("Hint")
        self.combo_scope = WheelSafeComboBox()
        self.combo_scope.addItem("当前数据", "active")
        self.combo_scope.addItem("全部对比数据", "all")
        self.combo_scope.currentIndexChanged.connect(lambda _i: self._refresh_texts())
        srow.addWidget(slab)
        srow.addWidget(self.combo_scope, 1)
        root.addWidget(self.scope_row)

        # ---- 格式
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.lab_fmt = QtWidgets.QLabel("目标格式")
        self.lab_fmt.setObjectName("Hint")
        self.combo_fmt = WheelSafeComboBox()
        self.combo_fmt.currentIndexChanged.connect(self._on_format)
        row.addWidget(self.lab_fmt)
        row.addWidget(self.combo_fmt, 1)
        root.addLayout(row)

        # ---- 路径
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.lab_path = QtWidgets.QLabel("保存到")
        self.lab_path.setObjectName("Hint")
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setMinimumWidth(300)
        btn_browse = QtWidgets.QPushButton("浏览…")
        btn_browse.setObjectName("Ghost")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(self.lab_path)
        row.addWidget(self.path_edit, 1)
        row.addWidget(btn_browse)
        root.addLayout(row)

        # ---- 规模 / 提示
        self.scale_label = QtWidgets.QLabel("")
        self.scale_label.setObjectName("Hint")
        self.scale_label.setWordWrap(True)
        root.addWidget(self.scale_label)

        self.note_label = _AutoHideLabel("")
        self.note_label.setObjectName("Hint")
        self.note_label.setWordWrap(True)
        root.addWidget(self.note_label)

        # ---- 逐剖面设置块
        self.slices_body = QtWidgets.QFrame()
        self.slices_body.setObjectName("SubPanel")
        body = QtWidgets.QVBoxLayout(self.slices_body)
        body.setContentsMargins(18, 0, 0, 2)
        body.setSpacing(6)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.combo_axis = WheelSafeComboBox()
        for title, key in exporter.SLICE_AXES:
            self.combo_axis.addItem(title, key)
        self.combo_axis.currentIndexChanged.connect(lambda _i: self._on_axis())
        self.edit_name = QtWidgets.QLineEdit(self._stem)     # 先填一个具体名字，用户可改
        self.edit_name.setPlaceholderText("可留空，留空就是 0 / 1 / 2 …")
        self.edit_name.setToolTip(
            "生成的文件名 = 文件名 + 下划线 + 序号 + 目标格式，例如 demo_7.mat。\n"
            "序号就是该方向的炮号 / 道号 / 时间采样号。\n"
            "留空则直接用序号做文件名，例如 7.mat。")
        self.edit_name.textChanged.connect(lambda _t: self._refresh_texts())
        for i, (label, w) in enumerate([("剖面方向", self.combo_axis),
                                       ("文件名", self.edit_name)]):
            lb = QtWidgets.QLabel(label)
            lb.setObjectName("Hint")
            grid.addWidget(lb, i, 0)
            grid.addWidget(w, i, 1)
        body.addLayout(grid)

        # 片层范围（起 / 止，闭区间）+ 「设为当前」快捷按钮
        rrow = QtWidgets.QHBoxLayout()
        rrow.setContentsMargins(0, 0, 0, 0)
        rrow.setSpacing(8)
        rlab = QtWidgets.QLabel("片层范围")
        rlab.setObjectName("Hint")
        self.spin_start = WheelSafeSpinBox()
        self.spin_stop = WheelSafeSpinBox()
        for sp in (self.spin_start, self.spin_stop):
            sp.setRange(0, 0)
            sp.setMinimumWidth(78)
            sp.setToolTip("片层下标（从 0 开始）；起止都是闭区间端点。")
            sp.valueChanged.connect(lambda _v: self._refresh_texts())
        tilde = QtWidgets.QLabel("~")
        tilde.setObjectName("Hint")
        self.btn_cur = QtWidgets.QPushButton("设为当前")
        self.btn_cur.setObjectName("Ghost")
        self.btn_cur.setToolTip("把范围设为当前剖面所在的那一片")
        self.btn_cur.clicked.connect(self._set_range_current)
        rrow.addWidget(rlab)
        rrow.addWidget(self.spin_start)
        rrow.addWidget(tilde)
        rrow.addWidget(self.spin_stop)
        rrow.addWidget(self.btn_cur)
        rrow.addStretch(1)
        body.addLayout(rrow)

        self.chk_current = QtWidgets.QCheckBox(
            "只导出当前显示的剖面（对比时含全部数据源）")
        self.chk_current.setToolTip(
            "勾上就只导出当前剖面面板正在显示的那一片，忽略上面的片层范围。\n"
            "多数据对比时，每份数据各导出自己当前显示的那一片。")
        self.chk_current.toggled.connect(self._on_current_toggled)
        body.addWidget(self.chk_current)

        # 一句话说清规则 + 一个具体例子，两行永远有内容（空标签会被样式刷成暗方块）
        self.slice_rule = QtWidgets.QLabel("")
        self.slice_rule.setObjectName("Hint")
        self.slice_rule.setWordWrap(True)
        body.addWidget(self.slice_rule)

        self.slice_preview = QtWidgets.QLabel("")
        self.slice_preview.setObjectName("Hint")
        self.slice_preview.setWordWrap(True)
        body.addWidget(self.slice_preview)
        root.addWidget(self.slices_body)

        # ---- 图片说明（剖面图 / 波形图）
        self.image_note = QtWidgets.QLabel(
            "导出的是**论文用图**：白底、深色坐标轴，横纵轴读数按设置面板里的\n"
            "dt / dx / ds 换算成秒与米，剖面图另带振幅色条。PNG 为位图，SVG 为矢量。\n"
            "剖面图用的是当前切片的全分辨率数据（不是屏幕上的抽稀画面）；AGC 开着\n"
            "时会做同样的增益处理。多数据对比时，每份数据各导出一个文件。")
        self.image_note.setObjectName("Hint")
        self.image_note.setWordWrap(True)
        root.addWidget(self.image_note)

        # ---- SEG-Y / SU 专用参数
        # 排版按"哪些是必填、哪些勾了才要填"分成两层：
        #   ① 采样间隔 —— 任何情况下都要写，单独一行，标注"必填"
        #   ② 规则坐标 —— 勾选才需要填下面两个间距，所以两个间距缩进放在复选框下面
        # 这样不用读文字说明也能看出依赖关系。
        self.seis_box = QtWidgets.QFrame()
        self.seis_box.setObjectName("Panel")
        sbox = QtWidgets.QVBoxLayout(self.seis_box)
        sbox.setContentsMargins(12, 10, 12, 10)
        sbox.setSpacing(7)
        sbox.addWidget(SectionLabel("道头参数"))

        dt_us = int(round(self._vol.dt * 1e6)) or 1000
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab_dt = QtWidgets.QLabel("采样间隔（必填）")
        lab_dt.setObjectName("Hint")
        self.spin_dt_us = WheelSafeSpinBox()
        self.spin_dt_us.setRange(1, 65535)
        self.spin_dt_us.setValue(min(65535, max(1, dt_us)))
        self.spin_dt_us.setSuffix(" µs")
        self.spin_dt_us.setMinimumWidth(120)
        self.spin_dt_us.setToolTip(
            "写入文件头（Interval）与每道道头（TRACE_SAMPLE_INTERVAL）。\n"
            "每道采样数、道数自动取自当前数据，不用填。")
        row.addWidget(lab_dt)
        row.addWidget(self.spin_dt_us, 1)
        sbox.addLayout(row)

        self.need_label = QtWidgets.QLabel(
            f"每道 {self._vol.nt} 个采样、共 {self._vol.ns * self._vol.nr} 道 —— "
            "这两项自动取自数据。")
        self.need_label.setObjectName("Hint")
        self.need_label.setWordWrap(True)
        sbox.addWidget(self.need_label)

        sline = QtWidgets.QFrame()
        sline.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        sline.setStyleSheet(f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;")
        sbox.addWidget(sline)

        self.chk_coords = QtWidgets.QCheckBox("写入坐标道头（按间距推算，非实测坐标，可选）")
        self.chk_coords.setChecked(True)
        self.chk_coords.setToolTip(
            "勾选后按下面两个间距推算一套「规则」几何写进道头：\n"
            "SourceX = 炮号 × ds\n"
            "GroupX  = SourceX + 道号 × dx\n"
            "offset  = 道号 × dx\n"
            "等价于「排列随炮整体移动」的滑动排列，三者自洽（offset == GroupX − SourceX）。\n"
            "dx 带小数时会写入坐标标量，避免小数被取整。\n\n"
            "暂不支持每炮观测系统排列不同的情况。")
        self.chk_coords.toggled.connect(self._sync_coords_enabled)
        sbox.addWidget(self.chk_coords)

        self.coords_body = QtWidgets.QFrame()
        self.coords_body.setObjectName("SubPanel")
        body = QtWidgets.QVBoxLayout(self.coords_body)
        body.setContentsMargins(18, 0, 0, 2)
        body.setSpacing(6)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.spin_dx = WheelSafeDoubleSpinBox()
        self.spin_dx.setRange(0.0, 1e6)
        self.spin_dx.setDecimals(3)
        self.spin_dx.setValue(float(self._vol.dx))
        self.spin_dx.setSuffix(" m")
        self.spin_dx.setMinimumWidth(110)
        self.spin_ds = WheelSafeDoubleSpinBox()
        self.spin_ds.setRange(0.0, 1e6)
        self.spin_ds.setDecimals(3)
        self.spin_ds.setValue(float(self._vol.ds))
        self.spin_ds.setSuffix(" m")
        self.spin_ds.setMinimumWidth(110)
        for i, (name, w) in enumerate([("检波器间距 dx", self.spin_dx),
                                       ("炮点间距 ds", self.spin_ds)]):
            lb = QtWidgets.QLabel(name)
            lb.setObjectName("Hint")
            w.setToolTip("按下式推算坐标：SourceX = 炮号 × ds，"
                         "GroupX = SourceX + 道号 × dx，offset = 道号 × dx")
            grid.addWidget(lb, i, 0)
            grid.addWidget(w, i, 1)
        body.addLayout(grid)

        rule = QtWidgets.QLabel("SourceX = 炮号×ds　GroupX = SourceX + 道号×dx　offset = 道号×dx")
        rule.setObjectName("Hint")
        rule.setWordWrap(True)
        body.addWidget(rule)
        sbox.addWidget(self.coords_body)

        self.seis_note = QtWidgets.QLabel("除此之外不继承源文件道头。")
        self.seis_note.setObjectName("Hint")
        self.seis_note.setWordWrap(True)
        sbox.addWidget(self.seis_note)
        root.addWidget(self.seis_box)
        self._sync_coords_enabled()

        self.error = _AutoHideLabel("")
        self.error.setStyleSheet(f"color: {style.ERR};")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self._ok = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("导出")
        self._ok.setObjectName("Primary")
        btns.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._on_content()

    # ---------------------------------------------------------------- 取值
    def content(self) -> str:
        """导出内容：``volume`` 整卷 / ``slices`` 逐剖面 / ``image`` 当前剖面图片。"""
        return self.content_ctl.value() or "volume"

    def fmt(self) -> str:
        return self.combo_fmt.currentData() or "npy"

    def path(self) -> str:
        return self.path_edit.text().strip()

    def dt_us(self) -> int:
        return int(self.spin_dt_us.value())

    def dx(self) -> float:
        return float(self.spin_dx.value())

    def ds(self) -> float:
        return float(self.spin_ds.value())

    def with_coords(self) -> bool:
        return self.chk_coords.isChecked()

    def slice_axis(self) -> str:
        return self.combo_axis.currentData() or "shot"

    def slice_range(self) -> tuple[int, int]:
        """片层范围（起, 止），闭区间。"""
        return int(self.spin_start.value()), int(self.spin_stop.value())

    def current_only(self) -> bool:
        """是否只导出当前显示的剖面。"""
        return self.content() == "slices" and self.chk_current.isChecked()

    def name_prefix(self) -> str:
        """单片文件名的前缀（可留空，留空就是纯序号）。"""
        return self.edit_name.text().strip()

    def dataset_scope(self) -> str:
        """导出哪些数据源：``active`` 只导当前数据，``all`` 含全部对比数据。"""
        return "all" if self._scope_all() else "active"

    def entry_count(self) -> int:
        return len(self._entries)

    def is_image(self) -> bool:
        """是否是「图片导出」内容（剖面图 / 波形图）。"""
        return self.content() in self.IMAGE_MODES

    def _scope_all(self) -> bool:
        # 只用"条目数"判断而不是 isVisible()：弹出前（或离屏测试时）面板还没显示，
        # isVisible() 一律为 False，会把"全部对比数据"误判成"当前数据"。
        return (self.content() in ("slices", "slice_image")
                and len(self._entries) > 1
                and self.combo_scope.currentData() == "all")

    def _current_index(self, axis: str) -> int:
        return int(self._entries[self._active]["pos"].get(axis, 0))

    # ---------------------------------------------------------------- 状态同步
    def _sync_coords_enabled(self) -> None:
        """勾了「写入坐标道头」才需要填下面两个间距 —— 没勾就把它们置灰。

        用置灰而不是隐藏：对话框高度不会跳，而且能看出"这里有两个参数，
        勾上就能填"。（:disabled 的样式在 style.py 里，现在看得出来了。）
        """
        self.coords_body.setEnabled(self.chk_coords.isChecked())

    def _sync_range(self, reset: bool = False) -> None:
        """把片层范围的上下限对到当前方向的片数，并按需摆好初值 / 置灰。"""
        axis = self.slice_axis()
        total = max(1, exporter.slice_count(self._vol.data, axis))
        hi = total - 1
        on = self.chk_current.isChecked()
        if on:
            start = stop = self._current_index(axis)
        elif reset:
            start, stop = 0, hi
        else:
            start, stop = self.spin_start.value(), self.spin_stop.value()
        start = max(0, min(start, hi))
        stop = max(0, min(stop, hi))
        for sp, val in ((self.spin_start, start), (self.spin_stop, stop)):
            sp.blockSignals(True)
            sp.setRange(0, hi)
            sp.setValue(val)
            sp.blockSignals(False)
        # 勾了「只导出当前剖面」时范围由程序决定，这几个控件置灰
        for w in (self.spin_start, self.spin_stop, self.btn_cur):
            w.setEnabled(not on)

    # ---------------------------------------------------------------- 交互
    def _on_content(self, _key: str = "") -> None:
        """切换导出内容：重建格式清单、显隐对应设置块。"""
        content = self.content()
        self.combo_fmt.blockSignals(True)
        self.combo_fmt.clear()
        for name, key in self.FORMATS[content]:
            self.combo_fmt.addItem(name, key)
        self.combo_fmt.setCurrentIndex(0)
        self.combo_fmt.blockSignals(False)
        if content == "slices":
            self._sync_range(reset=True)
        self._on_format()

    def _on_format(self, _index: int | None = None) -> None:
        content = self.content()
        seis = content == "volume" and self.fmt() in exporter.SEISMIC_KEYS
        self.seis_box.setVisible(seis)
        self.slices_body.setVisible(content == "slices")
        self.image_note.setVisible(self.is_image())
        self.scope_row.setVisible(
            content in ("slices", "slice_image") and len(self._entries) > 1)
        if content == "volume":
            self.note_label.setText("" if seis else
                                    "⚠ 只导出数据矩阵（形状 = 炮 × 检波器 × 时间）：\n"
                                    "不含 dt / dx / ds 等元信息（标尺会丢）；缺道以 0 填充。")
        else:
            self.note_label.setText("")
        self.error.setText("")
        self._refresh_texts()

    def _on_axis(self) -> None:
        self._sync_range(reset=True)
        self._refresh_texts()

    def _on_current_toggled(self, checked: bool = False) -> None:
        # "当前剖面"这个快捷选项本身就是为了对比 —— 有多份数据时自动切到全部数据源，
        # 免得勾了却只导出一份，与勾选框文字说的不一致。
        if checked and len(self._entries) > 1:
            self.combo_scope.setCurrentIndex(1)
        self._sync_range()
        self._refresh_texts()

    def _set_range_current(self) -> None:
        """把范围设为当前剖面所在的那一片。"""
        cur = self._current_index(self.slice_axis())
        for sp in (self.spin_start, self.spin_stop):
            sp.blockSignals(True)
            sp.setValue(cur)
            sp.blockSignals(False)
        self._refresh_texts()

    def _refresh_texts(self) -> None:
        self._refresh_path()
        self._refresh_scale_label()
        self._refresh_slice_texts()
        self._refit_height()

    def _refresh_path(self) -> None:
        """路径栏的语义随内容变：逐剖面填**文件夹**，其余填**文件**。

        标签文字**不跟着变** —— 「保存到」和「保存到文件夹」宽度不同，一改就会把
        右边的输入框挤得左右跳。文件夹这件事写在下方设置块里。
        """
        cur = self.path()
        all_suffix = set(self.SUFFIX.values())
        if self.content() == "slices":
            p = Path(cur) if cur else Path(self._dir)
            if p.suffix.lower() in all_suffix:          # 原来是文件 → 退到它所在的目录
                p = p.parent
            self.path_edit.setText(str(p))
            return
        suffix = self.SUFFIX[self.fmt()]
        p = Path(cur) if cur else None
        if p is not None and p.suffix.lower() in all_suffix:
            p = p.with_suffix(suffix)
        else:
            base = p if (p is not None and str(p)) else Path(self._dir)
            p = base / (self._stem + suffix)
        self.path_edit.setText(str(p))

    def _refresh_scale_label(self) -> None:
        """规模说明：整卷报整卷，逐剖面报片数与范围，图片报"论文用图"。"""
        content = self.content()
        if content == "slices":
            axis = self.slice_axis()
            total = exporter.slice_count(self._vol.data, axis)
            rows, cols = exporter.slice_shape(self._vol.data, axis)
            n = self.entry_count() if self._scope_all() else 1
            if self.chk_current.isChecked():
                self.scale_label.setText(
                    f"仅导出当前显示的剖面：沿「{exporter.SLICE_LABEL_OF.get(axis, axis)}」"
                    f"各数据源当前第 {self._current_index(axis)} 片（共 {total} 片），"
                    f"每片 {rows} × {cols}，共 {n} 个文件")
            else:
                a, b = self.slice_range()
                self.scale_label.setText(
                    exporter.describe_slices(self._vol.data, axis, self.fmt(), a, b))
        elif content == "slice_image":
            n = self.entry_count() if self._scope_all() else 1
            axis = self.slice_axis()
            rows, cols = exporter.slice_shape(self._vol.data, axis)
            self.scale_label.setText(
                f"论文用图：白底、物理坐标轴（时间 s / 空间 m）、振幅色条；"
                f"约 {rows} × {cols} 采样点全分辨率重绘，共 {n} 个文件")
        elif content == "wave_image":
            self.scale_label.setText(
                f"论文用图：白底、物理坐标轴；"
                f"{'各数据源曲线叠在一张图里' if self.entry_count() > 1 else '当前道'}，"
                f"共 1 个文件")
        else:
            self.scale_label.setText(exporter.describe(self._vol.data, self.fmt()))

    def _refresh_slice_texts(self) -> None:
        """逐剖面规则一句 + 例子一行，**两行永远都有内容**（空标签会被样式刷成暗方块）。"""
        if self.content() != "slices":
            return
        axis = self.slice_axis()
        word = exporter.word_of(axis)
        suffix = self.SUFFIX[self.fmt()]
        self.slice_rule.setText(
            f"规则：文件名 + 下划线 + {word} + {suffix}；文件名留空就只用{word}。")
        try:
            exporter.check_name(self.name_prefix())
        except exporter.ExportError as exc:
            self.slice_preview.setText(f"⚠ {exc}")
            return
        total = exporter.slice_count(self._vol.data, axis)
        if self.chk_current.isChecked():
            self.slice_preview.setText(
                f"例：{exporter.slice_name(self.name_prefix(), self._current_index(axis), suffix)}"
                f"　每份数据各一片")
            return
        a, b = self.slice_range()
        a2, b2 = min(a, b), max(a, b)
        names = [exporter.slice_name(self.name_prefix(), i, suffix)
                 for i in range(a2, min(a2 + 2, b2 + 1))]
        more = "…" if (b2 + 1 - a2) > len(names) else ""
        self.slice_preview.setText(f"例：{'、'.join(names)}{more}　共 {b2 - a2 + 1} / {total} 个文件")

    def _refit_height(self) -> None:
        """按当前宽度重算高度，把多出来的留白收回去。

        顶层窗口只在布局**要求变大**时才会跟着长（所以切到 SEG-Y / SU 会自己长高），
        反过来缩小它不管 —— 切回矩阵格式后底部就留一大片空白。宽度保持用户拖出来的值。
        构造期（还没显示）不调：那时窗口还没有真实尺寸，硬 resize 会把
        首次弹出的大小钉死在 640×480 这种默认值上，让 Qt 自己按 sizeHint 定更合适。
        """
        if not self.isVisible() or self.layout() is None:
            return
        lay = self.layout()
        lay.activate()
        w = self.width()
        h = lay.heightForWidth(w)
        if h <= 0:                                  # 极端情况下退回 sizeHint
            h = self.sizeHint().height()
        self.resize(w, max(h, self.minimumSizeHint().height()))

    def showEvent(self, ev) -> None:                # noqa: N802 （Qt 接口名）
        """弹出时先按「重算高度」的算法定一次尺寸。

        Qt 首次显示用的是 sizeHint，跟 heightForWidth 差十几个像素；不先统一，
        用户第一次动某个选项时窗口会突然跳一下。
        """
        super().showEvent(ev)
        if not self._fitted:
            self._fitted = True
            self._refit_height()

    def _browse(self) -> None:
        if self.content() == "slices":                  # 逐剖面导出选的是文件夹
            folder = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择导出文件夹", self.path())
            if folder:
                self.path_edit.setText(folder)
            return
        fmt = self.fmt()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出到", self.path(),
            f"{self.combo_fmt.currentText()} (*{self.SUFFIX[fmt]});;所有文件 (*)")
        if path:
            if not Path(path).suffix:
                path += self.SUFFIX[fmt]
            self.path_edit.setText(path)

    def _fail(self, message: str) -> None:
        """报错：显示文字并让对话框把这段高度撑开（不然红字会被挤掉）。"""
        self.error.setText(message)
        self._refit_height()

    def summary(self) -> str:
        """把「这次导出到底要干什么」汇总成几行，给确认框用。"""
        content, fmt = self.content(), self.fmt()
        kind = dict((k, name) for name, k in self.CONTENT_MODES).get(content, content)
        lines = [f"导出内容：{kind}", f"格式：{self.combo_fmt.currentText()}"]
        scope = "全部对比数据" if self._scope_all() else "当前数据"

        if content in self.IMAGE_MODES:
            lines.append(f"数据源：{scope}" if content == "slice_image"
                         else "数据源：全部曲线")
            if content == "wave_image":
                lines.append("画面：当前单道波形（白底、坐标轴按 dt 标出秒）")
            else:
                axis = self.slice_axis()
                idx = self._current_index(axis)
                lines.append(f"画面：当前剖面（沿「{exporter.SLICE_LABEL_OF.get(axis, axis)}」"
                             f"第 {idx} 片；白底、物理坐标轴、振幅色条）")
            lines.append(f"保存到：{self.path()}")
            return "\n".join(lines)

        if content == "slices":
            axis = self.slice_axis()
            total = exporter.slice_count(self._vol.data, axis)
            rows, cols = exporter.slice_shape(self._vol.data, axis)
            name_axis = exporter.SLICE_LABEL_OF.get(axis, axis)
            lines.append(f"数据源：{scope}")
            if self.chk_current.isChecked():
                idx = self._current_index(axis)
                lines.append(f"内容：逐剖面导出 —— 每份数据当前第 {idx} 片"
                             f"（沿「{name_axis}」，每片 {rows} × {cols}）")
                heads = [exporter.slice_name(self.name_prefix(), idx, self.SUFFIX[fmt])]
            else:
                a, b = self.slice_range()
                a2, b2 = min(a, b), max(a, b)
                lines.append(f"内容：逐剖面导出 第 {a2} ~ {b2} 片"
                             f"（共 {b2 - a2 + 1} / {total} 片，沿「{name_axis}」，"
                             f"每片 {rows} × {cols}）")
                heads = [exporter.slice_name(self.name_prefix(), i, self.SUFFIX[fmt])
                         for i in range(a2, min(a2 + 2, b2 + 1))]
            lines.append(f"文件夹：{self.path()}")
            lines.append("文件名：" + "、".join(heads) + ("…" if len(heads) < 2 else ""))
            return "\n".join(lines)

        n_shot, n_r, n_t = (int(v) for v in self._vol.shape)
        size = exporter.size_text(int(self._vol.data.size) * 4)
        lines.append(f"内容：整卷数据 {n_shot} 炮 × {n_r} 道 × {n_t} 采样（约 {size}）")
        lines.append(f"保存到：{self.path()}")
        if fmt in exporter.SEISMIC_KEYS:
            lines.append(f"采样间隔：{self.dt_us()} µs")
            coords = ("附带规则坐标（道距 "
                      f"{self.dx():g} m、炮距 {self.ds():g} m）" if self.with_coords()
                      else "不带坐标")
            lines.append(f"道头：写炮号 / 道号 / 采样参数；{coords}")
        return "\n".join(lines)

    def _confirm(self) -> bool:
        """导出前的最后确认：把动作信息摆出来，顺带把「要不要覆盖」一起问掉。

        覆盖原本是单独一个弹窗，两个框连着弹更容易点错，所以并成一次。
        """
        content = self.content()
        exists = (content != "slices") and Path(self.path()).exists()
        body = self.summary()
        if content == "slices":
            body += "\n\n目标文件夹里的同名文件会被覆盖。"
        elif exists:
            body += f"\n\n⚠ {Path(self.path()).name} 已存在，会被覆盖。"
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("确认导出")
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setText(body)
        ok = box.addButton("覆盖" if exists else "导出",
                           QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("取消", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        # 默认按钮 = 按回车时触发的那一个。凡是有覆盖风险的情况（目标文件已存在、
        # 或逐剖面导出可能覆盖一整批同名文件），都默认落在「取消」上。
        box.setDefaultButton(cancel if (exists or content == "slices") else ok)
        box.exec()
        return box.clickedButton() is ok

    def _validate(self) -> None:
        content, path = self.content(), self.path()
        if content == "slices":
            if not path:
                self._fail("请先指定导出文件夹。")
                return
            if not Path(path).is_dir():
                self._fail(f"文件夹不存在：{path}")
                return
            try:
                exporter.check_name(self.name_prefix())
            except exporter.ExportError as exc:
                self._fail(str(exc))
                return
            if not self.chk_current.isChecked():
                a, b = self.slice_range()
                total = exporter.slice_count(self._vol.data, self.slice_axis())
                if not (0 <= a < total) or not (0 <= b < total):
                    self._fail(f"片层范围超出下标 0 ~ {total - 1}。")
                    return
                if a > b:
                    self._fail(f"片层范围不合法：起点 {a} 大于终点 {b}。")
                    return
            if self._confirm():
                self.accept()
            return
        if not path:
            self._fail("请先指定保存路径。")
            return
        p = Path(path)
        if p.parent and not p.parent.exists():
            self._fail(f"目录不存在：{p.parent}")
            return
        if self._confirm():
            self.accept()


# ==================================================================== 悬浮胶囊
class PanelCapsule(QtWidgets.QFrame):
    """工作区右上角的「面板开关 + 摆法」胶囊：横排三个小图标 + 分隔线 + 「分屏」键。

    浮在内容之上、不占布局高度。几个刻意的取舍：

    * 三个图标按维度 1 → 2 → 3（单道波形 / 剖面 / 三维）；
    * 每个图标 = 左侧停靠条 + 类型图形：条**宽而亮** = 这类面板开着，只剩细线 = 已收起；
    * 三个图标都是**纯开关** —— 点一下只会"显示↔收起"，含义与当前状态无关。
      以前同一个点击按状态有三种含义（收起中的=加进来 / 显示中的=只看它 / 唯一的=
      退回上次组合），用户得先记住当前状态才知道点了会怎样，所以拆掉了；
      "只看这一块"改由快捷键 1/2/3、Tab，或「分屏」键打开的摆法面板承担；
    * 「分屏」键 = 打开摆法面板（用户自己连信号，见 ``LayoutPicker``）；
    * 「剖面」图标下方用 1–3 个圆点表示"现在有几块、哪几块被拉出成了独立窗口"。
      不写数字——数字会被读成"这块属于数据 2"，而它其实要表达"有 2 块"。
    """

    KINDS = ("trace", "slice", "side3d")
    DOT_ON = 5                # 圆点直径
    DOT_GAP = 3
    IDLE_OPACITY = 0.55

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Capsule")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(5, 4, 5, 4)
        lay.setSpacing(2)
        self.buttons: dict[str, QtWidgets.QToolButton] = {}
        for kind in self.KINDS:
            btn = QtWidgets.QToolButton()
            btn.setObjectName("CapsuleBtn")
            btn.setIconSize(QtCore.QSize(20, 20))
            btn.setFixedSize(24, 24)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            lay.addWidget(btn, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            self.buttons[kind] = btn
        sep = QtWidgets.QFrame()
        sep.setObjectName("CapsuleSep")
        sep.setFixedWidth(1)
        sep.setFixedHeight(22)
        lay.addWidget(sep, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        # 「交换主区」：交换主区那两块的先后（两块时就是这两块互换）。语义固定，
        # 只有"手上不足两块"时才置灰 —— 不再是"含义随状态变"。
        self.swap_btn = QtWidgets.QToolButton()
        self.swap_btn.setObjectName("CapsuleBtn")
        self.swap_btn.setIconSize(QtCore.QSize(20, 20))
        self.swap_btn.setFixedSize(24, 24)
        self.swap_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.swap_btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.split_btn = QtWidgets.QToolButton()
        self.split_btn.setObjectName("CapsuleBtnSplit")
        self.split_btn.setText("分屏")
        self.split_btn.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.split_btn.setIconSize(QtCore.QSize(18, 18))
        self.split_btn.setFixedHeight(24)
        self.split_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.split_btn, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.setFixedHeight(32 + self.DOT_ON + 3)
        self._dots: list[bool] = []
        self._effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._effect.setOpacity(self.IDLE_OPACITY)
        self.setGraphicsEffect(self._effect)
        self._fade = QtCore.QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(140)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

    def set_slice_dots(self, count: int, detached: list[bool] | None = None) -> None:
        """剖面有几块、哪几块被拉出为独立窗口。只有 ≥ 2 块时才画点。"""
        if count < 2:
            self._dots = []
        else:
            self._dots = [bool(detached[i]) if detached and i < len(detached) else False
                          for i in range(count)]
        self.update()

    def enterEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        self._fade_to(1.0)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        self._fade_to(self.IDLE_OPACITY)
        super().leaveEvent(ev)

    def _fade_to(self, value: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(float(value))
        self._fade.start()

    def paintEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        super().paintEvent(ev)
        if not self._dots:
            return
        btn = self.buttons["slice"]
        total = len(self._dots) * self.DOT_ON + (len(self._dots) - 1) * self.DOT_GAP
        x = btn.geometry().center().x() - total / 2.0 + self.DOT_ON / 2.0
        y = btn.geometry().bottom() + 3 + self.DOT_ON / 2.0
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = QtGui.QColor(style.ACCENT)
        for detached in self._dots:
            if detached:                # 空心 = 这一块已经被拉出成独立窗口
                p.setPen(QtGui.QPen(color, 1.2))
                p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            else:                       # 实心 = 这一块还在主窗口里
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(color)
            p.drawEllipse(QtCore.QPointF(x, y), self.DOT_ON / 2.0, self.DOT_ON / 2.0)
            x += self.DOT_ON + self.DOT_GAP
        p.end()


# ============================================== 分屏摆法：规格 / 缩略图 / 选择面板
# 摆法只用三块：剖面(slice) / 单道波形(trace) / 三维(right)，顺序固定按维度 1→2→3。
KIND_ORDER = ("slice", "trace", "right")
KIND_SHORT = {"slice": "剖", "trace": "道", "right": "三"}

# 一共七个**具体**摆法，按"要几块界面"分两组。三块的四个各自钉住一块：
#   B（默认）  单道波形**永远在底部通栏**，上面两块左右并排
#   A          三维**永远在右边一列**，左边两块上下叠放
#   BT         B 的镜像：单道波形**永远在顶部通栏**，下面两块左右并排
#   AL         A 的镜像：三维**永远在左边一列**，右边两块上下叠放
# BT/AL 原本只在"拖动落位"时才会出现；现在提升为一等公民，于是也能被选成默认布局。
# 两块的都是固定方向、固定默认顺序（可在设置里改默认先后）：
#   剖面+三维 → 左右（左剖面 右三维）
#   单道+三维 → 上下（上三维 下单道）
#   剖面+单道 → 上下（上剖面 下单道）
LAYOUT_KEYS = ("B", "A", "BT", "AL", "SR", "TR", "ST")
LAYOUT_GROUP = {"B": 3, "A": 3, "BT": 3, "AL": 3, "SR": 2, "TR": 2, "ST": 2}
LAYOUT_TITLE = {"B": "主 + 侧 + 底", "A": "左叠右",
                "BT": "单道在上", "AL": "三维在左",
                "SR": "剖面 ｜ 三维", "TR": "三维 ／ 单道", "ST": "剖面 ／ 单道"}
# 两块摆法：pair（排过序）→ (摆法键, 方向, 默认先后)
PAIR_LAYOUT = {("slice", "trace"): ("ST", "V", ("slice", "trace")),
               ("right", "slice"): ("SR", "H", ("slice", "right")),
               ("right", "trace"): ("TR", "V", ("right", "trace"))}
# 三块摆法里被"钉住"的那一块（剩余两块是可换序的）
THREE_PINNED = {"B": "trace", "A": "right", "BT": "trace", "AL": "right"}
# 三块构图的键（供"是不是三块摆法"的判定与设置校验用）
THREE_KEYS = tuple(k for k in LAYOUT_KEYS if LAYOUT_GROUP[k] == 3)


def pair_layout(pair):
    """两块界面的固定摆法：返回 ``(摆法键, 方向, 默认先后)``。"""
    key = tuple(sorted(pair))
    got = PAIR_LAYOUT.get(key)
    if got is not None:
        return got
    return ("SR", "H", key)                # 兜底（理论上到不了）


def three_free_pair(pinned: str, panels) -> tuple:
    """把 ``panels`` 里除 ``pinned`` 之外的两块的默认先后按 1→2→3 的次序取出来。"""
    pair = tuple(k for k in KIND_ORDER if k != pinned and k in panels)
    return pair


def layout_rects(key: str, order) -> list:
    """摆法的**示意矩形**：返回 ``[(kind, (x, y, w, h)), ...]``，坐标是 0~1 相对值。

    ``order`` 是"可换序那两块"的当前先后 —— 钉住的那块（B/BT 的单道、A/AL 的三维）
    由 ``key`` 自己决定，所以缩略图里"谁在底、谁在右"永远是真实的。
    """
    f1, f2 = order
    if key == "B":                          # 上排两块左右 + 单道底部通栏
        return [(f1, (0.0, 0.0, 0.62, 0.72)), (f2, (0.62, 0.0, 0.38, 0.72)),
                ("trace", (0.0, 0.72, 1.0, 0.28))]
    if key == "BT":                         # 单道顶部通栏 + 下排两块左右（B 的镜像）
        return [("trace", (0.0, 0.0, 1.0, 0.28)),
                (f1, (0.0, 0.28, 0.62, 0.72)), (f2, (0.62, 0.28, 0.38, 0.72))]
    if key == "A":                          # 左列两块上下 + 三维右列
        return [(f1, (0.0, 0.0, 0.62, 0.62)), (f2, (0.0, 0.62, 0.62, 0.38)),
                ("right", (0.62, 0.0, 0.38, 1.0))]
    if key == "AL":                         # 三维左列 + 右列两块上下（A 的镜像）
        return [("right", (0.0, 0.0, 0.38, 1.0)),
                (f1, (0.38, 0.0, 0.62, 0.62)), (f2, (0.38, 0.62, 0.62, 0.38))]
    if key == "SR":                         # 两块左右
        return [(f1, (0.0, 0.0, 0.62, 1.0)), (f2, (0.62, 0.0, 0.38, 1.0))]
    return [(f1, (0.0, 0.0, 1.0, 0.72)), (f2, (0.0, 0.72, 1.0, 0.28))]   # 两块上下


class LayoutThumb(QtWidgets.QWidget):
    """一张摆法缩略图：按 :func:`layout_rects` 画小方块，可换序的第一块用强调色。

    左上角另有一枚**星标**（可点）：亮起 = 这一张是该组合"当前生效的默认布局"。
    星标热区与"点缩略图切摆法"分得很开 —— 点星标只设默认，不切摆法（见
    :meth:`mouseReleaseEvent`），免得一次误点把画面切走。
    """

    clicked = QtCore.Signal()
    defaultToggled = QtCore.Signal(str)     # 带 key：点星标（= 把这张设为默认）

    # 星标的位置与热区（左上角，避开右上角那枚"当前"药丸）
    STAR_RECT = QtCore.QRectF(6.0, 4.0, 15.0, 15.0)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.order = ("slice", "right")
        self.active = False
        self.default = False                # 是不是"当前生效的默认"
        self._hover = False
        self.setFixedSize(116, 74)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._sync_tooltip()

    def _sync_tooltip(self) -> None:
        self.setToolTip(
            f"{LAYOUT_TITLE.get(self.key, self.key)}\n"
            "点缩略图 = 立刻切到这一张（不改默认）\n"
            "点左上角 ★ = 把这一张设为默认布局")

    def set_spec(self, order, active: bool, is_default: bool = False) -> None:
        self.order, self.active = tuple(order), bool(active)
        self.default = bool(is_default)
        self.update()

    def _star_hit(self) -> QtCore.QRectF:
        """星标的点击热区：比画出来的星稍大一圈，好点中。"""
        return self.STAR_RECT.adjusted(-3.0, -3.0, 3.0, 3.0)

    def enterEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        self._hover = True
        self.update()

    def leaveEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, ev) -> None:              # noqa: N802 （Qt 接口名）
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        pos = ev.position()
        if self._star_hit().contains(pos):               # 星标：只设默认，不切摆法
            self.defaultToggled.emit(self.key)
            return
        if self.rect().contains(pos.toPoint()):
            self.clicked.emit()

    def paintEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        """底 + 边框 + 三块示意；**选中与悬停必须长得明显不同**。

        以前两者都只是"一圈强调色边框"（只差线宽），鼠标划过时看着就像选中状态
        在乱跳。现在：选中的是**加粗强调边框 + 右上角一枚"当前"角标**，
        悬停只把底色提亮一格、边框仍是普通分隔线 —— 一眼能分清。
        """
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(style.CARD if self._hover else style.PANEL))
        p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor(style.ACCENT if self.active else style.LINE),
                            2.0 if self.active else 1.0))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0), 5, 5)
        if self.active:
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(style.ACCENT))
            pill = QtCore.QRectF(self.width() - 34.0, 2.0, 32.0, 13.0)
            p.drawRoundedRect(pill, 6.5, 6.5)
            p.setPen(QtGui.QColor(style.ON_ACCENT))
            p.setFont(style.mono_font(8))
            p.drawText(pill, QtCore.Qt.AlignmentFlag.AlignCenter, "当前")
        pad = 6.0
        iw, ih = self.width() - 2 * pad, self.height() - 2 * pad
        p.setFont(style.mono_font(8))
        head = self.order[0] if self.order else ""
        for kind, (x, y, w, h) in layout_rects(self.key, self.order):
            r = QtCore.QRectF(pad + x * iw + 1, pad + y * ih + 1,
                              max(3.0, w * iw - 2), max(3.0, h * ih - 2))
            is_main = kind == head          # 可换序的第一块 = 这一摆法的"主块"
            p.setBrush(QtGui.QColor(style.ACCENT_DIM if is_main else style.CARD))
            p.setPen(QtGui.QPen(QtGui.QColor(style.ACCENT if is_main else style.LINE), 1.0))
            p.drawRoundedRect(r, 2.5, 2.5)
            p.setPen(QtGui.QColor(style.ON_ACCENT if is_main else style.TEXT_DIM))
            if r.width() > 14 and r.height() > 12:
                p.drawText(r, QtCore.Qt.AlignmentFlag.AlignCenter, KIND_SHORT[kind])
        # 星标：亮起 = 当前生效的默认；未亮也画一枚淡色的，提示"这里可以点"。
        # 先垫一层底色，免得压在方块上时看不清。
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(style.PANEL))
        p.drawEllipse(self.STAR_RECT.adjusted(-1.0, -1.0, 1.0, 1.0))
        star = _star_path(self.STAR_RECT)
        if self.default:
            p.setPen(QtGui.QPen(QtGui.QColor(style.ACCENT), 1.0))
            p.setBrush(QtGui.QColor(style.ACCENT))
        else:
            p.setPen(QtGui.QPen(QtGui.QColor(style.TEXT_MUTE if self._hover
                                            else style.LINE), 1.0))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawPath(star)
        p.end()


def _star_path(rect: QtCore.QRectF) -> QtGui.QPainterPath:
    """五角星路径（内接于 ``rect``）—— 给缩略图的"设为默认"星标用。"""
    path = QtGui.QPainterPath()
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2.0
    inner = r * 0.42
    for i in range(10):
        ang = -math.pi / 2.0 + i * math.pi / 5.0
        rr = r if i % 2 == 0 else inner
        x, y = cx + rr * math.cos(ang), cy + rr * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


class LayoutPicker(QtWidgets.QFrame):
    """胶囊「分屏」键弹出的**摆法选择面板**：七个具体摆法，按"要几块界面"分两组。

    刻意不用文字菜单：光看名字（"左叠右""主+侧+底"）根本对不上画面。缩略图里
    谁的块最大、谁在左、谁在底一眼就对上，而且每张画的都是**确定的那张图**
    （B 里单道一定在底栏、A 里三维一定在右列）。

    两组**都能点**：点三块组而手上不足三块 → 自动补齐到三块；点两块组的某张 →
    直接换成它画的那两块。所以不存在"点了没反应"的死胡同。

    每张左上角还有一枚 ★（见 :class:`LayoutThumb`）：亮起的那张 = 该组合**当前生效的
    默认布局**（含内置），点它是"把这一张设为默认"，不切当前画面。
    """

    presetChosen = QtCore.Signal(str)
    resetRequested = QtCore.Signal()       # 「复位布局 / 找回所有面板」
    defaultRequested = QtCore.Signal(str)  # 点某张的 ★：把它设为默认
    restoreDefaultsRequested = QtCore.Signal()   # 「恢复内置默认布局」
    closed = QtCore.Signal()               # 面板收起时发一次（主窗口用它做"开关"判定）

    GROUP_TITLES = {3: "三块界面", 2: "两块界面"}

    def __init__(self, keys, labels, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Popup)
        self.setObjectName("LayoutPicker")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        head = QtWidgets.QLabel("分屏摆法")
        head.setObjectName("SectionTitle")
        root.addWidget(head)

        self._thumbs: dict[str, LayoutThumb] = {}
        for family in (3, 2):
            group = [k for k in keys if LAYOUT_GROUP[k] == family]
            if not group:
                continue
            cap = QtWidgets.QLabel(self.GROUP_TITLES[family])
            cap.setObjectName("Hint")
            root.addWidget(cap)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            for key in group:
                col = QtWidgets.QVBoxLayout()
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(3)
                thumb = LayoutThumb(key)
                thumb.clicked.connect(lambda k=key: self.presetChosen.emit(k))
                thumb.defaultToggled.connect(self.defaultRequested.emit)
                col.addWidget(thumb)
                self._thumbs[key] = thumb
                name = QtWidgets.QLabel(labels[key])
                name.setObjectName("Hint")
                name.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                col.addWidget(name)
                row.addLayout(col)
            row.addStretch(1)
            root.addLayout(row)

        self.hint = QtWidgets.QLabel("")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # 星标的图例 + 一键清掉自定义的默认（回到内置的 B / 各组合规范先后）
        self.btn_defaults = QtWidgets.QPushButton("恢复内置默认布局")
        self.btn_defaults.setObjectName("Ghost")
        self.btn_defaults.setToolTip(
            "清掉自定义的默认布局，回到内置的那一套：\n"
            "三块 → B（主+侧+底）；两块 → 剖面在左、三维在上、单道在下。")
        self.btn_defaults.clicked.connect(self.restoreDefaultsRequested.emit)
        root.addWidget(self.btn_defaults)

        # 兜底出口：面板被拉到独立窗口后万一找不回来（窗口跑到屏幕外、被系统关掉、
        # 状态错乱），这一条一键把所有面板收回主窗口并恢复默认摆法。
        self.btn_reset = QtWidgets.QPushButton("复位布局／找回所有面板")
        self.btn_reset.setObjectName("Ghost")
        self.btn_reset.setToolTip(
            "把拉到独立窗口的面板全部收回主窗口，并按**当前默认布局**重新排一次。\n"
            "面板找不到时点这里。")
        self.btn_reset.clicked.connect(self.resetRequested.emit)
        root.addWidget(self.btn_reset)

    def order_of(self, key: str):
        """某张缩略图**当前显示**的先后（= 点它会得到的先后）；没有这张图时返回 None。"""
        thumb = self._thumbs.get(key)
        return tuple(thumb.order) if thumb is not None else None

    def refresh(self, current: str, orders: dict, tip: str, stars=None) -> None:
        """把当前状态刷到缩略图上（当前摆法亮框；★ = 生效的默认；每张按各自的先后画）。"""
        stars = stars or set()
        for key, thumb in self._thumbs.items():
            thumb.set_spec(orders.get(key) or ("slice", "right"),
                           key == current, key in stars)
        self.hint.setText(tip)

    def hideEvent(self, ev) -> None:                     # noqa: N802 （Qt 接口名）
        super().hideEvent(ev)
        self.closed.emit()


# ==================================================================== 部件容器
def make_panel(title: str | None = None) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
    """统一的卡片式容器。"""
    frame = QtWidgets.QFrame()
    frame.setObjectName("Panel")
    lay = QtWidgets.QVBoxLayout(frame)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    if title:
        lab = SectionLabel(title)
        lay.addWidget(lab)
    return frame, lay


class FoldCard(QtWidgets.QFrame):
    """可折叠的设置分组：标题行（细箭头 + 分组图标 + 组名 + 摘要 + 右侧插槽）+ 内容区。

    交互上的几个约定，都是为了解决"不知道里面是什么、点不中、分不清符号"：

    * **整行都能点**（不是只有那颗小三角），鼠标移上去整行高亮、光标变手形；
    * 箭头是**细线条**画在**左侧**，只作状态指示；整块面板的显隐用的是
      另一个"方框 + 实心条"的停靠图标 —— 两者形状完全不同，不会混；
    * **收起后标题行右侧留一行摘要**：不用展开就知道里面是什么值。

    左栏是普通 ``QVBoxLayout``（不是 splitter），所以收起只是把内容压到 0 高，
    不会像中间那些面板一样撞上"最小高度把面板顶回去"的问题。
    """

    # 折叠动画时长：短到不打断阅读、长到能看清"它是从这里收掉的"
    ANIM_MS = 160

    # 展开状态变化时发出：主窗口用它同步图标轨道、把摘要写成最新值、记忆状态
    toggled = QtCore.Signal(bool)

    def __init__(self, title: str, parent=None, *, expanded: bool = True,
                 icon_name: str | None = None, summary: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setProperty("flash", False)     # 供"跳转高亮"用的动态属性
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 10)
        outer.setSpacing(6)

        self.header = QtWidgets.QWidget()
        self.header.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.header.installEventFilter(self)
        header = QtWidgets.QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # 细箭头：形状 = 折叠状态；放下拉/右收，与"停靠图标"完全不同
        self.arrow = QtWidgets.QToolButton()
        self.arrow.setObjectName("FoldArrow")
        self.arrow.setAutoRaise(True)
        self.arrow.setIconSize(QtCore.QSize(12, 12))
        self.arrow.setFixedSize(14, 14)
        self.arrow.clicked.connect(self.toggle)
        header.addWidget(self.arrow)

        # 分组图标：用户"每个设置项对应一个小图标"的要求
        self._icon_name = icon_name
        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setFixedSize(16, 16)
        if icon_name:
            self.icon_label.setPixmap(icons.group(icon_name, 16, style.TEXT_DIM))
        else:
            self.icon_label.setVisible(False)
        header.addWidget(self.icon_label)

        self.title = SectionLabel(title)
        header.addWidget(self.title)
        header.addStretch(1)

        # 收起后才出现的摘要：这是"收起来也知道里面是什么"的关键
        self.summary = ElidedLabel(summary)
        self.summary.setObjectName("Value")
        self.summary.setVisible(False)
        # 右对齐：省略后的文字始终紧贴右边的按钮，不会飘在标题后面
        self.summary.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight
                                  | QtCore.Qt.AlignmentFlag.AlignVCenter)
        # 伸缩因子在 set_expanded 里与"弹簧"互相交换：摘要显示时由摘要吃掉多余空间
        # （于是它能按需省略），隐藏时由弹簧把右侧插槽推到底。两者都占着伸缩的话，
        # 摘要只能分到一半空间、文字会被挤成省略号。
        self._header_lay = header
        header.addWidget(self.summary)

        self.slot_lay = QtWidgets.QHBoxLayout()      # 标题行右侧的小控件插槽
        self.slot_lay.setContentsMargins(0, 0, 0, 0)
        self.slot_lay.setSpacing(6)
        header.addLayout(self.slot_lay)
        outer.addWidget(self.header)

        self._body = QtWidgets.QWidget()
        # 竖向策略必须是 Preferred（**不能**用 Ignored）：Qt 在算布局需求时，
        # 会把 Ignored 方向的需求直接当作 0，于是"卡片需要多高"这件事就整个失真 ——
        # 五组内容超过窗口时，排在后面的分组会被压成 0 高而滚动条又不出现，
        # 表现就是"点了展开却什么都没出来"。收起靠 setMaximumHeight(0) 就够，
        # 它会把这一项的有效需求一并压到 0（最大值优先于最小需求），不冲突。
        self._body.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred,
                                 QtWidgets.QSizePolicy.Policy.Preferred)
        self.body = QtWidgets.QVBoxLayout(self._body)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addWidget(self._body)

        self._anim = QtCore.QPropertyAnimation(self._body, b"maximumHeight", self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self._anim.finished.connect(self.end_anim)
        self._expanded = True
        self.set_expanded(expanded, animate=False)

    # ------------------------------------------------------------ 交互
    def eventFilter(self, obj, ev) -> bool:             # noqa: N802 （Qt 接口名）
        """整行可点：点在标题文字、图标或空白处都能收放。

        箭头与插槽里的小控件自己会接收点击，不会冒泡到这里，所以不会重复触发。
        """
        if obj is self.header:
            if ev.type() == QtCore.QEvent.Type.MouseButtonRelease \
                    and ev.button() == QtCore.Qt.MouseButton.LeftButton \
                    and self.header.rect().contains(ev.position().toPoint()):
                self.toggle()
                return True
        return super().eventFilter(obj, ev)

    def add_header_widget(self, widget: QtWidgets.QWidget) -> None:
        self.slot_lay.addWidget(widget)

    def set_summary(self, text: str) -> None:
        """收起后显示在标题行右侧的一行摘要（展开时自动隐藏）。"""
        self.summary.setText(text)

    def flash(self, ms: int = 650) -> None:
        """整张卡片短暂闪一下强调色边框（轨道图标跳过来时用来"指一下路"）。

        QSS 里没有直接可动画的强调边框，这里走**动态属性 + 重算样式**：
        设了属性之后必须 ``unpolish/polish`` 一次，Qt 才会按新属性重新匹配规则。
        """
        self.setProperty("flash", True)
        self._repolish()
        QtCore.QTimer.singleShot(ms, self._clear_flash)

    def _clear_flash(self) -> None:
        self.setProperty("flash", False)
        self._repolish()

    def _repolish(self) -> None:
        st = self.style()
        if st is not None:
            st.unpolish(self)
            st.polish(self)
        self.update()

    def summary_text(self) -> str:
        """摘要的完整文本（不是被省略后的显示文本）。"""
        return self.summary.full_text()

    def is_expanded(self) -> bool:
        return self._expanded

    def restyle(self) -> None:
        """换主题：标题行的小图标与折叠箭头重画一遍（两张图都是按当时颜色现画的）。"""
        if self._icon_name:
            self.icon_label.setPixmap(icons.group(self._icon_name, 16, style.TEXT_DIM))
        self.arrow.setIcon(QtGui.QIcon(icons.chevron(
            12, style.TEXT_DIM if self._expanded else style.TEXT_MUTE,
            down=self._expanded)))

    # ------------------------------------------------------------ 尺寸需求
    def minimumSizeHint(self) -> QtCore.QSize:          # noqa: N802 （Qt 接口名）
        """卡片**当前状态**下真正需要的尺寸（高度取"想要的高度"、宽度取"最小宽度"）。

        不显式给出会踩一个很隐蔽的坑：内容区为配合折叠动画，竖向尺寸策略一度被设成
        Ignored（于是它的最小高度算作 0）。五组设置的总高超过窗口时，父布局就会照
        "最小需求"把内容压扁 —— 排在后面的分组被压成 0 高，而滚动区又认为不需要滚动条，
        表现就是"点了展开却什么都没出来"。**高度**因此钉在"布局想要的尺寸"上。

        **宽度**则必须用"布局的最小宽度"（``minimumSize``）而不是"想要的宽度"：
        后者取的是各行的**首选**宽度，会把里层滚动区撑得比可视区还宽 ——
        于是侧边栏底下凭空多出一条横向滚动条（用户明确要求这条滚条不该存在）。
        宽度需求小一点没关系，布局会按可用空间分配。
        """
        layout = self.layout()
        if layout is None:                               # 构造期还没装好布局
            return QtCore.QSize(60, 30)
        want = layout.sizeHint()
        least = layout.minimumSize()
        return QtCore.QSize(max(0, least.width()), want.height())

    def sizeHint(self) -> QtCore.QSize:                 # noqa: N802 （Qt 接口名）
        return self.minimumSizeHint()

    def set_expanded(self, on: bool, animate: bool = True) -> None:
        """展开 / 收起内容区；``animate`` 时用最大高度插值推一下。

        **起点必须是"当前实际高度"**：展开态下 ``maximumHeight`` 一直被钉在
        ``QWIDGETSIZE_MAX``，若从那个值开始插值到 0，前 95% 的时长全在"从 1600 万
        降到一个没意义的大数"这段空转里，真正的收拢只发生在最后 1~2 帧 ——
        观感就是"点了没反应，然后突然全部收掉"。
        """
        start, target = self.begin_anim(on)
        if not animate:
            self.set_anim_height(target)
            self.end_anim()
            return
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(target)
        self._anim.start()

    # ------------------------------------------------- 供主窗口统一进度驱动
    def begin_anim(self, on: bool) -> tuple[float, float]:
        """摆好起始状态，返回这次动画的 ``(起点高度, 终点高度)``。

        供两种驱动共用：单张卡片自己跑 QPropertyAnimation，或者 ⇕ 用一个
        统一的进度一次性推所有卡片（后者每帧只触发布局一次，比五个动画各推
        一次顺得多）。
        """
        on = bool(on)
        self._anim.stop()          # 自己那条动画要让位（批量折叠是外部驱动的）
        self._expanded = on
        self.arrow.setIcon(QtGui.QIcon(icons.chevron(
            12, style.TEXT_DIM if on else style.TEXT_MUTE, down=on)))
        self.summary.setVisible(not on)
        # 交换弹簧与摘要的伸缩因子（布局下标：0 箭头 / 1 图标 / 2 标题 / 3 弹簧 /
        # 4 摘要 / 5 插槽）。展开时摘要藏着，由弹簧把右侧插槽推到底；
        # 收起时反过来，让摘要吃掉多余空间（于是它能按需省略）。
        self._header_lay.setStretch(3, 1 if on else 0)
        self._header_lay.setStretch(4, 0 if on else 1)
        target = float(self._body.sizeHint().height()) if on else 0.0
        start = 0.0 if on else float(max(1, self._body.height()))
        self._body.setMaximumHeight(int(start))
        self.toggled.emit(on)
        return start, target

    def set_anim_height(self, value: float) -> None:
        """把内容区高度设到插值出的这一帧（批量折叠时由主窗口逐帧调用）。"""
        self._body.setMaximumHeight(max(0, int(round(value))))

    def end_anim(self) -> None:
        """动画收尾：展开时放开上限（内容要能跟着布局长），收起时钉在 0。"""
        self._body.setMaximumHeight(16777215 if self._expanded else 0)

    @property
    def anim_height(self) -> int:
        return self._body.maximumHeight()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def mouseDoubleClickEvent(self, ev) -> None:     # noqa: N802 （Qt 接口名）
        """双击标题行也能折叠 —— 和中间面板的操作习惯一致。"""
        self.toggle()


# ==================================================================== 拖动辅助
class DragLayer(QtWidgets.QWidget):
    """拖动面板时跟着鼠标的半透明快照窗口（"手上拿着这块面板"的视觉）。

    它**不接收鼠标事件**：拖动是靠原控件按下时的隐式鼠标抓取来跟踪的，
    这一层只要一抢事件，拖动就会断在半路。
    """

    def __init__(self, pixmap: QtGui.QPixmap):
        super().__init__(None, QtCore.Qt.WindowType.Tool
                         | QtCore.Qt.WindowType.FramelessWindowHint
                         | QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel()
        self.label.setPixmap(pixmap)
        lay.addWidget(self.label)
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        self.resize(max(1, int(pixmap.width() / dpr)),
                    max(1, int(pixmap.height() / dpr)))


class GhostSlot(QtWidgets.QFrame):
    """原位置留下的虚线占位：说明"面板是从这里被拿走的"，松手放回原位即取消。"""

    def __init__(self, parent: QtWidgets.QWidget, geometry: QtCore.QRect):
        super().__init__(parent)
        self.setObjectName("GhostSlot")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lab = QtWidgets.QLabel("松手放回这里即取消")
        lab.setObjectName("Hint")
        lab.setWordWrap(True)
        lab.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lab)
        self.setGeometry(geometry)
        self.show()
        self.raise_()


class _NCCALCSIZE_PARAMS(ctypes.Structure):
    """WM_NCCALCSIZE 的 lParam 结构（只需要 rgrc 那一项）。"""
    _fields_ = [("rgrc", ctypes.c_int * 4 * 3),
                ("lppos", ctypes.c_void_p)]


# WM_NCCALCSIZE：系统在算"客户区留多大"，我们在这里把边框吃掉（见 FloatingPanel.nativeEvent）
WM_NCCALCSIZE = 0x0083


class FloatingPanel(QtWidgets.QWidget):
    """面板被拉出后所在的极简窗口：**无系统边框、无系统标题栏**，只自绘 1px 描边。

    * 拖动 = 拖面板自己的标题栏（与在主窗口里是同一个手势）；
    * 收回 = 把窗口拖回主窗口工作区松手（与拖出完全对称），或点右上角悬停才出现的小箭头；
    * 缩放 = 右下角一块隐形抓角 —— 无边框窗口没地方放系统缩放手柄，只能自己留热区。

    为什么不用系统边框：Windows 的非客户区是 DWM 画的，Win11 才能改颜色、Win10 不能
    （只有"深色/浅色"两档）。要**任意配色**就只能自绘。所以这里走"无边框 + 自绘描边"，
    再向 DWM 讨一点系统质感（柔和阴影 + Win11 圆角），见 :meth:`_apply_dwm`。
    """

    returned = QtCore.Signal(object)          # 参数：面板控件本身
    GRIP = 10                                 # 右下角抓角边长
    MIN_SIZE = (160, 120)
    # 描边两态：聚焦时几乎与背景同色（等于没有边框，保持极简），
    # 失焦时提亮一档 —— 切到别的窗口再回来时才找得到这块面板在哪。
    # 两只颜色**现取**主题（类属性会把导入那一刻的颜色固化住）。
    @staticmethod
    def _border_on() -> str:
        return style.PANEL

    @staticmethod
    def _border_off() -> str:
        return style.LINE_HI

    def __init__(self, panel: QtWidgets.QWidget, size=(980, 760), parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window
                         | QtCore.Qt.WindowType.FramelessWindowHint)
        self.panel = panel
        self._set_floating(panel, True)
        lay = QtWidgets.QVBoxLayout(self)
        # 留 1px：那一圈是 DWM 的系统边框（顺带带来阴影与圆角），
        # 我们的描边就画在它下面这一层，颜色始终由我们说了算。
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        lay.addWidget(panel)
        self.resize(int(size[0]), int(size[1]))
        # 初始尺寸仍**与窗内等大**，但不再钉死尺寸：钉死会让窗口变成"不可缩放"，
        # 而 Windows 只吸附**可缩放**的窗口 —— 于是 Aero Snap、Win+方向键、Snap Layouts
        # 全用不了，这正是"拖出的窗口不是 windows 窗口、不能全屏也不能系统分屏"的根源。
        # 面板自身的最小尺寸在浮动期间放开（见 _set_floating），所以初始尺寸仍精确等于
        # 等大值，不会被面板内容顶宽；用户从边缘或右下角都能拉大。
        self.setMinimumSize(*self.MIN_SIZE)

        self.btn_back = QtWidgets.QToolButton(self)
        self.btn_back.setObjectName("Chevron")
        self.btn_back.setIcon(QtGui.QIcon(icons.panel_back(16, style.TEXT_DIM)))
        self.btn_back.setIconSize(QtCore.QSize(16, 16))
        self.btn_back.setFixedSize(22, 22)
        self.btn_back.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_back.setToolTip("收回主窗口")
        self.btn_back.clicked.connect(lambda: self.returned.emit(self.panel))
        self.btn_back.setVisible(False)
        # 「全屏 / 还原」：**自己实现的全屏**（showFullScreen），不走系统的最大化 ——
        # 系统最大化会给可缩放的无边框窗口加一圈边框条（顶部那条偏宽的白条就是它），
        # 全屏则一点边都不带，画满整块屏幕。
        self.btn_full = QtWidgets.QToolButton(self)
        self.btn_full.setObjectName("Chevron")
        self.btn_full.setIconSize(QtCore.QSize(16, 16))
        self.btn_full.setFixedSize(22, 22)
        self.btn_full.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self._sync_full_btn()
        self.btn_full.setVisible(False)
        self._place_buttons()
        self._grip_origin = None
        self.setMouseTracking(True)

    def _sync_full_btn(self) -> None:
        full = self.isFullScreen()
        self.btn_full.setIcon(QtGui.QIcon(
            icons.expand(16, style.TEXT_DIM, restore=full)))
        self.btn_full.setToolTip("退出全屏" if full else "全屏显示这块面板")

    def toggle_fullscreen(self) -> None:
        """在全屏与窗口之间切换。

        全屏用 ``showFullScreen``：无边框窗口铺满屏幕，**没有系统边框条**；
        退出时回到拉出那一刻的浮窗尺寸。
        """
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._sync_full_btn()
        self._place_buttons()

    def _place_buttons(self) -> None:
        """右上角那两颗悬浮按钮（收回 / 全屏）。

        离外沿留 9px：WS_THICKFRAME 让系统把最外**7px** 当成缩放边框（鼠标在那儿会被系统
        吃掉拿去缩放），按钮压进去就会点不中。
        """
        m, gap = 9, 4
        x = max(0, self.width() - self.btn_back.width() - m)
        self.btn_back.move(x, m)
        self.btn_full.move(max(0, x - self.btn_full.width() - gap), m)

    @staticmethod
    def _set_floating(widget: QtWidgets.QWidget, on: bool) -> None:
        """给面板打上/摘掉"浮窗里"的标记（描边由样式表按这个属性去掉）。

        浮动期间还要**放开面板自身的硬最小尺寸**：不放开的话，面板内容（三维那块里
        有一排定位按钮）的最小宽度会把浮窗顶宽，"拉出时与窗内等大"就不成立了。
        收回时按记下的原值恢复。
        """
        widget.setProperty("floating", bool(on))
        if on:
            if not hasattr(widget, "_docked_min"):
                widget._docked_min = widget.minimumSize()
            widget.setMinimumSize(1, 1)
        elif hasattr(widget, "_docked_min"):
            widget.setMinimumSize(widget._docked_min)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # ------------------------------------------------------------ 自绘描边 + 系统质感
    def paintEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        """在窗口最外圈画 1px 描边（聚焦/失焦两色）。"""
        super().paintEvent(ev)
        painter = QtGui.QPainter(self)
        try:
            painter.setPen(QtGui.QPen(QtGui.QColor(
                self._border_on() if self.isActiveWindow() else self._border_off())))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        finally:
            painter.end()

    def restyle(self) -> None:
        """换主题：描边色与两颗悬浮图标跟着走（描边是在 paintEvent 现取的，重画即可）。"""
        self.btn_back.setIcon(QtGui.QIcon(icons.panel_back(16, style.TEXT_DIM)))
        self._sync_full_btn()
        self._apply_dwm()          # 边框色也是按主题取的，换主题要重下一遍
        self.update()

    def changeEvent(self, ev) -> None:                  # noqa: N802 （Qt 接口名）
        if ev.type() == QtCore.QEvent.Type.ActivationChange:
            self.update()                               # 聚焦态变了，描边要换色
        elif ev.type() == QtCore.QEvent.Type.WindowStateChange:
            # 系统最大化 / 还原来回切之后要让系统**重算一次非客户区**：否则客户区会卡在
            # 旧尺寸上（实测还原后窗口 500×300、客户区却还是最大化时的 1920×1032）。
            self._refresh_frame()
        super().changeEvent(ev)

    def _refresh_frame(self) -> None:
        """让系统重新算一遍非客户区（等价于"重新套一次窗口样式"）。"""
        if os.name != "nt" or QtGui.QGuiApplication.platformName() != "windows":
            return
        try:                                             # pragma: no cover (平台相关)
            hwnd = self._hwnd(self)
            if not hwnd:
                return
            ctypes.windll.user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)   # NOSIZE|NOMOVE|NOZORDER|
                                                              # NOACTIVATE|FRAMECHANGED
        except Exception:
            pass

    def showEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        super().showEvent(ev)
        self._apply_native_style()
        self._apply_dwm()

    def nativeEvent(self, eventType, message):          # noqa: N802 （Qt 接口名）
        """把 ``WS_THICKFRAME`` 带来的**系统边框吃进客户区**（WM_NCCALCSIZE）。

        为什么需要：Qt 的 ``FramelessWindowHint`` 在创建窗口时就把 ``WS_THICKFRAME`` 去掉
        了，而我们为了让 Windows 认它"可缩放"（Aero Snap / Win+方向键 / 系统边缘缩放都
        要求这个）只能在创建之后补上。于是系统按"有边框的窗口"给客户区四边各留出
        **7px** 非客户区（实测），那圈边框由系统绘制 —— ``DWMWA_BORDER_COLOR`` 也改不了
        它的颜色，这就是那条去不掉的偏宽"白条"（顺带还把客户区缩了 7px，与 Qt 自己以为
        的尺寸对不上）。

        这里在系统算客户区时把矩形直接设成整个窗口：边框就不存在了，外观回到我们的自绘
        1px 描边，而"可缩放 + 吸附"的资格（``WS_THICKFRAME``）与系统边缘缩放全部保留。

        用 ``nativeEvent`` 而不是应用级 ``QAbstractNativeEventFilter``：WM_NCCALCSIZE 是
        **SendMessage 同步发**的（在 ``SetWindowPos`` 里），根本不过消息队列，应用级过滤器
        看不到它。
        """
        if eventType == b"windows_generic_MSG" and os.name == "nt" \
                and QtGui.QGuiApplication.platformName() == "windows":
            try:                                         # pragma: no cover (平台相关)
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCCALCSIZE and msg.wParam:
                    user32 = ctypes.windll.user32
                    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
                    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
                    style = user32.GetWindowLongPtrW(msg.hWnd, -16)   # GWL_STYLE
                    if style & 0x01000000:               # WS_MAXIMIZE：系统最大化中
                        # 这个状态下**不吃**边框：吃掉它会让 Qt/系统的尺寸记账打架
                        # （实测最大化后客户区会变成比窗口还大，还原来回切会卡住）。
                        # 代价只是"系统最大化"时仍有一圈系统边框，而正常状态没有。
                        return False
                    params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
                    # rgrc[1] 是系统这次算出的**新窗口矩形**；把它赋给 rgrc[0]
                    # （客户区）就等于"客户区铺满整个窗口" —— 四边边框因此消失。
                    # 注意**不能**用 GetWindowRect：那时窗口还没改成新尺寸。
                    for i, val in enumerate(params.rgrc[1]):
                        params.rgrc[0][i] = val
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    @staticmethod
    def _hwnd(widget) -> "ctypes.c_void_p | None":       # pragma: no cover (平台相关)
        """把 ``winId()`` 包成 ``HWND`` —— 直接传 int 会被 ctypes 按 32 位截断。"""
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            return wintypes.HWND(int(widget.winId()))
        except Exception:
            return None

    def _apply_native_style(self) -> None:
        """让这个**无边框**窗口在 Windows 眼里仍然是"可缩放"的普通窗口。

        为什么必须显式加：Qt 的 ``FramelessWindowHint`` 会把 ``WS_THICKFRAME`` 一起去掉
        （实测窗口 style = WS_POPUP|WS_CLIPCHILDREN|WS_CLIPSIBLINGS），于是 Shell 把它
        当成"不可缩放"的窗口 —— 而 Aero Snap、Win+方向键、Snap Layouts **只吸附可缩放的
        窗口**。这就是"拖出的窗口不是 windows 窗口、不能全屏也不能用系统分屏"的根源。

        加上 ``WS_THICKFRAME`` 后：系统接管非客户区的缩放边框（边缘光标会变成缩放箭头），
        窗口获得吸附资格；再补 ``WS_EX_APPWINDOW``，让它出现在任务栏 / Alt+Tab —— 浮窗是
        "有 owner 的窗口"，不加这条在任务栏里根本看不见，这也是"浮窗丢了找不到"的一个原因。
        ``WS_CAPTION`` 保持不加：外观仍是我们的自绘描边，不加系统标题栏。
        """
        if os.name != "nt" or QtGui.QGuiApplication.platformName() != "windows":
            return                                   # 离屏/非 Windows：不动手
        try:                                         # pragma: no cover (平台相关)
            import ctypes
            from ctypes import wintypes
            hwnd = self._hwnd(self)
            if not hwnd:
                return
            user32 = ctypes.windll.user32
            GWL_STYLE, GWL_EXSTYLE = -16, -20
            WS_THICKFRAME, WS_MAXIMIZEBOX, WS_MINIMIZEBOX = 0x00040000, 0x00010000, 0x00020000
            WS_EX_APPWINDOW = 0x00040000
            get = user32.GetWindowLongPtrW
            get.restype, get.argtypes = ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int]
            put = user32.SetWindowLongPtrW
            put.restype, put.argtypes = (ctypes.c_ssize_t,
                                         [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t])
            style = get(hwnd, GWL_STYLE)
            put(hwnd, GWL_STYLE,
                style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX)
            ex = get(hwnd, GWL_EXSTYLE)
            put(hwnd, GWL_EXSTYLE, ex | WS_EX_APPWINDOW)
            # 样式改完要让系统重算一次非客户区，否则新边框不生效
            user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)   # NOSIZE|NOMOVE|NOZORDER|
                                                             # NOACTIVATE|FRAMECHANGED
        except Exception:
            pass

    def _apply_dwm(self) -> None:
        """向 DWM 讨一点系统质感：柔和的窗口阴影（Win11 上还有圆角）。

        做法是把 DWM 的边框往里延伸 1px —— 这 1px 由系统合成，于是系统会给无边框
        窗口补上阴影/圆角。我们自己的描边画在它这一层下面，所以颜色仍完全可控。
        Windows 以外、或调用失败时直接退化成"只有自绘描边"，不影响使用。
        """
        if os.name != "nt" or QtGui.QGuiApplication.platformName() != "windows":
            return
        try:                                             # pragma: no cover (平台相关)
            import ctypes

            class MARGINS(ctypes.Structure):
                _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                            ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

            hwnd = self._hwnd(self)
            if not hwnd:
                return
            dwm = ctypes.windll.dwmapi
            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(1, 1, 1, 1)))
            pref = ctypes.c_int(2)                       # DWMWCP_ROUND
            dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            # 边框色 = 我们的面板色。窗口一旦被系统最大化/吸附，DWM 会画一圈**系统边框**，
            # 默认是系统主题的浅色（就是用户看到的那条偏宽的"白条"）；把它染成主题色，
            # 这圈边框就看不见了。属性 34 是 Win11（22000+）才有，Win10 会被忽略。
            col = QtGui.QColor(style.PANEL)
            cref = ctypes.c_uint32(col.red() | (col.green() << 8) | (col.blue() << 16))
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(cref), ctypes.sizeof(cref))
        except Exception:
            pass

    # ------------------------------------------------------------ 悬停才出现的收回按钮
    def enterEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        self.btn_back.setVisible(True)
        self.btn_full.setVisible(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        self.btn_back.setVisible(False)
        self.btn_full.setVisible(False)
        super().leaveEvent(ev)

    def resizeEvent(self, ev) -> None:                  # noqa: N802 （Qt 接口名）
        super().resizeEvent(ev)
        self._place_buttons()

    def closeEvent(self, ev) -> None:                   # noqa: N802 （Qt 接口名）
        """浮窗没有关闭按钮，但 Alt+F4 / 系统关闭仍会走到这里。

        不能让它就这么消失：窗口一隐藏，这块面板就既不在主窗口、也不在任何可见的
        浮窗里 —— "面板丢了、怎么点都找不回来"正是这么发生的。一律改成"收回主窗口"。
        """
        ev.ignore()
        self.returned.emit(self.panel)

    def _keep_reachable(self) -> None:
        """整块窗口跑到所有屏幕之外时，把它拉回最近一块屏幕的中间。

        浮窗没有系统标题栏，一旦完全落在屏幕外就再也点不到、拖不回来（换屏 / 拔掉副屏
        时最容易发生）。只在"与任何屏幕都不相交"时才动手，正常拖动不受影响。
        """
        app = QtWidgets.QApplication.instance()
        screens = list(app.screens()) if app is not None else []
        if not screens:
            return
        fg = self.frameGeometry()
        for scr in screens:
            if scr.availableGeometry().intersects(fg):
                return
        cursor = QtGui.QCursor.pos()
        best = min(screens, key=lambda s: (s.availableGeometry().center()
                                           - cursor).manhattanLength())
        avail = best.availableGeometry()
        self.move(avail.left() + max(0, (avail.width() - self.width()) // 2),
                  avail.top() + max(0, (avail.height() - self.height()) // 2))

    def moveEvent(self, ev) -> None:                    # noqa: N802 （Qt 接口名）
        super().moveEvent(ev)
        self._keep_reachable()

    # ------------------------------------------------------------ 右下角隐形抓角
    def _in_grip(self, pos: QtCore.QPoint) -> bool:
        return (pos.x() >= self.width() - self.GRIP
                and pos.y() >= self.height() - self.GRIP)

    def mousePressEvent(self, ev) -> None:              # noqa: N802 （Qt 接口名）
        if (ev.button() == QtCore.Qt.MouseButton.LeftButton
                and self._in_grip(ev.position().toPoint())):
            self._grip_origin = (ev.globalPosition().toPoint(), self.size())
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:               # noqa: N802 （Qt 接口名）
        pos = ev.position().toPoint()
        if self._grip_origin is None:
            # 抓角上换个对角缩放光标 —— 无边框窗口没有任何"这里能拉"的暗示，
            # 光标是唯一的提示手段
            self.setCursor(QtCore.Qt.CursorShape.SizeFDiagCursor
                           if self._in_grip(pos)
                           else QtCore.Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(ev)
            return
        start, size = self._grip_origin
        delta = ev.globalPosition().toPoint() - start
        self.resize(max(self.MIN_SIZE[0], size.width() + delta.x()),
                    max(self.MIN_SIZE[1], size.height() + delta.y()))
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:            # noqa: N802 （Qt 接口名）
        self._grip_origin = None
        super().mouseReleaseEvent(ev)


# ==================================================================== 窗口设置
def _theme_swatch_pixmap(key: str, w: int = 46, h: int = 14) -> QtGui.QPixmap:
    """主题预览小色块：底色打底 + 面板色 + 强调色并排。

    这三个颜色是**那套主题自己的颜色**（不是当前主题的），所以这里必须写实色 ——
    它本来就是"看一眼这套主题长什么样"，箭头不会跟着界面主题变。
    """
    bg, panel, accent = style.swatch_colors(key)
    pm = QtGui.QPixmap(w, h)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    try:
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor(style.LINE_HI), 1))
        p.setBrush(QtGui.QColor(bg))
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, w - 1.0, h - 1.0), 3.0, 3.0)
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        half = (w - 8.0) / 2.0
        p.setBrush(QtGui.QColor(panel))
        p.drawRoundedRect(QtCore.QRectF(4.0, 3.0, half, h - 6.0), 1.5, 1.5)
        p.setBrush(QtGui.QColor(accent))
        p.drawRoundedRect(QtCore.QRectF(4.0 + half + 2.0, 3.0, half, h - 6.0), 1.5, 1.5)
    finally:
        p.end()
    return pm


class PreferencesDialog(QtWidgets.QDialog):
    """窗口设置：管左侧图标轨道里**加入哪些设置分组**，以及界面配色主题。

    第一版只做两件事，都围绕"这个界面该显示什么"：

    * **侧边栏**：勾选哪些分组出现在左侧轨道上。加入的图标点了会"跳到该设置"
      （展开左栏 + 展开那一组 + 滚过去高亮），不是"只显示一种"；
    * **外观**：选界面配色主题（含"跟随系统"）。**改主题不影响导出的 PNG/SVG** ——
      那一路永远是论文白底。

    主题**边选边生效**（所见即所得）：每点一个主题就通过 ``on_theme`` 通知主窗口
    立刻换一次；点"取消"时把进来时的主题原样还回去。

    分组的顺序 / 名词 / 说明由主窗口传进来，避免这里反向依赖 ``main_window``。
    """

    def __init__(self, group_order, group_titles, group_tips,
                 selected, theme_key="deepblue", on_theme=None,
                 follow_layout=True, show_split=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("窗口设置")
        self.setModal(True)
        self.setMinimumWidth(470)
        self._order = list(group_order)
        self._checks: dict[str, QtWidgets.QCheckBox] = {}
        self._theme_radios: dict[str, QtWidgets.QRadioButton] = {}
        self._original_theme = theme_key
        self._on_theme = on_theme

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        head = QtWidgets.QLabel("窗口设置")
        head.setObjectName("Title")
        root.addWidget(head)

        # ---- 侧边栏：勾选哪几组进轨道
        box = QtWidgets.QGroupBox("侧边栏显示哪些设置")
        col = QtWidgets.QVBoxLayout(box)
        col.setContentsMargins(12, 6, 12, 10)
        col.setSpacing(8)
        for key in self._order:
            row = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            cb = QtWidgets.QCheckBox(group_titles[key])
            cb.setChecked(key in selected)
            cb.setIcon(QtGui.QIcon(icons.group(key, 16, style.TEXT_DIM)))
            cb.setIconSize(QtCore.QSize(16, 16))
            cb.setMinimumWidth(124)
            self._checks[key] = cb
            tip = QtWidgets.QLabel(group_tips[key])
            tip.setObjectName("Hint")
            tip.setWordWrap(True)
            h.addWidget(cb, 0)
            h.addWidget(tip, 1)
            col.addWidget(row)

        quick = QtWidgets.QHBoxLayout()
        quick.setContentsMargins(0, 0, 0, 0)
        quick.setSpacing(6)
        quick.addStretch(1)
        for text, keys in (("恢复默认", list(self._order)),
                           ("全部加入", list(self._order)),
                           ("全部移除", [])):
            btn = QtWidgets.QPushButton(text)
            btn.setObjectName("Ghost")
            btn.clicked.connect(lambda _c=False, k=keys: self._set_keys(k))
            quick.addWidget(btn)
        col.addLayout(quick)
        root.addWidget(box)

        # ---- 外观：界面配色主题（边选边生效；导出图永远是论文白底，不受影响）
        abox = QtWidgets.QGroupBox("外观")
        acol = QtWidgets.QVBoxLayout(abox)
        acol.setContentsMargins(12, 6, 12, 10)
        acol.setSpacing(6)
        self._theme_group = QtWidgets.QButtonGroup(self)
        self._theme_group.setExclusive(True)
        for key, label in style.theme_choices():
            rb = QtWidgets.QRadioButton(label)
            rb.setChecked(key == theme_key)
            rb.toggled.connect(lambda on, k=key: on and self._preview_theme(k))
            self._theme_group.addButton(rb)
            self._theme_radios[key] = rb
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(rb)
            row.addStretch(1)
            swatch = QtWidgets.QLabel()
            swatch.setPixmap(_theme_swatch_pixmap(key))
            swatch.setToolTip("底色 / 面板 / 强调色")
            row.addWidget(swatch)
            acol.addLayout(row)
        atip = QtWidgets.QLabel(
            "「跟随系统」会跟着 Windows 的浅色/深色自动切。\n"
            "只改界面配色；导出的 PNG / SVG 始终是论文白底。")
        atip.setObjectName("Hint")
        atip.setWordWrap(True)
        acol.addWidget(atip)
        root.addWidget(abox)

        # ---- 窗口：总窗口大小要不要跟着右侧排版一起变
        wbox = QtWidgets.QGroupBox("窗口大小")
        wcol = QtWidgets.QVBoxLayout(wbox)
        wcol.setContentsMargins(12, 6, 12, 10)
        wcol.setSpacing(6)
        self.chk_follow = QtWidgets.QCheckBox("窗口大小跟随排版自动调整")
        self.chk_follow.setChecked(bool(follow_layout))
        wcol.addWidget(self.chk_follow)
        wtip = QtWidgets.QLabel(
            "打开时：切到单块、开关某一块、换摆法时，总窗口会按当前排版的自然尺寸\n"
            "一起变大或变小，避免只剩一块时被硬撑变形。\n"
            "关掉时：窗口只在空间不够时变大，绝不缩小（完全交给手动调整）。")
        wtip.setObjectName("Hint")
        wtip.setWordWrap(True)
        wcol.addWidget(wtip)
        root.addWidget(wbox)

        # ---- 分屏面板：胶囊上那颗「分屏」快捷按钮要不要出现
        sbox = QtWidgets.QGroupBox("分屏面板")
        scol = QtWidgets.QVBoxLayout(sbox)
        scol.setContentsMargins(12, 6, 12, 10)
        scol.setSpacing(6)
        self.chk_split = QtWidgets.QCheckBox("在胶囊上显示「分屏」快捷按钮")
        self.chk_split.setChecked(bool(show_split))
        scol.addWidget(self.chk_split)
        stip = QtWidgets.QLabel(
            "关掉后胶囊上的「分屏」按钮隐藏，摆法面板也不会再弹出。\n"
            "布局仍可用「拖动面板标题行」与「⇄」调整；默认布局照旧生效。")
        stip.setObjectName("Hint")
        stip.setWordWrap(True)
        scol.addWidget(stip)
        root.addWidget(sbox)

        note = QtWidgets.QLabel("更多设置后续加入。")
        note.setObjectName("Hint")
        root.addWidget(note)

        # ---- 确认 / 取消
        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(8)
        foot.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("确定")
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        root.addLayout(foot)

    def _set_keys(self, keys) -> None:
        chosen = set(keys)
        for key, cb in self._checks.items():
            cb.setChecked(key in chosen)

    def selected_keys(self) -> list[str]:
        """按分组顺序返回被勾选的 key（保持轨道里的固定顺序）。"""
        return [k for k in self._order if self._checks[k].isChecked()]

    def follow_layout(self) -> bool:
        """总窗口大小是否跟随排版自动调整。"""
        return bool(self.chk_follow.isChecked())

    def show_split_panel(self) -> bool:
        """胶囊上是否显示「分屏」快捷按钮（关掉后摆法面板不再弹出）。"""
        return bool(self.chk_split.isChecked())

    # ---------------------------------------------------------------- 外观
    def _preview_theme(self, key: str) -> None:
        """点某个主题就立刻换一次（不落盘）——所见即所得。"""
        if self._on_theme is not None:
            self._on_theme(key)

    def theme_key(self) -> str:
        """当前选中的主题键。"""
        for key, rb in self._theme_radios.items():
            if rb.isChecked():
                return key
        return self._original_theme

    def reject(self) -> None:                            # noqa: N802 （Qt 接口名）
        """取消：把进来时的主题还回去（预览已经改过界面了）。"""
        if self._on_theme is not None:
            self._on_theme(self._original_theme)
        super().reject()


# ==================================================================== 导入意图
class ImportIntentDialog(QtWidgets.QDialog):
    """拖入文件时的"意图确认框"：这份数据和当前数据是**对比**还是**替换**。

    只有在"已经有数据、且能读出这份数据的形状"时才会弹出：

    * 形状相同 → 【对比】【替换】【取消】
    * 形状不同 → 【替换】【取消】
    * 已达对比上限（再选对比）→ 先给一句提示，再给【替换当前激活的一份】【取消】

    键盘可操作：回车 = 主按钮（对比 / 替换当前激活），Esc = 取消。
    结果放在 :attr:`choice`：``"compare"`` / ``"replace"``，取消为 ``None``。
    """

    def __init__(self, file_name: str, shape_text: str, current_text: str,
                 *, allow_compare: bool, compare_blocked: bool = False,
                 dup_warning: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入数据")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.choice: str | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QtWidgets.QLabel(f"要导入　{file_name}")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        info = QtWidgets.QLabel(
            f"这份数据：{shape_text}\n"
            f"当前数据：{current_text}")
        info.setObjectName("Hint")
        info.setWordWrap(True)
        root.addWidget(info)

        if compare_blocked:
            blocked = QtWidgets.QLabel(
                f"已载入 {current_text}，并且对比数据已达上限；"
                "只能替换当前激活的一份，或取消。")
            blocked.setObjectName("Hint")
            blocked.setWordWrap(True)
            root.addWidget(blocked)
        elif dup_warning:
            warn = QtWidgets.QLabel(dup_warning)
            warn.setObjectName("Hint")
            warn.setWordWrap(True)
            root.addWidget(warn)
        elif allow_compare:
            ask = QtWidgets.QLabel("要和当前数据一起对比，还是替换掉它？")
            ask.setObjectName("Hint")
            ask.setWordWrap(True)
            root.addWidget(ask)
        else:
            ask = QtWidgets.QLabel("形状与当前数据不同，将替换当前数据。")
            ask.setObjectName("Hint")
            ask.setWordWrap(True)
            root.addWidget(ask)

        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(0, 4, 0, 0)
        foot.setSpacing(8)
        foot.addStretch(1)

        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)

        if compare_blocked:
            primary = QtWidgets.QPushButton("替换当前激活的一份")
            primary.setObjectName("Primary")
            primary.clicked.connect(lambda: self._pick("replace"))
            foot.addWidget(cancel)
            foot.addWidget(primary)
            primary.setDefault(True)
        else:
            replace = QtWidgets.QPushButton("替换")
            replace.clicked.connect(lambda: self._pick("replace"))
            foot.addWidget(cancel)
            if allow_compare:
                compare = QtWidgets.QPushButton("对比")
                compare.setObjectName("Primary")
                compare.clicked.connect(lambda: self._pick("compare"))
                foot.addWidget(replace)
                foot.addWidget(compare)
                compare.setDefault(True)
            else:
                replace.setObjectName("Primary")
                foot.addWidget(replace)
                replace.setDefault(True)
        root.addLayout(foot)

    def _pick(self, choice: str) -> None:
        self.choice = choice
        self.accept()

