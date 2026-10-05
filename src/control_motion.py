"""Short, cancellable UI transitions; zero frame callbacks while idle."""
import time
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
            if t<1:self.jobs[key]=self.widget.after(16,frame)
        frame()
