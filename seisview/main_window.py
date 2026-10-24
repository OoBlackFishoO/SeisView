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
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import APP_NAME, __version__
from . import icons, loaders, style, view2d
from .app_state import DisplaySettings, WorkspaceState
from .dataset_service import MAX_DATASETS, DatasetService
from .docking import DockingController
from .display_pipeline import DisplayPipeline
from .export_service import ExportService
from .layout_config import CAPSULE_KEY
from .layout_engine import LayoutEngine
from .figure_options import DEFAULT_LINE_STYLES
from .loaders import LoadError
from .models import Dataset
from .settings_cards import SettingsCards
from .sidebar import SidebarController
from .view2d import SlicePanel
from .view_trace import TraceView
from .volume import SLICE_LABELS, SeisVolume, display_face
from .workspace import Workspace, pane_header
from .widgets import (FloatingPanel, FoldCard, ImportIntentDialog,
                      PanelCapsule, ValueLabel, make_panel, pair_layout)

AXIS_TITLES = {"shot": "炮点 S", "recv": "检波器 R", "time": "时间 T"}

# 左栏的收起状态与分组展开状态会被记住（下次启动还原）。
# 设 SEISVIEW_NO_PERSIST=1 可以关掉，方便反复做"全新启动"的测试。
_PERSIST_UI = not os.environ.get("SEISVIEW_NO_PERSIST")

# 分屏摆法、面板次序、胶囊键与贴边判定常量见 layout_config.py


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
        self.setWindowTitle("SeisView")

        # ---------------------------------------------------------- 状态
        self.datasets: list[Dataset] = []
        self.active = 0
        self.src_path = ""                  # 变量表里当前列出的文件
        self.pipeline = DisplayPipeline()   # 色标、AGC、缓存与统计
        self.dataset_service = DatasetService(self)
        self.export_service = ExportService(self)
        self.workspace_state = WorkspaceState(    # 分屏布局与面板停靠状态
            content_shown={"slice": True, "trace": False, "right": False},
            pair_order=["slice", "right"],
            layout_preset="B",
        )
        self.layout_engine = LayoutEngine(self)
        self.docking = DockingController(self)
        self.sidebar = SidebarController(self)
        self.settings_cards = SettingsCards(self)
        self._clim_scale = 1.0              # 色标半窗宽的倍数（对比度滑块的换算结果）
        self.panels: list[SlicePanel] = []
        # 线型按"数据顺序槽位"保存（1→黑实、2→红实、3→蓝虚），与数据份数无关：
        # 删掉中间某份数据后，剩下的会顶到前面的槽位，配色跟着"从左到右"走。
        self.line_styles: list[tuple[str, str]] = list(DEFAULT_LINE_STYLES)
        # 双击复位的“撤销一次取道”：第一次 release 已经改过位置，双击时还原
        self._pick_undo: dict | None = None
        # 用户手动 resize 后的尺寸锚：切换构图不再主动缩小（见 _fit_window_to_layout）
        self._user_size: tuple[int, int] | None = None
        self._auto_resize_depth = 0        # 程序化改窗口尺寸时加锁，不写入用户锚
        # 最大化 / 全屏前的窗口几何；退出全屏时显式恢复它（见 changeEvent）
        self._pre_big_geometry: QtCore.QRect | None = None
        self._left_animating = False       # 侧栏收展动画中：窗口尺寸由动画驱动
        self._region_sizes: dict[str, list[int]] = {}
        # 拖动绿线时三维切片跟随：合并高频刷新，避免每个像素都重算三个面
        self._face_timer = QtCore.QTimer(self)
        self._face_timer.setSingleShot(True)
        self._face_timer.timeout.connect(self._refresh_faces)
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
        self._suppress_window_resize = False   # 换摆法时先别动窗口，交给 _animate_layout_change
        self._window_target: tuple[int, int] | None = None    # 最近一次算出的目标窗口尺寸
        self._layout_anim: QtCore.QPropertyAnimation | None = None
        self._three_auto_closed = False    # 三维是被"二维数据"自动收起的
        self._is_2d = False                # 当前数据集是不是二维（ns == 1）
        self._is_1d = False                # 当前数据集是不是单道（ns == nr == 1）
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
        # 对比度拖动合并刷新：滑杆每移一格都会发 valueChanged，逐次全量重绘会明显卡顿
        self._clim_timer = QtCore.QTimer(self)
        self._clim_timer.setSingleShot(True)
        self._clim_timer.setInterval(16)
        self._clim_timer.timeout.connect(self._apply_contrast)

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

    # --------------------------------------------------- 显示管线兼容视图
    # 外部（现有测试）仍按原字段名读取；真实状态由 DisplayPipeline 持有。
    @property
    def _clims(self) -> list[tuple[float, float]]:
        return self.pipeline.clims

    @property
    def _raw_cache(self) -> dict:
        return self.pipeline.raw_cache

    @property
    def _stats(self) -> dict:
        return self.pipeline.stats

    @property
    def _clim(self) -> tuple[float, float]:
        return self.pipeline.active_clim

    # --------------------------------------------------- 工作区状态兼容视图
    @property
    def _user_size(self):
        return self.workspace_state.user_size

    @_user_size.setter
    def _user_size(self, value):
        self.workspace_state.user_size = value

    @property
    def _region_shown(self):
        return self.workspace_state.region_shown

    @_region_shown.setter
    def _region_shown(self, value):
        self.workspace_state.region_shown = value

    @property
    def _content_shown(self):
        return self.workspace_state.content_shown

    @_content_shown.setter
    def _content_shown(self, value):
        self.workspace_state.content_shown = value

    @property
    def _pair_order(self):
        return self.workspace_state.pair_order

    @_pair_order.setter
    def _pair_order(self, value):
        self.workspace_state.pair_order = value

    @property
    def _layout_preset(self):
        return self.workspace_state.layout_preset

    @_layout_preset.setter
    def _layout_preset(self, value):
        self.workspace_state.layout_preset = value

    @property
    def _default3_key(self):
        return self.workspace_state.default3_key

    @_default3_key.setter
    def _default3_key(self, value):
        self.workspace_state.default3_key = value

    @property
    def _default3_order(self):
        return self.workspace_state.default3_order

    @_default3_order.setter
    def _default3_order(self, value):
        self.workspace_state.default3_order = value

    @property
    def _pair_defaults(self):
        return self.workspace_state.pair_defaults

    @_pair_defaults.setter
    def _pair_defaults(self, value):
        self.workspace_state.pair_defaults = value

    @property
    def _follow_layout(self):
        return self.workspace_state.follow_layout

    @_follow_layout.setter
    def _follow_layout(self, value):
        self.workspace_state.follow_layout = value

    @property
    def _window_target(self):
        return self.workspace_state.window_target

    @_window_target.setter
    def _window_target(self, value):
        self.workspace_state.window_target = value

    @property
    def _three_auto_closed(self):
        return self.workspace_state.three_auto_closed

    @_three_auto_closed.setter
    def _three_auto_closed(self, value):
        self.workspace_state.three_auto_closed = value

    @property
    def _is_2d(self):
        return self.workspace_state.is_2d

    @_is_2d.setter
    def _is_2d(self, value):
        self.workspace_state.is_2d = value

    @property
    def _is_1d(self):
        return self.workspace_state.is_1d

    @_is_1d.setter
    def _is_1d(self, value):
        self.workspace_state.is_1d = value

    @property
    def _detached(self):
        return self.workspace_state.detached

    @_detached.setter
    def _detached(self, value):
        self.workspace_state.detached = value

    @property
    def _drag_vis(self):
        return self.workspace_state.drag_vis

    @_drag_vis.setter
    def _drag_vis(self, value):
        self.workspace_state.drag_vis = value

    @property
    def _preview_dock(self):
        return self.workspace_state.preview_dock

    @_preview_dock.setter
    def _preview_dock(self, value):
        self.workspace_state.preview_dock = value

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
            # 单击 = 纯开关（显示↔收起）
            btn.clicked.connect(lambda _c=False, k=key: self._toggle_content(k))
        self.capsule.swap_btn.clicked.connect(self._swap_main)
        self.capsule.reset_btn.clicked.connect(self.reset_panel_layout)
        wrap.capsule = self.capsule
        wrap.place_capsule()
        self._sync_reset_entry()

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
        row.addWidget(title)
        row.addWidget(ver)
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
        self.btn_sample.setToolTip("24 炮 × 72 检波点 × 700 采样，dt = 0.002 s")
        self.btn_sample.clicked.connect(self.load_sample)

        self.btn_clear = QtWidgets.QPushButton("清空数据")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.setMinimumWidth(92)
        self.btn_clear.setEnabled(False)
        self.btn_clear.clicked.connect(self.clear_data)

        self.btn_export = QtWidgets.QPushButton("导出 / 转换")
        self.btn_export.setObjectName("Ghost")
        self.btn_export.setMinimumWidth(104)
        self.btn_export.setEnabled(False)
        self.btn_export.setToolTip("快捷键 Ctrl+E")
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
        self.left_empty_hint = QtWidgets.QLabel("在窗口设置中加入设置分组。")
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







    # ---------------------------------------------------- 图标轨道：状态同步









    # ---------------------------------------------------- 分组摘要（收起时显示）

    # ---------------------------------------------------- 左栏状态记忆




    # ---------------------------------------------------- 主题切换
















    # ------------------------------------------------------- 线型（颜色 / 线型）
    # 画笔与图例都交给 view2d 里那一个实现，保证面板 / wiggle / 导出图完全一致






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
        manual_on = not agc_on and self.clim_combo.currentData() == "manual"
        self.spin_manual.setEnabled(manual_on)

        pure = self.chk_pure.isChecked()
        wig_on = self.chk_wiggle.isChecked() or pure
        self.lab_wig.setEnabled(wig_on)
        self.spin_wig.setEnabled(wig_on)
        self.gain.setEnabled(wig_on)        # SliderRow 会把标题一起灰掉
        # 「仅显示波形」勾上后，叠加开关本身就没意义了（等价于已勾选）
        self.chk_wiggle.setEnabled(not pure)

        n = len(self.datasets)
        self.chk_sync.setEnabled(n > 1)
        self.btn_remove.setEnabled(n > 1)
        self.btn_add.setEnabled(0 < n < MAX_DATASETS or n == 0)

    def _on_gate_toggle(self, _checked: bool = False) -> None:
        """AGC / 叠加波形 开关：先同步置灰状态，再重画。"""
        self._sync_gated_controls()
        self._refresh_all()

    def _on_pure_toggle(self, _checked: bool) -> None:
        """「仅显示波形」开关：勾上时自动勾选「叠加波形」（纯波形必然要画曲线）。"""
        if self.chk_pure.isChecked() and not self.chk_wiggle.isChecked():
            self.chk_wiggle.blockSignals(True)
            self.chk_wiggle.setChecked(True)
            self.chk_wiggle.blockSignals(False)
        self._sync_gated_controls()
        self._refresh_all()

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
        lay.addWidget(self.slice_header)
        self.slice_frame = wrap

        self.slice_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.slice_split.setChildrenCollapsible(False)
        self.slice_split.setHandleWidth(3)
        lay.addWidget(self.slice_split, 1)
        # 没有数据时，这一块换成一句操作提示
        self.slice_empty = QtWidgets.QLabel("拖入数据文件，或点击「载入示例」")
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
        self.layout_engine._swap_main()



    # -------------------------------------------------------------- 复位 / 找回






    # ------------------------------------------------------ 胶囊 / 快捷键入口











    # ------------------------------------------------ 排版（预设）与动画
    # 三块容器的"静止最小尺寸"（只在动画结束后生效；动画期间必须放开，
    # 否则"收起到 0"会被最小尺寸顶回来）。上限值见 _panel_metrics 的自然尺寸。
    WS_CENTER_MIN = 320      # 剖面列的最小宽度
    CS_TRACE_MIN = 150       # 单道波形的最小高度


    # 剖面画布的"显示比例"下限（宽 / 高）：数据面本身可能很细长（例如 72 道 × 700 采样的
    # 共炮点面，天然比例只有约 0.1），宽度被 400 的下限抬起来后就成了"又高又窄"的竖长条，
    # 会把下方单道波形挤没。这里给高度再夹一个上限：高 ≤ 宽 / 下限（即宽:高 至少 4:5）。
    # 横长的数据面不受影响（那时宽 / 高远大于该下限）。
    SLICE_MIN_DISPLAY_ASPECT = 0.8


    # 让位时"后面的项还剩多少可视为下限"：不是它们的最小尺寸，而是一个很小的可见值。
    # 这样高优先级那块能拿满自己的自然尺寸，低优先级那块也不会缩成 0 看不见。
    SQUEEZE_FLOOR_FRAC = 0.4
    SQUEEZE_FLOOR_PX = 64.0



    _LEAF_OF = {"slice": "slice_holder", "trace": "trace_holder", "right": "right_holder"}










    # 换摆法时的过渡时长：窗口尺寸从旧值滑到新值（面板按伸缩因子等比例铺开）
    LAYOUT_ANIM_MS = 190




    # 窗口尺寸的"边框开销"：左右外边距 + body 手柄 + 顶栏 + 状态栏（估算兜底用；
    # 实测拿得到时优先用实测值，见 _fit_window_to_layout）。
    CHROME_W = 34
    CHROME_H = 105



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
        if (getattr(self, "right_holder", None) is None
                or self._layout_animating() or self._left_animating):
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









    # ============================================================== 拖动统一手势
    # 一个手势、三种结果，全部由"松手的位置"决定，不再需要任何小按钮：
    #   · 落在另一块剖面面板内 → **交换剖面顺序**（顺序决定叠加波形/单道波形的配色）
    #   · 落在主窗口之外       → **拉出为极简独立窗口**，落点就是新窗口的位置
    #   · 其它                 → 取消，面板回到原位
    # 已经在独立窗口里的面板再拖，就是搬动那个窗口；拖回主窗口松手即收回。
    # 唯一提示是标题行最左边的 6 点抓手。
    _DRAG_SLOP = 6                       # 小于这个位移算点击，不启动拖动





    # 浮窗最小尺寸：只是"退化尺寸"的兜底（正常情况一律等大搬出去，不做任何缩放）
    MIN_FLOAT = (160, 120)

    # ---------------------------------------------------------------- 开始 / 移动























    # ---------------------------------------------------------------- 松手




    # ---------------------------------------------------------------- 拉出



    # ---------------------------------------------------------------- 换序



    # 拖动时贴着某块剖面面板左右边缘各留一条"感应带"：进感应带 = 插到这个位置，
    # 进面板主体 = 交换。两种意图各有各的提示，所以窗内**不需要**"离原位多远算
    # 拉出"这种距离阈值 —— 窗内只会插入/交换，只有拖到窗口外才是拉出。
    DROP_ZONE = 26






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
        self._view3d_placeholder = QtWidgets.QLabel("正在加载三维视图…")
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
        self.btn_reset.setToolTip("复位三维视角")
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
                self._view3d_placeholder.setText("三维视图不可用。")
                self._view3d_placeholder.setVisible(True)
                self.status.setText("三维视图不可用。")
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



    # ------------------------------------------------- 面板显隐（左栏 + 三维）





    def _build_statusbar(self) -> QtWidgets.QFrame:
        bar, lay = make_panel()
        lay.setContentsMargins(12, 6, 12, 6)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.status = QtWidgets.QLabel("就绪")
        self.status.setObjectName("Status")
        row.addWidget(self.status)
        row.addStretch(1)
        self.stats_label = ValueLabel("")
        row.addWidget(self.stats_label)
        lay.addLayout(row)
        return bar

    # ============================================================ 布局引擎（转发）
    def _shown_list(self, *args, **kwargs):
        return self.layout_engine._shown_list(*args, **kwargs)

    def _layout_vis(self, *args, **kwargs):
        return self.layout_engine._layout_vis(*args, **kwargs)

    def _layout_key(self, *args, **kwargs):
        return self.layout_engine._layout_key(*args, **kwargs)

    def _builtin_order_for(self, *args, **kwargs):
        return self.layout_engine._builtin_order_for(*args, **kwargs)

    def _thumb_order(self, *args, **kwargs):
        return self.layout_engine._thumb_order(*args, **kwargs)

    def _free_pair(self, *args, **kwargs):
        return self.layout_engine._free_pair(*args, **kwargs)

    def _star_keys(self, *args, **kwargs):
        return self.layout_engine._star_keys(*args, **kwargs)

    def _is_builtin_default(self, *args, **kwargs):
        return self.layout_engine._is_builtin_default(*args, **kwargs)

    def _sync_pair_order(self, *args, **kwargs):
        return self.layout_engine._sync_pair_order(*args, **kwargs)

    def _align_pair_order(self, *args, **kwargs):
        return self.layout_engine._align_pair_order(*args, **kwargs)

    def _slots(self, *args, **kwargs):
        return self.layout_engine._slots(*args, **kwargs)

    def _build_work_tree(self, *args, **kwargs):
        return self.layout_engine._build_work_tree(*args, **kwargs)

    def _apply_layout(self, *args, **kwargs):
        return self.layout_engine._apply_layout(*args, **kwargs)

    def _sync_layout_for_count(self, *args, **kwargs):
        return self.layout_engine._sync_layout_for_count(*args, **kwargs)

    def _reclaim(self, *args, **kwargs):
        return self.layout_engine._reclaim(*args, **kwargs)

    def reset_panel_layout(self, *args, **kwargs):
        return self.layout_engine.reset_panel_layout(*args, **kwargs)

    def _reclaim_stray_panels(self, *args, **kwargs):
        return self.layout_engine._reclaim_stray_panels(*args, **kwargs)

    def _sync_panel_chips(self, *args, **kwargs):
        return self.layout_engine._sync_panel_chips(*args, **kwargs)

    def _available_panels(self, *args, **kwargs):
        return self.layout_engine._available_panels(*args, **kwargs)

    def _sync_reset_entry(self, *args, **kwargs):
        return self.layout_engine._sync_reset_entry(*args, **kwargs)

    def layout_default_groups(self, *args, **kwargs):
        return self.layout_engine.layout_default_groups(*args, **kwargs)

    def apply_layout_defaults(self, *args, **kwargs):
        return self.layout_engine.apply_layout_defaults(*args, **kwargs)

    def _capsule_tip(self, *args, **kwargs):
        return self.layout_engine._capsule_tip(*args, **kwargs)

    def _toggle_content(self, *args, **kwargs):
        return self.layout_engine._toggle_content(*args, **kwargs)

    def _focus_panel(self, *args, **kwargs):
        return self.layout_engine._focus_panel(*args, **kwargs)

    def _cycle_panel(self, *args, **kwargs):
        return self.layout_engine._cycle_panel(*args, **kwargs)

    def _solo(self, *args, **kwargs):
        return self.layout_engine._solo(*args, **kwargs)

    def _on_restore_builtin_defaults(self, *args, **kwargs):
        return self.layout_engine._on_restore_builtin_defaults(*args, **kwargs)

    def _relayout_content(self, *args, **kwargs):
        return self.layout_engine._relayout_content(*args, **kwargs)

    def _panel_metrics(self, *args, **kwargs):
        return self.layout_engine._panel_metrics(*args, **kwargs)

    def _distribute(self, *args, **kwargs):
        return self.layout_engine._distribute(*args, **kwargs)

    def _compute_targets(self, *args, **kwargs):
        return self.layout_engine._compute_targets(*args, **kwargs)

    def _prio_of(self, *args, **kwargs):
        return self.layout_engine._prio_of(*args, **kwargs)

    def _squeeze_floor(self, *args, **kwargs):
        return self.layout_engine._squeeze_floor(*args, **kwargs)

    def _extent_along(self, *args, **kwargs):
        return self.layout_engine._extent_along(*args, **kwargs)

    def _min_along(self, *args, **kwargs):
        return self.layout_engine._min_along(*args, **kwargs)

    def _natural_along(self, *args, **kwargs):
        return self.layout_engine._natural_along(*args, **kwargs)

    def _relax_content_min(self, *args, **kwargs):
        return self.layout_engine._relax_content_min(*args, **kwargs)

    def _hold_content_min(self, *args, **kwargs):
        return self.layout_engine._hold_content_min(*args, **kwargs)

    def _fit_window_to_layout(self, *args, **kwargs):
        return self.layout_engine._fit_window_to_layout(*args, **kwargs)

    def _is_dragging_active(self, *args, **kwargs):
        return self.layout_engine._is_dragging_active(*args, **kwargs)

    def _animate_layout_change(self, *args, **kwargs):
        return self.layout_engine._animate_layout_change(*args, **kwargs)

    def _stop_layout_anim(self, *args, **kwargs):
        return self.layout_engine._stop_layout_anim(*args, **kwargs)

    def _window_anim_running(self, *args, **kwargs):
        return self.layout_engine._window_anim_running(*args, **kwargs)

    def _size_changed_enough(self, *args, **kwargs):
        return self.layout_engine._size_changed_enough(*args, **kwargs)

    def _layout_animating(self, *args, **kwargs):
        return self.layout_engine._layout_animating(*args, **kwargs)

    def _set_split_stretch(self, *args, **kwargs):
        return self.layout_engine._set_split_stretch(*args, **kwargs)

    def _total(self, *args, **kwargs):
        return self.layout_engine._total(*args, **kwargs)

    def _apply_sizes(self, *args, **kwargs):
        return self.layout_engine._apply_sizes(*args, **kwargs)

    def _stop_all_size_anims(self, *args, **kwargs):
        return self.layout_engine._stop_all_size_anims(*args, **kwargs)

    def _stop_size_anim(self, *args, **kwargs):
        return self.layout_engine._stop_size_anim(*args, **kwargs)

    def _rebuild_slice_panels(self, *args, **kwargs):
        return self.layout_engine._rebuild_slice_panels(*args, **kwargs)

    def _sync_empty_hint(self, *args, **kwargs):
        return self.layout_engine._sync_empty_hint(*args, **kwargs)

    def _top_right_owner(self, *args, **kwargs):
        return self.layout_engine._top_right_owner(*args, **kwargs)

    def _sync_header_pads(self, *args, **kwargs):
        return self.layout_engine._sync_header_pads(*args, **kwargs)

    def _effective_shown(self, *args, **kwargs):
        return self.layout_engine._effective_shown(*args, **kwargs)

    def _freeze_content_width(self, *args, **kwargs):
        return self.layout_engine._freeze_content_width(*args, **kwargs)

    # ============================================================ 拖动/浮窗（转发）
    def _is_detached(self, *args, **kwargs):
        return self.docking._is_detached(*args, **kwargs)

    def _watch_drag(self, *args, **kwargs):
        return self.docking._watch_drag(*args, **kwargs)

    def _toggle_float_maximized(self, *args, **kwargs):
        return self.docking._toggle_float_maximized(*args, **kwargs)

    def _drag_kind(self, *args, **kwargs):
        return self.docking._drag_kind(*args, **kwargs)

    def _begin_drag(self, *args, **kwargs):
        return self.docking._begin_drag(*args, **kwargs)

    def _move_drag(self, *args, **kwargs):
        return self.docking._move_drag(*args, **kwargs)

    def _update_drop_hint(self, *args, **kwargs):
        return self.docking._update_drop_hint(*args, **kwargs)

    def _drag_is_reorder(self, *args, **kwargs):
        return self.docking._drag_is_reorder(*args, **kwargs)

    def _enter_drag_layout(self, *args, **kwargs):
        return self.docking._enter_drag_layout(*args, **kwargs)

    def _clear_drag_layout(self, *args, **kwargs):
        return self.docking._clear_drag_layout(*args, **kwargs)

    def _apply_drag_preview(self, *args, **kwargs):
        return self.docking._apply_drag_preview(*args, **kwargs)

    def _squeeze_drag_preview(self, *args, **kwargs):
        return self.docking._squeeze_drag_preview(*args, **kwargs)

    def _child_visible(self, *args, **kwargs):
        return self.docking._child_visible(*args, **kwargs)

    def _splitter_span(self, *args, **kwargs):
        return self.docking._splitter_span(*args, **kwargs)

    def _hold_sizes(self, *args, **kwargs):
        return self.docking._hold_sizes(*args, **kwargs)

    def _leaf_widgets(self, *args, **kwargs):
        return self.docking._leaf_widgets(*args, **kwargs)

    def _key_of_widget(self, *args, **kwargs):
        return self.docking._key_of_widget(*args, **kwargs)

    def _preview_rect_for_drag(self, *args, **kwargs):
        return self.docking._preview_rect_for_drag(*args, **kwargs)

    def _drop_intent_at(self, *args, **kwargs):
        return self.docking._drop_intent_at(*args, **kwargs)

    def _visible_excluding(self, *args, **kwargs):
        return self.docking._visible_excluding(*args, **kwargs)

    def _region_above(self, *args, **kwargs):
        return self.docking._region_above(*args, **kwargs)

    def _zone_spec(self, *args, **kwargs):
        return self.docking._zone_spec(*args, **kwargs)

    def _zone_side_at(self, *args, **kwargs):
        return self.docking._zone_side_at(*args, **kwargs)

    def _layout_anim_running(self, *args, **kwargs):
        return self.docking._layout_anim_running(*args, **kwargs)

    def _drop_target(self, *args, **kwargs):
        return self.docking._drop_target(*args, **kwargs)

    def _open_drag_layer(self, *args, **kwargs):
        return self.docking._open_drag_layer(*args, **kwargs)

    def _panel_snapshot(self, *args, **kwargs):
        return self.docking._panel_snapshot(*args, **kwargs)

    def _finish_drag(self, *args, **kwargs):
        return self.docking._finish_drag(*args, **kwargs)

    def _apply_intent(self, *args, **kwargs):
        return self.docking._apply_intent(*args, **kwargs)

    def _discard_drag_layer(self, *args, **kwargs):
        return self.docking._discard_drag_layer(*args, **kwargs)

    def _inside_main_window(self, *args, **kwargs):
        return self.docking._inside_main_window(*args, **kwargs)

    def _tear_off(self, *args, **kwargs):
        return self.docking._tear_off(*args, **kwargs)

    def _close_detached(self, *args, **kwargs):
        return self.docking._close_detached(*args, **kwargs)

    def _restore_detached(self, *args, **kwargs):
        return self.docking._restore_detached(*args, **kwargs)

    def _swap_panel_order(self, *args, **kwargs):
        return self.docking._swap_panel_order(*args, **kwargs)

    def _move_panel_near(self, *args, **kwargs):
        return self.docking._move_panel_near(*args, **kwargs)

    def _after_order_change(self, *args, **kwargs):
        return self.docking._after_order_change(*args, **kwargs)

    def _panel_at(self, *args, **kwargs):
        return self.docking._panel_at(*args, **kwargs)

    def _drop_zone_at(self, *args, **kwargs):
        return self.docking._drop_zone_at(*args, **kwargs)

    def _highlight_panel(self, *args, **kwargs):
        return self.docking._highlight_panel(*args, **kwargs)

    def _sync_holder_widths(self, *args, **kwargs):
        return self.docking._sync_holder_widths(*args, **kwargs)

    def eventFilter(self, obj, ev) -> bool:            # noqa: N802 （Qt 接口名）
        return self.docking.event_filter(obj, ev)

    # ============================================================ 侧栏/主题（转发）
    def _sync_left_min_width(self, *args, **kwargs):
        return self.sidebar._sync_left_min_width(*args, **kwargs)

    def _sync_left_empty_hint(self, *args, **kwargs):
        return self.sidebar._sync_left_empty_hint(*args, **kwargs)

    def open_preferences(self, *args, **kwargs):
        return self.sidebar.open_preferences(*args, **kwargs)

    def _build_rail(self, *args, **kwargs):
        return self.sidebar._build_rail(*args, **kwargs)

    def _rail_separator(self, *args, **kwargs):
        return self.sidebar._rail_separator(*args, **kwargs)

    def _rail_button(self, *args, **kwargs):
        return self.sidebar._rail_button(*args, **kwargs)

    def _sync_rail(self, *args, **kwargs):
        return self.sidebar._sync_rail(*args, **kwargs)

    def _goto_group(self, *args, **kwargs):
        return self.sidebar._goto_group(*args, **kwargs)

    def _schedule_scroll_to_card(self, *args, **kwargs):
        return self.sidebar._schedule_scroll_to_card(*args, **kwargs)

    def _clear_active_group(self, *args, **kwargs):
        return self.sidebar._clear_active_group(*args, **kwargs)

    def _scroll_to_card(self, *args, **kwargs):
        return self.sidebar._scroll_to_card(*args, **kwargs)

    def _toggle_all_groups(self, *args, **kwargs):
        return self.sidebar._toggle_all_groups(*args, **kwargs)

    def _set_all_groups(self, *args, **kwargs):
        return self.sidebar._set_all_groups(*args, **kwargs)

    def _after_group_change(self, *args, **kwargs):
        return self.sidebar._after_group_change(*args, **kwargs)

    def _on_group_toggled(self, *args, **kwargs):
        return self.sidebar._on_group_toggled(*args, **kwargs)

    def _update_group_summaries(self, *args, **kwargs):
        return self.sidebar._update_group_summaries(*args, **kwargs)

    def _load_ui_state(self, *args, **kwargs):
        return self.sidebar._load_ui_state(*args, **kwargs)

    def _reset_layout_defaults(self, *args, **kwargs):
        return self.sidebar._reset_layout_defaults(*args, **kwargs)

    def _parse_pair_order(self, *args, **kwargs):
        return self.sidebar._parse_pair_order(*args, **kwargs)

    def _save_ui_state(self, *args, **kwargs):
        return self.sidebar._save_ui_state(*args, **kwargs)

    def apply_theme_key(self, *args, **kwargs):
        return self.sidebar.apply_theme_key(*args, **kwargs)

    def _sync_color_scheme_hook(self, *args, **kwargs):
        return self.sidebar._sync_color_scheme_hook(*args, **kwargs)

    def _on_system_scheme_changed(self, *args, **kwargs):
        return self.sidebar._on_system_scheme_changed(*args, **kwargs)

    def _refresh_theme_widgets(self, *args, **kwargs):
        return self.sidebar._refresh_theme_widgets(*args, **kwargs)

    def _set_region_visible(self, *args, **kwargs):
        return self.sidebar._set_region_visible(*args, **kwargs)

    def _pin_left_rail(self, *args, **kwargs):
        return self.sidebar._pin_left_rail(*args, **kwargs)

    def _pin_left_open(self, *args, **kwargs):
        return self.sidebar._pin_left_open(*args, **kwargs)

    # ============================================================ 设置卡片（转发）
    def _fill_data_card(self, *args, **kwargs):
        return self.settings_cards._fill_data_card(*args, **kwargs)

    def _spin(self, *args, **kwargs):
        return self.settings_cards._spin(*args, **kwargs)

    def _fill_compare_card(self, *args, **kwargs):
        return self.settings_cards._fill_compare_card(*args, **kwargs)

    def _fill_cut_card(self, *args, **kwargs):
        return self.settings_cards._fill_cut_card(*args, **kwargs)

    def _fill_slice_card(self, *args, **kwargs):
        return self.settings_cards._fill_slice_card(*args, **kwargs)

    def _fill_playback_card(self, *args, **kwargs):
        return self.settings_cards._fill_playback_card(*args, **kwargs)

    def _fill_density_card(self, *args, **kwargs):
        return self.settings_cards._fill_density_card(*args, **kwargs)

    def _fill_wave_card(self, *args, **kwargs):
        return self.settings_cards._fill_wave_card(*args, **kwargs)

    def _fill_trace_card(self, *args, **kwargs):
        return self.settings_cards._fill_trace_card(*args, **kwargs)

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

    # ------------------------------------------------------------ 数据装配（转发）
    def add_compare_file(self) -> None:
        self.dataset_service.add_compare_file()

    def remove_dataset(self) -> None:
        self.dataset_service.remove_dataset()

    def _dir_hint(self) -> str:
        return self.dataset_service.dir_hint()

    def _open_source(self, path: str, reset: bool) -> bool:
        return self.dataset_service.open_source(path, reset)

    def _load_selected_variable(self) -> None:
        self.dataset_service.load_selected_variable()

    def load_variable(self, key: str, target: str | None = None) -> bool:
        return self.dataset_service.load_variable(key, target)

    def _show_variable_values(self, path: str, key: str) -> bool:
        return self.dataset_service.show_variable_values(path, key)

    def _build_variable_vol(self, path: str, key: str,
                            info=None) -> SeisVolume | None:
        return self.dataset_service.build_variable_vol(path, key, info)

    def load_sample(self) -> None:
        self.dataset_service.load_sample()

    def clear_data(self) -> None:
        """清空已载入的数据，把界面恢复成「刚打开」的样子。"""
        self.dataset_service.clear_data()

    @staticmethod
    def _default_mode(vol: SeisVolume) -> str:
        return DatasetService.default_mode(vol)

    def _install_primary(self, vol: SeisVolume, path: str, key: str) -> bool:
        return self.dataset_service.install_primary(vol, path, key)

    def _append_dataset(self, vol: SeisVolume, path: str, key: str) -> bool:
        return self.dataset_service.append_dataset(vol, path, key)

    def _replace_active(self, vol: SeisVolume, path: str, key: str) -> bool:
        return self.dataset_service.replace_active(vol, path, key)

    def _after_dataset_change(self, animate_layout: bool = True) -> None:
        self.dataset_service.after_dataset_change(animate_layout)

    def _default_view_for(self, vol: SeisVolume | None) -> None:
        self.dataset_service.default_view_for(vol)

    def _sync_dimensional_defaults(self) -> None:
        self.dataset_service.sync_dimensional_defaults()

    def _reset_ui_after_clear(self) -> None:
        """清空数据后的界面复位（数据状态已由 DatasetService 清掉）。"""
        # ---- 数据来源
        self.src_path = ""
        self.file_label.setText("尚未打开文件")
        self.table.fill([])
        self.btn_load.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.src_info.setText("—")

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
        for spin, val in ((self.spin_dt, 0.001), (self.spin_dx, 12.5), (self.spin_ds, 25.0)):
            spin.setValue(val)

        # ---- 切片 / 目标道
        self.mode_ctl.set_enabled_keys({"shot", "recv", "time"})
        self.mode_ctl.set_value("shot")
        self.slice_slider.title.setText(AXIS_TITLES["shot"])
        self.slice_slider.set_range(0, 0, 0)
        self.playhead.set_range(0, 0)
        self.slice_title.setText("剖面")
        self.slice_info.setText("当前：—")
        self.trace_info.setText("—")
        self.trace_view.clear()
        self._sync_trace_legend(force=True)

        # ---- 面板布局：只开剖面（与刚打开一致），构图回到默认
        self._content_shown = {"slice": True, "trace": False, "right": False}
        self._pair_order = list(pair_layout(("slice", "right"))[2])
        self._layout_preset = self._default3_key or "B"
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
        self.status.setText("已清空数据。")

    def _base_sample(self, k: int) -> np.ndarray:
        """第 k 份数据用于估计基准色标的代表样本（兼容代理）。"""
        return self.pipeline.base_sample(self.datasets[k].vol)

    def _recompute_base_clim(self, k: int) -> None:
        """重算第 k 份数据的基准色标。"""
        self.pipeline.recompute_base_clim(k, self.datasets[k].vol,
                                          self._display_settings())

    def _recommended_manual_halfwidth(self) -> float | None:
        """推荐的手动半宽（兼容代理）。"""
        return self.pipeline.recommended_manual_halfwidth(self.datasets)

    # ============================================================== 导出 / 转换
    def export_volume(self) -> None:
        """导出：整卷数据 / 逐剖面 / 当前剖面图片（转发到 ExportService）。"""
        self.export_service.open_dialog()

    def _run_export(self, dlg) -> None:
        self.export_service.run(dlg)

    def _export_slices(self, dlg, progress, cancel) -> list[str]:
        return self.export_service.export_slices(dlg, progress, cancel)

    @staticmethod
    def _figure_labels(mode: str) -> tuple[str, str, str]:
        return ExportService.figure_labels(mode)

    def _export_figures(self, dlg, progress, cancel=None) -> list[str]:
        return self.export_service.export_figures(dlg, progress, cancel)

    def _export_slice_figures(self, dlg, progress, cancel=None) -> list[str]:
        return self.export_service.export_slice_figures(dlg, progress, cancel)

    def _figure_wiggle_set(self, k: int, shared: float | None = None) -> tuple:
        return self.export_service.figure_wiggle_set(k, shared)

    def _export_wave_figure(self, dlg) -> str:
        return self.export_service.export_wave_figure(dlg)

    # ================================================================== 刷新
    def _display_settings(self) -> DisplaySettings:
        """读取当前控件值，生成一轮刷新/导出使用的显示参数快照。

        同一轮刷新内只取一次：后续的切片、AGC、色标、wiggle、导出全部使用这个
        快照，避免计算过程中反复访问控件导致前后不一致。
        """
        return DisplaySettings(
            cmap=self.cmap_combo.cmap(),
            clim_mode=self.clim_combo.currentData(),
            manual_halfwidth=float(self.spin_manual.value()),
            contrast=self._clim_scale,
            agc_on=self.chk_agc.isChecked(),
            agc_window=int(self.combo_agc.currentData() or 0),
            decimation=self.combo_dec.currentData() or None,
            wiggle_on=self.chk_wiggle.isChecked(),
            pure_waveform=self.chk_pure.isChecked(),
            wiggle_traces=int(self.spin_wig.value()),
            wiggle_gain=self.gain.value() / 100.0,
            normalize_traces=self.chk_norm.isChecked(),
        )

    def _refresh_all(self, sync_controls: bool = True) -> None:
        if not self.datasets:
            return
        settings = self._display_settings()
        # 色标缓存与数据份数对齐（载入 / 追加 / 移除之后都从这里归一）
        self.pipeline.ensure_clim_count(len(self.datasets))
        # 每轮刷新重算一次切片，供叠加/统计复用
        self.pipeline.invalidate_slices()
        for k in range(len(self.datasets)):
            self._refresh_panel(k)
        # 共享色标：所有面板都用同一套窗口
        shared = self.pipeline.scale_window(
            self.pipeline.shared_base_clim(self.datasets, settings), settings)
        self.pipeline.set_shared_clim(shared, self.active)
        self._refresh_faces()
        self._refresh_trace()
        self._update_slice_info()
        if sync_controls:
            self._sync_controls()
        else:
            self.playhead.set_position(self.pos[self.mode])
        self._update_status()
        self._update_group_summaries()

    def _refresh_clim(self) -> None:
        """只按新对比度重画色标，不重算切片 / AGC。

        对比度只改 ``_clim_scale``（半窗宽倍数），切片数组与基准色标都不变 ——
        拖动滑杆时复用 ``_raw_cache`` / ``_shared_base_cache``，只重做上色和三维贴图，
        避免每移一格都跑一遍 ``display_face`` 导致卡顿。
        """
        if not self.datasets:
            return
        settings = self._display_settings()
        self.pipeline.invalidate_color()
        for k in range(len(self.datasets)):
            self._refresh_panel(k)
        shared = self.pipeline.scale_window(
            self.pipeline.shared_base_clim(self.datasets, settings), settings)
        self.pipeline.set_shared_clim(shared, self.active)
        # 三维没显示时不碰 GL 控件，等它重新显示时会按新色标刷新
        if self.view3d is not None and self._content_shown.get("right"):
            self._refresh_faces()

    def _refresh_panel(self, k: int) -> None:
        """画第 k 份数据的剖面；对比时三块共用同一套色标窗口。"""
        ds = self.datasets[k]
        settings = self._display_settings()
        img, clim = self.pipeline.panel_image(k, self.datasets, settings)
        pure = settings.pure_waveform
        wig_on = settings.wiggle_on or pure
        screen_styles = view2d.screen_line_styles(len(self.datasets))

        sets = None
        if wig_on:
            sets = [self.pipeline.wiggle_set(
                k, self.datasets, settings, screen_styles)]

        xlabel, ylabel, suffix = ds.vol.axis_labels_of(ds.mode, ds.pos[ds.mode])
        self.panels[k].view.set_slice(
            img, ds.vol.extent_of(ds.mode), settings.cmap, clim,
            xlabel, ylabel,
            full_shape=img.shape,
            wiggle=settings.wiggle_traces if wig_on else 0,
            gain=settings.wiggle_gain,
            wiggle_sets=sets, show_image=not pure)
        # 对比面板的小标题带识别色 + 同色小图例，一眼看出这块是哪份数据、
        # 屏上它的曲线是什么颜色（导出用另一套线型，见「导出线型」分组）
        title_rgb = tuple(QtGui.QColor(
            screen_styles[k % len(screen_styles)][0]).getRgb())
        self.panels[k].set_title(
            f"{ds.vol.name}　{suffix}", title_rgb,
            show=len(self.datasets) > 1,
            line_style=screen_styles[k % len(screen_styles)])
        # 单数据时组内只有一幅：换序抓手隐藏，整块移动统一用上方「剖面」组把手
        self.panels[k].set_reorder_affordance(len(self.datasets) > 1)
        # 记下这一片实际用的色标：导出"论文用图"时要和屏幕上一致
        self.pipeline.set_panel_clim(k, clim, self.active)
        if k == self.active:
            self.pipeline.set_stats(img)
        self._update_reference_panel(k)

    def _agc_window(self, mode: str) -> int | None:
        """当前设置下这一面该用的 AGC 窗口（兼容代理）。"""
        return self.pipeline.agc_window(mode, self._display_settings())

    def _processed_image(self, k: int, full: bool = False):
        """第 k 份数据当前切片 → ``(抽稀/AGC 后的二维数组, 是否施加了 AGC)``。

        统一走 ``DisplayPipeline``；这里只是为现有调用点保留的兼容代理。
        """
        return self.pipeline.processed_image(
            k, self.datasets, self._display_settings(), full)

    def _shared_base_clim(self) -> tuple[float, float]:
        """对比模式下三块面板共用的基准色标窗口（兼容代理）。"""
        return self.pipeline.shared_base_clim(
            self.datasets, self._display_settings())

    def _scale_window(self, base: tuple[float, float]) -> tuple[float, float]:
        """把基准窗口按对比度围绕中点对称缩放（兼容代理）。"""
        return self.pipeline.scale_window(base, self._display_settings())

    def _panel_image(self, k: int, full: bool = False):
        """第 k 份数据当前切片 → ``(显示用数组, 全体共享的色标窗口)``（兼容代理）。"""
        return self.pipeline.panel_image(
            k, self.datasets, self._display_settings(), full)

    def _clim_for_face(self, mode: str) -> tuple[float, float]:
        """三维里非当前两个面的色标（兼容代理）。"""
        return self.pipeline.clim_for_face(
            self.datasets, mode, self._display_settings(), self.active, self.mode)

    def _wiggle_set(self, k: int, shared: float | None = None) -> tuple:
        """第 k 份数据在剖面上叠加用的 wiggle 数据组（兼容代理）。"""
        return self.pipeline.wiggle_set(
            k, self.datasets, self._display_settings(),
            view2d.screen_line_styles(len(self.datasets)), shared)

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
        settings = self._display_settings()
        limit = settings.decimation
        faces: dict[str, tuple[np.ndarray, tuple[float, float]]] = {}
        for mode in ("shot", "recv", "time"):
            if mode == ds.mode:
                # **直接复用**二维面板这一轮的数组与色标：max|diff| 必须为 0
                img, clim = self.pipeline.panel_image(
                    self.active, self.datasets, settings)
            else:
                img = display_face(ds.vol, mode, ds.pos[mode],
                                   max_side=limit,
                                   agc_window=settings.agc_window_for(mode))
                clim = self.pipeline.clim_for_face(
                    self.datasets, mode, settings, self.active, ds.mode)
            faces[mode] = (img, clim)
        self.view3d.update_faces(self.pos["shot"], self.pos["recv"], self.pos["time"],
                                 faces, settings.cmap)
        self._update_face_info()

    def _traces(self) -> tuple[list, list, tuple[int, int]]:
        """每个数据源一条道：返回 ``(叠加曲线, 各道峰值, 当前数据的 (S, R))``。"""
        # 屏上按"数据识别色"上色；导出的白底论文图另走 line_styles（见 _export_*）
        screen_styles = view2d.screen_line_styles(len(self.datasets))
        labels = [self._dataset_label(k) for k in range(len(self.datasets))]
        return self.pipeline.traces(
            self.datasets, self.active, self._display_settings(),
            screen_styles, labels)

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

    def _update_slice_info(self) -> None:
        """在设置面板里显示当前剖面序号与目标道号（导出图里不再画这些字）。"""
        if not hasattr(self, "slice_info"):
            return
        if not self.datasets:
            self.slice_info.setText("当前：—")
            return
        ds = self.datasets[max(0, min(self.active, len(self.datasets) - 1))]
        name = {"shot": "炮点 S", "recv": "检波点 R", "time": "时间 T"}[ds.mode]
        self.slice_info.setText(
            f"当前：{name} = {ds.pos[ds.mode]}　"
            f"目标道 S = {ds.pos['shot']}  R = {ds.pos['recv']}")

    def _sync_controls(self) -> None:
        """让左侧各控件与**当前数据**的状态对齐（全部屏蔽信号，避免循环触发）。"""
        self._update_slice_info()
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
        self.compare_info.setText(
            f"已载入 {n} / {MAX_DATASETS} 份同形状数据。" if n else "未载入数据。")

    def _update_status(self) -> None:
        if not self.datasets:
            self.status.setText("就绪")
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
            self.face_info.setToolTip("")
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
            f"时间切片  T={t}  ({t * vol.dt:.3f} s)")

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
            self.status.setText("剖面参数已同步。")
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
        mode = self.clim_combo.currentData()
        # 首次切到「手动」且还没填过值时，用 P98(|振幅|) 给一个推荐起点；
        # 之后用户改过的值不再覆盖。
        if (mode == "manual" and self.datasets
                and getattr(self, "_clim_mode_prev", None) != "manual"
                and abs(float(self.spin_manual.value()) - 1.0) <= 1e-12):
            value = self._recommended_manual_halfwidth()
            if value is not None:
                self.spin_manual.blockSignals(True)
                self.spin_manual.setValue(value)
                self.spin_manual.blockSignals(False)
                self.status.setText(f"手动半宽：{value:.6g}")
        self._clim_mode_prev = mode
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
            # 连续拖动时只保留最后一次：16ms 合并一次重绘，松手再补最终帧
            self._clim_timer.start()

    def _flush_contrast(self, _value: int | None = None) -> None:
        """滑杆松手 / 输入框提交：立刻补上最后一次对比度变化。"""
        if self._clim_timer.isActive():
            self._clim_timer.stop()
        self._apply_contrast()

    def _apply_contrast(self) -> None:
        if self.datasets:
            self._refresh_clim()

    @staticmethod
    def _target_axis_for(mode: str) -> str | None:
        """当前切片下，绿线可移动的那一根轴。时间切片不提供选道。"""
        if mode == "shot":
            return "recv"
        if mode == "recv":
            return "shot"
        return None

    def _apply_target_index(self, slot: int, axis: str | None, value: int) -> None:
        """把某个数据源的目标道切到 ``value``；同步打开时广播到全部数据源。"""
        if axis is None or not (0 <= slot < len(self.datasets)):
            return
        self.active = slot
        limit = {"shot": "ns", "recv": "nr", "time": "nt"}[axis]
        for k, ds in enumerate(self.datasets):
            if k != slot and not self.chk_sync.isChecked():
                continue
            ds.pos[axis] = int(np.clip(value, 0, getattr(ds.vol, limit) - 1))
        # 只换目标道：单道波形与绿线更新，剖面图本身不动。
        self._refresh_trace()
        self._update_references()
        self._update_slice_info()
        self._update_status()
        # 三维里另一根轴上的切片要跟着走；时间切片位置不变。
        if self._content_shown.get("right"):
            self._face_timer.start(20)

    def _on_reference_drag(self, slot: int, col: int) -> None:
        """拖动绿线：``col`` 是视图映射回原始网格的横向列号。"""
        if not self.datasets or not (0 <= slot < len(self.datasets)):
            return
        axis = self._target_axis_for(self.datasets[slot].mode)
        self._apply_target_index(slot, axis, int(col))

    def _on_trace_step(self, slot: int, delta: int) -> None:
        """聚焦剖面时 ←/→：目标道单步移动。"""
        if not self.datasets or not (0 <= slot < len(self.datasets)):
            return
        ds = self.datasets[slot]
        axis = self._target_axis_for(ds.mode)
        if axis is None:
            return
        self._apply_target_index(slot, axis, int(ds.pos.get(axis, 0)) + int(delta))

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
            self.status.setText("已停止扫掠播放。")
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
            infos = self.dataset_service.list_variables(path)
        except LoadError as exc:
            self._error("无法读取文件", str(exc))
            return False
        except Exception as exc:                        # pragma: no cover
            self._error("无法读取文件", f"{type(exc).__name__}: {exc}")
            return False
        if not infos:
            self._error("没有可用变量", f"{Path(path).name} 里没有可载入的变量。")
            return False

        snap = self.dataset_service._source_snapshot()
        p = Path(path)
        self.src_path = path
        self.file_label.setText(f"{p.parent}  ▸  {p.name}")
        self.table.fill(infos)
        self.btn_load.setEnabled(True)
        self.src_info.setText(f"共 {len(infos)} 个可用变量。")
        info = infos[0]
        if len(info.shape) <= 1:
            vol = self.dataset_service.build_trace_vol(path, info.key, info)
        else:
            vol = self._build_variable_vol(path, info.key, info)
        if vol is None:
            self.dataset_service._restore_source(snap)
            return False
        if not self.datasets:
            # 没有数据：直接载入，不弹意图框
            ok = self._install_primary(vol, path, info.key)
            if not ok:
                self.dataset_service._restore_source(snap)
            return ok

        intent = self._ask_import_intent(vol, path, first=first)
        if intent == "compare":
            ok = self._append_dataset(vol, path, info.key)
            if not ok:
                self.dataset_service._restore_source(snap)
            return ok
        if intent == "replace":
            ok = self._apply_replace(vol, path, info.key)
            if not ok:
                self.dataset_service._restore_source(snap)
            return ok
        self.status.setText("已取消导入。")
        self.dataset_service._restore_source(snap)
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
            self.status.setText("已追加为对比数据。")
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