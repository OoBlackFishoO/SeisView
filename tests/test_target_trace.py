"""目标道：绿线拖动 / ←→ 单步 / 时间切片无效 / 对比同步。"""

from __future__ import annotations

import unittest

from golden_utils import ensure_app, install, make_window, synthetic_volume

from PySide6 import QtTest


class TargetTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    def setUp(self) -> None:
        self.win = make_window()
        install(self.win, synthetic_volume())
        self.win.datasets[0].mode = "shot"
        self.win._refresh_all()

    def tearDown(self) -> None:
        self.win.close()
        self.win.deleteLater()
        QtTest.QTest.qWait(10)

    def test_step_in_shot_mode_moves_recv_only(self) -> None:
        ds = self.win.datasets[0]
        before = dict(ds.pos)
        self.win._on_trace_step(0, 1)
        self.assertEqual(ds.pos["recv"], min(before["recv"] + 1, ds.vol.nr - 1))
        self.assertEqual(ds.pos["shot"], before["shot"])
        self.assertEqual(ds.pos["time"], before["time"])
        self.assertEqual(ds.pos["recv"], self.win._traces()[2][1])

    def test_step_in_recv_mode_moves_shot_only(self) -> None:
        ds = self.win.datasets[0]
        ds.mode = "recv"
        self.win._refresh_all()
        before = dict(ds.pos)
        self.win._on_trace_step(0, -1)
        self.assertEqual(ds.pos["shot"], max(before["shot"] - 1, 0))
        self.assertEqual(ds.pos["recv"], before["recv"])

    def test_time_slice_has_no_target_step(self) -> None:
        ds = self.win.datasets[0]
        ds.mode = "time"
        self.win._refresh_all()
        before = dict(ds.pos)
        self.win._on_trace_step(0, 1)
        self.win._on_trace_step(0, -1)
        self.assertEqual(ds.pos, before)

    def test_drag_sets_recv_and_clamps(self) -> None:
        ds = self.win.datasets[0]
        self.win._on_reference_drag(0, 2)
        self.assertEqual(ds.pos["recv"], 2)
        self.win._on_reference_drag(0, 10_000)
        self.assertEqual(ds.pos["recv"], ds.vol.nr - 1)

    def test_sync_broadcasts_target_trace(self) -> None:
        self.win._append_dataset(synthetic_volume(seed=2), "", "v2")
        QtTest.QTest.qWait(120)
        self.win.chk_sync.setChecked(True)
        start = self.win.datasets[0].pos["recv"]
        self.win._on_trace_step(0, 1)
        for ds in self.win.datasets:
            self.assertEqual(ds.pos["recv"], min(start + 1, ds.vol.nr - 1))


if __name__ == "__main__":
    unittest.main()
