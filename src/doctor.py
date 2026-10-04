"""Fast environment validation without starting a game, HUD or recording."""
import ctypes
import importlib.metadata
import json
import struct
import sys
import tempfile
from paths import ASSETS,data_directory,discover_game

def check():
    tests={}
    tests['windows_64_bit']=sys.platform=='win32' and struct.calcsize('P')==8
    tests['python_supported']=sys.version_info[:2]==(3,13)
    try:
        import tkinter
        t=tkinter.Tcl();tests['tk']=bool(t.eval('info patchlevel'));del t
    except Exception:tests['tk']=False
    try:
        import duckdb
        tests['duckdb']=duckdb.connect(':memory:').execute('select 42').fetchone()==(42,)
    except ImportError:tests['duckdb']=False
    from pyLMUSharedMemory.lmu_data import LMUObjectOut
    tests['sdk_layout']=ctypes.sizeof(LMUObjectOut)==324820 and LMUObjectOut.telemetry.offset==128464
    tests['offline_assets']=all((ASSETS/name).is_file() for name in ('report.html','compare.html','trackview.js','laplab.js','vehicleview.js','enduranceview.js','tracks/catalog.json'))
    root=data_directory()
    try:
        root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as f:f.write(b'check')
        tests['writable_data']=True
    except OSError:tests['writable_data']=False
    game=discover_game()
    return dict(ok=all(tests.values()),checks=tests,game_detected=game is not None,
        note='Game detection is optional; LMU_Data is read only. No game files were modified.',
        python=sys.version.split()[0],data_directory=str(root),version='0.1.0')
