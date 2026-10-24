"""分屏布局引擎：预设、splitter 树、尺寸分配、窗口自适应与摆法面板。

方法从 MainWindow 机械迁入；宿主（MainWindow）仍是控件与窗口的持有者，
这里只负责布局决策与执行。
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid as _qt_valid

from . import icons, style
from .layout_config import (CAPSULE_KEY, GROUP_OF, KEY_PAIR, PANEL_LABELS,
                            PANEL_ORDER, PANEL_PRIORITY, PINNED_OF,
                            WORKSPACE_MARGIN)
from .view2d import SlicePanel
from .widgets import (LAYOUT_TITLE, THREE_KEYS,
                      pair_layout, three_free_pair)


class LayoutEngine:
    """把一个宿主窗口的三块内容面板按预设装进 splitter 树。"""

    def __init__(self, host) -> None:
        self.host = host

    def _shown_list(self) -> list:
        """当前显示着的块，按 1 → 2 → 3 的固定次序。"""
        return [k for k in PANEL_ORDER if self.host._content_shown.get(k)]

    def _layout_vis(self) -> list:
        """决定**当前构图**的那份可见集合：几何上真的看得见的那几块。

        与 :meth:`_shown_list`（开关状态）不是一个东西 —— 被拉到独立窗口的那块，槽位
        已经让出来了，构图就该按**剩下的块**重新定。否则把它拖出去后，剩下两块会继续
        沿用三块构图那棵树和那套尺寸：实测拖出剖面后，两块落在 B 的 0.72/0.28 上，
        比例与缩略图对不上，看着就不像设计好的那三种两栏构图。
        """
        eff = self.host._effective_shown()
        return [k for k in PANEL_ORDER if eff[k]]

    def _layout_key(self) -> str:
        """当前这套排版是"七个具体摆法"里的哪一个（用于面板亮框）。

        只有一块界面时谈不上"排法"，返回空串（面板里就不亮任何一张）。
        """
        vis = self.host._layout_vis()
        if len(vis) >= 3:
            # 三块时构图由 ``_layout_preset`` 定；万一它还是"两块摆法"的键（例如从两块
            # 构图里又找回一块），退回默认的 B —— 别让三块挤在一行里。
            return self.host._layout_preset if self.host._layout_preset in THREE_KEYS else "B"
        if len(vis) == 2:
            return pair_layout(tuple(vis))[0]
        return ""

    def _builtin_order_for(self, key: str) -> tuple:
        """某张摆法的**内置**先后（用户没设过默认时的那一套）。"""
        if GROUP_OF.get(key, 0) >= 3:
            return three_free_pair(PINNED_OF.get(key, "trace"), PANEL_ORDER)
        pair = KEY_PAIR.get(key)
        if pair is None:
            return ("slice", "right")
        return tuple(pair_layout(pair)[2])

    def _thumb_order(self, key: str) -> tuple:
        """某张缩略图该画的先后 —— **就是点它会得到的那一套**。

        三块：用户把这张设成默认（且存了先后）就用存的那套，否则用内置；
        两块：这一组合设过默认就用设的，否则用内置。返回空元组表示"这张不适用"。
        """
        if not key:
            return ()
        if GROUP_OF.get(key, 0) >= 3:
            if self.host._default3_key == key and len(self.host._default3_order) == 2:
                return tuple(self.host._default3_order)
            return self.host._builtin_order_for(key)
        saved = self.host._pair_defaults.get(key)
        return tuple(saved) if saved else self.host._builtin_order_for(key)

    def _free_pair(self) -> tuple:
        """"可换序的那两块"的**默认**先后（不含被钉住的那块）：有用户配置就用配置的。"""
        vis = self.host._layout_vis()
        if len(vis) >= 3:
            return self.host._thumb_order(self.host._layout_key())
        if len(vis) == 2:
            return self.host._thumb_order(pair_layout(tuple(vis))[0])
        return tuple(vis)

    def _star_keys(self) -> set:
        """哪些缩略图该亮 ★ —— 即"各组合**当前生效**的默认"（含内置）。

        三块组只有一个生效项；两块组每个组合各有一个。
        """
        out = {self.host._default3_key or "B"}
        for key, pair in KEY_PAIR.items():
            saved = self.host._pair_defaults.get(key)
            out.add(key if saved else pair_layout(pair)[0])
        return out

    def _is_builtin_default(self) -> bool:
        """三块默认与三种两块默认**全都是内置**的（用来在提示行里写明"内置/自定义"）。"""
        return (not self.host._default3_key and not self.host._default3_order
                and not self.host._pair_defaults)

    def _sync_pair_order(self) -> None:
        """让 ``_pair_order`` 跟"当前可换序的那两块"对齐；换了组合就回到这一对的默认先后。

        默认先后就是需求里定的那三种（剖面+三维 → 左剖面右三维；单道+三维 → 上三维下单道；
        剖面+单道 → 上剖面下单道），**但用户可以在摆法面板里点 ★ 改掉它**。所以"⇄"的翻转
        只在这套组合内有效，换组合即回到该组合的默认。
        """
        want = self.host._free_pair()
        if len(want) != 2:
            self.host._pair_order = list(want)
            return
        if sorted(self.host._pair_order) != sorted(want):
            self.host._pair_order = list(want)

    def _align_pair_order(self, first: str | None = None) -> None:
        """对齐"可换序那两块"的先后：**集合没变就保序**（不要复位成默认），变了才回默认。

        这是拖动落位要的"按当前位置保序"：例如原来在 B 里用「⇄」把三维换到左边，
        把单道拖走/拖回之后，剩下的"剖面+三维"仍要保持三维在左。``first`` 非空时
        把它提到最前（拖动贴边时用："拖的那块排前面"）。
        """
        want = list(self.host._free_pair())
        if len(want) == 2:
            if not (len(self.host._pair_order) == 2
                    and sorted(self.host._pair_order) == sorted(want)):
                self.host._pair_order = want
        else:
            self.host._pair_order = want
        if first and first in self.host._pair_order:
            self.host._pair_order = [first] + [k for k in self.host._pair_order if k != first]

    def _slots(self) -> tuple:
        """三块在树里的**叶子顺序**（可换序的两块在前、钉住/收起的在后）。

        这个顺序同时是"缩略图里谁在左、谁在底"的依据，所以必须跟
        :meth:`_build_work_tree` 真正 addWidget 的顺序一致 —— 尤其是两块摆法，
        方向由这一对固定决定，先后则由「⇄」翻转，不能再按 1→2→3 的固定次序排。
        顺序按 :meth:`_layout_vis` 算：**被拖出去的那块排到最后（占 0 槽位）**，
        这样剩下两块才是那三种设计好的两栏构图。
        """
        vis = self.host._layout_vis()
        hidden = [k for k in PANEL_ORDER if k not in vis]
        if len(vis) >= 3:
            f1, f2 = self.host._free_pair()
            if len(self.host._pair_order) == 2 and set(self.host._pair_order) == {f1, f2}:
                f1, f2 = self.host._pair_order
            return (f1, f2, PINNED_OF.get(self.host._layout_key(), "trace"))
        if len(vis) == 2:
            f1, f2 = self.host._free_pair()
            if len(self.host._pair_order) == 2 and set(self.host._pair_order) == {f1, f2}:
                f1, f2 = self.host._pair_order
            return (f1, f2, hidden[0])
        return tuple(vis + hidden)

    def _build_work_tree(self) -> None:
        """按当前摆法把三块容器装进 splitter 树。

        五个摆法分两类：
          三块  B → V( H(f1, f2), 单道 )    上排两块左右 + 单道底部通栏（默认）
               A → H( V(f1, f2), 三维 )    左列两块上下 + 三维右列
          两块  H( f1, f2, 收起的一块 )     左右并排
               V( f1, f2, 收起的一块 )     上下排列
        其中 ``f1, f2`` 是 :meth:`_free_pair` 的先后 —— 「⇄」翻转它们即可换"谁在左、
        谁在下"。被钉住的那块（B 的单道 / A 的三维）在树里的位置固定，所以
        "单道永远在底栏、三维永远在右列"是结构保证的，不靠分配器。

        这里重建的是 **splitter 本身**；三块容器只是被插进新的槽位（``setParent(None)``
        后立刻挂到新分割器上，中间没有任何一次事件循环，视图不会被重建）。
        """
        self.host._stop_all_size_anims()
        leaves = {"slice": self.host.slice_holder, "trace": self.host.trace_holder,
                  "right": self.host.right_holder}
        self.host._sync_pair_order()
        visit = self.host._layout_vis()          # 构图按"实际可见"算（被拖出的那块让位）
        old_root = getattr(self.host, "work_tree", None)
        for w in leaves.values():
            w.setParent(None)              # 先摘出来，免得跟着旧树一起被删
        if old_root is not None:
            for sp in list(self.host._tree_splitters):
                sp.setParent(None)
                sp.deleteLater()
        self.host._tree_splitters = []

        def make(orient):
            sp = QtWidgets.QSplitter(orient)
            sp.setChildrenCollapsible(True)
            sp.setHandleWidth(4)
            self.host._tree_splitters.append(sp)
            return sp

        tree = {}
        preset3 = self.host._layout_key() if len(visit) >= 3 else None
        if preset3 in ("A", "AL"):
            # 左列（或右列）两块上下叠放 + 三维一列；AL 是 A 的镜像（三维在左）。
            f1, f2 = self.host._slots()[:2]         # 取**已换过序**的先后（⇄ / 拖动保序都靠它）
            inner = make(QtCore.Qt.Orientation.Vertical)
            inner.addWidget(leaves[f1])
            inner.addWidget(leaves[f2])
            root = make(QtCore.Qt.Orientation.Horizontal)
            if preset3 == "A":
                root.addWidget(inner)
                root.addWidget(leaves["right"])
            else:
                root.addWidget(leaves["right"])
                root.addWidget(inner)
            tree["inner"], tree["free"] = inner, (f1, f2)
        elif preset3 in ("B", "BT"):
            # 上排两块左右并排 + 单道通栏；BT 是 B 的镜像（单道在上）。
            f1, f2 = self.host._slots()[:2]         # 取**已换过序**的先后（⇄ / 拖动保序都靠它）
            top = make(QtCore.Qt.Orientation.Horizontal)
            top.addWidget(leaves[f1])
            top.addWidget(leaves[f2])
            root = make(QtCore.Qt.Orientation.Vertical)
            if preset3 == "B":
                root.addWidget(top)
                root.addWidget(leaves["trace"])
            else:
                root.addWidget(leaves["trace"])
                root.addWidget(top)
            tree["inner"], tree["free"] = top, (f1, f2)
        else:
            # 两块：方向由"哪两块"决定（就是需求里那三种两栏构图）；
            # 一块：方向无所谓（反正只显示一块），多出来的两块留在树里占 0，
            # 保证所有容器都有父控件。
            slots = self.host._slots()
            pair = tuple(slots[:2])
            orient = pair_layout(tuple(sorted(pair)))[1] if len(pair) == 2 else "H"
            root = make(QtCore.Qt.Orientation.Horizontal if orient == "H"
                        else QtCore.Qt.Orientation.Vertical)
            for k in slots:
                root.addWidget(leaves[k])
            tree["free"] = None
        tree["preset"] = self.host._layout_key()
        tree["slots"] = tuple(self.host._slots())
        tree["root"] = root
        self.host._tree = tree
        self.host.work_tree = root
        self.host._work_host_layout.addWidget(root)
        # 新树默认是隐藏的，要等下一轮事件循环才被布局系统显示出来 —— 那之前如果
        # 先画了一帧，看到的就是"工作区空着"再突然长出三块。这里当场显示，首帧即终态。
        root.show()

    def _apply_layout(self, key: str, first: str | None = None) -> None:
        """切到某个具体摆法；块数不够/多出来时**顺带对齐块数**（直接跳转，不置灰）。

        * 点三块摆法（A/B）而手上不足三块 → 补齐到三块；
        * 点两块摆法（SR/TR/ST）→ 直接换成它画的那两块；
        * 两块摆法之间互切时，只换"哪两块"，方向由这一对固定决定。

        ``first`` 指定"可换序那两块"里的第一个（拖动贴边时用："拖的那块排前面"）。
        """
        if key not in GROUP_OF:
            return
        want = GROUP_OF[key]
        need = set(PANEL_ORDER) if want >= 3 else set(KEY_PAIR[key])
        missing = need - self._available_panels()
        if missing:
            self.host.status.setText(
                "当前数据下没有 " + "、".join(PANEL_LABELS[k] for k in PANEL_ORDER
                                           if k in missing) + " 面板。")
            return
        # 这套构图要用的面板如果有在独立窗口里的，先收回来 —— 否则凑不齐块数，
        # "选了 A 却只排成两块"就是这么来的。
        self.host._reclaim(PANEL_ORDER if want >= 3 else KEY_PAIR[key])
        if want == 3:
            for k in PANEL_ORDER:
                self.host._content_shown[k] = True
            self.host._layout_preset = key
        else:
            pair = KEY_PAIR[key]
            self.host._content_shown = {k: (k in pair) for k in PANEL_ORDER}
        # 先后**同集合保序**（拖动贴边/拖动落位时不要把用户换过的顺序复位）
        self.host._align_pair_order(first)
        self.host._three_auto_closed = False
        if self.host._content_shown.get("right"):
            self.host._ensure_view3d()
        self.host._suppress_window_resize = True          # 窗口尺寸交给动画滑过去
        try:
            self.host._build_work_tree()
            self.host._relayout_content(animate=False)
        finally:
            self.host._suppress_window_resize = False
        self.host._animate_layout_change()
        vis = self.host._shown_list()
        self.host.status.setText(
            f"摆法 {key}：现在显示 " + "、".join(PANEL_LABELS[k] for k in vis) + "。")

    def _sync_layout_for_count(self, force_default: bool = True) -> None:
        """块数一变就让摆法跟着走：三块落到**用户配置的默认三块构图**上，两块落到对应那一对。

        切换是**结构保证**的：B/BT 里单道固定在底/顶栏、A/AL 里三维固定在右/左列，所以块数
        变化只是把位置腾出来/收回去，不会让"单道跑到通栏以外"。

        **变成三块时回到默认构图**（``_default3_key``，没配过就是内置的 B：主+侧+底、单道在
        底栏）—— 这正是需求里说的"用胶囊开到三块时落到默认那一套"；想临时换一种，从摆法面板里
        点那张缩略图即可。
        ``force_default=False`` 用于"拖出 / 收回一块"的路径：那只是几何让位，
        不该顺手把用户当前选的构图改掉。

        可见集合按 :meth:`_layout_vis` 算（被拖出去的那块不算），这样拖出之后剩下两块
        一定落在设计好的那三种两栏构图上。
        """
        vis = self.host._layout_vis()
        if "right" in vis:
            self.host._ensure_view3d()
        if force_default:
            # "块数变化 → 回到默认构图"，**连同它的先后**：否则用户以前「⇄」翻过的那套会留着，
            # 看上去就像"默认没生效"（先后也是默认的一部分）。
            if len(vis) >= 3:
                self.host._layout_preset = self.host._default3_key or "B"
                self.host._pair_order = list(self.host._thumb_order(self.host._layout_preset))
            elif len(vis) == 2:
                self.host._pair_order = list(self.host._thumb_order(pair_layout(tuple(vis))[0]))
        self.host._sync_pair_order()
        key = self.host._layout_key()
        need = (self.host._tree is None or self.host._tree.get("preset") != key
                or tuple(self.host._tree.get("slots", ())) != tuple(self.host._slots()))
        if need:
            self.host._suppress_window_resize = True
            try:
                self.host._build_work_tree()
                self.host._relayout_content(animate=False)
            finally:
                self.host._suppress_window_resize = False
            self.host._animate_layout_change()
        else:
            self.host._relayout_content(animate=True)

    def _reclaim(self, kinds) -> None:
        """把指定这几种面板从独立窗口**收回主窗口**。

        换摆法 / 独看 / 重新打开某一块之前必须先收回来：那块还在独立窗口里，主窗口就
        腾不出它的位置 —— 否则点了一张摆法缩略图会"没反应"（明明选了三块构图，实际
        只凑得出两块）。
        """
        want = set(kinds)
        for widget in list(self.host._detached):
            if self.host._drag_kind(widget) in want:
                self.host._close_detached(widget, silent=True)

    def reset_panel_layout(self) -> None:
        """**复位布局 / 找回所有面板**：一键把工作区恢复成"刚导入数据"的样子。

        这是"面板被拉到独立窗口后找不回来"时的兜底出口。它不看当前浮窗状态是否
        正确，而是**强制**做三件事：把所有面板收回主窗口（含状态错乱时的捞回）、
        恢复默认可见性（二维收起三维 / 三维三块全开）、回到**默认构图**
        （``_default3_key``，没配过就是内置的 B）。
        清空数据再导入不一定能救 —— 浮窗状态是独立于数据的一份状态，只有这里会重置它。
        """
        for widget in list(self.host._detached):
            self.host._close_detached(widget, silent=True)
        self.host._reclaim_stray_panels()
        self.host._clear_drag_layout(relayout=False)   # 万一是拖动中途调用：先撤掉瞬时状态
        avail = self._available_panels()
        one_d = avail == {"trace"}
        two_d = bool(self.host.datasets) and all(d.vol.is_single_shot for d in self.host.datasets)
        self.host._content_shown = {"slice": "slice" in avail, "trace": "trace" in avail,
                                    "right": "right" in avail and not two_d}
        if one_d:
            self.host._content_shown = {"slice": False, "trace": True, "right": False}
        self.host._layout_preset = self.host._default3_key or "B"
        self.host._pair_order = list(self.host._free_pair())   # 三块用该构图的默认；二维只有两块时按那一对
        self.host._three_auto_closed = False
        self.host._sync_layout_for_count()
        self._equalize_slice_panels()
        self.host.status.setText("已复位布局。")

    def _equalize_slice_panels(self) -> None:
        """把对比模式下的几块剖面恢复成同一宽度（刷新键的附带动作）。

        剖面之间是用户可拖动的 splitter：拖窄一块、拖宽另一块之后，
        刷新键除了复位整体布局，也应当把这几块"归位"成等宽。
        """
        sp = getattr(self.host, "slice_split", None)
        count = sp.count() if sp is not None else 0
        if count < 2:
            return
        total = self._total(sp)
        if total > count:
            base, extra = divmod(total, count)
            target = [base + (1 if i < extra else 0) for i in range(count)]
        else:
            # 剖面还没显示（尺寸为 0）时给等权值，等它拿到空间自然等分。
            target = [1] * count
        self._apply_sizes(sp, target, animate=False)

    def _reclaim_stray_panels(self) -> None:
        """把"标记为浮窗里、但已经不在任何浮窗记录里"的面板强行搬回主窗口。

        浮窗状态与真实父节点可能错乱（窗口被系统关掉、记录被提前 pop 掉）。
        这时只看 ``_detached`` 是找不到它们的 —— 所以按面板上的 ``floating`` 属性扫一遍，
        作为最后一道安全网。
        """
        strays = [w for w in (self.host.slice_wrap, self.host.trace_frame, self.host.right_frame)
                  if w.property("floating")]
        for widget in strays:
            self.host._detached.pop(widget, None)
            self.host._restore_detached(widget)

    def _available_panels(self) -> set[str]:
        """当前数据允许显示的面板：一维只有单道，二维没有三维，三维全开。"""
        vols = [d.vol for d in self.host.datasets]
        if not vols:
            return set(PANEL_ORDER)
        if all(v.is_single_trace for v in vols):
            return {"trace"}
        if all(v.is_single_shot for v in vols):
            return {"slice", "trace"}
        return set(PANEL_ORDER)

    def _sync_panel_chips(self) -> None:
        """胶囊三个图标的状态、「⇄ 交换」与刷新键的明暗、剖面块数圆点，全部对齐。"""
        if getattr(self.host, "capsule", None) is None:
            return
        avail = self._available_panels()
        for kind, btn in self.host.capsule.buttons.items():
            key = CAPSULE_KEY[kind]
            on = self.host._content_shown[key]
            allowed = key in avail
            btn.setEnabled(allowed)
            btn.setIcon(QtGui.QIcon(icons.kind(
                kind, 20, style.TEXT if on and allowed else style.TEXT_MUTE,
                style.ACCENT, on and allowed)))
            btn.setToolTip(self.host._capsule_tip(key, on, allowed))
        n = len(self.host.panels)
        group_floating = self.host._is_detached(self.host.slice_wrap)
        self.host.capsule.set_slice_dots(n, [group_floating] * n)
        f1, f2 = (self.host._pair_order + ["", ""])[:2]
        can_swap = bool(f2) and f1 in avail and f2 in avail
        dim = style.TEXT_DIM
        self.host.capsule.swap_btn.setIcon(QtGui.QIcon(
            icons.swap(18, dim if can_swap else style.TEXT_MUTE)))
        self.host.capsule.swap_btn.setEnabled(can_swap)
        self.host.capsule.swap_btn.setToolTip(
            f"交换：「{PANEL_LABELS[f1]}」↔「{PANEL_LABELS[f2]}」" if can_swap
            else "交换先后")
        self.host._sync_reset_entry()

    def _sync_reset_entry(self) -> None:
        """胶囊右侧的刷新键：一键复位布局并找回所有面板（对比剖面同时等宽归位）。"""
        cap = getattr(self.host, "capsule", None)
        if cap is None:
            return
        cap.reset_btn.setIcon(QtGui.QIcon(
            icons.reset_view(18, style.TEXT_DIM)))
        cap.reset_btn.setToolTip("复位布局／找回所有面板／对比剖面等宽")

    def _capsule_tip(self, key: str, on: bool, allowed: bool = True) -> str:
        name = PANEL_LABELS[key]
        if not allowed:
            return f"{name}　不可用"
        if on:
            return f"{name}　显示中"
        return f"{name}　已收起"


    def _toggle_content(self, key: str) -> None:
        """胶囊图标：**纯开关**（亮=在显示、暗=已收起），含义与当前状态无关。

        以前同一个点击按状态有三种含义（收起中的=加进来 / 显示中的=只看它 / 唯一的=
        退回上次组合），用户得先记住当前状态才知道点了会怎样 —— 现在只剩"开关"一种。
        "只看这一块"交给快捷键 1/2/3、Tab。
        """
        if key not in PANEL_ORDER:
            return
        if key not in self._available_panels():
            name = PANEL_LABELS[key]
            self.host.status.setText(f"「{name}」不可用。")
            return
        name = PANEL_LABELS[key]
        if self.host._content_shown.get(key):
            if self.host._is_single():
                self.host.status.setText("至少要保留一块面板。")
                return
            self.host._content_shown[key] = False
            self.host.status.setText(f"已收起「{name}」。")
        else:
            self.host._content_shown[key] = True
            # 点"已收起的块"= 要它显示出来：还在独立窗口里的先收回主窗口，
            # 不然这一下看起来毫无反应（块确实开着，只是还在桌面上飘着）。
            self.host._reclaim([key])
            self.host.status.setText(f"已显示「{name}」。")
        if key == "right":
            # 用户自己动了三维面板，就别再让"二维数据自动收起"覆盖他的选择
            self.host._three_auto_closed = False
            if self.host._content_shown.get("right"):
                self.host._ensure_view3d()
        self.host._sync_layout_for_count()

    def _focus_panel(self, key: str) -> None:
        """快捷键 1 / 2 / 3：只看某一块。"""
        self.host._solo(key)

    def _cycle_panel(self) -> None:
        """快捷键 Tab：在**当前可用的**面板之间循环独看。"""
        avail = [k for k in PANEL_ORDER if k in self._available_panels()]
        if not avail:
            return
        cur = next((k for k in avail if self.host._content_shown[k]), avail[0])
        i = avail.index(cur) if self.host._is_single() else -1
        self.host._solo(avail[(i + 1) % len(avail)])

    def _solo(self, key: str) -> None:
        """只看一块：另外两块收起。"""
        if key not in PANEL_ORDER:
            return
        if key not in self._available_panels():
            self.host.status.setText(
                f"「{PANEL_LABELS[key]}」在当前数据下不可用。")
            return
        # 其余两块要被收起 —— 还在独立窗口里的先收回主窗口，否则那些窗口会继续显示着
        # "已收起"的面板（开关状态与实际显示对不上）。
        self.host._reclaim(PANEL_ORDER)
        self.host._content_shown = {k: (k == key) for k in PANEL_ORDER}
        self.host._three_auto_closed = False
        if key == "right":
            self.host._ensure_view3d()
        self.host._relayout_content(animate=True)
        self.host.status.setText(
            f"已切到「{PANEL_LABELS[key]}」独看。")

    # ---------------------------------------------------- 默认分屏（设置页）
    def layout_default_groups(self) -> list[dict]:
        """设置页「默认分屏设置」要展示的四组：三块 + 三种两块组合。

        每组给出一到两个可选先后，``selected`` 标出当前生效的那一个。单块界面
        不需要摆法，所以这里只有四组。当前数据没显示的组合也照常列出，方便先配好。
        """
        host = self.host
        three_key = host._default3_key or "B"
        three_opts = [{"key": key, "order": tuple(host._thumb_order(key)),
                       "label": LAYOUT_TITLE[key]}
                      for key in ("B", "A", "BT", "AL")]
        groups = [{
            "id": "three",
            "title": "三块：剖面 + 单道 + 三维",
            "options": three_opts,
            "selected": {"key": three_key,
                         "order": tuple(host._thumb_order(three_key))},
            "builtin": {"key": "B",
                        "order": tuple(host._builtin_order_for("B"))},
        }]
        for gid, title, key in (("pair:slice+trace", "剖面 + 单道", "ST"),
                                ("pair:slice+right", "剖面 + 三维", "SR"),
                                ("pair:trace+right", "单道 + 三维", "TR")):
            pair = KEY_PAIR[key]
            builtin = tuple(pair_layout(pair)[2])
            chosen = tuple(host._pair_defaults.get(key) or builtin)
            opts = [{"key": key, "order": order,
                     "label": " → ".join(PANEL_LABELS[k] for k in order)}
                    for order in (builtin, tuple(reversed(builtin)))]
            groups.append({"id": gid, "title": title, "options": opts,
                           "selected": {"key": key, "order": chosen},
                           "builtin": {"key": key, "order": builtin}})
        return groups

    def apply_layout_defaults(self, choices: dict) -> None:
        """保存设置页的选择：``{组 id: (key, order)}``。只改默认，不动当前画面。"""
        for _gid, (key, order) in choices.items():
            order = tuple(order)
            if GROUP_OF.get(key, 0) >= 3:
                self.host._default3_key = key
                self.host._default3_order = order
            elif key in KEY_PAIR:
                self.host._pair_defaults[key] = order
        self.host._save_ui_state()
        self.host.status.setText("默认分屏设置已保存。")

    def _on_restore_builtin_defaults(self) -> None:
        """「恢复内置默认布局」：清掉自定义的默认，回到内置的 B 与各组合规范先后。"""
        self.host._default3_key = ""
        self.host._default3_order = ()
        self.host._pair_defaults = {}
        self.host._save_ui_state()
        self.host.status.setText("已恢复内置默认布局。")

    def _relayout_content(self, animate: bool = True, duration: int = 190) -> None:
        """按当前摆法 + 三块面板的显隐重排右侧工作区。

        **总窗口大小也跟着走**：先按当前排版算一遍"自然尺寸"（见
        :meth:`_fit_window_to_layout`，可以变大也可以变小），再把三块排进这棵
        splitter 树里 —— 三块始终是同一棵树、只是尺寸插值（绝不 reparent，
        所以三维的 GL 上下文、剖面面板的视野都不会被重置）；只有换"摆法"A/B/C/D
        才重建 splitter 树（见 :meth:`_build_work_tree`）。

        每块的自然尺寸按数据规模估（见 :meth:`_panel_metrics`）：剖面按"切片面的横纵
        采样数之比"、单道是一根扁条、三维取剖面宽度的 42%。空间不够时按
        主视图 → 侧栏 / 底栏 → 其它 的优先级让位。
        """
        if self.host._tree is None or self.host._tree.get("preset") != self.host._layout_key():
            self.host._build_work_tree()
        shown = self.host._effective_shown()
        # 记下改尺寸**之前**的外框左上角：期间可能因最小尺寸约束触发隐式 resize，
        # 结束（含动画结束）后按它把位置拉回来，auto-fit 就永远不会搬窗口。
        anchor = self.host._frame_anchor() if self.host.isVisible() else None
        work_w, work_h = self.host._fit_window_to_layout(shown)

        # 开始前放开最小尺寸约束，免得"收起到 0"被顶回来（结束时再设回来）
        self.host._relax_content_min()
        plans = self.host._compute_targets(shown, work_w, work_h)
        for i, (splitter, total, items) in enumerate(plans):
            sizes = self.host._distribute(total, items)
            self.host._set_split_stretch(
                splitter,
                [max(1, int(round(it.get("stretch", 1.0) * 10))) if sizes[k] > 0 else 0
                 for k, it in enumerate(items)])
            last = i == len(plans) - 1
            on_done = None
            if last:
                on_done = (self.host._hold_content_min if anchor is None
                           else lambda a=anchor: self.host._hold_content_min(a))
            self.host._apply_sizes(splitter, sizes, animate, duration, on_done=on_done)
        self.host._sync_panel_chips()
        self.host._sync_header_pads()
        self.host._update_references()

    def _panel_metrics(self) -> dict[str, dict]:
        """三块面板的"自然尺寸"与下限（像素），按当前数据的切片面估算。

        剖面的自然高度沿用 :meth:`_fit_window_to_layout` 里那套口径（每道约 1.15px，夹在
        [300, 880]），宽度按该面的横纵采样数之比还原 —— 于是 72 × 700 这种差得很远
        的两个方向也能得到比例正确的画布。单道波形是一根"扁条"，高度按采样点数走
        （夹在 [150, 260]）；三维取剖面宽度的 42%（夹在 [300, 560]）。
        """
        vol = self.host.vol
        aspect, rows, nt = 1.3, 400.0, 600.0
        if vol is not None:
            mode = self.host.mode or self.host._default_mode(vol)
            if mode == "shot":
                cols, rows = vol.nr, vol.nt
            elif mode == "recv":
                cols, rows = vol.ns, vol.nt
            else:
                cols, rows = vol.nr, vol.ns
            aspect = min(5.0, max(0.2, cols / max(1, rows)))
            nt = float(vol.nt)
        s_nat_h = min(880.0, max(300.0, rows * 1.15))
        s_nat_w = min(1200.0, max(400.0, s_nat_h * aspect))
        # 细长竖面：宽度被 400 下限抬起后，再把高度夹到"宽 / 显示比例下限"，
        # 免得剖面变成 400 × 805 这种竖长条（见 SLICE_MIN_DISPLAY_ASPECT 的说明）。
        s_nat_h = min(s_nat_h, s_nat_w / self.host.SLICE_MIN_DISPLAY_ASPECT)
        # 上面两项是**单幅剖面**的尺寸。对比模式下剖面组里并排 N 幅，整组的自然
        # 宽度必须是 N × 单幅，否则每幅只能拿到 1/N 宽度、画面被拉成竖条 ——
        # “优先保证剖面比例”的规则必须落在每一幅上，而不是整组上。
        n_slice = max(1, len(self.host.panels))
        gutter = (self.host.slice_split.handleWidth() * (n_slice - 1)
                  if getattr(self.host, "slice_split", None) is not None else 0)
        group_nat_w = s_nat_w * n_slice + gutter
        group_min_w = (320.0 if n_slice == 1
                       else max(320.0, 220.0 * n_slice))
        t_nat_h = min(260.0, max(150.0, nt * 0.30))
        r_nat_w = min(560.0, max(300.0, 0.42 * s_nat_w))
        return {
            "slice": {"min_w": group_min_w, "min_h": 180.0, "nat_w": group_nat_w,
                      "nat_h": s_nat_h, "prio": PANEL_PRIORITY["slice"]},
            "trace": {"min_w": 200.0, "min_h": 150.0, "nat_w": 520.0,
                      "nat_h": t_nat_h, "prio": PANEL_PRIORITY["trace"]},
            "right": {"min_w": 300.0, "min_h": 260.0, "nat_w": r_nat_w,
                      "nat_h": min(700.0, max(320.0, s_nat_h)),
                      "prio": PANEL_PRIORITY["right"]},
        }

    @staticmethod
    def _distribute(total: int, items: list[dict]) -> list[int]:
        """按**优先级**分配：先满足优先级高的（尽量给足它的自然尺寸），低的让位。

        每一项是 ``{"min","nat","priority","stretch"}``。需求里的优先级是
        **剖面 > 单道波形 > 三维**：空间不够时先保剖面的尺寸合理，其次单道，
        最后才动三维 —— 所以这里不是"大家按比例各让一点"，而是从高到低依次
        "给到自然尺寸"，剩下的才轮到下一块；``priority=0``（收起的那块）恒为 0。
        但让位有个底线：轮到高优先级那一块时，先给它后面的项扣出**各自的最小尺寸**，
        它自己最多缩到"可用空间 − 其它块的最小尺寸" —— 于是低优先级那块不会被压到
        下限以下（连最小尺寸都放不下时才退回"按优先级 × 最小尺寸"的等比例压缩）。
        分配完还有富余时按自然尺寸比例补回去，免得只剩一块时那块被整幅撑满。
        """
        n = len(items)
        if n == 0:
            return []
        if total <= 0:
            return [0] * n
        mins = [max(0.0, float(it.get("min", 0))) for it in items]
        nats = [max(mins[i], float(items[i].get("nat", 0))) for i in range(n)]
        prio = [max(0.0, float(it.get("priority", 1))) for it in items]
        sizes = [0.0] * n
        avail = float(total)
        floor_of = lambda m: max(64.0, 0.4 * float(m))          # noqa: E731
        order = [i for i in range(n) if prio[i] > 0 or mins[i] > 0]
        order.sort(key=lambda i: -prio[i])
        for pos, i in enumerate(order):
            # 给后面的项留出它们的**最小尺寸**（不再是"很小的可视为值"）：高优先级那块
            # 仍然先拿自然尺寸，但不能把低优先级那块压到它自己的下限以下 —— 实测：
            # 剖面拿满 805 后，底部的单道只剩 67px（连它 150 的最小高度都不到），看着
            # 就像"单道被删了"。改成预留后面各项的最小尺寸后，剖面最多让到
            # "可用空间 − 其它块的最小尺寸"；真的连最小值都塞不下时，下面的
            # "按优先级 × 最小尺寸压缩"分支会兜底。
            rest_floor = sum(mins[j] for j in order[pos + 1:])
            give = min(nats[i], max(floor_of(mins[i]), avail - rest_floor))
            sizes[i] = max(0.0, min(give, max(0.0, avail)))
            avail -= sizes[i]
        if order and avail > 0.5:
            # 有富余（窗口比"自然尺寸总和"还大）→ **只补给优先级最低的那一块**。
            # 这条是为"剖面比例优先"服务的：剖面的自然宽高比是按数据面算的，
            # 把富余塞给它就会被拉变形；塞给三维/单道只是让它们的画面更大，不走形。
            # （只有一块时它无处可让，才会自己吃掉富余。）
            #
            # ``order`` 可能为空：某个子分割器里的项**全被收起**（例如"单道独看"时
            # B 的上排 剖面+三维 两块都被隐藏）→ 没有谁该吃这份富余，直接不补。
            sizes[order[-1]] += avail
        out = [int(round(x)) for x in sizes]
        all_min = sum(mins)
        if all_min > total:
            # 连最小尺寸都放不下 → 按"优先级 × 最小尺寸"压缩：高优先级的仍然拿得多，
            # 而不是简单按最小尺寸平分（那样三维会和剖面拿到一样多）。
            weights = [mins[i] * max(1.0, prio[i]) for i in range(n)]
            wsum = sum(weights) or 1.0
            out = [int(round(total * weights[i] / wsum)) for i in range(n)]
        diff = total - sum(out)
        if diff:
            j = max(range(n), key=lambda i: out[i])
            out[j] = max(0, out[j] + diff)
        return out

    def _compute_targets(self, shown: dict, work_w: int, work_h: int):
        """算出每个分割器的目标尺寸；返回 ``[(splitter, total, items), ...]``（先内后外）。

        被钉住的那块（B 的单道在底栏、A 的三维在右列）位置由树结构定，这里只负责
        给出"可换序那两块"的尺寸；顺序与树里的子控件顺序一致。
        """
        tree = self.host._tree
        m = self.host._panel_metrics()
        W = max(200, int(work_w))
        H = max(150, int(work_h))
        free = tree.get("free")

        def pi(key: str, axis: str, prio_scale: float = 1.0) -> dict:
            """一块面板在某根轴上的分配项（没显示就整项归零，不占空间）。

            ``priority`` 决定"空间不够时谁先让"：剖面 3 > 单道 2 > 三维 1。
            ``stretch`` 决定窗口变大时多出来的尺寸怎么分（沿用同一套优先级）。
            """
            if not shown.get(key):
                return {"min": 0, "nat": 0, "priority": 0, "stretch": 0}
            d = m[key]
            p = PANEL_PRIORITY[key] * prio_scale
            return {"min": d["min_" + axis], "nat": d["nat_" + axis],
                    "priority": p, "stretch": p}

        plans = []
        if free is not None:
            f1, f2 = free
            on = bool(shown.get(f1)) or bool(shown.get(f2))
            if tree["preset"] in ("B", "BT"):         # 上排两块左右 + 单道一栏（BT 则是单道在上）
                a, b = pi(f1, "h"), pi(f2, "h")
                top = {"min": max(a["min"], b["min"]), "nat": max(a["nat"], b["nat"]),
                       "priority": max(a["priority"], b["priority"]), "stretch": 1.0}
                plans.append((tree["inner"], W, [pi(f1, "w"), pi(f2, "w")]))
                if tree["preset"] == "B":
                    plans.append((tree["root"], H, [top, pi("trace", "h")]))
                else:
                    plans.append((tree["root"], H, [pi("trace", "h"), top]))
            else:                                     # 左列两块上下 + 三维一列（AL 则是三维在左）
                a, b = pi(f1, "h"), pi(f2, "h")
                # 左列的自然宽度取**优先级更高那块**的（不是两者的最大值）：否则
                # 单道那 520 的"自然宽"会把窗口撑宽，反过来让剖面比其它摆法下更宽。
                col_nat = (m[(f1 if PANEL_PRIORITY[f1] >= PANEL_PRIORITY[f2] else f2)]
                           ["nat_w"] if on else 0.0)
                col = {"min": float(self.host.WS_CENTER_MIN) if on else 0.0,
                       "nat": col_nat,
                       "priority": max(a["priority"], b["priority"]) if on else 0.0,
                       "stretch": 1.0}
                plans.append((tree["inner"], H, [pi(f1, "h"), pi(f2, "h")]))
                if tree["preset"] == "A":
                    plans.append((tree["root"], W, [col, pi("right", "w")]))
                else:
                    plans.append((tree["root"], W, [pi("right", "w"), col]))
            return plans
        # 两块（或一块）：方向由这一对定，第三块留 0 占位
        axis = "w" if self.host.work_tree.orientation() == QtCore.Qt.Orientation.Horizontal \
            else "h"
        total = W if axis == "w" else H
        plans.append((tree["root"], total,
                      [pi(k, axis) for k in tree["slots"]]))
        return plans

    def _prio_of(self, widget, shown: dict, m: dict) -> float:
        """某个容器（或其子树）里最高的让位优先级 —— 0 表示整棵子树都收起了。"""
        if isinstance(widget, QtWidgets.QSplitter):
            vals = [self.host._prio_of(widget.widget(i), shown, m)
                    for i in range(widget.count())]
            return max(vals) if vals else 0.0
        key = next((k for k, name in self.host._LEAF_OF.items()
                    if getattr(self.host, name, None) is widget), None)
        if key is None or not shown.get(key):
            return 0.0
        return float(m[key].get("prio", 1.0))

    @staticmethod
    def _squeeze_floor(min_size) -> float:
        return max(64.0, 0.4 * float(min_size))

    def _extent_along(self, widget, horiz: bool, shown: dict, m: dict,
                      key_name: str) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的"自然"/"最小"尺寸。

        沿**分割器自己的方向**相加（横排一行宽 = 各列之和）；**垂直方向不取最大值，
        而是取"优先级最高的那一块"的尺寸** —— 这是"剖面优先"的关键一环：
        低优先级面板（单道/三维）不该把窗口撑大，它宁可自己被压窄，也不能让剖面
        的尺寸随别块开不开而变化。
        """
        if isinstance(widget, QtWidgets.QSplitter):
            same = ((widget.orientation() == QtCore.Qt.Orientation.Horizontal)
                    == bool(horiz))
            kids = [widget.widget(i) for i in range(widget.count())]
            vals = [self.host._extent_along(k, horiz, shown, m, key_name) for k in kids]
            if not vals:
                return 0.0
            if same:
                return sum(vals) + widget.handleWidth() * (len(vals) - 1)
            best = max(((self.host._prio_of(k, shown, m), v) for k, v in zip(kids, vals)),
                       key=lambda pv: (pv[0], pv[1]), default=(0.0, 0.0))
            return best[1]
        key = next((k for k, name in self.host._LEAF_OF.items()
                    if getattr(self.host, name, None) is widget), None)
        if key is None or not shown.get(key):
            return 0.0
        axis = "w" if horiz else "h"
        return m[key][f"{key_name}_{axis}"]

    def _min_along(self, widget, horiz: bool, shown: dict, m: dict) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的最小尺寸。"""
        return self.host._extent_along(widget, horiz, shown, m, "min")

    def _natural_along(self, widget, horiz: bool, shown: dict, m: dict) -> float:
        """某块容器（或包着它的子分割器）在指定轴上的**自然**尺寸（按数据规模估）。"""
        return self.host._extent_along(widget, horiz, shown, m, "nat")

    def _relax_content_min(self) -> None:
        """动画前放开所有最小尺寸：动画要能把任意一块压到 0。"""
        for sp in self.host._tree_splitters:
            sp.setMinimumWidth(0)
            sp.setMinimumHeight(0)
        for name in self.host._LEAF_OF.values():
            w = getattr(self.host, name, None)
            if w is not None:
                w.setMinimumWidth(0)
                w.setMinimumHeight(0)

    def _hold_content_min(self, anchor: QtCore.QPoint | None = None) -> None:
        """动画结束后设"静止最小尺寸"，让用户拖分割器把手时不会把某块压没。

        空间本来就塞不下时**不设**约束 —— 否则最小尺寸之和超过容器，会被裁掉一块；
        那时退回"按比例挤压"的旧行为，至少不出错。

        ``anchor`` 非空时顺带把外框左上角拉回去：设最小尺寸可能触发一次隐式 resize，
        位置会跟着挪一个边框宽度。
        """
        if self.host._tree is None:
            self.host._restore_anchor(anchor)
            return
        shown = self.host._effective_shown()
        # 这里给的是**可视为下限**（不是各块的最小尺寸）：分配器是按优先级把自然尺寸
        # 给足高优先级那块、低优先级那块吃剩下的；如果这里再把"最小尺寸"设成硬下限，
        # splitter 会把低优先级那块顶回去，高优先级那块就又被挤小了 —— 剖面的大小
        # 就又会随别的面板开不开而变。所以下限统一取"很小的可视为值"。
        raw = self.host._panel_metrics()
        m = {k: {**v,
                 "min_w": max(64.0, 0.4 * v["min_w"]),
                 "min_h": max(64.0, 0.4 * v["min_h"])}
             for k, v in raw.items()}

        def walk(sp: QtWidgets.QSplitter) -> None:
            horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
            kids = [sp.widget(i) for i in range(sp.count())]
            mins = [self.host._min_along(k, horiz, shown, m) for k in kids]
            need = sum(mins) + sp.handleWidth() * max(0, len(kids) - 1)
            total = sp.width() if horiz else sp.height()
            fits = total >= need
            for child, base in zip(kids, mins):
                if isinstance(child, QtWidgets.QSplitter):
                    walk(child)
                if horiz:
                    child.setMinimumHeight(0)
                    child.setMinimumWidth(int(base) if fits else 0)
                else:
                    child.setMinimumWidth(0)
                    child.setMinimumHeight(int(base) if fits else 0)
        walk(self.host.work_tree)
        self.host._restore_anchor(anchor)

    def _fit_window_to_layout(self, shown: dict) -> tuple[int, int]:
        """**总窗口尺寸跟着当前排版走**；返回分配用的工作区尺寸 ``(W, H)``。

        为什么需要这一步：窗口如果只在"导入数据那一刻"定一次尺寸，之后无论切到
        单块、还是换成别的摆法，窗口都不动 —— 于是三块只能被硬撑进原来的框里，
        宽高比常常离数据的自然比例很远，看着就是"不合理地拉伸"。

        这里改成：每当**面板组合变化**（独看 / 开关一块 / 换摆法 / 换主视图 / 换数据）
        都按当前这棵树，把每块的**自然尺寸**沿轴相加（同 :meth:`_natural_along` 的口径），
        得到一个"刚好合适"的窗口尺寸，再夹进 ``[MIN_SIZE, 屏幕可用区]``。
        与旧版最大的区别是**它也会变小** —— 关掉一块时窗口就收回去，而不是留下空白
        把剩下的块拉变形。

        两条保险：窗口设置里可以关掉这个行为（关掉后退回"只放大"）；用户手动 resize
        过的尺寸成为**锚点**（``_user_size``），换构图只在空间不足时扩容、不主动缩小 ——
        于是"调好的大小"不会因为切一趟别的视图就丢掉。
        """
        if self.host._tree is None or self.host.work_tree is None or not self.host.datasets:
            # 还没有数据时不自作聪明改窗口尺寸：这时三块的"自然尺寸"全是默认值，
            # 算出来只会把开场窗口改小，没有意义。
            return (int(self.host.work_host.width()), int(self.host.work_host.height()))
        m = self.host._panel_metrics()
        # 窗口只按**剖面与单道**的自然尺寸长：三维不拿自然尺寸、只占它的最小值 ——
        # 这正是"剖面 > 单道 > 三维"的优先级：三维不该把窗口撑大。
        mw = {k: dict(v) for k, v in m.items()}
        mw["right"]["nat_w"] = mw["right"]["min_w"]
        mw["right"]["nat_h"] = mw["right"]["min_h"]
        want_w = max(self.host._natural_along(self.host.work_tree, True, shown, mw),
                     self.host._min_along(self.host.work_tree, True, shown, m))
        want_h = max(self.host._natural_along(self.host.work_tree, False, shown, mw),
                     self.host._min_along(self.host.work_tree, False, shown, m))
        left_w = (self.host.left_wrap.width() if self.host._region_shown.get("left", True)
                  else self.host.LEFT_RAIL_W)
        # 边框开销用**实测值**：窗口尺寸减掉"左栏 + 工作区"剩下的那部分（外边距与手柄）。
        # 写死的估值差几十像素，会让面板被多出来的那截拉伸 —— 正是"适配数据形状没保持住"
        # 的来源。注意这里**不能再把左栏算进去**（上面已经单独加了 left_w）。
        cw, ch = self.host.CHROME_W, self.host.CHROME_H
        if self.host.work_host.width() > 1 and self.host.width() > self.host.work_host.width():
            cw = max(0.0, float(self.host.width() - self.host.work_host.width() - left_w))
        if self.host.work_host.height() > 1 and self.host.height() > self.host.work_host.height():
            ch = float(self.host.height() - self.host.work_host.height())
        # 当前构图**真正放不下**时的最小窗口（只用于用户尺寸锚的扩容判断）
        min_w = left_w + self.host._min_along(self.host.work_tree, True, shown, m) + cw
        min_h = self.host._min_along(self.host.work_tree, False, shown, m) + ch

        if self.host._user_size is not None:
            # 用户手动调过尺寸：它成为锚点，换构图**不主动缩小**；只有这个构图
            # 连最小尺寸都放不下时才扩容。
            win_w = max(float(self.host._user_size[0]), min_w)
            win_h = max(float(self.host._user_size[1]), min_h)
            if not self.host._follow_layout:
                win_w = max(win_w, float(self.host.width()))
                win_h = max(win_h, float(self.host.height()))
        else:
            win_w = left_w + want_w + cw
            win_h = want_h + ch
            if not self.host._follow_layout:
                # 关掉"跟随排版"就退回旧行为：只要不小于现在，绝不缩回去
                win_w = max(win_w, float(self.host.width()))
                win_h = max(win_h, float(self.host.height()))

        screen = self.host.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            win_w = min(win_w, avail.width() * 0.96)
            win_h = min(win_h, avail.height() * 0.94)
        win_w = max(win_w, float(self.host.MIN_SIZE[0]))
        win_h = max(win_h, float(self.host.MIN_SIZE[1]))

        # 全屏 / 最大化下**只重排 splitter，绝不 setGeometry**：否则会退出全屏
        if self.host.isFullScreen() or self.host.isMaximized():
            self.host._window_target = None
            return (max(60, int(self.host.work_host.width())),
                    max(60, int(self.host.work_host.height())))

        self.host._window_target = (int(win_w), int(win_h))

        # **拖动中不改窗口尺寸**：挤占会改变"实际可见集合"，而窗口尺寸又是跟着它算的
        # —— 一改尺寸，工作区几何（以及判定区域）就跟着动，光标相对位置随之变化、意图
        # 来回翻，看上去就是面板在莫名其妙地抖。拖动期间把窗口钉住，只让 splitter 在
        # 窗口内部重新分配；松手后（`_drag` 已清空）再一次性丝滑变成最终尺寸。
        if self.host._is_dragging_active():
            return (max(60, int(self.host.work_host.width())),
                    max(60, int(self.host.work_host.height())))
        if not self.host._suppress_window_resize and self.host.isVisible() \
                and self.host.work_tree.width() > 1 \
                and self.host._size_changed_enough(win_w, win_h):
            # 只改尺寸、不搬窗口（见 _resize_keeping_anchor）：位置永远由用户说了算
            self.host._resize_keeping_anchor(int(win_w), int(win_h))
            self.host._ensure_on_screen()           # 调完别越过屏幕边缘
        # 分配用的工作区尺寸：按"要改成多大"解析地算，而不是读刚 resize 还没走布局的
        # 控件尺寸 —— 否则这一帧会按老尺寸排，看着就是"先跳一下、再重排一次"。
        return (max(60, int(win_w - left_w - cw)), max(60, int(win_h - ch)))

    def _is_dragging_active(self) -> bool:
        """是否正处在一次真正的拖动中 —— 用来冻结窗口尺寸（见 :meth:`_fit_window_to_layout`）。

        拿起那一刻 ``freeze`` 还是 ``False``：让"归位"能**改这一次**窗口尺寸；随后置 ``True``，
        到松手前窗口尺寸恒定，挤占只在窗口内部发生（否则"挤占改变可见集合 → 窗口尺寸跟着算 →
        几何/判定区域跟着动 → 意图翻转"，看上去就是面板在抖）。
        """
        d = getattr(self.host, "_drag", None)
        return bool(d and d.get("active") and d.get("freeze"))

    def _animate_layout_change(self) -> None:
        """换摆法 / 换先后时的"丝滑"过渡：让**总窗口**从旧尺寸滑到新尺寸。

        摆法一换，splitter 的树结构就变了 —— "哪块在左、哪块在底"是结构决定的，
        这一段没法靠补间变形过去（除非把面板搬来搬去，那会丢掉三维的 GL 上下文）。
        但窗口尺寸可以：面板在窗口里是按伸缩因子等比例铺开的，窗口从旧尺寸滑到新
        尺寸时整幅画面一起"呼吸"，就不会出现"内容先跳一下、窗口再跟上"的错位感。
        """
        if self.host.isFullScreen() or self.host.isMaximized():
            return                      # 全屏下只重排 splitter，绝不改窗口 geometry
        target = getattr(self.host, "_window_target", None)
        if target is None or not self.host.isVisible():
            return
        if self.host._is_dragging_active():
            return                      # 拖动中钉住窗口尺寸（见 _fit_window_to_layout）
        tw, th = target
        if abs(tw - self.host.width()) < 8 and abs(th - self.host.height()) < 8:
            return
        self.host._stop_layout_anim()
        # 终值也用**外框锚点**算：不能用 self.host.x()/self.host.y()（客户区坐标）——
        # 尺寸一变 Qt 就重算外框偏移，拿客户区坐标当落点会让外框每轮挪一个边框宽度。
        anchor, off = self.host._frame_anchor(), self.host._client_offset()
        anim = QtCore.QPropertyAnimation(self.host, b"geometry", self.host)
        anim.setDuration(self.host.LAYOUT_ANIM_MS)
        anim.setStartValue(self.host.geometry())
        anim.setEndValue(QtCore.QRect(anchor.x() + off.x(), anchor.y() + off.y(),
                                      tw, th))
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.finished.connect(self.host._ensure_on_screen)
        self.host._layout_anim = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_layout_anim(self) -> None:
        anim = getattr(self.host, "_layout_anim", None)
        self.host._layout_anim = None
        if anim is None:
            return
        try:
            if anim.state() == QtCore.QAbstractAnimation.State.Running:
                anim.stop()
        except RuntimeError:                   # DeleteWhenStopped 已经把对象删了
            pass

    def _window_anim_running(self) -> bool:
        """总窗口的尺寸动画是否还在跑（动画帧不该写入用户尺寸锚）。"""
        anim = getattr(self.host, "_layout_anim", None)
        if anim is None:
            return False
        try:
            return anim.state() == QtCore.QAbstractAnimation.State.Running
        except RuntimeError:                   # pragma: no cover
            return False

    def _size_changed_enough(self, win_w: float, win_h: float) -> bool:
        """尺寸变化超过 3% 或 20px 才真的去改窗口 —— 否则每帧微调会让窗口抖。"""
        return (abs(win_w - self.host.width()) > max(20.0, self.host.width() * 0.03)
                or abs(win_h - self.host.height()) > max(20.0, self.host.height() * 0.03))

    def _layout_animating(self) -> bool:
        """两处 splitter 上是否还有尺寸动画在跑（避免窗口 resize 与动画互相打架）。"""
        for anim in list(self.host._size_anims.values()):
            try:
                if anim.state() == QtCore.QAbstractAnimation.State.Running:
                    return True
            except RuntimeError:                 # DeleteWhenStopped 已经把对象删了
                pass
        return False

    @staticmethod
    def _set_split_stretch(splitter: QtWidgets.QSplitter, weights: list[int]) -> None:
        for i, w in enumerate(weights[:splitter.count()]):
            splitter.setStretchFactor(i, int(w))

    @staticmethod
    def _total(splitter: QtWidgets.QSplitter) -> int:
        return max(1, sum(splitter.sizes()))

    def _apply_sizes(self, splitter: QtWidgets.QSplitter, target: list[int],
                     animate: bool, duration: int = 190, on_done=None) -> None:
        """把 splitter 的尺寸切到目标值；``animate`` 时用缓动插值滑过去。

        动画期间每一帧都调 ``setSizes``，所以剖面会跟着重绘 —— 抽稀之后的图足够快，
        不存在卡顿。动画结束把最终尺寸**钉死**一次（同时跑 ``on_done``，用来恢复
        展开后的 min/max 约束），避免最后一帧的取整误差留下一个悬空的把手。
        """
        n = splitter.count()
        if n == 0:
            if on_done is not None:
                on_done()
            return
        target = (list(target) + [0] * n)[:n]
        self.host._stop_size_anim(splitter)
        if not animate:
            splitter.setSizes(target)
            if on_done is not None:
                on_done()
            return
        start = (list(splitter.sizes()) + [0] * n)[:n]
        if start == target:
            splitter.setSizes(target)
            if on_done is not None:
                on_done()
            return

        def _finish(sp=splitter, t=target, cb=on_done):
            if not _qt_valid(sp):              # 旧 splitter 已被换摆法销毁
                return
            sp.setSizes(list(t))
            if cb is not None:
                cb()

        def _frame(v, sp=splitter, s=start, t=target):
            if not _qt_valid(sp):
                return
            sp.setSizes([int(round(a + (b - a) * float(v)))
                         for a, b in zip(s, t)])

        anim = QtCore.QVariantAnimation(self.host)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.valueChanged.connect(_frame)
        anim.finished.connect(_finish)
        self.host._size_anims[id(splitter)] = anim
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _stop_all_size_anims(self) -> None:
        """换树 / 清空数据前停掉所有 splitter 尺寸动画（它们的目标可能马上被销毁）。"""
        for anim in list(self.host._size_anims.values()):
            try:
                anim.stop()
            except RuntimeError:               # pragma: no cover
                pass
        self.host._size_anims.clear()

    def _stop_size_anim(self, splitter: QtWidgets.QSplitter) -> None:
        """掐掉同一根 splitter 上还没跑完的上一轮动画，免得两批动画互相抢。"""
        anim = self.host._size_anims.pop(id(splitter), None)
        if anim is None:
            return
        try:
            anim.stop()
        except RuntimeError:                       # pragma: no cover
            pass                                   # DeleteWhenStopped 已经把对象删了

    def _rebuild_slice_panels(self) -> None:
        """按当前数据份数调整中间的剖面面板：够用的**复用**，多出来的才新建。

        复用而不是每次重建：重建会让每块剖面视图（连同它的视野、提示线）重新
        初始化一遍，载入数据时看上去就是"剖面里的绘图抖了一下"。
        面板通过 ``slot`` 记住自己对应第几份数据 —— 移除中间某份数据时下标会整体
        前移，回调必须按当期下标取，而不是创建时捕获的那个。

        每块面板外面再套一个**容器**：面板被拉到独立窗口时，容器留在 splitter 里
        占住位置（压成 0 宽），这样剩下几块的下标与顺序都不会乱。
        """
        while len(self.host.panels) > len(self.host.datasets):
            panel = self.host.panels.pop()
            holder = self.host.panel_holders.pop()
            self.host._close_detached(panel, silent=True)     # 先收回，免得连窗口一起删掉
            panel.setParent(None)
            holder.setParent(None)
            panel.deleteLater()
            holder.deleteLater()
        while len(self.host.panels) < len(self.host.datasets):
            holder = QtWidgets.QWidget()
            hl = QtWidgets.QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            panel = SlicePanel()
            panel.slot = 0
            panel.picked.connect(lambda c, r, p=panel: self.host._on_pick(p.slot, c, r))
            panel.hovered.connect(lambda c, r, p=panel: self.host._on_hover(p.slot, c, r))
            panel.view.referenceDragged.connect(
                lambda c, p=panel: self.host._on_reference_drag(p.slot, c))
            panel.view.traceStepped.connect(
                lambda d, p=panel: self.host._on_trace_step(p.slot, d))
            # 双击复位：第一次 release 可能已经误取道，这里把那次变化撤回去
            panel.view.doubleClicked.connect(
                lambda p=panel: self.host._on_view_double_click(p.slot))
            # 拖动统一挂到主窗口这一处实现（拉出为独立窗口 / 拖到另一块上换序）
            self.host._watch_drag(panel.header, panel)
            # 这里**故意不给**剖面面板挂 tooltip：鼠标一停在地震画面上就会冒出一块
            # 半透明提示挡住波形，是纯粹的干扰。操作提示改挂在剖面区域的标题行上
            # （"剖面"那行），要看的时候才看。
            hl.addWidget(panel)
            self.host.slice_split.addWidget(holder)
            self.host.panels.append(panel)
            self.host.panel_holders.append(holder)
        for k, panel in enumerate(self.host.panels):
            panel.slot = k
            self.host.slice_split.setStretchFactor(k, 1)
        if self.host.panels:
            # 显式给一次等分尺寸：不依赖之后某个时机才发生的布局遍历，
            # 免得"先空一帧再出现"看着像闪一下
            self.host.slice_split.setSizes([1] * len(self.host.panels))
        self.host._sync_empty_hint()

    def _sync_empty_hint(self) -> None:
        """没有数据时把剖面区换成引导文字（有数据时换回真正的剖面）。"""
        empty = not self.host.panels
        self.host.slice_empty.setVisible(empty)
        self.host.slice_split.setVisible(not empty)

    def _top_right_owner(self) -> str | None:
        """工作区**右上角**那块面板是谁 —— 悬浮胶囊压在它上面，标题行要给它让位。

        三块构图按"钉住的是谁、在哪个方向"直接查表（``tree["slots"]`` 的前两块就是
        树里真正的先后）：
          * B  → 上排的右边那块（单道收起时上排会顶到最上，仍是它）
          * BT → 顶部通栏的单道
          * A  → 右列的三维
          * AL → 右列的上面那块
        两块 / 一块时退回按树的朝向取"最右"或"最上"。
        """
        if self.host._tree is None:
            return None
        shown = self.host._effective_shown()
        slots = self.host._tree["slots"]
        if not any(shown.get(k) for k in slots):
            return None
        if self.host._tree.get("inner") is not None and len(slots) >= 3:
            f1, f2 = slots[0], slots[1]
            cands = {"B": (f2, f1, "trace"), "BT": ("trace", f2, f1),
                     "A": ("right", f1, f2), "AL": (f1, f2, "right")}.get(
                         self.host._tree["preset"])
            if cands:
                for cand in cands:
                    if cand and shown.get(cand):
                        return cand
                return None
        if self.host.work_tree.orientation() == QtCore.Qt.Orientation.Horizontal:
            for k in reversed(slots):           # 左右排 → 最右那块
                if shown.get(k):
                    return k
        else:
            for k in slots:                     # 上下排 → 最上面那块
                if shown.get(k):
                    return k
        return None

    def _sync_header_pads(self) -> None:
        """给右上角那块面板的标题行在右端留出胶囊的宽度。

        胶囊是浮层（不进布局、不占高度），所以它会压住右上角那块面板的标题行 ——
        标题行右端的内容（比如单道的道号读数）必须让开，否则会被盖住看不全。
        """
        if not getattr(self.host, "_head_pads", None):
            return
        pad = 0
        cap = getattr(self.host, "capsule", None)
        if cap is not None:
            pad = int(max(cap.width(), cap.sizeHint().width()) + 2 * WORKSPACE_MARGIN)
        owner = self.host._top_right_owner()
        for key, item in self.host._head_pads.items():
            item.changeSize(pad if key == owner else 0, 0,
                            QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Minimum)

    def _effective_shown(self) -> dict[str, bool]:
        """当前工作区里**实际**还剩哪些面板要看。

        ``_content_shown`` 是"开关"（面板被拖到独立窗口里仍然算开着），这里再看一层
        几何：被拖走的那块，它的槽位要让出来给别的面板。

        拖动中还叠了两份**瞬时**状态（见 ``__init__``）：正在被拖的那块当作"不在窗口里"
        （剩下几块立刻按预设铺满），落位命中的那块当作"已经停靠"（把槽位先占出来画预览）。
        """
        drag = self.host._drag_vis
        dock = self.host._preview_dock
        # 剖面是一个整体：只有整组被拉到独立窗口时才让出主窗口里的槽位
        slice_on = (self.host._content_shown["slice"]
                    and not self.host._is_detached(self.host.slice_wrap))
        return {"slice": (slice_on or "slice" in dock) and "slice" not in drag,
                "trace": ((self.host._content_shown["trace"]
                           and not self.host._is_detached(self.host.trace_frame))
                          or "trace" in dock) and "trace" not in drag,
                "right": ((self.host._content_shown["right"]
                           and not self.host._is_detached(self.host.right_frame))
                          or "right" in dock) and "right" not in drag}

    def _freeze_content_width(self, width: int | None) -> None:
        """侧边栏动画期间把内容区宽度钉住：宽度不变 → 内部不重排，只做裁剪。

        这是"滑出去"能顺的关键 —— 不然每一帧宽度都在变，里面几百个控件要跟着
        重排一遍，还会连带改摘要标签的省略长度。``None`` 表示解冻。
        """
        content = self.host.left_content
        if width is None:
            content.setMinimumWidth(0)
            content.setMaximumWidth(16777215)
        else:
            content.setFixedWidth(max(0, int(width)))

    def _swap_main(self) -> None:
        """「⇄」：把"可换序那两块"的先后对调。

        语义固定、不看当前摆法：三块 B 里是**上排的剖面 ↔ 三维**，三块 A 里是
        **左列的剖面 ↔ 单道**，两块时就是这两块。钉住的那块（B 的单道在底栏、
        A 的三维在右列）不参与，所以"单道永远在底、三维永远在右"不会被打乱。
        """
        if len(self.host._pair_order) < 2:
            self.host.status.setText("没有可交换的面板。")
            return
        f1, f2 = self.host._pair_order
        self.host._pair_order = [f2, f1]
        self.host._suppress_window_resize = True
        try:
            self._build_work_tree()
            self._relayout_content(animate=False)
        finally:
            self.host._suppress_window_resize = False
        self._animate_layout_change()
        self.host.status.setText(
            f"已交换先后：现在是「{PANEL_LABELS[f2]}」在前、"
            f"「{PANEL_LABELS[f1]}」在后。")
