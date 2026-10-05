"""Small optional endurance overlays; independent preferences, all off initially."""
import tkinter as tk
from control_theme import T
from tkinter import ttk,messagebox
from pathlib import Path
from storage import atomic_json
import endurance
from vehiclehud import fmt

TITLES={'pit':'进站分析','stint':'Stint 长距离','weather':'天气与赛道'}
NAMES={'rain_severity':'雨量强度','wetness':'湿度','track_temp_c':'赛道温度'}

class Panels:
    def __init__(self,app,root):
        self.app=app;self.root=Path(root);self.windows={};self.labels={};self.topmost={};self.passthrough={};self.dialog=None
        self.refresh_visibility();app.root.after(100,self.tick)

    def save(self):atomic_json(self.root/'endurance_settings.json',self.app.endurance_settings)

    def toggle(self,kind):
        self.app.endurance_settings[kind+'_enabled']=getattr(self.app,kind+'_on').get();self.save();self.refresh_visibility()

    def hide(self,kind):getattr(self.app,kind+'_on').set(False);self.toggle(kind)

    def create(self,kind):
        app=self.app;w=tk.Toplevel(app.root);w.title('StintLab · '+TITLES[kind]+' HUD')
        x,y=app.endurance_settings.get(kind+'_position',[1160,70+list(TITLES).index(kind)*225])
        w.geometry(f'370x210{int(x):+d}{int(y):+d}');w.configure(bg=T.BG);w.overrideredirect(True)
        w.attributes('-topmost',app.top.get());w.attributes('-alpha',.97);w.protocol('WM_DELETE_WINDOW',lambda:self.hide(kind))
        w.update_idletasks();handle=app.user32.GetParent(w.winfo_id()) or w.winfo_id();style=app.user32.GetWindowLongW(handle,-20)
        app.user32.SetWindowLongW(handle,-20,(style|0x40000)&~0x80)
        title=tk.Frame(w,bg=T.FIELD);title.pack(fill='x')
        tk.Label(title,text=TITLES[kind],fg=T.ACCENT,bg=T.FIELD,font=('Segoe UI',10,'bold')).pack(side='left',padx=10,pady=5)
        tk.Button(title,text='×',command=lambda:self.hide(kind),bg=T.FIELD,fg=T.FG,bd=0,padx=10).pack(side='right')
        origin=[None]
        def begin(e):origin[0]=(e.x_root-w.winfo_x(),e.y_root-w.winfo_y())
        def move(e):
            if origin[0]:w.geometry(f'{e.x_root-origin[0][0]:+d}{e.y_root-origin[0][1]:+d}')
        def end(e):app.endurance_settings[kind+'_position']=[w.winfo_x(),w.winfo_y()];self.save();origin[0]=None
        for child in (title,*title.winfo_children()):
            if isinstance(child,tk.Button):continue
            child.bind('<Button-1>',begin);child.bind('<B1-Motion>',move);child.bind('<ButtonRelease-1>',end)
        menu=tk.Menu(w,tearoff=False);menu.add_command(label='进站 / Stint / 天气设置',command=self.settings_dialog)
        menu.add_command(label='隐藏该面板',command=lambda:self.hide(kind));w.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
        body=tk.Frame(w,bg=T.BG);body.pack(fill='both',expand=True,padx=10,pady=5);labels={}
        for key,size in [('main',16),('detail',10),('context',9),('alert',9)]:
            label=tk.Label(body,text='—',fg=T.FG if key=='main' else T.MUTED,bg=T.BG,font=('Segoe UI',size,'bold' if key=='main' else 'normal'),anchor='w',justify='left',wraplength=345)
            label.pack(fill='x',pady=2);labels[key]=label
        foot=tk.Label(w,text='F8 穿透 / 解锁 · 右键设置',fg=T.MUTED,bg=T.BG,font=('Segoe UI',8),anchor='w')
        foot.pack(side='bottom',fill='x',padx=10,pady=(0,6),before=body);labels['foot']=foot
        self.windows[kind]=w;self.labels[kind]=labels;self.topmost[kind]=app.top.get();return w

    def refresh_visibility(self):
        for kind in TITLES:
            enabled=getattr(self.app,kind+'_on').get();w=self.windows.get(kind)
            if enabled:
                if w is None or not w.winfo_exists():w=self.create(kind)
                w.deiconify()
            elif w is not None and w.winfo_exists():w.withdraw()

    def tick(self):
        app=self.app
        if app.closing:return
        enabled=[k for k in TITLES if getattr(app,k+'_on').get()]
        if enabled:
            with app.engine.lock:latest=app.engine.latest;data=app.engine.endurance_monitor.snapshot() if latest else None
            for kind in enabled:
                w=self.windows.get(kind)
                if w is None:continue
                if self.topmost.get(kind)!=app.top.get():w.attributes('-topmost',app.top.get());self.topmost[kind]=app.top.get()
                if self.passthrough.get(kind)!=app.clickthrough:
                    handle=app.user32.GetParent(w.winfo_id()) or w.winfo_id();style=app.user32.GetWindowLongW(handle,-20)
                    app.user32.SetWindowLongW(handle,-20,(style|0x80000|0x20) if app.clickthrough else style&~0x20);self.passthrough[kind]=app.clickthrough
                labels=self.labels[kind]
                if data is None:
                    labels['main'].configure(text='等待遥测');labels['detail'].configure(text='');labels['context'].configure(text='');labels['alert'].configure(text='');continue
                d=data;p=d['pit'];pace=d['pace'];weather=d['weather'];trend=d['trends']
                if kind=='pit':
                    state={1:'已请求进站',2:'驶入坑道',3:'停站状态',4:'驶出坑道'}.get(d['pit_state'],'进站中')
                    labels['main'].configure(text=(state if d['pit_active'] else '上次进站')+'  '+fmt(p.get('duration_s') if p else None)+' s')
                    labels['detail'].configure(text='静止 '+fmt(p.get('stationary_s') if p else None)+' s · 补油 '+fmt(p.get('fuel_added_l') if p else None,2)+' L')
                    labels['context'].configure(text='车速 '+fmt(d['speed_kmh'])+' km/h · 限速器 '+('开' if d['speed_limiter']==1 else '关' if d['speed_limiter']==0 else '—')+'\n阈值 '+(fmt(d['pit_limit_kmh'],0)+' km/h（手动）' if d['pit_limit_kmh'] else '未设置；超速提示关闭'))
                    text='进站超速：超过手动阈值' if d['pit_warning'] else '记录起点或缺口：计时不完整' if p and (p['partial_start'] or p['gap']) else '只记录实测补给；不推断维修或换胎'
                    labels['alert'].configure(text=text,fg='#ff9c94' if d['pit_warning'] else T.MUTED)
                elif kind=='stint':
                    labels['main'].configure(text='Stint '+str(d['stint'])+' · '+str(pace['count'])+' 完整圈')
                    labels['detail'].configure(text='中位圈速 '+fmt(pace['median_s'],2)+' s · 波动 '+fmt(pace['spread_s'],2)+' s')
                    labels['context'].configure(text='后段变化 '+fmt(pace['drift_s'],2)+' s · 油量 '+fmt(d['fuel_l'])+' L\n暖胎观察 '+str(app.endurance_settings['warmup_laps'])+' 圈；初 / 后段各 '+str(app.endurance_settings['pace_window'])+' 圈')
                    labels['alert'].configure(text='条件变化；请结合天气和交通复盘' if pace['conditions_changed'] else '至少两组窗口后显示趋势；不诊断轮胎衰退',fg=T.MUTED)
                else:
                    labels['main'].configure(text='雨 '+fmt(None if weather['rain_severity'] is None else weather['rain_severity']*100,0)+'% · 湿 '+fmt(None if weather['wetness'] is None else weather['wetness']*100,0)+'%')
                    labels['detail'].configure(text='赛道 '+fmt(weather['track_temp_c'])+' °C · 气温 '+fmt(weather['ambient_temp_c'])+' °C')
                    labels['context'].configure(text=str(round(d['trend_span_s']))+' s 趋势：雨 '+fmt(None if trend['rain_severity'] is None else trend['rain_severity']*100)+' / 湿 '+fmt(None if trend['wetness'] is None else trend['wetness']*100)+' 百分点\n风 X/Z '+fmt(weather['wind_x_raw'])+' / '+fmt(weather['wind_z_raw'])+'（SDK 原值）')
                    a=d['alerts'][-1] if d['alerts'] else None
                    recent=a and latest['et']-(app.engine.endurance_monitor.origin or 0)-a['time_s']<=15
                    labels['alert'].configure(text=NAMES[a['field']]+'显著变化' if recent else '雨量为强度；湿度为全赛道统计',fg='#ffca80' if recent else T.MUTED)
                labels['foot'].configure(text=('DEMO · 合成遥测' if latest.get('demo') else 'LMU · 实测遥测')+' · F8 穿透 / 解锁')
        app.root.after(100,self.tick)

    def settings_dialog(self):
        if self.dialog and self.dialog.winfo_exists():self.dialog.lift();return
        app=self.app;w=tk.Toplevel(app.root);self.dialog=w;w.title('进站 / Stint / 天气设置')
        x=max(0,(w.winfo_screenwidth()-600)//2);y=max(0,(w.winfo_screenheight()-665)//2)
        w.geometry(f'600x665+{x}+{y}');w.configure(bg=T.BG);w.transient(app.root);w.attributes('-topmost',app.top.get());w.lift()
        frame=tk.Frame(w,bg=T.BG);frame.pack(fill='both',expand=True,padx=18,pady=14)
        tk.Label(frame,text='独立设置 · 不改变油刹采样与参考圈',bg=T.BG,fg=T.ACCENT,font=('Segoe UI',13,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,10))
        variables={}
        options=[('pit_limit_kmh','进站限速 km/h（0 = 不警告）'),('pit_tolerance_kmh','超速容差 km/h'),('stationary_kmh','静止速度阈值 km/h'),
            ('warmup_laps','每段开头暖胎观察圈数'),('pace_window','稳定初段 / 后段各取圈数'),('weather_window_s','天气趋势窗口 秒'),
            ('rain_change','雨强变化提醒阈值（0–1）'),('wetness_change','湿度变化提醒阈值（0–1）'),('temp_change_c','赛道温度变化提醒 °C'),('alert_cooldown_s','同类提醒冷却 秒')]
        for row,(key,label) in enumerate(options,1):
            tk.Label(frame,text=label,bg=T.BG,fg=T.FG,anchor='w').grid(row=row,column=0,sticky='w',pady=7)
            var=tk.StringVar(value=str(app.endurance_settings[key]));variables[key]=var;ttk.Entry(frame,textvariable=var,width=15).grid(row=row,column=1,sticky='ew',padx=(12,0))
        tk.Label(frame,text='限速必须按赛事规则手动填写。趋势统计需要完整圈。\n圈速变化不自动归因于轮胎；天气仅反映已观测状态。\n风向量保留 SDK 原始单位，不当作气象预报。',bg=T.BG,fg=T.MUTED,justify='left',wraplength=540).grid(row=11,column=0,columnspan=2,sticky='w',pady=14)
        def apply():
            try:
                new=endurance.settings({**app.endurance_settings,**{k:float(v.get()) for k,v in variables.items()}})
                app.endurance_settings=new
                with app.engine.lock:
                    app.engine.endurance_monitor.configure(new);rec=app.engine.recorder;rec.endurance_settings=new
                    elapsed=app.engine.latest['et']-rec.origin if app.engine.latest and rec.file else 0
                if rec.file:
                    with rec.meta_lock:rec.meta.setdefault('endurance_settings_history',[]).append(dict(time_s=elapsed,settings=new))
                self.save();w.destroy()
            except (ValueError,OSError) as e:messagebox.showerror('设置未保存',str(e),parent=w)
        tk.Button(frame,text='应用并保存',command=apply).grid(row=12,column=0,columnspan=2,sticky='ew',pady=8);frame.columnconfigure(1,weight=1)
