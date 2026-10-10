@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  SeisView 打包（文件夹模式，双击即用）
echo ============================================
echo.

echo [1/3] 检查 PyInstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo      未安装，正在安装 ...
    python -m pip install "pyinstaller>=6" -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo      安装失败，请检查网络或 Python 环境。
        pause
        exit /b 1
    )
)

echo [2/3] 生成图标 ...
python make_icon.py

echo [3/3] 开始打包（第一次会慢一些，几分钟）...
python -m PyInstaller seisview.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo 打包失败，往上翻看错误信息。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  完成！  程序在： dist\SeisView\SeisView.exe
echo.
echo  双击这个 exe 就能用。
echo  想要桌面图标：右键 SeisView.exe - 发送到 - 桌面快捷方式。
echo  注意：dist\SeisView 整个文件夹要一起保留，不能只拷 exe。
echo ============================================
echo.
pause