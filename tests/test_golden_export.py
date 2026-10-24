"""黄金测试：导出切片几何、整卷/逐剖面写出、论文图取数。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PySide6 import QtTest, QtWidgets

from golden_utils import (assert_golden_json, assert_golden_npz, ensure_app,
                          install, make_window, synthetic_volume)
from seisview import export as exporter
from seisview import main_window as mw


class GoldenExportTest(unittest.TestCase):
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

    def test_slice_geometry_matches_volume(self):
        vol = synthetic_volume(shape=(3, 4, 5), with_bad=False)
        shapes = {}
        for mode in ("shot", "recv", "time"):
            self.assertEqual(exporter.slice_count(vol.data, mode),
                             vol.slice_index_range(mode))
            for i in range(vol.slice_index_range(mode)):
                np.testing.assert_array_equal(
                    exporter.take_slice(vol.data, mode, i),
                    vol.take_slice(mode, i))
            rows, cols = exporter.slice_shape(vol.data, mode)
            self.assertEqual((rows, cols), vol.take_slice(mode, 0).shape)
            shapes[mode] = [rows, cols]
        assert_golden_json("export_slice_shapes", shapes)

    def test_npy_roundtrip(self):
        vol = synthetic_volume(shape=(3, 4, 5), with_bad=False)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "cube.npy")
            out = exporter.export(path, vol.data, "npy")
            self.assertEqual(out, path)
            loaded = np.load(path, allow_pickle=False)
            np.testing.assert_array_equal(loaded, vol.data)
            assert_golden_json("export_npy_meta", {
                "shape": list(loaded.shape),
                "dtype": str(loaded.dtype),
            })

    def test_export_slices_npy(self):
        vol = synthetic_volume(shape=(3, 4, 5), with_bad=False)
        with tempfile.TemporaryDirectory() as tmp:
            made = exporter.export_slices(
                tmp, vol.data, "npy", mode="shot", name="s", start=0, stop=2)
            self.assertEqual([Path(p).name for p in made],
                             ["s_0.npy", "s_1.npy", "s_2.npy"])
            for i, path in enumerate(made):
                np.testing.assert_array_equal(
                    np.load(path, allow_pickle=False), vol.take_slice("shot", i))

    def test_figure_uses_panel_image(self):
        win = make_window()
        try:
            install(win, synthetic_volume(), "base")
            win.chk_pure.setChecked(False)
            win.clim_combo.setCurrentIndex(win.clim_combo.findData("manual"))
            win.spin_manual.setValue(2.5)
            win.contrast.set_value(200)
            win._flush_contrast()
            QtTest.QTest.qWait(40)

            captured = {}

            class _Plot:
                def close(self):
                    pass

            def fake_build(img, extent, cmap, clim, *args, **kwargs):
                captured.update(img=img, extent=extent, cmap=cmap, clim=clim)
                return _Plot()

            orig_build = mw.view2d.build_slice_figure
            orig_export = mw.view2d.export_figure
            mw.view2d.build_slice_figure = fake_build
            mw.view2d.export_figure = lambda *a, **kw: None
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    class _Dlg:
                        def content(self):
                            return "slice_image"

                        def dataset_scope(self):
                            return "active"

                        def path(self):
                            return str(Path(tmp) / "slice.png")

                        def fmt(self):
                            return "png"

                    made = win._export_slice_figures(_Dlg(), lambda *_: None)
            finally:
                mw.view2d.build_slice_figure = orig_build
                mw.view2d.export_figure = orig_export

            self.assertEqual(len(made), 1)
            expected_img, expected_clim = win._panel_image(0, full=True)
            np.testing.assert_array_equal(captured["img"], expected_img)
            np.testing.assert_allclose(captured["clim"], expected_clim)
            assert_golden_npz("export_figure_payload",
                              img=captured["img"],
                              clim=np.asarray(captured["clim"]))
            assert_golden_json("export_figure_meta", {
                "extent": list(captured["extent"]),
                "cmap": captured["cmap"],
            })
        finally:
            win.close()
            win.deleteLater()
            QtWidgets.QApplication.processEvents()


if __name__ == "__main__":                       # pragma: no cover
    unittest.main()
