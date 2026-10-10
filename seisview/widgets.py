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
    """标题 + 滑杆 + 等宽读数。"""

    valueChanged = QtCore.Signal(int)
    released = QtCore.Signal(int)

    def __init__(self, title: str, parent=None):
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
        head.addWidget(self.readout)
        lay.addLayout(head)

        self._suffix = ""
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self._on_change)
        self.slider.sliderReleased.connect(lambda: self.released.emit(self.slider.value()))
        lay.addWidget(self.slider)

    def _on_change(self, v: int) -> None:
        self.readout.setText(str(v) + self._suffix)
        self.valueChanged.emit(v)

    def configure(self, maximum: int, value: int = 0, suffix: str = "") -> None:
        self._suffix = suffix
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, maximum))
        self.slider.setValue(max(0, min(value, max(0, maximum))))
        self.slider.blockSignals(False)
        self.readout.setText(str(self.slider.value()) + suffix)

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

        self.error = QtWidgets.QLabel("")
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

        self.note_label = QtWidgets.QLabel("")
        self.note_label.setObjectName("Hint")
        self.note_label.setWordWrap(True)
        root.addWidget(self.note_label)

        # ---- SEG-Y / SU 专用参数
        self.seis_box = QtWidgets.QFrame()
        self.seis_box.setObjectName("Panel")
        sbox = QtWidgets.QVBoxLayout(self.seis_box)
        sbox.setContentsMargins(12, 10, 12, 10)
        sbox.setSpacing(7)
        sbox.addWidget(SectionLabel("道头参数（合成）"))

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        dt_us = int(round(volume.dt * 1e6)) or 1000
        self.spin_dt_us = WheelSafeSpinBox()
        self.spin_dt_us.setRange(1, 65535)
        self.spin_dt_us.setValue(min(65535, max(1, dt_us)))
        self.spin_dt_us.setSuffix(" µs")
        self.spin_dt_us.setMinimumWidth(110)
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
        for i, (name, w, tip) in enumerate([
                ("采样间隔", self.spin_dt_us, "写入二进制头与每道道头（TRACE_SAMPLE_INTERVAL）"),
                ("检波器间距 dx", self.spin_dx, "只在勾选下面「写入空间坐标」时使用"),
                ("炮点间距 ds", self.spin_ds, "只在勾选下面「写入空间坐标」时使用")]):
            lb = QtWidgets.QLabel(name)
            lb.setObjectName("Hint")
            lb.setToolTip(tip)
            w.setToolTip(tip)
            grid.addWidget(lb, i, 0)
            grid.addWidget(w, i, 1)
        sbox.addLayout(grid)

        self.chk_coords = QtWidgets.QCheckBox("写入空间坐标（SourceX / GroupX / offset）")
        self.chk_coords.setChecked(True)
        self.chk_coords.setToolTip(
            "勾选后按规则合成几何：\n"
            "SourceX = 炮号 × ds\n"
            "GroupX  = 炮号 × ds + 道号 × dx\n"
            "offset  = 道号 × dx\n"
            "三者自洽（offset == GroupX − SourceX）。\n"
            "dx 带小数时会写入坐标标量（SourceGroupScalar），避免小数被取整。")
        sbox.addWidget(self.chk_coords)

        self.seis_note = QtWidgets.QLabel(
            "道头按规则合成：FieldRecord = 炮号 + 1、TraceNumber = 道号 + 1、\n"
            "TRACE_SAMPLE_COUNT、TRACE_SAMPLE_INTERVAL；采样格式写 IEEE float32（格式码 5）。\n"
            "源文件原有的其它道头字段（CDP、高程、日期等）不会被带过来。")
        self.seis_note.setObjectName("Hint")
        self.seis_note.setWordWrap(True)
        sbox.addWidget(self.seis_note)
        root.addWidget(self.seis_box)

        self.error = QtWidgets.QLabel("")
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

    # ---------------------------------------------------------------- 交互
    def _on_format(self) -> None:
        fmt = self.fmt()
        seis = fmt in exporter.SEISMIC_KEYS
        self.seis_box.setVisible(seis)

        cur = self.path()
        p = Path(cur) if cur else None
        if p is None or p.suffix.lower() not in self._suffixes:
            p = Path(self._dir) / (self._stem + exporter.SUFFIX_OF[fmt])
        else:
            p = p.with_suffix(exporter.SUFFIX_OF[fmt])
        self.path_edit.setText(str(p))

        self.scale_label.setText(exporter.describe(self._vol.data, fmt))
        if seis:
            self.note_label.setText(
                "SEG-Y / SU 是「逐道带道头」的格式，立方体是个抽象网格，\n"
                "所以这里会合成一套最小但正确的道头，保证任何软件都能正确定位与分选。")
        else:
            self.note_label.setText(
                "⚠ 只导出数据矩阵：不含 dt / dx / ds 等元信息（标尺会丢），\n"
                "缺道位置以 0 填充，因此下游无法区分「真 0」与「缺道」。\n"
                "数据形状 S × R × T = 炮 × 检波器 × 时间，未做任何显示相关的处理。")
        self.error.setText("")

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出到", self.path(),
            f"{self.combo_fmt.currentText()} (*{exporter.SUFFIX_OF[self.fmt()]});;所有文件 (*)")
        if path:
            if not Path(path).suffix:
                path += exporter.SUFFIX_OF[self.fmt()]
            self.path_edit.setText(path)

    def _validate(self) -> None:
        path = self.path()
        if not path:
            self.error.setText("请先指定保存路径。")
            return
        p = Path(path)
        if p.parent and not p.parent.exists():
            self.error.setText(f"目录不存在：{p.parent}")
            return
        if p.exists():
            ans = QtWidgets.QMessageBox.question(
                self, "覆盖确认", f"{p.name} 已存在，覆盖吗？",
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No)
            if ans != QtWidgets.QMessageBox.StandardButton.Yes:
                return
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