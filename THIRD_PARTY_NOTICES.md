# Third-party notices

## pyLMUSharedMemory

Source: [TinyPedal/pyLMUSharedMemory](https://github.com/TinyPedal/pyLMUSharedMemory), commit `6cef58e22bf025268acee93e9e5ea4f569939c1b`.

Copyright (c) 2021 Tony Whitley; Copyright (c) 2025 Xiang. MIT license; full text included at `src/pyLMUSharedMemory/License.txt` and in portable distributions. This SDK exposes LMU's memory layout. Game trademarks remain the property of their owners. No game binaries are redistributed.

## Runtime and build dependencies

| Component | License | Role |
| --- | --- | --- |
| [CPython](https://github.com/python/cpython) | PSF / historical Python licenses | Embedded interpreter in portable builds |
| [Tcl/Tk](https://github.com/tcltk/tcl) | Tcl/Tk permissive licenses | Native HUD |
| [DuckDB](https://github.com/duckdb/duckdb) | MIT | Read-only native telemetry import |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | GPL-2.0-or-later with bootloader exception | Packaging; exception permits independent licensing of bundled apps |
| altgraph | MIT | Build dependency |
| packaging | Apache-2.0 / BSD-2-Clause | Build dependency |
| pefile | MIT | Build dependency |
| pyinstaller-hooks-contrib | GPL-2.0-or-later / Apache-2.0 for hooks | Build dependency |
| pywin32-ctypes | BSD-3-Clause | Build dependency |
| setuptools | MIT | Build dependency |

Installed distributions' license and notice files are copied into `licenses/` in the portable ZIP. `build-manifest.json` records versions and file checksums. The exact dependency versions are in `requirements-lock.txt`.

## Assets

HUD styling, wheel drawing and report rendering are project code. Public `src/tracks/catalog.json` is empty. No RaceCom executable, extracted bytecode, private RaceCom vehicle artwork, circuit PDF, private setup, recorded trajectory or personal racing record is shipped. Demo telemetry is generated mathematically at runtime.

At the project owner's request, `src/branding/gtd.ico` and `gtd-menu.png` are exact copies of `static/icons/favicon.ico` and `static/icons/character-icon-128x128.png` from [MarkYang44/GTD](https://github.com/MarkYang44/GTD). The latter is used in GTD's menu. Build-time extraction preserves the original six icon frames; the publication audit verifies both reviewed assets by SHA-256. This use does not assert ownership of the depicted character or grant rights to other GTD assets.

The charcoal, warm off-white and yellow-green palettes reference [MarkYang44/Endfield-Charge](https://github.com/MarkYang44/Endfield-Charge), particularly its `HUDView.swift` and `SettingsWindowController.swift` colours. The StintLab widgets and short transitions are independently implemented. Endfield branding artwork and code are not copied. StintLab is not affiliated with Arknights: Endfield or its rights holders; underlying trademarks remain with their respective owners.

## GTD circuit guide and car catalog

At the project owner's request, the editorial GTD guide snapshot `2026.09.22.1` is adapted into an independent StintLab offline interface. The 18 circuits, 24 cars, 144 recommendations, source notes, dates, and unverified build-evidence markers retain their original meaning. GTD is credited to [MarkYang44/GTD](https://github.com/MarkYang44/GTD). GTD download services, backend dependencies and user preferences are not imported.

The 42 WebP images are exact copies of GTD's existing public guide artwork from Le Mans Ultimate / Studio 397. Original official image URLs and page links are retained in `src/guide/provenance.json`; each reviewed asset has an exact SHA256 allowlist entry in `tools/guide_assets.py`. Those artworks and trademarks remain with their respective rights holders; the StintLab source license does not assert ownership of them. Private RaceCom artwork and personal racing records remain excluded.
