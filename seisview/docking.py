"""面板拖动与浮窗：拖动识别、贴边落位、换序、拉出/收回独立窗口。"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .layout_config import EDGE_FRAC, GROUP_OF, PANEL_ORDER
from .view2d import SlicePanel
from .widgets import DragLayer, FloatingPanel, pair_layout


class DockingController:
    """把标题行拖动翻译成布局动作；真实面板仍是宿主的控件。"""

    def __init__(self, host) -> None:
        self.host = host

    def _is_detached(self, widget) -> bool:
        return widget in self.host._detached

    def _watch_drag(self, header: QtWidgets.QWidget, target: QtWidgets.QWidget) -> None:
        """给某块面板的标题行挂上拖动监听（``target`` 是被拖走的那个控件）。"""
        header.installEventFilter(self.host)
        header.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.host._drag_watch[header] = target

    def _toggle_float_maximized(self, target) -> bool:
        """双击浮窗标题栏 = 全屏 / 还原（与右上角那颗「全屏」按钮同一个动作）。

        Qt 的 FramelessWindowHint 把系统标题栏去掉了，这个习惯动作得自己补；而我们自己
        拖动的路径下标题栏是 HTCLIENT，系统也不会替我们处理双击。
        **用自己实现的全屏，不用系统的最大化**：系统最大化会给"可缩放的无边框窗口"
        补一圈系统边框条（顶部那条偏宽的白条就是它），全屏则一点边都不带。
        返回 ``True`` 表示这次双击被处理掉了。
        """
        win = self.host._detached.get(target)
        if win is None:
            return False
        # 双击的第一次按下已经起了一次拖动（`_drag`），这里必须把它作废：否则紧跟着的
        # 松手会走 `_finish_drag`，而全屏后的浮窗覆盖在主窗口上 → 被误判成"拖回主窗口"
        # 直接收回去。
        self.host._drag = None
        win.toggle_fullscreen()
        self.host.status.setText("浮窗已退出全屏。" if not win.isFullScreen()
                           else "浮窗已全屏（再双击标题栏或点右上角按钮退出）。")
        return True

    def _drag_kind(self, target) -> str:
        if target is self.host.slice_wrap:
            return "slice"
        if isinstance(target, SlicePanel):
            return "slice"
        if target is self.host.trace_frame:
            return "trace"
        if target is self.host.right_frame:
            return "right"
        return "slice"

    def _begin_drag(self, header, target, pos: QtCore.QPoint, modifiers=0) -> bool:
        """开始一次拖动；返回 ``True`` 表示这次按下已经交给系统（不再走我们的拖动）。

        **Alt + 拖浮窗标题栏 = 交给 Windows 做原生拖动**：只有这样才拿得到 Aero Snap
        （拖到屏幕边分屏）、拖到顶部最大化，以及随后可用的 Win+方向键 / Snap Layouts。
        代价是原生拖动期间 Windows 跑自己的模态移动循环，Qt 收不到鼠标移动事件，所以
        这条路径下**没有实时落位预览**；默认（不按 Alt）仍然是我们自己的拖动，预览照旧。
        """
        win = self.host._detached.get(target)
        if win is not None and modifiers & QtCore.Qt.KeyboardModifier.AltModifier:
            handle = win.windowHandle()
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        self.host.status.setText("原生拖动中。")
                        return True
                except Exception:
                    pass                       # 平台不支持就退回我们自己的拖动
        # 记下**按下那一刻**的尺寸：面板一"离手"就隐藏，它的槽位会被邻居吃掉，
        # 松手时再读宽度已经不是用户看到的那块大小了。
        wrap = getattr(self.host, "workspace", None)
        if wrap is not None:
            wrap.show_drop_preview(None)   # 上一次拖动万一没收干净（松手事件丢了），兜一下
        self.host._preview_state = None         # 上一次拖动的预览状态不许影响这一次
        self.host._preview_cap = None
        self.host._zone_frozen = None
        kind = self.host._drag_kind(target)
        # 剖面有两种手势：
        #   · 组标题（slice_wrap）→ 整块移动 / 拉出 / 换分屏；
        #   · 单图标题（SlicePanel）→ 只在对比模式交换数据顺序，绝不拉出。
        group = target is self.host.slice_wrap
        reorder_only = isinstance(target, SlicePanel)
        slice_sizes = (list(self.host.slice_split.sizes())
                       if reorder_only and len(self.host.panels) > 1 else None)
        self.host._drag = {"header": header, "target": target, "press": pos,
                      "size": target.size(), "slice_sizes": slice_sizes,
                      "window": win, "active": False, "group": group,
                      "reorder_only": reorder_only,
                      "freeze": False, "blocked": False,
                      "offset": None, "intent": None,
                      "layer": None, "ghost": None}
        return False

    def _move_drag(self, pos: QtCore.QPoint) -> None:
        d = self.host._drag
        if d is None:
            return
        if not d["active"]:
            if (pos - d["press"]).manhattanLength() <= self.host._DRAG_SLOP:
                return
            kind = self.host._drag_kind(d["target"])
            if d.get("reorder_only") and len(self.host.panels) <= 1:
                if not d.get("blocked"):
                    d["blocked"] = True
                    self.host.status.setText("单幅剖面不能拖出。")
                return
            # 工作区只剩它这一块时**不允许拖走**（松手回原位）：拖出去会变成空工作区，
            # "让位"也没有别的块可铺。浮窗（本来就在窗外）不受这条限制 —— 拖回来才是它的用途。
            # 对比换序不涉及“把块拖走”，所以不适用这条限制。
            if (d["window"] is None and not d.get("reorder_only")
                    and not self.host._visible_excluding(kind)):
                if not d.get("blocked"):
                    d["blocked"] = True
                    self.host.status.setText("工作区只剩这一块，不能拖出。")
                return
            d["active"] = True
            d["freeze"] = False       # 拿起这一次先不冻结窗口：让"归位"能改一次尺寸
            d["header"].setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            self.host._zone_frozen = None  # 判定基准等"归位"落定后再冻结（见 _zone_side_at）
            if d["window"] is not None:
                d["offset"] = pos - d["window"].frameGeometry().topLeft()
                d["freeze"] = True
            else:
                d["offset"] = pos - d["target"].mapToGlobal(QtCore.QPoint(0, 0))
                # 先抓快照（此时槽位还没变），再让它**立刻让位**（顺带按预设改一次窗口尺寸）
                self.host._open_drag_layer(d)
                self.host._enter_drag_layout(kind)
                d["freeze"] = True    # 此后到松手前窗口尺寸恒定，挤占只在内部发生

        # 已经在独立窗口里的面板：拖动就是搬窗口；同时照样算落位（拖回主窗口就会收回）。
        # 以前这里直接 return，于是"拖回时没有亮线指引、落点也不生效"。
        if d["window"] is not None:
            d["window"].move(pos - d["offset"])
            self.host._update_drop_hint(pos, d, exclude=None)
            return

        if d["layer"] is not None:
            d["layer"].move(pos - d["offset"])
        self.host._update_drop_hint(pos, d, exclude=d["target"])

    def _update_drop_hint(self, pos: QtCore.QPoint, d: dict, exclude) -> None:
        """按光标位置算出"松手会发生什么"，并把工作区**预先挤占好**、画出落位预览。

        拖窗内面板与拖浮窗走的是**同一套**判定，所以看到什么、松手就是什么。
        """
        kind = self.host._drag_kind(d["target"])
        intent = self.host._drop_intent_at(
            pos, kind, exclude,
            group=bool(d.get("group")), reorder=bool(d.get("reorder_only")))
        d["intent"] = intent
        self.host._apply_drag_preview(kind, intent)

    def _drag_is_reorder(self) -> bool:
        """这次拖动是不是"对比模式下换数据顺序"（拖的是组内某幅剖面）。

        组标题的拖动不算换序：它移动的是整个剖面区域。换序时工作区**不该让位**：
        剖面组还在（别的剖面板占着它的位置），换的只是数据顺序 —— 让位会把整个
        剖面组抽掉，光标底下的目标块跟着跑，判定就全乱了。
        """
        d = self.host._drag
        return bool(d and d.get("reorder_only") and len(self.host.panels) > 1)

    def _enter_drag_layout(self, kind: str) -> None:
        """面板一"离手"就**立刻让位**：当作它已经不在窗口里，剩下几块按预设铺满。

        这就是需求里的"窗口内剩余界面自动按预设填充空间、不再保留占位"：原来那块原位
        会留一个虚线占位框（GhostSlot），现在是它的槽位直接消失、邻居立刻吃掉。
        """
        if self.host._drag_is_reorder():
            return
        self.host._drag_vis.add(kind)
        self.host._preview_dock.discard(kind)
        self.host._preview_state = None
        self.host._preview_cap = None
        self.host._sync_layout_for_count(force_default=False)

    def _clear_drag_layout(self, relayout: bool = True) -> None:
        """拖动结束：清掉瞬时的"让位 / 预览停靠"状态（构图由后续落位决定）。

        ``relayout=False`` 用于"马上还要落一次最终构图"的路径，免得先按中间态多排一次。
        """
        wrap = getattr(self.host, "workspace", None)
        if wrap is not None:
            wrap.show_drop_preview(None)       # **一定要收掉蓝色感应区**（否则会赖着不走）
        self.host._zone_frozen = None
        if not (self.host._drag_vis or self.host._preview_dock):
            return
        self.host._drag_vis.clear()
        self.host._preview_dock.clear()
        self.host._preview_state = None
        self.host._preview_cap = None
        if relayout:
            self.host._sync_layout_for_count(force_default=False)

    def _apply_drag_preview(self, kind: str, intent: dict | None) -> None:
        """**实时挤占**：命中落位时，工作区先摆成"松手之后的样子"。

        规则（对应需求里的分类讨论）：
          * 被拖那块当作**已经停靠**，先按结果构图把树建好；
          * "含被拖槽位的那根 splitter"强制成 **1/3 : 2/3**（被拖的那格占三分之一，按判定侧）；
          * 另一根 splitter 恢复"让位态"里的实际尺寸 —— 于是插剖面时单道尺寸位置真的不动，
            插单道 / 三维时其余两块作为整体只被压缩一个方向；
          * 蓝色感应区 = 那块 1/3（由冻结的判定轴 / 区域直接算出，不依赖实时几何）。
        没命中落位时退回"让位"状态（剩下几块铺满）。状态没变就直接返回 ——
        拖动中每一帧都重排会卡。
        """
        wrap = getattr(self.host, "workspace", None)
        if self.host._drag_is_reorder():
            # 对比模式换数据顺序：**不让位**，只用面板上的高亮条提示目标块
            if wrap is not None:
                wrap.show_drop_preview(None)
            other = intent.get("panel") if intent else None
            for p in self.host.panels:
                self.host._highlight_panel(p, p is other,
                                      intent.get("zone") if other else None)
            return
        target = intent.get("target") if intent else None
        side = intent.get("side") if intent else None
        state = (kind, target, side)
        if state == self.host._preview_state:
            return
        self.host._preview_state = state
        # 挤占前先量下"让位态"各块的实际尺寸：命中落位时，不该动的那几块要按它恢复。
        # 只量一次（首次命中时布局已落定，见 _zone_side_at），之后来回换侧都用这份 ——
        # 否则每次换侧都从"正在挤压的中间态"再量一次，几轮下来尺寸会漂。
        if target is None:
            self.host._preview_cap = None
        elif self.host._preview_cap is None:
            self.host._preview_cap = {k: (h.width(), h.height())
                                 for k, h in self.host._leaf_widgets().items()}
        cap = self.host._preview_cap or {}
        if target is None:
            # 没命中落位（含"拖到某块剖面上换数据顺序"）：退回让位状态
            self.host._preview_dock.discard(kind)
            self.host._drag_vis.add(kind)
            if wrap is not None:
                wrap.show_drop_preview(None)
        else:
            preset, first = target
            self.host._drag_vis.discard(kind)
            self.host._preview_dock.add(kind)
            self.host._content_shown[kind] = True
            if GROUP_OF.get(preset, 0) >= 3:
                self.host._layout_preset = preset
            self.host._align_pair_order(first)
        self.host._sync_layout_for_count(force_default=False)
        if target is not None:
            self.host._squeeze_drag_preview(kind, cap)
        if wrap is not None:
            wrap.show_drop_preview(self.host._preview_rect_for_drag(kind, intent))
        other = intent.get("panel") if intent else None
        for p in self.host.panels:
            self.host._highlight_panel(p, p is other, intent.get("zone") if other else None)

    def _squeeze_drag_preview(self, kind: str, cap: dict) -> None:
        """占位预览的挤占（见 :meth:`_apply_drag_preview`）。

        * 含被拖槽位的那根 splitter：按判定轴强制 1/3 : 2/3，被拖那格占三分之一；
        * 另一根 splitter：保持"让位态"的实际尺寸（``cap`` 是挤占前量下来的各块宽高）。
        """
        tree = self.host._tree
        leaf = self.host._leaf_widgets().get(kind)
        if tree is None or leaf is None:
            return
        inner, root = tree.get("inner"), tree.get("root")
        if inner is not None and leaf.parent() is inner:
            s_drag, other = inner, root
        else:
            s_drag, other = root, inner
        if s_drag is None:
            return
        # 先放开所有硬性最小尺寸：否则上一步按自然尺寸设下的"静止最小尺寸"会把挤压顶回去
        # （实测插剖面时单道被顶得比"让位态"更高，看着就是单道在动）。拖动结束时的
        # 正常重排会重新设回来。
        self.host._relax_content_min()
        total = self.host._splitter_span(s_drag)
        n = s_drag.count()
        # 只把 1/3 : 2/3 分给**看得见**的子块：两块构图的树里还挂着第三块（尺寸恒为 0），
        # 按 child 数平均分会让那块收起的面板凭空占走 2/9 —— 那就是"收缩后冒出个空面板"。
        shown = self.host._effective_shown()
        vis_idx = [i for i in range(n) if self.host._child_visible(s_drag.widget(i), shown)]
        idx = next((i for i in range(n) if s_drag.widget(i) is leaf), vis_idx[0])
        third = total / 3.0
        rest = (total - third) / max(1, len(vis_idx) - 1)
        sizes = [(third if i == idx else rest) if i in vis_idx else 0.0
                 for i in range(n)]
        self.host._apply_sizes(s_drag, [int(round(v)) for v in sizes], True)
        if other is not None:
            self.host._apply_sizes(other, self.host._hold_sizes(other, cap, kind), True)

    def _child_visible(self, widget, shown: dict) -> bool:
        """子块是不是"看得见"的：叶子看显隐，内置 inner（分割器）视为可见。"""
        if isinstance(widget, QtWidgets.QSplitter):
            return True
        k = self.host._key_of_widget(widget)
        return bool(k is not None and shown.get(k))

    def _splitter_span(self, sp) -> float:
        """splitter 交给**子块**的总长度（沿它自己的轴，已扣掉把手宽度）。

        Qt 的 ``sizes()`` 之和 = 控件长度 − 把手宽度 ×(n−1)，所以直接拿 work_host 的
        宽/高当总量会多算几个把手，归一化后子块尺寸会差几像素（看着就是"单道动了"）。
        """
        horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
        extent = self.host.work_host.width() if horiz else self.host.work_host.height()
        return max(1.0, float(extent) - float(sp.handleWidth()) * max(0, sp.count() - 1))

    def _hold_sizes(self, sp, cap: dict, kind: str) -> list:
        """``sp`` 每个子块保持它在"让位态"里的尺寸（沿它自己的轴）。

        子块若是"内置 inner"（另一根 splitter），它其实是"剩下那几块"整体占的那块区域，
        用"总量减去其它叶子的尺寸"补出来。
        """
        horiz = sp.orientation() == QtCore.Qt.Orientation.Horizontal
        total = self.host._splitter_span(sp)
        sizes, leaf_sum, filler = [], 0.0, False
        for i in range(sp.count()):
            k = self.host._key_of_widget(sp.widget(i))
            if k is not None and k != kind:
                v = float(cap.get(k, (0.0, 0.0))[0 if horiz else 1])
                sizes.append(v)
                leaf_sum += v
            else:
                sizes.append(None)
                filler = True
        if filler:
            fill = max(1.0, total - leaf_sum)
            return [int(round(fill if v is None else max(1.0, v))) for v in sizes]
        return [int(round(max(1.0, v))) for v in sizes]

    def _leaf_widgets(self) -> dict:
        return {k: getattr(self.host, n) for k, n in self.host._LEAF_OF.items()}

    def _key_of_widget(self, widget):
        for k, n in self.host._LEAF_OF.items():
            if getattr(self.host, n, None) is widget:
                return k
        return None

    def _preview_rect_for_drag(self, kind: str, intent: dict | None) -> tuple | None:
        """落位预览的相对矩形 = 那块 **1/3**（由冻结的判定轴与区域直接算出）。

        不依赖实时几何 —— 排布在动画时也不会画出落在工作区外面的怪矩形，所以
        不再需要"跟着动画刷新"的定时器。
        """
        if not intent or "target" not in intent:
            return None
        side = intent.get("side")
        spec = self.host._zone_frozen or self.host._zone_spec(kind)
        if spec is None or side not in ("first", "second"):
            return None
        axis, (rx, ry, rw, rh) = spec
        if axis == "x":
            w = rw / 3.0
            return (rx if side == "first" else rx + rw - w, ry, w, rh)
        h = rh / 3.0
        return (rx, ry if side == "first" else ry + rh - h, rw, h)

    def _drop_intent_at(self, global_pos: QtCore.QPoint, kind: str,
                        exclude=None, *, group: bool = False,
                        reorder: bool = False) -> dict | None:
        """松手会产生的结果；``None`` 表示没有落位（=按"拉出为独立窗口"处理）。

        * ``{"side": …, "target": (摆法键, 第一块)}`` → 插到工作区的某一侧（左/上 或 右/下）
        * ``{"panel": 面板, "zone": "left"/"right"/None}`` → 插到某块剖面旁边 / 与它换位
          （只在**对比模式**、即窗口里有 ≥2 块剖面、且拖的是组内单图时才走这条）

        ``group=True`` 表示拖的是整个剖面区域：它只按工作区边缘落位，永远不走
        “换数据顺序”那一条，否则整组拖动会被面板换序规则吞掉。
        """
        if not group and kind == "slice" and len(self.host.panels) > 1:
            drop = self.host._drop_zone_at(global_pos, exclude=exclude)
            if drop is not None:
                return {"panel": drop[0], "zone": drop[1]}
        if reorder:
            # 单图拖动只允许“落到另一幅剖面上换序”，不参与工作区边缘的停靠
            return None
        side = self.host._zone_side_at(global_pos, kind)
        if side is not None:
            target = self.host._drop_target(kind, side)
            if target is not None:
                return {"side": side, "target": target}
        return None

    def _visible_excluding(self, kind: str) -> list:
        """**基准**可见集合：几何上真的在窗口里的块，再排除被拖的那块。

        不看拖动中的瞬时状态（``_drag_vis`` / ``_preview_dock``）—— 判定用的是"松手前
        窗口里有几幅图"，也就是需求里分类讨论的那两条。
        """
        out = []
        for k in PANEL_ORDER:
            if k == kind or not self.host._content_shown.get(k):
                continue
            if k == "slice":
                if self.host.panels and not self.host._is_detached(self.host.slice_wrap):
                    out.append(k)
            elif k == "trace":
                if not self.host._is_detached(self.host.trace_frame):
                    out.append(k)
            elif k == "right":
                if not self.host._is_detached(self.host.right_frame):
                    out.append(k)
        return out

    def _region_above(self, key: str) -> tuple:
        """某块面板**上方**那一整块的相对区域（0~1）；那块看不见时退回整个工作区。"""
        wrap = getattr(self.host, "workspace", None)
        holder = {"slice": self.host.slice_holder, "trace": self.host.trace_holder,
                  "right": self.host.right_holder}[key]
        if wrap is None or wrap.height() <= 1 or holder.height() <= 0:
            return (0.0, 0.0, 1.0, 1.0)
        top = wrap.mapFromGlobal(holder.mapToGlobal(QtCore.QPoint(0, 0))).y()
        return (0.0, 0.0, 1.0, max(0.0, min(1.0, top / wrap.height())))

    def _zone_spec(self, kind: str):
        """这一回想"插到哪一侧"的**判定轴**与**判定区域**（相对工作区，0~1）。

        按窗口里除被拖那块以外还剩几幅图分（需求里的分类讨论）：
        * 剩 1 幅 → 结果就是这一对（左右或上下），判定轴 = 这一对的方向，区域 = 整个工作区；
        * 剩 2 幅 → 结果是三块构图，按插入的是哪一块决定轴与区域：
            - 插剖面：与上方的三维**左右**并排，区域 = **单道上方那一整块**；
            - 插单道：与已有两图**上下**叠放，区域 = 整个工作区；
            - 插三维：与已有两图**左右**并排，区域 = 整个工作区。
        没有可插入的余地时返回 ``None``。
        """
        vis = self.host._visible_excluding(kind)
        if len(vis) == 1:
            axis = "x" if pair_layout(tuple(sorted((kind, vis[0]))))[1] == "H" else "y"
            return axis, (0.0, 0.0, 1.0, 1.0)
        if len(vis) == 2:
            if kind == "slice":
                return "x", self.host._region_above("trace")
            if kind == "trace":
                return "y", (0.0, 0.0, 1.0, 1.0)
            return "x", (0.0, 0.0, 1.0, 1.0)
        return None

    def _zone_side_at(self, global_pos: QtCore.QPoint, kind: str) -> str | None:
        """光标落在"插入侧"的哪一侧：``first``（前/左/上三分之一）或 ``second``（后/右/下三分之一）。

        判定区域按 :meth:`_zone_spec` 算，两侧各占该区域的 :data:`EDGE_FRAC`；**中间那三分之一
        是不落位区** —— 松手就按"拉出为独立窗口"处理。

        判定基准**在拿起那一刻冻结一次**（``_zone_frozen``），且基准是"拿起、让位**落定之后**
        用户看到的场景" —— 布局还在过渡的那一小会儿先不判定（否则会拿过渡中的几何当基准）。
        一旦冻住就不再变：拖动中布局在挤占，实时重算会让判定区域跟着动、意图来回翻，
        看着就是面板在抖。
        """
        spec = self.host._zone_frozen
        if spec is None:
            if self.host._layout_anim_running():
                return None                      # "归位"还没落定，先不判定
            spec = self.host._zone_frozen = self.host._zone_spec(kind)
        if spec is None:
            return None
        axis, (rx, ry, rw, rh) = spec
        wrap = getattr(self.host, "workspace", None)
        if wrap is None or not wrap.isVisible():
            return None
        local = wrap.mapFromGlobal(global_pos)
        if not wrap.rect().contains(local):
            return None
        W, H = max(1, wrap.width()), max(1, wrap.height())
        if axis == "x":
            frac = (local.x() / W - rx) / max(1e-6, rw)
        else:
            frac = (local.y() / H - ry) / max(1e-6, rh)
        if frac <= EDGE_FRAC:
            return "first"
        if frac >= 1.0 - EDGE_FRAC:
            return "second"
        return None

    def _layout_anim_running(self) -> bool:
        """工作区这棵树 / 总窗口是否还有尺寸动画在跑（见 :meth:`_animate_layout_change`）。"""
        anim = getattr(self.host, "_layout_anim", None)
        try:
            if anim is not None and anim.state() == QtCore.QAbstractAnimation.State.Running:
                return True
        except RuntimeError:                       # DeleteWhenStopped 已经把对象删了
            pass
        return self.host._layout_animating()

    def _drop_target(self, kind: str, side: str):
        """``side``（first/second）→ ``(构图键, 可换序那两块的第一块)``。

        逐块查表保证"拖到哪就落在哪"。三块构图里有两块是"预设之外的内部构图"
        （BT：单道在上；AL：三维在左），但规则与 A/B 完全镜像，所以仍按同一套处理：
          * 插剖面：B 里它是上排的一块 → first 落在左上、second 落在右上；
          * 插单道：first → BT（单道在上），second → B（底栏通栏）；
          * 插三维：first → AL（三维在左一列），second → A（右列）。
        """
        vis = self.host._visible_excluding(kind)
        if len(vis) == 1:                       # 只剩一幅 → 结果就是那一对
            other = vis[0]
            key = pair_layout(tuple(sorted((kind, other))))[0]
            return key, (kind if side == "first" else other)
        if len(vis) < 2:
            return None
        if kind == "slice":
            return ("B", "slice") if side == "first" else ("B", "right")
        if kind == "trace":
            return ("BT", "trace") if side == "first" else ("B", "trace")
        return ("AL", "right") if side == "first" else ("A", "right")

    def _open_drag_layer(self, d: dict) -> None:
        """面板"离手"：抓快照并隐藏原面板。

        整组 / 普通面板隐藏后让位（邻居吃掉槽位）；对比换序只让**画面**消失，
        槽位宽度钉住，避免邻居先胀后缩。
        """
        target = d["target"]
        # 快照必须在隐藏**之前**抓，否则拿到的是空白图
        snap = self.host._panel_snapshot(target)
        if d.get("reorder_only"):
            # 换序时原面板要消失（手上拿着它），但**槽位宽度必须钉住**：
            # 否则邻居会立刻吃掉这块宽度，松手再恢复就成了“面板先缩再弹回来”。
            try:
                holder = self.host.panel_holders[self.host.panels.index(target)]
            except (ValueError, IndexError):
                holder = None
            if holder is not None and holder.width() > 1:
                d["pinned_holder"] = holder
                holder.setFixedWidth(holder.width())
        target.setVisible(False)
        layer = DragLayer(snap)
        layer.show()
        d["layer"] = layer

    def _panel_snapshot(self, target: QtWidgets.QWidget) -> QtGui.QPixmap:
        """拖动用的快照。三维那块要单独抓 framebuffer —— QWidget.grab() 抓不到 GL 画面。"""
        snap = target.grab()
        if self.host.view3d is not None and target.isAncestorOf(self.host.view3d):
            try:
                fb = self.host.view3d.grabFramebuffer()
            except Exception:                        # pragma: no cover
                fb = None
            if fb is not None and not fb.isNull():
                top_left = self.host.view3d.mapTo(target, QtCore.QPoint(0, 0))
                dpr = float(snap.devicePixelRatio() or 1.0)
                p = QtGui.QPainter(snap)
                p.drawImage(
                    QtCore.QRectF(top_left.x() * dpr, top_left.y() * dpr,
                                  self.host.view3d.width() * dpr,
                                  self.host.view3d.height() * dpr),
                    fb, QtCore.QRectF(0, 0, fb.width(), fb.height()))
                p.end()
        return snap

    def _finish_drag(self, pos: QtCore.QPoint) -> None:
        """松手定稿：落在感应区里就插进去；**其它任何位置一律拉出为独立窗口**。

        "其它位置"包括：中间那三分之一、工作区之外的顶栏/左侧栏、以及主窗口外面 ——
        以前落在工作区空白处是"取消拖动、回原位"，现在统一按"拉出"处理（用户明确要求：
        拖出去的那块本来就允许独立存在，不需要"取消"这一档）。占位框已经没有了，
        拖动期间工作区也早就按预设让位好了。
        """
        d, self.host._drag = self.host._drag, None
        if d is None:
            return
        d["header"].setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        if not d["active"]:
            self.host._clear_drag_layout()               # 只是点了一下：还原
            return
        for p in self.host.panels:
            self.host._highlight_panel(p, False)

        intent = d.get("intent")
        # 换序发生在浮动组内部时，光标本来就在主窗口外，不能因此拒绝落位
        accept = (intent is not None
                  and (self.host._inside_main_window(pos)
                       or (d.get("reorder_only") and "panel" in intent)))
        if accept:
            self.host._discard_drag_layer(d, restore=True)
            self.host._clear_drag_layout(relayout=False)  # 别多排一次：下面 _apply_intent 会落最终构图
            self.host._apply_intent(d, intent)
            if "panel" in intent and d.get("slice_sizes"):
                # 换序 = 只换数据顺序：各剖面块必须保持松手前的像素尺寸，
                # 绝不触发 splitter / window geometry 重排。
                sizes = list(d["slice_sizes"])
                QtCore.QTimer.singleShot(
                    0, lambda s=sizes: self.host.slice_split.setSizes(s))
            return
        if d.get("reorder_only"):
            # 单图拖动只用于换序：没有落到另一幅剖面上就原样回去，绝不拉出/让位
            self.host._discard_drag_layer(d, restore=True)
            self.host._clear_drag_layout()
            self.host.status.setText("拖到另一幅剖面上即可交换数据顺序。")
            return
        self.host._discard_drag_layer(d, restore=True)
        if d["window"] is not None:
            # 本来就是浮窗、又没命中落位 → 保持独立显示（撤掉拖动中的瞬时状态即可）
            self.host._clear_drag_layout()
            self.host.status.setText("浮窗保持独立显示。")
            return
        self.host._tear_off(d, pos)

    def _apply_intent(self, d: dict, intent: dict | None) -> None:
        """按落位意图重排 —— 与拖动时**实时挤占**出来的样子完全同源，所见即所得。"""
        if not intent:
            return
        if "target" in intent:
            preset, first = intent["target"]
            self.host._apply_layout(preset, first=first)
            return
        other = intent.get("panel")
        if other is None:
            return
        zone = intent.get("zone")
        if zone is None:
            self.host._swap_panel_order(d["target"], other)       # 主体 → 交换
        else:
            self.host._move_panel_near(d["target"], other, zone)   # 侧边 → 插入

    def _discard_drag_layer(self, d: dict, restore: bool) -> None:
        holder = d.get("pinned_holder")
        if holder is not None:
            # 换序结束：解除宽度钉住，交回 splitter / _sync_holder_widths 管理
            try:
                holder.setMinimumWidth(0)
                holder.setMaximumWidth(16777215)
            except RuntimeError:                # pragma: no cover
                pass
            d["pinned_holder"] = None
        if d.get("ghost") is not None:
            d["ghost"].setParent(None)
            d["ghost"].deleteLater()
            d["ghost"] = None
        if d.get("layer") is not None:
            d["layer"].hide()
            d["layer"].deleteLater()
            d["layer"] = None
        if restore:
            d["target"].setVisible(True)

    def _inside_main_window(self, global_pos: QtCore.QPoint) -> bool:
        return self.host.frameGeometry().contains(global_pos)

    def _tear_off(self, d: dict, pos: QtCore.QPoint) -> None:
        target = d["target"]
        kind = self.host._drag_kind(target)
        # **全屏 / 最大化下拖出面板 = 自动退出**，并回到进全屏前的窗口几何；
        # 浮窗尺寸用面板在正常窗口里的自然尺寸封顶，避免弹出和屏幕一样大的窗口。
        was_big = self.host.isFullScreen() or self.host.isMaximized()
        normal = self.host.normalGeometry() if was_big else None
        if was_big:
            self.host._auto_resize_depth += 1
            try:
                self.host.showNormal()
                if normal is not None and normal.isValid():
                    self.host.setGeometry(normal)
            finally:
                self.host._auto_resize_depth -= 1
            if normal is not None and normal.isValid():
                self.host._user_size = (normal.width(), normal.height())

        self.host._clear_drag_layout(relayout=False)   # 拉出前先撤掉瞬时的让位/预览状态
        offset = d["offset"] or QtCore.QPoint(0, 0)
        # 尺寸**与窗内一致**：拉出就是"原样搬出去"，不放大也不缩小。
        # 用按下那一刻记下的尺寸，因为面板"离手"后它的槽位已经被邻居吃掉了。
        # 以前按面板种类写死了尺寸，一块剖面拖出来变成 900 宽；三维更明显 ——
        # 窗口一变宽，GL 相机按新宽高比重算，模型看着就"变好大"。
        stamp = d.get("size") or target.size()
        w = max(self.host.MIN_FLOAT[0], stamp.width())
        h = max(self.host.MIN_FLOAT[1], stamp.height())
        if was_big:
            metrics = self.host._panel_metrics().get(kind)
            if metrics:
                w = min(w, max(self.host.MIN_FLOAT[0], metrics["nat_w"]))
                h = min(h, max(self.host.MIN_FLOAT[1], metrics["nat_h"]))
        screen = self.host.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            w, h = min(w, avail.width()), min(h, avail.height())
        size = (w, h)
        self.host._discard_drag_layer(d, restore=False)

        win = FloatingPanel(target, size, self.host)
        win.returned.connect(self.host._close_detached)
        self.host._detached[target] = win
        win.show()
        # 让光标停在面板里的同一个相对位置 —— 手感才对
        tw = max(1, target.width())
        th = max(1, target.height())
        win.move(pos - QtCore.QPoint(int(offset.x() / tw * win.width()),
                                     int(offset.y() / th * win.height())))
        target.setVisible(True)
        self.host._sync_holder_widths()
        # 拖出去之后，剩下两块必须**重新落成设计好的两栏构图**（而不是沿用三块构图
        # 的树与尺寸）：走 _sync_layout_for_count 会让它按实际可见集合重建树。
        self.host._sync_layout_for_count(force_default=False)
        self.host._sync_panel_chips()
        self.host.status.setText("已拉出为独立窗口。")

    def _close_detached(self, widget, silent: bool = False) -> None:
        """收回：把面板放回原位，再销毁空掉的浮窗。

        **无条件先还原面板**（即使 ``_detached`` 里已经没有这条记录）：一个面板如果
        既不在主窗口、也不在任何可见浮窗里，就再也找不回来了 —— 这里多还原一次不会
        有副作用，却堵住了"状态错乱 → 面板永久丢失"这条路。
        """
        win = self.host._detached.pop(widget, None)
        self.host._restore_detached(widget)
        if win is not None:
            win.hide()
            # 在它自己的信号处理里删窗口会把发送者删掉，所以推迟到下一轮事件循环
            QtCore.QTimer.singleShot(0, win.deleteLater)
        self.host._sync_holder_widths()
        # 收回后按"实际可见集合"重排：三块要么 A 要么 B，两块落在对应那一对上。
        self.host._sync_layout_for_count(force_default=False)
        self.host._sync_panel_chips()
        if not silent:
            self.host.status.setText("已把面板收回主窗口。")

    def _restore_detached(self, widget) -> None:
        """按控件类型放回它在主窗口里的原位。"""
        FloatingPanel._set_floating(widget, False)
        if widget is self.host.slice_wrap:
            # 整个剖面区域作为一个浮窗单元收回：放回外层占位容器
            self.host.slice_holder.layout().addWidget(widget)
            widget.setVisible(True)
            return
        if isinstance(widget, SlicePanel):
            if widget in self.host.panels:
                self.host.panel_holders[self.host.panels.index(widget)].layout().addWidget(widget)
            widget.setVisible(True)
            return
        if widget is self.host.trace_frame:
            self.host._trace_holder_layout.insertWidget(0, self.host.trace_frame)
            widget.setVisible(True)
            return
        if widget is self.host.right_frame:
            self.host._right_holder_layout.insertWidget(0, self.host.right_frame)
            widget.setVisible(True)

    def _swap_panel_order(self, src, target) -> None:
        i, j = self.host.panels.index(src), self.host.panels.index(target)
        self.host.datasets[i], self.host.datasets[j] = self.host.datasets[j], self.host.datasets[i]
        # 当前"激活的数据"要跟着数据走，而不是跟着位置走
        if self.host.active == i:
            self.host.active = j
        elif self.host.active == j:
            self.host.active = i
        self.host._after_order_change()
        self.host.status.setText(f"已交换数据 {i + 1} 与 {j + 1}。")

    def _move_panel_near(self, src, target, zone: str) -> None:
        """把 ``src`` 这块剖面挪到 ``target`` 的 ``left`` / ``right`` 一侧。

        挪的是 ``self.host.datasets`` 的顺序（面板按位置和数据一一对应），所以叠加波形与
        单道波形的配色会跟着新的"从左到右"顺序重排 —— 这正是用户拖动想要的效果。
        激活的数据按**对象**跟过去，而不是按下标，免得算错插入点导致的连带位移。
        """
        i, j = self.host.panels.index(src), self.host.panels.index(target)
        if i == j:
            return
        active_ds = self.host.datasets[self.host.active]
        item = self.host.datasets.pop(i)
        insert_at = j if zone == "left" else j + 1
        if i < insert_at:
            insert_at -= 1
        self.host.datasets.insert(insert_at, item)
        self.host.active = self.host.datasets.index(active_ds)
        self.host._after_order_change()
        self.host.status.setText(f"已把数据 {i + 1} 移到第 {insert_at + 1} 位。")

    def _after_order_change(self) -> None:
        self.host._sync_controls()
        self.host._refresh_all(sync_controls=False)
        self.host._update_face_info()

    def _panel_at(self, global_pos: QtCore.QPoint, exclude=None):
        """落在哪一块剖面面板上；已经在独立窗口里的不算。"""
        for panel in self.host.panels:
            if panel is exclude or self.host._is_detached(panel):
                continue
            if panel.isVisible() and panel.rect().contains(panel.mapFromGlobal(global_pos)):
                return panel
        return None

    def _drop_zone_at(self, global_pos: QtCore.QPoint, exclude=None):
        """``(面板, 落在哪一侧)``；``None`` 表示落在面板主体（= 交换）。"""
        panel = self.host._panel_at(global_pos, exclude=exclude)
        if panel is None:
            return None
        local = panel.mapFromGlobal(global_pos)
        if local.x() < self.host.DROP_ZONE:
            return (panel, "left")
        if local.x() > panel.width() - self.host.DROP_ZONE:
            return (panel, "right")
        return (panel, None)

    @staticmethod
    def _highlight_panel(panel, on: bool, zone: str | None = None) -> None:
        """落点提示：主体整块高亮 = 会交换；左/右边缘一条亮竖条 = 会插到这里。"""
        panel.setProperty("dropTarget", bool(on and zone is None))
        panel.setProperty("dropLeft", bool(on and zone == "left"))
        panel.setProperty("dropRight", bool(on and zone == "right"))
        panel.style().unpolish(panel)
        panel.style().polish(panel)

    def _sync_holder_widths(self) -> None:
        """剖面面板容器的宽度分配。

        剖面的整组移动/浮窗由外层 `slice_holder` 负责；这里只解除容器宽度上限，
        并在块数变化时给一次等分尺寸。
        """
        n = len(self.host.panel_holders)
        if n == 0:
            return
        for holder in self.host.panel_holders:
            holder.setMinimumWidth(0)
            holder.setMaximumWidth(16777215)
        if len(self.host.slice_split.sizes()) != n:
            self.host.slice_split.setSizes([1] * n)

    def event_filter(self, obj, ev) -> bool:            # noqa: N802 （Qt 接口名）
        target = self.host._drag_watch.get(obj)
        if target is None:
            return False
        kind = ev.type()
        if kind == QtCore.QEvent.Type.MouseButtonPress \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            if self.host._begin_drag(obj, target, ev.globalPosition().toPoint(),
                                ev.modifiers()):
                return True                      # 已交给系统原生拖动，别再往下传
        elif kind == QtCore.QEvent.Type.MouseButtonDblClick \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            if self.host._toggle_float_maximized(target):
                return True
        elif kind == QtCore.QEvent.Type.MouseMove and self.host._drag is not None:
            self.host._move_drag(ev.globalPosition().toPoint())
            return True
        elif kind == QtCore.QEvent.Type.MouseButtonRelease and self.host._drag is not None \
                and ev.button() == QtCore.Qt.MouseButton.LeftButton:
            self.host._finish_drag(ev.globalPosition().toPoint())
            return True
        return False
