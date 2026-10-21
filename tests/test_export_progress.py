"""A3：.mat / .npz 导出进度不能停在 90% 无说明。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from seisview import export as exporter


class ExportProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cube = np.random.default_rng(3).standard_normal((2, 4, 8)).astype(np.float32)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, fmt: str):
        events: list[tuple[float, str]] = []
        out = Path(self.tmp.name) / f"cube.{fmt}"
        exporter.export(out, self.cube, fmt,
                        progress=lambda f, t: events.append((f, t)))
        self.assertTrue(out.exists())
        return events

    def test_mat_and_npz_progress(self):
        for fmt in ("mat", "npz"):
            with self.subTest(fmt=fmt):
                events = self._run(fmt)
                fracs = [f for f, _t in events]
                self.assertTrue(events)
                self.assertEqual(fracs[-1], 1.0)
                # 全程只增不减
                self.assertEqual(fracs, sorted(fracs))
                self.assertTrue(any(t.startswith("正在序列化为")
                                    for _f, t in events))
                # 序列化阶段之前绝不冒充 100%
                self.assertTrue(all(f <= 0.99 for f in fracs[:-1]))
                # 组装阶段最多到 0.9，之后由 99% 文案接管
                self.assertTrue(any(f == 0.99 for f in fracs))


if __name__ == "__main__":
    unittest.main()
