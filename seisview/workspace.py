"""右侧工作区容器与内容面板标题行。"""

from __future__ import annotations

from PySide6 import QtWidgets

from . import icons, style
from .widgets import SectionLabel


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


