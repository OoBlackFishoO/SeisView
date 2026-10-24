"""黄金测试：数据集状态机（载入、追加、替换、移除、清空、二维/三维默认）。"""

from __future__ import annotations

import unittest

from PySide6 import QtTest, QtWidgets

from golden_utils import (append, assert_golden_json, dataset_signature,
                          ensure_app, install, make_window, synthetic_volume)


class GoldenDatasetTest(unittest.TestCase):
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
        self.errors: list[tuple[str, str]] = []
        self.win._error = lambda title, message: self.errors.append((title, message))

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        QtWidgets.QApplication.processEvents()

    def test_install_primary(self):
        install(self.win, synthetic_volume(), "main")
        assert_golden_json("dataset_install_primary", dataset_signature(self.win))

    def test_append_same_shape(self):
        install(self.win, synthetic_volume(seed=1, name="a"), "a")
        append(self.win, synthetic_volume(seed=2, scale=4.0, name="b"), "b")
        assert_golden_json("dataset_append_same_shape", dataset_signature(self.win))

    def test_append_shape_mismatch_is_rejected(self):
        install(self.win, synthetic_volume(seed=1, name="a"), "a")
        before = dataset_signature(self.win)
        ok = self.win._append_dataset(
            synthetic_volume(shape=(3, 4, 10), seed=2, name="bad"), "", "bad")
        self.assertFalse(ok)
        self.assertTrue(self.errors)
        self.assertEqual(dataset_signature(self.win), before)
        assert_golden_json("dataset_append_rejected", before)

    def test_replace_active_same_shape_keeps_position(self):
        win = self.win
        install(win, synthetic_volume(seed=1, name="a"), "a")
        win.mode = "recv"
        win.pos["recv"] = 3
        win._replace_active(synthetic_volume(seed=2, scale=2.0, name="b"), "", "b")
        QtTest.QTest.qWait(150)
        self.assertEqual(win.mode, "recv")
        self.assertEqual(win.pos["recv"], 3)
        assert_golden_json("dataset_replace_same_shape", dataset_signature(win))

    def test_replace_active_different_shape_uses_default_mode(self):
        win = self.win
        install(win, synthetic_volume(seed=1, name="a"), "a")
        win.mode = "recv"
        win._replace_active(synthetic_volume(shape=(1, 8, 32), seed=2,
                                             name="flat"), "", "flat")
        QtTest.QTest.qWait(150)
        self.assertEqual(win.mode, "shot")
        assert_golden_json("dataset_replace_different_shape", dataset_signature(win))

    def test_remove_dataset(self):
        win = self.win
        install(win, synthetic_volume(seed=1, name="a"), "a")
        append(win, synthetic_volume(seed=2, name="b"), "b")
        win.active = 1
        win.remove_dataset()
        QtTest.QTest.qWait(150)
        assert_golden_json("dataset_remove", dataset_signature(win))

    def test_clear_data_resets_ui(self):
        win = self.win
        install(win, synthetic_volume(seed=1, name="a"), "a")
        append(win, synthetic_volume(seed=2, name="b"), "b")
        win.clear_data()
        QtTest.QTest.qWait(450)

        widgets = {
            "mode": win.mode_ctl.value(),
            "cmap": win.cmap_combo.cmap(),
            "clim_mode": win.clim_combo.currentData(),
            "manual": float(win.spin_manual.value()),
            "contrast": int(win.contrast.value()),
            "agc": bool(win.chk_agc.isChecked()),
            "agc_window": int(win.combo_agc.currentData() or 0),
            "decimation": win.combo_dec.currentData(),
            "wiggle": bool(win.chk_wiggle.isChecked()),
            "pure": bool(win.chk_pure.isChecked()),
            "wiggle_traces": int(win.spin_wig.value()),
            "gain": int(win.gain.value()),
            "sync": bool(win.chk_sync.isChecked()),
            "speed": win.speed_combo.currentData(),
            "loop": bool(win.chk_loop.isChecked()),
            "line_styles": [list(p) for p in win.line_styles],
            "dt": float(win.spin_dt.value()),
            "dx": float(win.spin_dx.value()),
            "ds": float(win.spin_ds.value()),
        }
        assert_golden_json("dataset_clear", {
            "data": dataset_signature(win),
            "widgets": widgets,
        })

    def test_dimension_defaults(self):
        win = self.win
        install(win, synthetic_volume(shape=(1, 8, 32), seed=5, name="two_d"),
                "two_d")
        QtTest.QTest.qWait(150)
        two_d = dataset_signature(win)

        win._install_primary(synthetic_volume(seed=6, name="three_d"), "", "three_d")
        QtTest.QTest.qWait(150)
        three_d = dataset_signature(win)

        assert_golden_json("dataset_dimension_defaults",
                           {"two_d": two_d, "three_d": three_d})


if __name__ == "__main__":                       # pragma: no cover
    unittest.main()
