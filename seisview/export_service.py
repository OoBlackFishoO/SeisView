"""导出服务：整卷 / 逐剖面 / 论文用图的对话框编排与进度控制。

业务规则（格式、切片范围、文件名、论文图取数）都在这里；MainWindow 只负责
把按钮与快捷键接过来。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from . import export as exporter
from . import view2d
from .figure_options import (DEFAULT_LINE_STYLES, ExportFigureOptions,
                             FIGURE_TEXT, figure_labels as localize_figure)
from .volume import SLICE_LABELS
from .widgets import ExportDialog, FigurePreviewDialog


class ExportService:
    def __init__(self, host) -> None:
        self.host = host

    # ------------------------------------------------------------ 入口
    def open_dialog(self) -> None:
        """打开「导出 / 转换」对话框并按选择执行。"""
        host = self.host
        if not host.datasets:
            host.status.setText("请先打开数据或载入示例，再导出。")
            return
        entries = [{"label": host._dataset_label(k), "vol": ds.vol, "pos": ds.pos}
                   for k, ds in enumerate(host.datasets)]
        active_ds = host.datasets[host.active]
        src = Path(active_ds.path) if active_ds.path else None
        dlg = ExportDialog(entries, host.active,
                           src.parent if src else Path.home(),
                           src.stem if src else "seisview_export",
                           line_styles=list(host.line_styles),
                           mode=active_ds.mode,
                           source_path=str(src) if src else "",
                           parent=host)
        dlg.previewRequested.connect(lambda: self.show_preview(dlg))
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            host.status.setText("已取消导出。")
            return
        self.run(dlg)

    def run(self, dlg) -> None:
        """带进度与取消地跑一次导出。"""
        host = self.host
        prog = QtWidgets.QProgressDialog("正在导出…", "取消", 0, 100, host)
        prog.setWindowTitle("导出 / 转换")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setValue(0)
        # 显示值平滑追赶真实目标：算得出的段给真实百分比，算不出的段（序列化）
        # 停在 99% + 确定性文案。全程只增不减、不跳变。
        chaser = {"shown": 0, "target": 0, "text": ""}

        def tick() -> None:
            shown, target = chaser["shown"], chaser["target"]
            if shown >= target:
                return
            step = max(1, int(np.ceil((target - shown) * 0.25)))
            chaser["shown"] = min(target, shown + step)
            prog.setValue(chaser["shown"])

        timer = QtCore.QTimer(host)
        timer.setInterval(40)
        timer.timeout.connect(tick)
        timer.start()

        def on_progress(frac: float, text: str) -> None:
            pct = int(max(0.0, min(1.0, frac)) * 100)
            chaser["target"] = max(chaser["target"], pct)
            if text != chaser["text"]:
                chaser["text"] = text
                prog.setLabelText(text)
            # 即使百分比没变也要泵事件：序列化写盘期间界面靠这里保持重绘
            QtWidgets.QApplication.processEvents()

        host._stop()
        if dlg.content() in ("wave_image", "wiggle_image"):
            # 线型在导出图对话框里编辑；导出前同步回宿主，保持会话内一致
            host.line_styles = dlg.line_styles()
        try:
            content = dlg.content()
            if content in ("slice_image", "wiggle_image", "wave_image"):
                targets = 1
                if content == "slice_image" and dlg.dataset_scope() == "all":
                    targets = max(1, len(host.datasets))
                if targets <= 1:
                    # 单张图无法中途取消，隐藏无效的取消按钮
                    prog.setCancelButton(None)
                made = self.export_figures(
                    dlg, on_progress,
                    prog.wasCanceled if targets > 1 else None)
                timer.stop()
                prog.setValue(100)
                prog.close()
                canceled = prog.wasCanceled() and len(made) < targets
                if canceled:
                    where = f" → {Path(made[0]).parent}" if made else "。"
                    host.status.setText(
                        f"已取消导出：已写出 {len(made)} / {targets} 张图{where}")
                elif content == "wave_image":
                    host.status.setText(f"已导出波形图 → {made[0]}")
                elif content == "wiggle_image":
                    host.status.setText(f"已导出 wiggle 剖面图 → {made[0]}")
                elif made:
                    host.status.setText(
                        f"已导出 {len(made)} 张剖面图 → {Path(made[0]).parent}")
                else:
                    host.status.setText("没有生成任何图片。")
                return
            if content == "slices":
                made = self.export_slices(dlg, on_progress, prog.wasCanceled)
                timer.stop()
                prog.setValue(100)
                prog.close()
                host.status.setText(
                    f"已逐剖面导出 {len(made)} 个 "
                    f"{exporter.LABEL_OF.get(dlg.fmt(), dlg.fmt())} "
                    f"文件 → {dlg.path()}")
                return
            out = exporter.export(dlg.path(), host.vol.data, dlg.fmt(),
                                  dt_us=dlg.dt_us(), dx=dlg.dx(), ds=dlg.ds(),
                                  with_coords=dlg.with_coords(),
                                  progress=on_progress, cancel=prog.wasCanceled)
        except exporter.ExportError as exc:
            timer.stop()
            prog.close()
            host._error("导出失败", str(exc))
            return
        except Exception as exc:                            # pragma: no cover
            timer.stop()
            prog.close()
            host._error("导出失败", f"{type(exc).__name__}: {exc}")
            return
        timer.stop()
        prog.setValue(100)
        prog.close()
        size = Path(out).stat().st_size
        host.status.setText(
            f"已导出 {exporter.LABEL_OF.get(dlg.fmt(), dlg.fmt())} → {out}"
            f"（{size / 1024 ** 2:.1f} MB）")

    # ------------------------------------------------------------ 逐剖面
    def export_slices(self, dlg, progress, cancel) -> list[str]:
        """逐剖面导出：按对话框选的数据源 / 方向 / 片层范围逐份写出。"""
        host = self.host
        scope_all = dlg.dataset_scope() == "all"
        sel = [k for k in range(len(host.datasets)) if scope_all or k == host.active]
        axis = dlg.slice_axis()
        prefix = dlg.name_prefix()
        multi = len(sel) > 1
        jobs: list[tuple] = []
        for k in sel:
            ds = host.datasets[k]
            if dlg.current_only():
                idx = int(np.clip(ds.pos.get(axis, 0), 0,
                                 ds.vol.slice_index_range(axis) - 1))
                a = b = idx
            else:
                a, b = dlg.slice_range()
                a, b = min(a, b), max(a, b)
            name = prefix if not multi else (f"{prefix}_d{k + 1}" if prefix else f"d{k + 1}")
            jobs.append((ds, a, b, name))
        counts = [max(0, b - a + 1) for _ds, a, b, _n in jobs]
        total = max(1, sum(counts))

        made: list[str] = []
        base_count = 0
        for i, (ds, a, b, name) in enumerate(jobs):
            unit = max(1, counts[i])

            def cb(frac, text, base=base_count, unit=unit, i=i):
                progress((base + max(0.0, min(1.0, frac)) * unit) / total,
                         f"数据 {i + 1}：{text}")

            part = exporter.export_slices(
                dlg.path(), ds.vol.data, dlg.fmt(), mode=axis, name=name,
                start=a, stop=b, progress=cb, cancel=cancel)
            made.extend(part)
            base_count += unit
        return made

    # ------------------------------------------------------------ 论文用图
    @staticmethod
    def figure_labels(mode: str, language: str = "zh",
                      offset: bool = False) -> tuple[str, str, str]:
        """论文图的坐标轴文字，按所选语言返回（中 / 英）。"""
        return localize_figure(mode, language, offset)

    @staticmethod
    def _data_label(k: int, language: str) -> str:
        return f"{FIGURE_TEXT.get(language, FIGURE_TEXT['zh'])['data']} {k + 1}"

    def _figure_title(self, k: int, dlg, kind: str) -> str:
        """标题完全由用户输入；留空就不画标题。"""
        return self._options_of(dlg).title

    @staticmethod
    def _options_of(dlg) -> ExportFigureOptions:
        fn = getattr(dlg, "figure_options", None)
        return fn() if fn is not None else ExportFigureOptions()

    @staticmethod
    def _styles_of(dlg, host) -> list:
        fn = getattr(dlg, "line_styles", None)
        return list(fn()) if fn is not None else list(host.line_styles)

    def build_slice_plot(self, k: int, dlg) -> view2d.pg.PlotWidget:
        host = self.host
        ds = host.datasets[k]
        settings = host._display_settings()
        options = self._options_of(dlg)
        lang = options.language
        img, clim = host._panel_image(k, full=True)
        use_offset = bool(options.offset_axis and ds.mode == "shot")
        xlabel, ylabel, cbar = self.figure_labels(ds.mode, lang, use_offset)
        extent = ds.vol.extent_of(ds.mode)
        if use_offset:
            # 共炮点剖面：把横轴原点挪到当前炮点（偏移距 = R − S）。
            shift = float(ds.pos["shot"]) * float(ds.vol.ds)
            x0, x1, y0, y1 = extent
            extent = (x0 - shift, x1 - shift, y0, y1)
        if options.xlabel_override is not None:
            xlabel = options.xlabel_override
        if options.ylabel_override is not None:
            ylabel = options.ylabel_override
        # 剖面图永远是密度图；纯 wiggle 走单独的「wiggle 剖面」导出。
        return view2d.build_slice_figure(
            img, extent, settings.cmap, clim,
            xlabel, ylabel, invert_y=ds.vol.is_time_vertical(ds.mode),
            colorbar_label=cbar, grid=False,
            options=options, out_fmt=dlg.fmt(),
            title=self._figure_title(k, dlg, "slice"))

    def build_wiggle_plot(self, dlg) -> view2d.pg.PlotWidget:
        """纯 wiggle 剖面：对比模式下把所有数据源叠加在同一张图里。"""
        host = self.host
        options = self._options_of(dlg)
        lang = options.language
        settings = host._display_settings()
        active = host.datasets[max(0, min(host.active, len(host.datasets) - 1))]
        use_offset = bool(options.offset_axis and active.mode == "shot")
        xlabel, ylabel, _ = self.figure_labels(active.mode, lang, use_offset)
        if options.xlabel_override is not None:
            xlabel = options.xlabel_override
        if options.ylabel_override is not None:
            ylabel = options.ylabel_override
        extent = active.vol.extent_of(active.mode)
        if use_offset:
            shift = float(active.pos["shot"]) * float(active.vol.ds)
            x0, x1, y0, y1 = extent
            extent = (x0 - shift, x1 - shift, y0, y1)
        styles = self._styles_of(dlg, host) or list(DEFAULT_LINE_STYLES)
        sets = [self.figure_wiggle_set(k, line_styles=styles)
                for k in range(len(host.datasets))]
        labels = [self._data_label(k, lang) for k in range(len(host.datasets))]
        return view2d.build_wiggle_figure(
            sets[0][0] if sets else np.zeros((1, 1), dtype=np.float32),
            extent, xlabel, ylabel, sets,
            n_traces=settings.wiggle_traces, gain=settings.wiggle_gain,
            invert_y=active.vol.is_time_vertical(active.mode),
            labels=labels if len(sets) > 1 else None,
            options=options, out_fmt=dlg.fmt(),
            title=self._figure_title(host.active, dlg, "wiggle"))

    def build_wave_plot(self, dlg) -> view2d.pg.PlotWidget:
        host = self.host
        options = self._options_of(dlg)
        lang = options.language
        text = FIGURE_TEXT.get(lang, FIGURE_TEXT["zh"])
        styles = self._styles_of(dlg, host) or list(DEFAULT_LINE_STYLES)
        multi = len(host.datasets) > 1
        xlabel = (options.xlabel_override if options.xlabel_override is not None
                  else text["wave_x"])
        ylabel = (options.ylabel_override if options.ylabel_override is not None
                  else text["wave_y"])
        entries = [(t, amp, styles[k % len(styles)],
                    self._data_label(k, lang) if multi else name)
                   for k, (t, amp, _screen_style, name)
                   in enumerate(host._traces()[0])]
        rng = getattr(dlg, "time_range", None)
        return view2d.build_trace_figure(
            entries, xlabel=xlabel, ylabel=ylabel,
            options=options, out_fmt=dlg.fmt(),
            title=self._figure_title(host.active, dlg, "wave"),
            x_range=rng() if rng is not None else None)

    def export_figures(self, dlg, progress, cancel=None) -> list[str]:
        """导出论文用图（白底、物理坐标轴）：剖面图 / wiggle / 波形图。"""
        content = dlg.content()
        if content == "wave_image":
            return [self.export_wave_figure(dlg)]
        if content == "wiggle_image":
            return [self.export_wiggle_figure(dlg)]
        return self.export_slice_figures(dlg, progress, cancel)

    def export_slice_figures(self, dlg, progress, cancel=None) -> list[str]:
        """把每份数据的当前剖面重画成一张密度图。"""
        host = self.host
        scope_all = dlg.dataset_scope() == "all"
        sel = [k for k in range(len(host.datasets)) if scope_all or k == host.active]
        base = Path(dlg.path())
        suffix = ExportDialog.SUFFIX[dlg.fmt()]
        options = self._options_of(dlg)
        made: list[str] = []
        count = max(1, len(sel))
        for i, k in enumerate(sel):
            if cancel is not None and cancel():
                break
            plot = self.build_slice_plot(k, dlg)
            names = host._dataset_label(k)
            out = (base if count == 1 else
                   base.with_name(f"{base.stem}_d{k + 1}{base.suffix or suffix}"))
            view2d.export_figure(plot, str(out), dlg.fmt(), options)
            plot.close()
            made.append(str(out))
            progress((i + 1) / count, f"绘制第 {i + 1}/{count} 张图：{names}")
        return made

    def figure_wiggle_set(self, k: int, shared: float | None = None,
                          line_styles=None) -> tuple:
        """导出图里用的 wiggle 数据组（全分辨率 + 该数据的色标 + 线型）。"""
        host = self.host
        img, clim = host._panel_image(k, full=True)
        finite = np.abs(img[np.isfinite(img)]) if img.size else np.empty(0)
        scale = (float(shared) if shared
                 else (float(np.percentile(finite, 99)) if finite.size else 0.0))
        styles = list(line_styles or host.line_styles)
        return (img, clim, scale or 1.0, styles[k % len(styles)])

    def export_wave_figure(self, dlg) -> str:
        """把当前单道波形重画成一张论文图（白底、无网格、坐标轴带单位、带图例）。"""
        plot = self.build_wave_plot(dlg)
        out = str(dlg.path())
        view2d.export_figure(plot, out, dlg.fmt(), self._options_of(dlg))
        plot.close()
        return out

    def export_wiggle_figure(self, dlg) -> str:
        """纯 wiggle 剖面导出（对比模式叠加为一张）。"""
        plot = self.build_wiggle_plot(dlg)
        out = str(dlg.path())
        view2d.export_figure(plot, out, dlg.fmt(), self._options_of(dlg))
        plot.close()
        return out

    def preview_figure(self, dlg) -> QtGui.QImage:
        """按最终像素尺寸渲染当前图；不写文件，供导出前预览。"""
        content = dlg.content()
        if content == "wave_image":
            plot = self.build_wave_plot(dlg)
        elif content == "wiggle_image":
            plot = self.build_wiggle_plot(dlg)
        else:
            plot = self.build_slice_plot(self.host.active, dlg)
        image = view2d.render_figure_image(plot, self._options_of(dlg))
        plot.close()
        return image

    def show_preview(self, dlg) -> None:
        try:
            image = self.preview_figure(dlg)
        except Exception as exc:
            self.host._error("预览失败", f"{type(exc).__name__}: {exc}")
            return
        options = self._options_of(dlg)
        px_w, px_h = options.pixel_size()
        info = (f"目标尺寸：{px_w} × {px_h} px　"
                f"{options.width_mm:g} × {options.height_mm:g} mm　"
                f"{options.dpi} DPI")
        FigurePreviewDialog(image, info, dlg).exec()
