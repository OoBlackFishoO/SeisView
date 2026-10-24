"""导出论文用图与线型设置的共享定义。

放在独立模块里，供导出对话框、导出服务、离屏绘图与主窗口共同使用，
避免 ``widgets`` ↔ ``settings_cards`` ↔ ``export_service`` 之间循环依赖。
"""

from __future__ import annotations

from dataclasses import dataclass

LINE_COLORS = [
    ("黑", "#111827"), ("红", "#D62828"), ("蓝", "#1D4ED8"),
    ("绿", "#15803D"), ("橙", "#C2410C"), ("紫", "#7E22CE"),
    ("青", "#0E7490"), ("灰", "#6B7280"), ("白", "#FFFFFF"),
]
LINE_STYLES = [("实线", "solid"), ("虚线", "dash"),
               ("点线", "dot"), ("点划线", "dashdot")]
DEFAULT_LINE_STYLES = [("#111827", "solid"),
                       ("#D62828", "solid"),
                       ("#1D4ED8", "dash")]

FONT_FAMILIES = ("Arial", "Times New Roman", "DejaVu Sans")

# 论文图里的文字：中文 / 英文两套，随「图注语言」切换。
# 放在共享模块里，导出对话框（只改字段）与导出服务（真正画图）用同一份。
FIGURE_TEXT = {
    "zh": {
        "shot": ("检波器 R (m)", "时间 T (s)", "振幅"),
        "recv": ("炮点 S (m)", "时间 T (s)", "振幅"),
        "time": ("检波器 R (m)", "炮点 S (m)", "振幅"),
        "offset": "偏移距 (m)",
        "wave_x": "时间 T (s)",
        "wave_y": "振幅",
        "data": "数据",
    },
    "en": {
        "shot": ("Receiver R (m)", "Time T (s)", "Amplitude"),
        "recv": ("Source S (m)", "Time T (s)", "Amplitude"),
        "time": ("Receiver R (m)", "Source S (m)", "Amplitude"),
        "offset": "Offset (m)",
        "wave_x": "Time T (s)",
        "wave_y": "Amplitude",
        "data": "Data",
    },
}


def figure_labels(mode: str, language: str = "zh",
                  offset: bool = False) -> tuple[str, str, str]:
    """某一面 / 某种语言下的 (横轴, 纵轴, 色标) 文字。

    ``offset=True`` 只对共炮点剖面有效：横轴改用「偏移距（R − S）」。
    """
    text = FIGURE_TEXT.get(language, FIGURE_TEXT["zh"])
    if mode == "shot" and offset:
        return text["offset"], text["shot"][1], text["shot"][2]
    return text.get(mode, text["shot"])


@dataclass(frozen=True)
class ExportFigureOptions:
    """一张论文用图的尺寸、字体、线宽与标注口径。"""

    width_mm: float = 180.0
    height_mm: float = 130.0
    dpi: int = 300
    font_family: str = "Arial"
    font_pt: float = 14.0
    line_width_pt: float = 1.0
    colorbar: bool = True
    colorbar_pos: str = "right"       # right / bottom
    colorbar_label: bool = False      # 论文插图通常只留刻度数字，不加“振幅”
    legend: bool = True               # wiggle / 波形图：多份数据叠加时显示图例
    ticks_inside: bool = True         # True 刻度朝图内 / False 朝图外
    x_tick_major: float = 0.0         # >0 = 自定义横轴主刻度间隔（s 或 m）
    y_tick_major: float = 0.0         # >0 = 自定义纵轴主刻度间隔
    x_edge_ticks: bool = False        # 强制在横轴两端补刻度数字
    y_edge_ticks: bool = False        # 强制在纵轴两端补刻度数字
    offset_axis: bool = False         # 共炮点剖面：横轴用偏移距 R − S
    x_numbers_side: str = "bottom"    # 横轴刻度数字：bottom / top
    y_numbers_side: str = "left"      # 纵轴刻度数字：left / right
    xlabel_side: str = "bottom"       # 横轴标题：bottom / top
    ylabel_side: str = "left"         # 纵轴标题：left / right
    xlabel_override: str | None = None   # None = 跟随图注语言；"" = 不显示
    ylabel_override: str | None = None
    transparent: bool = False
    title: str = ""
    language: str = "zh"              # 图注语言：zh 中文 / en 英文

    def pixel_size(self) -> tuple[int, int]:
        """按物理尺寸与 DPI 换算成最终像素尺寸。"""
        return (max(1, round(self.width_mm / 25.4 * self.dpi)),
                max(1, round(self.height_mm / 25.4 * self.dpi)))

    def font_px(self) -> int:
        return max(1, round(self.font_pt * self.dpi / 72))

    def line_width_px(self) -> float:
        return max(0.3, self.line_width_pt * self.dpi / 72)
