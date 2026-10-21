# SeisView

[中文](README.md) | English

A lightweight seismic data viewer: **3D volume + slice + single-trace waveform** in one linked workspace (free split layouts, panels can be torn off into floating windows), with **multi-dataset comparison**. It is made for taking a quick look at what is actually inside `.npy` / `.npz` / `.mat` / `.sgy` / `.su` files.

![SeisView main window: just drop a file into the window](assets/主界面0.3.0.png)

![Example data loaded (layout B: slice | 3D, waveform in the bottom bar)](assets/载入示例后的界面0.3.0.png)

> The UI is currently Chinese. Screenshots are reused as-is; the captions here are in English.

---

## Features

- **Three-level drill-down**: 3D volume for the big picture → click a face to switch to that slice → click a trace on the slice to show its waveform.
- **Single-trace panel**: x = time, y = amplitude; in comparison mode traces from multiple datasets are overlaid in different colors. The target trace index can be changed once for all datasets.
- **Multi-dataset comparison**: up to **3** datasets with the same shape; each gets its own slice panel. A **sync switch** broadcasts the current slice position and target trace to the other datasets. Overlaid wiggle curves and trace colors follow the left-to-right dataset order (dragging A onto B also swaps colors). All comparison panels **share one color-scale window**, so "which dataset has stronger amplitudes" is directly comparable.
- **Three orthogonal faces**: common-shot, common-receiver and time slice. The 3D camera animates to the front view of the selected face.
- **Sweep playback**: drag the playhead or press play to flip through slices and inspect lateral continuity.
- **Display modes**: density image or wiggle-only; 9 colormaps (including the conventional red/blue), color limit (auto / robust / manual), contrast, AGC (whole trace or sliding window), render decimation. Controls that do not apply are greyed out. **Time slices have no time axis, so AGC is disabled and not applied there.**
- **Free workspace layouts**: the three panels live in one splitter tree. Single-view / split-view presets (7 concrete layouts, including "waveform on top" and "3D on the left"). Panels can be dragged to a workspace edge with a 1/3 preview, or torn off into floating windows and docked back. Any layout can be starred as the default.
- **Bad samples do not poison the display**: NaN / Inf are excluded from color-scale statistics and shown as holes in the panel background.
- **Import**: open a file (`Ctrl+O`) or drag files into the window. On drop, SeisView asks whether to compare or replace when shapes allow it, and reports duplicate paths and unsupported types.
- **Export / conversion**: whole volume / per-slice / current slice figure / current waveform figure. Matrices can be written as `.npy` / `.npz` / `.mat`, or as SEG-Y / SU with synthesized trace headers. Per-slice export supports a slice range and "current slice only". Figures are exported as **PNG / SVG** in a paper-ready style (white background, physical units, no grid by default).
- **2D data works too**: the 3D panel is closed automatically when a 2D dataset is loaded.
- **Themes**: Deep Blue (default), Midnight, Paper (light), High Contrast, **Rose**, **Frosted Grey (low contrast)**, plus Follow System. Exported figures are always paper-white and are not affected by the UI theme.
- **Startup optimization**: the 3D view and `scipy.signal` are loaded on demand; the splash screen covers the remaining window construction. On a source checkout, the startup import path is roughly 2.2 s → 0.6 s on the same machine.
- **SEG-Y / SU header scan**: one strided mmap pass reads both required header words (`FieldRecord`, `TraceNumber`) plus probe fields, instead of two field-by-field scans. Malformed/variable-length files automatically fall back to segyio.

## Quick start

### Option 1: prebuilt Windows package (recommended for non-Python users)

Download `SeisView-*-win64.zip` from [Releases](https://github.com/OoBlackFishoO/SeisView/releases), **extract the whole folder**, then double-click `SeisView.exe`. No Python installation is required.

> ⚠️ This is an onedir PyInstaller build. Keep the whole extracted directory together; copying only the exe will not work.

To create a desktop shortcut: right-click `SeisView.exe` → Send to → Desktop (shortcut).

### Option 2: run from source

```bash
pip install -r requirements.txt
python main.py
```

You can also pass a file path directly:

```bash
python main.py D:\data\volume.npz
```

Click **载入示例** (Load sample) to see the built-in synthetic volume immediately: 24 shots × 72 receivers × 700 samples, with four dipping reflectors, two diffractors and random noise.

Generate a few more realistic sample files (multi-key `.npz`, `.npy`, MATLAB-style `.mat`):

```bash
python make_sample.py      # writes to sample_data/
```

## Supported formats

| Format | Notes | Reader |
| --- | --- | --- |
| `.npy` | bare array | **mmap lazy read**, no resident copy |
| `.npz` | multi-variable container; choose one member | only the selected member is decompressed |
| `.mat` | MATLAB v4 / v5 / v7 | loaded and cached once; **v7.3 (HDF5) is not supported** and reported clearly |
| `.sgy` / `.segy` | standard SEG-Y | trace-header scan; optional mmap lazy read |
| `.su` | Seismic Unix (no file header) | same as SEG-Y; byte order auto-detected |

All data is normalized internally to **`(S, R, T)` = (shot, receiver, time)**. 2D data is promoted to `(1, R, T)`, so 1D / 2D / 3D share the same code path.

**Axis order**: `.npy` / `.npz` / `.mat` axis conventions differ worldwide (MATLAB often stores time × trace, Python often trace × time). The first time a file is opened, SeisView asks you to confirm the physical meaning of each axis and remembers it by file fingerprint. It deliberately does not guess: a wrong axis order is hard to notice later.

![Confirm the axis order on first open](assets/设置维度轴.png)

## SEG-Y / SU notes

**① The sorting rule is fixed**: `FieldRecord → shot S`, trace order within a shot (`TraceNumber`) → receiver R, samples → time T.

This is not a spatial cube: when sources and receivers are at different positions, **the R axis is the in-shot trace number, not a physical receiver coordinate**, and a time slice is a `(shot, trace)` index plane rather than a map. A summary is shown after loading.

If traces are missing, they are located **by trace number and the missing positions are left empty** (later traces are not shifted up, which would misalign the whole shot). The summary reports how many shots/traces are missing.

**② Large files are not preloaded**: when every shot has the same trace count and samples are standard float/int formats, SeisView builds a zero-copy `mmap + as_strided` view. Opening a 3 GB file only scans the trace headers once (a few seconds); rendering is instant and resident memory stays almost flat. Old IBM float data or irregular trace counts automatically fall back to a full read, with identical results.

> To profile a SEG-Y / SU file, start with `SEISVIEW_PROFILE=1` (PowerShell: `$env:SEISVIEW_PROFILE="1"; python main.py`). The console prints the time spent in **open / header scan / index build / mmap view or full read**. The header scan now reads both required header words in one strided mmap pass; abnormal files automatically fall back to segyio.

### Data where sources and receivers are at different positions (e.g. pluto)

The same rules still apply: a common-shot face is a standard shot gather (horizontal axis = trace number, vertical = time); a common-receiver face is a receiver gather for a fixed spread. If header fields such as `SourceGroupScalar` are valid, the offset range and trace spacing are written into the summary for verification. When no trustworthy spacing is available, the horizontal axis is shown as trace/shot index and explicitly labelled; SeisView does not invent a fake scale.

## Export and conversion

The **Export / Convert** button in the top bar (`Ctrl+E`) first asks **what** to export, then the format. Four content types with very different semantics are exposed in one dialog:

| Content | Formats | One-line description |
| --- | --- | --- |
| Whole volume | `.npy` / `.npz` / `.mat` / SEG-Y / SU | all samples, fixed shape `(S, R, T)` |
| Per-slice | `.npy` / `.npz` / `.mat` | one 2D file per slice; optional slice range |
| Current slice figure | PNG / SVG | **paper-ready** (white background + physical axes), redrawn rather than screenshotted |
| Current waveform figure | PNG / SVG | same style; current trace, all compared datasets included |

### Matrix output (`.npy` / `.npz` / `.mat`)

Only the data itself is written, with shape `(S, R, T)` = shot × receiver × time.

- No `dt` / `dx` / `ds` metadata is written; downstream code must know the sampling intervals.
- Missing traces are filled with **0**, so "real zero" and "missing trace" cannot be distinguished downstream.
- No display processing is baked in: AGC, decimation and color limits affect only what is drawn, never the exported values.

`.npy` is written header-first and then filled per shot through a memmap, so exporting a 3 GB volume keeps only one shot in memory. `.npz` / `.mat` writers need one contiguous array; the dialog warns about this and refuses above about 2.5 GB, suggesting `.npy` instead.

### Per-slice export

Each slice is written as a separate 2D file (e.g. 901 common-shot slices → 901 `.mat` files). The "Save to" field then means a **folder**.

- **Slice range** (start / end), plus "set range to the currently displayed slice";
- **Current slice only** — ignores the range above and exports the slice currently shown; in comparison mode, the current slice of **all datasets** is exported (their positions follow the sync switch; range controls are greyed out).

| Slice direction | Number of slices | File shape | Notes |
| --- | --- | --- | --- |
| Common shot (time × offset) | shots | `(time, receiver)` | the conventional `(nt, nr)` shot gather |
| Common receiver (time × shot) | traces | `(time, shot)` | |
| Time slice (shot × offset) | samples | `(shot, receiver)` | |

Each file follows the same orientation as the on-screen slice (rows = vertical axis, columns = horizontal axis), so plotting it in MATLAB / NumPy should look like what you saw. The variable name inside the file is always `cube` (a 2D array), so downstream code can read every file the same way.

File names follow one rule: **name + underscore + index + extension**, where the index is the shot / trace / time-sample number (0-based).

| Name field | Generated names (common shot, `.mat`) |
| --- | --- |
| `demo` | `demo_0.mat`, `demo_1.mat`, … |
| empty | `0.mat`, `1.mat`, …, `900.mat` |

If you cancel halfway, **files already written are kept** (they are complete); only the file currently being written is removed, and the message reports how many were written.

### Figures (PNG / SVG)

"Current slice figure" and "Current waveform figure" **redraw** the current view as a paper-ready figure rather than taking a screenshot:

- **White background + dark axes**, independent of the UI theme;
- Axes are converted to physical units using `dt / dx / ds` from the settings panel (seconds / metres);
- No grid by default (a grid only covers the reflectors);
- Compatible with grayscale and red/blue seismic colormaps; no grid in wiggle-only mode;
- Figure size and sampling-unit display are adjustable in the export dialog; in comparison mode, **one figure per dataset** is produced, with the dataset index in the file name.

Line styles (black solid / red solid / blue dashed, etc.) come from the **line style** control in the waveform group. They apply to exported figures only; on screen SeisView uses dataset identification colors.

### SEG-Y / SU output

SEG-Y is a flat list of traces, each carrying its own 240-byte trace header, while a volume is an abstract grid. SeisView therefore **synthesizes** a minimal but correct set of trace headers:

| Header field | Value |
| --- | --- |
| `FieldRecord` | shot + 1 |
| `TraceNumber` | in-shot trace number + 1 |
| `TRACE_SAMPLE_COUNT` / `TRACE_SAMPLE_INTERVAL` | samples per trace / sample interval (µs) |
| `SourceX` / `GroupX` / `offset` (only if "write coordinate headers" is checked) | `s·ds` / `s·ds + r·dx` / `r·dx` |

No other headers from the source file are inherited (CDP, elevation, date, etc. are not carried over).

The three values are self-consistent (`offset == GroupX − SourceX`, trace spacing = `dx`, shot spacing = `ds`), so any package can locate and sort the traces correctly. Reading the file back with SeisView restores the same `dt / dx / ds`.

**These are geometry inferred from spacings, not measured coordinates**. Real source/receiver positions cannot be derived from two spacings, and observation geometries that change per shot are not supported. For such data, leave the coordinate option off and write only shot / trace / sample information; a file without geometry is more honest than one with fake coordinates.

**Why coordinate scalars are mandatory**: SEG-Y coordinate fields are 32-bit integers. A trace spacing of 12.5 m would be rounded to 13, destroying the geometry. When `dx` / `ds` have decimals, SeisView writes `SourceGroupScalar = −10^k` and scales the coordinates to integers; the reader divides by the scalar and recovers the exact decimal.

Sample format is always **IEEE float32 (format code 5)** for best compatibility. Old software that only understands IBM float (code 1) needs an external conversion.

> SU has no file header, and `segyio` provides read-only support, so SU output is written manually as fixed-size records `[240-byte trace header][samples]` in little-endian order.

## UI cheat sheet

| Area | What it does |
| --- | --- |
| Top bar | Open file (`Ctrl+O`), load sample, export / convert (`Ctrl+E`); version badge; files can also be dropped into the window |
| Rail (far left) | Click an icon to jump to a settings group and highlight it; bottom has expand/collapse-all (⇕) and the gear (window settings) |
| Data | Choose variable, set `dt` / `dx` / `ds` (Enter applies), read the file summary |
| Slice & playback | Common-shot / common-receiver / time slice; slider or playhead; previous/next slice; play/pause, speed, loop |
| Density | Colormap, color limit, contrast, AGC, render decimation (inapplicable controls greyed out); density / wiggle-only switch |
| Waveform | Target trace index (broadcast in comparison), number and gain of overlaid wiggles; line style (export figures only) |
| Compare | Dataset selector, add/remove comparison dataset, sync switch |
| Capsule (top right) | Pure toggles for waveform / slice / 3D; `⇄` swaps the two reorderable panels; `分屏` opens the layout picker (with ★ default) |
| Workspace · slice | Left-drag to pan, wheel to zoom, double-click to reset; click to select that trace |
| Workspace · waveform | Current trace (x = time, y = amplitude); compared datasets are overlaid in different colors |
| Workspace · 3D | Drag to rotate, wheel to zoom; click a face to switch to it; bottom bar has the current-face readout and "reset view" |
| Panel header row | Drag = tear off / change split / dock back. The **slice group** handle on the 「剖面」 header moves the whole group (all comparison panels); the small `⇄` grip inside each slice panel only swaps dataset order. Shortcuts `1/2/3` focus one panel, `Tab` cycles |
| Gear (rail bottom) | Window settings: sidebar groups / theme / follow-layout window sizing / split panel |

Hovering over a slice shows the physical coordinate in the top-right corner; leaving the panel (or moving onto the reset button) shows `—`.

### Color scale, contrast and playback speed

Amplitudes map to colors through a **symmetric window** `median ± half-width`:

- **Color limit** (auto / robust / manual) sets the base window:
  - `auto` = `max(8 × 1.4826 × MAD, P95(|x|))`; the P95 floor clips at most 5% of heavy-tailed data;
  - `robust` = 2% / 98% percentiles;
  - `manual` = ± the entered value.
- **Contrast** scales the base half-width: `100%` = base, `200%` = half window (harder), `50%` = double window (softer), always symmetric around the window center. The slider is **logarithmic** over `10%–1000%`, with 100% in the middle.
- Out-of-window samples are clamped to the end colors **for display only**; the source data and exported values are untouched.
- **NaN / Inf are excluded** from statistics; they are drawn as holes. AGC energy statistics skip them as well.
- With **AGC** enabled, amplitudes are normalized per trace first and the base window is recomputed robustly per slice; the color-limit control is greyed out, contrast still applies.
- Sweep playback targets `150 / 70 / 35 / 16 ms` per slice (≈ `6.7 / 14.3 / 28.6 / 62.5` slices/s). Actual frame rate is limited by render time; changing speed during playback takes effect immediately.

### Comparison-mode regression checklist

After changing sync, ordering, colors, color scale or the clear path, run through this checklist:

- [ ] **Sync on**: changing the main slice/trace updates all other datasets.
- [ ] **Sync off**: changing the main dataset leaves the others untouched.
- [ ] **3-dataset reorder**: colors and data content both change; window and panel pixel sizes do not.
- [ ] **Clear and reload**: all panels return to the empty state (no leftover image/color scale/trace curve); reloading shows no ghost data.
- [ ] **Floating window**: comparison sync and the reference line still work after a panel is torn off.
- [ ] **Reference line / trace index**: sync-on panels select the same trace; reset (`A` button or double-click) does not move the green line.
- [ ] **Overlaid wiggles**: colors follow left-to-right order; the compact header legend matches the curves.
- [ ] **Shared color scale**: all panels use the same `median ± half-width`, so amplitudes are directly comparable.
- [ ] **Time slice**: AGC is greyed out and not applied; 2D and 3D time slices have the same brightness.

## Project layout

```text
seisview/
  volume.py      (S,R,T) data contract, three orthogonal slices, decimation, AGC, color scale
  loaders.py     file readers: npy / npz / mat / sgy / su (lazy mmap)
  export.py      export / conversion: matrices, per-slice, SEG-Y / SU with synthesized headers
  render.py      colormaps, array-to-RGBA, wiggle curves, 3D face textures
  view2d.py      slice / waveform panels and offscreen paper-figure rendering
  view3d.py      3D volume (face textures + ray picking + camera animation)
  widgets.py     custom widgets (capsule, floating panels, fold cards, dialogs, playhead, …)
  main_window.py assembly, signal wiring, layout / drag gestures, comparison, import / export
  style.py       palette-based themes and QSS
  icons.py       hand-drawn icons
  sample.py      built-in synthetic example
tests/           headless regression tests (unittest / pytest compatible)
main.py          entry point
make_sample.py   generate sample data files
make_icon.py     generate the application icon
README.md / README.en.md   Chinese / English docs
```

## Requirements

- Python 3.10+
- PySide6, pyqtgraph, PyOpenGL, numpy, scipy, segyio
- OpenGL 4.x for the 3D view (if unavailable, slice and waveform still work and a message is shown in the right panel)

## Build the Windows exe

Double-click **`build.bat`** (it checks/installs PyInstaller, generates the icon and packages the app):

```text
dist\SeisView\SeisView.exe
```

Configuration is in `seisview.spec`: onedir, no console window, icon, **version resource**, and a large exclusion list for unused PySide6 / PyQtGraph / scientific packages. The version number lives in two places and must be kept in sync:

- `seisview/__init__.py` → `__version__` (shown in the top-bar version badge);
- `assets/version_info.txt` → `filevers` / `prodvers` / `FileVersion` / `ProductVersion`.

> PyInstaller's `version=` argument expects a **file path**; passing `"0.3.1"` is interpreted as a path and fails.

> Packaging note: PyInstaller's `hook-pyqtgraph` used to pull `torch` into the module graph and add 3.5 GB of CUDA libraries. The spec excludes those explicitly; the package shrank from 3.8 GB to about 255 MB (≈96 MB zipped).

## Changelog

### v0.3.1

- **One AGC / decimation / color-scale pipeline** shared by 2D slices and 3D face textures; identical rendered arrays for the same face and parameters. Time slices never apply AGC (the control is disabled). Comparison panels share one color-scale window.
- **Reset only changes the view**: the lower-left `A` button is no longer mistaken for a trace pick, and the first click of a double-click reset is undone, so the green reference line and trace index stay put.
- **Comparison fixes**: clearing data no longer aborts with an index error and leaves stale images; hovering no longer resizes panels; reordering only changes dataset order, never window or panel sizes.
- **Interaction polish**: settings groups keep their scroll position when toggled; leaving a slice shows `—`; the on-screen legend is now a compact header legend; a manually resized window becomes the size anchor.
- **Layout / window**: collapsing the sidebar shrinks the window by the same amount; changing layouts in fullscreen/maximized mode no longer exits it; restoring from maximized returns to the pre-maximized size; tearing off a panel exits fullscreen.
- **Export progress**: `.mat` / `.npz` serialization shows "正在序列化为 MAT…" and progresses smoothly to 99% instead of freezing at 90%.
- **Slice area moves as one group**: one six-dot handle on the 「剖面」 group header drags all comparison panels together (tear-off/dock included); a distinct `⇄` grip inside each slice panel only swaps dataset order. Single slices can no longer be torn off alone.
- **Per-panel slice aspect**: the comparison group's natural width is `N × single-panel natural width`, so panels no longer become thin vertical strips.
- **Contrast range 10%–1000%** with a logarithmic slider (100% centered).
- **Faster startup**: 3D and `scipy.signal` are loaded on demand, plus a splash screen. Source-start import path roughly 2.2 s → 0.6 s on the same machine.
- **Faster SEG-Y / SU header scan**: one strided mmap pass reads both required header words; malformed files fall back automatically. On a 12 MB / 2880-trace file, header scan drops from ~48 ms to ~5 ms. Use `SEISVIEW_PROFILE=1` to see the phase timings.
- **New themes**: Rose and Frosted Grey (low contrast). Frosted Grey is a low-contrast layered palette, not true background blur (plain Qt widgets cannot blur what is behind them).

### v0.3.0

- Multi-dataset comparison (up to 3 datasets), sync switch, per-dataset slice panels, colors following left-to-right order.
- Waveform panel rebuilt: x = time, y = amplitude; overlaid curves for compared datasets; target trace control.
- Wiggle-only mode; drag-and-drop import; export dialog covering whole volume / per-slice / figures.
- New layout system (single/split views, 7 layouts, tear-off panels, starrable defaults, 1/3 drop previews).
- Sidebar rebuilt with icon rail; palette-based themes; window follows layout.

### v0.2.0

- Export / conversion to matrices and SEG-Y / SU, with a confirmation dialog before writing.
- Per-slice export.
- Auto color limit with a P95 floor; contrast direction inverted to "higher = harder".
- Density panel grouped into color / gain / wiggle overlay / performance; inapplicable controls greyed out.
- Slice interaction: left-drag pan, wheel zoom, double-click reset.
- NaN / Inf safe color scales.

### v0.1.0

- First release: linked 3D volume / slice / waveform views, three orthogonal faces, sweep playback, color scale and AGC, wiggle overlay, `npy` / `npz` / `mat` / `sgy` / `su` readers, onedir PyInstaller build.

## License

[MIT](LICENSE)
