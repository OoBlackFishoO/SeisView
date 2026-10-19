"""格式转换：把当前体数据导出成矩阵（npy / npz / mat），或写成 SEG-Y / SU。

导出矩阵
--------
统一按内部约定 ``(S, R, T)`` = ``(炮点, 检波器, 时间)`` 写出，而且**只写数据本身**：

* 不写 dt / dx / ds 等元信息（标尺信息会丢，下游要自己知道采样间隔）；
* 缺道位置以 **0** 填充（因此"真 0"和"缺道"在下游无法区分）。

换来的是一个纯矩阵，喂给任何算法都最省事。

写出 SEG-Y / SU
---------------
立方体是个抽象网格，而 SEG-Y 是"每道自带道头"的扁平道列表，所以要**合成一套最小
但正确的道头**：

===================== ========================================
道头字段                写入值
===================== ========================================
FieldRecord           炮号 + 1
TraceNumber           炮内道号 + 1
TRACE_SAMPLE_COUNT    每道采样数
TRACE_SAMPLE_INTERVAL 采样间隔 (µs)
SourceX / GroupX（可选）s·ds / s·ds + r·dx（按坐标标量放大成整数）
offset（可选）          r·dx（取整，按惯例不乘坐标标量）
===================== ========================================

几何自洽（``GroupX - SourceX == offset``），因此任何软件都能正确定位与分选，
读回来也能还原出同样的 dt / dx / ds。

**为什么要写坐标标量**：SEG-Y 的坐标字段是 32 位整数，道距 12.5 m 这种小数一旦直接
取整（12.5 → 13），读回来的道距就变成 13，几何就毁了。所以发现 dx/ds 带小数时，
按 ``SourceGroupScalar = -10^k``（负数表示除）把坐标放大成整数再写，
读者按标量还原即可拿到精确小数。

采样格式固定写 **IEEE float32（格式码 5）**，兼容性最好；老软件只认 IBM 浮点（码 1）
的话需要另做转换，这里不做。

大文件
------
``.npy`` 走"先写头、再 memmap 逐炮填"，全程只有一炮在内存里；
``.npz`` / ``.mat`` 的写入库都需要一整块连续数组，所以先整体拷进内存一次，
超出上限时明确拒绝并建议改用 .npy。

逐剖面导出
----------
矩阵格式还可以**沿某一轴切开、每片写成一个独立文件**（例如 901 个共炮点剖面 →
901 个 ``.mat``）。每片的方向与软件里的剖面窗口一致：**行 = 纵轴、列 = 横轴**。
文件名只有一条规则：``文件名_序号`` + 扩展名，``文件名`` 留空就只用序号；
序号就是该方向的炮号 / 道号 / 时间采样号（不补零）。
"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

# 导出目标：显示名 → 后缀标识
EXPORT_FORMATS = [
    ("NumPy 单文件 (.npy)", "npy"),
    ("NumPy 容器 (.npz)", "npz"),
    ("MATLAB (.mat)", "mat"),
    ("SEG-Y (.sgy)", "sgy"),
    ("Seismic Unix (.su)", "su"),
]
SUFFIX_OF = {"npy": ".npy", "npz": ".npz", "mat": ".mat", "sgy": ".sgy", "su": ".su"}
LABEL_OF = {key: name for name, key in EXPORT_FORMATS}
MATRIX_KEYS = ("npy", "npz", "mat")
SEISMIC_KEYS = ("sgy", "su")
NPZ_ARRAY_KEY = "cube"
MAT_ARRAY_KEY = "cube"

# ------------------------------------------------------------------ 逐剖面
# 切片方向：显示名 → 轴标识。括号里写的是导出矩阵的形状（行 * 列），
# 与软件里的剖面窗口一致，也方便一眼对上"会拿到一张什么样的二维矩阵"。
SLICE_AXES = [
    ("共炮点剖面（时间*偏移距）", "shot"),
    ("共检波点剖面（时间*炮点）", "recv"),
    ("时间切片（炮点*偏移距）", "time"),
]
SLICE_LABEL_OF = {key: name for name, key in SLICE_AXES}
# 序号在文件名里代表什么（给界面写示例用）
SLICE_INDEX_WORD = {"shot": "炮号", "recv": "道号", "time": "时间"}
# 文件名前缀默认留空 —— 留空时文件名就是纯序号
DEFAULT_NAME_PREFIX = ""
# 这些字符不能出现在文件名里（Windows 会直接失败或把路径拆开）
_BAD_NAME_CHARS = set('/\\:*?"<>|')

# 需要整块进内存的格式，超过这个体积就拒绝（避免直接把机器拖死）
_MATERIALIZE_MAX_BYTES = 2_500_000_000

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


class ExportError(RuntimeError):
    """导出过程中的可预期错误（消息直接给用户看）。"""


class _Cancelled(Exception):
    """内部信号：用户取消了导出。"""


def default_name(stem: str, fmt: str) -> str:
    """按源文件名给出默认导出文件名。"""
    return f"{stem}{SUFFIX_OF[fmt]}"


def export(path: str | os.PathLike, cube: np.ndarray, fmt: str, *,
           dt_us: int | None = None, dx: float = 12.5, ds: float = 25.0,
           with_coords: bool = True, progress: Progress | None = None,
           cancel: Cancel | None = None) -> str:
    """把 ``(S, R, T)`` 立方体导出成指定格式，返回写出的路径。

    ``progress(比例, 说明)`` 用于回报进度，``cancel()`` 返回 True 表示用户要中止
    （此时会删掉写了一半的文件）。
    """
    cube = np.asarray(cube)
    if cube.ndim != 3:
        raise ExportError(f"只支持导出三维体数据，当前是 {cube.ndim} 维。")
    if min(cube.shape) <= 0:
        raise ExportError("立方体为空，没有可导出的数据。")
    path = str(path)
    try:
        if fmt in MATRIX_KEYS:
            _export_matrix(path, cube, fmt, progress, cancel)
        elif fmt in SEISMIC_KEYS:
            _write_seismic(path, cube, fmt, dt_us=dt_us or 1000,
                           dx=dx, ds=ds, with_coords=with_coords,
                           progress=progress, cancel=cancel)
        else:
            raise ExportError(f"不支持的导出格式：{fmt}")
    except _Cancelled:
        _remove_quietly(path)
        raise ExportError("已取消导出。") from None
    except ExportError:
        _remove_quietly(path)
        raise
    except MemoryError as exc:
        _remove_quietly(path)
        raise ExportError(
            f"内存不足（立方体约 {cube.nbytes / 1024 ** 3:.1f} GB）。"
            "建议改用 .npy（支持流式写入），或先抽稀数据。") from exc
    except Exception as exc:
        _remove_quietly(path)
        raise ExportError(f"{type(exc).__name__}: {exc}") from exc
    return path


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _tick(cancel: Cancel | None) -> None:
    if cancel is not None and cancel():
        raise _Cancelled


def _native_dtype(arr: np.ndarray) -> np.dtype:
    """统一成"本机字节序"的浮点类型。

    惰性读出的 SEG-Y 是**大端** ``>f4``，直接写 .npy 会得到一个字节序古怪的文件，
    下游读起来容易踩坑，所以一律换成 ``=f4``。
    """
    dtype = np.dtype(arr.dtype)
    if dtype.kind not in "fiu":
        dtype = np.dtype(np.float32)
    return dtype.newbyteorder("=")


# ====================================================================== 矩阵
def _export_matrix(path: str, cube: np.ndarray, fmt: str,
                   progress: Progress | None, cancel: Cancel | None) -> None:
    if fmt == "npy":
        _export_npy(path, cube, progress, cancel)
        return
    # npz / mat 的写入库都要一整块连续数组
    dtype = _native_dtype(cube)
    # 注意用 cube.size（Python int）而不是 np.prod(shape)：Windows 上 numpy 默认
    # 整型是 int32，2.4e9 这种体积会在 np.prod 里直接溢出成负数，守卫就失效了。
    need = int(cube.size) * dtype.itemsize
    if need > _MATERIALIZE_MAX_BYTES:
        raise ExportError(
            f"该格式需要先把整个立方体放进内存（约 {need / 1024 ** 3:.1f} GB），"
            "超出上限。\n建议导出 .npy（支持流式写入，内存只占一炮）。")
    arr = _materialize(cube, dtype, progress, cancel)
    _tick(cancel)
    if fmt == "npz":
        np.savez(path, **{NPZ_ARRAY_KEY: arr})
    else:
        import scipy.io
        scipy.io.savemat(path, {MAT_ARRAY_KEY: arr})
    if progress is not None:
        progress(1.0, "完成")


def _materialize(cube: np.ndarray, dtype: np.dtype,
                 progress: Progress | None, cancel: Cancel | None) -> np.ndarray:
    """逐炮拷进一块连续内存。比 ``ascontiguousarray`` 多一个进度与取消。"""
    n_shot = cube.shape[0]
    out = np.empty(cube.shape, dtype=dtype)
    for s in range(n_shot):
        _tick(cancel)
        out[s] = cube[s]
        if progress is not None:
            progress((s + 1) / n_shot * 0.9, f"整理数据：第 {s + 1}/{n_shot} 炮")
    return out


def _export_npy(path: str, cube: np.ndarray,
                progress: Progress | None, cancel: Cancel | None) -> None:
    """.npy 流式写出：先只写文件头，再 memmap 逐炮填。

    这样 3 GB 的源数据导出时内存里也只有一炮（几千道 × 上百采样），
    不必先整体拷贝一份。
    """
    import numpy.lib.format as npformat

    dtype = _native_dtype(cube)
    shape = tuple(int(v) for v in cube.shape)
    with open(path, "wb") as fp:
        npformat.write_array_header_1_0(fp, {
            "descr": npformat.dtype_to_descr(dtype),
            "fortran_order": False,
            "shape": shape,
        })
        offset = fp.tell()          # 文件头按 64 字节对齐，正好是数据起点
    out = np.memmap(path, dtype=dtype, mode="r+", offset=offset, shape=shape)
    try:
        for s in range(shape[0]):
            _tick(cancel)
            out[s] = cube[s]
            if progress is not None:
                progress((s + 1) / shape[0], f"写入第 {s + 1}/{shape[0]} 炮")
        out.flush()
    finally:
        del out                     # 关掉映射，之后才能安全地读回校验


# ================================================================== 逐剖面导出
def slice_count(cube: np.ndarray, mode: str) -> int:
    """某一方向上能切出多少片。"""
    axis = {"shot": 0, "recv": 1, "time": 2}.get(mode)
    if axis is None:
        raise ExportError(f"未知的切片方向：{mode}")
    return int(cube.shape[axis])


def slice_shape(cube: np.ndarray, mode: str) -> tuple[int, int]:
    """单片矩阵的形状（行, 列），不真的切出数据。"""
    n_shot, n_r, n_t = (int(v) for v in cube.shape)
    if mode == "shot":
        return (n_t, n_r)          # 时间 × 检波器，即惯例的 (nt, nr) 炮集
    if mode == "recv":
        return (n_t, n_shot)
    return (n_shot, n_r)


def take_slice(cube: np.ndarray, mode: str, index: int) -> np.ndarray:
    """取第 ``index`` 片，方向与软件里的剖面窗口**一致**（行 = 纵轴、列 = 横轴）。

    共炮点 → ``(时间, 检波器)``：正好是地震惯例的 ``(nt, nr)`` 炮集；
    共检波点 → ``(时间, 炮点)``；时间切片 → ``(炮点, 检波器)``。
    """
    if mode == "shot":
        return np.ascontiguousarray(cube[index].T)
    if mode == "recv":
        return np.ascontiguousarray(cube[:, index, :].T)
    if mode == "time":
        return np.ascontiguousarray(cube[:, :, index])
    raise ExportError(f"未知的切片方向：{mode}")


def check_name(name: str) -> None:
    """校验文件名前缀：允许留空，不能有路径分隔符之类会让写文件失败的字符。"""
    bad = sorted({c for c in str(name) if c in _BAD_NAME_CHARS})
    if bad:
        raise ExportError("文件名里不能出现这些字符：" + " ".join(bad))


def slice_name(name: str, index: int, suffix: str) -> str:
    """单片文件名 = ``文件名_序号`` + 扩展名；文件名留空就只用序号。

    序号取该方向的下标，也就是炮号 / 道号 / 时间采样号；不补零，
    所以 901 片就是 ``0.mat`` … ``900.mat``。
    """
    stem = str(name).strip()
    return f"{stem}_{index}{suffix}" if stem else f"{index}{suffix}"


def _write_matrix_file(path: str, arr: np.ndarray, fmt: str) -> None:
    """把单片矩阵落盘（单片体积有限，直接整块写）。"""
    if fmt == "npy":
        np.save(path, arr, allow_pickle=False)
    elif fmt == "npz":
        np.savez(path, **{NPZ_ARRAY_KEY: arr})
    else:
        import scipy.io
        scipy.io.savemat(path, {MAT_ARRAY_KEY: arr})


def slice_range(cube: np.ndarray, mode: str,
                start: int | None = None, stop: int | None = None) -> tuple[int, int]:
    """把用户给的片层范围夹到合法区间，返回闭区间 ``(lo, hi)``。

    ``start`` / ``stop`` 为 None 表示"从第一片 / 到最后一片"；两值都是闭区间端点的下标。
    """
    total = slice_count(cube, mode)
    lo = 0 if start is None else int(start)
    hi = total - 1 if stop is None else int(stop)
    return int(max(0, min(lo, total - 1))), int(max(0, min(hi, total - 1)))


def export_slices(folder: str | os.PathLike, cube: np.ndarray, fmt: str, *,
                  mode: str = "shot", name: str = DEFAULT_NAME_PREFIX,
                  start: int | None = None, stop: int | None = None,
                  progress: Progress | None = None,
                  cancel: Cancel | None = None) -> list[str]:
    """逐剖面导出：沿选定轴切片，每片写成 ``folder`` 下一个独立文件。

    ``name`` 是文件名前缀（可留空，留空时文件名就是纯序号）。
    ``start`` / ``stop`` 指定**片层范围**（闭区间，下标从 0 起）：只导出这一段的片，
    省略表示全范围。返回写出的路径列表。中途取消时**已经写完的文件保留**
    （它们都是完整可用的），只删掉正在写的那一个。
    """
    cube = np.asarray(cube)
    if cube.ndim != 3:
        raise ExportError(f"只支持三维体数据，当前是 {cube.ndim} 维。")
    if fmt not in MATRIX_KEYS:
        raise ExportError("逐剖面导出只支持矩阵格式（.npy / .npz / .mat）。")
    folder = str(folder)
    if not os.path.isdir(folder):
        raise ExportError(f"目标文件夹不存在：{folder}")
    check_name(name)

    total = slice_count(cube, mode)
    if total <= 0:
        raise ExportError("这个方向上没有可导出的剖面。")
    lo, hi = slice_range(cube, mode, start, stop)
    if lo > hi:
        raise ExportError(f"片层范围不合法：{lo} ~ {hi}（共 {total} 片，下标 0 ~ {total - 1}）。")
    count = hi - lo + 1

    dtype = _native_dtype(cube)
    per_file = int(cube.size // total) * dtype.itemsize
    if per_file > _MATERIALIZE_MAX_BYTES:
        raise ExportError(
            f"单片就约 {per_file / 1024 ** 3:.1f} GB，超出上限（{size_text(_MATERIALIZE_MAX_BYTES)}）。")
    suffix = SUFFIX_OF[fmt]

    made: list[str] = []
    try:
        for n, i in enumerate(range(lo, hi + 1)):
            _tick(cancel)
            fname = slice_name(name, i, suffix)
            path = os.path.join(folder, fname)
            try:
                arr = np.ascontiguousarray(take_slice(cube, mode, i), dtype=dtype)
                _write_matrix_file(path, arr, fmt)
            except _Cancelled:
                _remove_quietly(path)
                raise
            except ExportError:
                _remove_quietly(path)
                raise
            except MemoryError as exc:
                _remove_quietly(path)
                raise ExportError(f"内存不足（单片约 {per_file / 1024 ** 2:.0f} MB）。") from exc
            except Exception as exc:
                _remove_quietly(path)
                raise ExportError(f"写「{fname}」失败：{type(exc).__name__}: {exc}") from exc
            made.append(path)
            if progress is not None:
                progress((n + 1) / count, f"第 {n + 1}/{count} 片（{word_of(mode)}{i}） → {fname}")
    except _Cancelled:
        raise ExportError(
            f"已取消导出：已经写出 {len(made)} 个文件，都在 {folder}。") from None
    if progress is not None:
        progress(1.0, "完成")
    return made


def word_of(mode: str) -> str:
    """片序号在文件名/提示里代表什么（炮号 / 道号 / 时间采样号）。"""
    return SLICE_INDEX_WORD.get(mode, "序号")


def describe_slices(cube: np.ndarray, mode: str, fmt: str,
                    start: int | None = None, stop: int | None = None) -> str:
    """逐剖面导出的规模说明（含片层范围）。"""
    total = slice_count(cube, mode)
    lo, hi = slice_range(cube, mode, start, stop)
    count = max(0, hi - lo + 1)
    rows, cols = slice_shape(cube, mode)
    nbytes = rows * cols * 4                    # 统一按 float32 估
    scope = (f"全部 {total} 片" if (lo == 0 and hi == total - 1)
             else f"第 {lo} ~ {hi} 片（{count} 片）")
    return (f"沿「{SLICE_LABEL_OF.get(mode, mode)}」共 {total} 片，本次导出 {scope}，"
            f"每片 {rows} × {cols}（约 {size_text(nbytes)}）\n"
            f"将写成 {count} 个 {SUFFIX_OF[fmt]} 文件，总共约 {size_text(nbytes * count)}")


# ====================================================================== SEG-Y
# 道头里的坐标是 32 位整数，超出范围就截断（宁可少点几何，也不能写出坏文件）
_INT32_MAX = 2_147_483_647


def _clamp32(v: float) -> int:
    return int(max(-_INT32_MAX, min(_INT32_MAX, round(v))))


def _coord_scalar(dx: float, ds: float, max_k: int = 4) -> int:
    """求一个 10 的幂，使 dx / ds（及其整数倍）都能正好变成整数。

    dx = 12.5 时返回 10（125 是整数），dx = 12.25 时返回 100。全都不是有限小数时
    取上限（``10**max_k``），此时坐标会有极小的取整误差 —— 比直接取整好得多。
    """
    for k in range(max_k + 1):
        scale = float(10 ** k)
        if all(abs(round(v * scale) - v * scale) < 1e-6 for v in (dx, ds) if v):
            return int(scale)
    return 10 ** max_k


def _text_header(cube: np.ndarray, dt_us: int, dx: float, ds: float,
                 with_coords: bool, scalar: int) -> str:
    """3200 字节文本头：让人打开文件就知道这份数据是怎么来的。"""
    n_shot, n_r, n_t = cube.shape
    lines = [
        "C 1 SEISVIEW EXPORT",
        f"C 2 SHOTS {n_shot}   TRACES/SHOT {n_r}   SAMPLES/TRACE {n_t}",
        f"C 3 SAMPLE INTERVAL {dt_us} US   RECORD LENGTH {n_t * dt_us / 1e6:.3f} S",
        "C 4 FIELD RECORD = SHOT NO. + 1   TRACE NO. = TRACE-IN-SHOT + 1",
        "C 5 DATA IS IEEE FLOAT32 (SEG-Y FORMAT CODE 5)",
    ]
    if with_coords:
        lines += [
            "C 6 GEOMETRY: SOURCE X = SHOT * DS   GROUP X = SOURCE X + TRACE * DX",
            f"C 7 DX (GROUP SPACING) = {dx:g}   DS (SHOT SPACING) = {ds:g}",
            f"C 8 SOURCEGROUPSCALAR = -{scalar} APPLIES TO SOURCE X / GROUP X ONLY",
            "C 9 OFFSET = TRACE * DX (COORDINATE UNITS, NOT SCALED)",
        ]
    lines.append("C END")
    return "\n".join(lines)


def _write_seismic(path: str, cube: np.ndarray, fmt: str, *,
                   dt_us: int, dx: float, ds: float, with_coords: bool,
                   progress: Progress | None, cancel: Cancel | None) -> None:
    """合成道头并写成 SEG-Y（大端，带 3600 字节文件头）或 SU（小端，无文件头）。"""
    su = fmt == "su"
    n_shot, n_r, n_t = cube.shape
    dt_us = int(dt_us)
    if dt_us > 65535:
        raise ExportError(f"采样间隔 {dt_us} µs 超出道头 16 位上限（65535），无法写入。")
    if n_t > 65535:
        raise ExportError(f"每道 {n_t} 个采样超出道头 16 位上限（65535），无法写入。")
    # 坐标标量：dx = 12.5 这类小数必须放大成整数，否则读回来变成 12.5→13
    scale = _coord_scalar(dx, ds) if with_coords else 1
    scalar_field = -scale if scale > 1 else 0        # 负数表示"除"，0 等同"×1"

    if su:
        _write_su(path, cube, dt_us=dt_us, dx=dx, ds=ds, with_coords=with_coords,
                  scale=scale, scalar_field=scalar_field,
                  progress=progress, cancel=cancel)
        return

    try:
        import segyio
    except ImportError as exc:                              # pragma: no cover
        raise ExportError("写出 SEG-Y 需要 segyio 库，请先执行：pip install segyio") from exc

    spec = segyio.spec()
    spec.format = 5                                          # IEEE float32
    spec.samples = np.arange(n_t, dtype=np.float32)
    spec.tracecount = int(n_shot) * int(n_r)
    spec.endian = "big"                                      # SEG-Y 标准就是大端

    TF = segyio.TraceField
    cursor = 0
    with segyio.create(path, spec) as f:
        try:
            f.bin[segyio.BinField.Interval] = dt_us
            f.bin[segyio.BinField.Samples] = n_t
            f.bin[segyio.BinField.Format] = 5
            f.text[0] = _text_header(cube, dt_us, dx, ds, with_coords, scale)
        except Exception:                                    # pragma: no cover
            pass                                             # 文件头写不进去也不影响数据
        for s in range(int(n_shot)):
            _tick(cancel)
            shot = np.ascontiguousarray(cube[s], dtype=np.float32)
            sx = _clamp32(s * ds * scale)
            for r in range(int(n_r)):
                hdr = {
                    TF.TRACE_SEQUENCE_FILE: cursor + 1,
                    TF.FieldRecord: s + 1,
                    TF.TraceNumber: r + 1,
                    TF.TRACE_SAMPLE_COUNT: n_t,
                    TF.TRACE_SAMPLE_INTERVAL: dt_us,
                }
                if with_coords:
                    hdr[TF.SourceGroupScalar] = scalar_field
                    hdr[TF.SourceX] = sx
                    hdr[TF.GroupX] = _clamp32((s * ds + r * dx) * scale)
                    hdr[TF.offset] = _clamp32(r * dx)     # 惯例：offset 不乘坐标标量
                f.header[cursor] = hdr
                cursor += 1
            # 整炮一次性写数据比逐道写快得多
            start = s * int(n_r)
            f.trace.raw[start:start + int(n_r)] = shot
            if progress is not None:
                progress((s + 1) / int(n_shot),
                         f"写出第 {s + 1}/{int(n_shot)} 炮（{cursor} 道）")
    if progress is not None:
        progress(1.0, "完成")


# ---------------------------------------------------------------- SU 手写
# segyio 只提供 segyio.su.open，没有 create，所以 SU 只能自己拼：
# 每条记录 = 240 字节道头 + 样点，全小端（SU 惯例是本机序）。
_SU_HEADER_BYTES = 240
# 字段名 → (1 起的字节位置, numpy 类型)。宽度按 SEG-Y 标准：
# 采样数/采样间隔是 16 位，坐标与道号是 32 位。
_SU_FIELDS = {
    "TRACE_SEQUENCE_FILE": (5, "<i4"),
    "FieldRecord": (9, "<i4"),
    "TraceNumber": (13, "<i4"),
    "offset": (37, "<i4"),
    "SourceGroupScalar": (71, "<i2"),
    "SourceX": (73, "<i4"),
    "GroupX": (81, "<i4"),
    "TRACE_SAMPLE_COUNT": (115, "<u2"),
    "TRACE_SAMPLE_INTERVAL": (117, "<u2"),
}
_SU_HEADER_DTYPE = np.dtype({
    "names": list(_SU_FIELDS),
    "formats": [np.dtype(t) for _p, t in _SU_FIELDS.values()],
    "offsets": [p - 1 for p, _t in _SU_FIELDS.values()],
    "itemsize": _SU_HEADER_BYTES,
})


def _write_su(path: str, cube: np.ndarray, *, dt_us: int, dx: float, ds: float,
              with_coords: bool, scale: int, scalar_field: int,
              progress: Progress | None, cancel: Cancel | None) -> None:
    n_shot, n_r, n_t = (int(v) for v in cube.shape)
    idx = np.arange(n_r, dtype=np.int64)
    hdr = np.zeros(n_r, dtype=_SU_HEADER_DTYPE)
    hdr["TraceNumber"] = idx + 1
    hdr["TRACE_SAMPLE_COUNT"] = n_t
    hdr["TRACE_SAMPLE_INTERVAL"] = dt_us
    if with_coords:
        hdr["SourceGroupScalar"] = scalar_field
        hdr["offset"] = np.clip(np.round(idx * dx), -_INT32_MAX, _INT32_MAX).astype("<i4")
        hdr["GroupX"] = np.clip(np.round(idx * dx * scale),
                                -_INT32_MAX, _INT32_MAX).astype("<i4")

    with open(path, "wb") as fp:
        for s in range(n_shot):
            _tick(cancel)
            hdr["FieldRecord"] = s + 1
            hdr["TRACE_SEQUENCE_FILE"] = s * n_r + idx + 1
            if with_coords:
                sx = _clamp32(s * ds * scale)
                hdr["SourceX"] = sx
                hdr["GroupX"] = np.clip(np.round((s * ds + idx * dx) * scale),
                                        -_INT32_MAX, _INT32_MAX).astype("<i4")
            shot = np.ascontiguousarray(cube[s], dtype="<f4")
            # 把 240 字节道头与样点交错排成"每道一条记录"，整炮一次写出
            rec = np.empty((n_r, _SU_HEADER_BYTES + n_t * 4), dtype=np.uint8)
            rec[:, :_SU_HEADER_BYTES] = hdr.view(np.uint8).reshape(n_r, _SU_HEADER_BYTES)
            rec[:, _SU_HEADER_BYTES:] = shot.view(np.uint8).reshape(n_r, n_t * 4)
            fp.write(rec)
            if progress is not None:
                progress((s + 1) / n_shot,
                         f"写出第 {s + 1}/{n_shot} 炮（{(s + 1) * n_r} 道）")
    if progress is not None:
        progress(1.0, "完成")


def size_text(nbytes: int) -> str:
    """人读的体积：小文件别显示成「约 0.00 GB」。"""
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.2f} GB"
    return f"{nbytes / 1024 ** 2:.1f} MB"


def describe(cube: np.ndarray, fmt: str) -> str:
    """导出前的规模说明，用于在对话框里提示大致要写多少数据。"""
    nbytes = int(cube.size) * 4          # 统一按 float32 估，避免 int32 溢出
    size = size_text(nbytes)
    text = f"{cube.shape[0]} 炮 × {cube.shape[1]} 道 × {cube.shape[2]} 采样"
    if fmt in ("mat", "npz"):
        # 这两个格式的写入库都要一整块连续数组，数据大到一定程度会失败
        # （真失败时会明确拒绝并建议改用 .npy）
        return f"{text}\n约 {size}（需要整块进内存，数据过大时可能失败）"
    if fmt == "npy":
        return f"{text}\n约 {size}"
    return f"{text}\n共 {cube.shape[0] * cube.shape[1]} 道，float32，约 {size}"
