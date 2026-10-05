"""Edit per-car tyre thresholds without starting telemetry collection."""
import tkinter as tk
from tkinter import ttk,messagebox
from app_config import ROOT
from control_widgets import CARD,FG,MUTED,Pill
import vehiclelab


def show(owner):
    previous=getattr(owner,'profile_dialog',None)
    if previous and previous.winfo_exists():previous.lift();return
    window=tk.Toplevel(owner.root);owner.profile_dialog=window;window.title('StintLab · 车型轮胎阈值');window.geometry('610x460')
    window.configure(bg=CARD);window.transient(owner.root)
    frame=tk.Frame(window,bg=CARD);frame.pack(fill='both',expand=True,padx=24,pady=22)
    config=vehiclelab.load_settings(ROOT/'vehicle_settings.json');latest=owner.hud.engine.latest if owner.active() else None
    car=tk.StringVar(window,value=latest['vehicle'] if latest else '*');enabled=tk.BooleanVar(window)
    tk.Label(frame,text='车型阈值',bg=CARD,fg=FG,font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
    tk.Label(frame,text='* 为通用默认；报警按车型保存。',bg=CARD,fg=MUTED).pack(anchor='w',pady=(5,15))
    box=ttk.Combobox(frame,textvariable=car,values=list(dict.fromkeys([car.get(),'*',*config['profiles']])),style='Lab.TCombobox');box.pack(fill='x',pady=6)
    tk.Checkbutton(frame,text='启用该车型温度 / 胎压 / 胎况报警',variable=enabled,bg=CARD,fg=FG,selectcolor='#314860',activebackground=CARD,activeforeground=FG).pack(anchor='w',pady=8)
    variables={}
    for key,title in [('temp_min','胎面中温下限 / °C'),('temp_max','胎面中温上限 / °C'),('pressure_min','胎压下限 / kPa'),('pressure_max','胎压上限 / kPa'),('wear_min','胎况字段下限 / %')]:
        row=tk.Frame(frame,bg=CARD);row.pack(fill='x',pady=6);tk.Label(row,text=title,bg=CARD,fg=MUTED).pack(side='left')
        var=tk.StringVar(window);variables[key]=var;tk.Entry(row,textvariable=var,bg='#293e57',fg=FG,insertbackground=FG,relief='flat',width=15).pack(side='right',ipady=5)
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
