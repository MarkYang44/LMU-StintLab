"""Native industrial form controls. Transitions stop completely when idle."""
from i18n import tr
import tkinter as tk
from tkinter import font as tkfont
from control_theme import T
from control_widgets import px, scale, rounded
from control_motion import Motion, blend


class Field(tk.Canvas):
    """An ordinary editable Entry inside a focus-aware, clipped-corner surface."""
    def __init__(self, parent, textvariable=None, width=26, font=None, height=42, **ignored):
        self.s=scale(parent);self.amount=0.;self.focused=False
        super().__init__(parent, bg=parent.cget('bg'), highlightthickness=0,
                         width=px(parent,width*8+28), height=px(parent,height))
        self.entry=tk.Entry(self,textvariable=textvariable,font=font or (T.FONT,10),
            bg=T.FIELD,fg=T.FG,insertbackground=T.ACCENT,selectbackground=T.SELECT,
            selectforeground=T.FG,relief='flat',borderwidth=0,highlightthickness=0)
        self.item=self.create_window(px(self,14),px(self,21),anchor='w',window=self.entry)
        self.motion=Motion(self)
        self.bind('<Configure>',lambda _:self.paint())
        self.entry.bind('<FocusIn>',lambda _:self.focus(True))
        self.entry.bind('<FocusOut>',lambda _:self.focus(False))
        self.bind('<Button-1>',lambda _:self.entry.focus_set())
        for widget in (self,self.entry):
            widget.bind('<Enter>',lambda _:self.hover(1),add='+')
            widget.bind('<Leave>',lambda _:self.hover(0),add='+')
    def focus(self,value):self.focused=value;self.hover(1 if value else 0)
    def hover(self,target):
        if self.focused:target=1
        start=self.amount
        def frame(t):self.amount=start+(target-start)*t;self.paint()
        self.motion.animate('surface',frame,145)
    def paint(self):
        w=self.winfo_width();h=self.winfo_height();s=self.s
        self.delete('surface')
        rounded(self,1,1,w-2,h-2,6*s,fill=T.FIELD,
            outline=blend(T.EDGE,T.ACCENT,self.amount),tags='surface')
        self.create_line(12*s,h-2,12*s+(w-24*s)*self.amount,h-2,
                         fill=T.ACCENT,width=s,tags='surface')
        self.tag_lower('surface');self.coords(self.item,14*s,h/2)
        self.itemconfigure(self.item,width=max(1,w-28*s))
    def get(self):return self.entry.get()
    def focus_set(self):self.entry.focus_set()


class Select(tk.Canvas):
    """Combobox-compatible selector with a native animated, scrollable flyout.

    The in-window popup never grabs input. Outside clicks both dismiss it and
    continue to the intended control; temporary owner bindings are removed.
    """
    def __init__(self,parent,textvariable=None,values=(),state='readonly',width=26,
                 height=7,font=None,style=None,**kwargs):
        self.s=scale(parent);self.variable=textvariable or tk.StringVar(parent)
        self.values=list(values);self.state=state;self.rows=max(1,min(8,int(height)))
        self.font=tkfont.Font(parent,font=font or (T.FONT,10))
        self.amount=0.;self.focused=False;self.popup=None;self.offset=0;self.active=-1
        self.popup_motion=None;self.query='';self.query_job=None;self.owner_binding=None;self.owner_click=None;self.owner_focus=None;self.highlight_y=None
        super().__init__(parent,bg=parent.cget('bg'),highlightthickness=0,takefocus=True,
            cursor='hand2',width=px(parent,width*8+32),height=px(parent,42),**kwargs)
        self.motion=Motion(self);self.edit=None
        if state=='normal':
            self.edit=tk.Entry(self,textvariable=self.variable,font=self.font,bg=T.FIELD,
                fg=T.FG,insertbackground=T.ACCENT,relief='flat',highlightthickness=0,borderwidth=0)
            self.edit_item=self.create_window(14*self.s,21*self.s,anchor='w',window=self.edit)
            self.edit.bind('<FocusIn>',lambda _:self.focus(True));self.edit.bind('<FocusOut>',lambda _:self.focus(False))
            self.edit.bind('<Alt-Down>',lambda _:self.open())
        self.trace=self.variable.trace_add('write',lambda *_:self.paint())
        self.bind('<Configure>',self.resized);self.bind('<Enter>',lambda _:self.hover(1))
        self.bind('<Leave>',lambda _:self.hover(0));self.bind('<Button-1>',self.toggle)
        self.bind('<FocusIn>',lambda _:self.focus(True));self.bind('<FocusOut>',lambda _:self.focus(False))
        self.bind('<KeyPress>',self.key);self.bind('<MouseWheel>',lambda _:'break')
        self.bind('<Destroy>',self.dispose,add='+')
    def configure(self,cnf=None,**kwargs):
        if cnf is None and not kwargs:return super().configure()
        if cnf:kwargs.update(cnf)
        for key in ('values','state','width'):
            if key not in kwargs:continue
            value=kwargs.pop(key)
            if key=='values':self.values=list(value);self.close()
            elif key=='state':
                self.state=value;self.close()
                if self.edit:self.edit.configure(state='disabled' if value=='disabled' else 'normal')
            else:kwargs['width']=px(self,int(value)*8+32)
        result=super().configure(**kwargs) if kwargs else None
        if hasattr(self,'motion'):self.paint()
        return result
    config=configure
    def cget(self,key):
        if key=='values':return tuple(self.values)
        if key=='state':return self.state
        return super().cget(key)
    def get(self):return self.variable.get()
    def set(self,value):self.variable.set(value)
    def current(self,index=None):
        if index is not None:self.variable.set(self.values[index])
        try:return self.values.index(self.variable.get())
        except ValueError:return -1
    def resized(self,_):
        # A resizing or moving form must not leave a detached popup behind.
        if self.popup:self.close()
        self.paint()
    def focus(self,value):self.focused=value;self.hover(1 if value else 0)
    def hover(self,target):
        if self.focused or self.popup:target=1
        start=self.amount
        def frame(t):self.amount=start+(target-start)*t;self.paint()
        self.motion.animate('surface',frame,140)
    def paint(self):
        self.delete('surface');w=self.winfo_width();h=self.winfo_height();s=self.s
        disabled=self.state=='disabled';foreground=T.MUTED if disabled else T.FG
        rounded(self,1,1,w-2,h-2,6*s,fill=blend(T.FIELD,T.HOVER,self.amount*.45),
            outline=T.EDGE if disabled else blend(T.EDGE,T.ACCENT,self.amount),tags='surface')
        self.create_line(w-39*s,11*s,w-39*s,h-11*s,fill=T.EDGE,tags='surface')
        direction=-1 if self.popup else 1
        self.create_line(w-27*s,h/2-2*s*direction,w-22*s,h/2+3*s*direction,w-17*s,h/2-2*s*direction,
            fill=T.ACCENT if self.popup else T.MUTED,width=1.5*s,tags='surface')
        if self.edit:
            self.coords(self.edit_item,14*s,h/2);self.itemconfigure(self.edit_item,width=max(1,w-60*s));self.tag_lower('surface')
        else:
            text=tr(str(self.variable.get()));maximum=max(1,w-66*s)
            if self.font.measure(text)>maximum:
                while text and self.font.measure(text+'…')>maximum:text=text[:-1]
                text+='…'
            self.create_text(14*s,h/2,text=text,anchor='w',fill=foreground,font=self.font,tags='surface')
    def toggle(self,_=None):
        if self.state=='disabled':return 'break'
        if self.popup:self.close()
        else:self.open()
        return 'break'
    def open(self):
        if self.popup or self.state=='disabled' or not self.values:return 'break'
        self.owner=self.winfo_toplevel()
        previous=getattr(self.owner,'_stintrix_active_select',None)
        if previous is not None and previous is not self:previous.close(False)
        self.owner._stintrix_active_select=self
        self.focus_set();self.active=max(0,self.current());self.visible=min(self.rows,len(self.values))
        self.offset=max(0,min(len(self.values)-self.visible,self.active-self.visible+1))
        self.row_h=px(self,42);self.full_h=self.row_h*self.visible+px(self,12)
        self.popup=tk.Frame(self.owner,bg=T.CARD,takefocus=True)
        self.panel=tk.Canvas(self.popup,bg=T.CARD,highlightthickness=1,highlightbackground=T.EDGE)
        self.panel.pack(fill='both',expand=True);self.popup_motion=Motion(self.panel)
        availablew=self.owner.winfo_width();availableh=self.owner.winfo_height()
        width=min(availablew-px(self,24),max(self.winfo_width(),min(px(self,620),max(self.font.measure(tr(str(v))) for v in self.values)+px(self,66))))
        originx=self.winfo_rootx()-self.owner.winfo_rootx();originy=self.winfo_rooty()-self.owner.winfo_rooty()
        x=max(px(self,12),min(availablew-width-px(self,12),originx));bottom=originy+self.winfo_height()+px(self,5)
        self.above=bottom+self.full_h>availableh-px(self,16)
        self.edge=originy-px(self,5) if self.above else bottom;self.popup_x=x;self.popup_width=width
        self.panel.bind('<Motion>',self.pointer);self.panel.bind('<Button-1>',self.pick)
        self.panel.bind('<MouseWheel>',self.wheel);self.popup.bind('<KeyPress>',self.key)
        self.popup.bind('<FocusOut>',self.lost_focus)
        self.popup.bind('<Escape>',lambda _:self.close())
        self.owner_binding=self.owner.bind('<Configure>',lambda e:self.close(False) if e.widget is self.owner else None,add='+')
        self.owner_click=self.owner.bind('<ButtonPress-1>',self.outside_click,add='+')
        self.owner_focus=self.owner.bind('<FocusOut>',self.window_focus_lost,add='+')
        self.highlight_y=px(self,6)+(self.active-self.offset)*self.row_h
        self.paint();self.paint_options()
        def frame(t):
            h=max(2,round(self.full_h*(.3+.7*t)));y=self.edge-h if self.above else self.edge
            self.popup.place(x=x,y=max(0,y),width=width,height=h);self.popup.lift()
        self.popup_motion.animate('reveal',frame,150)
        self.popup.focus_set()
        return 'break'
    def outside_click(self,event):
        if self.popup is None:return
        target=str(event.widget)
        if event.widget is self or (self.edit is not None and event.widget is self.edit):return
        if event.widget is self.popup or target.startswith(str(self.popup)+'.'):return
        self.close(False)
        # Intentionally do not return 'break': the outside button must work on
        # this very click, including navigation and opening another selector.
    def window_focus_lost(self,event):
        if event.widget is self.owner and self.focus_get() is None:self.close(False)
    def close(self,restore=True):
        popup=self.popup;self.popup=None
        if popup:
            try:
                popup.destroy()
                if restore and self.winfo_exists():self.focus_set()
            except tk.TclError:pass
        for name,sequence in (('owner_binding','<Configure>'),('owner_click','<ButtonPress-1>'),('owner_focus','<FocusOut>')):
            binding=getattr(self,name,None)
            if binding:
                try:self.owner.unbind(sequence,binding)
                except tk.TclError:pass
                setattr(self,name,None)
        owner=getattr(self,'owner',None)
        if owner is not None and getattr(owner,'_stintrix_active_select',None) is self:owner._stintrix_active_select=None
        if self.query_job:
            try:self.after_cancel(self.query_job)
            except tk.TclError:pass
            self.query_job=None
        self.query=''
        if self.winfo_exists():self.paint()
        return 'break'
    def lost_focus(self,event):
        if event.widget is self.popup:
            # FocusOut already runs after the transfer; do not create a dangling idle callback.
            focus=self.focus_get()
            if focus is None or (focus is not self.popup and not str(focus).startswith(str(self.popup)+'.')):self.close(False)
    def paint_options(self):
        if not self.popup:return
        panel=self.panel;panel.delete('all');s=self.s;w=self.popup_width if hasattr(self,'popup_width') else self.winfo_width()
        panel.create_rectangle(5*s,self.highlight_y,w-5*s,self.highlight_y+self.row_h,fill=T.HOVER,outline='')
        for row,index in enumerate(range(self.offset,min(len(self.values),self.offset+self.visible))):
            y=px(self,6)+row*self.row_h;chosen=self.values[index]==self.variable.get()
            if chosen:panel.create_rectangle(5*s,y,w-5*s,y+self.row_h,fill=T.SELECT,outline='')
            if chosen:panel.create_rectangle(5*s,y+9*s,8*s,y+self.row_h-9*s,fill=T.ACCENT,outline='')
            panel.create_text(19*s,y+self.row_h/2,text=tr(str(self.values[index])),anchor='w',font=self.font,fill=T.FG)
            if chosen:panel.create_text(w-24*s,y+self.row_h/2,text='✓',font=(T.FONT,11),fill=T.ACCENT)
        panel.create_rectangle(5*s,self.highlight_y+9*s,8*s,self.highlight_y+self.row_h-9*s,fill=T.ACCENT,outline='')
        if self.offset>0:panel.create_line(w-12*s,3*s,w-34*s,3*s,fill=T.ACCENT,width=2*s)
        if self.offset+self.visible<len(self.values):panel.create_line(w-12*s,self.full_h-3*s,w-34*s,self.full_h-3*s,fill=T.ACCENT,width=2*s)
    def pointer(self,event):
        row=int((event.y-px(self,6))//self.row_h);index=self.offset+row
        if 0<=row<self.visible and index<len(self.values) and index!=self.active:
            self.active=index;start=self.highlight_y;target=px(self,6)+row*self.row_h
            def frame(t):self.highlight_y=start+(target-start)*t;self.paint_options()
            self.popup_motion.animate('selection',frame,110)
    def pick(self,event):
        if not (0<=event.x<self.popup_width and 0<=event.y<self.full_h):return self.close()
        row=int((event.y-px(self,6))//self.row_h)
        if 0<=row<self.visible:self.choose(self.offset+row)
        return 'break'
    def choose(self,index):
        if 0<=index<len(self.values):
            self.variable.set(self.values[index]);self.close();self.event_generate('<<ComboboxSelected>>')
    def wheel(self,event):
        step=-1 if event.delta>0 else 1
        self.offset=max(0,min(len(self.values)-self.visible,self.offset+step))
        self.popup_motion.cancel('selection');self.highlight_y=px(self,6)+(self.active-self.offset)*self.row_h
        self.paint_options();return 'break'
    def key(self,event):
        key=event.keysym
        if key=='Escape':return self.close()
        if self.state=='disabled':return 'break'
        if key in ('Tab','ISO_Left_Tab'):
            self.close();target=self.tk_focusPrev() if event.state&1 or key=='ISO_Left_Tab' else self.tk_focusNext()
            if target:target.focus_set()
            return 'break'
        if key in ('Return','space'):
            if self.popup:self.choose(self.active)
            else:self.open()
            return 'break'
        if key in ('Up','Down','Home','End'):
            if not self.popup:self.open()
            if not self.popup:return 'break'
            if key=='Home':self.active=0
            elif key=='End':self.active=len(self.values)-1
            else:self.active=max(0,min(len(self.values)-1,self.active+(1 if key=='Down' else -1)))
            if self.active<self.offset:self.offset=self.active
            elif self.active>=self.offset+self.visible:self.offset=self.active-self.visible+1
            self.popup_motion.cancel('selection');self.highlight_y=px(self,6)+(self.active-self.offset)*self.row_h
            self.paint_options();return 'break'
        if event.char and event.char.isprintable():
            if not self.popup:self.open()
            if not self.popup:return 'break'
            self.query+=event.char.casefold()
            if self.query_job:self.after_cancel(self.query_job)
            def clear():self.query='';self.query_job=None
            self.query_job=self.after(700,clear)
            match=next((i for i,v in enumerate(self.values) if str(v).casefold().startswith(self.query)),None)
            if match is not None:
                self.active=match;self.offset=max(0,min(len(self.values)-self.visible,match))
                self.popup_motion.cancel('selection');self.highlight_y=px(self,6)+(self.active-self.offset)*self.row_h;self.paint_options()
            return 'break'
    def dispose(self,event):
        if event.widget is self:
            self.close(False)
            self.font.__del__();self.font.delete_font=False;self.edit=None
            try:self.variable.trace_remove('write',self.trace)
            except tk.TclError:pass
