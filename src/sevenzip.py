"""Pinned small 7zr process: no DLLs, no extraction to archive-provided paths."""
from contextlib import contextmanager
from functools import lru_cache
import hashlib,json,os,subprocess,tempfile
from pathlib import Path
from types import SimpleNamespace
from paths import APP_ROOT,ASSETS

VERSION='26.04'
SHA256='256feca8e274e5da655e2a284fabafd9f554365eb164862089dacd4e8276d282'
URL='https://github.com/ip7z/7zip/releases/download/'+VERSION+'/7zr.exe'
MAX_LIST=32*1024**2

@lru_cache(maxsize=4)
def _trusted(path,mtime,size):return hashlib.sha256(Path(path).read_bytes()).hexdigest()==SHA256
def executable():
    for path in (ASSETS/'tools/7zr.exe',APP_ROOT/'_local/dependencies/7zip'/VERSION/'7zr.exe'):
        if path.is_file():
            stat=path.stat()
            if _trusted(str(path),stat.st_mtime_ns,stat.st_size):return str(path)
            raise ValueError('7z 工具校验失败，请重新运行 Setup.cmd')
    raise ValueError('缺少 7z 工具，请运行 Setup.cmd；便携版请保留完整 _internal 文件夹')
def flags():
    return subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name=='nt' else 0
def run(args,cwd,timeout=900):
    with tempfile.TemporaryFile(dir=cwd) as log:
        child=subprocess.run([executable(),*args],cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
            creationflags=flags(),timeout=timeout)
        length=log.tell()
        if child.returncode:
            log.seek(max(0,length-4096));raise ValueError('7z 操作失败：'+log.read().decode('utf-8',errors='replace'))
        if length>MAX_LIST:raise ValueError('7z 文件列表过大')
        log.seek(0);return log.read().decode('utf-8',errors='strict')

def create(package,folder,files,manifest,work):
    listing=work/'files.txt'
    listing.write_text('\n'.join('./'+name for name in files)+'\n',encoding='utf-8')
    # Independent blocks give bounded, direct single-file reads and no huge solid
    # dictionary. All inputs are validated relative files in one plugin session.
    options=['a','-t7z','-mx=5','-m0=LZMA2:d=8m','-mmt=1','-ms=off','-sccUTF-8','-scsUTF-8','-bd','-bb0','-sse','-ssp','-spd','-spf']
    run([*options,str(package),'@'+str(listing)],folder)
    (work/'manifest.json').write_text(manifest,encoding='utf-8')
    run([*options,str(package),'--','manifest.json'],work)

class Reader:
    """Flat 7z payload presented as the existing manifest + session/ ZIP API."""
    def __init__(self,path,work):
        self.path=Path(path).resolve();self.work=Path(work);self._raw={};self._infos=[]
        output=run(['l','-slt','-ba','-sccUTF-8','-bd','--',str(self.path)],self.work,120)
        for block in output.replace('\r\n','\n').strip().split('\n\n'):
            if not block.strip():continue
            fields={}
            for line in block.splitlines():
                if ' = ' not in line:raise ValueError('7z 文件列表无效')
                key,value=line.split(' = ',1)
                if key in fields:raise ValueError('7z 文件列表包含重复字段')
                fields[key]=value
            raw=fields.get('Path','');name=raw.replace(chr(92),'/')
            if name.startswith('./'):name=name[2:]
            # The exact exported layout is flat. Also support an ordinary 7z
            # conversion of a legacy session/ ZIP without touching its manifest.
            mapped=name
            if mapped in self._raw:raise ValueError('7z 包含重复路径')
            if any(key in fields for key in ('Symbolic Link','Hard Link')) or 'L' in fields.get('Attributes',''):
                raise ValueError('7z 包含链接，不能导入')
            try:size=int(fields['Size'])
            except (KeyError,ValueError):raise ValueError('7z 文件大小无效') from None
            if size<0:raise ValueError('7z 文件大小无效')
            directory=fields.get('Folder')=='+' or 'D' in fields.get('Attributes','')
            info=SimpleNamespace(filename=mapped,file_size=size,external_attr=0,flag_bits=1 if fields.get('Encrypted')=='+' else 0,
                compress_type=0,is_dir=lambda value=directory:value)
            if directory:
                from session_archive import _safe_path
                _safe_path(name.rstrip('/'));continue
            self._infos.append(info);self._raw[mapped]=raw
        manifest=next((info for info in self._infos if info.filename=='manifest.json'),None)
        if manifest is None or manifest.file_size>8*1024**2:raise ValueError('不是有效的 Stintrix 比赛包')
        header=json.loads(self.read(manifest).decode('utf-8'))
        if not isinstance(header,dict):raise ValueError('比赛包清单无效')
        flat=header.get('container_layout')=='flat' or any(info.filename!='manifest.json' and not info.filename.startswith('session/') for info in self._infos)
        mapping={}
        for info in self._infos:
            old=info.filename;new='session/'+old if flat and old!='manifest.json' else old
            if new in mapping:raise ValueError('7z 包含重复路径')
            mapping[new]=self._raw[old];info.filename=new
        self._raw=mapping
    def infolist(self):return self._infos
    def read(self,info):
        with self.open(info.filename) as source:
            value=source.read(info.file_size+1)
            if len(value)!=info.file_size:raise ValueError('7z 文件大小不一致')
            return value
    @contextmanager
    def open(self,name):
        # stdout only: archive paths are never passed to filesystem extraction.
        with tempfile.TemporaryFile(dir=self.work) as errors:
            child=subprocess.Popen([executable(),'x','-so','-sccUTF-8','-bd','-bb0','-mmt=1','-spd',
                '--',str(self.path),self._raw[name]],cwd=self.work,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors,creationflags=flags())
            try:
                yield child.stdout
                child.stdout.close();code=child.wait(timeout=30)
                if code:
                    errors.seek(0);raise ValueError('7z 解压失败：'+errors.read(4096).decode('utf-8',errors='replace'))
            finally:
                child.stdout.close()
                if child.poll() is None:child.terminate();child.wait(timeout=10)
