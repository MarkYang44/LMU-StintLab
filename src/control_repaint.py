"""Coalesced native repaint after menu moves and restores."""
import ctypes
import tkinter as tk


class Presentation:
    def __init__(self,root):
        self.root=root;self.job=None;self.user=None;self.hwnd=None;self.position=None
        if hasattr(ctypes,'WinDLL'):
            try:
                user=ctypes.WinDLL('user32',use_last_error=True)
                user.RedrawWindow.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
                user.RedrawWindow.restype=ctypes.c_bool
                root.update_idletasks()
                # Only this menu's client area; no desktop, other apps or HUDs.
                self.user=user;self.hwnd=root.winfo_id()
            except (OSError,AttributeError):pass
        for sequence in ('<Configure>','<Map>'):
            root.bind(sequence,self.changed,add='+')
        root.bind('<Destroy>',self.destroyed,add='+')

    def changed(self,event):
        if self.root is None or event.widget is not self.root:return
        if event.type==tk.EventType.Configure:
            position=(event.x,event.y,event.width,event.height)
            if position==self.position:return
            self.position=position
        self.schedule()

    def schedule(self):
        if self.root is None:return
        if self.job is not None:self.root.after_cancel(self.job)
        # One repaint after the move/resize burst; no permanent frame timer.
        self.job=self.root.after(24,self.flush)

    def cancel(self):
        if self.job is not None and self.root is not None:self.root.after_cancel(self.job)
        self.job=None

    def flush(self):
        self.cancel()
        if self.root is None or not self.root.winfo_exists() or not self.root.winfo_ismapped():return
        if self.user and self.hwnd:
            # INVALIDATE | ERASE | ALLCHILDREN | UPDATENOW. Windows repaints the
            # exposed background and child controls, clearing stale client pixels.
            self.user.RedrawWindow(self.hwnd,None,None,0x185)

    def destroyed(self,event):
        if event.widget is self.root:
            self.cancel();self.root=None;self.user=None;self.hwnd=None
