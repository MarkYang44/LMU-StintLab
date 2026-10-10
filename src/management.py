"""Focused Tk windows, shared by the existing HUD. Local operations only."""
from i18n import tr,Label
import json
from json_store import load as load_json
import os
from pathlib import Path
import tkinter as tk
from control_fields import Select,Field
from control_theme import T
from tkinter import ttk,messagebox,filedialog
from library import inventory,save_note
from reference import ReferenceLap,DistanceAligner
from storage import atomic_json,recover_session,compress_session
from sessionlab import analyze_session
from laps import write_compare,complete_laps,export_selected_laps,finished_metadata
from paths import ASSETS


def panel(app,title,width,height):
    window=tk.Toplevel(app.root);window.title(tr(title));window.geometry(f'{width}x{height}')
    window.configure(bg=T.BG);window.attributes('-topmost',True)
    style=ttk.Style(window);style.theme_use('clam')
    style.configure('Scope.Treeview',background=T.CARD,foreground=T.FG,fieldbackground=T.CARD,rowheight=29)
    style.configure('Scope.Treeview.Heading',background=T.FIELD,foreground=T.MUTED)
    style.map('Scope.Treeview',background=[('selected',T.SELECT)])
    return window


def show_diagnostics(app,root):
    window=panel(app,'Stintrix · 性能诊断',680,465)
    label=Label(window,bg=T.BG,fg=T.FG,justify='left',anchor='nw',font=('Consolas',11));label.pack(fill='both',expand=True,padx=20,pady=18)
    snapshot={}
    def collect():
        nonlocal snapshot
        poll,fresh=app.engine.actual_rates();snapshot=app.engine.diagnostics.snapshot()
        batch=app.engine.recorder.batch
        snapshot.update(poll_hz=poll,fresh_hz=fresh,draw_hz=app.actual_draw_rate(),sampling_target=app.engine.target_hz,
            drawing_target=app.drawing_target(),missed_poll_cycles=app.engine.missed_cycles,
            missed_draw_cycles=app.render_clock.missed_cycles,writer_queue=batch.queue.qsize() if batch else 0,
            writer_peak=batch.peak if batch else 0,alignment=app.engine.reference_state,recording_error=getattr(app.engine,'recording_failure',None))
        return snapshot
    def display():
        if not window.winfo_exists() or app.closing:return
        s=collect();fmt=lambda v:'—' if v is None else f'{v:.3f}'
        rows=[f"轮询目标 {s['sampling_target']} / 绘制目标 {s['drawing_target']} Hz",
              f"实际轮询 {s['poll_hz']:.1f} / 新数据 {s['fresh_hz']:.1f} / 绘制 {s['draw_hz']:.1f} Hz",'',
              '最近 5 秒                 P50 ms    P95 ms    P99 ms']
        for key,name in [('read','共享内存读取'),('draw','绘制回调至 idle'),('interval','绘制间隔'),('latency','读入→首次绘制')]:
            d=s[key];rows.append(f"{name:<15} {fmt(d['p50_ms']):>9} {fmt(d['p95_ms']):>9} {fmt(d['p99_ms']):>9}")
        a=s['alignment'];rows.extend(['',f"累计长帧 {s['stutters']} / 绘制错过周期 {s['missed_draw_cycles']}",
            f"写盘队列 {s['writer_queue']} / 峰值 {s['writer_peak']} 行",
            f"参考对齐 {a.get('mode','关闭')} / 可信度 {a.get('confidence',0):.0%}",
            '参考条件未知：'+(' / '.join({'fuel_l':'燃油','tyre_compound':'胎种','track_temp_c':'赛道温度','wetness':'湿度','tc_level':'TC','abs_level':'ABS'}[k] for k in a.get('conditions',{}).get('unknown',[])) or '—'),
            '','延迟仅测插件读入至 Tk idle，不含方向盘、游戏或屏幕扫描。',
            '读取耗时只包含真实共享内存；DEMO 的该项为空。','GPU 渲染尚未替换：先用实赛基准识别瓶颈。'])
        label.config(text='\n'.join(rows));window.after(500,display)
    def export():
        path=Path(root)/'Diagnostics'/'latest.json';path.parent.mkdir(exist_ok=True)
        atomic_json(path,collect());messagebox.showinfo(tr('诊断已导出'),str(path),parent=window)
    tk.Button(window,text=tr('导出当前诊断 JSON'),command=export).pack(pady=10);display();return window


def show_library(app,root,render_review,make_report):
    root=Path(root);window=panel(app,'Stintrix · 比赛记录管理',1160,675)
    state={'items':[],'busy':False};status=tk.StringVar(value=tr('扫描记录中…'))
    filterbar=tk.Frame(window,bg=T.BG);filterbar.pack(fill='x',padx=15,pady=12)
    search=tk.StringVar();track=tk.StringVar(value='全部赛道');car=tk.StringVar(value='全部车辆');source=tk.StringVar(value='全部来源')
    Label(filterbar,text='搜索阶段 / 日期 / 车手 / 备注',bg=T.BG,fg=T.MUTED).pack(side='left')
    tk.Entry(filterbar,textvariable=search,width=24).pack(side='left',padx=6)
    trackbox=Select(filterbar,textvariable=track,state='readonly',width=26);trackbox.pack(side='left',padx=5)
    carbox=Select(filterbar,textvariable=car,state='readonly',width=24);carbox.pack(side='left',padx=5)
    sourcebox=Select(filterbar,textvariable=source,state='readonly',width=15,values=['全部来源','Logs','ImportedLogs','RecoveredLogs','DemoLogs']);sourcebox.pack(side='left',padx=5)
    tableframe=tk.Frame(window);tableframe.pack(fill='both',expand=True,padx=15)
    columns=('date','session_type','track','vehicle','best','stable','source','status','note')
    tree=ttk.Treeview(tableframe,columns=columns,show='headings',selectmode='extended',style='Scope.Treeview')
    for k,label,width in [('date','记录日期',175),('session_type','阶段',85),('track','赛道',210),('vehicle','车辆',165),('best','最快圈 s',95),('stable','稳定性 σ s',100),('source','来源',100),('status','状态',90),('note','备注 / 交通',200)]:
        tree.heading(k,text=tr(label));tree.column(k,width=width,minwidth=70)
    ys=ttk.Scrollbar(tableframe,orient='vertical',command=tree.yview);xs=ttk.Scrollbar(tableframe,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set);tree.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew');tableframe.rowconfigure(0,weight=1);tableframe.columnconfigure(0,weight=1)
    note=tk.StringVar();traffic=tk.BooleanVar();note_row=tk.Frame(window,bg=T.BG);note_row.pack(fill='x',padx=15,pady=10)
    Label(note_row,text='练习备注',bg=T.BG,fg=T.MUTED).pack(side='left');tk.Entry(note_row,textvariable=note).pack(side='left',fill='x',expand=True,padx=8)
    tk.Checkbutton(note_row,text=tr('交通影响（人工标记）'),variable=traffic,bg=T.BG,fg=T.MUTED,selectcolor=T.FIELD).pack(side='left')
    def selected():return [v for v in state['items'] if v['key'] in tree.selection()]
    def fill(*_):
        tree.delete(*tree.get_children());q=search.get().casefold()
        for v in state['items']:
            if track.get()!='全部赛道' and v['track']!=track.get():continue
            if car.get()!='全部车辆' and v['vehicle']!=car.get():continue
            if source.get()!='全部来源' and v['source']!=source.get():continue
            if q and q not in ' '.join(str(v[k]) for k in ('session_type','date','track','vehicle','driver','note')).casefold():continue
            tree.insert('', 'end',iid=v['key'],values=(v['date'][:19].replace('T',' '),v['session_type'],v['track'],v['vehicle'],
                f"{v['time_s']:.3f}" if v['time_s'] else '—',f"{v['stability_s']:.3f}" if v['stability_s'] is not None else '未分析',
                v['source'],v['status'],('交通 · ' if v['traffic'] else '')+v['note']))
        status.set(f"{tr('显示 ')}{len(tree.get_children())}{tr(' / 共 ')}{len(state['items'])}{tr(' 场；按 Ctrl 多选，最多六圈对比。')}")
    def background(work,done):
        if state['busy']:status.set(tr('上一个任务仍在处理，请稍候'));return
        state['busy']=True;status.set(tr('后台处理中…'))
        def finish(value,error):
            state['busy']=False
            if app.closing:return
            if not window.winfo_exists():return
            if error:status.set(error)
            else:done(value)
        app.run_background(work,finish)
    def refresh():
        def done(items):
            state['items']=items;trackbox['values']=['全部赛道',*sorted({v['track'] for v in items})];carbox['values']=['全部车辆',*sorted({v['vehicle'] for v in items})];fill()
        background(lambda:inventory(root),done)
    def one():
        values=selected()
        if len(values)!=1:raise ValueError('请选择一场记录')
        return values[0]
    def action(work,done):
        try:v=dict(one(),reference_kind=app.reference_kind.get())
        except ValueError as e:status.set(str(e));return
        background(lambda:work(v),done)
    def analyze(v):
        folder=Path(v['folder']);analyze_session(folder);render_review(folder);return folder/'review.html'
    def choose_reference(v):
        file=v['stable_file'] if v['reference_kind']=='stable' else v['fastest_file']
        if not file:raise ValueError('没有所选类型的参考圈；稳定圈需先分析且至少有三圈')
        return ReferenceLap.load(Path(v['folder'])/file)
    def lock_reference(ref):
        with app.engine.lock:app.engine.reference=ref;app.engine.aligner=DistanceAligner()
        app.reference_settings['path']=ref.path;app.reference_locked.set(True);app.reference_on.set(True);app.reference_auto.set(False);app.apply_reference()
        status.set(tr('已锁定第 ') + str(ref.info['number']) + tr(' 圈为 HUD 参考'))
    def compare():
        values=selected()
        if not 1<=len(values)<=6:status.set(tr('请选择 1–6 场记录'));return
        kind=app.reference_kind.get()
        def work():
            records=[]
            for v in values:
                file=v['stable_file'] if kind=='stable' else v['fastest_file']
                if not file:raise ValueError(v['track']+' 没有所选类型的参考圈')
                records.append(load_json(Path(v['folder'])/file))
            path=root/'LibraryCompare.html';write_compare(path,ASSETS/'compare.html',records);return path
        background(work,lambda path:os.startfile(path))
    def save():
        try:v=one();save_note(root,v['key'],note.get(),traffic.get());refresh()
        except ValueError as e:status.set(str(e))
    tree.bind('<<TreeviewSelect>>',lambda _: (note.set(selected()[0]['note']),traffic.set(selected()[0]['traffic'])) if len(selected())==1 else None)
    def recover(v):
        folder=recover_session(v['folder'],root);make_report(folder);return folder
    def same_session():
        try:show_lap_selection(app,root,one()['folder'])
        except ValueError as e:status.set(str(e))
    def transferred(result,kind):
        items=result['items'];errors=result['errors'];skipped=sum(v.get('status')=='skipped' for v in items)
        refresh()
        text=f"{kind}完成：成功 {len(items)-skipped} 场，重复跳过 {skipped} 场，失败 {len(errors)} 场。"
        if errors:text+='\n\n'+ '\n'.join(Path(e['item']).name+'：'+e['error'] for e in errors)
        status.set(text)
        (messagebox.showwarning if errors else messagebox.showinfo)('比赛包'+kind,text,parent=window)
    def export_packages():
        if state['busy']:status.set(tr('上一个任务仍在处理，请稍候'));return
        values=selected()
        if not values:status.set(tr('请选择一场或多场比赛；Ctrl / Shift 可多选'));return
        destination=filedialog.askdirectory(title=tr('选择赛事包导出目录'),parent=window)
        if not destination:return
        from session_archive import export_session,transfer_batch
        format=archive_format.get().lower()
        background(lambda:transfer_batch([v['key'] for v in values],lambda key:export_session(root,key,destination,format=format)),
                   lambda result:transferred(result,'导出'))
    def import_packages():
        if state['busy']:status.set(tr('上一个任务仍在处理，请稍候'));return
        packages=filedialog.askopenfilenames(title=tr('选择一个或多个 Stintrix 比赛包'),parent=window,
                                            filetypes=[('Stintrix ZIP / 7z','*.zip *.7z')])
        if not packages:return
        from session_archive import import_session,transfer_batch
        verify=archive_verify.get()
        background(lambda:transfer_batch(packages,lambda package:import_session(root,package,verify=verify)),
                   lambda result:transferred(result,'导入'))
    def race_images(v):
        from race_report import generate
        folder=Path(v['folder']);generate(folder);return folder
    import archive_preferences
    preferences=archive_preferences.load(root)
    archive_format=tk.StringVar(window,value='ZIP' if preferences['format']=='zip' else '7z')
    archive_verify=tk.BooleanVar(window,value=preferences['verify'])
    def save_archive():archive_preferences.save(root,archive_format.get().lower(),archive_verify.get())
    options=tk.Frame(window,bg=T.BG);options.pack(fill='x',padx=15)
    Label(options,text='导出格式',bg=T.BG,fg=T.FG).pack(side='left',padx=3)
    select=Select(options,textvariable=archive_format,values=['ZIP','7z'],width=8);select.pack(side='left',padx=8)
    select.bind('<<ComboboxSelected>>',lambda _:save_archive())
    from control_widgets import Switch
    Switch(options,'导入时完整校验',archive_verify,save_archive).pack(side='left',fill='x',expand=True)
    transferbar=tk.Frame(window,bg=T.BG);transferbar.pack(fill='x',padx=15)
    for text,command in [('导出比赛包（可多选）',export_packages),('导入比赛包（可多选）',import_packages)]:
        tk.Button(transferbar,text=tr(text),command=command).pack(side='left',padx=3,pady=3)
    tk.Button(transferbar,text=tr('圈速单 / 比赛日志'),command=lambda:action(race_images,os.startfile)).pack(side='left',padx=3,pady=3)
    Label(transferbar,text='ZIP / 7z · 默认快速导入 · 完整记录和备注保留',bg=T.BG,fg='#8fabc9').pack(side='left',padx=10)
    buttons=tk.Frame(window,bg=T.BG);buttons.pack(fill='x',padx=15)
    for text,command in [('刷新',refresh),('分析 / 完整复盘',lambda:action(analyze,lambda path:(os.startfile(path),refresh()))),('同场圈 A／B',same_session),('最快圈页',lambda:action(lambda v:Path(v['folder'])/'fastest_lap.html',os.startfile)),('多选对比',compare),('设为锁定参考',lambda:action(choose_reference,lock_reference)),('保存备注',save),('压缩备份',lambda:action(lambda v:compress_session(v['folder']),lambda v:status.set(f"{tr('已校验压缩备份：')}{v['compressed_bytes'] / 1048576:.2f}{tr(' MB；保留原 CSV')}"))),('恢复中断记录',lambda:action(recover,lambda path:refresh()))]:
        tk.Button(buttons,text=tr(text),command=command).pack(side='left',padx=3,pady=8)
    Label(window,textvariable=status,bg=T.BG,fg='#8fabc9',anchor='w',wraplength=1110).pack(fill='x',padx=15,pady=8)
    for variable in (search,track,car,source):variable.trace_add('write',fill)
    refresh();return window


def show_lap_selection(app,root,folder):
    root=Path(root).resolve();folder=Path(folder).resolve()
    if not folder.is_relative_to(root):raise ValueError('只能选择本插件目录中的比赛记录')
    dialogs=getattr(app,'lap_selection_windows',None)
    if dialogs is None:dialogs=app.lap_selection_windows={}
    existing=dialogs.get(str(folder))
    if existing is not None and existing.winfo_exists():existing.lift();existing.focus_force();return existing
    window=panel(app,'Stintrix · 同场完整圈对比',720,395);dialogs[str(folder)]=window
    title=Label(window,text=folder.name,bg=T.BG,fg='#dce9fb',font=('Segoe UI',11),wraplength=670,justify='left',anchor='w')
    title.pack(fill='x',padx=18,pady=(15,10))
    status=tk.StringVar(window,value=tr('后台扫描完整圈…'));state={'busy':False,'laps':{},'output':None}
    vars={};boxes={}
    for key in ('A','B'):
        row=tk.Frame(window,bg=T.BG);row.pack(fill='x',padx=18,pady=6)
        Label(row,text='圈 '+key,bg=T.BG,fg='#c6def5',font=('Segoe UI',11),width=6,anchor='w').pack(side='left')
        vars[key]=tk.StringVar(window)
        boxes[key]=Select(row,textvariable=vars[key],state='disabled',font=('Segoe UI',11),height=12)
        boxes[key].pack(side='left',fill='x',expand=True)
    Label(window,text='仅列出起终点、采样和距离完整的圈。无效 / 进站标记会保留；\n此类圈可查看数据，但不生成驾驶改进建议，也不能用作 HUD 参考。',
        bg=T.BG,fg='#91abc8',justify='left',anchor='w',wraplength=670).pack(fill='x',padx=18,pady=12)
    actions=tk.Frame(window,bg=T.BG);actions.pack(fill='x',padx=18,pady=6);buttons={}
    def enable(*_):
        ready=not state['busy'] and bool(state['laps'])
        for k in ('A','B'):
            boxes[k].configure(state='readonly' if ready else 'disabled')
            buttons[k].configure(state='normal' if ready and vars[k].get() in state['laps'] else 'disabled')
        pair=ready and all(vars[k].get() in state['laps'] for k in ('A','B')) and vars['A'].get()!=vars['B'].get()
        buttons['compare'].configure(state='normal' if pair else 'disabled')
        buttons['folder'].configure(state='normal' if state['output'] else 'disabled')
    def background(work,done):
        if state['busy']:return
        state['busy']=True;status.set(tr('后台处理中…'));enable()
        def finish(result,error):
            if app.closing or not window.winfo_exists():return
            state['busy']=False
            if error:status.set(error)
            else:
                try:done(result)
                except OSError as e:status.set(tr('文件已生成，打开失败：') + str(e))
            enable()
        app.run_background(work,finish)
    def selected(keys):
        try:return [state['laps'][vars[k].get()]['number'] for k in keys]
        except KeyError:raise ValueError('请先选择完整圈') from None
    def export(keys,compare=False):
        try:numbers=selected(keys)
        except ValueError as e:status.set(str(e));return
        if len(set(numbers))!=len(numbers):status.set(tr('圈 A 和圈 B 必须选择不同圈'));return
        def done(result):
            state['output']=result['folder'];status.set(tr('已提取第 ') + ' / '.join(map(str, numbers)) + tr(' 圈；JSON 与完整 CSV 保存到：\n') + result['folder'])
            if result['comparison']:os.startfile(result['comparison'])
        background(lambda:export_selected_laps(folder,numbers,ASSETS/'compare.html' if compare else None),done)
    for key,text,command in [('A','提取圈 A',lambda:export(['A'])),('B','提取圈 B',lambda:export(['B'])),
            ('compare','提取两圈并对比',lambda:export(['A','B'],True)),('folder','打开提取目录',lambda:os.startfile(state['output']))]:
        buttons[key]=tk.Button(actions,text=tr(text),command=command,state='disabled');buttons[key].pack(side='left',padx=(0,9),pady=5)
    Label(window,textvariable=status,bg=T.BG,fg='#9dc7e9',anchor='nw',justify='left',wraplength=670).pack(fill='both',expand=True,padx=18,pady=12)
    for box in boxes.values():box.bind('<<ComboboxSelected>>',enable)
    def loaded(result):
        metadata,scan=result;title.config(text=metadata.get('track', '') + ' · ' + metadata.get('vehicle', '') + '\n' + folder.name)
        labels=[]
        for v in scan['laps']:
            minutes=int(v['time_s']//60);seconds=v['time_s']-minutes*60
            flags=[]
            if v.get('lap_invalidated'):flags.append(tr('无效标记'))
            if v.get('in_pits'):flags.append(tr('进站标记'))
            if not flags:flags.append(tr('有效性已记录' if v['validity']=='verified' else '有效性未验证'))
            label=f"{tr('第 ')}{v['number']}{tr(' 圈  ·  ')}{minutes}:{seconds:06.3f}  ·  "+' / '.join(flags)
            state['laps'][label]=v;labels.append(label)
        for box in boxes.values():box['values']=labels
        if labels:vars['A'].set(labels[0])
        if len(labels)>1:vars['B'].set(labels[1])
        status.set(f"{tr('找到 ')}{len(labels)}{tr(' 个完整圈，排除 ')}{len(scan['candidates']) - len(labels)}{tr(' 个不完整或圈号不明确的记录。')}" + (tr('请选择圈 A／圈 B，再提取或对比。') if len(labels) > 1 else tr('两圈对比需要至少两个完整圈。')) + (' ' + scan['error'] if scan['error'] else ''))
    background(lambda:(finished_metadata(folder),complete_laps(folder)),loaded);return window
