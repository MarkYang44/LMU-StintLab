"""Black-box check of the shipping EXE; no test code is bundled in the app."""
import ctypes
from ctypes import wintypes
import csv
import json
import os
from pathlib import Path
import subprocess
import time


def close_demo(process,title_expected='LMU Stintrix · DEMO'):
    """Send a normal close only to the synthetic HUD this test launched."""
    if process.poll() is not None:return
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    targets=[]
    @callback_type
    def collect(handle,_):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        if pid.value==process.pid:
            title=ctypes.create_unicode_buffer(256);user.GetWindowTextW(handle,title,len(title))
            if title.value==title_expected:targets.append(handle)
        return True
    if not user.EnumWindows(collect,0) or len(targets)!=1:
        raise RuntimeError('Expected exactly one test-owned DEMO window')
    pid=wintypes.DWORD();user.GetWindowThreadProcessId(targets[0],ctypes.byref(pid))
    if process.poll() is not None or pid.value!=process.pid:
        raise RuntimeError('Test window ownership changed')
    if not user.PostMessageW(targets[0],0x0010,0,0):
        raise ctypes.WinError(ctypes.get_last_error())


def run(bundle,root):
    bundle=Path(bundle).resolve();root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False)
    environment=dict(os.environ,LMU_STINTRIX_DATA_DIR=str(root))
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    menu=subprocess.Popen([str(bundle/'LMU-Stintrix.exe')],cwd=bundle,env=environment,startupinfo=startup,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+20
        while True:
            if menu.poll() is not None:raise RuntimeError('Portable control center failed to start')
            try:close_demo(menu,'LMU Stintrix · 控制中心');break
            except RuntimeError:
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        menu.wait(timeout=15)
        if menu.returncode:raise RuntimeError('Portable control center failed to close')
        idle=not (root/'Logs').exists() and not (root/'DemoLogs').exists()
    finally:
        if menu.poll() is None:menu.terminate();menu.wait(timeout=10)
    process=subprocess.Popen([str(bundle/'LMU-Stintrix.exe'),'--demo'],cwd=bundle,
        env=environment,startupinfo=startup,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+30
        while not list((root/'DemoLogs').glob('*/inputs.csv')):
            if process.poll() is not None:raise RuntimeError('Portable HUD exited before recording')
            if time.monotonic()>deadline:raise RuntimeError('Portable HUD did not start recording')
            time.sleep(.05)
        deadline=time.monotonic()+43
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Portable HUD exited during recording')
            time.sleep(.1)
        close_demo(process);process.wait(timeout=60)
        if process.returncode:raise RuntimeError('Portable HUD failed with exit '+str(process.returncode))
    finally:
        if process.poll() is None:
            try:close_demo(process);process.wait(timeout=15)
            except (OSError,RuntimeError,subprocess.TimeoutExpired):
                process.terminate();process.wait(timeout=15)
    folders=list((root/'DemoLogs').glob('*/session.json'))
    if len(folders)!=1:raise RuntimeError('Expected one synthetic recording')
    folder=folders[0].parent
    required=('inputs.csv','session.json','review.html','fastest_lap_summary.json','fastest_lap.html',
              '圈速单.png','比赛日志.png','race_log.json','race_log.txt','race_images.json','race_events.csv')
    checks={name:(folder/name).is_file() for name in required}
    checks['control_center_starts_without_recording']=idle
    meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    summary=json.loads((folder/'fastest_lap_summary.json').read_text(encoding='utf-8'))
    with (folder/'inputs.csv').open(encoding='utf-8',newline='') as stream:
        rows=sum(1 for _ in csv.DictReader(stream))
    checks.update(normal_shutdown=meta.get('status')=='complete',
        fresh_samples_preserved=rows==meta.get('samples') and rows>1000,
        complete_reference=summary.get('status')=='saved',session_phase_folder='_Race_' in folder.name)
    from library import inventory
    from session_archive import export_session,import_session,_digest
    package=export_session(root,str(folder.relative_to(root)),root/'SessionPackages')
    restored=import_session(root/'archive-test-import',package['path'])
    imported=Path(restored['folder']);items=inventory(root/'archive-test-import')
    checks.update(session_phase_archive='_Race_' in package['path'],
        archive_roundtrip=all(_digest(folder/name)==_digest(imported/name) for name in required),
        archive_in_library=len(items)==1,
        session_phase_inventory=len(items)==1 and items[0]['session_type']=='Race',
        archive_duplicate=import_session(root/'archive-test-import',package['path'])['status']=='skipped')
    result=dict(ok=all(checks.values()),checks=checks,synthetic_only=True,test_code_in_product=False)
    (root.parent/'portable-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['ok']:raise RuntimeError('Portable smoke failed: '+str(checks))
    return result
