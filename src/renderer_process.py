"""Quiet, bounded renderer execution, including PyInstaller child processes."""
import ctypes as C
import os
import subprocess
from paths import data_directory


class Basic(C.Structure):
    _fields_=[('process_time',C.c_int64),('job_time',C.c_int64),('flags',C.c_uint32),
        ('minimum',C.c_size_t),('maximum',C.c_size_t),('active',C.c_uint32),
        ('affinity',C.c_size_t),('priority',C.c_uint32),('scheduling',C.c_uint32)]

class IO(C.Structure):_fields_=[(name,C.c_uint64) for name in ('reads','writes','other','read_bytes','write_bytes','other_bytes')]

class Limits(C.Structure):
    _fields_=[('basic',Basic),('io',IO),('process_memory',C.c_size_t),('job_memory',C.c_size_t),
        ('peak_process',C.c_size_t),('peak_job',C.c_size_t)]


def run(args,cwd,timeout=60):
    startup=None;kernel=None;job=None
    if os.name=='nt':
        # Null standard handles: windowed original builds cannot print Chinese
        # into a Windows cp1252 pipe. No console or success dialog is needed.
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESTDHANDLES
        startup.hStdInput=startup.hStdOutput=startup.hStdError=0
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[C.c_void_p,C.c_wchar_p];kernel.CreateJobObjectW.restype=C.c_void_p
        kernel.SetInformationJobObject.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_uint32]
        kernel.AssignProcessToJobObject.argtypes=[C.c_void_p,C.c_void_p]
        kernel.CloseHandle.argtypes=[C.c_void_p]
        job=kernel.CreateJobObjectW(None,None);limits=Limits();limits.basic.flags=0x2000
        if job and not kernel.SetInformationJobObject(job,9,C.byref(limits),C.sizeof(limits)):
            kernel.CloseHandle(job);job=None
    process=None
    try:
        temporary=data_directory()/'_renderer_temp';temporary.mkdir(parents=True,exist_ok=True)
        process=subprocess.Popen(args,cwd=cwd,startupinfo=startup,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1',TMP=str(temporary),TEMP=str(temporary)))
        if job and not kernel.AssignProcessToJobObject(job,int(process._handle)):
            kernel.CloseHandle(job);job=None
        try:return process.wait(timeout)
        except subprocess.TimeoutExpired:
            if job:kernel.CloseHandle(job);job=None
            else:process.kill()
            process.wait(timeout=10)
            raise RuntimeError('RaceCom 生成器超时；已结束本次生成任务，原始记录保留') from None
    finally:
        if job:kernel.CloseHandle(job)
