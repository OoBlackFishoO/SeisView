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
            clim = compute_clim(img, "robust")
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


if __name__ == "__main__":
    unittest.main()
