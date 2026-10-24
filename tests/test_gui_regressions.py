"""P0 / P1 的界面级回归：清空、复位、滚动、尺寸锚、换序、侧边栏、对比同步。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SEISVIEW_NO_PERSIST", "1")

import numpy as np
from PySide6 import QtCore, QtTest, QtWidgets
from shiboken6 import isValid

from seisview import main_window as mw


def _volume(scale=1.0, seed=1) -> mw.SeisVolume:
    rng = np.random.default_rng(seed)
    data = (rng.standard_normal((4, 6, 24)) * scale).astype(np.float32)
    return mw.SeisVolume(name=f"v{seed}", data=data)


class _FakeScreen:
    """offscreen 平台只有 800×800，测试里换成足够大的虚拟屏幕。"""

    def availableGeometry(self):
        return QtCore.QRect(0, 0, 1920, 1080)


class GuiRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from seisview import view3d as view3d_module
        cls.view3d_module = view3d_module
        cls._orig_create = view3d_module.create_view3d
        # 无头环境不建 OpenGL；三维逻辑由 test_face_pipeline 的纯函数覆盖
        view3d_module.create_view3d = lambda parent=None: None

    @classmethod
    def tearDownClass(cls):
        cls.view3d_module.create_view3d = cls._orig_create

    def setUp(self):
        self.win = mw.MainWindow()
        self.win.screen = lambda: _FakeScreen()
        self._load(3)
        self.win.show()
        QtTest.QTest.qWait(60)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        QtWidgets.QApplication.processEvents()

    def _load(self, n=3, scales=None):
        scales = scales or [1.0, 4.0, 12.0]
        self.win._install_primary(_volume(scales[0], seed=1), "", "v1")
        for i in range(1, n):
            self.win._append_dataset(_volume(scales[i], seed=i + 1), "", f"v{i + 1}")
        self.win._refresh_all()

    # ---------------------------------------------------------------- A4
    def test_clear_compare_resets_everything(self):
        old_views = [p.view for p in self.win.panels]
        self.assertGreaterEqual(len(old_views), 2)
        self.win.clear_data()
        QtTest.QTest.qWait(60)
        self.assertEqual(len(self.win.datasets), 0)
        self.assertEqual(len(self.win.panels), 0)
        for view in old_views:
            if isValid(view):                 # 面板已被销毁也是“没有残留”
                self.assertIsNone(view._img.image)
                self.assertFalse(view._line.isVisible())
        self.assertTrue(self.win.slice_empty.isVisible())
        for curve in self.win.trace_view._curves:
            data = curve.getData()
            self.assertTrue(data[0] is None or len(data[0]) == 0)
        # 清空后重新载入：新面板必须正常出图，不能沿用旧状态
        self.win._install_primary(_volume(2.0, seed=9), "", "new")
        self.win._refresh_all()
        QtTest.QTest.qWait(40)
        self.assertEqual(len(self.win.panels), 1)
        self.assertIsNotNone(self.win.panels[0].view._img.image)

    # ---------------------------------------------------------------- A9 / A7
    def test_fit_range_keeps_trace_and_reference(self):
        panel = self.win.panels[0]
        self.win._update_references()
        value = panel.view._line.value()
        pos = {k: dict(ds.pos) for k, ds in enumerate(self.win.datasets)}
        picked = []
        panel.view.picked.connect(lambda c, r: picked.append((c, r)))
        panel.view._fit_range()
        self.assertEqual(panel.view._line.value(), value)
        self.assertEqual(pos, {k: dict(ds.pos) for k, ds in enumerate(self.win.datasets)})
        self.assertEqual(picked, [])

    def test_auto_button_is_not_a_pick(self):
        panel = self.win.panels[0]
        btn = panel.view.getPlotItem().autoBtn
        btn.setVisible(True)
        QtTest.QTest.qWait(20)
        center = btn.mapToScene(btn.boundingRect().center())
        local = panel.view.mapFromScene(center)
        self.assertTrue(panel.view._on_plot_button(QtCore.QPointF(local)))
        middle = QtCore.QPointF(panel.view.width() / 2.0, panel.view.height() / 2.0)
        self.assertFalse(panel.view._on_plot_button(middle))
        # 真正点一次：必须只复位视野，不能顺手取道（绿线错位的原 bug）
        picked = []
        panel.view.picked.connect(lambda c, r: picked.append((c, r)))
        panel.view.getViewBox().setRange(xRange=(1, 2), yRange=(1, 2))
        QtTest.QTest.mouseClick(panel.view.viewport(),
                                QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, local)
        QtTest.QTest.qWait(20)
        self.assertEqual(picked, [])
        xr, yr = panel.view.getViewBox().viewRange()
        x0, x1, y0, y1 = panel.view._extent
        self.assertAlmostEqual(xr[0], x0)
        self.assertAlmostEqual(xr[1], x1)
        self.assertAlmostEqual(yr[0], y0)
        self.assertAlmostEqual(yr[1], y1)

    def test_double_click_undoes_first_release_pick(self):
        before = [dict(ds.pos) for ds in self.win.datasets]
        active_before = self.win.active
        self.win._on_pick(0, 2, 3)
        self.assertNotEqual(before, [dict(ds.pos) for ds in self.win.datasets])
        self.win._on_view_double_click(0)
        self.assertEqual(before, [dict(ds.pos) for ds in self.win.datasets])
        self.assertEqual(self.win.active, active_before)

    def test_hover_left_shows_dash(self):
        panel = self.win.panels[0]
        panel.view.hover_left.emit()
        self.assertEqual(panel.hover.text(), "—")

    # ---------------------------------------------------------------- A1
    def test_group_toggle_keeps_scroll_position(self):
        self.win._set_all_groups(True, animate=False)
        QtTest.QTest.qWait(40)
        bar = self.win.left_body.verticalScrollBar()
        if bar.maximum() <= 2:
            self.skipTest("侧边栏内容不足以产生滚动")
        bar.setValue(max(1, bar.maximum() // 2))
        value = bar.value()
        self.win.cards["compare"].set_expanded(False, animate=False)
        QtTest.QTest.qWait(260)
        self.assertLessEqual(abs(bar.value() - value), 2)

    # ---------------------------------------------------------------- A10
    def test_user_size_anchor_survives_layout_switch(self):
        self.win.resize(1180, 760)
        QtTest.QTest.qWait(30)
        expected = self.win.size()
        self.assertEqual(self.win._user_size, (expected.width(), expected.height()))
        for key in ("A", "B", "BT", "AL", "SR", "TR", "ST"):
            self.win._apply_layout(key)
            QtTest.QTest.qWait(280)          # 等窗口尺寸动画跑完
            # 用户尺寸是下限：切换构图绝不主动缩小
            self.assertGreaterEqual(self.win.width(), expected.width() - 2, key)
            self.assertGreaterEqual(self.win.height(), expected.height() - 2, key)

    # ---------------------------------------------------------------- A11
    def test_reorder_keeps_window_and_panel_sizes(self):
        sizes = list(self.win.slice_split.sizes())
        width, height = self.win.width(), self.win.height()
        first, second = self.win.datasets[0], self.win.datasets[1]
        self.win._swap_panel_order(self.win.panels[0], self.win.panels[1])
        QtTest.QTest.qWait(30)
        self.assertIs(self.win.datasets[0], second)
        self.assertIs(self.win.datasets[1], first)
        self.assertEqual((self.win.width(), self.win.height()), (width, height))
        self.assertEqual(self.win.slice_split.sizes(), sizes)

    def test_reset_button_equalizes_compare_panels(self):
        """对比模式下拖动改变各剖面宽度后，刷新键应把它们恢复成等宽。"""
        QtTest.QTest.qWait(200)               # 等载入后的面板重建落定
        sp = self.win.slice_split
        self.assertGreaterEqual(sp.count(), 2)
        sp.setSizes([500] + [10] * (sp.count() - 1))
        QtTest.QTest.qWait(30)
        self.assertGreater(max(sp.sizes()) - min(sp.sizes()), 10)
        self.win.reset_panel_layout()
        QtTest.QTest.qWait(80)
        self.assertLessEqual(max(sp.sizes()) - min(sp.sizes()), 2)

    # ---------------------------------------------------------------- B3
    def test_sidebar_collapse_keeps_workspace_size(self):
        # 窗口要足够宽，收起侧边栏后总宽度仍高于最小尺寸，才能验证“工作区像素不变”
        self.win.resize(1100, 760)
        QtTest.QTest.qWait(40)
        work_w = self.win.workspace.width()
        panel_w = self.win.panels[0].width()
        win_w = self.win.width()
        self.win._set_region_visible("left", False, animate=False)
        QtTest.QTest.qWait(50)
        self.assertLessEqual(abs(self.win.workspace.width() - work_w), 4)
        self.assertLessEqual(abs(self.win.panels[0].width() - panel_w), 4)
        self.assertLess(self.win.width(), win_w)
        self.win._set_region_visible("left", True, animate=False)
        QtTest.QTest.qWait(50)
        self.assertLessEqual(abs(self.win.workspace.width() - work_w), 4)
        self.assertLessEqual(abs(self.win.width() - win_w), 4)

    # ---------------------------------------------------------------- B8
    def test_sync_switch_broadcasts_and_isolates(self):
        self.win.active = 0
        self.win.mode = "shot"
        self.win.chk_sync.setChecked(True)
        self.win._on_slice_index(3)
        self.assertEqual({ds.pos["shot"] for ds in self.win.datasets}, {3})

        self.win.chk_sync.setChecked(False)
        other = self.win.datasets[1].pos["shot"]
        self.win._on_slice_index(1)
        self.assertEqual(self.win.datasets[1].pos["shot"], other)

    def test_shared_clim_and_compact_legend(self):
        self.win._refresh_all()
        self.assertTrue(self.win._clims)
        self.assertEqual(len(set(self.win._clims)), 1)
        self.win._sync_trace_legend(force=True)
        self.assertTrue(self.win.trace_legend.isVisible())
        self.assertEqual(self.win._trace_legend_lay.count(), 6)

    def test_hover_does_not_resize_compare_panels(self):
        """鼠标指到某幅剖面时，读数变长但不能把相邻剖面挤窄。"""
        self.win._solo("slice")
        QtTest.QTest.qWait(300)
        self.win.resize(1500, 760)
        QtTest.QTest.qWait(100)
        sizes = list(self.win.slice_split.sizes())
        widths = [p.width() for p in self.win.panels]
        self.assertGreaterEqual(widths[0], 300)
        for k, (col, row) in ((0, (9999, 9999)), (1, (0, 0)), (2, (1234, 4321))):
            self.win._on_hover(k, col, row)
            QtTest.QTest.qWait(40)
            self.assertLessEqual(
                max(abs(a - b) for a, b in
                    zip(sizes, self.win.slice_split.sizes())), 2)
            self.assertLessEqual(
                max(abs(a - b) for a, b in
                    zip(widths, [p.width() for p in self.win.panels])), 2)
        # 读数标签自身也不能再随文字改最小宽度
        for p in self.win.panels:
            self.assertEqual(p.hover.minimumSizeHint().width(), 0)

    def test_slice_group_is_one_drag_unit(self):
        """剖面组标题拖整组；组内单图标题只用于换序。"""
        self.assertIs(self.win._drag_watch.get(self.win.slice_header),
                      self.win.slice_wrap)
        self.assertEqual(self.win._drag_kind(self.win.slice_wrap), "slice")
        self.win._begin_drag(self.win.slice_header, self.win.slice_wrap,
                             QtCore.QPoint(10, 10))
        self.assertTrue(self.win._drag["group"])
        self.assertFalse(self.win._drag["reorder_only"])
        self.win._drag = None

        panel = self.win.panels[0]
        self.win._begin_drag(panel.header, panel, QtCore.QPoint(10, 10))
        self.assertFalse(self.win._drag["group"])
        self.assertTrue(self.win._drag["reorder_only"])
        self.win._drag = None
        # 单数据时组内不显示第二个六点
        self.win._install_primary(_volume(1.5, seed=99), "", "single")
        self.win._refresh_all()
        QtTest.QTest.qWait(40)
        self.assertFalse(self.win.panels[0].grab_handle.isVisible())

    # ---------------------------------------------------------------- A6 / 导出
    def test_slice_export_uses_current_clim_settings(self):
        """导出剖面 PNG 必须复用屏幕当前的手动半宽 / 对比度窗口。"""
        self.win.chk_pure.setChecked(False)
        self.win.clim_combo.setCurrentIndex(
            self.win.clim_combo.findData("manual"))
        self.win.spin_manual.setValue(2.5)
        self.win.contrast.set_value(200)
        QtTest.QTest.qWait(30)

        expected = self.win._scale_window(self.win._shared_base_clim())
        self.assertEqual(expected, (-1.25, 1.25))
        # 屏幕、全分辨率数组、真正传给绘图函数的三者必须是同一个窗口
        np.testing.assert_allclose(self.win._panel_image(0)[1], expected)
        np.testing.assert_allclose(self.win._panel_image(0, full=True)[1], expected)

        captured = {}

        class _Plot:
            def close(self):
                pass

        def fake_build(img, extent, cmap, clim, *args, **kwargs):
            captured["clim"] = clim
            return _Plot()

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        class _Dlg:
            def content(self):
                return "slice_image"

            def dataset_scope(self):
                return "active"

            def path(self):
                return str(Path(tmp.name) / "slice.png")

            def fmt(self):
                return "png"

        orig_build = mw.view2d.build_slice_figure
        orig_export = mw.view2d.export_figure
        mw.view2d.build_slice_figure = fake_build
        mw.view2d.export_figure = lambda *a, **kw: None
        try:
            made = self.win._export_slice_figures(_Dlg(), lambda *_: None)
        finally:
            mw.view2d.build_slice_figure = orig_build
            mw.view2d.export_figure = orig_export

        self.assertEqual(len(made), 1)
        np.testing.assert_allclose(captured["clim"], expected)

    def test_contrast_refresh_is_coalesced_and_reuses_raw_cache(self):
        """拖动对比度只重做上色：不重算切片，也不逐格全量刷新。"""
        raw_key = (0, False)
        raw_before = self.win._raw_cache[raw_key][0]
        base_before = self.win._shared_base_clim()
        calls = []
        orig_refresh = self.win._refresh_panel

        def spy(k):
            calls.append(k)
            return orig_refresh(k)

        self.win._refresh_panel = spy
        try:
            self.win.contrast.set_value(200)
            self.assertEqual(calls, [])          # 定时器未到，先不重绘
            QtTest.QTest.qWait(60)
        finally:
            del self.win._refresh_panel
        self.assertGreaterEqual(len(calls), 1)
        # 切片数组与基准窗口都没有被重算
        self.assertIs(self.win._raw_cache[raw_key][0], raw_before)
        self.assertIs(self.win._shared_base_clim(), base_before)
        expected = self.win._scale_window(base_before)
        np.testing.assert_allclose(self.win._panel_image(0)[1], expected)

    def test_manual_scope_autofills_p98_once(self):
        """首次切到手动时自动填入 P98 推荐值，之后不覆盖用户改过的值。"""
        self.win.clim_combo.setCurrentIndex(
            self.win.clim_combo.findData("manual"))
        QtTest.QTest.qWait(20)
        sample = np.concatenate(
            [self.win._base_sample(k) for k in range(len(self.win.datasets))])
        want = float(np.percentile(np.abs(sample), 98.0))
        self.assertAlmostEqual(self.win.spin_manual.value(), want, places=6)
        lo, hi = self.win._shared_base_clim()
        self.assertAlmostEqual(0.5 * (hi - lo), want, places=6)

        self.win.spin_manual.setValue(want / 2.0)
        self.win.clim_combo.setCurrentIndex(
            self.win.clim_combo.findData("auto"))
        self.win.clim_combo.setCurrentIndex(
            self.win.clim_combo.findData("manual"))
        QtTest.QTest.qWait(20)
        self.assertAlmostEqual(self.win.spin_manual.value(), want / 2.0, places=6)

    def test_first_load_does_not_animate_window(self):
        """首次载入直接落到最终尺寸，避免空窗口 → 有数据的中间帧闪烁。"""
        self.win.clear_data()
        QtTest.QTest.qWait(350)
        self.assertFalse(self.win.datasets)
        called = []
        orig = self.win._animate_layout_change

        def spy(*a, **kw):
            called.append(1)
            return orig(*a, **kw)

        self.win._animate_layout_change = spy
        try:
            self.win._install_primary(_volume(2.0, seed=9), "", "first")
        finally:
            del self.win._animate_layout_change
        self.assertEqual(called, [])
        self.assertTrue(self.win.updatesEnabled())
        self.assertIsNotNone(self.win.panels[0].view._img.image)

    def test_restore_maximized_returns_to_previous_size(self):
        self.win.resize(1000, 700)
        QtTest.QTest.qWait(80)
        before = self.win.size()
        self.win.showMaximized()
        QtTest.QTest.qWait(120)
        self.win.showNormal()
        QtTest.QTest.qWait(120)
        self.assertLessEqual(abs(self.win.width() - before.width()), 4)
        self.assertLessEqual(abs(self.win.height() - before.height()), 4)

    def test_clear_resets_window_to_default_size(self):
        self.win.resize(1400, 800)
        QtTest.QTest.qWait(80)
        self.assertEqual(self.win.width(), 1400)
        self.win.clear_data()
        QtTest.QTest.qWait(350)
        w, h = self.win._default_window_size()
        self.assertIsNone(self.win._user_size)
        self.assertLessEqual(abs(self.win.width() - w), 6, (self.win.width(), w))
        self.assertLessEqual(abs(self.win.height() - h), 6, (self.win.height(), h))

    def test_reorder_pickup_hides_panel_but_keeps_slot(self):
        """拿起一幅剖面时原位置必须消失，但槽位宽度不能被邻居吃掉。"""
        self.win._solo("slice")
        QtTest.QTest.qWait(300)
        panel = self.win.panels[0]
        holder = self.win.panel_holders[0]
        width = holder.width()
        sizes = list(self.win.slice_split.sizes())
        self.win._begin_drag(panel.header, panel, QtCore.QPoint(10, 10))
        d = self.win._drag
        self.win._open_drag_layer(d)
        self.assertFalse(panel.isVisible())
        self.assertEqual(holder.width(), width)
        self.assertEqual(self.win.slice_split.sizes(), sizes)
        self.assertIs(d.get("pinned_holder"), holder)
        self.win._discard_drag_layer(d, restore=True)
        self.win._drag = None
        self.assertTrue(panel.isVisible())
        self.assertEqual(holder.width(), width)

    def test_log_contrast_range_and_mapping(self):
        row = self.win.contrast
        self.assertEqual(row.value(), 100)
        self.assertEqual(row.slider.value(), row.LOG_POSITIONS // 2)
        row.set_value(10)
        self.assertEqual(row.value(), 10)
        self.assertEqual(row.slider.value(), 0)
        self.assertAlmostEqual(self.win._clim_scale, 10.0)
        row.set_value(1000)
        self.assertEqual(row.value(), 1000)
        self.assertEqual(row.slider.value(), row.LOG_POSITIONS)
        self.assertAlmostEqual(self.win._clim_scale, 0.1)
        row.set_value(316)
        self.assertLessEqual(abs(row.value() - 316), 2)
        row.set_value(100)
        self.assertAlmostEqual(self.win._clim_scale, 1.0)

    def test_new_themes_exist(self):
        from seisview import style
        self.assertIn("rose", style.THEME_ORDER)
        self.assertIn("frost", style.THEME_ORDER)
        base_keys = set(style.THEMES["deepblue"])
        for key in ("rose", "frost"):
            self.assertEqual(set(style.THEMES[key]), base_keys)
            style.set_theme(key, self.app)
            self.assertEqual(style.current_theme(), key)
        style.set_theme("deepblue", self.app)

    def test_time_slice_agc_is_disabled_and_not_applied(self):
        self.win._on_mode("time")
        QtTest.QTest.qWait(20)
        self.assertFalse(self.win.chk_agc.isEnabled())
        self.win.chk_agc.setChecked(True)
        img_on, _ = self.win._panel_image(0)
        self.win.chk_agc.setChecked(False)
        self.win._refresh_all()
        img_off, _ = self.win._panel_image(0)
        np.testing.assert_array_equal(img_on, img_off)


if __name__ == "__main__":
    unittest.main()
