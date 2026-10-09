"""Read-only Windows commit/physical headroom for optional background reports."""
import ctypes,os

def headroom():
    if os.name!='nt':return None
    from ctypes import wintypes as W
    class Info(ctypes.Structure):
        _fields_=[('cb',W.DWORD)]+[(name,ctypes.c_size_t) for name in ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable','SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+[(name,W.DWORD) for name in ('HandleCount','ProcessCount','ThreadCount')]
    info=Info();info.cb=ctypes.sizeof(info);api=ctypes.WinDLL('psapi').GetPerformanceInfo
    api.argtypes=[ctypes.POINTER(Info),W.DWORD];api.restype=W.BOOL
    if not api(ctypes.byref(info),info.cb):return None
    return dict(commit_available=(info.CommitLimit-info.CommitTotal)*info.PageSize,physical_available=info.PhysicalAvailable*info.PageSize)

def can_report():
    value=headroom()
    return value is None or value['commit_available']>=512*1048576 and value['physical_available']>=256*1048576
