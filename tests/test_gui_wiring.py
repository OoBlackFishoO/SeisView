"""GUI 连线回归测试：设置弹窗、一键收放、分屏、拉出浮窗、侧栏空状态、首帧稳定。

这些用例针对 MainWindow 拆分后出现的"信号槽里抛异常被吞掉、按钮点了没反应"一类
问题：既做行为验证，也做一次静态审计，防止控制器把 ``self`` 当成宿主控件用。
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from golden_utils import (
    ensure_app, install, make_window, synthetic_volume,
)

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

ROOT = Path(__file__).resolve().parent.parent
CONTROLLERS = (
    "display_pipeline", "export_service", "dataset_service",
    "layout_engine", "docking", "sidebar", "settings_cards",
)
# 控制器自身持有的实例属性（其余 ``self.x`` 必须是本类方法，或 ``self.host``）
_OWN_ATTRS = {
    "display_pipeline": {
        "raw_cache", "panel_cache", "shared_base_cache", "face_clim_cache",
        "base_clims", "clims", "active_clim", "stats", "host",
    },
    "sidebar": {"_jump_guard_until", "_jump_token", "_left_anim", "host"},
}


class _StubPrefs(QtWidgets.QDialog):
    """替身：记录 parent 并立刻返回"取消"，避免真的进模态循环。"""

    last_parent = None
    appearanceRequested = QtCore.Signal()
    splitDefaultsRequested = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(kwargs.get("parent"))
        _StubPrefs.last_parent = self.parentWidget()

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Rejected

    def selected_keys(self):
        return []

    def theme_key(self):
        return None

    def follow_layout(self):
        return True

    def layout_choices(self):
        return {}

    def layout_defaults_restored(self):
        return False


class GuiWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = ensure_app()

    def setUp(self) -> None:
        self.win = make_window()

    def tearDown(self) -> None:
        for widget in list(self.win._detached):
            self.win._close_detached(widget, silent=True)
        self.win.close()
        self.win.deleteLater()
        QtTest.QTest.qWait(10)

    # ---------------------------------------------------------- 设置 / 侧栏
    def test_preferences_dialog_gets_window_as_parent(self) -> None:
        """齿轮：弹窗 parent 必须是主窗口，传控制器会直接 TypeError。"""
        _StubPrefs.last_parent = None
        with mock.patch("seisview.sidebar.PreferencesDialog", _StubPrefs):
            self.win.open_preferences()
        self.assertIsNotNone(_StubPrefs.last_parent)
        self.assertIs(_StubPrefs.last_parent, self.win)

    def test_toggle_all_groups_flips_joined_cards(self) -> None:
        """⇕：一键收放会用 QVariantAnimation；parent 给错就整颗按钮失效。"""
        joined = [k for k in self.win.GROUP_ORDER if k in self.win._rail_keys]
        self.assertTrue(joined)
        before = {k: self.win.cards[k].is_expanded() for k in joined}

        self.win._toggle_all_groups()
        QtTest.QTest.qWait(400)

        after = {k: self.win.cards[k].is_expanded() for k in joined}
        self.assertTrue(any(after[k] != before[k] for k in joined),
                        f"一键开关没有生效：{before} -> {after}")

    def test_toggle_all_groups_collapses_when_any_expanded(self) -> None:
        """⇕ 的新语义：只要有一组展开，点击就全部收起；全收起时才全部展开。"""
        joined = [k for k in self.win.GROUP_ORDER if k in self.win._rail_keys]
        self.assertTrue(joined)
        for key in joined:
            self.win.cards[key].set_expanded(True, animate=False)
        self.win.cards[joined[0]].set_expanded(False, animate=False)
        QtTest.QTest.qWait(30)

        self.win._toggle_all_groups()
        QtTest.QTest.qWait(400)
        self.assertTrue(all(not self.win.cards[k].is_expanded() for k in joined))

        self.win._toggle_all_groups()
        QtTest.QTest.qWait(400)
        self.assertTrue(all(self.win.cards[k].is_expanded() for k in joined))

    def test_left_empty_hint_follows_rail_keys(self) -> None:
        """侧栏空状态：``hasattr`` 必须查宿主，否则引导文案永远不出现。"""
        keys_before = list(self.win._rail_keys)
        try:
            self.win._rail_keys = []
            self.win._sync_left_empty_hint()
            self.assertTrue(self.win.left_empty_hint.isVisible())
            self.assertTrue(all(not c.isVisible() for c in self.win.cards.values()))
        finally:
            self.win._rail_keys = keys_before
            self.win._sync_left_empty_hint()

    # ---------------------------------------------------------- 分屏 / 浮窗
    def test_capsule_uses_reset_button_instead_of_split(self) -> None:
        """「分屏」入口已移入设置：胶囊右侧改为复位布局的刷新键。"""
        self.assertFalse(hasattr(self.win.capsule, "split_btn"))
        self.assertTrue(self.win.capsule.reset_btn.isVisible())
        self.win.capsule.reset_btn.click()      # 不应抛异常
        QtTest.QTest.qWait(30)

    def test_preferences_default_split_editor(self) -> None:
        """默认分屏子窗口：四种组合各一组缩略图，整块方框可点选。"""
        from seisview.widgets import SplitDefaultsDialog

        groups = self.win.layout_default_groups()
        self.assertEqual(len(groups), 4)
        dlg = SplitDefaultsDialog(groups, parent=self.win)
        try:
            self.assertEqual(len(dlg._thumbs), 10)
            self.assertEqual(sum(1 for _g, _k, _o, t in dlg._thumbs
                                 if t.default), 4)
            # 点三块组里 A 的整块缩略图 → 该组选中 A，且每组仍只有一颗星
            target = next(t for g, k, _o, t in dlg._thumbs
                          if g == "three" and k == "A")
            target.clicked.emit()
            self.assertEqual(dlg.choices()["three"][0], "A")
            self.assertEqual(sum(1 for _g, _k, _o, t in dlg._thumbs
                                 if t.default), 4)
            dlg._restore_builtin()
            self.assertTrue(dlg.restored())
            self.assertEqual(dlg.choices()["three"][0], "B")
        finally:
            dlg.close()

    def test_tear_off_creates_floating_panel(self) -> None:
        """拖出面板：FloatingPanel 的 parent 必须是窗口，否则拉不出独立窗口。"""
        install(self.win, synthetic_volume())
        target = self.win.trace_frame
        stamp = target.size()
        drag = {
            "target": target, "size": stamp,
            "offset": QtCore.QPoint(0, 0),
            "pinned_holder": None, "ghost": None, "layer": None,
        }
        outside = self.win.frameGeometry().bottomRight() + QtCore.QPoint(60, 60)

        self.win.docking._tear_off(drag, outside)

        panel = self.win._detached.get(target)
        self.assertIsNotNone(panel)
        self.assertTrue(panel.isVisible())
        self.assertIs(panel.parentWidget(), self.win)

        self.win._close_detached(target)
        QtTest.QTest.qWait(30)
        self.assertNotIn(target, self.win._detached)

    # ---------------------------------------------------------- 一维 / 二维
    def test_2d_disables_3d_button_and_fits_slice(self) -> None:
        """二维数据：三维键置灰；换数据后窗口按剖面自然尺寸重算，不沿用旧锚点。"""
        install(self.win, synthetic_volume())
        self.win.resize(1600, 980)
        QtTest.QTest.qWait(120)
        vol2d = synthetic_volume(shape=(1, 72, 700), seed=5)
        self.win._install_primary(vol2d, "", "v2d")
        QtTest.QTest.qWait(350)

        self.assertFalse(self.win.capsule.buttons["side3d"].isEnabled())
        self.assertTrue(self.win.capsule.buttons["slice"].isEnabled())
        self.assertFalse(self.win._content_shown["right"])
        self.assertLess(self.win.width(), 1200, "二维载入后仍在沿用三维时的大窗口")

        self.win.capsule.buttons["side3d"].click()
        QtTest.QTest.qWait(60)
        self.assertFalse(self.win._content_shown["right"], "置灰的三维键仍被点开了")

    def test_1d_import_keeps_only_trace_panel(self) -> None:
        """一维数据导入后只留单道波形，剖面与三维键置灰不可点。"""
        import tempfile

        arr = np.linspace(-1.0, 1.0, 256, dtype=np.float32)
        fd, path = tempfile.mkstemp(suffix=".npy")
        os.close(fd)
        try:
            np.save(path, arr)
            self.assertTrue(self.win._open_source(path, reset=True))
            QtTest.QTest.qWait(300)

            self.assertEqual(self.win._content_shown,
                             {"slice": False, "trace": True, "right": False})
            self.assertTrue(self.win.capsule.buttons["trace"].isEnabled())
            self.assertFalse(self.win.capsule.buttons["slice"].isEnabled())
            self.assertFalse(self.win.capsule.buttons["side3d"].isEnabled())
            self.assertTrue(self.win.trace_frame.isVisible())
        finally:
            # .npy 走 mmap，先清掉数据释放句柄再删（Windows 上文件被占用会拒绝删除）
            self.win.clear_data()
            QtTest.QTest.qWait(50)
            try:
                os.unlink(path)
            except PermissionError:                     # pragma: no cover
                pass

    def test_goto_group_after_sidebar_expand_scrolls_into_view(self) -> None:
        """侧栏收起时点分组图标：要等展开动画结束再滚，卡片必须真的进视野。"""
        for key in self.win.GROUP_ORDER:
            self.win.cards[key].set_expanded(True, animate=False)
        self.win._set_region_visible("left", False, animate=False)
        QtTest.QTest.qWait(80)

        self.win._goto_group("density")
        QtTest.QTest.qWait(650)

        card = self.win.cards["density"]
        top = card.mapTo(self.win.left_body.viewport(),
                         card.rect().topLeft()).y()
        self.assertGreaterEqual(top, 0)
        self.assertLess(top, self.win.left_body.viewport().height(),
                        "分组卡片没有滚进视野")

    def test_goto_group_all_collapse_states(self) -> None:
        """全展开 / 目标收起 / 侧栏收起 / 全收起 时，跳转都必须把卡片带进视野。"""
        keys = list(self.win.GROUP_ORDER)
        cases = [
            ("all-open", {k: True for k in keys}, False),
            ("target-collapsed", {k: (k != "density") for k in keys}, False),
            ("all-open-closed", {k: True for k in keys}, True),
            ("target-collapsed-closed", {k: (k != "density") for k in keys}, True),
            ("all-collapsed-closed", {k: False for k in keys}, True),
        ]
        for name, state, closed in cases:
            with self.subTest(case=name):
                for key in keys:
                    self.win.cards[key].set_expanded(state[key], animate=False)
                if closed and self.win._region_shown.get("left", True):
                    self.win._set_region_visible("left", False, animate=False)
                elif not closed and not self.win._region_shown.get("left", True):
                    self.win._set_region_visible("left", True, animate=False)
                QtTest.QTest.qWait(60)
                self.win._goto_group("density")
                QtTest.QTest.qWait(700)
                card = self.win.cards["density"]
                top = card.mapTo(self.win.left_body.viewport(),
                                 card.rect().topLeft()).y()
                self.assertGreaterEqual(top, 0)
                self.assertLess(top, self.win.left_body.viewport().height(),
                                f"{name}: 卡片没有滚进视野")

    def test_pure_compare_keeps_all_panels(self) -> None:
        """对比 + 仅显示波形：每个剖面面板各画自己的波形，不再只留第一幅。"""
        install(self.win, synthetic_volume())
        self.win._append_dataset(synthetic_volume(seed=2), "", "v2")
        QtTest.QTest.qWait(150)
        self.win.chk_pure.setChecked(True)
        QtTest.QTest.qWait(200)

        self.assertTrue(self.win.chk_wiggle.isChecked())
        self.assertEqual(len(self.win.panels), 2)
        for panel in self.win.panels:
            self.assertTrue(panel.isVisible())
            self.assertTrue(panel.view._wiggles, "面板没有画自己的波形")

    def test_sidebar_collapse_width_is_monotonic(self) -> None:
        """侧栏收展：窗口宽度和分栏一起滑，不先跳后补。"""
        widths: list[int] = []

        def snap() -> None:
            widths.append(self.win.width())

        self.win._set_region_visible("left", False)
        for delay in (10, 50, 100, 160):
            QtCore.QTimer.singleShot(delay, snap)
        QtTest.QTest.qWait(320)

        self.assertGreaterEqual(len(widths), 3)
        self.assertEqual(widths, sorted(widths, reverse=True),
                         f"窗口宽度不是单调收缩：{widths}")
        self.assertFalse(self.win._left_animating)

    # ---------------------------------------------------------- 首帧闪烁
    def test_first_frame_already_shows_workspace(self) -> None:
        """载入数据后的第一帧就该有完整布局，不能先空一帧再长出三块。"""
        samples: list[float] = []

        def grab() -> None:
            img = self.win.grab().toImage().convertToFormat(
                QtGui.QImage.Format.Format_RGB32)
            crop = img.copy(340, 60, 700, 280)
            buf = np.frombuffer(crop.bits(), dtype=np.uint8).reshape(
                crop.height(), crop.width() * 4)
            samples.append(float(np.std(buf)))

        QtCore.QTimer.singleShot(3, grab)
        QtCore.QTimer.singleShot(8, grab)
        self.win._install_primary(synthetic_volume(), "", "v")
        QtTest.QTest.qWait(120)

        self.assertEqual(len(samples), 2)
        # 空白工作区是纯色（std≈0）；有剖面/单道/三维时方差远大于此。
        self.assertGreater(min(samples), 30.0,
                           f"首帧工作区仍是空的：{samples}")

    # ---------------------------------------------------------- 静态审计
    def test_controllers_only_touch_host_and_own_methods(self) -> None:
        """控制器里 ``self.foo`` 只能是本类方法 / 自身属性，宿主一律走 ``self.host``。"""
        problems: list[str] = []
        for name in CONTROLLERS:
            tree = ast.parse((ROOT / "seisview" / f"{name}.py").read_text("utf-8"))
            allowed = set(_OWN_ATTRS.get(name, ()))
            for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
                methods = {n.name for n in cls.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                    for node in ast.walk(fn):
                        if not (isinstance(node, ast.Attribute)
                                and isinstance(node.value, ast.Name)
                                and node.value.id == "self"):
                            continue
                        if node.attr == "host" or node.attr in methods or node.attr in allowed:
                            continue
                        problems.append(f"{name}.{cls.name}.{fn.name}: self.{node.attr}")
        self.assertEqual(problems, [], "控制器误把 self 当宿主：\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
