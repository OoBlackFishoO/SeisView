"""导出出图参数：物理尺寸、DPI、透明背景、色标位置与预览。"""

from __future__ import annotations

import os
import tempfile
import unittest

import numpy as np
from golden_utils import ensure_app, make_window, synthetic_volume

from PySide6 import QtGui, QtTest

from seisview import view2d
from seisview.figure_options import ExportFigureOptions


class FigureOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    def test_pixel_size_mm_and_dpi(self) -> None:
        opt = ExportFigureOptions(width_mm=180, height_mm=130, dpi=300)
        self.assertEqual(opt.pixel_size(), (2126, 1535))
        self.assertEqual(opt.font_px(), 58)

    def test_png_size_dpi_and_transparency(self) -> None:
        img = np.random.default_rng(1).standard_normal((20, 30)).astype("float32")
        opt = ExportFigureOptions(width_mm=90, height_mm=60, dpi=150,
                                  transparent=True, colorbar=True)
        plot = view2d.build_slice_figure(
            img, (0.0, 30.0, 0.0, 20.0), "seismic", (-3.0, 3.0),
            "R (m)", "T (s)", options=opt)
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            view2d.export_figure(plot, path, "png", opt)
            image = QtGui.QImage(path)
            self.assertEqual((image.width(), image.height()), (531, 354))
            self.assertTrue(image.hasAlphaChannel())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertAlmostEqual(image.dotsPerMeterX(), 5906, delta=2)
        finally:
            plot.close()
            os.unlink(path)

    def test_colorbar_off_and_bottom(self) -> None:
        img = np.zeros((8, 8), dtype="float32")
        for opt in (
            ExportFigureOptions(colorbar=False),
            ExportFigureOptions(colorbar=True, colorbar_pos="bottom"),
        ):
            plot = view2d.build_slice_figure(
                img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=opt)
            image = view2d.render_figure_image(plot, opt)
            self.assertFalse(image.isNull())
            plot.close()

    def test_bottom_colorbar_keeps_plot_aspect(self) -> None:
        """底部色标只吃掉高度；绘图区宽度要相应收窄，不能把剖面横向拉宽。"""
        img = np.zeros((20, 30), dtype="float32")

        def aspect(options) -> float:
            plot = view2d.build_slice_figure(
                img, (0.0, 900.0, 0.0, 1.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=options)
            try:
                view2d._show_offscreen(plot)
                rect = plot.getViewBox().geometry()
                self.assertGreater(rect.height(), 0)
                return rect.width() / rect.height()
            finally:
                plot.close()

        base = aspect(ExportFigureOptions(colorbar=False))
        bottom = aspect(ExportFigureOptions(colorbar=True, colorbar_pos="bottom"))
        self.assertAlmostEqual(bottom, base, delta=base * 0.01)
        # 底部色标条与收窄后的绘图区等宽
        plot = view2d.build_slice_figure(
            img, (0.0, 900.0, 0.0, 1.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)",
            options=ExportFigureOptions(colorbar=True, colorbar_pos="bottom"))
        try:
            view2d._show_offscreen(plot)
            lay = plot.getPlotItem().layout
            cbar = lay.itemAt(5, 1)
            self.assertAlmostEqual(cbar.geometry().width(),
                                   plot.getViewBox().geometry().width(), delta=2.0)
        finally:
            plot.close()

    def test_rightmost_tick_label_is_not_clipped(self) -> None:
        """无色标时最右端的刻度数字要完整落在图幅内，且仍与刻度线对齐。"""
        from PySide6 import QtCore

        img = np.zeros((8, 8), dtype="float32")
        opt = ExportFigureOptions(colorbar=False, x_tick_major=100.0)
        plot = view2d.build_slice_figure(
            img, (0.0, 900.0, 0.0, 1.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=opt)
        try:
            view2d._show_offscreen(plot)
            axis = plot.getAxis("bottom")
            picture = QtGui.QPicture()
            painter = QtGui.QPainter(picture)
            specs = axis.generateDrawSpecs(painter)
            painter.end()
            texts = specs[2]
            self.assertTrue(texts)
            # 所有刻度数字都在图幅（PlotItem 矩形）内
            frame = plot.getPlotItem().rect()
            for rect, _flags, _text in texts:
                mapped = axis.mapRectToParent(rect)
                self.assertTrue(QtCore.QRectF(frame).contains(mapped),
                                (mapped.getRect(), frame.getRect()))
            # 最后一个数字的中心仍在 900 刻度线上，没有被平移对齐
            last = max(texts, key=lambda t: t[0].right())
            tick_x = axis.mapToParent(
                QtCore.QPointF(axis.geometry().width(), 0.0)).x()
            center_x = axis.mapToParent(last[0].center()).x()
            self.assertAlmostEqual(center_x, tick_x, delta=1.5)
        finally:
            plot.close()

    def test_force_edge_ticks(self) -> None:
        """开启后，即使自定义间隔不落在端点上，两端也补出刻度与数字。"""
        img = np.zeros((8, 8), dtype="float32")
        cases = (
            ("bottom", {"x_tick_major": 80.0, "x_edge_ticks": True}, 0.0, 900.0),
            ("left", {"y_tick_major": 0.3, "y_edge_ticks": True}, 0.0, 1.0),
        )
        for side, kwargs, lo, hi in cases:
            opt = ExportFigureOptions(colorbar=False, **kwargs)
            plot = view2d.build_slice_figure(
                img, (0.0, 900.0, 0.0, 1.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=opt)
            try:
                values = plot.getAxis(side).tickValues(lo, hi, 1000)[0][1]
                self.assertIn(lo, values)
                self.assertIn(hi, values)
            finally:
                plot.close()
            # 不勾选时不额外补端点（900 不在 80 m 间隔上）
            quiet = ExportFigureOptions(
                colorbar=False,
                **{k: v for k, v in kwargs.items() if not k.endswith("edge_ticks")})
            plot = view2d.build_slice_figure(
                img, (0.0, 900.0, 0.0, 1.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=quiet)
            try:
                values = plot.getAxis(side).tickValues(lo, hi, 1000)[0][1]
                self.assertNotIn(hi, values)
            finally:
                plot.close()

    def test_line_pen_uses_flat_cap(self) -> None:
        """虚线/点线用平头笔帽，空位才符合名义的 4:2 / 1:2 / 4:2:1:2。"""
        from PySide6 import QtCore

        for dash in ("solid", "dash", "dot", "dashdot"):
            self.assertEqual(
                view2d.line_pen(("#111827", dash), 3.0).capStyle(),
                QtCore.Qt.PenCapStyle.FlatCap)

    def test_svg_writes_physical_mm(self) -> None:
        img = np.zeros((8, 8), dtype="float32")
        opt = ExportFigureOptions(width_mm=90, height_mm=60, dpi=150)
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=opt, out_fmt="svg", title="demo")
        fd, path = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        try:
            view2d.export_figure(plot, path, "svg", opt)
            with open(path, encoding="utf-8") as fh:
                text = fh.read(600)
            self.assertIn('width="90mm"', text)
            self.assertIn('height="60mm"', text)
        finally:
            plot.close()
            os.unlink(path)

    def test_title_only_no_annotation_on_figure(self) -> None:
        """图上只画用户标题；序号 / 道号改在设置面板显示。"""
        import pyqtgraph as pg

        img = np.zeros((8, 8), dtype="float32")
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=ExportFigureOptions(), title="Demo")
        try:
            item = plot.getPlotItem()
            self.assertEqual(
                [i for i in item.items if isinstance(i, pg.TextItem)], [])
            self.assertEqual(item.titleLabel.text, "Demo")
            self.assertEqual(item.titleLabel.opts.get("size"), "58px")
            # 14 pt @300 DPI 比 pyqtgraph 默认的 30 px 标题行高更高，不能裁字
            self.assertGreaterEqual(item.titleLabel.maximumHeight(), 58)
        finally:
            plot.close()

    def test_colorbar_keeps_gap_without_label(self) -> None:
        """关掉色标文字后，色条与图像之间仍然有留白。"""
        img = np.zeros((8, 8), dtype="float32")
        for pos in ("right", "bottom"):
            opt = ExportFigureOptions(colorbar=True, colorbar_pos=pos,
                                      colorbar_label=False)
            plot = view2d.build_slice_figure(
                img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=opt)
            try:
                lay = plot.getPlotItem().layout
                if pos == "right":
                    self.assertGreater(lay.columnMinimumWidth(4), 0)
                    self.assertIsNotNone(lay.itemAt(2, 5))
                else:
                    self.assertGreater(lay.rowMinimumHeight(4), 0)
                    self.assertIsNotNone(lay.itemAt(5, 1))
                self.assertGreater(lay.getContentsMargins()[1], 0)
            finally:
                plot.close()

    def test_trace_figure_time_range(self) -> None:
        """波形图按选定的时间段定视野，而不是整条记录。"""
        t = np.linspace(0.0, 1.0, 201)
        entries = [(t, np.sin(20.0 * t), ("#111827", "solid"), "Data 1")]
        plot = view2d.build_trace_figure(entries, x_range=(0.2, 0.45))
        try:
            x0, x1 = plot.getViewBox().viewRange()[0]
            self.assertAlmostEqual(x0, 0.2, places=6)
            self.assertAlmostEqual(x1, 0.45, places=6)
        finally:
            plot.close()

    def test_export_dialog_wave_time_range(self) -> None:
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": win.datasets[0].vol,
                      "pos": win.datasets[0].pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), parent=win)
                try:
                    dlg.content_ctl.set_value("wave_image")
                    dlg._on_content()
                    self.assertFalse(dlg.time_body.isHidden())
                    self.assertEqual(dlg.spin_t0.singleStep(), 0.1)
                    self.assertEqual(dlg.spin_t1.singleStep(), 0.1)
                    self.assertIsNone(dlg.time_range())      # 默认整段
                    dlg.spin_t0.setValue(0.005)
                    dlg.spin_t1.setValue(0.02)
                    self.assertEqual(dlg.time_range(), (0.005, 0.02))
                    image = win.export_service.preview_figure(dlg)
                    self.assertFalse(image.isNull())
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    self.assertTrue(dlg.time_body.isHidden())
                    self.assertIsNone(dlg.time_range())
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_slice_info_in_settings_panel(self) -> None:
        """剖面序号 + 目标道号显示在设置面板，而不是画到导出图上。"""
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            ds = win.datasets[0]
            ds.mode = "shot"
            ds.pos["shot"], ds.pos["recv"] = 2, 5
            win._update_slice_info()
            self.assertIn("炮点 S = 2", win.slice_info.text())
            self.assertIn("目标道 S = 2  R = 5", win.slice_info.text())
            ds.mode = "time"
            ds.pos["time"] = 7
            win._update_slice_info()
            self.assertIn("时间 T = 7", win.slice_info.text())
            win.clear_data()
            self.assertEqual(win.slice_info.text(), "当前：—")
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_figure_language_switch(self) -> None:
        """图注文字支持中 / 英切换。"""
        from seisview.export_service import ExportService

        self.assertEqual(ExportService.figure_labels("shot", "zh")[0],
                         "检波器 R (m)")
        self.assertEqual(ExportService.figure_labels("shot", "en")[0],
                         "Receiver R (m)")
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": win.datasets[0].vol,
                      "pos": win.datasets[0].pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), parent=win)
                try:
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    dlg.combo_lang.setCurrentIndex(1)          # English
                    self.assertEqual(dlg.figure_options().language, "en")
                    plot = win.export_service.build_slice_plot(0, dlg)
                    try:
                        self.assertEqual(plot.getAxis("bottom").labelText,
                                         "Receiver R (m)")
                        self.assertEqual(plot.getAxis("left").labelText,
                                         "Time T (s)")
                        # 300 DPI 下轴线要按物理线宽画，而不是默认的 1 px
                        self.assertGreaterEqual(
                            plot.getAxis("bottom").pen().widthF(), 3.0)
                    finally:
                        plot.close()
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_four_sided_axes_and_ticks(self) -> None:
        """四边都有坐标轴；只保留主刻度；刻度方向可切换。"""
        img = np.zeros((8, 8), dtype="float32")
        for inside in (True, False):
            opt = ExportFigureOptions(ticks_inside=inside)
            plot = view2d.build_slice_figure(
                img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=opt)
            try:
                for side in ("left", "right", "top", "bottom"):
                    axis = plot.getAxis(side)
                    self.assertTrue(axis.isVisible(), side)
                    self.assertEqual(axis.style["maxTickLevel"], 0)
                tick_len = plot.getAxis("bottom").style["tickLength"]
                self.assertEqual(tick_len > 0, not inside)
                # 上 / 右两边只画刻度，不重复数字
                self.assertFalse(plot.getAxis("top").style["showValues"])
                self.assertFalse(plot.getAxis("right").style["showValues"])
            finally:
                plot.close()

    def test_axis_label_can_be_customized_or_hidden(self) -> None:
        """轴标题可自定义；传空串时不显示。"""
        img = np.zeros((8, 8), dtype="float32")
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "Distance", "Time", options=ExportFigureOptions())
        try:
            self.assertEqual(plot.getAxis("bottom").labelText, "Distance")
            self.assertEqual(plot.getAxis("left").labelText, "Time")
        finally:
            plot.close()
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "", "", options=ExportFigureOptions())
        try:
            self.assertFalse(plot.getAxis("bottom").label.isVisible())
            self.assertFalse(plot.getAxis("left").label.isVisible())
        finally:
            plot.close()

    def test_export_dialog_axis_label_fields(self) -> None:
        """对话框里的轴标题默认自动填写，改过之后不随语言切换覆盖。"""
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": win.datasets[0].vol,
                      "pos": win.datasets[0].pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), mode="shot", parent=win)
                try:
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    self.assertEqual(dlg.edit_xlabel.text(), "检波器 R (m)")
                    self.assertFalse(dlg.chk_cbar_label.isChecked())
                    dlg.combo_lang.setCurrentIndex(1)          # English
                    self.assertEqual(dlg.edit_xlabel.text(), "Receiver R (m)")
                    dlg.edit_xlabel.setText("My X")
                    dlg.combo_lang.setCurrentIndex(0)          # 中文
                    self.assertEqual(dlg.edit_xlabel.text(), "My X")
                    dlg.edit_ylabel.setText("")                # 隐藏纵轴标题
                    dlg.combo_xnums.setCurrentIndex(1)         # 数字到上方
                    dlg.combo_ylabel_side.setCurrentIndex(1)   # 标题到右侧
                    opt = dlg.figure_options()
                    self.assertEqual(opt.xlabel_override, "My X")
                    self.assertEqual(opt.ylabel_override, "")
                    self.assertEqual(opt.x_numbers_side, "top")
                    self.assertEqual(opt.ylabel_side, "right")
                    plot = win.export_service.build_slice_plot(0, dlg)
                    try:
                        self.assertEqual(plot.getAxis("left").labelText, "")
                        self.assertFalse(plot.getAxis("left").label.isVisible())
                    finally:
                        plot.close()
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_offset_axis_for_shot_slice(self) -> None:
        """共炮点剖面可把横轴从检波器位置换成偏移距（R − S）。"""
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            ds = win.datasets[0]
            ds.mode = "shot"
            ds.pos["shot"] = 2
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": ds.vol, "pos": ds.pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), mode="shot", parent=win)
                try:
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    dlg.combo_xaxis.setCurrentIndex(1)          # 偏移距
                    self.assertEqual(dlg.edit_xlabel.text(), "偏移距 (m)")
                    opt = dlg.figure_options()
                    self.assertTrue(opt.offset_axis)
                    self.assertIsNone(opt.xlabel_override)      # 自动文字
                    plot = win.export_service.build_slice_plot(0, dlg)
                    try:
                        self.assertEqual(plot.getAxis("bottom").labelText,
                                         "偏移距 (m)")
                        x0, x1 = plot.getViewBox().viewRange()[0]
                        shift = ds.pos["shot"] * ds.vol.ds
                        width = ds.vol.nr * ds.vol.dx
                        self.assertAlmostEqual((x0 + x1) / 2, width / 2 - shift,
                                               delta=width * 0.05)
                    finally:
                        plot.close()
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_axis_numbers_and_labels_can_switch_sides(self) -> None:
        """刻度数字和轴标题可以分别换到上 / 右，并保留 0 端点标签。"""
        img = np.zeros((8, 8), dtype="float32")
        opt = ExportFigureOptions(x_numbers_side="top", y_numbers_side="right",
                                  xlabel_side="top", ylabel_side="right")
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=opt)
        try:
            self.assertTrue(plot.getAxis("top").style["showValues"])
            self.assertFalse(plot.getAxis("bottom").style["showValues"])
            self.assertTrue(plot.getAxis("right").style["showValues"])
            self.assertFalse(plot.getAxis("left").style["showValues"])
            self.assertEqual(plot.getAxis("top").labelText, "R (m)")
            self.assertEqual(plot.getAxis("right").labelText, "T (s)")
            # 端点标签（0）允许探出轴矩形，否则会被当成越界丢掉
            for side in ("top", "right", "bottom", "left"):
                self.assertGreaterEqual(
                    plot.getAxis(side).style["hideOverlappingLabels"], 16)
        finally:
            plot.close()

    def test_legend_toggle(self) -> None:
        """wiggle / 波形图的图例开关：关掉后不再创建图例。"""
        img = np.zeros((20, 30), dtype="float32")
        sets = [(img, (-1.0, 1.0), 1.0, ("#111827", "solid")),
                (img, (-1.0, 1.0), 1.0, ("#D62828", "solid"))]
        t = np.linspace(0.0, 1.0, 21)
        entries = [(t, np.sin(t), ("#111827", "solid"), "Data 1"),
                   (t, np.cos(t), ("#D62828", "solid"), "Data 2")]
        for flag in (True, False):
            opt = ExportFigureOptions(legend=flag)
            plot = view2d.build_wiggle_figure(
                img, (0.0, 30.0, 0.0, 20.0), "R (m)", "T (s)", sets,
                options=opt)
            try:
                self.assertEqual(plot.getPlotItem().legend is not None, flag)
            finally:
                plot.close()
            plot = view2d.build_trace_figure(entries, options=opt)
            try:
                self.assertEqual(plot.getPlotItem().legend is not None, flag)
            finally:
                plot.close()

    def test_wiggle_image_content_and_overlay(self) -> None:
        """wiggle 剖面是独立导出项；对比模式下叠加成一张图。"""
        import pyqtgraph as pg

        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            win._append_dataset(synthetic_volume(seed=2), "", "v2")
            QtTest.QTest.qWait(250)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": f"d{k + 1}", "vol": ds.vol, "pos": ds.pos}
                     for k, ds in enumerate(win.datasets)], win.active, tmp, "x",
                    line_styles=list(win.line_styles),
                    mode=win.datasets[win.active].mode, parent=win)
                try:
                    dlg.content_ctl.set_value("wiggle_image")
                    dlg._on_content()
                    self.assertFalse(dlg.line_style_box.isHidden())
                    self.assertTrue(dlg.colorbar_box.isHidden())
                    self.assertFalse(dlg.xaxis_box.isHidden())
                    self.assertTrue(dlg.chk_legend.isChecked())
                    plot = win.export_service.build_wiggle_plot(dlg)
                    try:
                        items = plot.getPlotItem().items
                        self.assertTrue(any(isinstance(i, pg.PlotDataItem)
                                            for i in items))
                        self.assertFalse(any(isinstance(i, pg.ImageItem)
                                             for i in items))
                        legend = plot.getPlotItem().legend
                        self.assertIsNotNone(legend)
                        self.assertEqual(len(legend.items), 2)
                    finally:
                        plot.close()
                    # 关掉图例后重新出图：不能留下空图例框
                    dlg.chk_legend.setChecked(False)
                    self.assertFalse(dlg.figure_options().legend)
                    plot = win.export_service.build_wiggle_plot(dlg)
                    try:
                        self.assertIsNone(plot.getPlotItem().legend)
                    finally:
                        plot.close()
                    dlg.chk_legend.setChecked(True)
                    self.assertFalse(
                        win.export_service.preview_figure(dlg).isNull())

                    # 剖面图永远是密度图，不受屏幕“仅显示波形”影响
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    plot = win.export_service.build_slice_plot(0, dlg)
                    try:
                        items = plot.getPlotItem().items
                        self.assertTrue(any(isinstance(i, pg.ImageItem)
                                            for i in items))
                        self.assertFalse(any(isinstance(i, pg.PlotDataItem)
                                             for i in items))
                    finally:
                        plot.close()
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_preview_dialog_can_zoom(self) -> None:
        from seisview.widgets import FigurePreviewDialog

        image = QtGui.QImage(200, 100, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("white"))
        dlg = FigurePreviewDialog(image, "test", parent=None)
        try:
            before = dlg.view.transform().m11()
            dlg.view.zoom(1.25)
            self.assertGreater(dlg.view.transform().m11(), before)
        finally:
            dlg.close()

    def test_preview_returns_image_without_file(self) -> None:
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": win.datasets[0].vol,
                      "pos": win.datasets[0].pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), parent=win)
                dlg.content_ctl.set_value("slice_image")
                dlg._on_content()
                image = win.export_service.preview_figure(dlg)
                self.assertFalse(image.isNull())
                self.assertEqual(os.listdir(tmp), [])
                dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)

    def test_figure_defaults_font_and_line(self) -> None:
        """默认字号 14 pt、线宽 1 pt；刻度间隔默认交给自动。"""
        opt = ExportFigureOptions()
        self.assertEqual(opt.font_pt, 14.0)
        self.assertEqual(opt.line_width_pt, 1.0)
        self.assertEqual(opt.x_tick_major, 0.0)
        self.assertEqual(opt.y_tick_major, 0.0)
        self.assertAlmostEqual(opt.line_width_px(), 300 / 72, places=6)

    def test_custom_tick_spacing_applies(self) -> None:
        """自定义主刻度间隔：四边除以 s 为单位实际生效。"""
        img = np.zeros((8, 8), dtype="float32")
        opt = ExportFigureOptions(x_tick_major=2.0, y_tick_major=1.0)
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=opt)
        try:
            xs = plot.getAxis("bottom").tickValues(0.0, 8.0, 1000)
            self.assertEqual(xs, [(2.0, [0.0, 2.0, 4.0, 6.0, 8.0])])
            self.assertEqual(
                plot.getAxis("top").tickValues(0.0, 8.0, 1000)[0][0], 2.0)
            ys = plot.getAxis("left").tickValues(0.0, 8.0, 1000)
            self.assertEqual(ys[0][0], 1.0)
            self.assertEqual(len(ys[0][1]), 9)
            self.assertEqual(
                plot.getAxis("right").tickValues(0.0, 8.0, 1000)[0][0], 1.0)
        finally:
            plot.close()

    def test_dense_tick_spacing_falls_back_to_auto(self) -> None:
        """间隔密到几百格以上时不照画，交回自动刻度。"""
        img = np.zeros((8, 8), dtype="float32")
        opt = ExportFigureOptions(x_tick_major=0.001)
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=opt)
        try:
            self.assertIsNone(plot.getAxis("bottom")._tickSpacing)
        finally:
            plot.close()

    def test_tick_numbers_set_farther_from_axis(self) -> None:
        """刻度数字与刻度线的间距按 1.2 mm 换算（300 DPI 约 14 px）。"""
        img = np.zeros((8, 8), dtype="float32")
        plot = view2d.build_slice_figure(
            img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
            "R (m)", "T (s)", options=ExportFigureOptions(dpi=300))
        try:
            self.assertGreaterEqual(
                plot.getAxis("bottom").style["tickTextOffset"][1], 14)
            self.assertGreaterEqual(
                plot.getAxis("left").style["tickTextOffset"][0], 14)
        finally:
            plot.close()

    def test_colorbar_has_four_sided_frame(self) -> None:
        """色标条四边都是黑色实线；底部色标按自身高度留足刻度与标题。"""
        from PySide6 import QtCore

        img = np.zeros((8, 8), dtype="float32")
        ink = QtGui.QColor(view2d._FIG_INK).name()
        for pos in ("right", "bottom"):
            opt = ExportFigureOptions(colorbar=True, colorbar_pos=pos,
                                      colorbar_label=True)
            plot = view2d.build_slice_figure(
                img, (0.0, 8.0, 0.0, 8.0), "seismic", (-1.0, 1.0),
                "R (m)", "T (s)", options=opt)
            try:
                lay = plot.getPlotItem().layout
                cbar = (lay.itemAt(2, 5) if pos == "right"
                        else lay.itemAt(5, 1))
                for side in ("left", "right", "top", "bottom"):
                    axis = cbar.getAxis(side)
                    self.assertTrue(axis.isVisible(), f"{pos}/{side}")
                    self.assertEqual(axis.pen().color().name(), ink)
                if pos == "bottom":
                    hint = cbar.sizeHint(
                        QtCore.Qt.SizeHint.PreferredSize).height()
                    self.assertGreaterEqual(lay.rowMinimumHeight(5), hint)
            finally:
                plot.close()

    def test_export_dialog_font_line_and_tick_fields(self) -> None:
        """对话框默认 14 pt / 1 pt、线宽 0.1 步进、刻度间隔单位随图种切换。"""
        win = make_window()
        try:
            win._install_primary(synthetic_volume(), "", "v")
            QtTest.QTest.qWait(150)
            with tempfile.TemporaryDirectory() as tmp:
                from seisview.widgets import ExportDialog
                dlg = ExportDialog(
                    [{"label": "d1", "vol": win.datasets[0].vol,
                      "pos": win.datasets[0].pos}], 0, tmp, "x",
                    line_styles=list(win.line_styles), mode="shot", parent=win)
                try:
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    self.assertEqual(dlg.spin_font_pt.value(), 14.0)
                    self.assertEqual(dlg.spin_line_pt.value(), 1.0)
                    self.assertEqual(dlg.spin_line_pt.singleStep(), 0.1)
                    # 刻度间隔默认填当前轴的整齐间隔，不再显示「自动」
                    self.assertGreater(dlg.spin_xtick.value(), 0.0)
                    self.assertGreater(dlg.spin_ytick.value(), 0.0)
                    self.assertEqual(dlg.spin_xtick.singleStep(), 10.0)  # 米制 +10
                    self.assertEqual(dlg.spin_ytick.singleStep(), 0.1)   # 秒制 +0.1
                    self.assertEqual(dlg.spin_xtick.specialValueText(), "自动")
                    self.assertEqual(dlg.unit_xtick.text(), "m")
                    self.assertEqual(dlg.unit_ytick.text(), "s")
                    dlg.spin_xtick.setValue(5.0)
                    dlg.spin_ytick.setValue(0.5)
                    dlg.chk_xedge.setChecked(True)
                    dlg.chk_yedge.setChecked(True)
                    opt = dlg.figure_options()
                    self.assertEqual(opt.x_tick_major, 5.0)
                    self.assertEqual(opt.y_tick_major, 0.5)
                    self.assertTrue(opt.x_edge_ticks)
                    self.assertTrue(opt.y_edge_ticks)
                    dlg.content_ctl.set_value("wave_image")
                    dlg._on_content()
                    self.assertEqual(dlg.unit_xtick.text(), "s")
                    self.assertEqual(dlg.unit_ytick.text(), "")
                    self.assertGreater(dlg.spin_xtick.value(), 0.0)
                    self.assertGreater(dlg.spin_ytick.value(), 0.0)
                    self.assertEqual(dlg.spin_xtick.singleStep(), 0.1)
                finally:
                    dlg.close()
        finally:
            win.close()
            win.deleteLater()
            QtTest.QTest.qWait(10)


if __name__ == "__main__":
    unittest.main()
