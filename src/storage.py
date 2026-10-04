"""Bounded, loss-explicit background CSV writer and non-destructive recovery."""
import csv
import ctypes
from datetime import datetime,timezone
import gzip
import hashlib
import json
import io
import os
from pathlib import Path
import queue
import threading
import time


def atomic_json(path,value):
    path=Path(path);pending=path.with_name(path.name+'.pending')
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');pending.replace(path)


class StorageError(OSError):
    pass


class PackedCSV:
    """Sink accepting complete escaped CSV records, including embedded newlines."""
    def __init__(self,file):self.file=file
    def writerows(self,rows):self.file.write(''.join(rows))


class BatchWriter:
    def __init__(self,folder,columns,capacity=131072,on_checkpoint=None,filename='inputs.csv',checkpoint_name='recording_checkpoint.json'):
        self.folder=Path(folder);self.checkpoint_name=checkpoint_name;self.file=(self.folder/filename).open('w',encoding='utf-8',newline='')
        csv.writer(self.file).writerow(columns);self.csv=PackedCSV(self.file)
        self.encoders=threading.local()
        self.queue=queue.Queue(maxsize=capacity);self.rows=0;self.peak=0;self.error=None;self.closed=False;self.on_checkpoint=on_checkpoint
        try:self.checkpoint()
        except Exception as e:
            self.file.close();raise StorageError('无法创建记录检查点：'+str(e)) from e
        self.thread=threading.Thread(target=self.run,name='InputScope CSV writer',daemon=False);self.thread.start()

    def checkpoint(self):
        self.file.flush();os.fsync(self.file.fileno())
        atomic_json(self.folder/self.checkpoint_name,dict(version=1,pid=os.getpid(),rows=self.rows,
            committed_bytes=os.fstat(self.file.fileno()).st_size,closed=self.closed,
            updated_utc=datetime.now(timezone.utc).isoformat()))
        if self.on_checkpoint:self.on_checkpoint()

    def add(self,row):
        if self.error:raise StorageError('后台写盘失败：'+self.error)
        if self.closed:raise StorageError('记录已关闭')
        if not hasattr(self.encoders,'buffer'):
            self.encoders.buffer=io.StringIO(newline='');self.encoders.writer=csv.writer(self.encoders.buffer)
        buffer=self.encoders.buffer;buffer.seek(0);buffer.truncate(0)
        self.encoders.writer.writerow(row)
        try:self.queue.put_nowait(buffer.getvalue())
        except queue.Full:raise StorageError('写盘队列已满；停止该段记录，未静默丢弃采样') from None
        self.peak=max(self.peak,self.queue.qsize())

    def run(self):
        last=time.monotonic()
        try:
            while True:
                try:item=self.queue.get(timeout=.2)
                except queue.Empty:
                    if time.monotonic()-last>=1:self.checkpoint();last=time.monotonic()
                    continue
                if item is None:break
                batch=[item];stop=False
                for _ in range(1023):
                    try:next_item=self.queue.get_nowait()
                    except queue.Empty:break
                    if next_item is None:stop=True;break
                    batch.append(next_item)
                self.csv.writerows(batch);self.rows+=len(batch)
                if time.monotonic()-last>=1:self.checkpoint();last=time.monotonic()
                if stop:break
            self.closed=True;self.checkpoint()
        except Exception as e:
            self.error=str(e);self.closed=True
        finally:self.file.close()

    def finish(self):
        if self.thread.is_alive():
            while self.thread.is_alive():
                try:self.queue.put(None,timeout=.2);break
                except queue.Full:continue
            self.thread.join()
        if self.error:raise StorageError('后台写盘失败：'+self.error)
        return dict(written_rows=self.rows,peak_queue_rows=self.peak)


def process_alive(pid):
    if os.name!='nt':
        return (Path('/proc')/str(pid)).exists() if Path('/proc').exists() else True
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return ctypes.get_last_error()==5
    try:
        code=ctypes.c_ulong();return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(handle)


def recover_session(source,root):
    source=Path(source).resolve();root=Path(root).resolve()
    if not source.is_relative_to(root):raise ValueError('只恢复本插件目录中的记录')
    checkpoint=json.loads((source/'recording_checkpoint.json').read_text(encoding='utf-8'))
    metadata=json.loads((source/'session.json').read_text(encoding='utf-8'))
    if checkpoint.get('version')!=1 or metadata.get('status')!='recording':
        raise ValueError('该场次不属于中断记录')
    if process_alive(checkpoint['pid']):raise ValueError('记录进程仍在运行，不能恢复')
    limit=checkpoint['committed_bytes'];size=(source/'inputs.csv').stat().st_size
    if not isinstance(limit,int) or not 0<limit<=size:raise ValueError('恢复检查点无效')
    folder=root/'RecoveredLogs'/('Recovered_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir(parents=True)
    remaining=limit
    with (source/'inputs.csv').open('rb') as f,(folder/'inputs.csv').open('wb') as out:
        while remaining:
            b=f.read(min(1048576,remaining))
            if not b:raise OSError('源记录在恢复时变短，请保留原文件后重试')
            out.write(b);remaining-=len(b)
    metadata.update(status='recovered',end_reason='recovered after interrupted recording',
        recovery_source=str(source),recovered_committed_bytes=limit,uncommitted_tail_bytes=size-limit,
        samples=checkpoint['rows'],ended_utc=checkpoint['updated_utc'])
    extra=source/'vehicle_checkpoint.json'
    if extra.exists() and (source/'vehicle.csv').exists():
        committed=json.loads(extra.read_text(encoding='utf-8'));limit=committed.get('committed_bytes')
        if not isinstance(limit,int) or not 0<limit<=(source/'vehicle.csv').stat().st_size:raise ValueError('附加遥测检查点无效')
        with (source/'vehicle.csv').open('rb') as f,(folder/'vehicle.csv').open('wb') as out:
            remaining=limit
            while remaining:
                chunk=f.read(min(1048576,remaining))
                if not chunk:raise OSError('附加遥测源记录变短')
                out.write(chunk);remaining-=len(chunk)
        metadata['vehicle_recovered_samples']=committed.get('rows')
    events=source/'race_events.csv';event_checkpoint=source/'race_events_checkpoint.json'
    if events.exists() and event_checkpoint.exists():
        committed=json.loads(event_checkpoint.read_text(encoding='utf-8'));limit=committed.get('committed_bytes')
        if not isinstance(limit,int) or not 0<limit<=events.stat().st_size:raise ValueError('赛事事件检查点无效')
        with events.open('rb') as stream,(folder/'race_events.csv').open('wb') as out:
            remaining=limit
            while remaining:
                chunk=stream.read(min(1048576,remaining))
                if not chunk:raise OSError('赛事事件源记录变短')
                out.write(chunk);remaining-=len(chunk)
        # Incomplete sessions have no final summary. Recover availability only,
        # rather than treating their observed positions as a final result.
        atomic_json(folder/'race_summary.json',dict(version=1,available=bool(metadata.get('race_journal',{}).get('scoring_available')),
            recovered=True,finish_flag=0,note='中断记录；只恢复检查点之前的事件。'))
    atomic_json(folder/'session.json',metadata)
    return folder


def compress_session(folder):
    """Create and verify a gzip backup, leaving every original byte untouched."""
    folder=Path(folder);source=folder/'inputs.csv';target=folder/'inputs.csv.gz';pending=folder/'inputs.csv.gz.pending'
    meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if meta.get('status')=='recording':raise ValueError('请等记录结束后再压缩')
    sha=hashlib.sha256()
    with source.open('rb') as f,gzip.open(pending,'wb',compresslevel=6) as out:
        for b in iter(lambda:f.read(1048576),b''):sha.update(b);out.write(b)
    check=hashlib.sha256()
    with gzip.open(pending,'rb') as f:
        for b in iter(lambda:f.read(1048576),b''):check.update(b)
    if sha.digest()!=check.digest():raise OSError('压缩校验失败')
    pending.replace(target)
    result=dict(source_sha256=sha.hexdigest(),source_bytes=source.stat().st_size,
        compressed_bytes=target.stat().st_size,original_retained=True)
    atomic_json(folder/'compression.json',result);return result
