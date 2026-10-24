"""黄金测试辅助：固定数据、无头窗口、数组/JSON 快照比较。

黄金文件位于 ``tests/golden/``。首次生成时设置环境变量
``SEISVIEW_UPDATE_GOLDEN=1``，之后正常运行时只读比较，绝不自动覆盖。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# 必须在 import PySide6 之前设置，保证无头运行且不受上次持久化状态影响
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SEISVIEW_NO_PERSIST", "1")
os.environ.setdefault("SEISVIEW_NO_SPLASH", "1")

import numpy as np
from PySide6 import QtCore, QtTest, QtWidgets

from seisview import main_window as mw

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
UPDATE = os.environ.get("SEISVIEW_UPDATE_GOLDEN") == "1"


def synthetic_volume(shape: tuple[int, int, int] = (6, 8, 32),
                     seed: int = 1, scale: float = 1.0,
                     name: str | None = None,
                     with_bad: bool = True) -> mw.SeisVolume:
    """确定性的合成体数据；默认带 NaN / +Inf / -Inf 三个坏点。"""
    rng = np.random.default_rng(seed)
    data = (rng.standard_normal(shape) * scale).astype(np.float32)
    if with_bad and data.size >= 3:
        data[0, 0, 0] = np.nan
        data[1 % shape[0], 1 % shape[1], 1] = np.inf
        data[2 % shape[0], 2 % shape[1], 2] = -np.inf
    return mw.SeisVolume(name=name or f"v{seed}", data=data)


class FakeScreen:
    """offscreen 平台只有 800×800，测试里换成足够大的虚拟屏幕。"""

    def availableGeometry(self) -> QtCore.QRect:
        return QtCore.QRect(0, 0, 1920, 1080)


def ensure_app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make_window() -> mw.MainWindow:
    win = mw.MainWindow()
    win.screen = lambda: FakeScreen()
    win.show()
    QtTest.QTest.qWait(30)
    return win


def install(win: mw.MainWindow, vol: mw.SeisVolume, key: str = "v",
            wait: int = 120) -> None:
    win._install_primary(vol, "", key)
    QtTest.QTest.qWait(wait)


def append(win: mw.MainWindow, vol: mw.SeisVolume, key: str = "v",
           wait: int = 260) -> None:
    win._append_dataset(vol, "", key)
    QtTest.QTest.qWait(wait)


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def assert_golden_npz(name: str, *, exact: bool = False, **arrays) -> None:
    """比较/生成 ``（name）.npz``。浮点默认按 rtol=1e-6 比较，整数与 RGBA 精确比较。"""
    path = GOLDEN_DIR / f"{name}.npz"
    normalized = {k: np.asarray(v) for k, v in arrays.items()}
    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **normalized)
        return
    if not path.exists():
        raise AssertionError(f"缺少黄金文件：{path}（先设置 SEISVIEW_UPDATE_GOLDEN=1 生成）")
    with np.load(path, allow_pickle=False) as expected:
        if set(expected.files) != set(normalized):
            raise AssertionError(
                f"{path.name} 的数组名不一致：期望 {sorted(expected.files)}，"
                f"实际 {sorted(normalized)}")
        for key, actual in normalized.items():
            want = expected[key]
            if exact or (actual.dtype.kind in "iu" and want.dtype.kind in "iu"):
                np.testing.assert_array_equal(actual, want, err_msg=f"{name}:{key}")
            else:
                np.testing.assert_allclose(
                    actual, want, rtol=1e-6, atol=0, equal_nan=True,
                    err_msg=f"{name}:{key}")


def assert_golden_json(name: str, value) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    actual = jsonable(value)
    if UPDATE:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=2,
                                   sort_keys=True), "utf-8")
        return
    if not path.exists():
        raise AssertionError(f"缺少黄金文件：{path}（先设置 SEISVIEW_UPDATE_GOLDEN=1 生成）")
    expected = json.loads(path.read_text("utf-8"))
    if actual != expected:
        raise AssertionError(
            f"{path.name} 不一致：\n实际 = {json.dumps(actual, ensure_ascii=False, sort_keys=True)}\n"
            f"期望 = {json.dumps(expected, ensure_ascii=False, sort_keys=True)}")


def load_golden_json(name: str):
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        raise AssertionError(f"缺少黄金文件：{path}")
    return json.loads(path.read_text("utf-8"))


def _ratios(sizes) -> list[float]:
    values = [int(v) for v in sizes]
    total = sum(max(0, v) for v in values)
    if total <= 0:
        return [0.0 for _ in values]
    return [round(max(0, v) / total, 4) for v in values]


def layout_signature(win: mw.MainWindow) -> dict:
    """布局的结构签名：预设、槽位、树方向与 splitter 比例。"""
    tree = win._tree or {}
    root = tree.get("root")
    inner = tree.get("inner")
    return {
        "preset": tree.get("preset"),
        "slots": list(win._slots()),
        "layout_key": win._layout_key(),
        "layout_vis": list(win._layout_vis()),
        "effective_shown": dict(win._effective_shown()),
        "content_shown": dict(win._content_shown),
        "pair_order": list(win._pair_order),
        "root_orientation": root.orientation().name if root is not None else None,
        "inner_orientation": inner.orientation().name if inner is not None else None,
        "splitter_orientations": [sp.orientation().name for sp in win._tree_splitters],
        "splitter_ratios": [_ratios(sp.sizes()) for sp in win._tree_splitters],
    }


def dataset_signature(win: mw.MainWindow) -> dict:
    return {
        "datasets": [
            {
                "name": ds.vol.name,
                "shape": list(ds.vol.shape),
                "mode": ds.mode,
                "pos": dict(ds.pos),
                "path": ds.path,
                "key": ds.key,
            }
            for ds in win.datasets
        ],
        "active": win.active,
        "panels": len(win.panels),
        "base_clims": len(win.pipeline.base_clims),
        "clims": [list(map(float, pair)) for pair in win._clims],
        "content_shown": dict(win._content_shown),
        "layout_preset": win._layout_preset,
        "pair_order": list(win._pair_order),
        "user_size": list(win._user_size) if win._user_size else None,
    }
