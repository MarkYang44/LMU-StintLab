"""Short, cancellable UI transitions; zero frame callbacks while idle."""
import time
import math
import tkinter as tk


def ease(value):return 1-(1-min(1,max(0,value)))**3


def blend(first,second,fraction):
    a=[int(first[i:i+2],16) for i in (1,3,5)];b=[int(second[i:i+2],16) for i in (1,3,5)]
    return '#'+''.join(f'{round(x+(y-x)*fraction):02x}' for x,y in zip(a,b))


class Motion:
    def __init__(self,widget):
        self.widget=widget;self.jobs={};widget.bind('<Destroy>',self.destroy,add='+')
    def destroy(self,event):
        if event.widget is self.widget:self.cancel()
    def cancel(self,key=None):
        for name in list(self.jobs) if key is None else [key]:
            job=self.jobs.pop(name,None)
            if job:
                try:self.widget.after_cancel(job)
                except tk.TclError:pass
    def animate(self,key,paint,duration=180):
        self.cancel(key);started=time.perf_counter()
        def frame():
            self.jobs.pop(key,None)
            if not self.widget.winfo_exists():return
            t=min(1,(time.perf_counter()-started)*1000/max(1,duration));paint(ease(t))
            if t<1:self.jobs[key]=self.widget.after(10,frame)
        frame()


class SmoothScroll:
    """Accumulate wheel input in pixels, retarget without restarting velocity.

    Limits are read on each frame so resizing/filtering cannot overscroll.
    Scrollbar dragging is immediate and cancels the remaining wheel motion.
    """
    def __init__(self,widget,position,limit,paint):
        self.widget=widget;self.position=position;self.limit=limit;self.paint=paint
        self.target=0.;self.job=None;self.last=0.
        widget.bind('<Destroy>',self.destroy,add='+')
    def destroy(self,event):
        if event.widget is self.widget:self.cancel()
    def cancel(self):
        if self.job is not None:
            try:self.widget.after_cancel(self.job)
            except tk.TclError:pass
        self.job=None
        try:self.target=self.position()
        except tk.TclError:self.target=0.
    def move(self,value):
        self.cancel();self.target=max(0,min(self.limit(),value));self.paint(self.target)
    def add(self,delta):
        if self.job is None:self.target=self.position()
        self.target=max(0,min(self.limit(),self.target+delta))
        if self.job is None:
            self.last=time.perf_counter();self.job=self.widget.after(10,self.frame)
    def frame(self):
        self.job=None
        if not self.widget.winfo_exists():return
        now=time.perf_counter();dt=min(.1,max(.001,now-self.last));self.last=now
        maximum=self.limit();current=max(0,min(maximum,self.position()))
        self.target=max(0,min(maximum,self.target));gap=self.target-current
        if abs(gap)<.3:self.paint(self.target);return
        self.paint(current+gap*(1-math.exp(-dt/.045)))
        self.job=self.widget.after(10,self.frame)
