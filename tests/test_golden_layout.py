"""黄金测试：分屏布局结构、尺寸决策与拖动落区判定。"""

from __future__ import annotations

import unittest

from PySide6 import QtCore, QtTest, QtWidgets

from golden_utils import (UPDATE, assert_golden_json, ensure_app, install,
                          layout_signature, load_golden_json, make_window,
                          synthetic_volume)
from seisview.widgets import LAYOUT_KEYS


class GoldenLayoutTest(unittest.TestCase):
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
        QtTest.QTest.qWait(200)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        QtWidgets.QApplication.processEvents()

    def test_default_3d_layout(self):
        assert_golden_json("layout_default_3d", layout_signature(self.win))

    def test_default_2d_layout(self):
        win = make_window()
        try:
            install(win, synthetic_volume(shape=(1, 8, 32), seed=5), "two_d")
            QtTest.QTest.qWait(200)
            assert_golden_json("layout_default_2d", layout_signature(win))
        finally:
            win.close()
            win.deleteLater()
            QtWidgets.QApplication.processEvents()

    def test_all_presets(self):
        win = self.win
        shots = {}
        for key in LAYOUT_KEYS:
            win._apply_layout(key)
            QtTest.QTest.qWait(420)
            shots[key] = layout_signature(win)
        assert_golden_json("layout_presets", shots)

    def test_swap_main_keeps_structure(self):
        win = self.win
        win._apply_layout("B")
        QtTest.QTest.qWait(420)
        before = layout_signature(win)
        win._swap_main()
        QtTest.QTest.qWait(420)
        after = layout_signature(win)

        self.assertEqual(before["preset"], after["preset"])
        self.assertEqual(before["root_orientation"], after["root_orientation"])
        self.assertEqual(before["inner_orientation"], after["inner_orientation"])
        self.assertNotEqual(before["slots"][:2], after["slots"][:2])
        assert_golden_json("layout_after_swap", after)

    def test_toggle_and_solo(self):
        win = self.win
        shots = {}
        win._solo("slice")
        QtTest.QTest.qWait(420)
        shots["solo_slice"] = layout_signature(win)

        win._toggle_content("trace")
        QtTest.QTest.qWait(420)
        shots["add_trace"] = layout_signature(win)

        win._toggle_content("right")
        QtTest.QTest.qWait(420)
        shots["add_right"] = layout_signature(win)

        assert_golden_json("layout_toggle_solo", shots)

    def test_window_target(self):
        win = self.win
        win._apply_layout("B")
        QtTest.QTest.qWait(420)
        work_w, work_h = 0, 0
        win._suppress_window_resize = True
        try:
            work_w, work_h = win._fit_window_to_layout(win._effective_shown())
        finally:
            win._suppress_window_resize = False

        actual = {
            "target": list(win._window_target) if win._window_target else None,
            "work": [int(work_w), int(work_h)],
        }
        if UPDATE:
            assert_golden_json("layout_window_target", actual)
            return
        expected = load_golden_json("layout_window_target")
        self.assertIsNotNone(actual["target"])
        for got, want in zip(actual["target"], expected["target"]):
            self.assertLessEqual(abs(got - want), 4)
        self.assertGreater(actual["work"][0], 0)
        self.assertGreater(actual["work"][1], 0)

    def test_drop_zone_sides(self):
        win = self.win
        win._apply_layout("B")
        QtTest.QTest.qWait(420)
        win._zone_frozen = None
        self.assertFalse(win._layout_anim_running())

        wrap = win.workspace
        self.assertGreater(wrap.width(), 10)
        self.assertGreater(wrap.height(), 10)

        def side_at(fx: float, fy: float) -> str | None:
            pos = wrap.mapToGlobal(
                QtCore.QPoint(int(wrap.width() * fx), int(wrap.height() * fy)))
            return win._zone_side_at(pos, "trace")

        self.assertEqual(side_at(0.5, 0.10), "first")
        self.assertIsNone(side_at(0.5, 0.50))
        self.assertEqual(side_at(0.5, 0.90), "second")


if __name__ == "__main__":                       # pragma: no cover
    unittest.main()
