"""生成演示用的样例数据文件，写到 sample_data/ 下。

- sample_volume.npz   三个键：seismic 三维体、section 二维剖面、shot_gather 单炮
                       用于验证"多键文件"与"同一文件里混有不同维度的变量"
- volume.npy          裸三维数组 (S, R, T)
- section.npy         裸二维剖面 (R, T)  —— 打开时会走二维路径
- volume_matlab.mat   以 MATLAB 常见的 (T, R, S) 顺序存放，用来检验轴序确认
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seisview.sample import make_section, make_volume  # noqa: E402


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "sample_data")
    os.makedirs(out, exist_ok=True)

    data = make_volume()                      # (24, 72, 700) float32
    section = make_section()                  # (72, 700) float32
    shot = np.ascontiguousarray(data[12])     # (72, 700) 单炮

    np.savez(os.path.join(out, "sample_volume.npz"),
             seismic=data, section=section, shot_gather=shot)
    np.save(os.path.join(out, "volume.npy"), data)
    np.save(os.path.join(out, "section.npy"), section)

    try:
        from scipy.io import savemat
        # MATLAB 习惯把时间放在第一维，正好用来演示轴序确认
        savemat(os.path.join(out, "volume_matlab.mat"),
                {"seismic": np.transpose(data, (2, 1, 0))}, do_compression=True)
        saved_mat = True
    except Exception as exc:                   # pragma: no cover
        print(f"跳过 .mat 生成：{exc}")
        saved_mat = False

    print(f"样例数据已写入：{out}")
    for name in sorted(os.listdir(out)):
        size = os.path.getsize(os.path.join(out, name))
        print(f"  {name:<24} {size / 1024:8.1f} KB")
    if not saved_mat:
        print("（未生成 .mat，需要 scipy）")
    print(f"\n三维数据形状 (S, R, T) = {data.shape}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())