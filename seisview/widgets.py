"""自定义控件：分段选择、参数滑杆、播放头轨道、变量表、轴序确认框、数组数值查看。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import export as exporter
from . import render, style
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
    """下拉框：滚轮不改值。"""


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


# ==================================================================== 分段控件
_SEG_QSS = f"""
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
    color: #EAF7FF;
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
        self.setStyleSheet(_SEG_QSS)
        self._group.idClicked.connect(self._on_clicked)
        if self._keys:
            self.set_value(self._keys[0])

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
    """面板标题栏上的折叠/展开按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Chevron")
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        self.setText("▾" if expanded else "▸")
        self.setToolTip("折叠此面板" if expanded else "展开此面板")


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
    """导出 / 转换：把当前体数据写成矩阵，或重写成 SEG-Y / SU。

    两种目标的性质差别很大，所以这里把取舍写在明面上：
    矩阵格式只写数据、不带标尺；SEG-Y / SU 会**合成**一套最小但正确的道头
    （不是复制源文件的道头）。
    """

    def __init__(self, volume, default_dir, default_stem: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出 / 转换")
        self.setModal(True)
        self.setMinimumWidth(540)
        self._vol = volume
        self._dir = str(default_dir)
        self._stem = default_stem
        self._suffixes = set(exporter.SUFFIX_OF.values())
        self._fitted = False                        # 首次弹出时统一一次尺寸

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        head = QtWidgets.QLabel(f"导出体数据　{volume.name}")
        head.setObjectName("Title")
        head.setWordWrap(True)
        root.addWidget(head)

        # ---- 格式
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QtWidgets.QLabel("目标格式")
        lab.setObjectName("Hint")
        self.combo_fmt = WheelSafeComboBox()
        for name, key in exporter.EXPORT_FORMATS:
            self.combo_fmt.addItem(name, key)
        self.combo_fmt.currentIndexChanged.connect(self._on_format)
        row.addWidget(lab)
        row.addWidget(self.combo_fmt, 1)
        root.addLayout(row)

        # ---- 路径
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QtWidgets.QLabel("保存到")
        lab.setObjectName("Hint")
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setMinimumWidth(300)
        btn_browse = QtWidgets.QPushButton("浏览…")
        btn_browse.setObjectName("Ghost")
        btn_browse.clicked.connect(self._browse)
        row.addWidget(lab)
        row.addWidget(self.path_edit, 1)
        row.addWidget(btn_browse)
        root.addLayout(row)

        # ---- 规模 / 提示
        self.scale_label = QtWidgets.QLabel("")
        self.scale_label.setObjectName("Hint")
        self.scale_label.setWordWrap(True)
        root.addWidget(self.scale_label)

        # 没话说就自动收起来：SEG-Y / SU 下这条说明是空的，留着就是一个空盒子
        self.note_label = _AutoHideLabel("")
        self.note_label.setObjectName("Hint")
        self.note_label.setWordWrap(True)
        root.addWidget(self.note_label)

        # ---- 逐剖面导出（只对矩阵格式有意义）
        # 与 SEG-Y 参数区同一个套路：勾选框 + 缩进子块，没勾就置灰。
        self.chk_slices = QtWidgets.QCheckBox("逐剖面导出（每片一个文件，存进上面的文件夹）")
        self.chk_slices.setToolTip(
            "沿一个方向切开，每片写成一个独立的二维矩阵文件。\n"
            "例如 901 个共炮点剖面 → 901 个文件。\n"
            "勾上之后「保存到」那一栏填的是文件夹，不是文件。\n"
            "每片的方向与剖面窗口一致：行 = 纵轴、列 = 横轴。")
        self.chk_slices.toggled.connect(self._on_slices_toggled)
        root.addWidget(self.chk_slices)

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
        self.combo_axis.currentIndexChanged.connect(lambda _i: self._refresh_slice_texts())
        self.edit_name = QtWidgets.QLineEdit(self._stem)     # 先填一个具体名字，用户可改
        self.edit_name.setPlaceholderText("可留空，留空就是 0 / 1 / 2 …")
        self.edit_name.setToolTip(
            "生成的文件名 = 文件名 + 下划线 + 序号 + 目标格式，例如 demo_7.mat。\n"
            "序号就是该方向的炮号 / 道号 / 时间采样号。\n"
            "留空则直接用序号做文件名，例如 7.mat。")
        self.edit_name.textChanged.connect(lambda _t: self._refresh_slice_texts())
        for i, (label, w) in enumerate([("剖面方向", self.combo_axis),
                                       ("文件名", self.edit_name)]):
            lb = QtWidgets.QLabel(label)
            lb.setObjectName("Hint")
            grid.addWidget(lb, i, 0)
            grid.addWidget(w, i, 1)
        body.addLayout(grid)

        # 一句话把规则说清楚 + 一个具体例子。两行都是短句，不随状态换行数，
        # 所以勾选前后对话框高度一动不动。
        self.slice_rule = QtWidgets.QLabel("")
        self.slice_rule.setObjectName("Hint")
        self.slice_rule.setWordWrap(True)
        body.addWidget(self.slice_rule)

        self.slice_preview = QtWidgets.QLabel("")
        self.slice_preview.setObjectName("Hint")
        self.slice_preview.setWordWrap(True)
        body.addWidget(self.slice_preview)
        root.addWidget(self.slices_body)

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

        dt_us = int(round(volume.dt * 1e6)) or 1000
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

        need = QtWidgets.QLabel(
            f"每道 {volume.nt} 个采样、共 {volume.ns * volume.nr} 道 —— 这两项自动取自数据。")
        need.setObjectName("Hint")
        need.setWordWrap(True)
        sbox.addWidget(need)

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
        self.spin_dx.setValue(float(volume.dx))
        self.spin_dx.setSuffix(" m")
        self.spin_dx.setMinimumWidth(110)
        self.spin_ds = WheelSafeDoubleSpinBox()
        self.spin_ds.setRange(0.0, 1e6)
        self.spin_ds.setDecimals(3)
        self.spin_ds.setValue(float(volume.ds))
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

        self._on_format()

    # ---------------------------------------------------------------- 取值
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

    def per_slice(self) -> bool:
        """是否逐剖面导出。用格式判定而不是 isVisible()：弹出前也要答对。"""
        return self.fmt() in exporter.MATRIX_KEYS and self.chk_slices.isChecked()

    def slice_axis(self) -> str:
        return self.combo_axis.currentData() or "shot"

    def name_prefix(self) -> str:
        """单片文件名的前缀（可留空，留空就是纯序号）。"""
        return self.edit_name.text().strip()

    def _sync_coords_enabled(self) -> None:
        """勾了「写入坐标道头」才需要填下面两个间距 —— 没勾就把它们置灰。

        用置灰而不是隐藏：对话框高度不会跳，而且能看出"这里有两个参数，
        勾上就能填"。（:disabled 的样式在 style.py 里，现在看得出来了。）
        """
        self.coords_body.setEnabled(self.chk_coords.isChecked())

    def _sync_slices_enabled(self) -> None:
        self.slices_body.setEnabled(self.chk_slices.isChecked())

    # ---------------------------------------------------------------- 交互
    def _on_slices_toggled(self, _checked: bool = False) -> None:
        self._sync_slices_enabled()
        self._refresh_path()
        self._refresh_slice_texts()

    def _on_format(self) -> None:
        fmt = self.fmt()
        seis = fmt in exporter.SEISMIC_KEYS
        matrix = fmt in exporter.MATRIX_KEYS
        self.seis_box.setVisible(seis)

        # 逐剖面只对矩阵格式有意义：切到 SEG-Y / SU 时，连勾选框和下面那一整块
        # 都收起来，别留下一堆用不上的东西
        self.chk_slices.setVisible(matrix)
        self.slices_body.setVisible(matrix)
        if not matrix and self.chk_slices.isChecked():
            self.chk_slices.setChecked(False)
        self._sync_slices_enabled()

        self._refresh_path()
        self._refresh_scale_label()
        if seis:
            self.note_label.setText("")
        else:
            self.note_label.setText(
                "⚠ 只导出数据矩阵（形状 = 炮 × 检波器 × 时间）：\n"
                "不含 dt / dx / ds 等元信息（标尺会丢）；缺道以 0 填充。")
        self.error.setText("")
        self._refresh_slice_texts()
        self._refit_height()

    def _refresh_path(self) -> None:
        """路径栏的语义随模式变：整卷导出填**文件**，逐剖面导出填**文件夹**。

        标签文字**不跟着变** —— 「保存到」和「保存到文件夹」宽度不同，一改就会把
        右边的输入框挤得左右跳。文件夹这件事写在勾选框文字和提示里。
        """
        cur = self.path()
        if self.per_slice():
            p = Path(cur) if cur else Path(self._dir)
            if p.suffix.lower() in self._suffixes:      # 原来是文件 → 退到它所在的目录
                p = p.parent
            self.path_edit.setText(str(p))
        else:
            suffix = exporter.SUFFIX_OF[self.fmt()]
            p = Path(cur) if cur else None
            if p is not None and p.suffix.lower() in self._suffixes:
                p = p.with_suffix(suffix)
            else:
                # 当前是个目录（刚在逐剖面模式下）→ 在它里面放默认文件名
                base = p if (p is not None and str(p)) else Path(self._dir)
                p = base / (self._stem + suffix)
            self.path_edit.setText(str(p))

    def _refresh_scale_label(self) -> None:
        """规模说明：整卷导出报整卷，逐剖面报「多少片、每片多大」。"""
        if self.per_slice():
            self.scale_label.setText(
                exporter.describe_slices(self._vol.data, self.slice_axis(), self.fmt()))
        else:
            self.scale_label.setText(exporter.describe(self._vol.data, self.fmt()))

    def _refresh_slice_texts(self) -> None:
        """规则一句 + 例子一行，**两行永远都有内容**。

        不按勾选状态清空：空标签会被全局样式刷成一个暗色小方块（空盒子），
        而「勾上才出现一行」又会让对话框高度在勾选时跳一下 —— 两头都不讨好。
        子块没勾时整体是置灰的，看例子也清楚「这是勾上以后的效果」。
        """
        self._refresh_scale_label()
        axis = self.slice_axis()
        word = exporter.SLICE_INDEX_WORD.get(axis, "序号")
        suffix = exporter.SUFFIX_OF[self.fmt()]
        self.slice_rule.setText(
            f"规则：文件名 + 下划线 + {word} + {suffix}；文件名留空就只用{word}。")
        try:
            exporter.check_name(self.name_prefix())
        except exporter.ExportError as exc:
            self.slice_preview.setText(f"⚠ {exc}")
            self._refit_height()
            return
        total = exporter.slice_count(self._vol.data, axis)
        names = [exporter.slice_name(self.name_prefix(), i, suffix)
                 for i in range(min(2, total))]
        more = "…" if total > len(names) else ""
        self.slice_preview.setText(f"例：{'、'.join(names)}{more}　共 {total} 个文件")
        self._refit_height()

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
        if self.per_slice():                    # 逐剖面导出选的是文件夹
            folder = QtWidgets.QFileDialog.getExistingDirectory(
                self, "选择导出文件夹", self.path())
            if folder:
                self.path_edit.setText(folder)
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出到", self.path(),
            f"{self.combo_fmt.currentText()} (*{exporter.SUFFIX_OF[self.fmt()]});;所有文件 (*)")
        if path:
            if not Path(path).suffix:
                path += exporter.SUFFIX_OF[self.fmt()]
            self.path_edit.setText(path)

    def _fail(self, message: str) -> None:
        """报错：显示文字并让对话框把这段高度撑开（不然红字会被挤掉）。"""
        self.error.setText(message)
        self._refit_height()

    def summary(self) -> str:
        """把「这次导出到底要干什么」汇总成几行，给确认框用。"""
        vol, fmt = self._vol, self.fmt()
        lines = [f"格式：{exporter.LABEL_OF.get(fmt, fmt)}"]
        if self.per_slice():
            axis = self.slice_axis()
            total = exporter.slice_count(vol.data, axis)
            rows, cols = exporter.slice_shape(vol.data, axis)
            lines.append(f"内容：逐剖面导出 {total} 个文件"
                         f"（沿「{exporter.SLICE_LABEL_OF.get(axis, axis)}」，"
                         f"每片 {rows} × {cols}）")
            lines.append(f"文件夹：{self.path()}")
            heads = [exporter.slice_name(self.name_prefix(), i, exporter.SUFFIX_OF[fmt])
                     for i in range(min(2, total))]
            lines.append("文件名：" + "、".join(heads) + ("…" if total > len(heads) else ""))
        else:
            n_shot, n_r, n_t = (int(v) for v in vol.shape)
            size = exporter.size_text(int(vol.data.size) * 4)
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
        exists = (not self.per_slice()) and Path(self.path()).exists()
        body = self.summary()
        if self.per_slice():
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
        box.setDefaultButton(cancel if (exists or self.per_slice()) else ok)
        box.exec()
        return box.clickedButton() is ok

    def _validate(self) -> None:
        path = self.path()
        if self.per_slice():
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