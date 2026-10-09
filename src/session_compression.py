"""Transparent per-file Windows compression; original paths and bytes survive."""
import ctypes,hashlib,json,os,subprocess
from pathlib import Path
from storage import atomic_json,process_alive
import reporting

TEXT={'.csv','.json','.html','.svg','.txt'}
MIN_BYTES=65536
LOCK='.storage_compression.pending'

def enabled(root):
    try:return json.loads((Path(root)/'storage_settings.json').read_text(encoding='utf-8')).get('auto_compress',True) is True
    except (OSError,ValueError,AttributeError):return True

def physical_size(path):
    if os.name!='nt':return Path(path).stat().st_size
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    fn=kernel.GetCompressedFileSizeW;fn.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulong)];fn.restype=ctypes.c_ulong
    high=ctypes.c_ulong();ctypes.set_last_error(0);low=fn(str(Path(path).resolve()),ctypes.byref(high))
    if low==0xffffffff and ctypes.get_last_error():raise ctypes.WinError(ctypes.get_last_error())
    return (high.value<<32)|low

def ntfs(path):
    if os.name!='nt':return False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    volume=ctypes.create_unicode_buffer(32768);filesystem=ctypes.create_unicode_buffer(32)
    kernel.GetVolumePathNameW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_ulong]
    kernel.GetVolumeInformationW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_ulong]
    if not kernel.GetVolumePathNameW(str(Path(path).resolve()),volume,len(volume)):return False
    return bool(kernel.GetVolumeInformationW(volume.value,None,0,None,None,None,filesystem,len(filesystem))) and filesystem.value=='NTFS'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

@reporting.serialized
def compress(folder):
    folder=Path(folder)
    if folder.is_symlink() or folder.is_junction():raise ValueError('记录路径无效')
    folder=folder.resolve()
    metadata=json.loads((folder/'session.json').read_text(encoding='utf-8-sig'))
    if metadata.get('status') not in ('finished','complete','completed','recovered','imported'):
        raise ValueError('请等记录完整保存后再压缩')
    if not ntfs(folder):return dict(supported=False,files=[],saved_bytes=0,errors=[])
    lock=folder/LOCK
    if lock.exists():
        try:pid=json.loads(lock.read_text(encoding='utf-8'))['pid']
        except (OSError,ValueError,KeyError):raise ValueError('压缩锁无效，请稍后重试') from None
        if process_alive(pid):raise ValueError('该赛事正在压缩，请稍后重试')
        lock.unlink()
    result=dict(version=1,method='Windows per-file LZX',supported=True,files=[],saved_bytes=0,errors=[])
    with lock.open('x',encoding='utf-8') as out:json.dump({'pid':os.getpid()},out)
    try:
        executable=str(Path(os.environ['SystemRoot'])/'System32'/'compact.exe')
        candidates=[]
        for file in folder.rglob('*'):
            if file.is_symlink() or file.is_junction() or not file.resolve().is_relative_to(folder):
                raise ValueError('赛事包含链接，不能压缩')
            if file.is_file() and file.suffix.lower() in TEXT and file.name!='storage_compression.json' and file.stat().st_size>=MIN_BYTES:
                candidates.append(file)
        for file in sorted(candidates):
            try:
                stat=file.stat();before=physical_size(file);sha=digest(file)
                child=subprocess.run([executable,'/c','/exe:LZX','/q',str(file)],capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS,timeout=180)
                after=physical_size(file);check=file.stat()
                if stat.st_size!=check.st_size or stat.st_mtime_ns!=check.st_mtime_ns or sha!=digest(file):
                    raise OSError('压缩期间记录内容发生变化')
                if child.returncode:raise OSError('Windows compact returned '+str(child.returncode))
                entry=dict(file=file.relative_to(folder).as_posix(),logical_bytes=stat.st_size,
                    physical_bytes=after,sha256=sha,saved_bytes=max(0,before-after))
                result['files'].append(entry);result['saved_bytes']+=entry['saved_bytes']
            except (OSError,subprocess.SubprocessError) as error:
                result['errors'].append(dict(file=file.relative_to(folder).as_posix(),error=str(error)))
        atomic_json(folder/'storage_compression.json',result)
        return result
    finally:lock.unlink(missing_ok=True)

def after_report(folder):
    """Best effort after all writers/generators finish, never on the sample thread."""
    folder=Path(folder)
    if not enabled(folder.parent.parent):return
    try:compress(folder)
    except (OSError,ValueError) as error:
        (folder/'storage_compression_error.txt').write_text(str(error),encoding='utf-8')
