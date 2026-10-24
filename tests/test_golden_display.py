"""黄金测试：显示管线（切片、抽稀、AGC、色标、上色、单道、缓存语义）。"""

from __future__ import annotations

import unittest

import numpy as np
from PySide6 import QtTest, QtWidgets

from golden_utils import (append, assert_golden_json, assert_golden_npz,
                          ensure_app, install, make_window, synthetic_volume)
from seisview import render


class GoldenDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_app()
        from seisview import view3d as view3d_module
        cls.view3d_module = view3d_module
        cls._orig_create = view3d_module.create_view3d
        view3d_module.create_view3d = lambda parent=None: None

    @classmethod
    def tearDownClass(cls):
        cls.view3d_module.create_view3d = cls._orig_create

    def setUp(self):
        self.win = make_window()
        install(self.win, synthetic_volume(), "base")

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        QtWidgets.QApplication.processEvents()

    # ------------------------------------------------------------ 基础剖面/上色
    def test_default_shot_panel_and_rgba(self):
        win = self.win
        win.mode = "shot"
        win._refresh_all()
        img, clim = win._panel_image(0)
        rgba = render.to_rgba(img, win.cmap_combo.cmap(), clim)
        assert_golden_npz("display_shot_default", img=img, clim=np.array(clim))
        assert_golden_npz("rgba_shot_default", exact=True, rgba=rgba)
        assert_golden_json("display_shot_stats", win._stats)

    def test_recv_with_agc_window(self):
        win = self.win
        win.mode = "recv"
        win.chk_agc.setChecked(True)
        win.combo_agc.setCurrentIndex(win.combo_agc.findData(11))
        win._refresh_all()
        img, clim = win._panel_image(0)
        rgba = render.to_rgba(img, win.cmap_combo.cmap(), clim)
        assert_golden_npz("display_recv_agc11", img=img, clim=np.array(clim))
        assert_golden_npz("rgba_recv_agc11", exact=True, rgba=rgba)

    def test_time_slice_ignores_agc(self):
        win = self.win
        win.mode = "time"
        win.chk_agc.setChecked(False)
        win._refresh_all()
        img_off, _ = win._panel_image(0)

        win.chk_agc.setChecked(True)
        win.combo_agc.setCurrentIndex(win.combo_agc.findData(51))
        win._refresh_all()
        img_on, clim = win._panel_image(0)

        np.testing.assert_array_equal(img_off, img_on)
        assert_golden_npz("display_time_agc_ignored", img=img_on,
                          clim=np.array(clim))

    def test_clim_modes(self):
        win = self.win
        win.spin_manual.setValue(2.5)
        arrays = {}
        for mode in ("auto", "p95", "p98", "p99", "manual"):
            win.clim_combo.setCurrentIndex(win.clim_combo.findData(mode))
            win._refresh_all()
            arrays[f"clim_{mode}"] = np.array(win._panel_image(0)[1])
            arrays[f"base_{mode}"] = np.array(win._shared_base_clim())
        assert_golden_npz("display_clim_modes", **arrays)

    # ------------------------------------------------------------ 抽稀/对比/单道
    def test_contrast_and_decimation(self):
        win = make_window()
        try:
            install(win, synthetic_volume(shape=(8, 12, 600), seed=7,
                                          with_bad=False), "big")
            win.contrast.set_value(200)
            win._flush_contrast()
            win.combo_dec.setCurrentIndex(win.combo_dec.findData(512))
            win._refresh_all()
            img, clim = win._panel_image(0)
            assert_golden_npz("display_contrast_decimation", img=img,
                              clim=np.array(clim))
            assert_golden_json("display_contrast_decimation_stats", win._stats)
        finally:
            win.close()
            win.deleteLater()
            QtWidgets.QApplication.processEvents()

    def test_compare_shared_clim(self):
        win = self.win
        win.clear_data()
        QtTest.QTest.qWait(400)
        install(win, synthetic_volume(seed=1, scale=1.0, name="a"), "a")
        append(win, synthetic_volume(seed=2, scale=4.0, name="b"), "b")
        append(win, synthetic_volume(seed=3, scale=12.0, name="c"), "c")
        win._refresh_all()

        arrays = {"clims": np.asarray(win._clims)}
        for k in range(3):
            img, clim = win._panel_image(k)
            arrays[f"img{k}"] = img
            arrays[f"clim{k}"] = np.array(clim)
        assert_golden_npz("display_compare_shared_clim", **arrays)
        self.assertEqual(len({tuple(c) for c in win._clims}), 1)

    def test_traces_normalize(self):
        win = self.win
        append(win, synthetic_volume(seed=2, scale=4.0, name="b"), "b")
        win.chk_norm.setChecked(True)
        win._refresh_all()
        traces, peaks, sr = win._traces()
        assert_golden_npz("display_traces_norm_on",
                          t=np.asarray(traces[0][0]),
                          amp0=np.asarray(traces[0][1]),
                          amp1=np.asarray(traces[1][1]),
                          peaks=np.asarray(peaks))
        assert_golden_json("display_traces_sr", {"sr": list(sr)})

        win.chk_norm.setChecked(False)
        win._refresh_all()
        traces_off, peaks_off, _ = win._traces()
        assert_golden_npz("display_traces_norm_off",
                          amp0=np.asarray(traces_off[0][1]),
                          amp1=np.asarray(traces_off[1][1]),
                          peaks=np.asarray(peaks_off))

    # ------------------------------------------------------------ 缓存语义
    def test_contrast_reuses_raw_cache(self):
        win = self.win
        win._refresh_all()
        raw_key = (0, False)
        raw_before = win._raw_cache[raw_key][0]
        base_before = win._shared_base_clim()

        win.contrast.set_value(200)
        QtTest.QTest.qWait(60)

        self.assertIs(win._raw_cache[raw_key][0], raw_before)
        self.assertIs(win._shared_base_clim(), base_before)
        expected = win._scale_window(base_before)
        np.testing.assert_allclose(win._panel_image(0)[1], expected)


if __name__ == "__main__":                       # pragma: no cover
    unittest.main()
