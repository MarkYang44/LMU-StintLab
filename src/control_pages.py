"""Bounded native page reuse and cancellable GUI-thread construction slices."""
from dataclasses import dataclass,field
import time
import tkinter as tk

@dataclass
class Page:
    frame:object
    attributes:dict=field(default_factory=dict)
    sync:list=field(default_factory=list)
    forms:dict=field(default_factory=dict)
    complete:bool=False

class PageDeck:
    CACHE=(0,3)
    def __init__(self,owner,host):
        self.owner=owner;self.host=host;self.pages={};self.active=None;self.index=None
        self.pending=None;self.job=None;self.generator=None;self.building=None;self.before={}
    def cancel_request(self):
        if self.pending is not None:self.owner.root.after_cancel(self.pending);self.pending=None
    def request(self,index):
        self.cancel_request()
        self.owner.title.configure(text=self.owner.page_titles[index])
        self.owner.subtitle.configure(text=self.owner.page_subtitles[index])
        self.owner.shell.select(index)
        def open_page():
            self.pending=None
            if not self.owner.closing:self.owner.show_page(index,progressive=True)
        self.pending=self.owner.root.after(16,open_page)
    def cancel_build(self):
        if self.job is not None:self.owner.root.after_cancel(self.job);self.job=None
        if self.generator is not None:self.generator.close();self.generator=None
    def pause(self,widget):
        motion=getattr(widget,'motion',None)
        if motion is not None:
            motion.cancel()
            if widget.__class__.__name__=='Switch':widget.value=float(widget.variable.get())
            for name,value in (('amount',0),('focused',False),('pressed',False)):
                if hasattr(widget,name):setattr(widget,name,value)
            if hasattr(widget,'paint'):widget.paint()
        if widget.__class__.__name__=='Select':widget.close(False)
        for child in widget.winfo_children():self.pause(child)
    def mount(self,index,builder,progressive=False):
        self.cancel_build()
        if self.active is not None:
            self.pause(self.active.frame);self.active.frame.pack_forget()
            if self.index not in self.CACHE or not self.active.complete:
                self.active.frame.destroy();self.pages.pop(self.index,None)
        self.index=index
        cached=self.pages.get(index)
        if cached is not None and cached.complete:
            self.active=cached;self.owner.content=cached.frame
            for name,value in cached.attributes.items():setattr(self.owner,name,value)
            cached.frame.pack(fill='x')
            for refresh in cached.sync:refresh()
            return
        page=Page(tk.Frame(self.host,bg=self.host.cget('bg')));self.active=page
        if index in self.CACHE:self.pages[index]=page
        self.owner.content=page.frame;page.frame.pack(fill='x')
        self.before=dict(vars(self.owner));self.building=page
        result=builder()
        if result is not None and hasattr(result,'__next__'):
            self.generator=result
            if progressive:self.step();return
            for _ in result:pass
        self.finish()
    def register(self,module,variables,refresh):
        self.building.forms[module]=variables;self.building.sync.append(refresh)
    def on_resume(self,refresh):self.building.sync.append(refresh)
    def finish(self):
        page=self.active
        page.attributes={name:value for name,value in vars(self.owner).items()
            if self.before.get(name) is not value and isinstance(value,(tk.Widget,tk.Variable))
            and name not in ('root','content','scroll','title','subtitle','tree','guide_page')}
        page.complete=True;self.generator=None;self.job=None;self.building=None
    def step(self):
        self.job=None;start=time.perf_counter()
        try:
            while time.perf_counter()-start<.006:next(self.generator)
        except StopIteration:self.finish();return
        self.job=self.owner.root.after(16,self.step)
    def dispose(self):
        self.cancel_request();self.cancel_build()
        for page in self.pages.values():
            if page.frame.winfo_exists():page.frame.destroy()
        self.pages.clear();self.active=None;self.building=None;self.before={};self.owner=None;self.host=None
