# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— 全量版（保留 scipy，所以 .mat 仍可读）。

用法（在项目根目录）：
    python -m PyInstaller seisview.spec --noconfirm --clean

产物：dist/SeisView/SeisView.exe
这是"文件夹模式"（onedir）。双击 SeisView.exe 即可运行；想要桌面图标就右键它
→ 发送到 → 桌面快捷方式（图标会自动带上）。整个 dist/SeisView 目录必须一起
保留或一起拷贝，不能只拷 exe。
"""

import os

from PyInstaller.utils.hooks import collect_submodules

HERE = os.path.abspath(os.getcwd())

ICON = os.path.join("assets", "seisview.ico")

# exe 的版本资源：PyInstaller 的 version= 要的是**文件路径**（写成 "0.3.0" 会被当成路径去
# 找文件而报错）。资源内容见 assets/version_info.txt —— 里面的版本号要与
# seisview/__init__.py 的 __version__ 保持一致。
VERSION_TXT = os.path.join("assets", "version_info.txt")

# 用不到的大件，明确排除。PySide6 全量装完 450+ MB，其中 WebEngine 一项就上百 MB；
# 本程序只用 QtCore/QtGui/QtWidgets/QtOpenGL（pyqtgraph 的 3D 需要 OpenGL）。
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebSockets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtDesigner",
    "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtSerialPort",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6",
    # 实测坑：_pyinstaller_hooks_contrib 里的 hook-pyqtgraph 会顺着
    # PyInstaller 的模块图把 torch 一路分析进来，凭空多出 3.5 GB 的 CUDA 运行库
    # （torch_cuda.dll 885 MB、cudnn 561 MB…）。本程序完全不碰这些，必须显式排掉。
    "torch", "torchaudio", "torchvision", "torchgen",
    "tensorboard", "tensorflow", "keras", "sklearn", "pandas",
    "numba", "llvmlite", "cv2", "h5py", "sympy", "psutil",
    "jupyter", "jupyter_rfb", "jupyter_client", "notebook", "nbformat",
    "nbconvert", "ipykernel", "pyqtgraph.jupyter", "pyqtgraph.exporters",
]

# PyOpenGL 和 pyqtgraph 都会在运行时动态 import 子模块，静态分析扫不到，
# 必须显式收集，否则打包后会报 "cannot find platform module" 之类。
HIDDEN = [
    "scipy.io",                 # .mat 读取
    "segyio", "segyio._segyio",  # SEG-Y / SU 读取
    *collect_submodules("OpenGL"),
    "pyqtgraph.opengl",
]

a = Analysis(
    ["main.py"],
    pathex=[HERE],
    binaries=[],
    datas=[(ICON, "assets"), (os.path.join("assets", "seisview.png"), "assets")],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SeisView",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX 压缩会拖慢启动，还容易被杀软误报
    console=False,               # 双击不弹黑窗
    disable_windowed_traceback=False,   # 真崩了给个带信息的对话框，别静默退出
    icon=ICON,
    version=VERSION_TXT,         # 写进 exe 的 FileVersion / ProductVersion
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SeisView",
)