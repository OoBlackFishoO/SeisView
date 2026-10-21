"""SeisView 启动入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from . import APP_NAME, style


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

    不做重活、不等后台线程，只是把启动阶段的空白感消掉。
    """
    if os.environ.get("SEISVIEW_NO_SPLASH"):
        return None
    pm = QtGui.QPixmap(520, 260)
    pm.fill(QtGui.QColor(style.BG))
    p = QtGui.QPainter(pm)
    try:
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor(style.LINE_HI), 1))
        p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
        p.setPen(QtGui.QColor(style.TEXT))
        p.setFont(QtGui.QFont(style.UI_FONT, 30, QtGui.QFont.Weight.DemiBold))
        p.drawText(pm.rect().adjusted(36, 54, -36, 0),
                   QtCore.Qt.AlignmentFlag.AlignLeft, APP_NAME)
        p.setPen(QtGui.QColor(style.ACCENT))
        p.setFont(QtGui.QFont(style.UI_FONT, 11))
        p.drawText(pm.rect().adjusted(38, 128, -36, 0),
                   QtCore.Qt.AlignmentFlag.AlignLeft, "地震数据可视化")
        p.setPen(QtGui.QColor(style.TEXT_DIM))
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
    icon = asset_path("seisview.ico") or asset_path("seisview.png")
    if icon is not None:                 # 任务栏 / 标题栏图标
        app.setWindowIcon(QtGui.QIcon(str(icon)))
    style.apply_theme(app)

    splash = _make_splash()
    # 主窗口模块（pyqtgraph 等）挪到启动画面之后才 import：这一段耗时
    # 现在有东西可看，而不是一段纯黑等待。
    from .main_window import MainWindow
    win = MainWindow()
    win.show()
    if splash is not None:
        splash.finish(win)
    # 命令行里给了文件就直接打开
    if len(argv) > 1:
        win.open_path(argv[1])
    return app.exec()


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())