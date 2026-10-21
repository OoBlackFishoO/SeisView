"""B11：SEG-Y/SU 快速道头扫描必须与 segyio 逐字段结果一致，且能安全回退。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from seisview import export, loaders


class FastHeaderScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        rng = np.random.default_rng(11)
        cls.cube = (rng.standard_normal((12, 8, 30)) * 0.1).astype(np.float32)
        cls.path = Path(cls.tmp.name) / "demo.sgy"
        export.export(cls.path, cls.cube, "sgy",
                      dt_us=2000, dx=12.5, ds=25.0, with_coords=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _scan(self, force_fallback: bool = False):
        loaders._seismic_cache.clear()
        if force_fallback:
            orig = loaders._fast_seismic_headers
            loaders._fast_seismic_headers = (
                lambda *a, **k: (_ for _ in ()).throw(ValueError("force")))
            try:
                return loaders._scan_seismic(self.path)
            finally:
                loaders._fast_seismic_headers = orig
        return loaders._scan_seismic(self.path)

    def test_fast_scan_matches_fallback(self):
        fast = self._scan(False)
        slow = self._scan(True)
        for key in ("shots", "tracl", "n_shot", "n_r", "ns", "dt", "dt_us",
                    "dx", "ds", "nbytes", "trace_bytes", "first_sample",
                    "store_dtype", "regular", "by_tracl", "blocks"):
            with self.subTest(key=key):
                if isinstance(fast[key], np.ndarray):
                    np.testing.assert_array_equal(fast[key], slow[key])
                else:
                    self.assertEqual(fast[key], slow[key])

    def test_fast_scan_returns_real_values(self):
        info = self._scan(False)
        self.assertFalse(info["timing"]["fallback"])
        self.assertEqual(info["n_shot"], 12)
        self.assertEqual(info["n_r"], 8)
        # FieldRecord 从 1 开始，TraceNumber 每炮 1..8
        self.assertTrue(np.all(np.diff(info["shots"]) > 0))
        self.assertEqual(int(info["tracl"][0]), 1)

    def test_load_data_matches_source(self):
        loaders._seismic_cache.clear()
        arr = loaders.load_array(self.path, "seismic")
        self.assertEqual(arr.shape, self.cube.shape)
        np.testing.assert_allclose(np.asarray(arr), self.cube, rtol=0, atol=1e-6)
        del arr


if __name__ == "__main__":
    unittest.main()
