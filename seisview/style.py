"""暗色主题：调色板、字体、QSS。"""

from __future__ import annotations

from PySide6 import QtGui

# ------------------------------------------------------------------ 调色板
BG = "#0B0E14"        # 最底层背景
PANEL = "#111620"     # 面板
CARD = "#1A2130"      # 卡片 / 悬浮
LINE = "#232C3D"      # 1px 描边
LINE_HI = "#3D4A63"   # 描边高亮
ACCENT = "#38BDF8"    # 主强调色（天青）
ACCENT_DIM = "#1E5C78"
OK = "#34D399"        # 成功 / 播放
WARN = "#FBBF24"
ERR = "#F87171"
TEXT = "#E6EDF7"      # 主文字
TEXT_DIM = "#8A94A6"  # 次文字
TEXT_MUTE = "#5A6474" # 弱文字
GL_BG = "#0B0E14"
GL_BOX = "#3D4A63"

UI_FONT = "Segoe UI"
MONO_FONT = "Cascadia Mono"

QSS = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "{UI_FONT}", "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 12px;
}}
QToolTip {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {LINE_HI};
    padding: 4px 6px;
}}

/* ---------------------------------------------------------- 面板 / 卡片 */
QFrame#Panel {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 6px;
}}
QLabel#SectionTitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
    padding: 2px 0px;
}}
QLabel#Title {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#Value {{
    font-family: "{MONO_FONT}", Consolas, monospace;
    color: {ACCENT};
    font-size: 11px;
}}
QLabel#Hint {{
    color: {TEXT_MUTE};
    font-size: 11px;
}}
QLabel#Status {{
    font-family: "{MONO_FONT}", Consolas, monospace;
    color: {TEXT_DIM};
    font-size: 11px;
}}

/* ---------------------------------------------------------------- 按钮 */
QPushButton {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 5px 12px;
    color: {TEXT};
}}
QPushButton:hover {{
    background-color: #222B3C;
    border-color: {LINE_HI};
}}
QPushButton:pressed {{
    background-color: #17202E;
}}
QPushButton:disabled {{
    color: {TEXT_MUTE};
    background-color: #131A26;
    border-color: #1C2434;
}}
QPushButton#Primary {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    color: #EAF7FF;
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background-color: #24708F;
}}
QPushButton#Ghost {{
    background-color: transparent;
    border: 1px solid {LINE};
    color: {TEXT_DIM};
}}
QPushButton#Ghost:hover {{
    color: {TEXT};
    border-color: {LINE_HI};
}}
QPushButton#Play {{
    background-color: #123B2E;
    border-color: {OK};
    color: #CFFCE9;
    font-weight: 600;
}}
QPushButton#Play:hover {{
    background-color: #17513E;
}}

/* --------------------------------------------------------------- 折叠按钮 */
QToolButton#Chevron {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    font-size: 13px;
    padding: 0px 3px;
}}
QToolButton#Chevron:hover {{
    color: {ACCENT};
}}

/* --------------------------------------------------------------- 下拉框 */
QComboBox {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {LINE_HI}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    border: 1px solid {LINE_HI};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}

/* --------------------------------------------------------------- 数字框 */
QSpinBox, QDoubleSpinBox {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 3px 6px;
    font-family: "{MONO_FONT}", Consolas, monospace;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}

/* ---------------------------------------------------------------- 滑块 */
QSlider::groove:horizontal {{
    height: 2px;
    background: {LINE_HI};
    border-radius: 1px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    height: 2px;
    border-radius: 1px;
}}
QSlider::handle:horizontal {{
    background: #D8E6F5;
    width: 8px;
    height: 8px;
    margin: -4px 0;
    border-radius: 4px;
}}
QSlider::handle:horizontal:hover {{
    background: {ACCENT};
    width: 10px;
    height: 10px;
    margin: -5px 0;
    border-radius: 5px;
}}

/* ---------------------------------------------------------------- 勾选 */
QCheckBox {{ spacing: 6px; color: {TEXT_DIM}; }}
QCheckBox::indicator {{
    width: 13px; height: 13px;
    border: 1px solid {LINE_HI};
    border-radius: 3px;
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

/* ---------------------------------------------------------------- 表格 */
QTableWidget {{
    background-color: {PANEL};
    alternate-background-color: #141B28;
    border: 1px solid {LINE};
    border-radius: 6px;
    gridline-color: {LINE};
    selection-background-color: {ACCENT_DIM};
    selection-color: #EAF7FF;
}}
QTableWidget::item {{ padding: 3px 6px; }}
QHeaderView::section {{
    background-color: {CARD};
    color: {TEXT_DIM};
    border: none;
    border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE};
    padding: 5px 6px;
    font-size: 11px;
    font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {CARD}; border: none; }}

/* ---------------------------------------------------------------- 滚动条 */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {LINE_HI}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0px; }}
QScrollBar::handle:horizontal {{
    background: {LINE_HI}; border-radius: 5px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------------------------------------------------------- 分割条 */
QSplitter::handle {{ background-color: {LINE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {ACCENT}; }}

/* ---------------------------------------------------------------- 对话框 */
QDialog {{ background-color: {PANEL}; }}
QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    color: {TEXT_DIM};
    font-size: 11px;
}}
QProgressBar {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 3px;
    text-align: center;
    color: {TEXT_DIM};
    font-size: 10px;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 2px; }}
"""


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    app.setFont(QtGui.QFont(UI_FONT, 9))


def mono_font(size: int = 9) -> QtGui.QFont:
    f = QtGui.QFont(MONO_FONT, size)
    f.setStyleHint(QtGui.QFont.StyleHint.Monospace)
    return f