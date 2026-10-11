"""文件读取层：.npy / .npz / .mat / .sgy / .segy / .su → SeisVolume。

设计要点
--------
1. **多键适配**：一个文件里可能有多个变量（.npz 的多个成员、.mat 的多个矩阵），
   先枚举出清单交用户选择，而不是自作主张取第一个。
2. **按需读取**：
   - ``.npy`` 用 ``mmap_mode='r'``，逐页惰性，最优；
   - ``.npz`` 只解压被选中的那一个成员，其余成员不碰；
   - ``.mat``（v4/v5/v7）无法按成员惰性读，必须整文件载入 —— 这一点会在
     变量清单里明确标注，并做一次缓存避免重复载入。
3. **轴序人工确认**：地震数据的轴序在全世界都不统一（MATLAB 常存 (T,R)、
   Python 常存 (R,T)），自动猜测必然时不时出错，而画错的图极难被发现。
   因此首次打开某个文件时要求确认一次，之后按文件指纹记住。
   SEG-Y/SU 例外：立方体是按道头现搭的，轴序由构造决定，无需确认。

不支持 .mat v7.3（HDF5）—— 会被明确拒绝并提示。

SEG-Y / SU
----------
两者共用同一套 240 字节道头，区别只在 SU 没有 3600 字节的文件头，
且 SU 的采样数与采样间隔只存在于道头里（没有二进制头可查），
所以 SU 走 ``segyio.su.open``，且必须按**本机字节序**读（x86 上是小端）。

从道头到立方体的映射是**固定**的：``FieldRecord → 炮点 S``、
``炮内 TraceNumber 顺序 → 检波器 R``、样点 → 时间 T。
这不是"空间立方体"：炮点和检波点不在同一个位置时，R 轴是炮内道序而不是
物理检波点坐标，第三维切片也是 (炮号, 道号) 索引平面而不是平面图 ——
这一点会在载入后的摘要里写明。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .volume import LABEL_TO_ROLE, ROLE_LABELS, ROLE_RECV, ROLE_SHOT, ROLE_TIME, SeisVolume

SUPPORTED_SUFFIXES = (".npy", ".npz", ".mat", ".sgy", ".segy", ".su")
SEISMIC_SUFFIXES = (".sgy", ".segy", ".su")

_NPY_MAGIC = b"\x93NUMPY"
_MAT_MAGIC = b"MATLAB 5.0 MAT-file"


# ====================================================================== 变量清单
@dataclass
class VariableInfo:
    """一个待选变量的元信息（尽量在不读数据的前提下拿到）。"""

    key: str
    shape: tuple[int, ...]
    dtype: str
    nbytes: int
    note: str = ""
    # 已知的轴角色。非 None 表示进不去轴序确认框（SEG-Y 的立方体是按道头搭的）
    roles: tuple[str, ...] | None = None

    @property
    def ndim(self) -> int:
        return len(self.shape)

    @property
    def size_text(self) -> str:
        n = self.nbytes
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
            n /= 1024.0
        return f"{n:.1f} GB"


class LoadError(RuntimeError):
    """读取失败（含不支持格式），消息面向用户，可直接显示。"""


def _npy_header_meta(fp) -> tuple[str, tuple[int, ...], int]:
    """只读 .npy 文件头，拿到 dtype / shape / 数据区偏移，不碰数据。"""
    magic = fp.read(6)
    if magic[:6] != _NPY_MAGIC:
        raise LoadError("不是合法的 .npy 文件头")
    major = fp.read(1)[0]
    fp.read(1)  # minor
    if major == 1:
        hlen = int.from_bytes(fp.read(2), "little")
    else:
        hlen = int.from_bytes(fp.read(4), "little")
    raw = fp.read(hlen).decode("latin1")
    try:
        hdr = ast.literal_eval(raw.strip())
    except (ValueError, SyntaxError) as exc:  # pragma: no cover - 损坏文件
        raise LoadError(f".npy 头解析失败：{exc}") from exc
    descr = str(hdr["descr"])
    shape = tuple(int(v) for v in hdr["shape"])
    offset = 6 + 2 + (2 if major == 1 else 4) + hlen
    return descr, shape, offset


def _itemsize_of(descr: str) -> int:
    try:
        return np.dtype(descr).itemsize
    except TypeError:
        return 0


def list_variables(path: str | os.PathLike) -> list[VariableInfo]:
    """枚举文件中所有可用的数值变量，尽量不读数据。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".npy":
        return _list_npy(p)
    if suffix == ".npz":
        return _list_npz(p)
    if suffix == ".mat":
        return _list_mat(p)
    if suffix in SEISMIC_SUFFIXES:
        return _list_seismic(p)
    raise LoadError(f"不支持的扩展名：{suffix}（仅支持 .npy / .npz / .mat / .sgy / .segy / .su）")


def _list_npy(p: Path) -> list[VariableInfo]:
    with open(p, "rb") as fp:
        descr, shape, _ = _npy_header_meta(fp)
    if not _is_numeric_descr(descr):
        raise LoadError(f"{p.name} 的 dtype 不是数值类型（{descr}），无法作为体数据展示")
    nbytes = _itemsize_of(descr) * int(np.prod(shape, dtype=np.int64)) if shape else 0
    return [VariableInfo(key=p.stem, shape=shape, dtype=descr, nbytes=int(nbytes),
                         note="惰性")]


def _list_npz(p: Path) -> list[VariableInfo]:
    out: list[VariableInfo] = []
    with zipfile.ZipFile(p) as zf:
        for name in zf.namelist():
            if not name.endswith(".npy"):
                continue
            key = name[:-4]
            with zf.open(name) as fp:
                try:
                    descr, shape, _ = _npy_header_meta(fp)
                except LoadError:
                    continue
            if not _is_numeric_descr(descr):
                continue
            nbytes = _itemsize_of(descr) * int(np.prod(shape, dtype=np.int64)) if shape else 0
            out.append(VariableInfo(key=key, shape=shape, dtype=descr, nbytes=int(nbytes),
                                    note="按需"))
    if not out:
        raise LoadError(f"{p.name} 中没有数值型 .npy 成员")
    return out


_mat_cache: dict[str, dict] = {}


def _list_mat(p: Path) -> list[VariableInfo]:
    with open(p, "rb") as fp:
        head = fp.read(128)
    if not head.startswith(_MAT_MAGIC):
        raise LoadError(f"{p.name} 不是 MAT v4/v5 文件（可能是 v7.3 / HDF5，本工具暂不支持）")

    data = _load_mat_cached(str(p))  # 整文件载入（MAT 无法按成员惰性读）
    out: list[VariableInfo] = []
    for key, val in data.items():
        if not isinstance(val, np.ndarray):
            continue
        if not np.issubdtype(val.dtype, np.number):
            continue
        out.append(
            VariableInfo(key=key, shape=tuple(int(v) for v in val.shape),
                         dtype=str(val.dtype), nbytes=int(val.nbytes),
                         note="整载" if len(data) > 1 else "")
        )
    if not out:
        raise LoadError(f"{p.name} 中没有数值型矩阵变量")
    return out


def _load_mat_cached(path: str) -> dict:
    """载入 .mat 并缓存（同一路径只读一次）。"""
    hit = _mat_cache.get(path)
    if hit is not None:
        return hit
    from scipy.io import loadmat

    try:
        raw = loadmat(path, squeeze_me=True, struct_as_record=False)
    except NotImplementedError as exc:
        raise LoadError("这是 MAT v7.3（HDF5）文件，本工具暂不支持，"
                        "请另存为 v7 或导出为 .npz") from exc
    data = {k: v for k, v in raw.items() if not k.startswith("__")}
    _mat_cache[path] = data
    return data


def _is_numeric_descr(descr: str) -> bool:
    try:
        dt = np.dtype(descr)
    except TypeError:
        return False
    return np.issubdtype(dt, np.number)


# ====================================================================== SEG-Y / SU
# 从道头搭一个 (炮, 道, 时间) 立方体。默认按 FieldRecord 分炮、炮内按
# TraceNumber 顺序排道；顺序由文件自身决定，不做空间重排，保证可复现。
SEISMIC_KEY = "体数据（炮 × 道 × 时间）"
# 立方体超过这个体积就拒绝，免得直接 OOM
_MAX_CUBE_BYTES = 6 * 1024 ** 3
_seismic_cache: dict[str, dict] = {}
_seismic_endian: dict[str, str] = {}

# 每读一个道头字段要扫一遍整个文件（按页粒度），所以只读真正必需的两个：
# FieldRecord 用来分炮、TraceNumber 用来排道。其余字段只从开头几百道取。
_HEADER_SAMPLE = 512
_SEGY_HEADER_BYTES = 3600          # 文本头 3200 + 二进制头 400
_TRACE_HEADER_BYTES = 240


def _import_segyio():
    try:
        import segyio
    except ImportError as exc:                       # pragma: no cover
        raise LoadError("读取 SEG-Y/SU 需要 segyio 库，请先执行：pip install segyio") from exc
    return segyio


def _open_seismic(p: Path):
    """打开 SEG-Y / SU。SU 没有二进制头，必须按本机字节序读，所以端序要试。"""
    segyio = _import_segyio()
    if p.suffix.lower() == ".su":
        last = None
        for endian in ("little", "big"):             # SU 惯例是本机序（x86 = 小端）
            try:
                f = segyio.su.open(p, "r", ignore_geometry=True, strict=False,
                                   endian=endian)
            except Exception as exc:                 # pragma: no cover
                last = exc
                continue
            if f.tracecount > 0 and len(f.samples) > 0:
                _seismic_endian[str(p)] = "<" if endian == "little" else ">"
                return f
            f.close()
        raise LoadError(f"打不开 SU 文件 {p.name}：无法从道头确定每道采样数"
                        + (f"（{last}）" if last else ""))
    try:
        f = segyio.open(p, "r", ignore_geometry=True, strict=False)
    except Exception as exc:
        raise LoadError(f"打不开 SEG-Y 文件 {p.name}：{exc}") from exc
    _seismic_endian[str(p)] = ">"                 # SEG-Y 标准就是大端
    return f


def _scaled_coord(vals, scalar) -> np.ndarray:
    """SEG-Y 坐标标量：正数乘、负数除、0 视为 1。"""
    v = np.asarray(vals, dtype=np.float64)
    s = np.asarray(scalar, dtype=np.float64)
    s = np.where(s == 0, 1.0, s)
    return np.where(s > 0, v * s, v / np.abs(s))


def _median_step(values: np.ndarray) -> float:
    if values.size < 2:
        return 0.0
    d = np.abs(np.diff(values.astype(np.float64)))
    d = d[np.isfinite(d) & (d > 0)]
    return float(np.median(d)) if d.size else 0.0


def _scan_seismic(p: Path) -> dict:
    """扫一遍道头，建立"炮 → 道"的索引。结果按路径缓存，载入时不再重扫。"""
    hit = _seismic_cache.get(str(p))
    if hit is not None:
        return hit

    segyio = _import_segyio()
    TF = segyio.TraceField
    with _open_seismic(p) as f:
        n_traces = int(f.tracecount)
        ns = int(len(f.samples))
        if n_traces <= 0 or ns <= 0:
            raise LoadError(f"{p.name} 里没有可用的道（道数 {n_traces}、每道采样 {ns}）")

        # 只全扫两个必需字段：FieldRecord 用来分炮、TraceNumber 用来排道。
        # 每读一个字段 ≈ 把整个文件按页扫一遍，所以不能再多读了。
        field = np.asarray(f.attributes(TF.FieldRecord)[:])
        tracl = np.asarray(f.attributes(TF.TraceNumber)[:]).astype(np.int64)

        # 其余道头字段只从开头若干道取，够用来估道距/炮距和报告偏移距范围
        n_probe = int(min(_HEADER_SAMPLE, n_traces))
        hdrs = [f.header[i] for i in range(n_probe)]
        probe_sc = np.array([h[TF.SourceGroupScalar] for h in hdrs], dtype=np.int64)
        probe_off = np.array([h[TF.offset] for h in hdrs], dtype=np.float64)
        sx = _scaled_coord([h[TF.SourceX] for h in hdrs], probe_sc)
        gx = _scaled_coord([h[TF.GroupX] for h in hdrs], probe_sc)

        # 采样格式与采样间隔：优先二进制头（Rev1 更可靠），取不到再退回道头
        fmt_code = 5                     # SU 没有二进制头；SU 数据就是本机 float32
        try:
            fmt_code = int(f.bin[segyio.BinField.Format])
        except Exception:
            fmt_code = 5
        dt_us = 0
        try:
            dt_us = int(f.bin[segyio.BinField.Interval])
        except Exception:
            dt_us = 0
        if dt_us <= 0:
            dt_us = int(hdrs[0][TF.TRACE_SAMPLE_INTERVAL]) if hdrs else 0
        dt = (dt_us / 1_000_000.0) if dt_us > 0 else 0.001

    # 分炮：FieldRecord 升序；炮内按 TraceNumber 升序
    shots, inv = np.unique(field, return_inverse=True)
    order = np.lexsort((tracl, inv))
    sorted_inv = inv[order]
    starts = np.searchsorted(sorted_inv, np.arange(shots.size), side="left")
    stops = np.searchsorted(sorted_inv, np.arange(shots.size), side="right")
    counts = stops - starts

    # 定位方式：若各炮的 TraceNumber 最小值一致（通常都是 1），说明是"炮内道号"，
    # 就按道号定位 —— 缺道时该位置留空，后面的道不会被顶上来（否则整炮错位）。
    # 若各炮起始号不同（可能是全文件连续编号），退回"按顺序紧密排列"。
    bases = np.array([int(tracl[order[starts[k]:stops[k]]].min())
                      for k in range(int(shots.size))], dtype=np.int64)
    by_tracl = bases.size > 0 and bool(np.all(bases == bases[0]))
    base = int(bases[0]) if by_tracl else 0

    # 每炮：文件里的道索引 + 目标行号；两边都连续就走整块读，否则逐道读
    blocks: list[tuple[str, object]] = []
    holes = 0
    short = 0
    n_r = 0
    max_count = int(counts.max()) if counts.size else 0
    for k in range(int(shots.size)):
        idx = order[starts[k]:stops[k]].astype(np.int64)
        r = (tracl[idx] - base).astype(np.int64) if by_tracl \
            else np.arange(idx.size, dtype=np.int64)
        if idx.size < max_count:
            short += 1
        if r.size and (r[-1] - r[0] + 1) != r.size:
            holes += 1
        n_r = max(n_r, int(r[-1]) + 1 if r.size else 0)
        both_contig = (idx.size > 0
                       and (idx[-1] - idx[0] + 1) == idx.size
                       and (r[-1] - r[0] + 1) == r.size)
        if both_contig:
            blocks.append(("range", (int(idx[0]), int(idx[-1]) + 1, int(r[0]))))
        else:
            blocks.append(("index", (idx, r)))

    # 道距 / 炮距：用开头若干道的道头坐标估
    dx = _median_step(gx) if gx.size > 1 else 0.0
    if dx <= 0:
        dx = _median_step(probe_off)
    # sx 在同一炮内不变、跨炮才跳，所以取"非零差值"的中位数
    jumps = np.abs(np.diff(sx))
    jumps = jumps[jumps > 0]
    ds = float(np.median(jumps)) if jumps.size else 0.0
    # 道头单位千奇百怪，超出合理范围就当成"没有物理标尺"，退回序号轴
    dx_ok = 0.05 <= dx <= 5000.0
    ds_ok = 0.05 <= ds <= 5000.0
    dx = dx if dx_ok else 1.0
    ds = ds if ds_ok else 1.0

    # 惰性视图的适用条件：各炮道数一致、炮块在文件里连续且按序排列，
    # 样点又是能直接映射到磁盘的定长格式（IEEE float / 定长整型）。
    # IBM 浮点必须做转换，所以只能整块读。
    regular = bool(blocks) and all(
        kind == "range" and tuple(payload) == (k * n_r, (k + 1) * n_r, 0)
        for k, (kind, payload) in enumerate(blocks))
    fmt_bytes = {1: 4, 2: 4, 3: 2, 5: 4, 6: 8, 8: 1}.get(fmt_code, 4)
    fmt_code_map = {5: "f4", 2: "i4", 3: "i2", 8: "i1"}
    trace_bytes = _TRACE_HEADER_BYTES + fmt_bytes * ns
    head_bytes = 0 if p.suffix.lower() == ".su" else _SEGY_HEADER_BYTES
    store_dtype = None
    if regular and fmt_code in fmt_code_map:
        store_dtype = _seismic_endian.get(str(p), ">") + fmt_code_map[fmt_code]

    nbytes = int(shots.size) * n_r * ns * np.dtype(store_dtype or "f4").itemsize
    info = {
        "shots": shots, "tracl": tracl, "sx": sx, "gx": gx, "offset": probe_off,
        "n_traces": n_traces, "ns": ns, "dt": dt, "dt_us": dt_us, "fmt_code": fmt_code,
        "n_shot": int(shots.size), "n_r": n_r, "blocks": blocks, "regular": regular,
        "counts": counts, "short": short, "holes": holes, "by_tracl": by_tracl,
        "dx": dx, "ds": ds, "dx_ok": dx_ok, "ds_ok": ds_ok, "nbytes": nbytes,
        "trace_bytes": trace_bytes, "first_sample": head_bytes + _TRACE_HEADER_BYTES,
        "store_dtype": store_dtype, "probed": int(n_probe),
        "sx_range": (float(np.nanmin(sx)), float(np.nanmax(sx))) if sx.size else (0.0, 0.0),
        "gx_range": (float(np.nanmin(gx)), float(np.nanmax(gx))) if gx.size else (0.0, 0.0),
        "off_range": (float(np.nanmin(probe_off)), float(np.nanmax(probe_off)))
                     if probe_off.size else (0.0, 0.0),
    }
    info["summary"] = _seismic_summary(p, info)
    _seismic_cache[str(p)] = info
    return info


def _seismic_summary(p: Path, info: dict) -> str:
    lines = [
        f"当前：{p.name}",
        f"{info['n_shot']} 炮 × {info['n_r']} 道 × {info['ns']} 采样　"
        f"dt {info['dt'] * 1000:.4g} ms　记录长 {info['ns'] * info['dt']:.3f} s",
    ]
    if not info["by_tracl"]:
        lines.append("各炮 TraceNumber 起始号不一致（可能是全文件连续编号），已按顺序紧密排列")
    if info["holes"]:
        where = "按道号定位，缺失位置留空" if info["by_tracl"] else "缺道可能造成该炮错位"
        lines.append(f"{info['holes']} 炮存在缺道（{where}）")
    if info["short"] and not info["holes"]:
        lines.append(f"{info['short']} 炮道数少于最多炮（{info['n_r']}），末尾补零")
    lines.append(
        f"偏移距 {info['off_range'][0]:.6g} ~ {info['off_range'][1]:.6g}"
        f"（前 {info['probed']} 道抽样）　"
        + (f"道距 {info['dx']:.6g} m　炮距 {info['ds']:.6g} m（取自道头）"
           if info["dx_ok"] and info["ds_ok"] else
           "道头坐标未能给出可信间距，横轴按道序号/炮序号显示"))
    if info["store_dtype"]:
        lines.append("数据按需读取，不会整卷载入内存")
    lines.append("R 轴 = 炮内道序（非物理检波点坐标）；时间切片是 (炮号, 道号) 索引平面")
    return "\n".join(lines)


def _list_seismic(p: Path) -> list[VariableInfo]:
    info = _scan_seismic(p)
    kind = "SU" if p.suffix.lower() == ".su" else "SEG-Y"
    note = f"{kind} 惰性读取" if info["store_dtype"] else f"{kind} 道头分选"
    return [VariableInfo(
        key=SEISMIC_KEY,
        shape=(info["n_shot"], info["n_r"], info["ns"]),
        dtype=str(np.dtype(info["store_dtype"] or "f4")),
        nbytes=info["nbytes"],
        note=note,
        roles=(ROLE_SHOT, ROLE_RECV, ROLE_TIME),
    )]


def _lazy_seismic(p: Path, info: dict):
    """建一个零拷贝的立方体视图：只有真正要看的那一片才会从磁盘读上来。

    每条道是 ``[240 字节道头][定长样点]`` 的定长记录，所以第 (s, r, t) 个样点在
    文件里的偏移是可以用"步长"表达的 —— 于是 mmap + ``as_strided`` 就能直接
    把它当成 (炮, 道, 时间) 数组用，不必先把整个文件读进内存。
    实测：230 MB 文件建视图 1.3 ms（整块读要 0.6 s 且占同等内存）。

    条件不满足（各炮道数不一致、样点格式需要转换等）时返回 None，由调用方整块读。
    """
    if not info.get("store_dtype") or not info["regular"]:
        return None
    dtype = np.dtype(info["store_dtype"])
    if info["first_sample"] % dtype.itemsize:        # memmap 要求按元素对齐
        return None
    try:
        mm = np.memmap(p, dtype=dtype, mode="r", offset=info["first_sample"])
        view = np.lib.stride_tricks.as_strided(
            mm, shape=(info["n_shot"], info["n_r"], info["ns"]),
            strides=(info["n_r"] * info["trace_bytes"], info["trace_bytes"],
                     dtype.itemsize),
            writeable=False)
    except (ValueError, OSError, MemoryError):
        return None
    if view.nbytes != info["nbytes"]:                # 兜底：形状对不上就别用
        return None
    return view


def _load_seismic(p: Path) -> np.ndarray:
    info = _scan_seismic(p)
    lazy = _lazy_seismic(p, info)
    if lazy is not None:
        return lazy                                  # 惰性：不预读数据
    if info["nbytes"] > _MAX_CUBE_BYTES:
        raise LoadError(
            f"从道头算出的立方体约 {info['nbytes'] / 1024 ** 3:.1f} GB，超出内存上限，"
            "请先在外部抽稀或只取一部分炮")
    cube = np.zeros((info["n_shot"], info["n_r"], info["ns"]),
                    dtype=np.dtype(info["store_dtype"] or "f4"))
    with _open_seismic(p) as f:
        for k, (kind, payload) in enumerate(info["blocks"]):
            if kind == "range":
                start, stop, r0 = payload
                cube[k, r0:r0 + (stop - start)] = np.asarray(
                    f.trace.raw[start:stop], dtype=cube.dtype)
            else:
                fidx, ridx = payload
                cube[k, ridx] = np.asarray([f.trace[int(i)] for i in fidx],
                                           dtype=cube.dtype)
    return cube


def load_meta(path: str | os.PathLike, key: str) -> dict:
    """该变量附带的元信息（目前只有 SEG-Y/SU 有：dt 与摘要）。"""
    p = Path(path)
    if p.suffix.lower() not in SEISMIC_SUFFIXES:
        return {}
    info = _scan_seismic(p)
    return {"dt": info["dt"], "dx": info["dx"], "ds": info["ds"],
            "meta": {"summary": info["summary"], "source": "SEG-Y" if p.suffix.lower() != ".su" else "SU"}}


# ====================================================================== 载入数组
def load_array(path: str | os.PathLike, key: str) -> np.ndarray:
    """载入指定变量。

    ``.npy`` 走 mmap（不占常驻内存），``.mat`` 走缓存，``.npz`` 只解压目标成员，
    ``.sgy``/``.segy``/``.su`` 按道头现搭 ``(炮, 道, 时间)`` 立方体。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in SEISMIC_SUFFIXES:
        return _load_seismic(p)
    if suffix == ".npy":
        arr = np.load(p, mmap_mode="r", allow_pickle=False)
        if not np.issubdtype(arr.dtype, np.number):
            raise LoadError(f"{key} 不是数值数组（{arr.dtype}）")
        return arr
    if suffix == ".npz":
        with np.load(p, allow_pickle=False) as z:
            if key not in z.files:
                raise LoadError(f"{p.name} 中不存在变量 {key}")
            return z[key]
    if suffix == ".mat":
        data = _load_mat_cached(str(p))
        if key not in data:
            raise LoadError(f"{p.name} 中不存在变量 {key}")
        arr = data[key]
        if not isinstance(arr, np.ndarray):
            raise LoadError(f"{key} 不是矩阵变量（{type(arr).__name__}）")
        return arr
    raise LoadError(f"不支持的扩展名：{suffix}")


def file_fingerprint(path: str | os.PathLike) -> str:
    """文件指纹：路径 + 大小 + 修改时间，用于记住轴序选择。"""
    p = Path(path)
    try:
        st = p.stat()
        raw = f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        raw = str(p)
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()[:16]


# ====================================================================== 轴序记忆
def _config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "SeisView"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path.home() / ".seisview"
        d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def load_config() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    try:
        _config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    except OSError:
        pass


def get_axis_memory(fingerprint: str) -> list[str] | None:
    return load_config().get("axes", {}).get(fingerprint)


def set_axis_memory(fingerprint: str, roles: list[str]) -> None:
    cfg = load_config()
    cfg.setdefault("axes", {})[fingerprint] = roles
    save_config(cfg)


# ====================================================================== 轴序 → 体数据
def guess_roles(shape: tuple[int, ...]) -> list[str]:
    """给出一个**默认猜测**供用户确认，绝不静默采用。

    只能保证"是个合理的起点"，用户必须过目。时间轴通常是最长的一维。
    """
    n = len(shape)
    if n == 1:
        return [ROLE_TIME]
    if n == 2:
        # 约定俗成的两种存法：(T, R) 与 (R, T)。长的那个更可能是时间。
        return [ROLE_TIME, ROLE_RECV] if shape[0] >= shape[1] else [ROLE_RECV, ROLE_TIME]
    if n == 3:
        return [ROLE_SHOT, ROLE_RECV, ROLE_TIME]
    return [ROLE_SHOT, ROLE_RECV, ROLE_TIME] + ["ignore"] * (n - 3)


def roles_to_order(roles: list[str]) -> tuple[list[int], list[str]]:
    """把每个轴的物理角色翻译成 (转置顺序, 补维说明)。

    返回 ``order``：``order[0]`` 是炮点轴、``order[1]`` 是检波器轴、``order[2]`` 是时间轴，
    取值 -1 表示该维度在源数据中不存在，需要插入长度为 1 的新轴。
    """
    order: list[int] = []
    missing: list[str] = []
    for want in (ROLE_SHOT, ROLE_RECV, ROLE_TIME):
        if want in roles:
            order.append(roles.index(want))
        else:
            order.append(-1)
            missing.append(ROLE_LABELS[want])
    if order[2] == -1:
        raise LoadError("必须指定哪一个轴是「时间」")
    return order, missing


def build_volume(name: str, arr: np.ndarray, roles: list[str], **kw) -> SeisVolume:
    """按确认后的轴序把原始数组规范化成 (S, R, T) 的 SeisVolume。"""
    if arr.ndim != len(roles):
        raise LoadError(f"轴数不匹配：数据 {arr.ndim} 维，但指定了 {len(roles)} 个轴角色")
    order, _missing = roles_to_order(roles)

    # 先转置已有维度（忽略负索引），再补齐缺失维度
    present = [i for i in order if i >= 0]
    if len(set(present)) != len(present):
        raise LoadError("同一个轴被指定了多个角色，请重新确认轴序")
    data = np.transpose(arr, present) if len(present) == arr.ndim else arr
    for k, idx in enumerate(order):
        if idx == -1:
            data = np.expand_dims(data, axis=k)

    # 刻意不做 ascontiguousarray：.npy 的 mmap 一旦强制连续就会把整个文件读进内存，
    # 惰性加载的意义就没了。切片函数会在取出二维面时再拷贝成连续数组。
    return SeisVolume(name=name, data=data, **kw)


def describe_shape(shape: tuple[int, ...]) -> str:
    return " × ".join(str(v) for v in shape)


def role_options() -> list[str]:
    return [ROLE_LABELS[r] for r in (ROLE_SHOT, ROLE_RECV, ROLE_TIME)] + ["忽略"]


def label_to_role(label: str) -> str:
    return LABEL_TO_ROLE.get(label, "ignore")