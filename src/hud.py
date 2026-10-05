"""Windows Tk HUD and user interaction; telemetry runs in the engine."""
import ctypes
import json
import math
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import endurance
import vehiclelab
from app_config import COLORS, INPUT_CHANNELS, ROOT
from background import BackgroundTasks
from buffers import NumericRing, window_rate, window_rows
from engine import Engine
from hud_geometry import WheelDisplay, hud_layout, pedal_fill, reduce_trace, steering_angle
from laps import library_laps, write_compare
from paths import ASSETS, telemetry_directory
from reference import DistanceAligner, ReferenceLap, best_reference
from sampling import (FrameDeadline, PRESETS, PreciseWait, drawing_rate, load_settings,
                      save_settings, validate_settings)
from session_reports import make_report, render_review
from telemetry_import import import_recording


class App:
    def __init__(self, demo=False, clean=False, clean_controls=False, root=None, on_menu=None):
        self.root = root if root is not None else tk.Tk()
        self.on_menu=on_menu
        self.root.title('LMU StintLab' + (' · DEMO' if demo else ''))
        from branding import apply
        apply(self.root)
        self.root.geometry('640x228+70+70')
        self.root.minsize(440, 160)
        self.root.overrideredirect(True)
        self.root.configure(bg='#0c111a')
        self.top = tk.BooleanVar(self.root,value=True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 1.0)
        self.clickthrough = False
        self.f7_down = False
        self.f6_down = False
        self.f8_down = False
        self.f9_down = False
        self.f10_down = False
        self.f11_down = False
        self.settings = load_settings(ROOT / 'settings.json')
        self.vehicle_settings=vehiclelab.load_settings(ROOT/'vehicle_settings.json')
        self.endurance_settings=endurance.load_settings(ROOT/'endurance_settings.json')
        for kind in ('pit','stint','weather'):setattr(self,kind+'_on',tk.BooleanVar(self.root,value=self.endurance_settings[kind+'_enabled']))
        self.tyres_on=tk.BooleanVar(self.root,value=self.vehicle_settings['tyres_enabled'])
        self.strategy_on=tk.BooleanVar(self.root,value=self.vehicle_settings['strategy_enabled'])
        try:
            self.reference_settings = json.loads((ROOT/'reference_settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):
            self.reference_settings = dict(enabled=False,automatic=True,path='')
        self.reference_on = tk.BooleanVar(self.root,value=bool(self.reference_settings.get('enabled',False)))
        self.reference_auto = tk.BooleanVar(self.root,value=bool(self.reference_settings.get('automatic',True)))
        self.reference_loading = False
        self.reference_generation = 0
        self.reference_scan_at = 0
        self.reference_match_key = None
        self.reference_message = ''
        self.reference_kind = tk.StringVar(self.root,value=self.reference_settings.get('kind','fastest'))
        self.reference_locked = tk.BooleanVar(self.root,value=bool(self.reference_settings.get('locked',False)))
        self.input_channel = tk.StringVar(self.root,value=self.settings['input_channel'])
        self.settings_dialog = None
        self.hud_mode = tk.StringVar(self.root,value='normal')
        self.applied_hud_mode = 'normal'
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.GetParent.argtypes = [ctypes.c_void_p]
        self.user32.GetParent.restype = ctypes.c_void_p
        self.user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        self.drag_origin = None
        def begin_drag(event):
            scale = min(self.canvas.winfo_width()/640, self.canvas.winfo_height()/228)
            if self.hud_mode.get() == 'normal' and event.y < 32*scale:
                if event.x > self.canvas.winfo_width() - 36*scale:
                    self.close()
                    return
                if event.x > self.canvas.winfo_width() - 76*scale:
                    self.open_control_center()
                    return
            self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        def move_drag(event):
            if self.drag_origin:
                x, y = event.x_root - self.drag_origin[0], event.y_root - self.drag_origin[1]
                self.root.geometry(f'{x:+d}{y:+d}')
        menu = tk.Menu(self.root, tearoff=False, bg='#172236', fg='#eef4ff')
        menu.add_command(label='打开控制中心',command=self.open_control_center)
        menu.add_command(label='打开记录', command=self.open_logs)
        menu.add_command(label='打开 CSV 复盘', command=self.review_csv)
        menu.add_command(label='最快圈曲线对比', command=self.open_fastest_compare)
        menu.add_command(label='比赛记录管理 / 稳定性分析',command=self.show_library)
        menu.add_command(label='性能诊断 / 实赛测量',command=self.show_diagnostics)
        menu.add_command(label='导入官方 DuckDB 比赛记录（只读）', command=self.import_native_dialog)
        menu.add_checkbutton(label='比赛中最快圈参考（F6）',variable=self.reference_on,command=self.apply_reference)
        menu.add_checkbutton(label='自动匹配同车同赛道最快圈',variable=self.reference_auto,command=self.apply_reference)
        menu.add_command(label='手动选择参考圈 .lap.json',command=self.select_reference)
        menu.add_checkbutton(label='锁定当前参考圈',variable=self.reference_locked,command=self.apply_reference)
        menu.add_radiobutton(label='参考类型：最快完整圈',variable=self.reference_kind,value='fastest',command=self.apply_reference)
        menu.add_radiobutton(label='参考类型：典型稳定圈（至少 3 圈）',variable=self.reference_kind,value='stable',command=self.apply_reference)
        menu.add_command(label='演示 / 真实遥测', command=self.toggle_demo)
        menu.add_command(label='采样与刷新设置（F10）', command=self.show_sampling_settings)
        vehicle_menu=tk.Menu(menu,tearoff=False,bg='#172236',fg='#eef4ff')
        vehicle_menu.add_checkbutton(label='四轮轮胎 HUD',variable=self.tyres_on,command=lambda:self.vehicle_panels.toggle('tyres'))
        vehicle_menu.add_checkbutton(label='燃油与能量 HUD',variable=self.strategy_on,command=lambda:self.vehicle_panels.toggle('strategy'))
        vehicle_menu.add_command(label='车型阈值与策略设置',command=lambda:self.vehicle_panels.settings_dialog())
        menu.add_cascade(label='轮胎与燃油 / 能量',menu=vehicle_menu)
        endurance_menu=tk.Menu(menu,tearoff=False,bg='#172236',fg='#eef4ff')
        for kind,label in [('pit','进站分析 HUD'),('stint','Stint 长距离 HUD'),('weather','天气与赛道 HUD')]:
            endurance_menu.add_checkbutton(label=label,variable=getattr(self,kind+'_on'),command=lambda k=kind:self.endurance_panels.toggle(k))
        endurance_menu.add_command(label='进站 / Stint / 天气设置',command=lambda:self.endurance_panels.settings_dialog())
        menu.add_cascade(label='进站 / Stint / 天气',menu=endurance_menu)
        menu.add_separator()
        for label,channel in (('输入：原始（F7 切换）','raw'),
                              ('输入：游戏过滤后（F7 切换）','filtered')):
            menu.add_radiobutton(label=label,variable=self.input_channel,value=channel,
                                 command=self.apply_input_channel)
        menu.add_separator()
        for label,mode in (('普通面板','normal'),('纯净：仅曲线（F9）','curves'),
                           ('纯净：曲线＋踏板/方向盘（F11）','controls')):
            menu.add_radiobutton(label=label,variable=self.hud_mode,value=mode,
                                 command=self.apply_clean_mode)
        menu.add_separator()
        self.window = tk.StringVar(self.root,value='10')
        for seconds in ('5', '10', '20'):
            menu.add_radiobutton(label=seconds + ' 秒波形', variable=self.window, value=seconds)
        menu.add_separator()
        menu.add_command(label='小面板 440 × 170', command=lambda: self.root.geometry('440x170'))
        menu.add_command(label='标准面板 640 × 228', command=lambda: self.root.geometry('640x228'))
        menu.add_command(label='高清面板 840 × 300', command=lambda: self.root.geometry('840x300'))
        for opacity in (0.75, 0.90, 1.0):
            menu.add_command(label=f'不透明度 {int(opacity * 100)}%',
                             command=lambda value=opacity: self.root.attributes('-alpha', value))
        menu.add_command(label='鼠标穿透 / 解锁（F8）', command=self.toggle_clickthrough)
        self.canvas = tk.Canvas(self.root, bg='#0c111a', highlightthickness=0)
        self.canvas.bind('<Button-1>', begin_drag)
        self.canvas.bind('<B1-Motion>', move_drag)
        self.canvas.bind('<Button-3>', lambda event: menu.tk_popup(event.x_root, event.y_root))
        self.canvas.pack(fill='both', expand=True)
        self.chrome_key = None
        self.trace_key = None
        self.trace_expiry = 0
        self.live_key = None
        self.live_items = {}
        self.wheel_display = None
        self.root.update_idletasks()
        handle = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = self.user32.GetWindowLongW(handle, -20)
        self.user32.SetWindowLongW(handle, -20, (style | 0x40000) & ~0x80)
        self.user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        self.gdi32 = ctypes.WinDLL('gdi32')
        self.gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self.render_wake = threading.Event()
        self.engine = Engine(demo, settings=self.settings, rate_wake=self.render_wake,vehicle_settings=self.vehicle_settings,endurance_settings=self.endurance_settings)
        self.engine.diagnostics_gui = True
        self.diagnostics = self.engine.diagnostics
        self.engine.reference_enabled = self.reference_on.get()
        self.draw_times = NumericRing(1,12001)
        self._draw_rate = 0
        self._draw_rate_at = -math.inf
        self.closing = False
        self.tasks = BackgroundTasks()
        self.task_job = self.root.after(25, self.poll_tasks)
        from vehiclehud import Panels
        self.vehicle_panels=Panels(self,ROOT)
        from endurancehud import Panels as EndurancePanels
        self.endurance_panels=EndurancePanels(self,ROOT)
        self.render_clock = FrameDeadline(time.perf_counter())
        self.render_stop = threading.Event()
        self.render_waiter = PreciseWait(self.render_stop,self.render_wake)
        self.draw_job = None
        self.drawing = False
        self.gui_yield_at = time.perf_counter()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if clean or clean_controls:
            self.hud_mode.set('controls' if clean_controls else 'curves')
            self.apply_clean_mode()
        self.draw()
        self.root.after(25,self.poll_keys)
        self.root.after(500,self.refresh_reference)

    def run_background(self, work, done):
        return self.tasks.submit(work, done)

    def open_control_center(self):
        if self.on_menu:self.on_menu()
        else:
            from control_center import show_attached
            show_attached(self)

    def poll_tasks(self):
        self.task_job = None
        if self.closing:
            return
        try:
            for done, result, error in self.tasks.completions():
                done(result, error)
        finally:
            if not self.closing:
                self.task_job = self.root.after(25, self.poll_tasks)

    def apply_reference(self):
        self.reference_generation += 1
        if self.reference_locked.get() and self.engine.reference:self.reference_settings['path']=self.engine.reference.path
        self.reference_settings.update(enabled=self.reference_on.get(),automatic=self.reference_auto.get(),
            kind=self.reference_kind.get(),locked=self.reference_locked.get())
        (ROOT/'reference_settings.json').write_text(json.dumps(self.reference_settings,ensure_ascii=False,indent=2),encoding='utf-8')
        with self.engine.lock:
            self.engine.reference_enabled = self.reference_on.get()
            self.engine.reference_points.clear()
            self.engine.reference_latest = None
            self.engine.reference_revision += 1
            self.engine.aligner=DistanceAligner()
        self.reference_match_key = None
        self.trace_key = None

    def toggle_reference(self):
        self.reference_on.set(not self.reference_on.get())
        self.apply_reference()

    def select_reference(self):
        path = filedialog.askopenfilename(title='选择完整参考圈',initialdir=ROOT/'Logs',filetypes=[('InputScope fastest lap','*.lap.json')])
        if not path:return
        try:
            reference = ReferenceLap.load(path)
        except Exception as error:
            messagebox.showerror('参考圈读取失败',str(error));return
        self.reference_auto.set(False)
        self.reference_locked.set(True)
        self.reference_on.set(True)
        self.reference_settings['path'] = path
        with self.engine.lock:self.engine.reference = reference
        self.apply_reference()

    def refresh_reference(self):
        if self.closing:return
        with self.engine.lock:
            sample = self.engine.latest
            if sample:sample=dict(sample,conditions=self.engine.aligner.match_conditions(sample))
        key = (sample.get('track'),sample.get('vehicle'),sample.get('track_length')) if sample else None
        if self.reference_on.get() and not self.reference_loading and (self.reference_match_key != key or
                sample and self.reference_auto.get() and not self.reference_locked.get() and time.monotonic()>=self.reference_scan_at):
            self.reference_match_key = key
            automatic = self.reference_auto.get() and not self.reference_locked.get()
            kind = self.reference_kind.get()
            path = self.reference_settings.get('path','')
            self.reference_loading = True
            self.reference_scan_at = time.monotonic()+10
            generation = self.reference_generation
            engine = self.engine
            with engine.lock:current = engine.reference
            def load():
                return (best_reference(ROOT,sample,current,kind) if automatic and sample else
                        ReferenceLap.load(path) if not automatic and path else None)
            def done(reference, error):
                self.reference_loading = False
                if engine is not self.engine or key != self.reference_match_key or generation!=self.reference_generation:return
                with engine.lock:
                    if engine.reference is not reference:
                        engine.reference = reference
                        engine.reference_points.clear()
                        engine.reference_latest = None
                        self.engine.reference_revision += 1
                        engine.aligner=DistanceAligner()
                self.reference_message = error or ('无匹配参考圈' if reference is None else '')
            self.run_background(load,done)
        self.root.after(1000,self.refresh_reference)

    def import_native_dialog(self):
        path = filedialog.askopenfilename(title='只读导入已结束的 LMU DuckDB 记录',
            initialdir=telemetry_directory(),
            filetypes=[('LMU native telemetry','*.duckdb')])
        if not path:return
        dialog=tk.Toplevel(self.root);dialog.title('官方日志导入');dialog.geometry('490x285');dialog.attributes('-topmost',True)
        tk.Label(dialog,text='源数据库只读，输出保存在 InputScope / ImportedLogs。\n可留空使用日志内元数据；圈长未知时只做估算。',justify='left').pack(padx=12,pady=12)
        fields={}
        for key,label in (('track','赛道（可选）'),('vehicle','车辆（可选）'),('driver','车手（可选）'),('track_length','圈长 m（可选）')):
            row=tk.Frame(dialog);row.pack(fill='x',padx=12,pady=3);tk.Label(row,text=label,width=18,anchor='w').pack(side='left');v=tk.StringVar();tk.Entry(row,textvariable=v).pack(side='left',fill='x',expand=True);fields[key]=v
        status=tk.Label(dialog,text='',wraplength=460,justify='left');status.pack(pady=8)
        def begin():
            values={k:v.get().strip() for k,v in fields.items() if v.get().strip()}
            if 'track_length' in values:
                try:
                    length=float(values['track_length'])
                    if not math.isfinite(length) or not 100<length<100000:raise ValueError()
                except ValueError:status.config(text='圈长应为 100–100000 m 之间的数字');return
            button.config(state='disabled');status.config(text='正在只读导入并生成完整复盘 / 最快圈…')
            def run():
                folder=import_recording(path,ROOT,values);make_report(folder)
                return folder
            def done(folder,error):
                if not dialog.winfo_exists():return
                button.config(state='normal')
                if error:status.config(text=error)
                else:
                    dialog.destroy();self.reference_match_key=None;os.startfile(folder/'review.html')
            self.run_background(run,done)
        button=tk.Button(dialog,text='开始导入',command=begin);button.pack()

    def drawing_target(self):
        return drawing_rate(self.settings,self.engine.target_hz)

    def actual_draw_rate(self):
        now = time.monotonic()
        if now-self._draw_rate_at >= 0.25:
            horizon = max(2.5,2.5/self.drawing_target())
            self._draw_rate = window_rate(self.draw_times, now-horizon)
            self._draw_rate_at = now
        return self._draw_rate

    def toggle_clean(self, with_controls=False):
        mode = 'controls' if with_controls else 'curves'
        self.hud_mode.set('normal' if self.hud_mode.get()==mode else mode)
        self.apply_clean_mode()

    def toggle_input_channel(self):
        self.input_channel.set('filtered' if self.input_channel.get()=='raw' else 'raw')
        self.apply_input_channel()

    def apply_input_channel(self):
        checked = dict(self.settings, input_channel=self.input_channel.get())
        # This is a HUD preference only. Do not reset the sampler or recorder.
        self.settings = checked
        try:
            save_settings(ROOT/'settings.json', checked)
        except OSError as error:
            messagebox.showerror('无法保存输入通道', '本次切换已生效，但无法保存下次启动的选项：\n'+str(error))
        # An explicit switch remains responsive even at a 1 Hz drawing target.
        self.trace_key = None
        self.render_wake.set()
        if not self.drawing:
            if self.draw_job is not None:
                self.root.after_cancel(self.draw_job)
            self.draw_job = self.root.after_idle(self.queue_draw)

    def apply_clean_mode(self):
        mode = self.hud_mode.get()
        if mode == self.applied_hud_mode:
            return
        was_clean = self.applied_hud_mode != 'normal'
        self.canvas.pack_forget()
        if mode != 'normal':
            if not was_clean:
                self.normal_size = (self.root.winfo_width(), self.root.winfo_height())
                self.normal_opacity = self.root.attributes('-alpha')
            self.root.minsize(*( (320,80) if mode=='controls' else (240,60) ))
            self.root.geometry('600x100' if mode=='controls' else '440x100')
            self.root.configure(bg='#000000')
            self.root.attributes('-alpha', 1.0)
            self.canvas.configure(bg='#000000')
            self.canvas.pack(fill='both', expand=True)
        else:
            self.root.minsize(440, 160)
            width, height = self.normal_size
            self.root.geometry(f'{width}x{height}')
            self.root.configure(bg='#0c111a')
            self.root.attributes('-alpha', self.normal_opacity)
            self.canvas.configure(bg='#0c111a')
            self.canvas.pack(fill='both', expand=True)
        self.applied_hud_mode = mode
        self.chrome_key = None

    def toggle_clickthrough(self):
        self.root.update_idletasks()
        window = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = self.user32.GetWindowLongW(window, -20)
        self.clickthrough = not self.clickthrough
        style = (style | 0x80000 | 0x20) if self.clickthrough else (style & ~0x20)
        self.user32.SetWindowLongW(window, -20, style)

    def open_logs(self):
        path = self.engine.last_folder or self.engine.recorder.output
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def show_library(self):
        from management import show_library
        show_library(self,ROOT,render_review,make_report)

    def show_diagnostics(self):
        from management import show_diagnostics
        show_diagnostics(self,ROOT)

    def open_fastest_compare(self):
        demo = self.engine.demo
        path = ROOT/('DemoFastestLapCompare.html' if demo else 'FastestLapCompare.html')
        def prepare():
            write_compare(path,ASSETS/'compare.html',
                          library_laps(ROOT/('DemoLogs' if demo else 'Logs')))
            return path
        def done(result,error):
            if error:messagebox.showerror('最快圈对比',error)
            else:os.startfile(str(result))
        self.run_background(prepare,done)

    def toggle_demo(self):
        if self.engine.recorder.file and not self.engine.demo:
            messagebox.showinfo('记录中', '请先结束当前真实记录，再切换演示。')
            return
        demo = not self.engine.demo
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        if self.engine.thread.is_alive():
            return
        self.engine = Engine(demo, settings=self.settings, rate_wake=self.render_wake,vehicle_settings=self.vehicle_settings,endurance_settings=self.endurance_settings)
        self.diagnostics=self.engine.diagnostics
        self.engine.reference_enabled = self.reference_on.get()
        self.reference_match_key = None
        self.render_wake.set()
        self.root.title('LMU StintLab' + (' · DEMO' if demo else ''))

    def show_sampling_settings(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self.settings_dialog = dialog
        dialog.title('InputScope · 采样与刷新设置')
        dialog.configure(bg='#111a29')
        dialog.attributes('-topmost', True)
        dialog.resizable(False, False)
        panel = tk.Frame(dialog, bg='#111a29', padx=22, pady=18)
        panel.pack(fill='both', expand=True)
        tk.Label(panel,text='采样与刷新',bg='#111a29',fg='#eef4ff',font=('Segoe UI',15,'bold')).grid(row=0,column=0,columnspan=2,sticky='w')
        variables = {key:tk.StringVar(value=str(value)) for key,value in self.settings.items()
                     if key != 'input_channel'}
        modes = tk.Frame(panel,bg='#111a29')
        modes.grid(row=1,column=0,columnspan=2,sticky='w',pady=(10,6))
        inputs = {}
        def mode_changed():
            dynamic = variables['mode'].get()=='dynamic'
            for key,widget in inputs.items():
                enabled = ((key=='draw_hz' and variables['draw_mode'].get()=='manual')
                           or (key=='fixed_hz' and not dynamic)
                           or (key not in ('draw_hz','fixed_hz') and dynamic))
                widget.configure(state='normal' if enabled else 'disabled')
        for text,value in (('固定采样','fixed'),('动态采样','dynamic')):
            tk.Radiobutton(modes,text=text,value=value,variable=variables['mode'],command=mode_changed,
                           bg='#111a29',fg='#dce7f8',selectcolor='#26364f',activebackground='#111a29',activeforeground='#ffffff').pack(side='left',padx=(0,15))
        for row,(key,label,maximum,increment) in enumerate((
                ('fixed_hz','固定目标（1–4000 Hz）',4000,1),
                ('min_hz','动态最低（1–4000 Hz）',4000,1),
                ('max_hz','动态最高（1–4000 Hz）',4000,1),
                ('change_pct_s','变化阈值（百分点 / 秒）',10000,0.1),
                ('hold_s','降频延迟（秒）',30,0.1),
                ('brake_pct','刹车升频（%，0 为关闭）',100,1),
                ('draw_hz','手动 HUD 绘制（1–4000 Hz）',4000,1)), start=3):
            tk.Label(panel,text=label,bg='#111a29',fg='#becde3',anchor='w').grid(row=row,column=0,sticky='w',pady=5,padx=(0,28))
            entry = tk.Spinbox(panel,textvariable=variables[key],from_=0 if key=='brake_pct' else 0.1 if key in ('hold_s','change_pct_s') else 1,
                               to=maximum,increment=increment,width=12,bg='#24334b',fg='#f4f7ff',insertbackground='#ffffff',
                               disabledbackground='#182233',disabledforeground='#62748e',buttonbackground='#35465e',relief='flat')
            entry.grid(row=row,column=1,sticky='e',pady=5)
            inputs[key] = entry
        presets = tk.Frame(panel,bg='#111a29')
        presets.grid(row=2,column=0,columnspan=2,sticky='w',pady=(0,8))
        def preset(name):
            for key,value in PRESETS[name].items():
                variables[key].set(str(value))
            mode_changed()
        for name in PRESETS:
            tk.Button(presets,text=name+'预设',command=lambda value=name:preset(value),bg='#26364f',fg='#dce7f8',relief='flat',padx=10).pack(side='left',padx=(0,7))
        tk.Checkbutton(panel,text='HUD 绘制跟随采样频率（推荐）',variable=variables['draw_mode'],
                       onvalue='sync',offvalue='manual',command=mode_changed,
                       bg='#111a29',fg='#dce7f8',selectcolor='#26364f',activebackground='#111a29',
                       activeforeground='#ffffff').grid(row=10,column=0,columnspan=2,sticky='w',pady=(7,0))
        info = tk.Label(panel,text='',bg='#111a29',fg='#52b5ff',justify='left',anchor='w')
        info.grid(row=11,column=0,columnspan=2,sticky='w',pady=(13,5))
        tk.Label(panel,text='同步模式：HUD 与采样目标一起升降频，无 240 Hz 上限。\n实际新数据受游戏限制，可见帧率受显示器和系统性能限制。\n动态模式：输入变化或刹车升频，平稳后延迟降频。',
                 bg='#111a29',fg='#8fa2be',justify='left',anchor='w').grid(row=12,column=0,columnspan=2,sticky='w',pady=(2,12))
        error = tk.Label(panel,text='',bg='#111a29',fg='#ff8194',wraplength=400,justify='left')
        error.grid(row=13,column=0,columnspan=2,sticky='w')
        def mark_pending(*_):
            error.configure(text='参数已修改，点击“应用并保存”生效。',fg='#e8bf7e')
        for variable in variables.values():
            variable.trace_add('write',mark_pending)
        def apply():
            try:
                checked = validate_settings(dict({key:var.get() for key,var in variables.items()},
                                                 input_channel=self.input_channel.get()))
                save_settings(ROOT/'settings.json', checked)
                self.settings = checked
                self.engine.update_settings(checked)
                error.configure(text='已应用并保存；采集不中断。',fg='#34e59a')
            except (ValueError,OSError) as problem:
                error.configure(text=str(problem),fg='#ff8194')
        actions = tk.Frame(panel,bg='#111a29')
        actions.grid(row=14,column=0,columnspan=2,sticky='e',pady=(10,0))
        tk.Button(actions,text='关闭',command=dialog.destroy,bg='#26364f',fg='#dce7f8',relief='flat',padx=16).pack(side='left',padx=6)
        tk.Button(actions,text='应用并保存',command=apply,bg='#315a84',fg='#ffffff',relief='flat',padx=16).pack(side='left')
        def refresh():
            if not dialog.winfo_exists():
                return
            poll, fresh = self.engine.actual_rates()
            draw = self.actual_draw_rate()
            info.configure(text=f'采样目标 {self.engine.target_hz} / 绘制目标 {self.drawing_target()} Hz  ·  {self.engine.reason}\n实际轮询 {poll:.1f}  /  新数据 {fresh:.1f}  /  绘制 {draw:.1f} Hz')
            dialog.after(250,refresh)
        mode_changed()
        refresh()

    def review_csv(self):
        path = filedialog.askopenfilename(title='打开完整输入记录', initialdir=str(self.engine.recorder.output),
                                          filetypes=[('Input CSV', 'inputs.csv')])
        if path:
            def done(_,error):
                if error:messagebox.showerror('无法打开记录',error)
                else:os.startfile(str(Path(path).parent / 'review.html'))
            self.run_background(lambda:make_report(Path(path).parent),done)

    def rounded(self, x0, y0, x1, y1, radius=12, **options):
        r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
        return self.canvas.create_polygon(
            x0+r,y0, x1-r,y0, x1,y0, x1,y0+r, x1,y1-r, x1,y1,
            x1-r,y1, x0+r,y1, x0,y1, x0,y1-r, x0,y0+r, x0,y0,
            smooth=True, splinesteps=24, **options)

    def paint_chrome(self, w, h, clean, controls=False):
        """Cache vector glass surfaces outside the live refresh path."""
        key = (w, h, clean, controls)
        if key == self.chrome_key:
            return
        self.chrome_key = key
        c = self.canvas
        c.delete('chrome')
        s = min(w/640, h/228)
        handle = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        if clean:
            self.user32.SetWindowRgn(handle, None, True)
            if controls:
                for bounds in hud_layout(w,h,True,True)['pedals']:
                    c.create_rectangle(*bounds,fill='#111820',outline='#273748',tags='chrome')
                c.tag_lower('chrome')
            return
        region = self.gdi32.CreateRoundRectRgn(0, 0, w+1, h+1, round(32*s), round(32*s))
        if region and not self.user32.SetWindowRgn(handle, region, True):
            self.gdi32.DeleteObject(region)
        # Soft glass tint and a cool upper reflection, kept opaque for legibility.
        for step in range(48):
            t = step / 47
            rgb = tuple(round(a * (1-t) + b * t) for a, b in zip((44,57,76), (13,20,32)))
            color = '#%02x%02x%02x' % rgb
            c.create_rectangle(0, step*h/48, w, (step+1)*h/48+1,
                               fill=color, outline='', tags='chrome')
        self.rounded(1, 1, w-1, h-1, 16*s, fill='', outline='#708199', width=1, tags='chrome')
        c.create_line(23*s, 1, w-23*s, 1, fill='#b0bed0', tags='chrome')
        c.create_text(18*s, 18*s, text='INPUTSCOPE', fill='#f1f5fb', anchor='w',
                      font=('Segoe UI', -max(10,round(12*s)), 'bold'), tags='chrome')
        self.rounded(w-74*s, 7*s, w-40*s, 29*s, 10*s, fill='#39465a', outline='#59667b', tags='chrome')
        c.create_text(w-57*s, 17*s, text='•••', fill='#e4ecf8', font=('Segoe UI', -round(13*s)), tags='chrome')
        c.create_text(w-22*s, 17*s, text='×', fill='#aab9cf', font=('Segoe UI', -round(18*s)), tags='chrome')
        card_width = (w-44*s)/3
        for lane, (name, tint, color) in enumerate(zip(('THROTTLE / 油门', 'BRAKE / 刹车', 'STEERING / 转向'),
                                                     ('#263f3d','#44353f','#2b3d52'), COLORS)):
            x = 14*s + lane*(card_width+8*s)
            self.rounded(x, 37*s, x+card_width, 82*s, 12*s, fill=tint, outline='#526174', tags='chrome')
            c.create_line(x+12*s, 38*s, x+card_width-12*s, 38*s, fill='#6b7c8b', tags='chrome')
            c.create_oval(x+10*s, 47*s, x+15*s, 52*s, fill=color, outline='', tags='chrome')
            c.create_text(x+21*s, 50*s, text=name if w>=560 else ('油门','刹车','转向')[lane],
                          fill='#c1cbda', anchor='w', font=('Segoe UI', -max(9,round(10*s))), tags='chrome')
        layout = hud_layout(w,h)
        x0,x1,y0,y1 = layout['plot']
        self.rounded(14*s,89*s,x1+10*s,h-27*s,12*s,fill='#121d2b',outline='#42516a',tags='chrome')
        c.create_line(28*s,90*s,x1-4*s,90*s,fill='#6a7d95',tags='chrome')
        for grid in range(1,4):
            y = y0+(y1-y0)*grid/4
            c.create_line(x0,y,x1,y,fill='#243245', tags='chrome')
        for grid in range(1,6):
            x = x0+(x1-x0)*grid/6
            c.create_line(x,y0,x,y1,fill='#1c2a3d', tags='chrome')
        px0,py0,px1,py1 = layout['panel']
        self.rounded(px0,py0,px1,py1,12*s,fill='#121d2b',outline='#42516a',tags='chrome')
        c.create_line(px0+12*s,py0+s,px1-12*s,py0+s,fill='#6a7d95',tags='chrome')
        for bounds,label,color in zip(layout['pedals'],('B','T'),(COLORS[1],COLORS[0])):
            bx0,by0,bx1,by1 = bounds
            self.rounded(bx0-2*s,by0-2*s,bx1+2*s,by1+2*s,4*s,
                         fill='#182536',outline='#35465e',tags='chrome')
            c.create_text((bx0+bx1)/2,py0+12*s,text=label,fill=color,
                          font=('Segoe UI',-max(8,round(9*s)),'bold'),tags='chrome')
        cx,cy,radius = layout['wheel']
        c.create_oval(cx-radius-3*s,cy-radius-3*s,cx+radius+3*s,cy+radius+3*s,
                      outline='#25384c',width=1,tags='chrome')
        c.create_line(cx,cy-radius-3*s,cx,cy-radius+2*s,fill='#52b5ff',width=1.5,tags='chrome')
        c.create_text(cx,py0+12*s,text='M4 GT3 · 540°',fill='#91a8c5',
                      font=('Segoe UI',-max(7,round(8*s))),tags='chrome')
        c.tag_lower('chrome')

    def poll_keys(self):
        if self.closing:return
        failure=getattr(self.engine,'recording_failure',None)
        if failure and failure!=getattr(self,'reported_recording_failure',None):
            self.reported_recording_failure=failure
            self.root.after_idle(lambda message=failure:messagebox.showerror('记录已停止：写盘失败',message,parent=self.root))
        elif not failure:self.reported_recording_failure=None
        key_state = self.user32.GetAsyncKeyState(0x75)
        f6 = bool(key_state & 0x8000)
        if (key_state & 1) or (f6 and not self.f6_down):self.toggle_reference()
        self.f6_down = f6
        key_state = self.user32.GetAsyncKeyState(0x76)
        f7 = bool(key_state & 0x8000)
        if (key_state & 1) or (f7 and not self.f7_down):
            self.toggle_input_channel()
        self.f7_down = f7
        key_state = self.user32.GetAsyncKeyState(0x77)
        f8 = bool(key_state & 0x8000)
        if (key_state & 1) or (f8 and not self.f8_down):
            self.toggle_clickthrough()
        self.f8_down = f8
        key_state = self.user32.GetAsyncKeyState(0x78)
        f9 = bool(key_state & 0x8000)
        if (key_state & 1) or (f9 and not self.f9_down):
            self.toggle_clean()
        self.f9_down = f9
        key_state = self.user32.GetAsyncKeyState(0x79)
        f10 = bool(key_state & 0x8000)
        if (key_state & 1) or (f10 and not self.f10_down):
            self.show_sampling_settings()
        self.f10_down = f10
        key_state = self.user32.GetAsyncKeyState(0x7a)
        f11 = bool(key_state & 0x8000)
        if (key_state & 1) or (f11 and not self.f11_down):
            self.toggle_clean(with_controls=True)
        self.f11_down = f11
        if self.render_clock.set_rate(self.drawing_target(),time.perf_counter()):
            if not self.drawing:
                if self.draw_job is not None:
                    self.root.after_cancel(self.draw_job)
                self.draw_job = self.root.after_idle(self.queue_draw)
        self.root.after(25,self.poll_keys)

    def draw(self, event=None):
        if self.closing or self.drawing:
            return
        self.drawing = True
        self.paint_started=time.perf_counter()
        self.draw_job = None
        self.render_clock.set_rate(self.drawing_target(),time.perf_counter())
        remaining = self.render_clock.deadline-time.perf_counter()
        if 0 < remaining < 0.003:
            # The last fraction of a millisecond uses an interruptible native wait,
            # releasing the GIL, rather than rounding every frame up to one ms.
            if self.render_waiter.until(self.render_clock.deadline):
                self.render_clock.set_rate(self.drawing_target(),time.perf_counter())
        c = self.canvas
        mode = self.hud_mode.get()
        channel = self.input_channel.get()
        point_offset,channel_label = INPUT_CHANNELS[channel]
        clean = mode != 'normal'
        controls = mode == 'controls'
        w, h = max(4, c.winfo_width()), max(4, c.winfo_height())
        if self.live_key != (w,h,mode):
            c.delete('live')
            c.delete('wheel')
            self.live_items.clear()
            self.wheel_display = None
            self.live_key = (w,h,mode)
        self.paint_chrome(w, h, clean, controls)
        s = min(w/640,h/228)
        window = float(self.window.get())
        now = time.monotonic()
        layout = hud_layout(w,h,clean,controls)
        x0,x1,y0,y1 = layout['plot']
        self.engine.configure_plot(x1-x0,window,y1-y0)
        with self.engine.lock:
            trace_key = (id(self.engine),self.engine.plot_revision,self.engine.reference_revision,w,h,mode,window,channel)
            rebuild = trace_key != self.trace_key or now >= self.trace_expiry
            points = window_rows(self.engine.plot_points, now-window) if rebuild else ()
            latest = self.engine.latest
            reference_points = window_rows(self.engine.reference_points, now-window) if rebuild and self.engine.reference_enabled else ()
            reference_latest = self.engine.reference_latest
            if hasattr(self,'diagnostics'):self.paint_sample=latest
        if rebuild:
            c.delete('trace')
            self.trace_key = trace_key
            self.trace_expiry = points[0][0]+window if points else math.inf
        else:
            c.move('trace',-(now-self.trace_time)/window*(x1-x0),0)
        self.trace_time = now
        input_offset = 3 if channel=='filtered' else 0
        values = latest['controls'][input_offset:input_offset+3] if latest else [0, 0, 0]
        if not clean:
            self.live_item('input_channel',c.create_text,111*s,18*s,
                           text=f'/  LMU · {channel_label} · F7',fill='#a9bdd7',anchor='w',
                           font=('Segoe UI',-max(9,round(10*s))))
        if not clean or controls:
            self.paint_controls(layout,values,clean=clean)
        for lane, (name, color, value) in enumerate(zip(('油门', '刹车', '转向'), COLORS, values)):
            value_text = f'{value * 100:+.0f}%' if lane == 2 else f'{value * 100:.0f}%'
            if not clean:
                card_width = (w-44*s)/3
                self.live_item('value'+str(lane),c.create_text,25*s+lane*(card_width+8*s),68*s,text=value_text,
                               fill=color,anchor='w',font=('Segoe UI',-round(21*s),'bold'))
            coords = []
            previous = None
            for point in points:
                if previous is not None and point[0] - previous > 3:
                    if len(coords) >= 4:
                        self.paint_trace(coords, lane, clean)
                    coords = []
                x = x1 - (now - point[0]) / window * (x1 - x0)
                low, high = point[point_offset+lane+3], point[point_offset+lane+6]
                height = (y1-y0)/(2 if lane==2 else 1)
                # Sub-quarter-pixel ranges are visually indistinguishable. Larger
                # ranges still emit both extrema, preserving brief pedal spikes.
                displayed = (low,high) if (high-low)*height>=0.25 else (point[point_offset+lane],)
                for v in displayed:
                    fraction = (v + 1) / 2 if lane == 2 else v
                    coords.extend((x, y1 - fraction * (y1 - y0)))
                previous = point[0]
            if len(coords) >= 4:
                self.paint_trace(coords, lane, clean)
        if rebuild:
            offset=3 if channel=='filtered' else 1
            for lane,color in enumerate(('#b4f7d9','#ffc0c8')):
                coords=[];previous=None
                for point in reference_points:
                    if previous is not None and point[0]-previous>.15:
                        if len(coords)>=4:c.create_line(*reduce_trace(coords),fill=color,width=max(1,s),dash=(3,4),tags='trace')
                        coords=[]
                    coords.extend((x1-(now-point[0])/window*(x1-x0),y1-point[offset+lane]*(y1-y0)));previous=point[0]
                if len(coords)>=4:c.create_line(*reduce_trace(coords),fill=color,width=max(1,s),dash=(3,4),tags='trace')
        poll_hz, sample_hz = self.engine.actual_rates()
        draw_hz = self.actual_draw_rate()
        failure=getattr(self.engine,'recording_failure',None)
        state = 'ERROR / 记录停止' if failure else 'DEMO' if self.engine.demo else 'REC' if self.engine.recorder.file else 'WAIT / SAVED'
        lock = '穿透' if self.clickthrough else '可拖动'
        if not clean:
            self.live_item('state',c.create_oval,16*s,h-17*s,21*s,h-12*s,
                           fill=COLORS[1] if failure else COLORS[0] if self.engine.recorder.file else '#8da1bd',outline='')
            mode = 'DYN' if self.settings['mode']=='dynamic' else 'FIX'
            self.live_item('rates',c.create_text,28*s,h-14*s,
                           text=f'{state} {mode}{self.engine.target_hz}   ·   新{sample_hz:.0f} / 绘{draw_hz:.0f} Hz',
                           fill='#a9b9d0',anchor='w',font=('Segoe UI',-max(9,round(10*s))))
            alignment=getattr(self.engine,'reference_state',{})
            approximate=isinstance(alignment,dict) and (alignment.get('confidence',1)<.6 or alignment.get('conditions',{}).get('unknown'))
            self.live_item('keys',c.create_text,w-16*s,h-14*s,
                           text=('写盘异常 · 该段已停止' if failure else f'REF{"≈" if approximate else ""} {reference_latest[-1]:+.3f}s · F6' if self.reference_on.get() and reference_latest else
                                 ('REF '+self.engine.reference_state.get('mode','未匹配')+' · F6' if self.reference_on.get() else f'{int(window)}s   ·   F8 {lock}   ·   F9 纯净')),
                           fill='#889ab4',anchor='e',font=('Segoe UI',-max(9,round(10*s))))
        # Tk queues canvas painting as an idle task. Acknowledge after that task,
        # without a nested update_idletasks loop consuming future render callbacks.
        self.draw_job = self.root.after_idle(self.finish_draw)

    def finish_draw(self):
        self.draw_job = None
        self.drawing = False
        if self.closing:
            return
        self.draw_times.append((time.monotonic(),))
        if hasattr(self,'diagnostics'):self.diagnostics.paint(self.paint_started,self.paint_sample,self.drawing_target())
        deadline = self.render_clock.complete(time.perf_counter())
        delay = max(0,int((deadline-time.perf_counter())*1000))
        now = time.perf_counter()
        # Windows/Tk must periodically leave its zero-delay event queue to accept
        # native input and positive timers. Yield one ms per four ms of busy drawing,
        # while allowing submillisecond frames between yields.
        if delay == 0 and now-self.gui_yield_at >= 0.004:
            delay = 1
        if delay:
            self.gui_yield_at = now
        # Zero-delay timers can starve positive timers and input on Windows Tk.
        # Idle continuations let normal UI events run between high-rate frames.
        self.draw_job = self.root.after(delay,self.draw) if delay else self.root.after_idle(self.queue_draw)

    def queue_draw(self):
        # The idle stage queues a timer rather than drawing inside an idle handler.
        # This keeps update_idletasks from recursively consuming future frames.
        if not self.closing:
            self.draw_job = self.root.after(0,self.draw)

    def live_item(self, key, create, *coords, **options):
        cached = self.live_items.get(key)
        if cached is None:
            self.live_items[key] = (create(*coords,**options,tags='live'),options,coords)
        else:
            if cached[2] != coords:
                self.canvas.coords(cached[0],*coords)
            if cached[1] != options:
                changed = {name:value for name,value in options.items() if cached[1].get(name)!=value}
                self.canvas.itemconfigure(cached[0],**changed)
            self.live_items[key] = (cached[0],options,coords)

    def paint_controls(self, layout, values, clean=False):
        # Called once in the same render pass and with the same selected input snapshot
        # as the waveforms. These controls have no separate refresh timer.
        s = layout['scale']
        for bounds,value,color,key in zip(layout['pedals'],(values[1],values[0]),
                                         (COLORS[1],COLORS[0]),('brake','throttle')):
            self.live_item(key+'_bar',self.canvas.create_rectangle,*pedal_fill(bounds,value),
                           fill=color,outline='',state='normal' if value>0 else 'hidden')
            if not clean:
                self.live_item(key+'_percent',self.canvas.create_text,(bounds[0]+bounds[2])/2,
                               layout['panel'][3]-10*s,text=f'{value*100:.0f}%',fill=color,
                               font=('Segoe UI',-max(8,round(9*s)),'bold'))
        if self.wheel_display is None:
            self.wheel_display = WheelDisplay(self.canvas,*layout['wheel'],
                                              background='#000000' if clean else '#121d2b')
        angle = steering_angle(values[2])
        self.wheel_display.set_angle(angle)
        if not clean:
            self.live_item('wheel_degrees',self.canvas.create_text,layout['wheel'][0],
                           layout['panel'][3]-10*s,text=f'{angle:+.0f}°',fill='#b9d9fa',
                           font=('Segoe UI',-max(8,round(10*s)),'bold'))

    def paint_trace(self, coords, lane, clean):
        coords = reduce_trace(coords)
        if not clean:
            self.canvas.create_line(*coords, fill=('#204b44','#502d3b','#23435d')[lane],
                                    width=4, capstyle='round', joinstyle='bevel', tags='trace')
        self.canvas.create_line(*coords, fill=COLORS[lane], width=1.8 if not clean else 2,
                                capstyle='round', joinstyle='bevel', tags='trace')

    def close(self):
        self.closing = True
        center=getattr(self,'control_center',None)
        if center and center.root.winfo_exists():
            if not center.closing:
                center.closing=True;center.tasks.close();center.root.after_cancel(center.job)
        tasks = getattr(self, 'tasks', None)
        if tasks:
            tasks.close()
        if getattr(self, 'task_job', None) is not None:
            self.root.after_cancel(self.task_job)
            self.task_job = None
        self.render_stop.set()
        if self.draw_job is not None:
            self.root.after_cancel(self.draw_job)
            self.draw_job = None
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        if self.engine.thread.is_alive():
            self.root.after(25, self.close)
            return
        # Keep Tk and its variables alive on the GUI thread until all exports finish.
        if ((tasks and tasks.busy) or (center and center.tasks.busy) or
                any(t.is_alive() for t in [*self.engine.recorder.pending_reports,*getattr(self,'archive_workers',[])])):
            self.root.after(25,self.close)
            return
        self.render_waiter.close()
        if tasks:
            # Discard callbacks after shutdown while releasing their result data.
            for _ in tasks.completions():
                pass
        if center:
            for _ in center.tasks.completions():pass
        self.root.destroy()
