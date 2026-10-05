"""Window-index correctness, independent core imports and safe task completion."""
import bisect
from collections import deque
from collections.abc import Sequence
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from background import BackgroundTasks
from buffers import ControlHistory, NumericRing, window_rows, window_rate
from sessionlab import lap_conditions


class ModularityTests(unittest.TestCase):
    def test_window_boundaries_duplicates_growth_wrap_and_empty(self):
        history=NumericRing(2,137);expected=deque(maxlen=137)
        for i in range(1100):
            row=(i//2*.03125,math.sin(i));history.append(row);expected.append(row)
            if i%71==0:
                for cutoff in (0,row[0]-.1,row[0],row[0]+.1):
                    self.assertEqual(list(history.iter_since(cutoff)),[r for r in expected if r[0]>=cutoff])
                    self.assertEqual(history.lower_bound(cutoff),bisect.bisect_left([r[0] for r in expected],cutoff))
            if i%11==0:history.popleft();expected.popleft()
        history.clear()
        self.assertEqual(list(history.iter_since(0)),[])
        self.assertEqual(history.lower_bound(0),0)

    def test_window_never_materializes_hidden_history_and_keeps_spike(self):
        class TrackedHistory(ControlHistory):
            def __getitem__(self,index):
                self.reads.append(index)
                return super().__getitem__(index)
        history=TrackedHistory(80001);history.reads=[]
        for i in range(80000):
            raw=(.2,1 if i==70000 else 0,-.23456789012345)
            filtered=(.6,.8 if i==70001 else 0,.123456789012345)
            history.append((i/4000,*raw,*raw,*raw,*filtered,*filtered,*filtered))
        rows=window_rows(history,15)
        self.assertEqual(len(rows),20000)
        self.assertEqual(history.reads,list(range(60000,80000)))
        self.assertEqual(rows[10000][2],1)
        self.assertEqual(rows[10001][11],.8)
        self.assertEqual(rows[-1][3],-.23456789012345)

    def test_rates_equal_legacy_window_without_allocating_rows(self):
        history=NumericRing(1,127);legacy=deque(maxlen=127)
        for i in range(800):history.append((i*.03125,));legacy.append((i*.03125,))
        for cutoff in (0,24,24.96875,25):
            self.assertEqual(window_rate(history,cutoff),window_rate(legacy,cutoff))
        flat=NumericRing(1,3);flat.extend([(1,),(1,),(1,)])
        self.assertEqual(flat.rate_since(0),0)

    def test_native_conditions_use_logarithmic_reads_and_event_offset(self):
        class Data(Sequence):
            reads=0
            def __len__(self):return 200000
            def __getitem__(self,i):
                if not 0<=i<len(self):raise IndexError(i)
                self.reads+=1;return (i*.01,i)
        event=Data();regular=Data()
        native={'channels':{'Fuel Level':{'event':True,'data':event},
                            'TCLevel':{'event':False,'data':regular}}}
        result=lap_conditions([],native,1000,5)
        self.assertEqual(result,{'fuel_l':100500,'tc_level':100000})
        self.assertLess(event.reads,23);self.assertLess(regular.reads,23)

    def test_native_conditions_keep_first_value_tolerance_and_last_value(self):
        native={'channels':{'Fuel Level':{'event':True,'data':[(10,42),(11,41)]}}}
        self.assertEqual(lap_conditions([],native,0,10),{'fuel_l':42})
        self.assertEqual(lap_conditions([],native,-.3,10),{})
        self.assertEqual(lap_conditions([],native,20,10),{'fuel_l':41})

    def test_core_and_cli_version_do_not_import_tk(self):
        code="import sys;sys.path.insert(0,'src');import inputscope,engine,recorder,telemetry;assert 'tkinter' not in sys.modules;inputscope.main()"
        result=subprocess.run([sys.executable,'-c',code,'--version'],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LMU Stintrix',result.stdout)

    def test_workers_never_invoke_callbacks_until_owner_drains(self):
        owner=threading.get_ident();calls=[];tasks=BackgroundTasks()
        try:
            future=tasks.submit(lambda:threading.get_ident(),lambda result,error:calls.append((threading.get_ident(),result,error)))
            future.result(3);self.assertEqual(calls,[])
            for done,result,error in tasks.completions():done(result,error)
            self.assertEqual(calls[0][0],owner);self.assertNotEqual(calls[0][1],owner)
            self.assertIsNone(calls[0][2]);self.assertFalse(tasks.busy)
        finally:tasks.close()

    def test_shutdown_finishes_queued_writes_and_rejects_new_tasks(self):
        tasks=BackgroundTasks(workers=1);gate=threading.Event();calls=[]
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'export.txt'
            try:
                a=tasks.submit(lambda:gate.wait(3),lambda *_:None)
                b=tasks.submit(lambda:path.write_text('complete',encoding='utf-8'),lambda *_:calls.append('done'))
                tasks.close();self.assertTrue(tasks.busy)
                with self.assertRaises(RuntimeError):tasks.submit(lambda:None,lambda *_:None)
                gate.set();a.result(3);b.result(3)
                self.assertEqual(path.read_text(),'complete');self.assertFalse(tasks.busy)
                self.assertEqual(calls,[])
            finally:gate.set();tasks.close()

    def test_task_failures_are_delivered_and_later_tasks_still_work(self):
        tasks=BackgroundTasks(workers=1)
        try:
            def fail():raise ValueError('failed export')
            a=tasks.submit(fail,lambda *_:None);b=tasks.submit(lambda:42,lambda *_:None)
            a.result(3);b.result(3)
            completions=list(tasks.completions())
            self.assertEqual(completions[0][1:],(None,'failed export'))
            self.assertEqual(completions[1][1:],(42,None))
        finally:tasks.close()

    def test_hud_waits_for_shared_background_writes_on_close(self):
        from hud import App
        hud=object.__new__(App);hud.root=Mock();hud.render_stop=Mock();hud.draw_job=None
        hud.engine=Mock();hud.engine.thread.is_alive.return_value=False;hud.engine.recorder.pending_reports=[]
        hud.render_waiter=Mock();hud.tasks=Mock();hud.tasks.busy=True;hud.task_job='timer'
        hud.close();hud.root.destroy.assert_not_called();hud.tasks.close.assert_called_once()
        hud.root.after_cancel.assert_called_once_with('timer')
        hud.tasks.busy=False;hud.tasks.completions.return_value=[];hud.close()
        hud.root.destroy.assert_called_once();hud.render_waiter.close.assert_called_once()

    def test_session_change_accepts_first_frame_with_equal_elapsed_time(self):
        from engine import Engine
        from tests.test_core import fixture
        from telemetry import extract
        import time
        sample=extract(fixture());phase=[5]
        class Feed:
            def read(self):return dict(sample,session=phase[0])
            def close(self):pass
        with tempfile.TemporaryDirectory(dir=ROOT) as folder,patch('recorder.make_report'):
            engine=Engine(output=folder,reader_factory=Feed,settings={'fixed_hz':500})
            try:
                for value in (5,8):
                    phase[0]=value;deadline=time.monotonic()+2
                    while engine.recorder.meta.get('session')!=value or not engine.recorder.file:
                        if time.monotonic()>deadline:self.fail('New session first frame was lost')
                        time.sleep(.005)
            finally:
                engine.stop.set();engine.wake.set();engine.thread.join(3)
                for thread in engine.recorder.pending_reports:thread.join(3)
            records=[json.loads(p.read_text()) for p in Path(folder).glob('*/session.json')]
            self.assertEqual(len(records),2)
            self.assertEqual({m['session'] for m in records},{5,8})
            self.assertTrue(all(m['samples']==1 and m['status']=='complete' for m in records))

    def test_real_tk_dispatch_and_shutdown_finish_background_export(self):
        # Fresh process isolates Tcl and private settings from all other fixtures.
        code='''
import sys,threading
from pathlib import Path
sys.path.insert(0,'src')
from inputscope import App,Recorder
Recorder._report=staticmethod(lambda folder:None)
app=App(demo=True);app.root.withdraw()
owner=threading.get_ident();callbacks=[];out=Path(sys.argv[1]);gate=threading.Event()
def done(result,error):
    assert error is None and result!=owner
    callbacks.append(threading.get_ident())
    app.run_background(lambda:(gate.wait(3),out.write_text('complete',encoding='utf-8')),lambda *_:None)
    app.root.after(20,app.close)
    app.root.after(100,gate.set)
app.run_background(threading.get_ident,done)
app.root.after(5000,lambda:(gate.set(),app.close()))
app.root.mainloop()
assert callbacks==[owner] and out.read_text()=='complete'
assert not app.tasks.busy
'''
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            env=dict(os.environ,LMU_STINTRIX_DATA_DIR=str(Path(folder)/'data'))
            result=subprocess.run([sys.executable,'-c',code,str(Path(folder)/'export.txt')],cwd=ROOT,
                env=env,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_library_compare_and_reference_read_tk_settings_on_main_thread(self):
        code='''
import os,sys,threading
from pathlib import Path
sys.path.insert(0,'src')
from inputscope import App,Recorder,make_report,render_review
from app_config import ROOT,ASSETS
from management import show_library
from laps import export_fastest
from tests.test_core import Tests
import tkinter as tk
from tkinter import ttk
Recorder._report=staticmethod(lambda folder:None)
folder=ROOT/'Logs'/'synthetic';Tests().lap_csv(folder);export_fastest(folder,ASSETS/'compare.html')
app=App(demo=True);app.root.withdraw();owner=threading.get_ident();opened=[]
get=app.reference_kind.get
def guarded_get():
    assert threading.get_ident()==owner,'Tk setting read from a worker'
    return get()
app.reference_kind.get=guarded_get
def opened_file(path):
    assert threading.get_ident()==owner
    opened.append(str(path))
os.startfile=opened_file
window=show_library(app,ROOT,render_review,make_report);window.withdraw()
def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)
widgets=list(descendants(window));tree=next(w for w in widgets if isinstance(w,ttk.Treeview))
buttons={w.cget('text'):w for w in widgets if isinstance(w,tk.Button)}
phase=[0]
def progress():
    if app.closing:return
    if phase[0]==0 and 'Logs/synthetic' in [v.replace('\\\\','/') for v in tree.get_children()]:
        key=next(v for v in tree.get_children() if v.replace('\\\\','/')=='Logs/synthetic')
        tree.selection_set(key);buttons['多选对比'].invoke();phase[0]=1
    elif phase[0]==1 and opened:
        buttons['设为锁定参考'].invoke();phase[0]=2
    elif phase[0]==2 and app.reference_locked.get():
        app.close();return
    app.root.after(25,progress)
app.root.after(25,progress);app.root.after(5000,app.close);app.root.mainloop()
assert phase[0]==2 and len(opened)==1 and app.reference_locked.get()
assert app.engine.reference is not None
'''
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            env=dict(os.environ,LMU_STINTRIX_DATA_DIR=str(Path(folder)/'data'))
            result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,
                capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
