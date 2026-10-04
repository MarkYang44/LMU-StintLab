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

HUD styling, wheel drawing and report rendering are project code. Public `src/tracks/catalog.json` is empty. No RaceCom executable, extracted bytecode, vehicle artwork, circuit PDF, commercial logo, private setup, recorded trajectory or personal racing record is shipped. Demo telemetry is generated mathematically at runtime.
