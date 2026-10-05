"""Industrial surfaces and animated controls, using the lightweight Tk runtime."""
from i18n import tr
import ctypes
import tkinter as tk
from control_theme import T
from tkinter import font as tkfont
from control_motion import Motion,blend



def scale(widget):return max(1,float(widget.winfo_fpixels('1i'))/96)
def px(widget,value):return round(value*scale(widget))


def rounded(canvas,x,y,w,h,r,**kwargs):
    """Clipped opposing corners, retained under its old name for UI compatibility."""
    r=min(r,w/3,h/3)
    return canvas.create_polygon(x+r,y,x+w,y,x+w,y+h-r,x+w-r,y+h,x,y+h,x,y+r,**kwargs)


class Pill(tk.Canvas):
    def __init__(self,parent,text,command,width=140,primary=False):
        self.s=scale(parent);self.font=tkfont.Font(parent,family=T.FONT,size=10,weight='bold')
        width=max(width*self.s,self.font.measure(tr(text))+36*self.s)
        super().__init__(parent,width=round(width),height=px(parent,46),bg=parent.cget('bg'),highlightthickness=0,cursor='hand2',takefocus=True)
        self.primary=primary;self.command=command;self.label=text;self.amount=0;self.pressed=False;self.focused=False;self.motion=Motion(self)
        self.bind('<Configure>',lambda _:self.paint())
        self.bind('<Enter>',lambda _:self.hover(1));self.bind('<Leave>',lambda _:self.hover(0))
        self.bind('<ButtonPress-1>',self.press);self.bind('<ButtonRelease-1>',self.release)
        self.bind('<Return>',lambda _:self.command());self.bind('<space>',lambda _:self.command())
        self.bind('<FocusIn>',lambda _:self.focus(True));self.bind('<FocusOut>',lambda _:self.focus(False))
    def focus(self,value):self.focused=value;self.paint()
    def hover(self,target):
        start=self.amount
        def paint(t):self.amount=start+(target-start)*t;self.paint()
        self.motion.animate('hover',paint,160)
    def press(self,_):self.pressed=True;self.focus_set();self.paint()
    def release(self,event):
        fire=self.pressed and 0<=event.x<self.winfo_width() and 0<=event.y<self.winfo_height()
        self.pressed=False;self.paint()
        if fire:self.command()
    def paint(self):
        self.delete('all');s=self.s;w=self.winfo_width();h=self.winfo_height();shift=2*s if self.pressed else 0
        base=T.BUTTON if self.primary else T.FIELD;over=T.BUTTON_HOVER if self.primary else T.HOVER;color=blend(base,over,self.amount)
        rounded(self,2*s,4*s,w-4*s,h-7*s,7*s,fill=T.BG,outline='')
        rounded(self,2*s,2*s+shift,w-4*s,h-7*s,7*s,fill=color,outline=T.ACCENT if self.focused else (T.ACCENT if self.primary else T.EDGE))
        if not self.primary:self.create_line(10*s,3*s+shift,30*s+24*s*self.amount,3*s+shift,fill=T.ACCENT,width=2*s)
        self.create_text(w/2,h/2-1*s+shift,text=tr(self.label),fill=T.INK if self.primary else T.FG,font=self.font)


class GlassCard(tk.Canvas):
    def __init__(self,parent):
        self.s=scale(parent);self.margin=round(22*self.s)
        super().__init__(parent,bg=parent.cget('bg'),highlightthickness=0,height=100)
        self.body=tk.Frame(self,bg=T.CARD);self.item=self.create_window(self.margin,round(20*self.s),anchor='nw',window=self.body)
        self.bind('<Configure>',self.layout);self.body.bind('<Configure>',self.resize)
    def resize(self,_):
        h=self.body.winfo_reqheight()+round(42*self.s)
        if int(self.cget('height'))!=h:self.configure(height=h)
    def layout(self,_):
        s=self.s;w=self.winfo_width();h=self.winfo_height();self.itemconfigure(self.item,width=max(30,w-2*self.margin))
        self.delete('glass')
        rounded(self,1,1,w-3,h-7*s,12*s,fill=T.CARD,outline=T.EDGE,width=1,tags='glass')
        self.create_line(17*s,1,69*s,1,fill=T.ACCENT,width=2*s,tags='glass')
        for i in range(3):
            self.create_line(w-(22+i*6)*s,h-13*s,w-(18+i*6)*s,h-17*s,fill=T.EDGE,tags='glass')
        self.tag_lower('glass')


class Switch(tk.Canvas):
    """Label and animated toggle; keyboard activation and external state updates."""
    def __init__(self,parent,text,variable,command):
        self.s=scale(parent);self.variable=variable;self.command=command;self.text=text;self.value=float(variable.get());self.motion=None
        super().__init__(parent,height=px(parent,48),bg=parent.cget('bg'),highlightthickness=0,takefocus=True,cursor='hand2')
        self.motion=Motion(self);self.bind('<Configure>',lambda _:self.paint());self.bind('<Button-1>',lambda _:self.toggle())
        self.bind('<Return>',lambda _:self.toggle());self.bind('<space>',lambda _:self.toggle())
        self.bind('<FocusIn>',lambda _:self.paint());self.bind('<FocusOut>',lambda _:self.paint())
        self.trace=variable.trace_add('write',self.changed);self.bind('<Destroy>',self.cleanup,add='+')
    def cleanup(self,event):
        if event.widget is self:
            try:self.variable.trace_remove('write',self.trace)
            except tk.TclError:pass
    def toggle(self):self.focus_set();self.variable.set(not self.variable.get());self.command()
    def changed(self,*_):
        start=self.value;target=float(self.variable.get())
        def frame(t):self.value=start+(target-start)*t;self.paint()
        self.motion.animate('toggle',frame,190)
    def paint(self):
        self.delete('all');s=self.s;w=self.winfo_width();h=self.winfo_height();x=w-54*s;y=(h-25*s)/2
        self.create_text(0,h/2,text=tr(self.text),anchor='w',font=(T.FONT,10),fill=T.FG)
        rounded(self,x,y,48*s,25*s,4*s,fill=blend(T.FIELD,T.SELECT,self.value),outline=T.ACCENT if self.focus_get() is self else T.EDGE)
        cx=x+(13+22*self.value)*s
        self.create_rectangle(cx-8*s,y+4*s,cx+8*s,y+21*s,fill=blend(T.MUTED,T.ACCENT,self.value),outline='')


class CardGrid(tk.Frame):
    """Two balanced columns on wide displays; stack before forms become cramped."""
    def __init__(self,parent):
        super().__init__(parent,bg=T.BG);self.cards=[];self.wide=None;self.bind('<Configure>',self.layout)
        self.columnconfigure(0,weight=1,uniform='cards');self.columnconfigure(1,weight=1,uniform='cards')
    def add(self,card):self.cards.append(card);self.layout()
    def layout(self,_=None):
        wide=self.winfo_width()>=px(self,900)
        if self.wide==wide and all(c.winfo_manager() for c in self.cards):return
        self.wide=wide
        for i,card in enumerate(self.cards):
            card.grid(row=0 if wide else i,column=i if wide else 0,columnspan=1 if wide else 2,
                sticky='new',padx=(0,px(self,9)) if wide and i==0 else ((px(self,9),0) if wide else 0),pady=(0,px(self,18)))


class LaunchArtwork(tk.Canvas):
    """Static racing-line motif, so decoration adds no idle rendering load."""
    def __init__(self,parent):
        super().__init__(parent,bg=T.CARD,height=px(parent,78),highlightthickness=0);self.bind('<Configure>',self.paint)
    def paint(self,_=None):
        self.delete('all');s=scale(self);w=self.winfo_width()
        self.create_text(0,20*s,text='LE MANS ULTIMATE',anchor='w',fill=T.FG,font=('Segoe UI',15,'bold'))
        self.create_text(1*s,48*s,text='DRIVE  /  RECORD  /  REFLECT',anchor='w',fill=T.ACCENT,font=('Segoe UI',8,'bold'))
        if w<px(self,610):return
        x=w-270*s
        for offset,color in ((0,T.EDGE),(7,T.MUTED),(14,T.ACCENT)):
            points=(x,56*s+offset,x+42*s,56*s+offset,x+77*s,12*s+offset,x+134*s,12*s+offset,x+166*s,46*s+offset,x+239*s,46*s+offset)
            self.create_line(*points,fill=color,width=2*s)
        self.create_rectangle(x+173*s,47*s,x+181*s,55*s,fill=T.ACCENT,outline='')


def backdrop(root):
    """Opaque readable content, with native dark chrome and rounded corners."""
    root.attributes('-alpha',1.0)
    if not hasattr(ctypes,'WinDLL'):return
    try:
        root.update_idletasks();user=ctypes.WinDLL('user32');user.GetParent.argtypes=[ctypes.c_void_p];user.GetParent.restype=ctypes.c_void_p
        hwnd=user.GetParent(root.winfo_id()) or root.winfo_id();dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        for key,value in ((20,1 if T.mode=='dark' else 0),(33,2)):
            data=ctypes.c_int(value);dwm.DwmSetWindowAttribute(hwnd,key,ctypes.byref(data),ctypes.sizeof(data))
    except (OSError,AttributeError):pass
