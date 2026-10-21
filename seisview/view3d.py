"""三维数据体视图：线框立方体 + 三个正交面贴图 + 点击拾取。

世界坐标约定
------------
``X = 检波器 R``、``Y = 炮点 S``、``Z = 时间 T``（pyqtgraph 的相机方位角在 XY
平面内，Z 是"向上"方向，因此把时间放在 Z 轴，三维旋转手感最自然）。

**时间的显示方向**：与剖面、单道波形保持一致 —— 顶部是 t=0，**向下增大**。
Z 轴本身的几何方向仍然朝上，但贴图与切片位置按"t=0 在顶"来放，这样三块视图
读起来方向相同，不用在脑子里翻转。

为什么各轴要归一化
------------------
地震体的三个方向量纲不同（例如 24 炮 × 72 道 × 700 采样），严格按采样点数画
出来是一根几乎看不见的细柱。因此按"最短轴至少占最长轴的 45%"做显示缩放：
只改变观感，不改变切片位置与物理读数。

三个面
------
- 共炮点面：``Y = s`` 的竖直面，横轴 R、纵轴 T
- 共检波点面：``X = r`` 的竖直面，横轴 S、纵轴 T
- 时间切片：``Z = t`` 的水平面，横轴 R、纵轴 S

点击拾取用射线与平面求交：从鼠标位置反投影出一条世界坐标射线，与三个候选面
求交，取最近的一个。该方式不依赖 OpenGL 的拾取缓冲，结果稳定可测。
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph.opengl as gl
from PySide6 import QtCore, QtGui
from shiboken6 import isValid

from . import render, style
from .volume import SeisVolume


class CameraAnimator(QtCore.QObject):
    """把 GLViewWidget 的相机参数包装成可被 QPropertyAnimation 驱动的属性。"""

    azimuthChanged = QtCore.Signal(float)
    elevationChanged = QtCore.Signal(float)
    distanceChanged = QtCore.Signal(float)

    def __init__(self, view: "VolumeView3D"):
        super().__init__(view)
        self._view = view

    def _az(self) -> float:
        return float(self._view.opts["azimuth"])

    def _set_az(self, v: float) -> None:
        self._view.opts["azimuth"] = float(v)
        self._view.update()
        self.azimuthChanged.emit(float(v))

    def _el(self) -> float:
        return float(self._view.opts["elevation"])

    def _set_el(self, v: float) -> None:
        self._view.opts["elevation"] = float(v)
        self._view.update()
        self.elevationChanged.emit(float(v))

    def _dist(self) -> float:
        return float(self._view.opts["distance"])

    def _set_dist(self, v: float) -> None:
        self._view.opts["distance"] = float(max(1e-3, v))
        self._view.update()
        self.distanceChanged.emit(float(v))

    azimuth = QtCore.Property(float, _az, _set_az, notify=azimuthChanged)
    elevation = QtCore.Property(float, _el, _set_el, notify=elevationChanged)
    distance = QtCore.Property(float, _dist, _set_dist, notify=distanceChanged)


# 各面的正视方位角 / 仰角
# 方位角的选取让每个面的横轴都朝屏幕右侧增大（与二维剖面一致，不会是镜像）
_FOCUS = {
    "recv": (0.0, 8.0),     # 面法线沿 X，屏幕右 = +Y = 炮点 S
    "shot": (-90.0, 8.0),   # 面法线沿 Y，屏幕右 = +X = 检波器 R
    "time": (90.0, 88.0),   # 面法线沿 Z（自上而下俯视）
}

# 显示缩放：最短轴至少占最长轴的这一比例
_MIN_AXIS_FRAC = 0.45


class VolumeView3D(gl.GLViewWidget):
    """三维数据体导航视图。"""

    faceClicked = QtCore.Signal(str)   # 'shot' / 'recv' / 'time'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundColor(style.GL_BG)
        # fov 是**水平**视场角；35° 的窄视角透视畸变小，更像工程软件的正投影
        self.opts["fov"] = 35
        # **不设最小尺寸**：三维面板要能被收放动画压到 0；展开后不被拖扁由所在容器
        # 的最小尺寸保证（见 main_window._hold_content_min）。

        self._vol: SeisVolume | None = None
        self._s = self._r = self._t = 0
        self._counts = (1, 1, 1)        # 各轴的采样点数 (R, S, T)
        self._lens = (1.0, 1.0, 1.0)    # 各轴的显示长度 (R, S, T)

        self._box: gl.GLBoxItem | None = None
        self._faces: dict[str, gl.GLImageItem] = {}
        self._labels: list[gl.GLTextItem] = []
        self._press_pos: QtCore.QPoint | None = None
        # 自动取景：为 True 时面板尺寸一变就按记下的视角重算取景距离（用户转过/缩放过
        # 之后置 False，不再插手）。见 resizeEvent / _refit。
        self._auto_fit = True
        self._fit_view: tuple[float, float] | None = None

        self._anim = CameraAnimator(self)
        self._anims: list[QtCore.QPropertyAnimation] = []

    # ------------------------------------------------------------ 构建
    def set_volume(self, vol: SeisVolume) -> None:
        self.clear()
        self._faces.clear()
        self._labels.clear()
        self._vol = vol

        self._counts = (vol.nr, vol.ns, vol.nt)
        longest = max(self._counts)
        self._lens = tuple(float(max(c, longest * _MIN_AXIS_FRAC))
                           for c in self._counts)

        self._box = gl.GLBoxItem(size=QtGui.QVector3D(*self._lens),
                                 color=style.GL_BOX, glOptions="translucent")
        self.addItem(self._box)

        for mode in ("shot", "recv", "time"):
            item = gl.GLImageItem(np.zeros((2, 2, 4), dtype=np.ubyte), glOptions="opaque")
            self.addItem(item)
            self._faces[mode] = item

        self._add_axis_labels()
        self.reset_view()

    def _disp(self, axis: int, index: int) -> float:
        """把某轴的切片序号映射到显示坐标。"""
        n = max(1, self._counts[axis] - 1)
        return float(index) / n * self._lens[axis]

    def _disp_z(self, index: int) -> float:
        """时间切片的显示高度：t=0 在立方体顶端，向下增大。"""
        n = max(1, self._counts[2] - 1)
        return self._lens[2] * (1.0 - float(index) / n)

    def _add_axis_labels(self) -> None:
        # GLTextItem 内部会做 QVector3D(*self.pos)，因此 pos 必须是三元组，
        # 直接传 QVector3D 会在绘制时抛 TypeError。
        lx, ly, lz = self._lens
        font = QtGui.QFont(style.UI_FONT, 9)
        specs = [
            ("检波器 R", (lx, -ly * 0.08, 0.0)),
            ("炮点 S", (-lx * 0.08, ly, 0.0)),
            ("时间 T ↓", (-lx * 0.08, -ly * 0.08, lz)),
        ]
        for text, pos in specs:
            try:
                item = gl.GLTextItem(text=text, pos=pos, color=style.TEXT_DIM,
                                     font=font)
            except Exception:
                continue
            self.addItem(item)
            self._labels.append(item)

    def clear_volume(self) -> None:
        self.clear()
        self._faces.clear()
        self._labels.clear()
        self._box = None
        self._vol = None

    def restyle(self) -> None:
        """换主题：画布底色、外框线、轴标签颜色跟着走。

        轴标签只能**重建**（``GLTextItem`` 没有改色接口），手上有数据卷时才重建 ——
        没数据时标签本来就不存在，重建会去取不存在的 ``_lens``。
        """
        self.setBackgroundColor(style.GL_BG)
        if self._box is not None:
            try:
                self._box.setColor(style.GL_BOX)
            except Exception:                        # pragma: no cover
                pass
        if self._vol is not None:
            for item in list(self._labels):
                try:
                    self.removeItem(item)
                except Exception:                    # pragma: no cover
                    pass
            self._labels.clear()
            self._add_axis_labels()
        self.update()

    # ------------------------------------------------------------ 刷新
    def update_faces(self, s: int, r: int, t: int,
                     faces: dict[str, tuple[np.ndarray, tuple[float, float]]],
                     cmap: str) -> None:
        """用主窗口算好的三个面刷新贴图。

        ``faces[mode] = (二维显示数组, 色标)``，数组由 ``volume.display_face``
        产出，与二维剖面**完全相同**（含同一套抽稀、AGC 与色标）。这里只负责
        摆方向、上色，不再自己算 AGC / 抽稀 / 色标 —— 否则三维与二维会再次分叉。
        """
        if self._vol is None:
            return
        self._s, self._r, self._t = s, r, t

        shot_img = render.face_texture(
            render.face_orientation(faces["shot"][0], "shot"),
            cmap, faces["shot"][1])
        item = self._faces["shot"]
        item.setData(shot_img)
        item.resetTransform()
        item.scale(self._lens[0] / shot_img.shape[0],
                   self._lens[2] / shot_img.shape[1], 1.0)
        item.rotate(90, 1, 0, 0)                 # 局部 y → 世界 Z
        item.translate(0, self._disp(1, s), 0)

        recv_img = render.face_texture(
            render.face_orientation(faces["recv"][0], "recv"),
            cmap, faces["recv"][1])
        item = self._faces["recv"]
        item.setData(recv_img)
        item.resetTransform()
        item.scale(self._lens[1] / recv_img.shape[0],
                   self._lens[2] / recv_img.shape[1], 1.0)
        item.rotate(120, 1, 1, 1)
        item.translate(self._disp(0, r), 0, 0)

        time_img = render.face_texture(
            render.face_orientation(faces["time"][0], "time"),
            cmap, faces["time"][1])
        item = self._faces["time"]
        item.setData(time_img)
        item.resetTransform()
        item.scale(self._lens[0] / time_img.shape[0],
                   self._lens[1] / time_img.shape[1], 1.0)
        item.translate(0, 0, self._disp_z(t))

    # ------------------------------------------------------------ 相机
    def _fit_distance(self, azimuth: float, elevation: float,
                      margin: float = 1.12) -> float:
        """求一个刚好把整个立方体框进视野的相机距离。

        ``GLViewWidget`` 的 fov 是水平视场角，竖直方向按面板高宽比换算，
        所以取景距离必须跟着面板形状走，否则窄高面板里物体会显得很小。
        这里把 8 个角点逐个投影求下界，取最大值。

        **注意**：尺寸拿不到时（面板还没展开、宽高为 0）算出来的距离是按"方形视口"
        估的，会明显偏远 —— 所以结果会连着尺寸一起记下来，等面板真有了尺寸再由
        :meth:`_refit_when_sized` 补一次取景。
        """
        lx, ly, lz = self._lens
        w, h = max(1, self.width()), max(1, self.height())
        az = math.radians(azimuth)
        el = math.radians(elevation)
        # 相机方向单位向量（由中心指向相机）与视线方向
        eye = np.array([math.cos(el) * math.cos(az),
                        math.cos(el) * math.sin(az),
                        math.sin(el)])
        fwd = -eye
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        n = float(np.linalg.norm(right))
        if n < 1e-9:
            self._fit_view = (azimuth, elevation)
            return max(lx, ly, lz) * 1.6
        right /= n
        up = np.cross(right, fwd)

        tan_h = math.tan(0.5 * math.radians(float(self.opts["fov"])))
        tan_v = tan_h * h / w

        need = 0.0
        for cx in (0.0, lx):
            for cy in (0.0, ly):
                for cz in (0.0, lz):
                    p = np.array([cx - lx / 2.0, cy - ly / 2.0, cz - lz / 2.0])
                    along = float(np.dot(p, fwd))       # 该点沿视线离中心的偏移
                    x = abs(float(np.dot(p, right)))
                    y = abs(float(np.dot(p, up)))
                    need = max(need, x / tan_h - along, y / tan_v - along)
        self._fit_view = (azimuth, elevation)
        return max(1e-6, need * margin)

    def _refit(self) -> None:
        """按记下的视角重算取景距离（只调距离，不动角度）。"""
        if self._vol is None or not self._fit_view:
            return
        w, h = self.width(), self.height()
        if w <= 2 or h <= 2:
            return
        az, el = self._fit_view
        self.opts["distance"] = self._fit_distance(az, el)
        self.update()

    def resizeEvent(self, ev) -> None:               # noqa: N802 （Qt 接口名）
        """自动取景期间跟着面板形状走。

        这块面板在不同排版下的形状差得很远（细高的右列 / 宽扁的通栏），而取景距离
        又必须跟着形状算 —— 所以只要用户还没自己转过/缩放过（``_auto_fit``），
        每次尺寸变化就重新取一次景。载入数据时面板往往还是折叠的（没有尺寸），
        这一步同时把那种"按退化视口算出来的偏远距离"纠正回来。
        """
        super().resizeEvent(ev)
        if self._auto_fit:
            self._refit()

    def wheelEvent(self, ev) -> None:                 # noqa: N802 （Qt 接口名）
        self._auto_fit = False                        # 用户自己缩放过了，别再动取景
        super().wheelEvent(ev)

    def reset_view(self) -> None:
        if self._vol is None:
            return
        lx, ly, lz = self._lens
        az, el = 40.0, 22.0
        self.opts["center"] = QtGui.QVector3D(lx / 2.0, ly / 2.0, lz / 2.0)
        self.opts["azimuth"] = az
        self.opts["elevation"] = el
        self.opts["distance"] = self._fit_distance(az, el)
        self._auto_fit = True
        self.update()

    def focus_face(self, mode: str, animate: bool = True) -> None:
        # 连续点两个面时先掐掉上一轮动画，否则两批动画会互相抢相机。
        # 动画用了 DeleteWhenStopped，跑完 C++ 对象就没了，必须先用 isValid
        # 校验，直接调 stop() 会抛 "Internal C++ object already deleted"。
        for anim in self._anims:
            if isValid(anim):
                anim.stop()
        self._anims = []
        az, el = _FOCUS.get(mode, (40.0, 22.0))
        dist = self._fit_distance(az, el)
        self._auto_fit = True               # 换面就是重新取景，之后继续跟着面板尺寸走
        if not animate:
            self.opts["azimuth"], self.opts["elevation"] = az, el
            self.opts["distance"] = dist
            self.update()
            return
        self._anims = [
            self._run_anim(self._anim, b"azimuth", az, angular=True),
            self._run_anim(self._anim, b"elevation", el, angular=True),
            self._run_anim(self._anim, b"distance", dist, angular=False),
        ]

    def _run_anim(self, obj, prop: bytes, target: float, angular: bool = True,
                  duration: int = 520) -> QtCore.QPropertyAnimation:
        cur = float(obj.property(prop.decode()))
        end = cur + (((target - cur + 180.0) % 360.0) - 180.0) if angular else target
        anim = QtCore.QPropertyAnimation(obj, prop, self)
        anim.setDuration(duration)
        anim.setStartValue(cur)
        anim.setEndValue(end)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        anim.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        return anim

    # ------------------------------------------------------------ 拾取
    def _ray(self, pos: QtCore.QPointF) -> tuple[np.ndarray, np.ndarray] | None:
        """从屏幕坐标反投影出世界坐标射线 (origin, direction)。"""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return None
        ndc_x = 2.0 * pos.x() / w - 1.0
        ndc_y = 1.0 - 2.0 * pos.y() / h

        dist = float(self.opts["distance"])
        near = dist * 0.001
        far = dist * 1000.0
        half_w = near * math.tan(0.5 * math.radians(float(self.opts["fov"])))
        half_h = half_w * h / w

        try:
            mv = self.viewMatrix()
            inv, ok = mv.inverted()
            if not ok:
                return None
            p_near = inv.map(QtGui.QVector3D(ndc_x * half_w, ndc_y * half_h, -near))
            p_far = inv.map(QtGui.QVector3D(ndc_x * half_w * far / near,
                                            ndc_y * half_h * far / near, -far))
        except Exception:
            return None

        origin = np.array([p_near.x(), p_near.y(), p_near.z()], dtype=np.float64)
        tip = np.array([p_far.x(), p_far.y(), p_far.z()], dtype=np.float64)
        direction = tip - origin
        norm = float(np.linalg.norm(direction))
        if norm < 1e-12:
            return None
        return origin, direction / norm

    def pick_face(self, pos: QtCore.QPointF) -> str | None:
        """返回鼠标位置下最靠前的面；无命中返回 None。"""
        if self._vol is None:
            return None
        ray = self._ray(pos)
        if ray is None:
            return None
        origin, direction = ray
        lx, ly, lz = self._lens

        # (模式, 平面法线轴, 平面位置, 面内两个范围) —— 全部用显示坐标
        planes = [
            ("shot", 1, self._disp(1, self._s), (0.0, lx, 0.0, lz)),
            ("recv", 0, self._disp(0, self._r), (0.0, ly, 0.0, lz)),
            ("time", 2, self._disp_z(self._t), (0.0, lx, 0.0, ly)),
        ]
        best: tuple[float, str] | None = None
        for mode, axis, plane_pos, (a0, a1, b0, b1) in planes:
            denom = direction[axis]
            if abs(denom) < 1e-9:
                continue
            hit_t = (plane_pos - origin[axis]) / denom
            if hit_t <= 0.0:
                continue
            point = origin + direction * hit_t
            other = [i for i in range(3) if i != axis]
            if not (min(a0, a1) <= point[other[0]] <= max(a0, a1)):
                continue
            if not (min(b0, b1) <= point[other[1]] <= max(b0, b1)):
                continue
            if best is None or hit_t < best[0]:
                best = (hit_t, mode)
        return best[1] if best else None

    # ------------------------------------------------------------ 鼠标
    def mousePressEvent(self, ev) -> None:
        self._press_pos = ev.position().toPoint()
        self._auto_fit = False             # 用户自己开始转视角了 → 不再自动取景
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        super().mouseReleaseEvent(ev)
        if self._press_pos is None or self._vol is None:
            return
        moved = (ev.position().toPoint() - self._press_pos).manhattanLength()
        self._press_pos = None
        if moved > 4:                      # 拖动是旋转，不当作点击
            return
        mode = self.pick_face(ev.position())
        if mode:
            self.faceClicked.emit(mode)


def create_view3d(parent=None):
    """创建三维视图；OpenGL 不可用时返回 None。"""
    try:
        view = VolumeView3D(parent)
        view.makeCurrent()
        view.doneCurrent()
        return view
    except Exception:
        return None