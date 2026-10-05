"""Virtual session table: pixel scrolling, stable IDs and immediate selection.

    Only visible rows are drawn; complete recording data never enters this view.
    A small Treeview-compatible surface keeps existing session actions unchanged.
"""
from i18n import tr
import math
import tkinter as tk
from control_theme import T
from tkinter import ttk,font as tkfont
from control_motion import Motion,SmoothScroll,blend
from control_widgets import scale


class SessionList(tk.Frame):
    def __init__(self,parent,columns,height=9,selectmode='browse',checkboxes=False,**_):
        super().__init__(parent,bg=T.CARD)
        self.s=s=scale(parent);self.rowheight=44*s;self.columns=list(columns);self.multiple=selectmode=='extended'
        self.checkboxes=bool(checkboxes and self.multiple);self.gutter=32*s if self.checkboxes else 0
        self.widths={key:100*s for key in columns};self.minimum={key:60*s for key in columns}
        self.stretch=set();self.labels={key:key for key in columns};self.rows={};self.order=[];self.indices={}
        self.chosen=set();self.previous=set();self.anchor=None;self.cursor=None;self.fade=1.;self.offset=0.;self.xoffset=0.
        self.pending=None;self.textcache={};self.header_key=None;self.font=tkfont.Font(self,family=T.FONT,size=9)
        self.small=tkfont.Font(self,family='Segoe UI',size=9);self.bold=tkfont.Font(self,family=T.FONT,size=9,weight='bold')
        self.header=tk.Canvas(self,height=round(36*s),bg=T.FIELD,highlightthickness=0);self.header.grid(row=0,column=0,sticky='ew')
        self.viewport=tk.Canvas(self,height=round(height*self.rowheight),bg=T.CARD,highlightthickness=0,takefocus=True)
        self.viewport.grid(row=1,column=0,sticky='nsew');self.columnconfigure(0,weight=1);self.rowconfigure(1,weight=1)
        self.vertical=ttk.Scrollbar(self,orient='vertical',style='Lab.Vertical.TScrollbar',command=self.yview)
        self.vertical.grid(row=1,column=1,sticky='ns',padx=(round(4*s),0))
        self.horizontal=ttk.Scrollbar(self,orient='horizontal',style='Lab.Horizontal.TScrollbar',command=self.xview)
        self.motion=Motion(self.viewport)
        self.scroller=SmoothScroll(self.viewport,lambda:self.offset,self.limit,self.set_offset)
        self.viewport.bind('<Configure>',lambda _:self.schedule())
        self.viewport.bind('<MouseWheel>',self.wheel);self.viewport.bind('<Button-1>',self.click)
        self.viewport.bind('<Motion>',self.hover);self.viewport.bind('<Leave>',lambda _:self.set_hover(None));self.hovered=None
        for key in ('Up','Down','Home','End','Prior','Next'):
            self.viewport.bind('<'+key+'>',lambda event,k=key:self.key(event,k))
        self.viewport.bind('<Control-a>',self.select_all)
        self.viewport.bind('<space>',self.toggle_focused)
        if self.checkboxes:self.header.bind('<Button-1>',self.header_click)
        super().bind('<Destroy>',self.destroyed,add='+')
    def bind(self,sequence=None,func=None,add=None):
        if hasattr(self,'viewport') and sequence not in ('<Destroy>','<Configure>'):
            return self.viewport.bind(sequence,func,add)
        return super().bind(sequence,func,add)
    def destroyed(self,event):
        if event.widget is self and self.pending:
            try:self.after_cancel(self.pending)
            except tk.TclError:pass
            self.pending=None
    def heading(self,key,text):self.labels[key]=tr(text);self.schedule()
    def column(self,key,width,minwidth,stretch):
        self.widths[key]=width;self.minimum[key]=minwidth
        if stretch:self.stretch.add(key)
        self.schedule()
    def get_children(self):return tuple(self.order)
    def exists(self,iid):return str(iid) in self.rows
    def selection(self):return tuple(i for i in self.order if i in self.chosen)
    def selection_set(self,items):
        values=[items] if isinstance(items,str) else list(items)
        selected={str(i) for i in values if self.exists(i)}
        if not self.multiple and len(selected)>1:selected={next(i for i in self.order if i in selected)}
        self.previous=self.chosen.copy();self.chosen=selected;self.fade=0.
        def frame(t):self.fade=t;self.paint()
        self.motion.animate('selection',frame,180)
        self.viewport.event_generate('<<TreeviewSelect>>')
    def delete(self,*items):
        removed=set(items)
        for iid in removed:self.rows.pop(iid,None)
        self.order=[iid for iid in self.order if iid not in removed];self.chosen.difference_update(removed)
        if self.cursor in removed:self.cursor=None
        if self.anchor in removed:self.anchor=None
        self.schedule()
    def insert(self,parent,index,iid,values,tags=()):
        iid=str(iid)
        if iid in self.rows:raise ValueError('Duplicate session ID')
        self.rows[iid]=tuple(values)
        if index=='end':self.order.append(iid)
        else:self.order.insert(int(index),iid)
        self.schedule();return iid
    def replace(self,rows,selected=()):
        """Replace a filtered inventory in one transaction, retaining stable IDs."""
        self.motion.cancel();self.rows={str(i):tuple(values) for i,values in rows};self.order=list(self.rows)
        self.chosen={str(i) for i in selected if str(i) in self.rows};self.previous=self.chosen.copy();self.fade=1.
        if self.cursor not in self.rows:self.cursor=None
        if self.anchor not in self.rows:self.anchor=None
        self.scroller.cancel();self.schedule()
    def schedule(self):
        if self.pending is None:self.pending=self.after_idle(self.layout)
    def layout(self):
        self.pending=None;self.indices={iid:i for i,iid in enumerate(self.order)}
        width=max(1,self.viewport.winfo_width());total=sum(self.widths.values())+self.gutter;extra=max(0,width-total)
        self.actual={key:self.widths[key]+(extra/len(self.stretch) if key in self.stretch else 0) for key in self.columns}
        self.totalwidth=sum(self.actual.values())+self.gutter;self.xoffset=max(0,min(self.xoffset,self.totalwidth-width))
        if self.totalwidth>width+1:self.horizontal.grid(row=2,column=0,sticky='ew',pady=(round(3*self.s),0))
        else:self.horizontal.grid_remove()
        self.offset=max(0,min(self.offset,self.limit()));self.scroller.target=max(0,min(self.scroller.target,self.limit()))
        self.paint()
    def limit(self):return max(0,len(self.order)*self.rowheight-self.viewport.winfo_height())
    def set_offset(self,value):self.offset=value;self.paint()
    def yview(self,*args):
        if not args:return self.fractions()
        if args[0]=='moveto':self.scroller.move(float(args[1])*max(1,len(self.order)*self.rowheight))
        elif args[0]=='scroll':
            step=self.viewport.winfo_height()*.85 if args[2]=='pages' else self.rowheight
            self.scroller.add(int(args[1])*step)
    def xview(self,*args):
        if not args:return (self.xoffset/self.totalwidth,min(1,(self.xoffset+self.viewport.winfo_width())/self.totalwidth))
        if args[0]=='moveto':value=float(args[1])*self.totalwidth
        else:value=self.xoffset+int(args[1])*(self.viewport.winfo_width()*.85 if args[2]=='pages' else 24*self.s)
        self.xoffset=max(0,min(value,max(0,self.totalwidth-self.viewport.winfo_width())));self.paint()
    def fractions(self):
        total=max(1,len(self.order)*self.rowheight)
        return (self.offset/total,min(1,(self.offset+self.viewport.winfo_height())/total))
    def wheel(self,event):
        if event.state&1:self.xview('scroll',round(-event.delta/120*3),'units')
        else:self.scroller.add(-event.delta/120*self.rowheight*2.4)
        return 'break'
    def at(self,event):
        index=math.floor((event.y+self.offset)/self.rowheight)
        return self.order[index] if 0<=index<len(self.order) else None
    def click(self,event):
        self.viewport.focus_set();iid=self.at(event)
        if iid is None:return 'break'
        self.cursor=iid
        self.choose(iid,bool(event.state&4) or (self.checkboxes and event.x<self.gutter),bool(event.state&1));return 'break'
    def toggle_focused(self,event):
        if self.multiple and self.cursor in self.rows:self.choose(self.cursor,control=True)
        return 'break'
    def header_click(self,event):
        if event.x<self.gutter:
            self.selection_set(()) if len(self.chosen)==len(self.order) else self.select_all(event)
        return 'break'
    def choose(self,iid,control=False,shift=False):
        if self.multiple and shift and self.anchor in self.indices:
            a,b=sorted((self.indices[self.anchor],self.indices[iid]));values=set(self.order[a:b+1])
            if control:values|=self.chosen
        elif self.multiple and control:
            values=self.chosen^{iid};self.anchor=iid
        else:values={iid};self.anchor=iid
        self.selection_set(values)
    def select_all(self,event):
        if self.multiple:self.selection_set(self.order)
        return 'break'
    def key(self,event,key):
        if not self.order:return 'break'
        index=self.indices.get(self.cursor,-1 if key=='Down' else 0);page=max(1,int(self.viewport.winfo_height()/self.rowheight)-1)
        index={'Up':index-1,'Down':index+1,'Home':0,'End':len(self.order)-1,'Prior':index-page,'Next':index+page}[key]
        index=max(0,min(len(self.order)-1,index));iid=self.order[index];self.cursor=iid
        if not (event.state&4):self.choose(iid,False,bool(event.state&1))
        top=index*self.rowheight;bottom=top+self.rowheight
        if top<self.offset:self.scroller.move(top)
        elif bottom>self.offset+self.viewport.winfo_height():self.scroller.move(bottom-self.viewport.winfo_height())
        self.paint();return 'break'
    def hover(self,event):self.set_hover(self.at(event))
    def set_hover(self,iid):
        if iid!=self.hovered:self.hovered=iid;self.paint()
    def fit(self,value,width,font):
        value=str(value)
        key=(value,round(width),str(font))
        if key in self.textcache:return self.textcache[key]
        if font.measure(value)<=width:result=value
        else:
            low=0;high=len(value)
            while low<high:
                middle=(low+high+1)//2
                if font.measure(value[:middle]+'…')<=width:low=middle
                else:high=middle-1
            result=value[:low]+'…'
        if len(self.textcache)>=1024:self.textcache.clear()
        self.textcache[key]=result;return result
    def paint(self):
        if not hasattr(self,'actual'):return
        c=self.viewport;h=c.winfo_height();w=c.winfo_width();s=self.s;c.delete('all')
        header_key=(T.mode,w,self.xoffset,tuple(self.actual.values()),tuple(self.labels.values()))
        if header_key!=self.header_key:
            self.header_key=header_key;self.header.delete('all');x=self.gutter-self.xoffset
            for key in self.columns:
                width=self.actual[key]
                self.header.create_text(x+12*s,18*s,text=self.labels[key],anchor='w',fill=T.MUTED,font=self.bold)
                x+=width
            self.header.create_line(0,35*s,w,35*s,fill=T.EDGE)
        first=max(0,int(self.offset/self.rowheight));last=min(len(self.order),math.ceil((self.offset+h)/self.rowheight)+1)
        for index in range(first,last):
            iid=self.order[index];y=index*self.rowheight-self.offset;base=T.CARD if index%2==0 else T.STRIPE
            amount=(self.fade if iid not in self.previous else 1) if iid in self.chosen else (1-self.fade if iid in self.previous else 0)
            color=blend(T.HOVER if iid==self.hovered else base,T.SELECT,amount)
            c.create_rectangle(0,y,w,y+self.rowheight,fill=color,outline='')
            if amount>0:c.create_rectangle(0,y+7*s,3*s,y+self.rowheight-7*s,fill=blend(color,T.ACCENT,amount),outline='')
            x=self.gutter-self.xoffset
            for key,value in zip(self.columns,self.rows[iid]):
                width=self.actual[key]
                if x+width>0 and x<w:
                    font=self.small if key in ('date','lap') else self.font
                    fg=T.ACCENT if key=='lap' and iid in self.chosen else (T.MUTED if key=='date' else T.FG)
                    c.create_text(x+12*s,y+self.rowheight/2,text=self.fit(value,max(0,width-24*s),font),anchor='w',font=font,fill=fg)
                x+=width
            if self.checkboxes:
                c.create_rectangle(0,y,self.gutter,y+self.rowheight,fill=color,outline='')
                self.checkbox(c,16*s,y+self.rowheight/2,iid in self.chosen)
            if self.cursor==iid and c.focus_get() is c:
                c.create_rectangle(5*s,y+3*s,w-3*s,y+self.rowheight-3*s,outline=T.EDGE)
        if not self.order:c.create_text(w/2,h/2,text='没有匹配的赛事记录',font=self.font,fill=T.MUTED)
        if self.checkboxes:
            self.header.delete('check');self.header.create_rectangle(0,0,self.gutter,35*s,fill=T.FIELD,outline='',tags='check')
            self.checkbox(self.header,16*s,18*s,bool(self.order) and len(self.chosen)==len(self.order),'check')
        self.vertical.set(*self.fractions());self.horizontal.set(*self.xview())
    def checkbox(self,canvas,x,y,checked,tag=''):
        half=6*self.s
        canvas.create_rectangle(x-half,y-half,x+half,y+half,fill=T.BUTTON if checked else '',outline=T.ACCENT if checked else T.MUTED,tags=tag)
        if checked:canvas.create_line(x-3*self.s,y,x-self.s,y+2*self.s,x+4*self.s,y-3*self.s,fill=T.INK,width=max(1,1.5*self.s),tags=tag)
