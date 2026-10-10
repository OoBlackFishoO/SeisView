"""SeisView 项目根目录启动脚本：python main.py [文件路径]"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seisview.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())