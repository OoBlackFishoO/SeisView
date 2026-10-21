# SeisView

[中文](README.md) | English

SeisView is a desktop visualization tool for seismic data. It provides linked 3D volume, 2D slice and single-trace waveform views, multi-dataset comparison, and image export.

![SeisView main window](assets/主界面0.3.0.png)

![Example data loaded](assets/载入示例后的界面0.3.0.png)

---

## Features

### What the software does

- Loads `.npy`, `.npz`, `.mat`, `.sgy` / `.segy` and `.su` data and organizes it by shot, receiver and time.
- Provides linked 3D volume, common-shot slice, common-receiver slice, time slice and single-trace waveform views.
- Supports side-by-side comparison of up to three datasets with the same shape, including synchronized slices, a shared color scale and dataset-ordered colors.
- Exports whole volumes, per-slice data, current slice figures and current waveform figures.

### Functional effects

- **Linked views**: selecting a face on the 3D volume switches to the corresponding slice; selecting a position on a slice switches the waveform; slice position, target trace and display settings can stay consistent across panels.
- **Comparison**: datasets are shown side by side and can share slice position and target trace; all panels use one color-scale window, so amplitude strength is directly comparable; overlaid wiggles and traces use distinct colors by dataset order.
- **Display controls**: density image or wiggle-only rendering, color scale, color limit, contrast, AGC and render decimation. Controls that do not apply are disabled; AGC is disabled on time slices.
- **Sweep browsing**: use the playhead or playback to move through slices and inspect lateral continuity.
- **Workspace layout**: single-view and split-view modes, multiple preset layouts; panels can be reordered, torn off into floating windows, or docked back.
- **Image export**: redraws the current slice or waveform as a white-background PNG / SVG with physical axis units.

### Typical use cases

- Quickly inspect data dimensions, axis order, amplitude range and valid traces.
- Compare data before/after processing, different processing results, or different display parameters.
- Perform basic quality control, such as locating missing traces, dead traces and abnormal amplitudes.
- Produce consistent slice and waveform figures for reports, papers or presentations.
- Demonstrate the relationship between a 3D volume, orthogonal slices and single traces in teaching.

## Quick start

### Windows package

Download `SeisView-*-win64.zip` from [Releases](https://github.com/OoBlackFishoO/SeisView/releases), extract the whole folder, and double-click `SeisView.exe`. Python is not required.

> The release is an onedir package. Keep the complete directory together; copying only the exe will not work.

### Run from source

```bash
pip install -r requirements.txt
python main.py
```

A file path can also be passed directly:

```bash
python main.py D:\data\volume.npz
```

Click **载入示例** to view the built-in synthetic data. Running `python make_sample.py` generates additional sample files.

## Supported formats

| Format | Notes |
| --- | --- |
| `.npy` | NumPy array |
| `.npz` | NumPy multi-variable container; choose a variable |
| `.mat` | MATLAB v4 / v5 / v7; v7.3 (HDF5) is not supported |
| `.sgy` / `.segy` | Standard SEG-Y |
| `.su` | Seismic Unix, no file header |

When a `.npy` / `.npz` / `.mat` file is opened for the first time, SeisView asks for the physical meaning of each axis (shot, receiver, time) and remembers the setting per file.

![Confirm the axis order on first open](assets/设置维度轴.png)

### SEG-Y / SU notes

- The sorting rule is fixed: `FieldRecord` → shot, in-shot `TraceNumber` order → receiver, samples → time.
- When sources and receivers are at different positions, the receiver axis represents the in-shot trace number, and a time slice is a shot/trace index plane.
- Missing traces are located by trace number and left empty; the load summary reports them.
- Large files are read on demand; the complete dataset is not loaded into memory when the file is opened.

## Interface and controls

| Area | Operation |
| --- | --- |
| Top bar | Open file, load sample, export / convert |
| Left settings | Select variable, set sampling interval and trace spacing, switch slice direction, adjust display and comparison settings |
| 3D panel | Drag to rotate, wheel to zoom; click a face to switch to that slice |
| Slice panel | Left-drag to pan, wheel to zoom, double-click to reset; click to select the target trace |
| Waveform panel | Shows the current trace; overlays multiple datasets in comparison mode |
| Panel header | Drag to move or tear off; the slice group header moves all panels, while the inner `⇄` grip only swaps dataset order |

## Export and conversion

The top-bar **Export / Convert** button (`Ctrl+E`) provides four content types:

| Content | Formats | Notes |
| --- | --- | --- |
| Whole volume | `.npy` / `.npz` / `.mat` / SEG-Y / SU | All samples, shaped shot × receiver × time |
| Per-slice | `.npy` / `.npz` / `.mat` | One file per slice along a selected direction; optional slice range |
| Current slice figure | PNG / SVG | White background, physical axes and a color bar |
| Current waveform figure | PNG / SVG | Current trace; all compared datasets included |

Matrix exports contain only the data, without sampling metadata; missing traces are filled with 0. Figure exports are redrawn from the current slice or waveform and do not include the UI theme or window decoration.

## Build the Windows application

Run `build.bat`; the output is:

```text
dist\SeisView\SeisView.exe
```

Keep the version number in `seisview/__init__.py` (`__version__`) and `assets/version_info.txt` (version resource) in sync.

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
