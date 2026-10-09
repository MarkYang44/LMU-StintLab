"""Short-lived report process: release analysis heaps without touching the HUD."""
import os,subprocess,sys
from pathlib import Path
import threading
from memory_budget import can_report
from storage import atomic_json
_resume_lock=threading.Lock()

class ReportDeferred(RuntimeError):pass

def run(folder,data_root):
    if not can_report():raise ReportDeferred('系统内存紧张，报告等待可用内存；完整记录已保存')
    folder=Path(folder).resolve();environment=dict(os.environ,LMU_STINTRIX_DATA_DIR=str(Path(data_root).resolve()))
    command=[sys.executable]
    if not getattr(sys,'frozen',False):command.append(str(Path(__file__).with_name('inputscope.py')))
    command.extend(['--report-worker',str(folder)])
    options={}
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        options=dict(startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    log=folder/'report_worker.log'
    with log.open('wb') as stream:
        result=subprocess.run(command,env=environment,stdout=stream,stderr=stream,**options)
    if result.returncode==75:raise ReportDeferred('系统内存紧张，报告等待可用内存；完整记录已保存')
    if result.returncode:raise RuntimeError('赛后报告处理失败；原记录已保留，请查看 report_worker.log')
    if log.stat().st_size==0:log.unlink()

def entry(folder):
    folder=Path(folder).resolve()
    from laps import finished_metadata
    finished_metadata(folder)
    from session_reports import make_report
    make_report(folder,isolated=False)


def pending(root):
    return (path for name in ('Logs','DemoLogs','ImportedLogs','RecoveredLogs') for path in (Path(root)/name).glob('*/report_pending.json'))

def resume_pending(root):
    if not can_report() or not _resume_lock.acquire(blocking=False):return 0
    completed=0
    try:
        from session_reports import make_report
        for path in pending(root):
            folder=path.parent.resolve()
            if path.is_symlink() or path.parent.is_symlink() or not folder.is_relative_to(Path(root).resolve()):continue
            import json
            try:meta=json.loads((folder/'session.json').read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):continue
            if meta.get('status') in ('recording','write_error'):continue
            if not can_report():break
            try:make_report(folder,isolated=True)
            except ReportDeferred:break
            except Exception as error:(folder/'report_error.txt').write_text(str(error),encoding='utf-8')
            else:completed+=1
            path.unlink(missing_ok=True)
    finally:_resume_lock.release()
    return completed

def defer(folder,error):
    atomic_json(Path(folder)/'report_pending.json',dict(version=1,status='waiting_for_memory',reason=str(error)))
