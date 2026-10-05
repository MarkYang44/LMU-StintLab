"""One identity for Explorer, taskbar, title bars and the control center."""
import ctypes
from paths import APP_ROOT,ASSETS


def directory():
    packaged=ASSETS/'branding'
    return packaged if (packaged/'stintlab.ico').is_file() else APP_ROOT/'_local/branding'


def apply(root):
    import tkinter as tk
    folder=directory()
    try:
        images=[tk.PhotoImage(master=root,file=str(folder/f'stintlab-{n}.png')) for n in (32,48,64,128)]
        root.iconphoto(True,*images);root._brand_images=images
        root.iconbitmap(str(folder/'stintlab.ico'))
    except (OSError,tk.TclError):pass


def taskbar():
    if hasattr(ctypes,'WinDLL'):
        try:
            shell=ctypes.WinDLL('shell32');shell.SetCurrentProcessExplicitAppUserModelID.argtypes=[ctypes.c_wchar_p]
            shell.SetCurrentProcessExplicitAppUserModelID('LMU.StintLab.Desktop')
        except (OSError,AttributeError):pass
