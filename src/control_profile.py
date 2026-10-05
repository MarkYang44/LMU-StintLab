"""Edit per-car tyre thresholds without starting telemetry collection."""
import tkinter as tk
from control_fields import Select,Field
from tkinter import ttk,messagebox
from app_config import ROOT
from control_widgets import Pill,px
from control_theme import T
import vehiclelab


def show(owner):
    previous=getattr(owner,'profile_dialog',None)
    if previous and previous.winfo_exists():previous.lift();return
    window=tk.Toplevel(owner.root);owner.profile_dialog=window;window.title('StintLab · 车型轮胎阈值');window.geometry(f'{px(window,680)}x{px(window,680)}');window.minsize(px(window,620),px(window,650))
    window.configure(bg=T.CARD);window.transient(owner.root)
    frame=tk.Frame(window,bg=T.CARD);frame.pack(fill='both',expand=True,padx=24,pady=22)
    config=vehiclelab.load_settings(ROOT/'vehicle_settings.json');latest=owner.hud.engine.latest if owner.active() else None
    car=tk.StringVar(window,value=latest['vehicle'] if latest else '*');enabled=tk.BooleanVar(window)
    tk.Label(frame,text='车型阈值',bg=T.CARD,fg=T.FG,font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
    tk.Label(frame,text='* 为通用默认；报警按车型保存。',bg=T.CARD,fg=T.MUTED).pack(anchor='w',pady=(5,15))
    box=Select(frame,textvariable=car,values=list(dict.fromkeys([car.get(),'*',*config['profiles']])),style='Lab.TCombobox');box.pack(fill='x',pady=6)
    tk.Checkbutton(frame,text='启用该车型温度 / 胎压 / 胎况报警',variable=enabled,bg=T.CARD,fg=T.FG,selectcolor=T.FIELD,activebackground=T.CARD,activeforeground=T.FG).pack(anchor='w',pady=8)
    variables={}
    for key,title in [('temp_min','胎面中温下限 / °C'),('temp_max','胎面中温上限 / °C'),('pressure_min','胎压下限 / kPa'),('pressure_max','胎压上限 / kPa'),('wear_min','胎况字段下限 / %')]:
        row=tk.Frame(frame,bg=T.CARD);row.pack(fill='x',pady=6);tk.Label(row,text=title,bg=T.CARD,fg=T.MUTED).pack(side='left')
        var=tk.StringVar(window);variables[key]=var;Field(row,textvariable=var,width=15).pack(side='right')
    def load(_=None):
        value=config['profiles'].get(car.get(),config['profiles'].get('*',vehiclelab.DEFAULT_PROFILE));enabled.set(value['alerts'])
        for key,var in variables.items():var.set(str(value[key]))
    box.bind('<<ComboboxSelected>>',load);load()
    def save():
        try:
            value=vehiclelab.load_settings(ROOT/'vehicle_settings.json');profiles=dict(value['profiles'])
            profiles[car.get().strip() or '*']=vehiclelab.profile(dict(alerts=enabled.get(),**{k:float(v.get()) for k,v in variables.items()}))
            owner.update_module('vehicle',dict(profiles=profiles));window.destroy()
        except (ValueError,OSError) as error:messagebox.showerror('设置未保存',str(error),parent=window)
    Pill(frame,'应用并保存',save,150,True).pack(anchor='e',pady=15)
