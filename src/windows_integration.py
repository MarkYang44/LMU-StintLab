"""Per-user Unicode Shell links and asynchronous application catalog verification.

API: https://learn.microsoft.com/en-us/windows/win32/shell/links
"""
import ctypes as C
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from paths import APP_ROOT

DESCRIPTION='LMU StintLab | Local telemetry, HUD and lap analysis'
APP_ID='LMU.StintLab.Desktop'


def executable():
    path=Path(sys.executable) if getattr(sys,'frozen',False) else APP_ROOT/'LMU-StintLab.exe'
    if not path.is_file() or path.name.casefold()!='lmu-stintlab.exe':
        raise ValueError('请先下载并完整解压 Windows 便携版，再添加开始菜单入口')
    return path.resolve()


def shortcut_path():
    appdata=os.environ.get('APPDATA')
    if not appdata:raise OSError('Windows 未提供当前用户的开始菜单目录')
    return Path(appdata)/'Microsoft/Windows/Start Menu/Programs/LMU StintLab.lnk'


def guid(value):return (C.c_ubyte*16).from_buffer_copy(uuid.UUID(value).bytes_le)


def checked(result):
    if result<0:raise OSError(f'Windows Shell link HRESULT 0x{result & 0xffffffff:08X}')


class ShellLink:
    """Scoped IShellLinkW and IPersistFile; every COM reference is released."""
    def __enter__(self):
        self.shell=C.c_void_p();self.file=C.c_void_p();self.initialized=False
        self.ole=C.WinDLL('ole32');self.ole.CoInitializeEx.argtypes=[C.c_void_p,C.c_uint]
        self.ole.CoInitializeEx.restype=C.c_long
        result=self.ole.CoInitializeEx(None,2)
        if result not in (0,1,-2147417850):checked(result)
        self.initialized=result in (0,1)
        self.ole.CoCreateInstance.argtypes=[C.c_void_p,C.c_void_p,C.c_uint,C.c_void_p,C.c_void_p]
        self.ole.CoCreateInstance.restype=C.c_long
        try:
            clsid=guid('00021401-0000-0000-C000-000000000046')
            iid=guid('000214F9-0000-0000-C000-000000000046')
            checked(self.ole.CoCreateInstance(C.byref(clsid),None,1,C.byref(iid),C.byref(self.shell)))
            persist=guid('0000010b-0000-0000-C000-000000000046')
            self.call(self.shell,0,(C.c_void_p,C.c_void_p),C.byref(persist),C.byref(self.file))
        except BaseException:self.__exit__(None,None,None);raise
        return self
    @staticmethod
    def call(pointer,index,types,*args):
        table=C.cast(pointer,C.POINTER(C.POINTER(C.c_void_p))).contents
        result=C.WINFUNCTYPE(C.c_long,C.c_void_p,*types)(table[index])(pointer,*args)
        checked(result);return result
    def __exit__(self,*_):
        for pointer in (self.file,self.shell):
            if pointer.value:self.call(pointer,2,());pointer.value=None
        if self.initialized:self.ole.CoUninitialize();self.initialized=False
    def text(self,index):
        buffer=C.create_unicode_buffer(32768)
        self.call(self.shell,index,(C.c_void_p,C.c_int),buffer,len(buffer))
        return buffer.value
    def load(self,path):self.call(self.file,5,(C.c_wchar_p,C.c_uint),str(path),0)
    def save(self,path):self.call(self.file,6,(C.c_wchar_p,C.c_int),str(path),1)
    def read(self):
        buffer=C.create_unicode_buffer(32768)
        self.call(self.shell,3,(C.c_void_p,C.c_int,C.c_void_p,C.c_uint),buffer,len(buffer),None,4)
        return dict(target=buffer.value,directory=self.text(8),description=self.text(6))
    def configure(self,target):
        for index,value in ((20,str(target)),(9,str(target.parent)),(7,DESCRIPTION),(11,'')):
            self.call(self.shell,index,(C.c_wchar_p,),value)
        self.call(self.shell,17,(C.c_wchar_p,C.c_int),str(target),0)
        self.call(self.shell,15,(C.c_int,),1)
        # PKEY_AppUserModel_ID matches the EXE's taskbar identity.
        class PropertyKey(C.Structure):_fields_=[('fmtid',C.c_ubyte*16),('pid',C.c_uint)]
        class VariantData(C.Union):_fields_=[('text',C.c_wchar_p),('padding',C.c_ubyte*16)]
        class Variant(C.Structure):_fields_=[('vt',C.c_ushort),('reserved',C.c_ushort*3),('data',VariantData)]
        iid=guid('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99');store=C.c_void_p()
        self.call(self.shell,0,(C.c_void_p,C.c_void_p),C.byref(iid),C.byref(store))
        try:
            key=PropertyKey(guid('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3'),5)
            value=Variant();value.vt=31;value.data.text=APP_ID
            self.call(store,6,(C.c_void_p,C.c_void_p),C.byref(key),C.byref(value))
            self.call(store,7,())
        finally:self.call(store,2,())


def inspect(path):
    with ShellLink() as link:link.load(path);return link.read()


def notify_path(path,event):
    """Notify the real file event, not the unrelated icon-association event."""
    notify=C.WinDLL('shell32').SHChangeNotify
    notify.argtypes=[C.c_long,C.c_uint,C.c_void_p,C.c_void_p]
    value=C.create_unicode_buffer(str(path))
    # SHCNF_PATHW | SHCNF_FLUSH: retain the string until delivery completes.
    notify(event,0x1005,C.cast(value,C.c_void_p),None)


def catalog_entry(target):
    """Read the current user's Start application catalog, without a console."""
    script=r'''
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$items=@(Get-StartApps | Where-Object { $_.AppID -eq $env:STINTLAB_EXPECTED_ID -or $_.AppID -eq $env:STINTLAB_EXPECTED_EXE })
ConvertTo-Json -InputObject $items -Compress
'''
    command=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    environment=dict(os.environ,STINTLAB_EXPECTED_ID=APP_ID,STINTLAB_EXPECTED_EXE=str(target))
    powershell=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result=subprocess.run([str(powershell),'-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',command],
            capture_output=True,env=environment,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:return None
        items=json.loads(result.stdout.decode('utf-8-sig'))
        return items[0] if isinstance(items,list) and items else None
    except (OSError,ValueError,subprocess.TimeoutExpired):return None


def needs_repair():
    """Repair only an already-enabled link pointing to this exact portable EXE.

    Source tests and temporary bundles must never replace the installed entry.
    Running the real menu repeats registration in the logged-in user's context.
    """
    if os.name!='nt' or not getattr(sys,'frozen',False):return False
    try:
        path=shortcut_path()
        if not path.is_file():return False
        info=inspect(path)
        if info['description']!=DESCRIPTION or Path(info['target'])!=executable():return False
    except (OSError,ValueError,AttributeError):return False
    try:
        from paths import data_directory
        previous=json.loads((data_directory()/'desktop_registration.json').read_text(encoding='utf-8'))
        return not (previous.get('recognized') and previous.get('revision')==2 and previous.get('target')==str(executable())
                    and previous.get('user')==os.getlogin() and previous.get('link_mtime_ns')==path.stat().st_mtime_ns)
    except (OSError,ValueError,AttributeError):return True


def register(remove=False,verify=False):
    """Validate ownership, then stage and verify before replacing our own link."""
    if os.name!='nt':raise OSError('开始菜单入口仅适用于 Windows')
    target=executable();path=shortcut_path()
    if path.exists() and inspect(path)['description']!=DESCRIPTION:
        raise OSError('同名快捷方式属于其他应用，未修改；请先在开始菜单检查名称')
    if remove:
        path.unlink(missing_ok=True)
        notify_path(path,4)  # SHCNE_DELETE
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        pending=path.with_name('StintLab-'+uuid.uuid4().hex+'.lnk')
        try:
            with ShellLink() as link:link.configure(target);link.save(pending)
            stored=inspect(pending)
            if Path(stored['target'])!=target or Path(stored['directory'])!=target.parent or stored['description']!=DESCRIPTION:
                raise OSError('Windows 快捷方式校验失败，原入口保留')
            pending.replace(path)
        finally:pending.unlink(missing_ok=True)
        notify_path(path,2)  # SHCNE_CREATE
        notify_path(path,0x2000)  # SHCNE_UPDATEITEM
    notify_path(path.parent,0x1000)  # SHCNE_UPDATEDIR
    result=dict(path=str(path),target=str(target),removed=bool(remove))
    if verify:
        entry=None if remove else catalog_entry(target)
        result.update(recognized=bool(entry),entry=entry,revision=2)
        try:result['user']=os.getlogin()
        except OSError:result['user']=None
        result['link_mtime_ns']=path.stat().st_mtime_ns if path.exists() else None
        from paths import data_directory
        from storage import atomic_json
        atomic_json(data_directory()/'desktop_registration.json',result)
    return result
