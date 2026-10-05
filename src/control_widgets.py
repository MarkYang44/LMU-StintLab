"""Small glass-style Tk primitives; no web runtime or image dependencies."""
import ctypes
import tkinter as tk

BG='#101a2b';CARD='#1c2c43';EDGE='#3c526b';FG='#eff5ff';MUTED='#a4b8ce';ACCENT='#59dfb5'


def rounded(canvas,x,y,w,h,r,**kwargs):
    return canvas.create_polygon(x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,
        x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y,smooth=True,splinesteps=24,**kwargs)


class Pill(tk.Canvas):
    def __init__(self,parent,text,command,width=140,primary=False):
        super().__init__(parent,width=width,height=40,bg=parent.cget('bg'),highlightthickness=0,cursor='hand2')
        self.primary=primary;self.command=command;self.label=text;self.bind('<Configure>',lambda _:self.paint(False))
        self.bind('<Enter>',lambda _:self.paint(True));self.bind('<Leave>',lambda _:self.paint(False))
        self.bind('<Button-1>',lambda _:self.command());self.bind('<Return>',lambda _:self.command());self.configure(takefocus=True)
    def paint(self,hover):
        self.delete('all');w=self.winfo_width();color=('#6becc3' if hover else ACCENT) if self.primary else ('#354d69' if hover else '#293e57')
        rounded(self,1,2,w-3,36,18,fill=color,outline='#92edd6' if self.primary else '#48617a',width=1)
        self.create_text(w/2,20,text=self.label,fill='#092d29' if self.primary else FG,font=('Microsoft YaHei UI',10,'bold'))


class GlassCard(tk.Canvas):
    def __init__(self,parent):
        super().__init__(parent,bg=BG,highlightthickness=0,height=100)
        self.body=tk.Frame(self,bg=CARD);self.item=self.create_window(18,16,anchor='nw',window=self.body)
        self.bind('<Configure>',self.layout);self.body.bind('<Configure>',self.resize)
    def resize(self,_):
        h=self.body.winfo_reqheight()+34
        if int(self.cget('height'))!=h:self.configure(height=h)
    def layout(self,_):
        w=self.winfo_width();h=self.winfo_height();self.itemconfigure(self.item,width=max(30,w-36))
        self.delete('glass');rounded(self,1,4,w-3,h-6,22,fill='#080f1d',outline='',tags='glass')
        rounded(self,1,1,w-3,h-6,22,fill=CARD,outline=EDGE,width=1,tags='glass')
        # Subtle frost around the translucent rim; widgets retain solid contrast.
        for y in range(4,15):
            color='#%02x%02x%02x'%(40-y//2,59-y//2,80-y//2)
            self.create_line(24,y,w-24,y,fill=color,tags='glass')
        self.create_line(26,2,w-26,2,fill='#71859a',tags='glass');self.tag_lower('glass')


def backdrop(root):
    """Request Windows rounded corners and backdrop where DWM supports them."""
    if not hasattr(ctypes,'WinDLL'):return
    try:
        root.update_idletasks();user=ctypes.WinDLL('user32');user.GetParent.argtypes=[ctypes.c_void_p];user.GetParent.restype=ctypes.c_void_p
        root.attributes('-alpha',0.97)
        hwnd=user.GetParent(root.winfo_id()) or root.winfo_id();dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        for key,value in ((20,1),(33,2),(38,2)):
            data=ctypes.c_int(value);dwm.DwmSetWindowAttribute(hwnd,key,ctypes.byref(data),ctypes.sizeof(data))
    except (OSError,AttributeError):pass
