"""左侧设置栏：图标轨道、分组展开、轨道导航、UI 状态持久化与主题切换。"""

from __future__ import annotations

import os
import time

from PySide6 import QtCore, QtGui, QtWidgets

from . import icons, style
from .dataset_service import MAX_DATASETS
from .layout_config import KEY_PAIR, PANEL_ORDER
from .volume import SLICE_LABELS
from .widgets import (AppearanceDialog, FoldCard, PreferencesDialog,
                      SegmentedControl, SplitDefaultsDialog, THREE_KEYS)

_PERSIST_UI = not os.environ.get("SEISVIEW_NO_PERSIST")


class SidebarController:
    """把左栏的显隐、分组状态、偏好设置与主题重刷从主窗口拆出来。"""

    def __init__(self, host) -> None:
        self.host = host
        self._jump_guard_until = 0.0
        self._jump_token = 0
        self._left_anim = None

    def _sync_left_min_width(self) -> None:
        """把左栏的宽度下限钉成"内容真正需要的宽度"。

        侧边栏里好几行是并排控件（下拉框 + 数字框 + 色块），合起来最宽的那张卡片
        决定内容需要多宽。原先下限写死 300 —— 比内容窄，里层滚动区就被撑宽，
        于是底下凭空多出一条横向滚动条，而且**刚打开、还没有任何数据时就有**。
        这里按卡片实测宽度算：既不长出横条，也不裁切任何一行。
        """
        widest = max((c.minimumSizeHint().width() for c in self.host.cards.values()),
                     default=0)
        self.host._left_min_w = max(self.host.LEFT_MIN_W, widest + self.host.LEFT_CHROME_W)
        self.host.left_wrap.setMinimumWidth(self.host._left_min_w)
        # 上限也要跟着让路：否则内容比上限还宽时，minimum>maximum 会互相打架
        self.host.left_wrap.setMaximumWidth(max(self.host.LEFT_MAX_W, self.host._left_min_w))

    def _sync_left_empty_hint(self) -> None:
        """按 ``_rail_keys`` 决定哪些分组卡片在左栏里出现；一组都没有 → 显示引导文案。"""
        if not hasattr(self.host, "left_empty_hint"):
            return
        for key, card in self.host.cards.items():
            card.setVisible(key in self.host._rail_keys)
        self.host.left_empty_hint.setVisible(not self.host._rail_keys)

    def open_preferences(self) -> None:
        """齿轮：打开「窗口设置」。外观与默认分屏在各自的子窗口里设置。"""
        keys_before = list(self.host._rail_keys)
        follow_before = self.host._follow_layout
        dlg = PreferencesDialog(
            self.host.GROUP_ORDER, self.host.GROUP_TITLES,
            keys_before, follow_layout=follow_before, parent=self.host)
        dlg.appearanceRequested.connect(self.open_appearance)
        dlg.splitDefaultsRequested.connect(self.open_split_defaults)
        accepted = dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
        keys = dlg.selected_keys() if accepted else keys_before
        follow = dlg.follow_layout() if accepted else follow_before

        # 去掉已不在轨道里的组的"当前高亮组"，免得高亮留在一个看不见的图标上
        if self.host._active_group not in keys:
            self.host._active_group = None
        self.host._rail_keys = keys
        self.host._sync_left_empty_hint()
        self.host._sync_rail()

        if follow != follow_before:
            self.host._follow_layout = follow
            self.host._save_ui_state()
            if follow:
                self.host._relayout_content(animate=False)   # 立刻按当前排版重算一次窗口
            self.host.status.setText(
                "窗口大小已设为" + ("跟随排版。" if follow else "仅放大。"))
        elif keys != keys_before:
            self.host.status.setText("窗口设置已更新。")

    def open_appearance(self) -> None:
        """「外观」子窗口：边选边预览，取消恢复，确定后持久化。"""
        before = self.host._theme_key
        dlg = AppearanceDialog(
            before,
            on_preview=lambda k: self.host.apply_theme_key(
                k, persist=False, announce=False),
            parent=self.host)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.host.apply_theme_key(dlg.theme_key(), persist=True, announce=True)

    def open_split_defaults(self) -> None:
        """「默认分屏设置」子窗口：确定后保存；恢复按钮清掉自定义默认。"""
        dlg = SplitDefaultsDialog(self.host.layout_default_groups(),
                                  parent=self.host)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        if dlg.restored():
            self.host._on_restore_builtin_defaults()
        else:
            self.host.apply_layout_defaults(dlg.choices())

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
        rail.setFixedWidth(self.host.LEFT_RAIL_W)
        v = QtWidgets.QVBoxLayout(rail)
        v.setContentsMargins(5, 8, 5, 8)
        v.setSpacing(4)

        self.host.btn_left_dock = self.host._rail_button(28, 28, 22)
        self.host.btn_left_dock.clicked.connect(
            lambda: self.host._set_region_visible("left", not self.host._region_shown["left"]))
        v.addWidget(self.host.btn_left_dock, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        self.host._rail_sep_top = self.host._rail_separator()
        v.addWidget(self.host._rail_sep_top)

        self.host.rail_btns: dict[str, QtWidgets.QToolButton] = {}
        for key in self.host.GROUP_ORDER:
            btn = self.host._rail_button(28, 26, 18)
            btn.setCheckable(True)
            btn.setToolTip(self.host.GROUP_TITLES[key])
            btn.clicked.connect(lambda _c=False, k=key: self.host._goto_group(k))
            v.addWidget(btn, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.host.rail_btns[key] = btn

        # ⇕ 紧跟在分组图标下面，之间用一条细分隔线把"分组导航 / 全局动作"分开
        v.addWidget(self.host._rail_separator())

        self.host.btn_left_all = self.host._rail_button(28, 26, 18)
        self.host.btn_left_all.clicked.connect(self.host._toggle_all_groups)
        v.addWidget(self.host.btn_left_all, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)

        # 齿轮：窗口设置（管哪些组出现在侧边栏、外观等）。放在 ⇕ 下面。
        self.host.btn_prefs = self.host._rail_button(28, 26, 18)
        self.host.btn_prefs.setIcon(QtGui.QIcon(icons.gear(18, style.TEXT_DIM)))
        self.host.btn_prefs.setToolTip("窗口设置")
        self.host.btn_prefs.clicked.connect(self.host.open_preferences)
        v.addWidget(self.host.btn_prefs, 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
        v.addStretch(1)
        self.host.rail = rail
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

    def _sync_rail(self) -> None:
        """轨道图标跟着当前状态换形换色。

        分组图标**只代表"跳到某一组"**，不代表显隐 —— 所以它们不随分组收放变色，
        只在"刚跳过去"的那一刻点亮一下（``_active_group``）。是否显示由
        ``_rail_keys`` 决定（齿轮里勾了谁就有谁）。
        """
        shown = self.host._region_shown.get("left", True)
        self.host.btn_left_dock.setIcon(QtGui.QIcon(icons.dock(
            22, style.TEXT_DIM if shown else style.TEXT_MUTE, style.ACCENT,
            expanded=shown, side="left")))
        self.host.btn_left_dock.setToolTip("收起设置面板" if shown else "展开设置面板")

        for key, btn in self.host.rail_btns.items():
            btn.setVisible(key in self.host._rail_keys)
            on = key == self.host._active_group
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
            btn.setIcon(QtGui.QIcon(icons.group(
                key, 18, style.ON_ACCENT if on else style.TEXT_MUTE)))
        self.host._rail_sep_top.setVisible(bool(self.host._rail_keys))

        # ⇕ 只管"已加入的那些组"：只要有一组开着，点击就是"全部收起"
        joined = self.host._rail_keys
        any_on = bool(joined) and any(self.host.cards[k].is_expanded() for k in joined)
        self.host.btn_left_all.setIcon(QtGui.QIcon(icons.collapse_all(18, style.TEXT_DIM)))
        self.host.btn_left_all.setToolTip(
            "没有已加入的设置项" if not joined else ("全部收起" if any_on else "全部展开"))

    def _goto_group(self, key: str) -> None:
        """轨道上的分组图标 = "打开这一组设置并转到它的位置"。

        和"只显示一种设置"不是一回事：这里**不动**别的分组，只保证这一组是展开的，
        然后把它滚到贴顶、标题行闪一下强调色、状态栏报一句 —— 让人明确知道
        "跳到了哪一组"，而不是把界面切换成另一个样子。
        """
        card = self.host.cards[key]
        self._jump_token += 1
        token = self._jump_token
        # 卡片自身的展开会触发 `_on_group_toggled` 的"保持原位置"定时器，
        # 它会在跳转滚动之后把滚动条拉回去。跳转期间先把这些定时器作废。
        self._jump_guard_until = time.monotonic() + 0.8
        was_closed = not self.host._region_shown.get("left", True)
        if was_closed:
            # 等左栏展开动画真正跑完再滚 —— 动画期间滚动区范围还没长出来。
            self.host._set_region_visible(
                "left", True,
                on_done=lambda c=card, t=token: self._jump_to_card(c, t))
        grew = not card.is_expanded()
        if grew:
            card.blockSignals(True)
            try:
                card.set_expanded(True)
            finally:
                card.blockSignals(False)
        self.host._active_group = key
        self.host._after_group_change()
        # 展开有 160ms 的动画：要等它跑完、内容长到最终高度、滚动区真的长出滚动条
        # 之后再滚 —— 否则此刻范围还是 0，怎么设都被夹在顶端，"贴顶"根本没发生。
        if not was_closed:
            QtCore.QTimer.singleShot(
                FoldCard.ANIM_MS + 60 if grew else 0,
                lambda c=card, t=token: self._jump_to_card(c, t))
        card.flash()
        # 轨道高亮与标题闪烁同步收尾：图标不代表"选中/显隐"，只作一次性的"我跳到了这儿"
        QtCore.QTimer.singleShot(700, self.host._clear_active_group)
        self.host.status.setText(f"已跳到「{self.host.GROUP_TITLES[key]}」设置。")

    def _jump_to_card(self, card: QtWidgets.QWidget, token: int) -> None:
        """把目标卡片滚进视野；多拍执行以吃掉落后的布局刷新。"""
        if token != self._jump_token:
            return                       # 已经跳到别的组了

        def _beat() -> None:
            if token == self._jump_token:
                self._scroll_to_card(card)

        _beat()
        QtCore.QTimer.singleShot(60, _beat)

        def _last() -> None:
            if token != self._jump_token:
                return
            _beat()
            # guard 按时间自然过期：过早清零会让更晚的 _keep_anchor 把滚动拉回去

        QtCore.QTimer.singleShot(160, _last)

    def _schedule_scroll_to_card(self, card: QtWidgets.QWidget, delay: int = 0) -> None:
        """滚动到某张卡片贴顶：分两拍做。

        第一拍等展开动画结束，第二拍再等一次布局刷新（滚动条范围要等布局算完才更新）。
        两拍都只是"尽力贴顶"—— 卡片接近底部时 ``setValue`` 会自动夹到能到的最大值。
        """
        def _do() -> None:
            self.host._scroll_to_card(card)
            QtCore.QTimer.singleShot(0, lambda: self.host._scroll_to_card(card))
        QtCore.QTimer.singleShot(max(0, int(delay)), _do)

    def _clear_active_group(self) -> None:
        if self.host._active_group is None:
            return
        self.host._active_group = None
        self.host._sync_rail()

    def _scroll_to_card(self, card: QtWidgets.QWidget) -> None:
        inner = self.host.left_body.widget()
        if inner is None:
            return
        top = card.mapTo(inner, QtCore.QPoint(0, 0)).y()
        self.host.left_body.verticalScrollBar().setValue(max(0, top - 8))

    def _toggle_all_groups(self) -> None:
        """⇕：把**已加入侧边栏的那些组**一并展开 / 一并收起。

        没加入的组不参与 —— 它们本来就不在界面上，⇕ 去动它们只会让人费解。
        一组都没加入时 ⇕ 无事可做（左栏自己的空状态文案已经指了路）。
        """
        joined = [k for k in self.host.GROUP_ORDER if k in self.host._rail_keys]
        if not joined:
            return
        any_on = any(self.host.cards[k].is_expanded() for k in joined)
        self.host._set_all_groups(not any_on, keys=joined)

    def _set_all_groups(self, on: bool, keys: list[str] | None = None,
                        animate: bool = True) -> None:
        """把 ``keys`` 里的分组收放到 ``on``（默认 = 已加入侧边栏的那些组）。

        这些卡片共用**一个进度**：每帧只算一次插值、只触发一次布局，比多张卡片各推
        一次顺得多。动画期间还把垂直滚动条钉成"常显"，免得它中途出现/消失把整列
        宽度一起改掉（那会让内容逐帧重排）。
        """
        keys = [k for k in self.host.GROUP_ORDER
                if (keys is None or k in keys)]
        if not keys:
            self.host._after_group_change()
            return
        self.host._group_anim_busy = True
        try:
            spans = [(self.host.cards[k], self.host.cards[k].begin_anim(on)) for k in keys]
        finally:
            self.host._group_anim_busy = False

        if self.host._group_anim is not None:
            self.host._group_anim.stop()
            self.host._group_anim = None

        if not animate:
            for card, (_start, target) in spans:
                card.set_anim_height(target)
                card.end_anim()
            self.host._after_group_change()
            return

        # 滚动条钉成"常显"：免得它中途出现/消失把整列宽度一起改掉（那会让内容逐帧重排）
        area = self.host.left_body
        area.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        anim = QtCore.QVariantAnimation(self.host)
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
            self.host._group_anim = None
            self.host._after_group_change()

        anim.valueChanged.connect(_frame)
        anim.finished.connect(_done)
        self.host._group_anim = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _after_group_change(self, reset_scroll: bool = False) -> None:
        self.host._update_group_summaries()
        self.host._sync_rail()
        self.host._save_ui_state()
        self.host._sync_left_empty_hint()
        if reset_scroll:
            # 只有“清空数据/回到初始状态”才回顶部；普通展开/收起必须留在原地
            self.host.left_body.verticalScrollBar().setValue(0)

    def _on_group_toggled(self, key: str, on: bool) -> None:
        """某个分组被收放（点箭头 / 点整行 / 双击标题行）。

        不再有"手风琴"联动：多组可以自由同时展开，一组被收掉不影响其他组 ——
        这里是纯粹的"记状态 + 刷摘要"，把每个分组当成一件独立的事。
        滚动条位置要保住：内容高度变化后按标题行原来的屏幕位置反算，让被点的
        那一行留在原地（允许为容纳内容做最小必要位移）。
        """
        if self.host._group_anim_busy:
            return                       # 批量动画自己会收尾，这里不插手
        card = self.host.cards[key]
        bar = self.host.left_body.verticalScrollBar()
        inner = self.host.left_body.widget()
        top_before = (card.mapTo(inner, QtCore.QPoint(0, 0)).y() - bar.value()
                      if inner is not None else 0)
        self.host._after_group_change()

        def _keep_anchor() -> None:
            if time.monotonic() < self._jump_guard_until:
                return                    # 正在"跳到某组"，别把滚动拉回原位
            content = self.host.left_body.widget()
            if content is None:
                return
            # 让这张卡的标题行回到收放前的视口 y：滚动值 = 内容内 y − 目标视口 y
            target = card.mapTo(content, QtCore.QPoint(0, 0)).y() - top_before
            bar.setValue(max(0, target))

        # 展开动画 160ms；结束后布局才算最终高度，再下一轮事件循环滚动范围才更新
        QtCore.QTimer.singleShot(FoldCard.ANIM_MS + 30, _keep_anchor)
        QtCore.QTimer.singleShot(FoldCard.ANIM_MS + 60, _keep_anchor)

    def _update_group_summaries(self) -> None:
        """给每张卡片的收起态写一行摘要：不展开也知道里面是什么值。

        只写**当前处于收起态**的卡片，并且内容不变就不写 —— 否则每次刷新都改
        一堆隐藏标签的文字，会让左栏反复重排（拖滑块时尤其明显）。
        """
        def put(key: str, text: str) -> None:
            card = self.host.cards[key]
            if not card.is_expanded() and card.summary_text() != text:
                card.set_summary(text)

        # 摘要刻意写得短：左栏一共三百来像素，太长会把标题行挤变形
        if self.host.datasets:
            vol = self.host.vol
            put("data", f"{vol.ns}×{vol.nr}×{vol.nt}")
            n = max(1, vol.slice_index_range(self.host.mode) - 1)
            put("cut", f"{SLICE_LABELS[self.host.mode]} {self.host.pos[self.host.mode]}/{n}")
        else:
            put("data", "未载入数据")
            put("cut", "无数据")
        cmap = str(self.host.cmap_combo.currentText()).split("（")[0]
        put("density", f"{cmap} · {self.host.contrast.value()}% · "
                       f"AGC {'开' if self.host.chk_agc.isChecked() else '关'}")
        wig = ("仅波形" if self.host.chk_pure.isChecked()
               else ("叠加" if self.host.chk_wiggle.isChecked() else "关"))
        put("wave", f"{wig} · {self.host.spin_wig.value()} 道")
        cnt = len(self.host.datasets)
        put("compare", f"{cnt}/{MAX_DATASETS}" + (
            " · 已同步" if cnt > 1 and self.host.chk_sync.isChecked() else ""))

    def _load_ui_state(self) -> None:
        """恢复上次的左栏状态；读不到或格式不对就退回默认。

        ``SEISVIEW_NO_PERSIST=1`` 时**读写都不做**（只挡保存不够：测试里会被上次
        留下的状态污染，跑不出"全新启动"的行为）。
        """
        if not _PERSIST_UI:
            self.host._group_expanded = dict(self.host.GROUP_DEFAULT)
            self.host._rail_keys = list(self.host.GROUP_ORDER)
            self.host._theme_key = "deepblue"
            self.host._follow_layout = True
            self.host._reset_layout_defaults()
            return
        s = self.host._settings
        self.host._group_expanded = dict(self.host.GROUP_DEFAULT)
        self.host._region_shown["left"] = bool(s.value("ui/left_visible", True, type=bool))
        raw = str(s.value("ui/groups", "", type=str))
        parts = raw.split(",")
        if len(parts) == len(self.host.GROUP_ORDER) and all(p in ("0", "1") for p in parts):
            self.host._group_expanded = {k: (v == "1")
                                    for k, v in zip(self.host.GROUP_ORDER, parts)}
        # 轨道里加入了哪几组。用逗号分隔的一组 key；空串 = 一组都不加（合法状态）。
        raw = str(s.value("ui/rail_keys", ",".join(self.host.GROUP_ORDER), type=str))
        keys = [k for k in raw.split(",") if k in self.host.GROUP_ORDER]
        self.host._rail_keys = keys
        # 主题（含 "system"）。认不出来的键在 style.set_theme 里会退回默认。
        self.host._theme_key = str(s.value("ui/theme", "deepblue", type=str))
        # 窗口大小是否跟随右侧排版自动调整（默认开）
        self.host._follow_layout = bool(s.value("ui/follow_layout", True, type=bool))
        # 默认布局（设置页「默认分屏设置」里点 ★ 设定的那几项）
        self.host._reset_layout_defaults()
        raw = str(s.value("ui/default3", "", type=str))
        if raw in THREE_KEYS:
            self.host._default3_key = raw
            order = self.host._parse_pair_order(
                str(s.value("ui/default3_order", "", type=str)),
                self.host._builtin_order_for(raw))
            if len(order) == 2:
                self.host._default3_order = order
        for key, pair in KEY_PAIR.items():
            order = self.host._parse_pair_order(
                str(s.value(f"ui/pair_default_{key}", "", type=str)),
                self.host._builtin_order_for(key))
            if len(order) == 2:
                self.host._pair_defaults[key] = order

    def _reset_layout_defaults(self) -> None:
        """把"默认布局"清成内置的那一套（启动 / 无持久化时用）。"""
        self.host._default3_key = ""
        self.host._default3_order = ()
        self.host._pair_defaults = {}

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
        s = self.host._settings
        s.setValue("ui/left_visible", bool(self.host._region_shown.get("left", True)))
        s.setValue("ui/groups", ",".join(
            "1" if self.host.cards[k].is_expanded() else "0" for k in self.host.GROUP_ORDER))
        s.setValue("ui/rail_keys", ",".join(k for k in self.host.GROUP_ORDER
                                            if k in self.host._rail_keys))
        s.setValue("ui/theme", self.host._theme_key)
        s.setValue("ui/follow_layout", bool(self.host._follow_layout))
        s.setValue("ui/default3", self.host._default3_key)
        s.setValue("ui/default3_order", ",".join(self.host._default3_order))
        for key in KEY_PAIR:
            s.setValue(f"ui/pair_default_{key}",
                       ",".join(self.host._pair_defaults.get(key, ())))

    def apply_theme_key(self, key: str, persist: bool = True,
                        announce: bool = True) -> None:
        """切换界面主题（``key`` 可为 ``"system"``＝跟随系统）。

        换主题要动的**不只是样式表**：图标、pyqtgraph 画布底、三维 GL 底色、
        plot 图例、控件自己的行内样式，都是按"当时"的颜色现画的，必须逐个重刷。

        **导出图不在其中** —— 它固定用论文白底，与主题无关（见 style.PAPER_*）。
        """
        style.set_theme(key, QtWidgets.QApplication.instance())
        self.host._theme_key = style.current_key()
        self.host._sync_color_scheme_hook()
        self.host._refresh_theme_widgets()
        if persist:
            self.host._save_ui_state()
        if not announce:
            return
        label = style.theme_label(self.host._theme_key)
        if self.host._theme_key == style.SYSTEM_KEY:
            light = style.current_theme() == "paper"
            label += f"（当前跟随到{'纸白' if light else '极夜黑'}）"
        self.host.status.setText(f"已切换主题：{label}")

    def _sync_color_scheme_hook(self) -> None:
        """只在"跟随系统"时监听系统深浅变化，换到固定主题就把连接摘掉。"""
        hints = QtGui.QGuiApplication.styleHints()
        if hints is None:                                   # pragma: no cover
            return
        try:
            hints.colorSchemeChanged.disconnect(self.host._on_system_scheme_changed)
        except Exception:
            pass
        self.host._scheme_hook = None
        if self.host._theme_key != style.SYSTEM_KEY:
            return
        try:
            hints.colorSchemeChanged.connect(self.host._on_system_scheme_changed)
            self.host._scheme_hook = hints.colorSchemeChanged
        except Exception:                                   # pragma: no cover
            self.host._scheme_hook = None

    def _on_system_scheme_changed(self, *_args) -> None:
        """系统切了浅色/深色：跟随系统时立刻跟着换（不写回偏好，偏好仍是 system）。"""
        if self.host._theme_key != style.SYSTEM_KEY:
            return
        self.host.apply_theme_key(style.SYSTEM_KEY, persist=False)

    def _refresh_theme_widgets(self) -> None:
        """把"按当时颜色现画"的东西全部重刷一遍。

        需要手工补的只有这几类：现画的图标、pyqtgraph 画布/图例、三维 GL 底、
        控件自带的行内样式（分段按钮、分组横线）。其余控件都吃全局 QSS，会自己变。
        """
        self.host._sync_rail()
        self.host.btn_prefs.setIcon(QtGui.QIcon(icons.gear(18, style.TEXT_DIM)))
        self.host.btn_reset.setIcon(QtGui.QIcon(icons.reset_view(18, style.TEXT_DIM)))
        self.host._sync_panel_chips()
        for lab in self.host.findChildren(QtWidgets.QLabel, "GrabHandle"):
            lab.setPixmap(icons.grab(14, style.TEXT_MUTE))
        divider = f"color: {style.LINE}; background: {style.LINE}; max-height: 1px;"
        for line in self.host.findChildren(QtWidgets.QFrame, "HDivider"):
            line.setStyleSheet(divider)
        for card in self.host.cards.values():
            card.restyle()
        for seg in self.host.findChildren(SegmentedControl):
            seg.restyle()
        for panel in self.host.panels:
            panel.restyle()
        self.host.trace_view.restyle()
        self.host._sync_trace_legend(force=True)
        if self.host.view3d is not None:
            self.host.view3d.restyle()
        for win in list(self.host._detached.values()):
            win.restyle()
        # 切片图是按当时的底色烘进 RGBA 的，缓存作废重画一遍
        if self.host.datasets:
            self.host._refresh_all(sync_controls=False)
        else:
            self.host.pipeline.panel_cache.clear()
        self.host.update()

    def _set_region_visible(self, key: str, on: bool, animate: bool = True,
                            on_done=None) -> None:
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
            self.host._toggle_content("right")
            return
        if self.host._region_shown.get("left", True) == bool(on):
            return
        self.host._region_shown["left"] = bool(on)
        total = self.host._total(self.host.body_split)
        old_left = max(self.host.LEFT_RAIL_W, self.host.left_wrap.width())
        old_win = self.host.width()
        old_right = max(1, self.host.workspace.width())
        chrome = max(0, old_win - old_left - old_right)
        self.host._sync_rail()

        if not on:
            self.host._region_sizes["left"] = list(self.host.body_split.sizes())
            new_left = self.host.LEFT_RAIL_W
        else:
            saved = self.host._region_sizes.get("left")
            new_left = (saved[0] if saved and len(saved) == 2 and sum(saved) > 120
                        else self.host._left_min_w)

        # 先摆好内容可见性与宽度约束，动画结束时再钉死
        if not on:
            self.host.left_wrap.setMinimumWidth(0)
            self.host.left_wrap.setMaximumWidth(16777215)
            self.host._freeze_content_width(self.host.left_content.width())
            self.host.status.setText("已收起设置面板。")
            pin = self.host._pin_left_rail
        else:
            self.host.left_wrap.setMinimumWidth(0)
            self.host.left_wrap.setMaximumWidth(16777215)
            self.host.left_content.setVisible(True)
            # 同样先把内容钉在最终宽度上：动画里只有"露出来的部分"在变，内部不重排
            self.host._freeze_content_width(max(120, new_left - self.host.LEFT_RAIL_W - 6))
            self.host.status.setText("已展开设置面板。")
            pin = self.host._pin_left_open

        def _finished() -> None:
            pin()
            if on_done is not None:
                on_done()

        # 侧边栏收起不是“空间不足”，不该让工作区去吸收它让出的宽度：
        # 总窗口等量反向变化，右侧各块维持原来的像素尺寸。
        can_resize_window = not (self.host.isFullScreen() or self.host.isMaximized())
        if can_resize_window:
            avail = (self.host.screen() or QtGui.QGuiApplication.primaryScreen())
            max_w = (avail.availableGeometry().width() if avail is not None else 10 ** 6)
            new_win = min(float(old_win) + (new_left - old_left), max_w)
            new_win = max(new_win, float(self.host.MIN_SIZE[0]))
            if animate and abs(new_win - old_win) > 1:
                self._animate_left_toggle(
                    old_left, new_left, float(old_win), float(new_win),
                    chrome, opening=bool(on), on_done=_finished)
                self.host._save_ui_state()
                return
            if abs(new_win - old_win) > 1:
                self.host._resize_keeping_anchor(int(new_win), self.host.height())
            right_w = max(1, self.host.width() - new_left - chrome)
            actual_delta = self.host.width() - old_win
            if self.host._user_size is not None:
                self.host._user_size = (max(1, self.host._user_size[0] + actual_delta),
                                   self.host._user_size[1])
        else:
            # 全屏 / 最大化：窗口不能动，只能把空间在内部重新分配
            right_w = max(1, total - new_left)

        self.host._apply_sizes(self.host.body_split, [new_left, right_w],
                               animate, on_done=_finished)
        self.host._save_ui_state()

    def _stop_left_anim(self) -> None:
        """停掉未完成的侧栏收展动画，并归还窗口尺寸锁。"""
        anim, self._left_anim = self._left_anim, None
        if anim is None:
            return
        try:
            anim.stop()
        except RuntimeError:                     # DeleteWhenStopped 已经删了
            pass
        if self.host._left_animating:
            self.host._auto_resize_depth = max(0, self.host._auto_resize_depth - 1)
            self.host._left_animating = False

    def _animate_left_toggle(self, old_left: int, new_left: int,
                             old_win: float, new_win: float, chrome: int,
                             opening: bool, on_done) -> None:
        """窗口宽度与 splitter 比例同一条进度：两边一起滑，不再先跳后补。"""
        self._stop_left_anim()
        anchor = self.host._frame_anchor()
        off = self.host._client_offset()
        duration = int(getattr(self.host, "LAYOUT_ANIM_MS", 190))
        anim = QtCore.QVariantAnimation(self.host)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self.host._left_animating = True
        self.host._auto_resize_depth += 1

        def frame(v) -> None:
            t = float(v)
            win = old_win + (new_win - old_win) * t
            left = int(round(old_left + (new_left - old_left) * t))
            width = int(round(win))
            self.host.setGeometry(anchor.x() + off.x(), anchor.y() + off.y(),
                                  width, self.host.height())
            self.host.body_split.setSizes(
                [left, max(1, width - left - chrome)])

        def done() -> None:
            self._left_anim = None
            if self.host._left_animating:
                self.host._auto_resize_depth = max(0, self.host._auto_resize_depth - 1)
                self.host._left_animating = False
            width = int(round(new_win))
            self.host.setGeometry(anchor.x() + off.x(), anchor.y() + off.y(),
                                  width, self.host.height())
            self.host.body_split.setSizes(
                [int(new_left), max(1, width - int(new_left) - chrome)])
            if self.host._user_size is not None:
                delta = width - int(round(old_win))
                self.host._user_size = (
                    max(1, self.host._user_size[0] + delta),
                    self.host._user_size[1])
            self.host._hold_content_min()
            on_done()

        anim.valueChanged.connect(frame)
        anim.finished.connect(done)
        self._left_anim = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _pin_left_rail(self) -> None:
        """收起动画结束：这时才真正隐藏内容，再把左栏钉在轨道宽度上。"""
        self.host.left_content.setVisible(False)
        self.host._freeze_content_width(None)
        self.host.left_wrap.setMinimumWidth(self.host.LEFT_RAIL_W)
        self.host.left_wrap.setMaximumWidth(self.host.LEFT_RAIL_W)

    def _pin_left_open(self) -> None:
        """展开动画结束：解冻内容宽度，恢复左栏的可用宽度区间。"""
        self.host._freeze_content_width(None)
        self.host.left_wrap.setMinimumWidth(self.host._left_min_w)
        self.host.left_wrap.setMaximumWidth(max(self.host.LEFT_MAX_W, self.host._left_min_w))
