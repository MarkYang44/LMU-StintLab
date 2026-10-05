"""CLI entry point and compatibility exports for existing StintLab integrations.

Collection, recording and presentation live in independent modules. The public
class/function names remain available here; patch their owning modules in tests.
"""
import ctypes
import json
import sys
import time
from app_config import ASSETS, ROOT, COLORS, INPUT_CHANNELS, COLUMNS, EXTRA_COLUMNS, POLL_HZ, DRAW_HZ
from engine import Engine
from recorder import Recorder
from telemetry import SharedReader, decode, extract
from session_reports import make_report, render_review
from hud_geometry import WheelDisplay, hud_layout, pedal_fill, rotate_wheel, steering_angle, reduce_trace
from sampling import (DEFAULTS, PRESETS, AdaptiveSampler, PreciseWait, FrameDeadline, drawing_rate,
                      load_settings, save_settings, validate_settings)
from telemetry_import import import_recording


def __getattr__(name):
    # Keep core imports and command-line analysis free of Tk until it is needed.
    if name in {'App', 'tk', 'filedialog', 'messagebox'}:
        import hud
        value = getattr(hud, name)
        globals()[name] = value
        return value
    raise AttributeError(name)


def main():
    if '--version' in sys.argv:
        print('LMU StintLab 0.1.10');return
    if '--race-images' in sys.argv:
        index=sys.argv.index('--race-images')
        if index+1>=len(sys.argv):raise ValueError('--race-images 后需要已结束的赛事目录')
        from race_report import generate
        generate(sys.argv[index+1]);return
    if '--import-duckdb' in sys.argv:
        index=sys.argv.index('--import-duckdb')
        if index+1>=len(sys.argv):raise ValueError('--import-duckdb 后需要已结束的 .duckdb 文件路径')
        folder=import_recording(sys.argv[index+1],ROOT)
        make_report(folder)
        (ROOT/'last_native_import.json').write_text(json.dumps({'folder':str(folder)},ensure_ascii=False),encoding='utf-8')
        return
    # Keep the high-rate reader from holding Python's GIL for the default 5 ms
    # timeslice while the GUI is trying to draw a submillisecond frame.
    sys.setswitchinterval(0.0005)
    from branding import taskbar
    taskbar()
    # Opt in before creating Tk windows; render to real pixels instead of bitmap scaling.
    dpi = ctypes.WinDLL('user32', use_last_error=True)
    try:
        dpi.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if not dpi.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            dpi.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            dpi.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            dpi.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        dpi.SetProcessDPIAware()
    timer = ctypes.WinDLL('winmm')
    requested = timer.timeBeginPeriod(1) == 0
    try:
        if any(flag in sys.argv for flag in ('--hud','--demo','--clean','--clean-controls')):
            from hud import App
            App('--demo' in sys.argv, clean='--clean' in sys.argv,
                clean_controls='--clean-controls' in sys.argv).root.mainloop()
        else:
            from control_center import ControlCenter
            ControlCenter().root.mainloop()
    finally:
        if requested:
            timer.timeEndPeriod(1)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (ROOT / 'startup_error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
