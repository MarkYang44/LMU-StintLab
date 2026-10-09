"""Local launchpad: HUD, categorized preferences and direct session actions."""
from i18n import tr,Label
import json
import os
import threading
from types import SimpleNamespace
from pathlib import Path
import tkinter as tk
from control_theme import T
from tkinter import ttk,filedialog,messagebox
from app_config import ROOT
from background import BackgroundTasks
from control_widgets import GlassCard,Pill,Switch,CardGrid,LaunchArtwork,backdrop,px
from control_fields import Select,Field
from paths import ASSETS
from control_shell import Shell
from control_list import SessionList
import branding
import control_settings
import renderer_config
import sampling
import vehiclelab
import endurance
import control_theme

PAGES=('运行与 HUD','赛事复盘','曲线对比','采样与遥测','图像与数据','赛道指南','车型图鉴')
SUBTITLES=('比赛中保持专注。所有控制，在这里。','你的赛事、圈速单与日志，集中在一处。','完整圈 / 距离对齐 / 轨迹与驾驶分析','分别配置输入采样、轮胎策略与耐力赛遥测。','RaceCom 原版报告与本地赛事包。','赛道特性、练习建议与车型选择。','车型优缺点、适配赛道与并排对比。')


class ControlCenter:
    def __init__(self,root=None,hud=None):
        # Closed Tcl interpreters can remain in widget cycles. Reclaim them on
        # their GUI thread before another image worker can trigger collection.
        import gc
        gc.collect()
        self.root=root or tk.Tk();self.hud=hud;self.closing=False;self.attached=hud is not None
        self.data_path=ROOT;self.guide_page=None;self.guide_state={};self.tasks=BackgroundTasks();self.items=[];self.scan_generation=0;self.scanning=False;self.page=0
        import i18n
        i18n.load(ROOT/'interface_settings.json')
        control_theme.load(ROOT/'interface_settings.json')
        self.root.title(tr('LMU Stintrix · 控制中心'));self.root.configure(bg=T.BG)
        self.root.protocol('WM_DELETE_WINDOW',self.hide if self.attached else self.close)
        from race_model import read_json
        self.reference_settings=read_json(ROOT/'reference_settings.json',{})
        self.reference_kind=tk.StringVar(self.root,value=self.reference_settings.get('kind','fastest'))
        self.reference_on=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('enabled',False)))
        self.reference_auto=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('automatic',True)))
        self.reference_locked=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('locked',False)))
        self.engine=SimpleNamespace(lock=threading.Lock(),reference=None,aligner=None)
        self.status=tk.StringVar(self.root,value=tr('就绪 · 记录仅保存在本机'))
        self.build_shell()
        branding.apply(self.root)
        # Bind to this toplevel only, leaving the HUD's high-rate event loop alone.
        self.root.bind('<MouseWheel>',self.wheel)
        self.show_page(0);backdrop(self.root)
        from control_repaint import Presentation
        self.presentation=Presentation(self.root);self.root._stintrix_presentation=self.presentation
        self.job=self.root.after(50,self.tick)
        self.repair_windows_entry()

    def build_shell(self):
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('Scope.Treeview',background=T.CARD,fieldbackground=T.CARD,foreground=T.FG)
        style.configure('Scope.Treeview.Heading',background=T.FIELD,foreground=T.MUTED)
        style.map('Scope.Treeview',background=[('selected',T.SELECT)],foreground=[('selected',T.FG)])
        style.configure('Lab.TCombobox',fieldbackground=T.FIELD,background=T.FIELD,foreground=T.FG,arrowcolor=T.MUTED,padding=7,borderwidth=0,font=('Microsoft YaHei UI',10))
        style.configure('TCombobox',fieldbackground=T.FIELD,background=T.FIELD,foreground=T.FG,arrowcolor=T.MUTED)
        style.map('TCombobox',fieldbackground=[('readonly',T.FIELD)],foreground=[('readonly',T.FG)],selectbackground=[('readonly',T.SELECT)],selectforeground=[('readonly',T.FG)])
        for kind in ('Entry','Spinbox'):
            for name,value in (('background',T.FIELD),('foreground',T.FG),('insertBackground',T.FG)):
                self.root.option_add('*'+kind+'.'+name,value)
        style.configure('Lab.Vertical.TScrollbar',background=T.EDGE,troughcolor=T.BG,borderwidth=0,arrowsize=0,width=px(self.root,7))
        style.layout('Lab.Vertical.TScrollbar',[('Vertical.Scrollbar.trough',{'sticky':'ns','children':[('Vertical.Scrollbar.thumb',{'expand':1,'sticky':'nswe'})]})])
        style.map('Lab.Vertical.TScrollbar',background=[('active',T.ACCENT)])
        style.configure('Lab.Horizontal.TScrollbar',background=T.EDGE,troughcolor=T.CARD,borderwidth=0,arrowsize=0,width=px(self.root,7))
        style.layout('Lab.Horizontal.TScrollbar',[('Horizontal.Scrollbar.trough',{'sticky':'ew','children':[('Horizontal.Scrollbar.thumb',{'expand':1,'sticky':'nswe'})]})])
        style.map('Lab.Horizontal.TScrollbar',background=[('active',T.ACCENT)])
        style.map('Lab.TCombobox',fieldbackground=[('readonly',T.FIELD)],foreground=[('readonly',T.FG)],selectbackground=[('readonly',T.FIELD)],selectforeground=[('readonly',T.FG)])
        self.root.option_add('*TCombobox*Listbox.background',T.FIELD);self.root.option_add('*TCombobox*Listbox.foreground',T.FG)
        self.root.option_add('*TCombobox*Listbox.selectBackground',T.SELECT)
        self.page_titles=PAGES;self.page_subtitles=SUBTITLES
        self.shell=Shell(self.root,PAGES,self.request_page,self.status,self.toggle_theme,self.toggle_language)
        self.scroll=self.shell.scroll;self.content=self.shell.content;self.content_item=self.shell.item
        self.title=self.shell.title;self.subtitle=self.shell.subtitle
        from control_pages import PageDeck
        self.pages=PageDeck(self,self.shell.content)
    def toggle_theme(self):self.set_theme('light' if T.mode=='dark' else 'dark')

    def set_theme(self,mode):
        if mode==T.mode:return
        try:control_theme.save(ROOT/'interface_settings.json',mode)
        except (OSError,ValueError) as error:self.status.set(tr('主题未保存：') + str(error));return
        previous=T.mode
        control_theme.set_mode(mode)
        self.rebuild_interface()
        backdrop(self.root)
        control_theme.recolor(self.root,previous)
        if self.active():self.hud.apply_theme()

    def toggle_language(self):
        import i18n
        target='en' if i18n.language=='zh' else 'zh'
        try:i18n.save(ROOT/'interface_settings.json',target)
        except (OSError,ValueError) as error:self.status.set(tr('语言未保存：')+str(error));return
        self.rebuild_interface()
        self.root.title(tr('LMU Stintrix · 控制中心'))
        self.status.set(tr('就绪 · 记录仅保存在本机'))
        i18n.refresh(self.root)

    def rebuild_interface(self):
        page=self.page;geometry=self.root.geometry();fraction=self.scroll.yview()[0]
        state={name:value.get() for name,value in vars(self).items() if isinstance(value,tk.Variable)}
        query=self.search.get() if self.tree else ''
        selected=self.tree.selection() if self.tree else ()
        table_position=self.tree.offset if self.tree else 0
        self.pages.dispose()
        self.shell.motion.cancel();self.shell.scroller.cancel();self.shell.navigation.motion.cancel()
        self.shell.side.destroy();self.shell.main.destroy();self.root.configure(bg=T.BG)
        self.build_shell();self.root.geometry(geometry);self.show_page(page)
        for name,value in state.items():
            variable=getattr(self,name,None)
            if isinstance(variable,tk.Variable):variable.set(value)
        if self.tree:self.search.set(query);self.populate(selected)
        self.root.update_idletasks();self.scroll.yview_moveto(fraction)
        if self.tree:self.tree.scroller.move(table_position)

    def label(self,parent,text,size=10,color=None,bold=False):
        return Label(parent,text='' if isinstance(text,tk.Variable) else text,textvariable=text if isinstance(text,tk.Variable) else None,
            bg=parent.cget('bg'),fg=color or T.FG,font=('Microsoft YaHei UI',size,'bold' if bold else 'normal'),anchor='w',justify='left')

    def card(self,title,subtitle='',parent=None):
        card=GlassCard(parent or self.content)
        if parent:parent.add(card)
        else:card.pack(fill='x',pady=(0,px(self.root,18)))
        body=card.body
        self.label(body,title,14,T.FG,True).pack(anchor='w',pady=(0,5))
        if subtitle:
            label=self.label(body,subtitle,9,T.MUTED);label.pack(fill='x',pady=(0,px(self.root,14)))
            label.bind('<Configure>',lambda e:label.configure(wraplength=max(100,e.width)))
        return body

    def button(self,parent,text,command,primary=False,width=140):
        button=Pill(parent,text,command,width,primary);button.pack(side='left',padx=(0,px(self.root,9)),pady=4);return button

    def row(self,parent):
        row=tk.Frame(parent,bg=parent.cget('bg'));row.pack(fill='x',pady=5);return row

    def choice(self,parent,label,var,choices,command=None):
        row=self.row(parent);caption=self.label(row,label,10,T.MUTED);caption.pack(side='left')
        box=Select(row,textvariable=var,values=choices,state='readonly',width=26)
        box.pack(side='right',padx=4);box.bind('<<ComboboxSelected>>',lambda _:command() if command else None)
        row.stacked=False
        def layout(event):
            stacked=event.width<caption.winfo_reqwidth()+box.winfo_reqwidth()+px(row,14)
            if stacked==row.stacked:return
            row.stacked=stacked;caption.pack_forget();box.pack_forget()
            if stacked:
                caption.pack(anchor='w',pady=(0,4));box.pack(fill='x',padx=4)
            else:
                caption.pack(side='left');box.pack(side='right',padx=4)
        row.bind('<Configure>',layout)
        return box

    def wheel(self,event):
        if str(event.widget).startswith(str(self.content)) and not isinstance(event.widget,(ttk.Treeview,ttk.Combobox,Select)):
            self.shell.scroller.add(-event.delta/120*px(self.root,65))
            return 'break'

    def show(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()
    def hide(self):self.root.withdraw()
    def active(self):
        return self.hud is not None and not self.hud.closing and self.hud.root.winfo_exists()

    def request_page(self,index):self.pages.request(index)

    def show_page(self,index,progressive=False):
        self.pages.cancel_request()
        self.page=index;self.progressive=progressive;self.scan_generation+=1;self.tree=None;self.guide_page=None
        self.shell.scroller.cancel()
        self.title.configure(text=PAGES[index]);self.subtitle.configure(text=SUBTITLES[index]);self.scroll.yview_moveto(0)
        if self.shell.navigation.selected!=index:self.shell.select(index)
        self.pages.mount(index,(self.run_page,self.review_page,self.compare_page,self.settings_page,self.data_page,self.tracks_page,self.cars_page)[index],progressive)

    def tracks_page(self):
        from control_guide import show
        show(self,'tracks')

    def cars_page(self):
        from control_guide import show
        show(self,'cars')

    def run_page(self):
        body=self.card('下一段 Stint，从这里开始','练习时显示 HUD；排位赛和正赛自动保存记录与报告')
        LaunchArtwork(body).pack(fill='x',pady=(0,px(self.root,7)))
        self.live_label=self.label(body,'等待启动',11,T.ACCENT);self.live_label.pack(anchor='w',pady=(0,10))
        row=self.row(body);self.button(row,'▶  启动 HUD',self.start,True,160);self.button(row,'停止并保存',self.stop_hud,False,140)
        self.button(row,'演示模式',lambda:self.start(True),False,120)
        grid=CardGrid(self.content);grid.pack(fill='x')
        body=self.card('油门 / 刹车 / 转向','输入通道、显示模式与波形窗口',grid)
        self.mode=tk.StringVar(self.root,value=self.hud.hud_mode.get() if self.active() else 'normal')
        modes={'标准面板':'normal','纯净 · 仅曲线':'curves','纯净 · 曲线 + 踏板 / 方向盘':'controls'}
        self.mode_label=tk.StringVar(self.root,value=next(k for k,v in modes.items() if v==self.mode.get()))
        self.choice(body,'显示模式',self.mode_label,list(modes),lambda:self.set_hud('mode',modes[self.mode_label.get()]))
        current=sampling.load_settings(ROOT/'settings.json');self.channel=tk.StringVar(self.root,value='游戏过滤后' if current['input_channel']=='filtered' else '原始输入')
        self.choice(body,'输入通道',self.channel,['原始输入','游戏过滤后'],lambda:self.set_hud('channel','filtered' if self.channel.get()=='游戏过滤后' else 'raw'))
        self.window=tk.StringVar(self.root,value=self.hud.window.get() if self.active() else '10')
        self.choice(body,'波形窗口 / 秒',self.window,['5','10','20'],lambda:self.set_hud('window',self.window.get()))
        row=self.row(body);self.button(row,'鼠标穿透 / 解锁',lambda:self.hud_action('toggle_clickthrough'),False,172)
        self.button(row,'性能诊断',lambda:self.hud_action('show_diagnostics'),False,130)
        body=self.card('附加遥测面板','按需开启，让比赛视野保持清爽',grid)
        vehicle=vehiclelab.load_settings(ROOT/'vehicle_settings.json');end=endurance.load_settings(ROOT/'endurance_settings.json')
        switches=[]
        for module,key,title in [('vehicle','tyres','四轮轮胎温度 / 胎压 / 胎况'),('vehicle','strategy','燃油、虚拟能量与续航策略'),('endurance','pit','进站计时与补给'),('endurance','stint','Stint 长距离节奏'),('endurance','weather','天气与赛道趋势')]:
            value=tk.BooleanVar(self.root,value=(vehicle if module=='vehicle' else end)[key+'_enabled'])
            Switch(body,title,value,lambda m=module,k=key,v=value:self.update_module(m,{k+'_enabled':v.get()})).pack(fill='x',pady=2)
            switches.append((module,key,value))

        channel=self.channel
        def refresh_run():
            channel.set('游戏过滤后' if sampling.load_settings(ROOT/'settings.json')['input_channel']=='filtered' else '原始输入')
            values={'vehicle':vehiclelab.load_settings(ROOT/'vehicle_settings.json'),'endurance':endurance.load_settings(ROOT/'endurance_settings.json')}
            for module,key,variable in switches:
                value=values[module][key+'_enabled']
                if variable.get()!=value:variable.set(value)
        self.pages.on_resume(refresh_run)

        body=self.card('Windows 快捷启动','添加后可在开始菜单 / Windows 搜索中输入 Stintrix 或 LMU 启动；迁移程序后可再次更新入口')
        row=self.row(body)
        self.button(row,'添加 / 更新开始菜单',self.register_app,False,185)
        self.button(row,'移除开始菜单入口',lambda:self.register_app(True),False,170)
        self.label(body,'可在 Windows 搜索结果中右键固定到开始菜单或任务栏。',9,T.MUTED).pack(anchor='w',pady=6)

    def register_app(self,remove=False):
        from windows_integration import register
        self.work(lambda:register(remove,verify=True),self.registration_result)

    def registration_result(self,result):
        if result['removed']:self.status.set(tr('开始菜单入口已移除，程序和数据仍保留'))
        elif result.get('recognized'):self.status.set(tr('Windows 应用目录已识别 LMU Stintrix · 可从开始菜单打开'))
        else:self.status.set(tr('快捷方式已更新，但 Windows 尚未列出应用；可稍后再次更新入口'))

    def repair_windows_entry(self):
        from windows_integration import needs_repair,register
        if self.attached or not needs_repair():return
        def done(result,error):
            if self.closing:return
            if error:self.status.set(tr('开始菜单入口未更新：') + error)
            else:self.registration_result(result)
        self.run_background(lambda:register(verify=True),done)

    def start(self,demo=False):
        if self.active():self.hud.root.lift();self.status.set(tr('HUD 已在运行；请先停止后切换真实 / 演示模式'));return
        if self.hud is not None and self.hud.root.winfo_exists():self.status.set(tr('正在保存上一场记录，请稍候'));return
        from hud import App
        self.hud=App(demo,root=tk.Toplevel(self.root),on_menu=self.show)
        if hasattr(self,'mode_label'):
            mode={'标准面板':'normal','纯净 · 仅曲线':'curves','纯净 · 曲线 + 踏板 / 方向盘':'controls'}[self.mode_label.get()]
            self.hud.hud_mode.set(mode);self.hud.apply_clean_mode();self.hud.window.set(self.window.get())
        self.status.set(tr('DEMO · 合成数据') if demo else tr('HUD 已启动 · 等待 LMU 遥测'))

    def stop_hud(self):
        if self.active():self.status.set(tr('正在结束录制并生成报告…'));self.hud.close()

    def hud_action(self,method):
        if self.active():getattr(self.hud,method)()
        else:self.status.set(tr('请先启动 HUD，再打开这项实时功能'))

    def set_hud(self,key,value):
        if key=='channel':self.update_module('sampling',{'input_channel':value})
        elif self.active():
            if key=='mode':self.hud.hud_mode.set(value);self.hud.apply_clean_mode()
            else:self.hud.window.set(value)

    def run_background(self,work,done):return self.tasks.submit(work,done)
    def work(self,work,done=None):
        self.status.set(tr('正在处理…'))
        def finish(result,error):
            if error:self.status.set(tr('操作未完成：') + error);messagebox.showerror('Stintrix',error,parent=self.root)
            else:
                self.status.set(tr('已完成 · 数据保存在本机'))
                if done:done(result)
        self.run_background(work,finish)

    def sessions(self,body,multiple=False,checkboxes=False):
        row=self.row(body);self.search=tk.StringVar(self.root);entry=Field(row,textvariable=self.search)
        entry.pack(side='left',fill='x',expand=True);entry.entry.bind('<KeyRelease>',lambda _:self.populate())
        self.button(row,'刷新记录',self.refresh,False,112)
        self.tree=SessionList(body,columns=('date','type','track','car','lap'),height=9,selectmode='extended' if multiple else 'browse',checkboxes=checkboxes)
        for key,title,width in [('date','时间（UTC）',180),('type','阶段',76),('track','赛道',200),('car','车辆',175),('lap','最快圈',92)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=px(self.root,width),minwidth=px(self.root,60),stretch=key in ('track','car'))
        self.tree.pack(fill='x',pady=(6,2));
        self.tree.bind('<Double-1>',lambda _:self.report('review.html'))
        self.tree.bind('<Return>',lambda _:self.report('review.html'))
        if checkboxes:
            row=self.row(body);self.selected_count=tk.StringVar(self.root,value='已选 0 场')
            self.button(row,'全选当前列表',lambda:self.tree.selection_set(self.tree.get_children()),False,128)
            self.button(row,'清除选择',lambda:self.tree.selection_set(()),False,108)
            self.label(row,self.selected_count,9,T.MUTED).pack(side='right',padx=8)
            self.tree.bind('<<TreeviewSelect>>',lambda _:self.update_selection_count())
        self.refresh()

    def update_selection_count(self):
        if self.tree and self.tree.checkboxes:self.selected_count.set(f'已选 {len(self.tree.selection())} 场 / 列表 {len(self.tree.get_children())} 场')

    def refresh(self):
        from library import inventory
        generation=self.scan_generation
        def done(result,error):
            if self.closing or generation!=self.scan_generation:return
            if error:self.status.set(error);return
            selected={self.items[int(i)]['folder'] for i in self.tree.selection()} if self.tree else set()
            self.items=result;chosen=[str(i) for i,item in enumerate(result) if item['folder'] in selected]
            self.populate(chosen);self.status.set(f"{len(result)}{tr(' 场本地记录 · 旧 Practice 记录仍保留')}")
        self.run_background(lambda:inventory(ROOT),done)

    def populate(self,selected=None):
        if self.tree is None or not self.tree.winfo_exists():return
        selected=self.tree.selection() if selected is None else selected;query=self.search.get().strip().casefold();rows=[]
        for i,value in enumerate(self.items):
            if query and query not in ' '.join(str(value.get(k,'')) for k in ('track','vehicle','session_type','date','driver')).casefold():continue
            time=value.get('time_s');lap=f'{int(time//60)}:{time%60:06.3f}' if time else '—'
            rows.append((str(i),(value['date'][:19].replace('T',' '),value['session_type'],value['track'],value['vehicle'],lap)))
        self.tree.replace(rows,selected)
        self.update_selection_count()

    def selection(self,count=1):
        chosen=[self.items[int(i)] for i in self.tree.selection()] if self.tree else []
        if count is None and not chosen:raise ValueError('请至少勾选一场赛事记录')
        if count is not None and len(chosen)!=count:raise ValueError(f'请选择 {count} 场赛事记录')
        if any(v['status'] in ('recording','write_error') for v in chosen):raise ValueError('请等记录完整保存后再操作')
        return chosen

    def with_selection(self,action,count=1):
        try:action(self.selection(count))
        except (ValueError,OSError) as error:self.status.set(str(error))

    def report(self,name):
        def action(items):
            folder=Path(items[0]['folder']);path=folder/name
            if name.endswith('.png'):
                from race_report import generate
                def build():
                    generate(folder)
                    if not path.is_file():raise ValueError('这场记录没有完成圈，未生成圈速单；可以查看比赛日志')
                    return str(path)
                self.work(build,os.startfile)
            elif path.is_file():os.startfile(path)
            else:
                from session_reports import make_report
                self.work(lambda:(make_report(folder),str(path))[1],os.startfile)
        self.with_selection(action)

    def review_page(self):
        body=self.card('赛事资料库','搜索时间、阶段、赛道或车辆 · 双击打开赛事复盘')
        self.sessions(body,True,True)
        row=self.row(body);self.button(row,'赛事 Review',lambda:self.report('review.html'),True,140)
        self.button(row,'查看圈速单',lambda:self.report('圈速单.png'),False,130);self.button(row,'查看比赛日志',lambda:self.report('比赛日志.png'),False,140)
        from control_delete import remove
        self.button(row,'删除选中赛事',lambda:remove(self),False,160)
        row=self.row(body);self.button(row,'同场圈 A / 圈 B',self.selected_laps,False,160);self.button(row,'导出赛事包',self.export_package,False,140)
        self.button(row,'完整记录管理',self.library,False,150)

    def compare_page(self):
        body=self.card('圈速对比','同场任意完整圈，或选择两场相同车辆 / 赛道的最快圈；Ctrl 多选赛事')
        self.sessions(body,True);row=self.row(body)
        self.button(row,'圈 A / 圈 B 选择器',self.selected_laps,True,180)
        self.button(row,'跨场最快圈对比',self.compare_sessions,False,180);self.button(row,'查看最快圈',lambda:self.report('fastest_lap.html'),False,150)
        body=self.card('比赛中参考圈','参考圈、锁定参考、自动匹配与稳定圈功能继续保留')
        row=self.row(body);self.button(row,'选择实时参考圈',lambda:self.hud_action('select_reference'),False,170)
        self.button(row,'开启 / 关闭参考',lambda:self.toggle_reference(),False,180)

    def toggle_reference(self):
        if self.active():self.hud.reference_on.set(not self.hud.reference_on.get());self.hud.apply_reference()
        else:self.status.set(tr('请先启动 HUD'))

    def selected_laps(self):
        from management import show_lap_selection
        self.with_selection(lambda items:show_lap_selection(self,ROOT,Path(items[0]['folder'])))

    def compare_sessions(self):
        from laps import write_compare
        def action(items):
            if any(items[0][k]!=items[1][k] for k in ('track','vehicle')):raise ValueError('请选择相同赛道、相同车辆的两场赛事')
            if any(not v['fastest_file'] for v in items):raise ValueError('这两场赛事需要已有最快完整圈')
            def build():
                records=[json.loads((Path(v['folder'])/v['fastest_file']).read_text(encoding='utf-8')) for v in items]
                path=ROOT/'FastestLapCompare.html';write_compare(path,ASSETS/'compare.html',records);return str(path)
            self.work(build,os.startfile)
        self.with_selection(action,2)

    def library(self):
        if self.active():self.hud.show_library()
        else:
            from management import show_library
            from session_reports import render_review,make_report
            show_library(self,ROOT,render_review,make_report)

    def apply_reference(self):
        from storage import atomic_json
        self.reference_settings.update(enabled=self.reference_on.get(),automatic=self.reference_auto.get(),
            locked=self.reference_locked.get(),kind=self.reference_kind.get())
        atomic_json(ROOT/'reference_settings.json',self.reference_settings)
        self.status.set(tr('参考圈已保存，启动 HUD 时自动载入'))

    def form(self,body,module,specs,choices=()):
        source={'sampling':sampling,'vehicle':vehiclelab,'endurance':endurance}[module].load_settings(ROOT/({'sampling':'settings.json','vehicle':'vehicle_settings.json','endurance':'endurance_settings.json'}[module]))
        variables={};baseline={key:str(value) for key,value in source.items()}
        for key,label in specs:
            row=self.row(body);self.label(row,label,10,T.MUTED).pack(side='left')
            var=tk.StringVar(self.root,value=str(source[key]));variables[key]=var
            Field(row,textvariable=var,width=15,font=('Segoe UI',11)).pack(side='right',padx=4)
            yield
        for key,label,options in choices:
            var=tk.StringVar(self.root,value=source[key]);variables[key]=var;self.choice(body,label,var,options)
            yield
        row=self.row(body)
        def save():
            try:self.update_module(module,{key:variables[key].get() for key in variables})
            except (ValueError,OSError) as e:messagebox.showerror(tr('设置未保存'),str(e),parent=self.root)
        self.button(row,'应用并保存',save,True,145)
        def refresh_form():
            current={'sampling':sampling,'vehicle':vehiclelab,'endurance':endurance}[module].load_settings(ROOT/({'sampling':'settings.json','vehicle':'vehicle_settings.json','endurance':'endurance_settings.json'}[module]))
            for key,variable in variables.items():
                value=variable.get();equal=value==baseline[key]
                if not equal:
                    try:equal=float(value)==float(baseline[key])
                    except ValueError:pass
                if equal:variable.set(str(current[key]))
            baseline.update({key:str(value) for key,value in current.items()})
        self.pages.register(module,variables,refresh_form)
        yield


    def update_module(self,module,values):
        control_settings.apply(module,values,self.hud if self.active() else None);self.status.set(tr('设置已保存') + (tr('并应用到 HUD') if self.active() else tr('，启动 HUD 时生效')))

    def settings_page(self):
        body=self.card('输入采样与 HUD 刷新','1–4000 Hz · sync 跟随采样目标；有效数据频率由游戏和硬件决定')
        yield from self.form(body,'sampling',[('fixed_hz','固定采样 / Hz'),('min_hz','动态最低 / Hz'),('max_hz','动态最高 / Hz'),
            ('change_pct_s','升频变化阈值 / % 每秒'),('hold_s','降频延迟 / 秒'),('brake_pct','刹车升频阈值 / %'),('draw_hz','手动绘制 / Hz')],
            [('mode','采样模式',['fixed','dynamic']),('draw_mode','绘制模式',['sync','manual'])])
        body=self.card('轮胎、燃油与能量策略')
        yield from self.form(body,'vehicle',[('record_hz','附加遥测记录 / Hz'),('history_laps','耗油统计圈数'),('reserve_l','燃油余量 / L'),('extra_finish_laps','保险圈数'),('target_value','手动赛程数值')],
            [('target_mode','赛程来源',['auto','laps','time']),('rate_mode','耗油统计',['conservative','median'])])
        from control_profile import show
        self.button(self.row(body),'车型轮胎阈值',lambda:show(self),False,160)
        body=self.card('进站、Stint 与天气')
        yield from self.form(body,'endurance',[('pit_limit_kmh','进站限速 / km/h（0 关闭）'),('pit_tolerance_kmh','超速容差 / km/h'),('stationary_kmh','静止阈值 / km/h'),
            ('warmup_laps','暖胎观察圈数'),('pace_window','节奏统计窗口 / 圈'),('weather_window_s','天气趋势窗口 / 秒'),('rain_change','雨强提醒阈值 / 0–1'),
            ('wetness_change','湿度提醒阈值 / 0–1'),('temp_change_c','温度提醒阈值 / °C'),('alert_cooldown_s','提醒冷却 / 秒')])

    def data_page(self):
        body=self.card('RaceCom 原版图像','直接调用你自己的 Image Generate.exe；原版版式、字体、颜色与车辆校准保留')
        config=renderer_config.load();self.renderer_mode=tk.StringVar(self.root,value=config['mode']);self.renderer_path=tk.StringVar(self.root,value=config['executable'])
        self.choice(body,'生成方式',self.renderer_mode,['racecom','native'])
        entry=Field(body,textvariable=self.renderer_path,font=('Segoe UI',10));entry.pack(fill='x',pady=8)
        def choose():
            path=filedialog.askopenfilename(parent=self.root,title=tr('选择 RaceCom 的 Image Generate.exe'),filetypes=[('RaceCom 图像生成器','*.exe')])
            if path:self.renderer_path.set(path)
        def save():
            try:renderer_config.save(dict(mode=self.renderer_mode.get(),executable=self.renderer_path.get()));self.status.set(tr('图像生成器已配置；下一场结束自动生成到赛事文件夹'))
            except (ValueError,OSError) as e:messagebox.showerror(tr('配置未保存'),str(e),parent=self.root)
        row=self.row(body);self.button(row,'选择生成器',choose,False,140);self.button(row,'保存配置',save,True,140)
        self.label(body,'racecom = 原版版式；native = Stintrix 兼容版式。\nGitHub 下载包不包含 RaceCom 程序、商标图片或个人记录。',9,T.MUTED).pack(anchor='w',pady=8)
        body=self.card('赛事包 / ZIP','勾选多场或全选当前列表，一次导出；每场一个 ZIP，导入时校验并新建记录')
        self.sessions(body,True,True);row=self.row(body);self.button(row,'批量导出选中赛事',self.export_package,True,180);self.button(row,'导入赛事包',self.import_package,False,145)
        self.button(row,'导入官方遥测',self.import_native,False,155)

    def export_package(self):
        from session_archive import export_session,transfer_batch
        if getattr(self,'exporting',False):self.status.set(tr('赛事包正在导出，请等待完成'));return
        def action(items):
            directory=filedialog.askdirectory(parent=self.root,title=tr('选择赛事包导出目录'))
            if not directory:return
            keys=[item['key'] for item in items];self.exporting=True
            self.status.set(f"{tr('正在导出 ')}{len(keys)}{tr(' 场赛事，每场一个 ZIP…')}")
            def done(result,error):
                self.exporting=False
                if error:self.status.set(tr('导出未完成：') + error);messagebox.showerror('Stintrix',error,parent=self.root);return
                self.status.set(f"{tr('已导出 ')}{len(result['items'])}{tr(' 场赛事 · 失败 ')}{len(result['errors'])}{tr(' 场')}")
                if result['items']:os.startfile(directory)
                if result['errors']:
                    details='\n'.join(v['item']+'：'+v['error'] for v in result['errors'][:10])
                    messagebox.showwarning(tr('部分赛事未导出'),details,parent=self.root)
            self.run_background(lambda:transfer_batch(keys,lambda key:export_session(ROOT,key,Path(directory))),done)
        self.with_selection(action,None)

    def import_package(self):
        from session_archive import import_session
        path=filedialog.askopenfilename(parent=self.root,title=tr('导入赛事包'),filetypes=[('赛事 ZIP','*.zip')])
        if path:self.work(lambda:import_session(ROOT,path),lambda _:self.refresh())

    def import_native(self):
        from telemetry_import import import_recording
        from session_reports import make_report
        path=filedialog.askopenfilename(parent=self.root,title=tr('导入 LMU 官方遥测（只读）'),filetypes=[('LMU 遥测','*.duckdb')])
        if path:
            def work():
                folder=import_recording(path,ROOT);make_report(folder);return folder
            self.work(work,lambda _:self.refresh())

    def tick(self):
        if self.closing:return
        if self.hud and not self.hud.root.winfo_exists():self.hud=None
        for done,result,error in self.tasks.completions():
            try:done(result,error)
            except (OSError,ValueError,tk.TclError) as e:self.status.set(tr('操作未完成：') + str(e))
        if self.page==0 and self.active():
            engine=self.hud.engine;poll,fresh=engine.actual_rates()
            self.live_label.configure(text=f"{engine.status}{tr(' · 读取 ')}{poll:.0f}{tr(' / 有效 ')}{fresh:.0f} Hz")
            values=[(self.channel,'游戏过滤后' if self.hud.input_channel.get()=='filtered' else '原始输入'),
                (self.mode_label,{'normal':'标准面板','curves':'纯净 · 仅曲线','controls':'纯净 · 曲线 + 踏板 / 方向盘'}[self.hud.hud_mode.get()]),
                (self.window,self.hud.window.get())]
            for variable,value in values:
                if variable.get()!=value:variable.set(value)
        elif self.page==0:self.live_label.configure(text=tr('已停止') if self.hud else tr('等待启动'))
        self.job=self.root.after(100,self.tick)

    def close(self):
        if not self.closing:
            self.closing=True;self.presentation.cancel();self.pages.cancel_request();self.pages.cancel_build();self.tasks.close();self.root.after_cancel(self.job);self.shell.motion.cancel();self.shell.navigation.motion.cancel();self.shell.scroller.cancel()
            if self.active():self.hud.close()
        if self.tasks.busy or (self.hud and self.hud.root.winfo_exists()):self.root.after(50,self.close);return
        for _ in self.tasks.completions():pass
        variables=[value for value in vars(self).items() if isinstance(value[1],tk.Variable)]
        forms=[value for page in self.pages.pages.values() for form in page.forms.values() for value in form.values()]
        self.pages.dispose();self.shell.navigation.command=None
        self.root._brand_images=[]
        for name,variable in variables:
            variable.__del__();variable._tk=None
        for variable in forms:
            if variable._tk is not None:variable.__del__();variable._tk=None
        self.root.destroy()


def show_attached(hud):
    center=getattr(hud,'control_center',None)
    if center and center.root.winfo_exists():center.show()
    else:
        center=ControlCenter(tk.Toplevel(hud.root),hud);hud.control_center=center
