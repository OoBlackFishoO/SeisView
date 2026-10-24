"""A2：二维剖面与三维贴图必须走同一条 AGC / 抽稀 / 上色链。"""

from __future__ import annotations

import unittest

import numpy as np

from seisview import render
from seisview.volume import (SeisVolume, agc, compute_clim, decimate,
                             display_face, shared_clim)


def _volume(ns=5, nr=9, nt=37, scale=1.0, seed=7) -> SeisVolume:
    rng = np.random.default_rng(seed)
    data = (rng.standard_normal((ns, nr, nt)) * scale).astype(np.float32)
    # 放几个坏点，确认坏点不会被 AGC 扩散
    data[0, 0, 0] = np.nan
    data[1, 2, 3] = np.inf
    return SeisVolume(name="t", data=data)


class FacePipelineTest(unittest.TestCase):
    def test_fixed_order_matches_legacy_pipeline(self):
        vol = _volume()
        legacy = agc(decimate(vol.take_slice("shot", 1),
                              max_cols=6, max_rows=6), 7, axis=0)
        got = display_face(vol, "shot", 1, max_side=6, agc_window=7)
        np.testing.assert_array_equal(got, legacy)

    def test_time_slice_ignores_agc(self):
        vol = _volume()
        off = display_face(vol, "time", 3, max_side=6)
        on = display_face(vol, "time", 3, max_side=6, agc_window=101)
        np.testing.assert_array_equal(off, on)

    def test_even_window_is_rejected(self):
        vol = _volume()
        with self.assertRaises(AssertionError):
            display_face(vol, "shot", 0, agc_window=10)

    def test_direction_transform_is_lossless(self):
        vol = _volume()
        for mode, index in (("shot", 1), ("recv", 2), ("time", 3)):
            img = display_face(vol, mode, index, max_side=8, agc_window=5)
            clim = compute_clim(img, "p98")
            rgba = render.to_rgba(img, "seismic", clim)
            tex = render.face_texture(render.face_orientation(img, mode),
                                      "seismic", clim)
            # face_texture 返回 (x, y, 4)，像素轴必须显式换回来（不能用 .T 反转通道轴）
            oriented = tex if mode == "time" else tex[:, ::-1]
            back = oriented.transpose(1, 0, 2)
            self.assertEqual(back.shape, rgba.shape)
            np.testing.assert_array_equal(back, rgba)

    def test_shared_clim_uses_one_window(self):
        a = _volume(scale=1.0, seed=1)
        b = _volume(scale=20.0, seed=2)
        ia = display_face(a, "shot", 1)
        ib = display_face(b, "shot", 1)
        lo, hi = shared_clim([ia, ib], "auto")
        self.assertLess(lo, hi)
        # 两份数据必须落在同一个窗口里，否则对比时“哪份更强”没有意义
        self.assertGreater(hi, float(np.percentile(np.abs(ib), 50)))
        np.testing.assert_allclose(shared_clim([ia, ib], "auto"),
                                   shared_clim([ib, ia], "auto"))


class ClimModeTest(unittest.TestCase):
    """色标口径：自动 = max(8×MAD, P99)，分位 = Pq(|x|)，手动 = 0 中心 ± 半宽。"""

    def test_auto_is_eight_sigma_for_gaussian(self):
        rng = np.random.default_rng(0)
        arr = rng.standard_normal(200_000).astype(np.float32)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        lo, hi = compute_clim(arr, "auto")
        self.assertAlmostEqual(0.5 * (hi - lo), 1.4826 * mad * 8.0, places=4)
        self.assertAlmostEqual(0.5 * (hi + lo), med, places=5)

    def test_auto_falls_back_to_p99_on_heavy_tail(self):
        arr = np.zeros(10_000, np.float32)
        arr[::50] = 1000.0                 # 2% 强振幅，MAD 为零
        lo, hi = compute_clim(arr, "auto")
        self.assertAlmostEqual(0.5 * (hi - lo), 1000.0)
        self.assertAlmostEqual(0.5 * (hi + lo), 0.0)

    def test_percentile_modes_use_absolute_quantile(self):
        rng = np.random.default_rng(1)
        arr = rng.standard_normal(20_000).astype(np.float32)
        med = float(np.median(arr))
        for mode, q in (("p95", 95.0), ("p98", 98.0), ("p99", 99.0)):
            want = float(np.percentile(np.abs(arr), q))
            lo, hi = compute_clim(arr, mode)
            self.assertAlmostEqual(hi - med, want, places=4, msg=mode)
            self.assertAlmostEqual(lo, med - want, places=4, msg=mode)

    def test_manual_is_zero_centered_half_width(self):
        # 数据最大幅值是 100，手动值 2.5 只表示窗口 [-2.5, +2.5]
        arr = np.full(100, 100.0, np.float32)
        self.assertEqual(compute_clim(arr, "manual", 2.5), (-2.5, 2.5))


if __name__ == "__main__":
    unittest.main()
