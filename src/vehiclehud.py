"""Optional compact tyre/strategy overlays and local per-car preferences."""
import copy
import tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
from storage import atomic_json
import vehiclelab

BG='#101925';FG='#dceafa';MUTED='#8da8c7';BLUE='#69b8ff'
fmt=lambda x,n=1:'—' if x is None else f'{x:.{n}f}'


class Panels:
    def __init__(self,app,root):
        self.app=app;self.root=Path(root);self.windows={};self.labels={};self.passthrough={};self.topmost={};self.dialog=None
        self.refresh_visibility();app.root.after(100,self.tick)

    def save(self):atomic_json(self.root/'vehicle_settings.json',self.app.vehicle_settings)

    def toggle(self,kind):
        self.app.vehicle_settings[kind+'_enabled']=getattr(self.app,kind+'_on').get();self.save();self.refresh_visibility()

    def hide(self,kind):
        getattr(self.app,kind+'_on').set(False);self.toggle(kind)

    def create(self,kind):
        w=tk.Toplevel(self.app.root);w.title('InputScope · '+('四轮轮胎 HUD' if kind=='tyres' else '燃油与能量 HUD'))
        width,height=(400,300) if kind=='tyres' else (400,280)
        x,y=self.app.vehicle_settings.get(kind+'_position',[740,70 if kind=='tyres' else 395])
        w.geometry(f'{width}x{height}{int(x):+d}{int(y):+d}');w.configure(bg=BG);w.overrideredirect(True);w.attributes('-topmost',True);w.attributes('-alpha',.97)
        w.protocol('WM_DELETE_WINDOW',lambda:self.hide(kind))
        w.update_idletasks()
        handle=self.app.user32.GetParent(w.winfo_id()) or w.winfo_id()
        style=self.app.user32.GetWindowLongW(handle,-20)
        self.app.user32.SetWindowLongW(handle,-20,(style|0x40000)&~0x80)
        title=tk.Frame(w,bg='#27394e');title.pack(fill='x');tk.Label(title,text='TYRES / 四轮轮胎' if kind=='tyres' else 'STINT / 燃油与能量',fg=FG,bg='#27394e',font=('Segoe UI',10,'bold')).pack(side='left',padx=10,pady=5)
        tk.Button(title,text='×',command=lambda:self.hide(kind),bg='#27394e',fg=FG,bd=0,padx=10).pack(side='right')
        origin=[None]
        def begin(e):origin[0]=(e.x_root-w.winfo_x(),e.y_root-w.winfo_y())
        def move(e):
            if origin[0]:w.geometry(f'{e.x_root-origin[0][0]:+d}{e.y_root-origin[0][1]:+d}')
        def end(e):
            self.app.vehicle_settings[kind+'_position']=[w.winfo_x(),w.winfo_y()];self.save();origin[0]=None
        for child in [title,*title.winfo_children()]:
            if isinstance(child,tk.Button):continue
            child.bind('<Button-1>',begin);child.bind('<B1-Motion>',move);child.bind('<ButtonRelease-1>',end)
        menu=tk.Menu(w,tearoff=False);menu.add_command(label='车型阈值与策略设置',command=self.settings_dialog);menu.add_command(label='隐藏该面板',command=lambda:self.hide(kind))
        w.bind('<Button-3>',lambda e:menu.tk_popup(e.x_root,e.y_root))
        body=tk.Frame(w,bg=BG);body.pack(fill='both',expand=True,padx=10,pady=7);labels={}
        if kind=='tyres':
            for i,name in enumerate(('左前 FL','右前 FR','左后 RL','右后 RR')):
                frame=tk.Frame(body,bg='#19283a',highlightbackground='#354b65',highlightthickness=1);frame.grid(row=i//2,column=i%2,sticky='nsew',padx=3,pady=3)
                tk.Label(frame,text=name,fg=BLUE,bg='#19283a',font=('Segoe UI',9,'bold')).pack(anchor='w',padx=7,pady=(4,1))
                label=tk.Label(frame,text='—',fg=FG,bg='#19283a',justify='left',anchor='w',font=('Segoe UI',9));label.pack(fill='both',expand=True,padx=7,pady=(0,5));labels[vehiclelab.WHEELS[i]]=label
            for row in (0,1):body.rowconfigure(row,weight=1)
            for col in (0,1):body.columnconfigure(col,weight=1)
        else:
            for key,size in [('fuel',17),('estimate',10),('target',10),('energy',10),('status',9)]:
                label=tk.Label(body,text='—',fg=FG if key=='fuel' else MUTED,bg=BG,font=('Segoe UI',size,'bold' if key=='fuel' else 'normal'),anchor='w',justify='left',wraplength=375)
                label.pack(fill='x',pady=2);labels[key]=label
        foot=tk.Label(w,text='等待真实遥测 · F8 穿透 / 解锁',fg=MUTED,bg=BG,font=('Segoe UI',8),anchor='w',wraplength=380);foot.pack(side='bottom',fill='x',padx=10,pady=(0,7),before=body);labels['foot']=foot
        w.attributes('-topmost',self.app.top.get());self.topmost[kind]=self.app.top.get()
        self.windows[kind]=w;self.labels[kind]=labels;return w

    def refresh_visibility(self):
        for kind in ('tyres','strategy'):
            enabled=getattr(self.app,kind+'_on').get();w=self.windows.get(kind)
            if enabled:
                if w is None or not w.winfo_exists():w=self.create(kind)
                w.deiconify()
            elif w is not None and w.winfo_exists():w.withdraw()

    def tick(self):
        app=self.app
        if app.closing:return
        with app.engine.lock:
            latest=app.engine.latest;values=app.engine.vehicle_latest or {};estimate=(app.engine.vehicle_estimate or {}) if latest else {}
        name=latest.get('vehicle','') if latest else '';p=app.vehicle_settings['profiles'].get(name,app.vehicle_settings['profiles'].get('*',vehiclelab.DEFAULT_PROFILE))
        for kind,w in self.windows.items():
            if not getattr(app,kind+'_on').get():continue
            if self.topmost.get(kind)!=app.top.get():
                w.attributes('-topmost',app.top.get());self.topmost[kind]=app.top.get()
            if self.passthrough.get(kind)!=app.clickthrough:
                handle=app.user32.GetParent(w.winfo_id()) or w.winfo_id();style=app.user32.GetWindowLongW(handle,-20)
                app.user32.SetWindowLongW(handle,-20,(style|0x80000|0x20) if app.clickthrough else style&~0x20);self.passthrough[kind]=app.clickthrough
            labels=self.labels[kind]
            if kind=='tyres':
                for wheel in vehiclelab.WHEELS:
                    temp=values.get(wheel+'_middle_c');alert=vehiclelab.tyre_alerts(values,p)
                    color='#ff9c94' if any(m.startswith(wheel.upper()) for m in alert) else FG
                    text='内/中/外 '+('/'.join(fmt(values.get(wheel+'_'+f),0) for f in ('inner_c','middle_c','outer_c')))+' °C\n'+fmt(values.get(wheel+'_pressure_kpa'))+' kPa · 胎体 '+fmt(values.get(wheel+'_carcass_c'),0)+'°\n胎况 '+fmt(values.get(wheel+'_wear_fraction')*100 if values.get(wheel+'_wear_fraction') is not None else None)+'%'
                    labels[wheel].configure(text=text,fg=color)
                alerts=vehiclelab.tyre_alerts(values,p);labels['foot'].configure(text=(' / '.join(alerts) if alerts else ('DEMO · ' if latest and latest.get('demo') else '')+(name or '等待真实遥测')+' · '+('自定义阈值' if p['alerts'] else '温压报警未启用')),fg='#ffb69c' if alerts else MUTED)
            else:
                labels['fuel'].configure(text='燃油 '+fmt(values.get('fuel_l'),2)+' L',fg=FG)
                labels['estimate'].configure(text='近期 '+str(estimate.get('count',0))+' 圈 · '+fmt(estimate.get('rate_l'),3)+' L/圈 · 可跑 '+fmt(estimate.get('range_laps'),2)+' 圈')
                labels['target'].configure(text='目标需 '+fmt(estimate.get('required_l'),2)+' L · 余量 '+fmt(estimate.get('margin_l'),2)+' L',fg='#ff9c94' if estimate.get('margin_l') is not None and estimate['margin_l']<0 else '#80ddbc')
                labels['energy'].configure(text='电池 '+fmt(values.get('battery_soc_pct'))+'% · VE '+fmt(values.get('virtual_energy_pct'))+'%\n回收 '+fmt(values.get('regen_kw'))+' kW · VE 可跑 '+fmt(estimate.get('energy_range_laps'),2)+' 圈')
                labels['status'].configure(text=('建议补 '+fmt(estimate.get('add_l'),2)+' L · 目标超油箱，需停站' if estimate.get('exceeds_capacity') else '建议补 '+fmt(estimate.get('add_l'),2)+' L · 安全余量 '+fmt(app.vehicle_settings['reserve_l'])+' L'))
                labels['foot'].configure(text=('DEMO · ' if latest and latest.get('demo') else '')+((estimate.get('remaining_source') or '赛程未知') if latest else '等待真实遥测')+' · '+('保守最高耗油' if app.vehicle_settings['rate_mode']=='conservative' else '中位耗油')+' · F8 穿透')
        app.root.after(100,self.tick)

    def settings_dialog(self):
        if self.dialog is not None and self.dialog.winfo_exists():self.dialog.lift();return
        from management import panel
        app=self.app;window=panel(app,'InputScope · 轮胎阈值与燃油策略',620,720);self.dialog=window
        config=copy.deepcopy(app.vehicle_settings);latest=app.engine.latest
        car=tk.StringVar(window,value=latest['vehicle'] if latest else '*');p=config['profiles'].get(car.get(),config['profiles'].get('*',vehiclelab.DEFAULT_PROFILE))
        frame=tk.Frame(window,bg=BG);frame.pack(fill='both',expand=True,padx=18,pady=15)
        tk.Label(frame,text='轮胎阈值按车型保存；* 为通用默认。',bg=BG,fg=FG,anchor='w').grid(row=0,column=0,columnspan=2,sticky='w',pady=5)
        tk.Label(frame,text='车型',bg=BG,fg=MUTED).grid(row=1,column=0,sticky='w');box=ttk.Combobox(frame,textvariable=car,values=list(dict.fromkeys([car.get(),'*',*config['profiles']])),width=40);box.grid(row=1,column=1,sticky='ew',pady=5)
        enabled=tk.BooleanVar(window,value=p['alerts']);tk.Checkbutton(frame,text='启用该车型自定义温度 / 胎压 / 胎况报警',variable=enabled,bg=BG,fg=FG,selectcolor='#26394f').grid(row=2,column=0,columnspan=2,sticky='w')
        variables={}
        specs=[('temp_min','胎面中温下限 °C',p['temp_min']),('temp_max','胎面中温上限 °C',p['temp_max']),('pressure_min','胎压下限 kPa',p['pressure_min']),('pressure_max','胎压上限 kPa',p['pressure_max']),('wear_min','胎况字段下限 %',p['wear_min']),
               ('reserve_l','燃油安全余量 L',config['reserve_l']),('extra_finish_laps','计时赛额外保险圈',config['extra_finish_laps']),('history_laps','估算采用最近完整圈数 1–20',config['history_laps']),('record_hz','附加遥测记录上限 1–50 Hz',config['record_hz']),('target_value','手动总圈数 / 从应用起剩余分钟',config['target_value'])]
        for row,(key,label,value) in enumerate(specs,3):
            var=tk.StringVar(window,value=str(value));variables[key]=var;tk.Label(frame,text=label,bg=BG,fg=MUTED,anchor='w').grid(row=row,column=0,sticky='w',pady=4);tk.Entry(frame,textvariable=var,width=18).grid(row=row,column=1,sticky='ew',pady=4)
        mode=tk.StringVar(window,value=config['target_mode']);rate=tk.StringVar(window,value=config['rate_mode'])
        for row,label,var,options in [(13,'赛程来源',mode,['auto','laps','time']),(14,'耗油统计方式',rate,['conservative','median'])]:
            tk.Label(frame,text=label,bg=BG,fg=MUTED).grid(row=row,column=0,sticky='w',pady=5);ttk.Combobox(frame,textvariable=var,state='readonly',values=options).grid(row=row,column=1,sticky='ew')
        tk.Label(frame,text='auto：游戏比赛圈数 / 时间；laps：手动总圈数；time：剩余分钟。\nconservative：近期最高耗油；median：中位数。轮胎示例阈值默认不报警。\n胎况是 mWear 字段百分比，不等同剩余抓地力。',bg=BG,fg=MUTED,justify='left',wraplength=580).grid(row=15,column=0,columnspan=2,sticky='w',pady=10)
        def load_profile(_):
            current=config['profiles'].get(car.get(),config['profiles'].get('*',vehiclelab.DEFAULT_PROFILE));enabled.set(current['alerts'])
            for key in vehiclelab.DEFAULT_PROFILE:
                if key!='alerts':variables[key].set(str(current[key]))
        box.bind('<<ComboboxSelected>>',load_profile)
        def apply():
            try:
                new={**config,'profiles':dict(config['profiles'])};new['profiles'][car.get().strip() or '*']=vehiclelab.profile({'alerts':enabled.get(),**{k:float(variables[k].get()) for k in vehiclelab.DEFAULT_PROFILE if k!='alerts'}})
                new.update({k:float(variables[k].get()) for k in ('reserve_l','extra_finish_laps','history_laps','record_hz','target_value')},target_mode=mode.get(),rate_mode=rate.get());new=vehiclelab.settings(new)
                # Preserve current panel visibility and positions, changed outside this dialog.
                for key,value in app.vehicle_settings.items():
                    if key.endswith('_enabled') or key.endswith('_position'):new[key]=value
                app.vehicle_settings=new
                with app.engine.lock:
                    app.engine.fuel_planner.configure(new);app.engine.recorder.vehicle_settings=new
                    if app.engine.latest:
                        app.engine.fuel_planner.baseline_et=app.engine.latest['et']
                        sample={**app.engine.latest,'vehicle':app.engine.latest.get('vehicle_data',{})}
                        app.engine.vehicle_estimate=app.engine.fuel_planner.estimate(sample)
                if app.engine.recorder.file:
                    with app.engine.recorder.meta_lock:
                        recorder=app.engine.recorder;elapsed=app.engine.latest['et']-recorder.origin if app.engine.latest else 0
                        prior=dict(recorder.meta['vehicle_strategy'])
                        if not recorder.meta.get('vehicle_settings_history'):recorder.meta['vehicle_settings_history']=[dict(time_s=0,strategy=prior)]
                        current={k:new[k] for k in ('history_laps','rate_mode','target_mode','target_value','reserve_l','extra_finish_laps')};current['started_at_s']=elapsed
                        recorder.meta['vehicle_strategy']=current;recorder.meta['vehicle_settings_history'].append(dict(time_s=elapsed,strategy=current))
                        recorder.meta['vehicle_telemetry']['target_hz']=new['record_hz']
                        recorder.meta['vehicle_profile']=new['profiles'].get(app.engine.latest['vehicle'],new['profiles'].get('*',vehiclelab.DEFAULT_PROFILE)) if app.engine.latest else vehiclelab.DEFAULT_PROFILE
                self.save();window.destroy()
            except (ValueError,OSError) as e:messagebox.showerror('设置未保存',str(e),parent=window)
        tk.Button(frame,text='应用并保存',command=apply).grid(row=16,column=0,columnspan=2,sticky='ew',pady=7);frame.columnconfigure(1,weight=1)
