"""数据装配服务：打开文件、选变量、确认轴序、安装/追加/替换/移除/清空。

只负责数据状态机与载入流程；面板刷新、布局重建等 UI 收尾仍通过宿主
（MainWindow）的既有方法完成，保证行为不变。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets

from . import loaders
from .loaders import LoadError
from .models import Dataset
from .sample import build_sample_volume
from .volume import SeisVolume
from .widgets import ArrayViewDialog, ask_axis_order

MAX_DATASETS = 3


class DatasetService:
    def __init__(self, host) -> None:
        self.host = host

    # ------------------------------------------------------------ 忙碌 / 来源
    @contextlib.contextmanager
    def _busy(self, text: str):
        """同步扫描 / 读取大文件时至少给用户一个"正在忙"的反馈。"""
        QtWidgets.QApplication.setOverrideCursor(
            QtCore.Qt.CursorShape.WaitCursor)
        self.host.status.setText(text)
        QtWidgets.QApplication.processEvents()
        try:
            yield
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def list_variables(self, path: str):
        """扫描文件变量（带等待光标，供打开/拖放共用）。"""
        with self._busy("正在扫描文件…"):
            return loaders.list_variables(path)

    def _source_snapshot(self) -> tuple:
        """保存「数据」卡片当前的来源状态，失败时恢复。"""
        host = self.host
        return (host.src_path, host.file_label.text(), host.table.infos(),
                host.btn_load.isEnabled(), host.src_info.text())

    def _restore_source(self, snap: tuple) -> None:
        path, label, infos, load_enabled, info = snap
        host = self.host
        host.src_path = path
        host.file_label.setText(label)
        host.table.fill(infos)
        host.btn_load.setEnabled(load_enabled)
        host.src_info.setText(info)

    # ------------------------------------------------------------ 打开/加载
    def add_compare_file(self) -> None:
        """再选一份文件载入为对比数据（形状必须与第一份一致）。"""
        host = self.host
        if len(host.datasets) >= MAX_DATASETS:
            host._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            host, "添加对比数据", self.dir_hint(),
            "地震数据 (*.sgy *.segy *.su *.npy *.npz *.mat);;所有文件 (*)")
        if path:
            self.open_source(path, reset=False)

    def remove_dataset(self) -> None:
        """移除当前数据；至少保留一份。"""
        host = self.host
        if len(host.datasets) <= 1:
            return
        idx = host.active
        host.datasets.pop(idx)
        host.pipeline.pop_base_clim(idx)
        host.active = max(0, min(idx, len(host.datasets) - 1))
        self.after_dataset_change()
        host.status.setText(f"已移除数据 {idx + 1}。")

    def dir_hint(self) -> str:
        host = self.host
        ds = host.datasets[host.active] if host.datasets else None
        if ds is not None and ds.path:
            return str(Path(ds.path).parent)
        return str(Path.home())

    def open_source(self, path: str, reset: bool) -> bool:
        """列出文件里的变量并载入第一个。

        ``reset=True`` 替换主数据，``False`` 追加为对比数据。返回是否成功载入。
        """
        host = self.host
        if not path or not Path(path).exists():
            host._error("文件不存在", f"找不到 {path}")
            return False
        if not reset and len(host.datasets) >= MAX_DATASETS:
            host._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return False
        try:
            infos = self.list_variables(path)
        except LoadError as exc:
            host._error("无法读取文件", str(exc))
            return False
        except Exception as exc:                        # pragma: no cover
            host._error("无法读取文件", f"{type(exc).__name__}: {exc}")
            return False

        snap = self._source_snapshot()
        host.src_path = path
        p = Path(path)
        host.file_label.setText(f"{p.parent}  ▸  {p.name}")
        host.table.fill(infos)
        host.btn_load.setEnabled(True)
        host.src_info.setText(f"共 {len(infos)} 个可用变量，正在载入第一个…")
        host.status.setText(f"已识别 {len(infos)} 个变量。")
        # 打开即出图：默认载入第一个变量，需要确认轴序时会弹框
        try:
            ok = self.load_variable(infos[0].key,
                                    target="reset" if reset else "append")
        except Exception:
            self._restore_source(snap)
            raise
        if not ok:
            self._restore_source(snap)
        return ok

    def load_selected_variable(self) -> None:
        info = self.host.table.current_info()
        if info is not None:
            self.load_variable(info.key)

    def load_variable(self, key: str, target: str | None = None) -> bool:
        """载入 ``key`` 变量。

        ``target`` 为 ``"reset"`` 时替换主数据、``"append"`` 时追加为对比数据、
        ``None``（默认）时替换**当前**数据。返回是否成功。
        """
        host = self.host
        if not host.src_path:
            return False
        info = host.table.info_of_key(key)
        if info is None:
            return False
        if len(info.shape) <= 1:
            # 一维/标量：当作一条单道记录载入主界面（只留单道波形面板）。
            vol = self.build_trace_vol(host.src_path, key, info)
        else:
            vol = self.build_variable_vol(host.src_path, key, info)
        if vol is None:
            return False

        if target == "reset":
            return self.install_primary(vol, host.src_path, key)
        if target == "append":
            return self.append_dataset(vol, host.src_path, key)
        return self.replace_active(vol, host.src_path, key)

    def show_variable_values(self, path: str, key: str) -> bool:
        """一维/标量变量：直接把数值列表显示出来（不进体数据）。"""
        host = self.host
        try:
            with self._busy("正在读取数值…"):
                arr = loaders.load_array(path, key)
        except LoadError as exc:
            host._error("读取失败", str(exc))
            return False
        ArrayViewDialog(f"{Path(path).name}  ▸  {key}", arr, host).exec()
        host.status.setText(f"已查看 {key} 的数值。")
        return True

    def build_trace_vol(self, path: str, key: str, info=None) -> SeisVolume | None:
        """把一维/标量变量读成 ``(1, 1, T)`` 的单道体数据（只读，不装配）。"""
        host = self.host
        try:
            with self._busy("正在读取变量…"):
                arr = np.asarray(loaders.load_array(path, key)).ravel()
        except LoadError as exc:
            host._error("读取失败", str(exc))
            return None
        except Exception as exc:                        # pragma: no cover
            host._error("读取失败", f"{type(exc).__name__}: {exc}")
            return None
        if arr.size == 0:
            host._error("数据为空", f"变量 {key} 里没有数值。")
            return None
        extra = loaders.load_meta(path, key)
        dt = float(extra.get("dt") or host.spin_dt.value())
        data = arr.reshape(1, 1, -1).astype(np.float32, copy=False)
        return SeisVolume(name=f"{Path(path).stem}·{key}", data=data, dt=dt,
                          dx=float(host.spin_dx.value()),
                          ds=float(host.spin_ds.value()),
                          meta=dict(extra.get("meta", {})))

    def build_variable_vol(self, path: str, key: str,
                           info=None) -> SeisVolume | None:
        """把 ``path`` 里的 ``key`` 读成规范化 (S,R,T) 体数据（只读，不装配）。"""
        host = self.host
        if info is None:
            info = host.table.info_of_key(key)
        if info is None:
            return None
        if len(info.shape) <= 1:
            return None
        if len(info.shape) > 3:
            host._error("暂不支持", f"变量 {key} 是 {len(info.shape)} 维，无法载入。")
            return None
        if min(info.shape, default=0) <= 0:
            host._error("数据为空",
                        f"变量 {key} 的形状 {' × '.join(map(str, info.shape))} "
                        "含 0 长度维度，无法载入。")
            return None

        fingerprint = f"{loaders.file_fingerprint(path)}:{key}"
        remember = False
        if info.roles:
            # SEG-Y/SU：立方体是按道头现搭的，轴序由构造决定，不必再确认
            roles = list(info.roles)
            host.status.setText(f"已按道头分选出 {key}，正在载入…")
        else:
            initial = loaders.get_axis_memory(fingerprint)
            if initial and len(initial) != len(info.shape):
                initial = None
            answer = ask_axis_order(f"{Path(path).name}  ▸  {key}", info.shape,
                                    initial, host)
            if answer is None:
                host.status.setText("已取消载入。")
                return None
            roles, remember = answer
            if len(roles) != len(info.shape):
                host._error("轴序不完整", "每一个维度都需要指定一个物理含义。")
                return None

        # SEG-Y 的 dt / 道距来自道头；非 SEG-Y 用界面上的当前值做默认
        extra = loaders.load_meta(path, key)
        dt = float(extra.get("dt") or host.spin_dt.value())
        dx = float(extra.get("dx") or host.spin_dx.value())
        ds = float(extra.get("ds") or host.spin_ds.value())

        try:
            with self._busy("正在读取变量…"):
                arr = loaders.load_array(path, key)
                vol = loaders.build_volume(
                    f"{Path(path).stem}·{key}", arr, roles,
                    dt=dt, dx=dx, ds=ds, meta=dict(extra.get("meta", {})))
        except LoadError as exc:
            host._error("载入失败", str(exc))
            return None
        except Exception as exc:                        # pragma: no cover
            host._error("载入失败", f"{type(exc).__name__}: {exc}")
            return None

        if remember:
            loaders.set_axis_memory(fingerprint, roles)
        return vol

    def load_sample(self) -> None:
        host = self.host
        if not host.btn_sample.isEnabled():     # _busy 里的 processEvents 可能重入
            return
        host.btn_sample.setEnabled(False)
        host.src_path = ""
        host.file_label.setText("示例数据")
        host.table.fill([])
        host.btn_load.setEnabled(False)
        try:
            with self._busy("正在准备示例数据…"):
                vol = build_sample_volume()
            self.install_primary(vol, "", "示例")
            host.src_info.setText(
                f"示例数据　{vol.ns} 炮 × {vol.nr} 检波点 × {vol.nt} 采样\n"
                f"dt {vol.dt * 1000:g} ms")
            host.status.setText("已载入示例数据。")
        finally:
            host.btn_sample.setEnabled(True)

    # ------------------------------------------------------------ 清空
    def clear_data(self) -> None:
        """清空数据状态；界面复位交给宿主的 ``_reset_ui_after_clear``。"""
        host = self.host
        host._stop()
        host._stop_layout_anim()
        host._stop_all_size_anims()       # 面板/树马上要销毁，别让旧动画继续摸它们
        # 拉出去的浮窗先收回主窗口：否则数据清了，那些窗口还孤零零留在桌面上
        for widget in list(host._detached):
            host._close_detached(widget, silent=True)

        # ---- 数据集合
        # 先把每块面板的图 / 叠加曲线 / 提示线 / 读数显式复位，再移除面板与数据。
        # 只依赖 deleteLater 的话，对比多面板 + 浮窗/缓存的组合下容易留残影。
        for panel in list(host.panels):
            panel.reset_view_state()

        host.datasets = []
        host.active = 0
        host.pipeline.reset()
        host._pick_undo = None
        loaders.clear_caches()
        # 清空数据 = 回到“刚打开”的状态：用户尺寸锚也要一并清掉，
        # 否则窗口会一直保持清空前那个（可能被对比数据撑大的）尺寸。
        host._user_size = None
        host._window_target = None
        host._is_2d = False
        host._is_1d = False
        host._three_auto_closed = False
        host._reset_ui_after_clear()

    # ------------------------------------------------------------ 数据集装配
    @staticmethod
    def default_mode(vol: SeisVolume) -> str:
        """默认落在"成像面积最大"的那一面。"""
        areas = {"shot": vol.nr * vol.nt, "recv": vol.ns * vol.nt,
                 "time": vol.ns * vol.nr}
        return max(areas, key=lambda m: areas[m])

    def install_primary(self, vol: SeisVolume, path: str, key: str) -> bool:
        """替换整个数据集为这一份数据。"""
        host = self.host
        if min(vol.shape) <= 0:
            host._error("数据为空", f"形状 {' × '.join(map(str, vol.shape))} "
                                    "含 0 长度维度，无法载入。")
            return False
        first_load = not host.datasets
        prev_shape = tuple(host.datasets[0].vol.shape) if host.datasets else None
        ds = Dataset(vol=vol, path=path, key=key)
        ds.mode = self.default_mode(vol)
        host.datasets = [ds]
        host.active = 0
        host.pipeline.set_base_clims([(-1.0, 1.0)])
        host._recompute_base_clim(0)
        # 换了数据维度/形状：窗口尺寸重新按新数据的自然尺寸算，用户尺寸锚作废 ——
        # 否则先看过三维、再载入二维时，窗口还保持旧的大尺寸，剖面被拉得很宽。
        if first_load or prev_shape != tuple(vol.shape):
            host._user_size = None
        # 刚载入：按数据维度给一次默认排版
        self.default_view_for(vol)
        host._is_2d = bool(vol.is_single_shot)
        host._is_1d = bool(vol.is_single_trace)
        # 首次载入不做窗口尺寸动画：空窗口 → 有数据是一次性跳变
        self.after_dataset_change(animate_layout=not first_load)
        return True

    def append_dataset(self, vol: SeisVolume, path: str, key: str) -> bool:
        """追加一份对比数据（形状必须与第一份一致）。"""
        host = self.host
        if min(vol.shape) <= 0:
            host._error("数据为空", f"形状 {' × '.join(map(str, vol.shape))} "
                                    "含 0 长度维度，无法载入。")
            return False
        if not host.datasets:
            return self.install_primary(vol, path, key)
        base = host.datasets[0].vol
        if tuple(vol.shape) != tuple(base.shape):
            host._error("维度不一致",
                        "对比数据必须与第一份形状相同。\n"
                        f"当前：{base.ns} × {base.nr} × {base.nt}（S × R × T）\n"
                        f"这份：{vol.ns} × {vol.nr} × {vol.nt}")
            return False
        if len(host.datasets) >= MAX_DATASETS:
            host._error("已达上限", f"最多同时对比 {MAX_DATASETS} 份数据。")
            return False
        ds = Dataset(vol=vol, path=path, key=key)
        ds.mode = host.datasets[0].mode
        ds.pos = dict(host.datasets[0].pos)
        host.datasets.append(ds)
        host.active = len(host.datasets) - 1
        host.pipeline.append_base_clim()
        host._recompute_base_clim(host.active)
        self.after_dataset_change()
        host.status.setText(f"已作为第 {host.active + 1} 份对比数据载入。")
        return True

    def replace_active(self, vol: SeisVolume, path: str, key: str) -> bool:
        """用新变量替换当前数据；形状一致时保留切片位置。"""
        host = self.host
        if min(vol.shape) <= 0:
            host._error("数据为空", f"形状 {' × '.join(map(str, vol.shape))} "
                                    "含 0 长度维度，无法载入。")
            return False
        if not host.datasets:
            return self.install_primary(vol, path, key)
        k = host.active
        old = host.datasets[k]
        if len(host.datasets) > 1 and tuple(vol.shape) != tuple(old.vol.shape):
            host._error("维度不一致", "对比模式下替换数据必须保持相同形状。")
            return False
        ds = Dataset(vol=vol, path=path, key=key)
        same = tuple(vol.shape) == tuple(old.vol.shape)
        if same:
            ds.mode = old.mode
            ds.pos = {"shot": min(old.pos.get("shot", 0), vol.ns - 1),
                      "recv": min(old.pos.get("recv", 0), vol.nr - 1),
                      "time": min(old.pos.get("time", 0), vol.nt - 1)}
        else:
            ds.mode = self.default_mode(vol)
            # 维度/形状变了：旧窗口尺寸不再代表这份数据的自然比例，排版也按新维度重置
            host._user_size = None
            self.default_view_for(vol)
        host.datasets[k] = ds
        host._is_2d = bool(vol.is_single_shot)
        host._is_1d = bool(vol.is_single_trace)
        host._recompute_base_clim(k)
        self.after_dataset_change()
        return True

    def after_dataset_change(self, animate_layout: bool = True) -> None:
        """数据集合发生变化后统一收尾。"""
        host = self.host
        host._stop()
        host.setUpdatesEnabled(False)
        try:
            host._rebuild_slice_panels()
            host._sync_panel_chips()           # 剖面块数圆点跟着数据份数走
            self.sync_dimensional_defaults()
            host.mode_ctl.set_enabled_keys({"shot", "recv", "time"})
            host.mode_ctl.set_value(host.mode)
            host.btn_export.setEnabled(True)
            host.btn_clear.setEnabled(True)
            host.trace_view.clear()
            if host._content_shown.get("right"):
                host._ensure_view3d()          # 三维数据/面板要显示时才建 GL 控件
            if host.view3d is not None:
                host.view3d.set_volume(host.vol)
                host.view3d.focus_face(host.mode, animate=False)
            host._sync_gated_controls()
            host._refresh_all()
            host._update_face_info()
            summary = host.vol.meta.get("summary")     # SEG-Y/SU 带自己的载入摘要
            if summary:
                host.src_info.setText(summary)
            # 数据规模变了 → 三块的自然尺寸与窗口尺寸都要按新数据重算一遍。
            host._suppress_window_resize = True
            try:
                host._relayout_content(animate=False)
            finally:
                host._suppress_window_resize = False
        finally:
            host.setUpdatesEnabled(True)
            host.update()
        if animate_layout:
            host._animate_layout_change()
        else:
            if host._window_target is not None and not (
                    host.isFullScreen() or host.isMaximized()):
                # 首次载入直接落到最终尺寸：只出现一帧最终画面
                host._resize_keeping_anchor(*host._window_target)
                host._ensure_on_screen()
            # 尺寸落定后强制同步画完最终布局与面板内容，避免先看到一帧中间状态
            host.repaint()

    def default_view_for(self, vol: SeisVolume | None) -> None:
        """按数据维度给一次默认排版。

        * 一维（单道）：只留单道波形；
        * 二维（单炮）：剖面 + 单道，三维不显示；
        * 三维：三块全开。
        """
        host = self.host
        if vol is not None and vol.is_single_trace:
            host._content_shown = {"slice": False, "trace": True, "right": False}
        elif vol is not None and vol.is_single_shot:
            host._content_shown = {"slice": True, "trace": True, "right": False}
        else:
            host._content_shown = {"slice": True, "trace": True, "right": True}
        host._layout_preset = host._default3_key or "B"
        host._pair_order = list(host._free_pair())
        host._three_auto_closed = False

    def sync_dimensional_defaults(self) -> None:
        """数据维度变化后修正默认可见集合：一维只剩单道，二维收起三维。"""
        host = self.host
        one_d = bool(host.datasets) and all(d.vol.is_single_trace
                                            for d in host.datasets)
        two_d = bool(host.datasets) and all(d.vol.is_single_shot
                                            for d in host.datasets)
        if one_d:
            shown = {"slice": False, "trace": True, "right": False}
            if dict(host._content_shown) != shown:
                host._content_shown = shown
                host._sync_layout_for_count()
            return
        if two_d == host._is_2d:
            return
        host._is_2d = two_d
        shown = dict(host._content_shown)
        if two_d:
            if not shown.get("right"):
                return
            shown["right"] = False
            if not any(shown.values()):
                shown["slice"] = True
            host._three_auto_closed = True
        elif host._three_auto_closed:
            shown["right"] = True
            host._three_auto_closed = False
        else:
            return
        host._content_shown = shown
        host._sync_layout_for_count()
