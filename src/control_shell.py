"""Responsive desktop frame and animated navigation, separate from session logic."""
import tkinter as tk
from control_theme import T
from tkinter import ttk,font as tkfont
from control_motion import Motion,SmoothScroll,blend
from control_widgets import rounded,scale,px,Pill
import branding


def symbol(canvas,kind,x,y,s,color):
    def line(*v):canvas.create_line(*[n*s+(x if i%2==0 else y) for i,n in enumerate(v)],fill=color,width=max(1,1.5*s),capstyle='round',joinstyle='round')
    if kind==0:line(0,13,5,13,8,3,12,20,16,8,23,8)
    elif kind==1:
        for row,width in enumerate((23,16,20)):line(0,row*8,width,row*8)
    elif kind==2:line(0,19,5,13,9,16,14,3,19,8,24,0);line(0,6,6,3,12,9,18,17,24,12)
    elif kind==3:
        for i,p in enumerate((5,15,9)):line(i*8,0,i*8,22);line(i*8-3,p,i*8+3,p)
    elif kind==5:line(3,16,0,9,4,0,14,2,23,13,18,22,6,20,3,16)
    elif kind==6:
        line(0,15,3,5,8,5,11,1,18,1,21,5,24,5,27,15,0,15);line(5,15,5,20,10,20,10,15);line(18,15,18,20,23,20,23,15)
    else:
        line(0,5,8,5,11,0,21,0,24,5,24,21,0,21,0,5);line(9,12,15,12);line(12,9,12,15)


class Navigation(tk.Canvas):
    def __init__(self,parent,names,command):
        self.s=scale(parent);self.step=68*self.s;self.names=names;self.command=command;self.selected=0;self.position=0;self.hovered=-1
        super().__init__(parent,bg=T.RAIL,height=round(self.step*len(names)),highlightthickness=0,takefocus=True,cursor='hand2')
        self.motion=Motion(self);self.bind('<Configure>',lambda _:self.paint());self.bind('<Motion>',self.hover);self.bind('<Leave>',self.leave)
        self.bind('<Button-1>',self.click);self.bind('<Up>',lambda _:self.command(max(0,self.selected-1)))
        self.bind('<Down>',lambda _:self.command(min(len(names)-1,self.selected+1)))
    def click(self,event):
        index=int(event.y//self.step)
        if 0<=index<len(self.names):self.focus_set();self.command(index)
    def hover(self,event):
        index=int(event.y//self.step)
        if self.hovered!=index:self.hovered=index;self.paint()
    def leave(self,_):self.hovered=-1;self.paint()
    def select(self,index):
        start=self.position;self.selected=index
        def frame(t):self.position=start+(index-start)*t;self.paint()
        self.motion.animate('selection',frame,230)
    def paint(self):
        self.delete('all');s=self.s;w=self.winfo_width();top=self.position*self.step+6*s
        rounded(self,0,top,w-1,self.step-12*s,8*s,fill=T.SELECT,outline=T.MARK)
        rounded(self,0,top+17*s,3*s,22*s,1*s,fill=T.ACCENT,outline='')
        for i,name in enumerate(self.names):
            y=i*self.step+self.step/2;color=T.FG if i==self.selected else T.MUTED
            if i==self.hovered and i!=self.selected:
                rounded(self,4*s,i*self.step+9*s,w-9*s,self.step-18*s,8*s,fill=T.HOVER,outline='');color=T.FG
            symbol(self,i,19*s,y-10*s,s,T.ACCENT if i==self.selected else color)
            self.create_text(57*s,y,text=name,anchor='w',fill=color,font=(T.FONT,11,'bold' if i==self.selected else 'normal'))
            self.create_text(w-12*s,y,text=f'{i+1:02}',anchor='e',fill=T.ACCENT if i==self.selected else T.MUTED,font=('Consolas',8))


class Shell:
    def __init__(self,root,names,command,status,on_theme=None):
        self.root=root;self.s=s=scale(root);self.compact=False
        self.brand_font=tkfont.Font(root,family='Segoe UI',size=23,weight='bold')
        self.rail_width=max(round(252*s),self.brand_font.measure('StintLab')+round(48*s))
        available_w=max(800,root.winfo_screenwidth()-round(70*s));available_h=max(600,root.winfo_screenheight()-round(100*s))
        root.geometry(f'{min(round(1240*s),available_w)}x{min(round(850*s),available_h)}')
        root.minsize(min(round(1060*s),available_w),min(round(700*s),available_h))
        self.side=side=tk.Frame(root,bg=T.RAIL,width=self.rail_width);side.pack(side='left',fill='y');side.pack_propagate(False)
        self.brand=tk.Canvas(side,bg=T.RAIL,highlightthickness=0,height=round(177*s));self.brand.pack(fill='x',padx=round(25*s),pady=(round(22*s),round(4*s)))
        self.brand.bind('<Configure>',self.paint_brand)
        self.logo=None
        try:
            self.logo=tk.PhotoImage(master=root,file=str(branding.directory()/'menu-icon.png'))
            if s<1.6:self.logo=self.logo.subsample(2)
        except tk.TclError:pass
        self.navigation=Navigation(side,names,command);self.navigation.pack(fill='x',padx=round(16*s))
        foot=tk.Frame(side,bg=T.RAIL);foot.pack(side='bottom',fill='x',padx=round(25*s),pady=round(26*s))
        tk.Label(foot,text='●  LOCAL & PRIVATE',bg=T.RAIL,fg=T.ACCENT,font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x')
        tk.Label(foot,text='排位 / 正赛自动记录\n练习 / Warmup 仅实时显示',bg=T.RAIL,fg=T.MUTED,font=(T.FONT,9),anchor='w',justify='left',pady=12).pack(fill='x')
        self.footer=foot;side.bind('<Configure>',self.layout_sidebar)
        self.main=main=tk.Frame(root,bg=T.BG);main.pack(side='left',fill='both',expand=True,padx=round(28*s),pady=(round(26*s),round(14*s)))
        self.motion=Motion(main)
        head=tk.Frame(main,bg=T.BG);head.pack(fill='x',pady=(0,round(22*s)))
        top=tk.Frame(head,bg=T.BG);top.pack(fill='x')
        self.breadcrumb=tk.Label(top,text='STINTLAB  /  CONTROL CENTER',font=('Segoe UI',9,'bold'),bg=T.BG,fg=T.ACCENT,anchor='w');self.breadcrumb.pack(side='left')
        self.theme_button=Pill(top,'◐  浅色主题' if T.mode=='dark' else '◑  深色主题',on_theme or (lambda:None),115)
        self.theme_button.configure(height=round(32*s));self.theme_button.pack(side='right')
        self.title=tk.Label(head,font=(T.FONT,25,'bold'),bg=T.BG,fg=T.FG,anchor='w');self.title.pack(fill='x',pady=(round(10*s),round(3*s)))
        self.subtitle=tk.Label(head,font=(T.FONT,10),bg=T.BG,fg=T.MUTED,anchor='w');self.subtitle.pack(fill='x')
        self.subtitle.bind('<Configure>',lambda e:self.subtitle.configure(wraplength=e.width))
        footer=tk.Frame(main,bg=T.BG);footer.pack(side='bottom',fill='x',pady=(round(12*s),0))
        tk.Label(footer,textvariable=status,font=(T.FONT,9),bg=T.BG,fg=T.MUTED,anchor='w').pack(side='left',fill='x',expand=True)
        tk.Label(footer,text='STINTLAB  //  LOCAL',font=('Consolas',8),bg=T.BG,fg=T.MUTED).pack(side='right')
        viewport=tk.Frame(main,bg=T.BG);viewport.pack(fill='both',expand=True)
        self.scroll=tk.Canvas(viewport,bg=T.BG,highlightthickness=0)
        self.scroller=SmoothScroll(self.scroll,lambda:self.scroll.canvasy(0),
            lambda:max(0,self.content.winfo_height()-self.scroll.winfo_height()),
            lambda value:self.scroll.yview_moveto(value/max(1,self.content.winfo_height())))
        bar=ttk.Scrollbar(viewport,orient='vertical',command=self.scrollbar,style='Lab.Vertical.TScrollbar')
        bar.pack(side='right',fill='y',padx=(round(8*s),0));self.scroll.pack(side='left',fill='both',expand=True);self.scroll.configure(yscrollcommand=bar.set)
        self.content=tk.Frame(self.scroll,bg=T.BG);self.item=self.scroll.create_window(0,0,anchor='nw',window=self.content)
        self.scroll.bind('<Configure>',lambda e:self.scroll.itemconfigure(self.item,width=e.width))
        # The animation translates the window, not the scrollable document origin.
        self.content.bind('<Configure>',lambda e:self.scroll.configure(scrollregion=(0,0,e.width,e.height)))
    def paint_brand(self,_=None):
        c=self.brand;s=self.s;c.delete('all')
        if self.logo:c.create_image(0,0,image=self.logo,anchor='nw')
        c.create_text(0,82*s,text='StintLab',font=self.brand_font,fill=T.FG,anchor='w')
        c.create_text(1*s,114*s,text='LE MANS ULTIMATE',font=('Segoe UI',9,'bold'),fill=T.MUTED,anchor='w')
        right=c.winfo_width();c.create_text(right-2*s,25*s,text='SYS / 01',font=('Consolas',8),fill=T.ACCENT,anchor='e')
        line=(132 if self.compact else 153)*s
        c.create_line(0,line,right,line,fill=T.EDGE);c.create_line(0,line,44*s,line,fill=T.ACCENT,width=2*s)
    def scrollbar(self,*args):
        self.scroller.cancel();self.scroll.yview(*args)
    def layout_sidebar(self,event):
        s=self.s;self.compact=event.height<780*s
        height=round((140 if self.compact else 177)*s)
        if int(self.brand.cget('height'))!=height:self.brand.configure(height=height);self.paint_brand()
        budget=event.height-height-26*s-self.footer.winfo_reqheight()-52*s
        step=max(32*s,min(68*s,budget/len(self.navigation.names)))
        if abs(step-self.navigation.step)>.5:
            self.navigation.step=step;self.navigation.configure(height=round(step*len(self.navigation.names)));self.navigation.paint()
    def select(self,index):
        self.navigation.select(index);self.breadcrumb.configure(text=f'STINTLAB  / 0{index+1}')
        def frame(t):
            self.scroll.coords(self.item,0,round((1-t)*14*self.s))
            self.title.configure(fg=blend(T.MUTED,T.FG,t))
        self.motion.animate('page',frame,240)
