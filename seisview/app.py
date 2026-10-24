"""SeisView 启动入口。"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import APP_NAME

# 启动画面用色**先写死**：此时还不 import style，尽量缩短“进程已启动、
# 但屏幕上还没有任何窗口”的空窗期。取值与默认深蓝主题一致。
_SPLASH_BG = "#0B0E14"
_SPLASH_LINE = "#3D4A63"
_SPLASH_TEXT = "#E6EDF7"
_SPLASH_ACCENT = "#38BDF8"
_SPLASH_DIM = "#8A94A6"
_SPLASH_FONT = "Segoe UI"


def asset_path(name: str) -> Path | None:
    """找资源文件。

    源码运行时资源在项目根的 assets/ 下；用 PyInstaller 打包后会被解到
    ``sys._MEIPASS`` 指向的临时目录，所以两种位置都要找。
    """
    roots = [Path(getattr(sys, "_MEIPASS", "")) if hasattr(sys, "_MEIPASS") else None,
             Path(__file__).resolve().parent.parent]
    for root in roots:
        if root is None:
            continue
        p = root / "assets" / name
        if p.exists():
            return p
    return None


def _make_splash() -> QtWidgets.QSplashScreen | None:
    """轻量启动画面：窗口骨架还在构建时先给一个“正在载入”的反馈。

    优先直接加载 ``assets/splash.png``（与打包版 bootloader 的 splash 同一张图），
    加载不到时才用 QPainter 现画一份兜底。
    """
    if os.environ.get("SEISVIEW_NO_SPLASH"):
        return None
    pm = QtGui.QPixmap()
    path = asset_path("splash.png")
    if path is not None:
        pm.load(str(path))
    if pm.isNull():
        pm = QtGui.QPixmap(520, 260)
        pm.fill(QtGui.QColor(_SPLASH_BG))
        p = QtGui.QPainter(pm)
        try:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            p.setPen(QtGui.QPen(QtGui.QColor(_SPLASH_LINE), 1))
            p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
            p.setPen(QtGui.QColor(_SPLASH_TEXT))
            p.setFont(QtGui.QFont(_SPLASH_FONT, 30, QtGui.QFont.Weight.DemiBold))
            p.drawText(pm.rect().adjusted(36, 54, -36, 0),
                       QtCore.Qt.AlignmentFlag.AlignLeft, APP_NAME)
            p.setPen(QtGui.QColor(_SPLASH_ACCENT))
            p.setFont(QtGui.QFont(_SPLASH_FONT, 11))
            p.drawText(pm.rect().adjusted(38, 128, -36, 0),
                       QtCore.Qt.AlignmentFlag.AlignLeft, "地震数据可视化")
            p.setPen(QtGui.QColor(_SPLASH_DIM))
            p.drawText(pm.rect().adjusted(38, 174, -36, 0),
                       QtCore.Qt.AlignmentFlag.AlignLeft, "正在准备界面…")
        finally:
            p.end()
    splash = QtWidgets.QSplashScreen(pm)
    splash.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QtGui.QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        splash.move(geo.center() - pm.rect().center())
    splash.show()
    QtWidgets.QApplication.processEvents()
    return splash


def _pyi_splash():
    """打包版的 PyInstaller 启动画面（源码运行时返回 None）。

    PyInstaller 的 splash 由 bootloader 在 Python 代码执行前就画出来，
    正好补上“双击 exe → Qt 启动画面出现”之间那段空窗。
    """
    if not getattr(sys, "frozen", False):
        return None
    try:
        import pyi_splash                      # type: ignore[import-not-found]
    except ImportError:
        return None
    if os.environ.get("SEISVIEW_NO_SPLASH"):
        try:
            pyi_splash.close()
        except Exception:                       # pragma: no cover
            pass
        return None
    return pyi_splash


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # 让所有 OpenGL 上下文共享资源（必须在 QApplication 之前设）。
    # 三维面板可以整块拉到独立窗口 / 再放回来，控件会被 reparent、GL 上下文随之重建；
    # 不共享的话，pyqtgraph 缓存在类上的着色器程序在新上下文里全部失效，三维面板
    # 会变成一片空白并刷一屏 GLError。共享之后程序与顶点缓冲跨上下文仍有效。
    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QtWidgets.QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    # 启动画面尽量早：打包版直接用 bootloader 的 splash（比 Qt 还早），
    # 源码运行则立刻建 Qt splash；主题、图标都放到 splash 之后。
    boot_splash = _pyi_splash()
    splash = None if boot_splash is not None else _make_splash()

    from . import style
    style.apply_theme(app)
    icon = asset_path("seisview.ico") or asset_path("seisview.png")
    if icon is not None:                 # 任务栏 / 标题栏图标
        app.setWindowIcon(QtGui.QIcon(str(icon)))

    # 主窗口模块（pyqtgraph 等）挪到启动画面之后才 import：这一段耗时
    # 现在有东西可看，而不是一段纯黑等待。
    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    # 后台预热示例数据：scipy 的首次 import 在冷启动时可能卡一两秒，
    # 放到这里就不会让第一次点「载入示例」看起来像未响应。
    from .sample import prewarm
    threading.Thread(target=prewarm, name="seisview-sample-warmup",
                     daemon=True).start()
    if boot_splash is not None:
        # 等主窗口真正画出第一帧再收起 bootloader 的 splash，避免露出未绘制的灰底。
        def _close_boot() -> None:
            try:
                boot_splash.close()
            except Exception:                   # pragma: no cover
                pass

        QtCore.QTimer.singleShot(60, _close_boot)
    elif splash is not None:
        splash.finish(win)
    # 命令行里给了文件就直接打开
    if len(argv) > 1:
        win.open_path(argv[1])
    return app.exec()


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())
