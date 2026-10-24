"""v0.4.0 发布守卫：空维度、坏文件、NaN、路径安全、缓存与打包配置。"""

from __future__ import annotations

import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PySide6 import QtTest, QtWidgets
from golden_utils import ensure_app, install, make_window, synthetic_volume

from seisview import __version__, loaders, view2d
from seisview.loaders import LoadError, VariableInfo
from seisview.volume import SeisVolume
from seisview.widgets import ExportDialog


def _silence_errors(win):
    errors: list[tuple[str, str]] = []
    win._error = lambda title, message: errors.append((title, message))
    return errors


def _close(win) -> None:
    win.close()
    win.deleteLater()
    QtTest.QTest.qWait(10)


class ReleaseGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    # ------------------------------------------------------------ 空维度
    def test_zero_dimension_is_rejected_without_state_change(self) -> None:
        arr = np.zeros((0, 8, 32), dtype=np.float32)
        with self.assertRaises(LoadError):
            loaders.build_volume("bad", arr, ["shot", "recv", "time"])

        win = make_window()
        errors = _silence_errors(win)
        try:
            install(win, synthetic_volume())
            before = tuple(win.datasets[0].vol.shape)
            ok = win._install_primary(SeisVolume("bad", arr), "", "bad")
            self.assertFalse(ok)
            self.assertEqual(len(win.datasets), 1)
            self.assertEqual(tuple(win.datasets[0].vol.shape), before)
            self.assertTrue(errors)
        finally:
            _close(win)

    # ------------------------------------------------------------ NaN
    def test_nan_trace_and_wave_export_stay_finite(self) -> None:
        data = np.random.default_rng(1).standard_normal((6, 8, 32)).astype(np.float32)
        data[3, 4, 10] = np.nan
        win = make_window()
        try:
            win._install_primary(SeisVolume("bad", data), "", "bad")
            QtTest.QTest.qWait(200)
            ds = win.datasets[0]
            ds.mode = "shot"
            ds.pos = {"shot": 3, "recv": 4, "time": 10}
            win._refresh_all()
            QtTest.QTest.qWait(80)

            traces, peaks, _ = win._traces()
            self.assertTrue(np.isfinite(peaks[0]))
            t, amp, _style, _name = traces[0]
            self.assertGreater(np.count_nonzero(np.isfinite(amp)), 0)
            self.assertTrue(np.isnan(amp[10]))
            bounds = view2d._trace_bounds(traces, None)
            self.assertIsNotNone(bounds)
            self.assertTrue(all(np.isfinite(v) for v in bounds))

            with tempfile.TemporaryDirectory() as tmp:
                dlg = ExportDialog(
                    [{"label": "d1", "vol": ds.vol, "pos": ds.pos}], 0, tmp, "nan",
                    line_styles=list(win.line_styles), mode=ds.mode, parent=win)
                try:
                    dlg.content_ctl.set_value("wave_image")
                    dlg._on_content()
                    plot = win.export_service.build_wave_plot(dlg)
                    try:
                        xr, yr = plot.getViewBox().viewRange()
                        self.assertTrue(np.all(np.isfinite(xr + yr)))
                    finally:
                        plot.close()
                    image = win.export_service.preview_figure(dlg)
                    self.assertFalse(image.isNull())
                finally:
                    dlg.close()
        finally:
            _close(win)

    def test_all_nan_wiggle_scale_is_safe(self) -> None:
        win = make_window()
        errors = _silence_errors(win)
        try:
            data = np.full((6, 8, 32), np.nan, dtype=np.float32)
            win._install_primary(SeisVolume("nan", data), "", "nan")
            QtTest.QTest.qWait(150)
            self.assertTrue(errors == [] or len(win.datasets) == 1)
            _img, _clim, scale, _style = win.export_service.figure_wiggle_set(0)
            self.assertTrue(np.isfinite(scale))
            self.assertGreater(scale, 0)
        finally:
            _close(win)

    # ------------------------------------------------------------ 默认路径 / 源文件
    def test_default_export_path_is_not_source_and_source_is_blocked(self) -> None:
        win = make_window()
        errors = _silence_errors(win)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "data.npz"
                rng = np.random.default_rng(1)
                np.savez(src, cube=rng.standard_normal((6, 8, 32)).astype(np.float32),
                         metadata=np.array([1, 2, 3]))
                cube = np.load(src)["cube"]
                win._install_primary(SeisVolume("data", cube), str(src), "cube")
                QtTest.QTest.qWait(150)
                ds = win.datasets[0]
                dlg = ExportDialog(
                    [{"label": "d1", "vol": ds.vol, "pos": ds.pos}], 0,
                    src.parent, src.stem, line_styles=list(win.line_styles),
                    mode=ds.mode, source_path=str(src), parent=win)
                try:
                    idx = dlg.combo_fmt.findData("npz")
                    dlg.combo_fmt.setCurrentIndex(idx)
                    out = Path(dlg.path())
                    self.assertEqual(out.name, "data_export.npz")
                    self.assertNotEqual(out.resolve(), src.resolve())
                    self.assertTrue(ExportDialog._is_source_path(
                        str(src), str(src)))

                    captured: list[str] = []
                    dlg._fail = lambda message: captured.append(message)
                    dlg.path_edit.setText(str(src))
                    dlg._validate()
                    self.assertTrue(captured)
                    self.assertIn("不能覆盖", captured[-1])
                finally:
                    dlg.close()
        finally:
            _close(win)

    def test_suffix_must_match_format(self) -> None:
        win = make_window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dlg = ExportDialog(
                    [{"label": "d1", "vol": synthetic_volume(), "pos": {}}], 0,
                    tmp, "x", parent=win)
                try:
                    self.assertIn(".npy", dlg._suffix_message("x.svg"))
                    captured: list[str] = []
                    dlg._fail = lambda message: captured.append(message)
                    dlg._confirm = lambda: False
                    dlg.path_edit.setText(str(Path(tmp) / "noext"))
                    dlg._validate()
                    self.assertEqual(Path(dlg.path()).suffix, ".npy")
                    self.assertEqual(captured, [])
                    dlg.path_edit.setText(str(Path(tmp) / "x.svg"))
                    dlg._validate()
                    self.assertTrue(captured)
                    self.assertIn("后缀", captured[-1])
                finally:
                    dlg.close()
        finally:
            _close(win)

    # ------------------------------------------------------------ 对话框滚动
    def test_export_dialog_uses_scroll_area(self) -> None:
        win = make_window()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dlg = ExportDialog(
                    [{"label": "d1", "vol": synthetic_volume(), "pos": {}}], 0,
                    tmp, "x", parent=win)
                try:
                    self.assertIs(dlg.scroll.widget(), dlg.body)
                    box = dlg.findChild(QtWidgets.QDialogButtonBox)
                    self.assertIsNotNone(box)
                    self.assertFalse(dlg.scroll.isAncestorOf(box))
                    self.assertEqual(dlg._bounded_height(2000, 700), 700)
                    self.assertEqual(dlg._bounded_height(100, 700), 200)
                finally:
                    dlg.close()
        finally:
            _close(win)

    # ------------------------------------------------------------ 对比替换守卫
    def test_compare_replace_requires_same_shape(self) -> None:
        win = make_window()
        errors = _silence_errors(win)
        try:
            install(win, synthetic_volume())
            win._append_dataset(synthetic_volume(seed=2), "", "v2")
            QtTest.QTest.qWait(200)
            shapes = [d.vol.shape for d in win.datasets]
            one_d = SeisVolume("1d", np.zeros((1, 1, 32), dtype=np.float32))
            ok = win.dataset_service.replace_active(one_d, "", "one")
            self.assertFalse(ok)
            self.assertEqual([d.vol.shape for d in win.datasets], shapes)
            self.assertTrue(errors)
        finally:
            _close(win)

    # ------------------------------------------------------------ 坏文件
    def test_corrupt_files_raise_load_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_npy = Path(tmp) / "bad.npy"
            bad_npy.write_bytes(b"\x93NUMPY")
            with self.assertRaises(LoadError) as ctx:
                loaders.list_variables(bad_npy)
            self.assertIn("文件头", str(ctx.exception))

            bad_npz = Path(tmp) / "bad.npz"
            bad_npz.write_bytes(b"this is not a zip file")
            with self.assertRaises(LoadError) as ctx:
                loaders.list_variables(bad_npz)
            self.assertIn("读取失败", str(ctx.exception))

    # ------------------------------------------------------------ 缓存
    def test_lru_eviction_and_clear(self) -> None:
        cache: "OrderedDict[str, int]" = OrderedDict()
        sizes: dict[str, int] = {}
        loaders._lru_put(cache, sizes, "a", 1, 10, 2, 100)
        loaders._lru_put(cache, sizes, "b", 2, 10, 2, 100)
        loaders._lru_put(cache, sizes, "c", 3, 10, 2, 100)
        self.assertEqual(list(cache), ["b", "c"])

        cache.clear()                       # 尺寸表里的孤儿项要在下次 put 时清掉
        loaders._lru_put(cache, sizes, "d", 4, 10, 2, 100)
        self.assertEqual(list(cache), ["d"])
        self.assertEqual(sizes, {"d": 10})

        loaders.clear_caches()
        self.assertEqual(len(loaders._mat_cache), 0)
        self.assertEqual(len(loaders._seismic_cache), 0)

    # ------------------------------------------------------------ 来源恢复
    def test_failed_open_restores_source_panel(self) -> None:
        win = make_window()
        try:
            install(win, synthetic_volume())
            win.src_path = "OLD"
            win.file_label.setText("old label")
            win.table.fill([VariableInfo("old", (6, 8, 32), "float32", 0)])
            win.btn_load.setEnabled(True)
            win.src_info.setText("old info")
            with tempfile.TemporaryDirectory() as tmp:
                new = Path(tmp) / "new.npy"
                np.save(new, np.zeros((6, 8, 32), dtype=np.float32))
                svc = win.dataset_service
                svc.load_variable = lambda *a, **k: False
                ok = svc.open_source(str(new), reset=False)
                self.assertFalse(ok)
                self.assertEqual(win.src_path, "OLD")
                self.assertEqual(win.file_label.text(), "old label")
                self.assertEqual([i.key for i in win.table.infos()], ["old"])
                self.assertEqual(win.src_info.text(), "old info")
        finally:
            _close(win)

    # ------------------------------------------------------------ 图片导出取消
    def test_slice_image_export_can_cancel_between_datasets(self) -> None:
        win = make_window()
        try:
            install(win, synthetic_volume())
            win._append_dataset(synthetic_volume(seed=2), "", "v2")
            QtTest.QTest.qWait(200)
            with tempfile.TemporaryDirectory() as tmp:
                dlg = ExportDialog(
                    [{"label": f"d{k + 1}", "vol": d.vol, "pos": d.pos}
                     for k, d in enumerate(win.datasets)], win.active, tmp, "x",
                    line_styles=list(win.line_styles),
                    mode=win.datasets[win.active].mode, parent=win)
                try:
                    dlg.content_ctl.set_value("slice_image")
                    dlg._on_content()
                    dlg.combo_scope.setCurrentIndex(1)
                    out = Path(tmp) / "fig.png"
                    dlg.path_edit.setText(str(out))
                    calls = {"n": 0}

                    def cancel() -> bool:
                        calls["n"] += 1
                        return calls["n"] > 1

                    made = win.export_service.export_slice_figures(
                        dlg, lambda *_: None, cancel)
                    self.assertEqual(len(made), 1)
                    self.assertTrue(Path(made[0]).exists())
                finally:
                    dlg.close()
        finally:
            _close(win)

    # ------------------------------------------------------------ 打包 / 版本
    def test_packaging_spec_and_version_are_release_ready(self) -> None:
        root = Path(__file__).resolve().parent.parent
        spec = (root / "seisview.spec").read_text("utf-8")
        self.assertEqual(spec.count('"pyqtgraph.exporters"'), 1)
        self.assertIn('(SPLASH_IMG, "assets")', spec)

        self.assertEqual(__version__, "0.4.0")
        info = (root / "assets" / "version_info.txt").read_text("utf-8")
        self.assertIn("filevers=(0, 4, 0, 0)", info)
        self.assertIn('StringStruct("FileVersion", "0.4.0")', info)
        self.assertIn('StringStruct("ProductVersion", "0.4.0")', info)

        req = (root / "requirements.txt").read_text("utf-8")
        self.assertIn("pyqtgraph>=0.14", req)
        self.assertIn("segyio>=1.9.14", req)


if __name__ == "__main__":
    unittest.main()
