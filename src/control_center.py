"""Local launchpad: HUD, categorized preferences and direct session actions."""
import json
import os
import threading
from types import SimpleNamespace
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app_config import ROOT
from background import BackgroundTasks
from control_widgets import BG,CARD,FG,MUTED,ACCENT,GlassCard,Pill,backdrop
from paths import ASSETS
import control_settings
import renderer_config
import sampling
import vehiclelab
import endurance

PAGES=('运行与 HUD','赛事复盘','曲线对比','采样与遥测','图像与数据')
SUBTITLES=('比赛中保持专注。所有控制，在这里。','你的赛事、圈速单与日志，集中在一处。','完整圈 / 距离对齐 / 轨迹与驾驶分析','分别配置输入采样、轮胎策略与耐力赛遥测。','RaceCom 原版报告与本地赛事包。')


class ControlCenter:
    def __init__(self,root=None,hud=None):
        self.root=root or tk.Tk();self.hud=hud;self.closing=False;self.attached=hud is not None
        self.tasks=BackgroundTasks();self.items=[];self.scan_generation=0;self.scanning=False;self.page=0
        self.root.title('LMU StintLab · 控制中心');self.root.geometry('1160x800');self.root.minsize(980,680);self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW',self.hide if self.attached else self.close)
        from race_model import read_json
        self.reference_settings=read_json(ROOT/'reference_settings.json',{})
        self.reference_kind=tk.StringVar(self.root,value=self.reference_settings.get('kind','fastest'))
        self.reference_on=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('enabled',False)))
        self.reference_auto=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('automatic',True)))
        self.reference_locked=tk.BooleanVar(self.root,value=bool(self.reference_settings.get('locked',False)))
        self.engine=SimpleNamespace(lock=threading.Lock(),reference=None,aligner=None)
        self.status=tk.StringVar(self.root,value='就绪 · 记录仅保存在本机')
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('Lab.Treeview',background=CARD,foreground=FG,fieldbackground=CARD,rowheight=38,borderwidth=0,font=('Microsoft YaHei UI',9))
        style.configure('Lab.Treeview.Heading',background='#273c55',foreground=MUTED,relief='flat',font=('Microsoft YaHei UI',9,'bold'))
        style.map('Lab.Treeview',background=[('selected','#365777')],foreground=[('selected',FG)])
        style.configure('Lab.TCombobox',fieldbackground='#293e57',background='#293e57',foreground=FG,arrowcolor=MUTED)
        style.map('Lab.TCombobox',fieldbackground=[('readonly','#293e57')],foreground=[('readonly',FG)],selectbackground=[('readonly','#293e57')],selectforeground=[('readonly',FG)])
        sidebar=tk.Frame(self.root,bg='#132035',width=216);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        self.label(sidebar,'STINTLAB',23,FG,True).pack(anchor='w',padx=25,pady=(36,1))
        self.label(sidebar,'LE MANS ULTIMATE',9,ACCENT).pack(anchor='w',padx=27,pady=(0,40))
        self.nav=[]
        for i,name in enumerate(PAGES):
            button=tk.Button(sidebar,text=f'  {i+1:02}    {name}',anchor='w',font=('Microsoft YaHei UI',11),bg='#132035',fg=MUTED,
                activebackground='#2a425d',activeforeground=FG,relief='flat',bd=0,padx=10,pady=14,cursor='hand2',command=lambda n=i:self.show_page(n))
            button.pack(fill='x',padx=13,pady=4);self.nav.append(button)
        foot=tk.Frame(sidebar,bg='#132035');foot.pack(side='bottom',fill='x',padx=26,pady=28)
        self.label(foot,'LOCAL FIRST',9,ACCENT,True).pack(anchor='w')
        self.label(foot,'Qualify + Race 录制\nPractice / Warmup 仅显示',9,MUTED).pack(anchor='w',pady=9)
        main=tk.Frame(self.root,bg=BG);main.pack(side='left',fill='both',expand=True,padx=28,pady=(24,12))
        header=tk.Frame(main,bg=BG);header.pack(fill='x',pady=(4,17))
        self.title=self.label(header,'',24,FG,True);self.title.pack(anchor='w');self.subtitle=self.label(header,'',10,MUTED);self.subtitle.pack(anchor='w',pady=(5,0))
        self.label(main,self.status,9,MUTED).pack(side='bottom',fill='x',pady=(10,0))
        viewport=tk.Frame(main,bg=BG);viewport.pack(fill='both',expand=True)
        self.scroll=tk.Canvas(viewport,bg=BG,highlightthickness=0);bar=ttk.Scrollbar(viewport,orient='vertical',command=self.scroll.yview)
        bar.pack(side='right',fill='y');self.scroll.pack(side='left',fill='both',expand=True);self.scroll.configure(yscrollcommand=bar.set)
        self.content=tk.Frame(self.scroll,bg=BG);self.content_item=self.scroll.create_window(0,0,anchor='nw',window=self.content)
        self.scroll.bind('<Configure>',lambda e:self.scroll.itemconfigure(self.content_item,width=e.width))
        self.content.bind('<Configure>',lambda e:self.scroll.configure(scrollregion=self.scroll.bbox('all')))
        # Bind to this toplevel only, leaving the HUD's high-rate event loop alone.
        self.root.bind('<MouseWheel>',self.wheel)
        self.show_page(0);backdrop(self.root);self.job=self.root.after(50,self.tick)

    def label(self,parent,text,size=10,color=FG,bold=False):
        return tk.Label(parent,text='' if isinstance(text,tk.Variable) else text,textvariable=text if isinstance(text,tk.Variable) else None,
            bg=parent.cget('bg'),fg=color,font=('Microsoft YaHei UI',size,'bold' if bold else 'normal'),anchor='w',justify='left')

    def card(self,title,subtitle=''):
        card=GlassCard(self.content);card.pack(fill='x',pady=(0,16));body=card.body
        self.label(body,title,14,FG,True).pack(anchor='w',pady=(0,5))
        if subtitle:self.label(body,subtitle,9,MUTED).pack(anchor='w',pady=(0,14))
        return body

    def button(self,parent,text,command,primary=False,width=140):
        button=Pill(parent,text,command,width,primary);button.pack(side='left',padx=(0,9),pady=4);return button

    def row(self,parent):
        row=tk.Frame(parent,bg=parent.cget('bg'));row.pack(fill='x',pady=5);return row

    def choice(self,parent,label,var,choices,command=None):
        row=self.row(parent);self.label(row,label,10,MUTED).pack(side='left')
        box=ttk.Combobox(row,textvariable=var,values=choices,state='readonly',style='Lab.TCombobox',width=26)
        box.pack(side='right',padx=4);box.bind('<<ComboboxSelected>>',lambda _:command() if command else None);return box

    def wheel(self,event):
        if str(event.widget).startswith(str(self.content)) and not isinstance(event.widget,(ttk.Treeview,ttk.Combobox)):
            self.scroll.yview_scroll(-int(event.delta/120),'units')

    def show(self):
        self.root.deiconify();self.root.lift();self.root.focus_force()
    def hide(self):self.root.withdraw()
    def active(self):
        return self.hud is not None and not self.hud.closing and self.hud.root.winfo_exists()

    def show_page(self,index):
        self.page=index;self.scan_generation+=1;self.tree=None
        for child in self.content.winfo_children():child.destroy()
        self.title.configure(text=PAGES[index]);self.subtitle.configure(text=SUBTITLES[index]);self.scroll.yview_moveto(0)
        for n,button in enumerate(self.nav):button.configure(bg='#2a405b' if n==index else '#132035',fg=FG if n==index else MUTED)
        (self.run_page,self.review_page,self.compare_page,self.settings_page,self.data_page)[index]()

    def run_page(self):
        body=self.card('Le Mans Ultimate','连接 LMU_Data · 练习时显示 HUD，排位赛和正赛自动录制')
        self.live_label=self.label(body,'等待启动',11,ACCENT);self.live_label.pack(anchor='w',pady=(0,10))
        row=self.row(body);self.button(row,'▶  启动 HUD',self.start,True,160);self.button(row,'停止并保存',self.stop_hud,False,140)
        self.button(row,'演示模式',lambda:self.start(True),False,120)
        body=self.card('油门 / 刹车 / 转向','原始输入与游戏过滤后输入可切换；HUD 绘制频率跟随采样设置')
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
        body=self.card('附加遥测面板','分模块启用；窗口位置、车型阈值和策略参数沿用已有设置')
        vehicle=vehiclelab.load_settings(ROOT/'vehicle_settings.json');end=endurance.load_settings(ROOT/'endurance_settings.json')
        for module,key,title in [('vehicle','tyres','四轮轮胎温度 / 胎压 / 胎况'),('vehicle','strategy','燃油、虚拟能量与续航策略'),('endurance','pit','进站计时与补给'),('endurance','stint','Stint 长距离节奏'),('endurance','weather','天气与赛道趋势')]:
            value=tk.BooleanVar(self.root,value=(vehicle if module=='vehicle' else end)[key+'_enabled'])
            tk.Checkbutton(body,text=title,variable=value,command=lambda m=module,k=key,v=value:self.update_module(m,{k+'_enabled':v.get()}),
                bg=CARD,fg=FG,selectcolor='#314860',activebackground=CARD,activeforeground=FG,font=('Microsoft YaHei UI',10),pady=5).pack(anchor='w')

    def start(self,demo=False):
        if self.active():self.hud.root.lift();self.status.set('HUD 已在运行；请先停止后切换真实 / 演示模式');return
        if self.hud is not None and self.hud.root.winfo_exists():self.status.set('正在保存上一场记录，请稍候');return
        from hud import App
        self.hud=App(demo,root=tk.Toplevel(self.root),on_menu=self.show)
        if hasattr(self,'mode_label'):
            mode={'标准面板':'normal','纯净 · 仅曲线':'curves','纯净 · 曲线 + 踏板 / 方向盘':'controls'}[self.mode_label.get()]
            self.hud.hud_mode.set(mode);self.hud.apply_clean_mode();self.hud.window.set(self.window.get())
        self.status.set('DEMO · 合成数据' if demo else 'HUD 已启动 · 等待 LMU 遥测')

    def stop_hud(self):
        if self.active():self.status.set('正在结束录制并生成报告…');self.hud.close()

    def hud_action(self,method):
        if self.active():getattr(self.hud,method)()
        else:self.status.set('请先启动 HUD，再打开这项实时功能')

    def set_hud(self,key,value):
        if key=='channel':self.update_module('sampling',{'input_channel':value})
        elif self.active():
            if key=='mode':self.hud.hud_mode.set(value);self.hud.apply_clean_mode()
            else:self.hud.window.set(value)

    def run_background(self,work,done):return self.tasks.submit(work,done)
    def work(self,work,done=None):
        self.status.set('正在处理…')
        def finish(result,error):
            if error:self.status.set('操作未完成：'+error);messagebox.showerror('StintLab',error,parent=self.root)
            else:
                self.status.set('已完成 · 数据保存在本机')
                if done:done(result)
        self.run_background(work,finish)

    def sessions(self,body,multiple=False):
        row=self.row(body);self.search=tk.StringVar(self.root);entry=tk.Entry(row,textvariable=self.search,bg='#293e57',fg=FG,insertbackground=FG,relief='flat',font=('Microsoft YaHei UI',10))
        entry.pack(side='left',fill='x',expand=True,ipady=8);entry.bind('<KeyRelease>',lambda _:self.populate())
        self.button(row,'刷新记录',self.refresh,False,112)
        self.tree=ttk.Treeview(body,columns=('date','type','track','car','lap'),show='headings',height=9,
            style='Lab.Treeview',selectmode='extended' if multiple else 'browse')
        for key,title,width in [('date','时间（UTC）',145),('type','阶段',76),('track','赛道',200),('car','车辆',175),('lap','最快圈',92)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,minwidth=60,stretch=key in ('track','car'))
        self.tree.pack(fill='x',pady=(6,8));self.tree.bind('<Double-1>',lambda _:self.report('review.html'))
        self.refresh()

    def refresh(self):
        from library import inventory
        generation=self.scan_generation
        def done(result,error):
            if self.closing or generation!=self.scan_generation:return
            if error:self.status.set(error);return
            self.items=result;self.populate();self.status.set(f'{len(result)} 场本地记录 · 旧 Practice 记录仍保留')
        self.run_background(lambda:inventory(ROOT),done)

    def populate(self):
        if self.tree is None or not self.tree.winfo_exists():return
        selected=self.tree.selection();self.tree.delete(*self.tree.get_children());query=self.search.get().strip().casefold()
        for i,value in enumerate(self.items):
            if query and query not in ' '.join(str(value.get(k,'')) for k in ('track','vehicle','session_type','date','driver')).casefold():continue
            time=value.get('time_s');lap=f'{int(time//60)}:{time%60:06.3f}' if time else '—'
            self.tree.insert('','end',iid=str(i),values=(value['date'][:19].replace('T',' '),value['session_type'],value['track'],value['vehicle'],lap))
        remaining=[s for s in selected if self.tree.exists(s)]
        if remaining:self.tree.selection_set(remaining)

    def selection(self,count=1):
        chosen=[self.items[int(i)] for i in self.tree.selection()] if self.tree else []
        if len(chosen)!=count:raise ValueError(f'请选择 {count} 场赛事记录')
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
        self.sessions(body)
        row=self.row(body);self.button(row,'赛事 Review',lambda:self.report('review.html'),True,140)
        self.button(row,'查看圈速单',lambda:self.report('圈速单.png'),False,130);self.button(row,'查看比赛日志',lambda:self.report('比赛日志.png'),False,140)
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
        else:self.status.set('请先启动 HUD')

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
        self.status.set('参考圈已保存，启动 HUD 时自动载入')

    def form(self,body,module,specs,choices=()):
        source={'sampling':sampling,'vehicle':vehiclelab,'endurance':endurance}[module].load_settings(ROOT/({'sampling':'settings.json','vehicle':'vehicle_settings.json','endurance':'endurance_settings.json'}[module]))
        variables={}
        for key,label in specs:
            row=self.row(body);self.label(row,label,10,MUTED).pack(side='left')
            var=tk.StringVar(self.root,value=str(source[key]));variables[key]=var
            tk.Entry(row,textvariable=var,bg='#293e57',fg=FG,insertbackground=FG,relief='flat',width=15,font=('Segoe UI',11)).pack(side='right',ipady=5,padx=4)
        for key,label,options in choices:
            var=tk.StringVar(self.root,value=source[key]);variables[key]=var;self.choice(body,label,var,options)
        row=self.row(body)
        def save():
            try:self.update_module(module,{key:variables[key].get() for key in variables})
            except (ValueError,OSError) as e:messagebox.showerror('设置未保存',str(e),parent=self.root)
        self.button(row,'应用并保存',save,True,145)

    def update_module(self,module,values):
        control_settings.apply(module,values,self.hud if self.active() else None);self.status.set('设置已保存'+('并应用到 HUD' if self.active() else '，启动 HUD 时生效'))

    def settings_page(self):
        body=self.card('输入采样与 HUD 刷新','1–4000 Hz · sync 跟随采样目标；有效数据频率由游戏和硬件决定')
        self.form(body,'sampling',[('fixed_hz','固定采样 / Hz'),('min_hz','动态最低 / Hz'),('max_hz','动态最高 / Hz'),
            ('change_pct_s','升频变化阈值 / % 每秒'),('hold_s','降频延迟 / 秒'),('brake_pct','刹车升频阈值 / %'),('draw_hz','手动绘制 / Hz')],
            [('mode','采样模式',['fixed','dynamic']),('draw_mode','绘制模式',['sync','manual'])])
        body=self.card('轮胎、燃油与能量策略')
        self.form(body,'vehicle',[('record_hz','附加遥测记录 / Hz'),('history_laps','耗油统计圈数'),('reserve_l','燃油余量 / L'),('extra_finish_laps','保险圈数'),('target_value','手动赛程数值')],
            [('target_mode','赛程来源',['auto','laps','time']),('rate_mode','耗油统计',['conservative','median'])])
        from control_profile import show
        self.button(self.row(body),'车型轮胎阈值',lambda:show(self),False,160)
        body=self.card('进站、Stint 与天气')
        self.form(body,'endurance',[('pit_limit_kmh','进站限速 / km/h（0 关闭）'),('pit_tolerance_kmh','超速容差 / km/h'),('stationary_kmh','静止阈值 / km/h'),
            ('warmup_laps','暖胎观察圈数'),('pace_window','节奏统计窗口 / 圈'),('weather_window_s','天气趋势窗口 / 秒'),('rain_change','雨强提醒阈值 / 0–1'),
            ('wetness_change','湿度提醒阈值 / 0–1'),('temp_change_c','温度提醒阈值 / °C'),('alert_cooldown_s','提醒冷却 / 秒')])

    def data_page(self):
        body=self.card('RaceCom 原版图像','直接调用你自己的 Image Generate.exe；原版版式、字体、颜色与车辆校准保留')
        config=renderer_config.load();self.renderer_mode=tk.StringVar(self.root,value=config['mode']);self.renderer_path=tk.StringVar(self.root,value=config['executable'])
        self.choice(body,'生成方式',self.renderer_mode,['racecom','native'])
        entry=tk.Entry(body,textvariable=self.renderer_path,bg='#293e57',fg=FG,insertbackground=FG,relief='flat',font=('Segoe UI',10));entry.pack(fill='x',ipady=9,pady=8)
        def choose():
            path=filedialog.askopenfilename(parent=self.root,title='选择 RaceCom 的 Image Generate.exe',filetypes=[('RaceCom 图像生成器','*.exe')])
            if path:self.renderer_path.set(path)
        def save():
            try:renderer_config.save(dict(mode=self.renderer_mode.get(),executable=self.renderer_path.get()));self.status.set('图像生成器已配置；下一场结束自动生成到赛事文件夹')
            except (ValueError,OSError) as e:messagebox.showerror('配置未保存',str(e),parent=self.root)
        row=self.row(body);self.button(row,'选择生成器',choose,False,140);self.button(row,'保存配置',save,True,140)
        self.label(body,'racecom = 原版版式；native = StintLab 兼容版式。\nGitHub 下载包不包含 RaceCom 程序、商标图片或个人记录。',9,MUTED).pack(anchor='w',pady=8)
        body=self.card('赛事包 / ZIP','一场比赛打包为一个文件；导入校验后新建记录，不覆盖现有赛事')
        self.sessions(body);row=self.row(body);self.button(row,'导出选中赛事',self.export_package,True,165);self.button(row,'导入赛事包',self.import_package,False,145)
        self.button(row,'导入官方遥测',self.import_native,False,155)

    def export_package(self):
        from session_archive import export_session
        def action(items):
            directory=filedialog.askdirectory(parent=self.root,title='选择赛事包导出目录')
            if directory:self.work(lambda:export_session(ROOT,items[0]['key'],Path(directory)),lambda result:os.startfile(str(Path(result['path']).parent)))
        self.with_selection(action)

    def import_package(self):
        from session_archive import import_session
        path=filedialog.askopenfilename(parent=self.root,title='导入赛事包',filetypes=[('赛事 ZIP','*.zip')])
        if path:self.work(lambda:import_session(ROOT,path),lambda _:self.refresh())

    def import_native(self):
        from telemetry_import import import_recording
        from session_reports import make_report
        path=filedialog.askopenfilename(parent=self.root,title='导入 LMU 官方遥测（只读）',filetypes=[('LMU 遥测','*.duckdb')])
        if path:
            def work():
                folder=import_recording(path,ROOT);make_report(folder);return folder
            self.work(work,lambda _:self.refresh())

    def tick(self):
        if self.closing:return
        if self.hud and not self.hud.root.winfo_exists():self.hud=None
        for done,result,error in self.tasks.completions():
            try:done(result,error)
            except (OSError,ValueError,tk.TclError) as e:self.status.set('操作未完成：'+str(e))
        if self.page==0 and self.active():
            engine=self.hud.engine;poll,fresh=engine.actual_rates()
            self.live_label.configure(text=f'{engine.status} · 读取 {poll:.0f} / 有效 {fresh:.0f} Hz')
            values=[(self.channel,'游戏过滤后' if self.hud.input_channel.get()=='filtered' else '原始输入'),
                (self.mode_label,{'normal':'标准面板','curves':'纯净 · 仅曲线','controls':'纯净 · 曲线 + 踏板 / 方向盘'}[self.hud.hud_mode.get()]),
                (self.window,self.hud.window.get())]
            for variable,value in values:
                if variable.get()!=value:variable.set(value)
        elif self.page==0:self.live_label.configure(text='已停止' if self.hud else '等待启动')
        self.job=self.root.after(100,self.tick)

    def close(self):
        if not self.closing:
            self.closing=True;self.tasks.close();self.root.after_cancel(self.job)
            if self.active():self.hud.close()
        if self.tasks.busy or (self.hud and self.hud.root.winfo_exists()):self.root.after(50,self.close);return
        for _ in self.tasks.completions():pass
        self.root.destroy()


def show_attached(hud):
    center=getattr(hud,'control_center',None)
    if center and center.root.winfo_exists():center.show()
    else:
        center=ControlCenter(tk.Toplevel(hud.root),hud);hud.control_center=center
