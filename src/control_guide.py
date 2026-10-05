"""Complete native guide pages: spacious cards, private favorites and comparison."""
import tkinter as tk
from tkinter import ttk
from control_theme import T
from control_fields import Field
from control_widgets import px
from guidebook import catalog
from guide_library import Library
from guide_cards import Cards


class GuidePage:
    PAGE_SIZE=3
    def __init__(self,center,view):
        self.center=center;self.view=view;self.job=None;self.closed=False
        self.library=Library(catalog(),center.data_path/'guide_settings.json')
        import i18n
        self.library.language=i18n.language
        self.state=center.guide_state.setdefault(view,{})
        for key,value in dict(query='',group='',car='',favorite='',page=0,comparison=[],mode='browse').items():self.state.setdefault(key,value)
        self.state.setdefault('expanded',[])
        self.cards=Cards(self);self.rows=[];self.card_count=0;self.variables={};self.compare_buttons={};self.favorite_buttons={}
        self.build();self.container.bind('<Destroy>',self.dispose,add='+');self.render()

    def tr(self,zh,en):return self.library.tr(zh,en)
    def dispose(self,event):
        if event.widget is not self.container:return
        self.closed=True
        try:self.variables['query'].trace_remove('write',self.query_trace)
        except tk.TclError:pass
        if self.job:
            try:self.center.root.after_cancel(self.job)
            except tk.TclError:pass

    def build(self):
        center=self.center;tr=self.tr
        self.container=tk.Frame(center.content,bg=T.BG);self.container.pack(fill='x')
        body=self.cards.surface(self.container,tr('赛道资料库','Circuit library') if self.view=='tracks' else tr('车型资料库','Car library'),
            f"GTD {self.library.data['content_version']} · {self.library.data['updated']} · {tr('全部资料在菜单内展示','All content shown in this menu')}")
        row=center.row(body);query=tk.StringVar(center.root,value=self.state['query']);self.variables['query']=query
        center.label(row,tr('搜索  ','Search  '),10,T.MUTED).pack(side='left')
        entry=Field(row,textvariable=query,font=(T.FONT,11))
        entry.pack(side='left',fill='x',expand=True);self.search_entry=entry.entry
        self.query_trace=query.trace_add('write',lambda *_:self.filter_changed())
        class_values={tr('全部组别','All classes'):'','LMGT3':'LMGT3','Hypercar':'Hypercar'}
        car_values={tr('全部车型','All cars'):'',**{item['name']:item['slug'] for item in self.library.data['cars'].values()}}
        favorite_values={tr('全部内容','All content'):'',tr('收藏的车型','Favorite cars'):'cars'}
        if self.view=='tracks':favorite_values[tr('收藏的赛道','Favorite circuits')]='tracks'
        self.choices={}
        for key,title,values in [('group',tr('组别','Class'),class_values),('car',tr('车型','Car'),car_values),('favorite',tr('收藏','Favorites'),favorite_values)]:
            variable=tk.StringVar(center.root,value=next((name for name,value in values.items() if value==self.state[key]),next(iter(values))))
            self.variables[key]=variable;self.choices[key]=values
            box=center.choice(body,title,variable,list(values),self.filter_changed);box.configure(width=35)
        row=center.row(body);center.button(row,tr('重置筛选','Reset filters'),self.reset,width=132)
        center.button(row,'English' if self.library.language=='zh' else '中文',self.language,width=115)
        center.button(row,tr('上一页','Previous'),lambda:self.turn(-1),width=100)
        center.button(row,tr('下一页','Next'),lambda:self.turn(1),width=100)
        self.result=center.label(body,'',10,T.ACCENT);self.result.pack(fill='x',pady=(10,0))
        self.cards.text(body,tr('资料参考：','Reference: ')+self.library.data['game_reference']+' · '+tr('实测验证：','Build-validated: ')+f"{self.library.data['validated_recommendations']}/{self.library.data['total_recommendations']}",9,T.MUTED)
        self.selection= self.cards.surface(self.container,tr('车型 / 推荐对比','Car / recommendation comparison'))
        self.selected_label=self.cards.text(self.selection,'',10,T.MUTED)
        row=center.row(self.selection)
        center.button(row,tr('查看对比','View comparison'),self.compare,True,width=145)
        center.button(row,tr('清空选择','Clear selection'),self.clear,width=125)
        center.button(row,tr('返回资料列表','Back to library'),self.browse,width=155)
        self.results=tk.Frame(self.container,bg=T.BG);self.results.pack(fill='x')
        body=self.cards.surface(self.container,tr('资料翻页','Library pages'))
        row=center.row(body);center.button(row,tr('上一页','Previous'),lambda:self.turn(-1),width=115)
        center.button(row,tr('下一页','Next'),lambda:self.turn(1),width=115)
        self.page_label=center.label(row,'',10,T.MUTED);self.page_label.pack(side='right',padx=10)
        self.cards.text(body,tr('文字来自 GTD；图片来源 Le Mans Ultimate / Studio 397。保留原资料日期和未验证标记。','Content adapted from GTD; artwork credited to Le Mans Ultimate / Studio 397. Original dates and unverified markers retained.'),9,T.MUTED)

    def filter_changed(self):
        self.state['query']=self.variables['query'].get()
        for key,values in self.choices.items():self.state[key]=values.get(self.variables[key].get(),'')
        self.state['page']=0;self.state['mode']='browse'
        if self.job:self.center.root.after_cancel(self.job)
        self.job=self.center.root.after(180,self.render)

    def render(self):
        self.job=None
        if self.closed:return
        fraction=self.center.scroll.yview()[0]
        for child in self.results.winfo_children():child.destroy()
        self.card_count=0;self.compare_buttons={};self.favorite_buttons={};self.rows=self.library.rows(self.view,self.state)
        if self.view=='tracks':text=self.tr('条赛道','circuits')+f" · {sum(len(recs) for _,recs in self.rows)} "+self.tr('条推荐','recommendations')
        else:text=self.tr('台车型','cars')
        self.result.configure(text=f'{len(self.rows)} '+text)
        self.update_selection()
        if self.state['mode']=='compare':
            for index,key in enumerate(self.state['comparison']):
                car,rec=self.library.item(key)
                if car:
                    self.cards.text(self.results,self.tr('对比 ','Comparison ')+chr(65+index),12,T.ACCENT,True)
                    self.cards.car(self.results,car,rec,True);self.card_count+=1
            self.page_label.configure(text=self.tr('对比中 · 保留原赛道上下文','Comparing · original circuit context retained'))
        else:
            pages=max(1,(len(self.rows)+self.PAGE_SIZE-1)//self.PAGE_SIZE)
            self.state['page']=max(0,min(pages-1,self.state['page']));start=self.state['page']*self.PAGE_SIZE
            for item,recs in self.rows[start:start+self.PAGE_SIZE]:
                if self.view=='tracks':self.cards.track(self.results,item,recs)
                else:self.cards.car(self.results,item)
                self.card_count+=1
            if not self.rows:self.cards.text(self.results,self.tr('没有匹配的资料，试试重置筛选。','No matches. Try resetting filters.'),12,T.MUTED)
            self.page_label.configure(text=f"{self.state['page']+1} / {pages} · "+self.tr('每页 3 张完整卡片','3 complete cards per page'))
        self.center.root.update_idletasks();self.center.scroll.yview_moveto(fraction)
        self.center.status.set(self.tr('完整原生图文 · 收藏仅保存在本机','Complete native library · favorites remain local'))

    def update_selection(self):
        self.selected_label.configure(text='\n'.join(self.library.name(key) for key in self.state['comparison']) or self.tr('选择 2–3 项进行对比。','Choose 2–3 items to compare.'))
        panel=self.selection.master
        if self.state['comparison']:panel.pack(fill='x',pady=(0,px(panel,18)),before=self.results)
        else:panel.pack_forget()

    def favorite(self,kind,slug):
        try:self.library.favorite(kind,slug)
        except OSError as error:self.center.status.set(self.tr('收藏保存失败：','Could not save favorite: ')+str(error));return
        if self.state['favorite']:self.render()
        else:
            for button in self.favorite_buttons.get((kind,slug),[]):
                button.label=('★ ' if slug in self.library.favorites[kind] else '☆ ')+self.tr('收藏','Favorite');button.paint()
    def select(self,key):
        if not self.library.toggle_comparison(self.state['comparison'],key):self.center.status.set(self.tr('最多选择 3 项，请先移除一项。','Select up to 3 items; remove one first.'));return
        if self.state['mode']=='compare':
            if len(self.state['comparison'])<2:self.state['mode']='browse'
            self.render()
        else:
            self.update_selection()
            for button in self.compare_buttons.get(key,[]):
                button.label=self.tr('移出对比','Remove') if key in self.state['comparison'] else self.tr('加入对比','Compare');button.primary=key in self.state['comparison'];button.paint()
            self.center.status.set(self.tr('已选 ','Selected ')+str(len(self.state['comparison']))+'/3')
    def compare(self):
        if len(self.state['comparison'])<2:self.center.status.set(self.tr('请先选择至少 2 项。','Choose at least 2 items first.'));return
        self.state['mode']='compare';self.render();self.center.scroll.yview_moveto(0)
    def clear(self):self.state['comparison'].clear();self.state['mode']='browse';self.render()
    def browse(self):self.state['mode']='browse';self.render();self.center.scroll.yview_moveto(0)
    def reset(self):
        self.state.update(query='',group='',car='',favorite='',page=0,mode='browse')
        self.variables['query'].set('')
        for key,values in self.choices.items():self.variables[key].set(next(iter(values)))
        self.filter_changed()
    def language(self):self.center.toggle_language()
    def turn(self,delta):
        self.state['mode']='browse';self.state['page']+=delta;self.render();self.center.scroll.yview_moveto(0)
    def jump(self,view,slug):
        target=self.center.guide_state.setdefault(view,{})
        target.update(query=self.library.data[view][slug]['name'],group='',car='',favorite='',page=0,mode='browse')
        self.center.show_page(5 if view=='tracks' else 6)


def show(center,view):
    center.guide_page=GuidePage(center,view)
