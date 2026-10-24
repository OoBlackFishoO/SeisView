"""分屏布局的共享常量：面板顺序、预设、两栏组合与贴边判定。

放在独立模块里，避免布局引擎与主窗口各自维护一份表。
"""

from __future__ import annotations

from .widgets import (LAYOUT_GROUP, LAYOUT_TITLE, THREE_PINNED)

CAPSULE_KEY = {"trace": "trace", "slice": "slice", "side3d": "right"}
PANEL_LABELS = {"trace": "单道波形", "slice": "剖面", "right": "三维"}
PANEL_ORDER = ("slice", "trace", "right")
PANEL_PRIORITY = {"slice": 3.0, "trace": 2.0, "right": 1.0}

KEY_PAIR = {"SR": ("slice", "right"), "TR": ("right", "trace"),
            "ST": ("slice", "trace")}
GROUP_OF = LAYOUT_GROUP
PINNED_OF = THREE_PINNED

# 贴边感应带占工作区该方向的比例
EDGE_FRAC = 1.0 / 3.0
# Workspace 的边距（胶囊与落位预览用）
WORKSPACE_MARGIN = 8
