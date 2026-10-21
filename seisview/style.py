"""主题：调色板、字体、QSS。

主题机制
--------
界面颜色不再是一组写死的常量，而是**一份调色板**（:data:`THEMES`）。模块顶层的那些
名字（``BG`` / ``PANEL`` / ``TEXT`` …）在 :func:`set_theme` 时会被就地改写 ——
其它模块都是在**用的时候**才读 ``style.XXX``（画图标、画滑块、拼样式表都是如此），
所以换主题只要改这批全局名 + 重装样式表即可，不必到处传参。

两套颜色，互不干扰：

* **屏幕**：跟着主题走（``GL_BG`` / ``SCREEN_LINES`` …）。深色主题是深底亮线，
  浅色主题是白底深线 —— 屏幕曲线用的是"数据识别色"，每套主题各配一组。
* **导出**：永远是论文白底（``PAPER_*``），**与主题无关**。导出的 PNG/SVG 是要
  贴进论文/报告的，不能因为界面换了个皮就跟着变。
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui

# ------------------------------------------------------------------ 调色板
# 每组键与模块顶层的名字一一对应；set_theme 会把它们原样装回全局。
_DEEPBLUE = {
    "label": "深蓝（默认）",
    "BG": "#0B0E14", "PANEL": "#111620", "CARD": "#1A2130",
    "LINE": "#232C3D", "LINE_HI": "#3D4A63",
    "ACCENT": "#38BDF8", "ACCENT_DIM": "#1E5C78", "ON_ACCENT": "#EAF7FF",
    "PRIMARY_HOVER": "#24708F",
    "OK": "#34D399", "WARN": "#FBBF24", "ERR": "#F87171",
    "TEXT": "#E6EDF7", "TEXT_DIM": "#8A94A6", "TEXT_MUTE": "#5A6474",
    "TEXT_OFF": "#3B4453",
    "BTN_HOVER": "#222B3C", "BTN_PRESSED": "#17202E",
    "DISABLED_BG": "#131A26", "DISABLED_BORDER": "#1C2434",
    "PLAY_BG": "#123B2E", "PLAY_TEXT": "#CFFCE9", "PLAY_HOVER": "#17513E",
    "TABLE_ALT": "#141B28", "SLIDER_HANDLE": "#D8E6F5",
    "CAPSULE_BG": "rgba(11, 14, 20, 200)",
    "GL_BG": "#0B0E14", "GL_BOX": "#3D4A63",
    # 屏幕上的数据识别色（按下标取）：深底用亮色
    "SCREEN_LINES": ("#38BDF8", "#FACC15", "#F472B6", "#A78BFA"),
}

_MIDNIGHT = {
    "label": "极夜黑",
    "BG": "#000000", "PANEL": "#0A0A0C", "CARD": "#141417",
    "LINE": "#1E1E23", "LINE_HI": "#34343B",
    "ACCENT": "#22D3EE", "ACCENT_DIM": "#145E6B", "ON_ACCENT": "#E6FBFF",
    "PRIMARY_HOVER": "#17707F",
    "OK": "#34D399", "WARN": "#FBBF24", "ERR": "#F87171",
    "TEXT": "#EDEDED", "TEXT_DIM": "#9A9AA3", "TEXT_MUTE": "#6B6B74",
    "TEXT_OFF": "#45454C",
    "BTN_HOVER": "#191920", "BTN_PRESSED": "#101014",
    "DISABLED_BG": "#0C0C10", "DISABLED_BORDER": "#17171C",
    "PLAY_BG": "#06301F", "PLAY_TEXT": "#CFFCE9", "PLAY_HOVER": "#0A4530",
    "TABLE_ALT": "#0E0E12", "SLIDER_HANDLE": "#D6E4F0",
    "CAPSULE_BG": "rgba(0, 0, 0, 205)",
    "GL_BG": "#000000", "GL_BOX": "#34343B",
    "SCREEN_LINES": ("#22D3EE", "#FACC15", "#F472B6", "#A78BFA"),
}

_PAPER = {
    "label": "纸白（浅色）",
    "BG": "#F1F3F7", "PANEL": "#FFFFFF", "CARD": "#EAEEF4",
    "LINE": "#D5DBE4", "LINE_HI": "#AEB8C6",
    "ACCENT": "#2563EB", "ACCENT_DIM": "#2563EB", "ON_ACCENT": "#FFFFFF",
    "PRIMARY_HOVER": "#1D4ED8",
    "OK": "#0E9F6E", "WARN": "#B45309", "ERR": "#DC2626",
    "TEXT": "#171A20", "TEXT_DIM": "#525A68", "TEXT_MUTE": "#7C8698",
    "TEXT_OFF": "#AEB6C2",
    "BTN_HOVER": "#E4E9F1", "BTN_PRESSED": "#D6DCE6",
    "DISABLED_BG": "#F0F2F6", "DISABLED_BORDER": "#E1E5EC",
    "PLAY_BG": "#0E9F6E", "PLAY_TEXT": "#FFFFFF", "PLAY_HOVER": "#0B8A5F",
    "TABLE_ALT": "#F5F7FA", "SLIDER_HANDLE": "#8FA3BE",
    "CAPSULE_BG": "rgba(255, 255, 255, 216)",
    "GL_BG": "#FFFFFF", "GL_BOX": "#AEB8C6",
    # 白底上要用深色线，才看得清
    "SCREEN_LINES": ("#0369A1", "#B45309", "#BE185D", "#6D28D9"),
}

_CONTRAST = {
    "label": "高对比",
    "BG": "#000000", "PANEL": "#0A0A0A", "CARD": "#1A1A1A",
    "LINE": "#3A3A3A", "LINE_HI": "#707070",
    "ACCENT": "#FFD400", "ACCENT_DIM": "#6B5900", "ON_ACCENT": "#FFFBD6",
    "PRIMARY_HOVER": "#8A7400",
    "OK": "#00E676", "WARN": "#FFB300", "ERR": "#FF5252",
    "TEXT": "#FFFFFF", "TEXT_DIM": "#D6D6D6", "TEXT_MUTE": "#A8A8A8",
    "TEXT_OFF": "#6E6E6E",
    "BTN_HOVER": "#242424", "BTN_PRESSED": "#141414",
    "DISABLED_BG": "#0F0F0F", "DISABLED_BORDER": "#2A2A2A",
    "PLAY_BG": "#004D2E", "PLAY_TEXT": "#FFFFFF", "PLAY_HOVER": "#006B41",
    "TABLE_ALT": "#121212", "SLIDER_HANDLE": "#FFFFFF",
    "CAPSULE_BG": "rgba(0, 0, 0, 226)",
    "GL_BG": "#000000", "GL_BOX": "#707070",
    "SCREEN_LINES": ("#FFD400", "#00E5FF", "#FF5EC8", "#9DFF6B"),
}

# 玫瑰红：深酒红底 + 粉珊瑚强调色，适合长时间看剖面的暖色主题
_ROSE = {
    "label": "玫瑰红",
    "BG": "#140B10", "PANEL": "#1E1018", "CARD": "#2C1622",
    "LINE": "#40202E", "LINE_HI": "#65364A",
    "ACCENT": "#FB7185", "ACCENT_DIM": "#7C2D3E", "ON_ACCENT": "#FFF1F4",
    "PRIMARY_HOVER": "#B2455A",
    "OK": "#34D399", "WARN": "#FBBF24", "ERR": "#F87171",
    "TEXT": "#F7E8EE", "TEXT_DIM": "#C29AA9", "TEXT_MUTE": "#8A6374",
    "TEXT_OFF": "#4F3240",
    "BTN_HOVER": "#351A27", "BTN_PRESSED": "#27121D",
    "DISABLED_BG": "#1A0D14", "DISABLED_BORDER": "#2E1723",
    "PLAY_BG": "#5B1F31", "PLAY_TEXT": "#FFE4EB", "PLAY_HOVER": "#7A2B43",
    "TABLE_ALT": "#20121B", "SLIDER_HANDLE": "#FFD6E0",
    "CAPSULE_BG": "rgba(20, 11, 16, 205)",
    "GL_BG": "#140B10", "GL_BOX": "#65364A",
    "SCREEN_LINES": ("#FB7185", "#FBBF24", "#38BDF8", "#A78BFA"),
}

# 磨砂灰：低反差、低饱和的冷灰层，面板用比底色浅一档的表面色模拟“雾面”
_FROST = {
    "label": "磨砂灰（低反差）",
    "BG": "#141A1F", "PANEL": "#1C232A", "CARD": "#252E36",
    "LINE": "#323D46", "LINE_HI": "#4E5D68",
    "ACCENT": "#8BD3E6", "ACCENT_DIM": "#3A6C7A", "ON_ACCENT": "#F2FBFF",
    "PRIMARY_HOVER": "#57A9BC",
    "OK": "#5FD3A6", "WARN": "#E8C15A", "ERR": "#F08A8A",
    "TEXT": "#EAF2F7", "TEXT_DIM": "#A9BBC7", "TEXT_MUTE": "#788B98",
    "TEXT_OFF": "#4A5A64",
    "BTN_HOVER": "#2D373F", "BTN_PRESSED": "#232B32",
    "DISABLED_BG": "#1A2026", "DISABLED_BORDER": "#2A333A",
    "PLAY_BG": "#1E4A3E", "PLAY_TEXT": "#DFF8EE", "PLAY_HOVER": "#2A6150",
    "TABLE_ALT": "#202830", "SLIDER_HANDLE": "#DCEBF3",
    "CAPSULE_BG": "rgba(20, 26, 31, 200)",
    "GL_BG": "#141A1F", "GL_BOX": "#4E5D68",
    "SCREEN_LINES": ("#8BD3E6", "#F3D27A", "#F2A7C3", "#B9A7F0"),
}

THEMES: dict[str, dict] = {
    "deepblue": _DEEPBLUE,
    "midnight": _MIDNIGHT,
    "paper": _PAPER,
    "contrast": _CONTRAST,
    "rose": _ROSE,
    "frost": _FROST,
}
# 可选主题的顺序（界面里就按这个列）
THEME_ORDER = ("deepblue", "midnight", "paper", "contrast", "rose", "frost")
# "跟随系统"：浅色系统 → 纸白，深色系统 → 极夜黑
SYSTEM_KEY = "system"
_SYSTEM_LIGHT = "paper"
_SYSTEM_DARK = "midnight"

# "论文用图"观感：**只给导出的 png/svg 用**（屏幕上一律走主题）。
# 白底 + 深色坐标轴是论文里最通用的样子，也是黑/红/蓝细线能看清的前提。
# 这三个值**不随主题变** —— 导出图不该因为界面换皮而改变。
PAPER_BG = "#FFFFFF"
PAPER_INK = "#333333"
PAPER_GRID = "#DCE3EC"

UI_FONT = "Segoe UI"
MONO_FONT = "Cascadia Mono"

# 当前主题键（"system" 也照原样记着，便于界面回显）
_current_key = "deepblue"
_current_resolved = "deepblue"


def _install(name: str) -> None:
    """把某套调色板装到模块全局名上，并重算样式表。"""
    global QSS, _current_resolved
    for key, value in THEMES[name].items():
        if key == "label":
            continue
        globals()[key] = value
    _current_resolved = name
    QSS = _build_qss()


def system_color_scheme() -> str:
    """系统当前是深色还是浅色（''hints' 拿不到时按深色算）。"""
    hints = QtGui.QGuiApplication.styleHints()
    if hints is None:                                   # pragma: no cover
        return "dark"
    try:
        scheme = hints.colorScheme()
    except Exception:                                   # pragma: no cover
        return "dark"
    if scheme == QtCore.Qt.ColorScheme.Light:
        return "light"
    if scheme == QtCore.Qt.ColorScheme.Dark:
        return "dark"
    return "dark"                                       # Unknown：按深色兜底


def resolve_key(key: str) -> str:
    """"system" → 具体主题键；其它键原样返回（不在表里的退回默认）。"""
    if key == SYSTEM_KEY:
        return _SYSTEM_LIGHT if system_color_scheme() == "light" else _SYSTEM_DARK
    return key if key in THEMES else "deepblue"


def theme_label(key: str) -> str:
    if key == SYSTEM_KEY:
        return "跟随系统"
    return THEMES.get(key, THEMES["deepblue"])["label"]


def theme_choices() -> list[tuple[str, str]]:
    """界面用：``[(主题键, 显示名), ...]``，含"跟随系统"。"""
    items = [(SYSTEM_KEY, theme_label(SYSTEM_KEY))]
    items += [(k, THEMES[k]["label"]) for k in THEME_ORDER]
    return items


def swatch_colors(key: str) -> tuple[str, str, str]:
    """界面预览用的一组色块：``(底色, 面板色, 强调色)``。"""
    name = resolve_key(key)
    p = THEMES[name]
    return (p["BG"], p["PANEL"], p["ACCENT"])


def set_theme(key: str, app=None) -> str:
    """切换主题（``key`` 可为 ``"system"``）。返回实际生效的主题键。

    加载顺序很要紧：**先装调色板、再重装样式表**。QSS 是一整块字符串，重装时
    Qt 会把所有控件重新走一遍样式匹配 —— 颜色立刻生效，不需要重建控件。
    """
    global _current_key
    _current_key = key if (key in THEMES or key == SYSTEM_KEY) else "deepblue"
    _install(resolve_key(_current_key))
    if app is not None:
        app.setStyleSheet(QSS)
    return _current_resolved


def current_key() -> str:
    """当前**选择**的主题键（可能是 "system"）。"""
    return _current_key


def current_theme() -> str:
    """当前实际生效的主题键（不会是 "system"）。"""
    return _current_resolved


def _build_qss() -> str:
    """按**当前**调色板拼出整份样式表。

    每套主题都要重来一遍，所以它是个函数而不是一个常量。QSS 里所有颜色都走
    ``{TOKEN}`` —— 不留写死的十六进制"漏色点"，否则换主题时会有一两处颜色不变。
    """
    return f"""
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
/* 拖动换序时的高亮落点：正在被拖过去的那个剖面面板亮一圈强调色边框 */
QFrame#Panel[dropTarget="true"] {{
    border: 2px solid {ACCENT};
    background-color: {CARD};
}}
/* 拖动经过面板左右边缘的"感应带"：亮起一条竖条，提示"松手会插到这个位置" */
QFrame#Panel[dropLeft="true"] {{
    border-left: 3px solid {ACCENT};
    background-color: {CARD};
}}
QFrame#Panel[dropRight="true"] {{
    border-right: 3px solid {ACCENT};
    background-color: {CARD};
}}
/* 轨道图标跳转后，被跳到的那张设置卡片闪一下强调色边框（用于"指一下路"） */
QFrame#Panel[flash="true"] {{
    border: 1px solid {ACCENT};
    background-color: {CARD};
}}
/* 没有数据时剖面区里的引导文字 */
QLabel#EmptyHint {{
    color: {TEXT_MUTE};
    font-size: 13px;
    line-height: 170%;
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
/* 顶栏里那枚版本小签：等宽、低对比，一眼能认出是版本号但不抢标题 */
QLabel#Version {{
    font-family: "{MONO_FONT}", Consolas, monospace;
    color: {TEXT_MUTE};
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 7px;
    padding: 0px 6px;
    font-size: 10px;
}}
QLabel#Status {{
    font-family: "{MONO_FONT}", Consolas, monospace;
    color: {TEXT_DIM};
    font-size: 11px;
}}
/* 对比面板的小标题：带数据源识别色（颜色由控件的行内样式覆盖） */
QLabel#PanelTitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
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
    background-color: {BTN_HOVER};
    border-color: {LINE_HI};
}}
QPushButton:pressed {{
    background-color: {BTN_PRESSED};
}}
QPushButton:disabled {{
    color: {TEXT_MUTE};
    background-color: {DISABLED_BG};
    border-color: {DISABLED_BORDER};
}}
QPushButton#Primary {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton#Primary:hover {{
    background-color: {PRIMARY_HOVER};
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
    background-color: {PLAY_BG};
    border-color: {OK};
    color: {PLAY_TEXT};
    font-weight: 600;
}}
QPushButton#Play:hover {{
    background-color: {PLAY_HOVER};
}}
/* 顶栏的面板开关：勾选状态 = 该面板当前可见（旧版切换条留下的样式，仍被别处复用） */
QPushButton#Toggle {{
    background-color: transparent;
    border: 1px solid {LINE};
    color: {TEXT_MUTE};
}}
QPushButton#Toggle:hover {{
    color: {TEXT};
    border-color: {LINE_HI};
}}
QPushButton#Toggle:checked {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    color: {ON_ACCENT};
    font-weight: 600;
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
/* 设置分组的细箭头：纯图形按钮，不要边框与内边距，免得把标题行撑高 */
QToolButton#FoldArrow {{
    background: transparent;
    border: none;
    padding: 0px;
    margin: 0px;
}}

/* ------------------------------------------------------------ 图标轨道 */
/* 左栏最左侧那条常驻的图标轨道：收起整栏后只剩它 */
QFrame#Rail {{
    background-color: {PANEL};
    border: 1px solid {LINE};
    border-radius: 6px;
}}
QToolButton#RailBtn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 2px;
}}
QToolButton#RailBtn:hover {{
    background: {CARD};
}}
QToolButton#RailBtn:checked {{
    background: {ACCENT_DIM};
}}

/* ---------------------------------------------------------- 拖动 / 浮窗 */
/* 被拉出去的面板在独立窗口里：去掉描边与圆角，就是一块贴片（极简） */
QFrame#Panel[floating="true"] {{
    border: 0px;
    border-radius: 0px;
}}
/* 拖动中留在原位的虚线占位 */
QFrame#GhostSlot {{
    background: transparent;
    border: 1px dashed {LINE_HI};
    border-radius: 6px;
}}

/* ---------------------------------------------------------- 悬浮图标胶囊 */
/* 工作区右上角的面板开关：浮在内容之上，不占布局高度 */
QFrame#Capsule {{
    background-color: {CAPSULE_BG};
    border: 1px solid {LINE};
    border-radius: 8px;
}}
QToolButton#CapsuleBtn {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 1px;
}}
QToolButton#CapsuleBtn:hover {{
    background: {CARD};
}}
/* 胶囊上的分隔线与「分屏」按钮 */
QFrame#CapsuleSep {{
    background: {LINE};
    border: none;
}}
QToolButton#CapsuleBtnSplit {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 1px 2px;
    color: {TEXT_DIM};
    font-size: 11px;
}}
QToolButton#CapsuleBtnSplit:hover {{
    background: {CARD};
    color: {TEXT};
}}
/* 面板标题行右侧的小图标按钮（三维的「复位视角」） */
QToolButton#HeadBtn {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 1px;
}}
QToolButton#HeadBtn:hover {{ background: {CARD}; }}
/* 拖动时的工作区**落位预览**：松手后这一块会占的区域（半透明见 Workspace._preview_opacity） */
QFrame#EdgeHint {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: 3px;
}}
/* 胶囊右键弹出的「分屏方式 / 主视图」菜单 */
QFrame#LayoutPicker {{
    background-color: {CARD};
    border: 1px solid {LINE_HI};
    border-radius: 8px;
}}
QMenu {{
    background-color: {CARD};
    border: 1px solid {LINE_HI};
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 22px 5px 12px;
    border-radius: 4px;
    color: {TEXT};
}}
QMenu::item:selected {{
    background-color: {ACCENT_DIM};
    color: {ON_ACCENT};
}}
QMenu::separator {{
    height: 1px;
    background: {LINE};
    margin: 4px 6px;
}}
QMenu::indicator {{
    width: 12px;
    height: 12px;
    margin-left: 6px;
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

/* --------------------------------------------------------------- 输入框 */
QLineEdit {{
    background-color: {CARD};
    border: 1px solid {LINE};
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 18px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:hover {{ border-color: {LINE_HI}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:read-only {{ color: {TEXT_DIM}; }}

/* ------------------------------------------------------------ 禁用态外观 */
/* 控件被禁用时必须一眼看出来。之前这几个控件的 QSS 没写 :disabled 规则，
   灰掉之后和正常状态几乎一样，结果被当成"坏了、改不动值"。 */
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QLineEdit:disabled, QCheckBox:disabled {{
    color: {TEXT_MUTE};
    background-color: {BG};
    border-color: {LINE};
}}
/* 标签的禁用态要单独写：QSS 里 id 选择器（QLabel#Hint）优先级高于伪类，
   不然 QLabel:disabled 会被 QLabel#Hint 盖掉，置灰看不出来。 */
QLabel:disabled, QLabel#Hint:disabled, QLabel#Value:disabled, QLabel#Status:disabled {{
    color: {TEXT_OFF};
}}
QSlider::sub-page:horizontal:disabled {{ background: {LINE}; }}
QSlider::handle:horizontal:disabled {{ background: {LINE_HI}; }}

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
    background: {SLIDER_HANDLE};
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
    alternate-background-color: {TABLE_ALT};
    border: 1px solid {LINE};
    border-radius: 6px;
    gridline-color: {LINE};
    selection-background-color: {ACCENT_DIM};
    selection-color: {ON_ACCENT};
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

/* ------------------------------------------------- 对话框里的分级子块 */
/* 左侧一条竖线 + 缩进：让人一眼看出这几项是从属于上面那个复选框的，
   不用靠文字说明去解释"勾了才要填" */
QFrame#SubPanel {{
    border: none;
    border-left: 2px solid {LINE_HI};
    background: transparent;
}}
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


def apply_theme(app, key: str = "deepblue") -> str:
    """启动时装配：Fusion 风格 + 字号 + 指定主题的样式表。返回实际生效的主题键。

    启动时先用默认主题铺一遍（避免窗口还没建好就是一片系统默认灰），主窗口随后
    会按本地记下的偏好再调一次 :func:`set_theme`。
    """
    app.setStyle("Fusion")
    app.setFont(QtGui.QFont(UI_FONT, 9))
    return set_theme(key, app)


def mono_font(size: int = 9) -> QtGui.QFont:
    f = QtGui.QFont(MONO_FONT, size)
    f.setStyleHint(QtGui.QFont.StyleHint.Monospace)
    return f


# 导入时就把默认主题装上：模块顶层的那些颜色名（BG/PANEL/TEXT…）与 QSS
# 需要有值，其它模块一 import 就能直接用。
_install("deepblue")
