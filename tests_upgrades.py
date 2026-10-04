"""Seven-feature regressions: integrity, failure visibility and truthful analysis."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT/'src'))
import inputscope as app
import sessionlab,storage,diagnostics,library
from reference import ReferenceLap,DistanceAligner,best_reference
import tests as base_tests
fixture=base_tests.fixture


def clean_session(folder):
    base_tests.Tests().lap_csv(folder)
    path=folder/'inputs.csv'
    with path.open(encoding='utf-8',newline='') as f:reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    for row in rows:row.update(lap_invalidated='0',in_pits='0',fuel_l='20',tyre_compound='1',track_temp_c='30',wetness='0',tc_level='3',abs_level='2')
    with path.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    return folder


def ref_value():
    return dict(format='inputscope.fastest-lap',version=1,session=dict(track='T',vehicle='C'),
        lap=dict(number=1,track_length_m=1000,time_s=10),data=[[i*10,i/10,.7,.1,.6,.1,360] for i in range(101)],
        trajectory=dict(source='recorded_world_xz',points=[[i/10,i*10,i*10,0] for i in range(101)]),conditions={})


class Upgrades(unittest.TestCase):
    def test_stable_is_observed_median_lap_and_original_unchanged(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=clean_session(Path(t)/'session');paths=[folder/'inputs.csv',folder/'session.json']
            before=[p.read_bytes() for p in paths];v=sessionlab.analyze_session(folder)
            self.assertEqual(v['recent_stability']['count'],4)
            self.assertAlmostEqual(v['recent_stability']['median'],10)
            stable=json.loads((folder/v['stable_reference_file']).read_text(encoding='utf-8'))
            self.assertEqual(stable['lap']['number'],3);self.assertEqual(stable['lap']['time_s'],9)
            self.assertEqual(stable['conditions']['fuel_l'],20);ReferenceLap(stable)
            self.assertEqual([p.read_bytes() for p in paths],before)
            self.assertEqual(v['laps'][0]['start_time_s'],10)
            self.assertEqual(v['laps'][0]['end_time_s'],22)

    def test_less_than_three_does_not_invent_stable_reference(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=base_tests.Tests().lap_csv(Path(t)/'session');v=sessionlab.analyze_session(f)
            self.assertEqual(v['recent_stability']['count'],2);self.assertIsNone(v['stable_reference_file'])

    def test_condition_mismatch_and_unknown(self):
        self.assertFalse(sessionlab.condition_check({'fuel_l':20},{'fuel_l':24})['allowed'])
        v=sessionlab.condition_check({},{});self.assertTrue(v['allowed']);self.assertEqual(len(v['unknown']),6)

    def test_automatic_prefers_known_compatible_conditions(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            for name,fuel,duration in [('known',20,12),('different',35,8),('unknown',None,10)]:
                folder=Path(t)/'Logs'/name;folder.mkdir(parents=True);v=ref_value()
                for row in v['data']:row[1]*=duration/10
                v['lap']['time_s']=duration
                v['conditions']={'fuel_l':fuel} if fuel else {}
                (folder/'fast.lap.json').write_text(json.dumps(v),encoding='utf-8')
                (folder/'fastest_lap_summary.json').write_text(json.dumps(dict(session=v['session'],lap=v['lap'],file='fast.lap.json',conditions=v['conditions'])),encoding='utf-8')
            selected=best_reference(t,dict(track='T',vehicle='C',track_length=1000,conditions={'fuel_l':20}))
            self.assertIn('known',selected.path);self.assertEqual(selected.duration,12)

    def test_alignment_projection_gap_teleport_and_conditions(self):
        ref=ReferenceLap(ref_value());align=DistanceAligner()
        s=dict(track='T',vehicle='C',track_length=1000,lap=1,lap_start=0,et=1,distance=100,speed=360,position=[100,0,0])
        self.assertEqual(align.update(s,ref),100);self.assertEqual(align.state['mode'],'位置投影')
        s.update(et=1.05,position=[105,0,0]);self.assertAlmostEqual(align.update(s,ref),105)
        s.update(et=1.5);self.assertIsNone(align.update(s,ref));self.assertEqual(align.state['mode'],'遥测缺口')
        s.update(et=1.51,position=[999,0,0]);self.assertIsNone(align.update(s,ref));self.assertEqual(align.state['mode'],'坐标跳变')
        ref.conditions={'tyre_compound':1};s['conditions']={'tyre_compound':2};self.assertIsNone(align.update(s,ref))
        self.assertIsNone(ref.sample(s))

    def test_fuel_matching_uses_observed_lap_start_not_consumed_fuel(self):
        ref=ReferenceLap(ref_value());ref.conditions={'fuel_l':20};align=DistanceAligner()
        sample=dict(track='T',vehicle='C',track_length=1000,lap=1,lap_start=0,et=0,distance=0,speed=360,conditions={'fuel_l':20})
        self.assertIsNotNone(align.update(sample,ref))
        sample.update(et=.1,distance=10,conditions={'fuel_l':17})
        self.assertIsNotNone(align.update(sample,ref));self.assertEqual(align.state['matching_conditions']['fuel_l'],20)
        sample.update(lap=2,lap_start=.2,et=.2,distance=0)
        self.assertIsNone(align.update(sample,ref));self.assertEqual(align.state['mode'],'条件不匹配')

    def test_action_counts_time_based_at_different_sampling_rates(self):
        def rows(hz):
            return [dict(session_time_s=i/hz,throttle=1 if i/hz<1 or i/hz>2 else .2,
                brake=max(0,1-i/hz),steering=.1*math.sin(i/hz*math.tau),
                filtered_throttle=1 if i/hz<1 or i/hz>2 else .2,filtered_brake=max(0,1-i/hz),
                filtered_steering=.1*math.sin(i/hz*math.tau)) for i in range(3*hz+1)]
        low=sessionlab.actions(rows(100));high=sessionlab.actions(rows(1000))
        self.assertEqual(low['raw']['throttle_lifts'],1);self.assertEqual(high['raw']['throttle_lifts'],1)
        self.assertEqual(low['raw']['steering_corrections'],high['raw']['steering_corrections'])
        self.assertAlmostEqual(low['raw']['brake_release_pct_s'],100,places=6)
        self.assertAlmostEqual(high['raw']['brake_release_pct_s'],100,places=6)
        self.assertIsNone(high['abs_active_s']);self.assertEqual(high['input_difference_pct'],[0,0,0])

    def test_background_writer_drains_and_checkpoint_counts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            w=storage.BatchWriter(t,['a','b']);expected=3000
            for i in range(expected):w.add([i,'车辆'])
            stats=w.finish();self.assertEqual(stats['written_rows'],expected)
            with (Path(t)/'inputs.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.reader(f))
            self.assertEqual(len(rows),expected+1);self.assertEqual(rows[-1],[str(expected-1),'车辆'])
            c=json.loads((Path(t)/'recording_checkpoint.json').read_text());self.assertTrue(c['closed']);self.assertEqual(c['rows'],expected)
            self.assertEqual(c['committed_bytes'],(Path(t)/'inputs.csv').stat().st_size)

    def test_overflow_is_explicit_and_accepted_samples_retained(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            w=storage.BatchWriter(t,['a'],capacity=1);original=w.csv;entered=threading.Event();release=threading.Event()
            class Slow:
                def writerows(self,rows):entered.set();release.wait(2);original.writerows(rows)
            w.csv=Slow()
            try:
                w.add([1]);self.assertTrue(entered.wait(2));w.add([2])
                with self.assertRaisesRegex(storage.StorageError,'队列已满'):w.add([3])
            finally:release.set();result=w.finish()
            self.assertEqual(result['written_rows'],2)

    def test_background_io_error_is_not_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            w=storage.BatchWriter(t,['a'])
            class Bad:
                def writerows(self,rows):raise OSError('injected disk failure')
            w.csv=Bad();w.add([1])
            with self.assertRaisesRegex(storage.StorageError,'injected disk failure'):w.finish()

    def test_engine_writer_failure_stops_segment_and_rejects_analysis(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            sample=app.extract(fixture())
            class Feed:
                def read(self):return dict(sample,et=time.monotonic())
                def close(self):pass
            with patch.object(storage.BatchWriter,'add',side_effect=storage.StorageError('injected queue failure')):
                engine=app.Engine(output=Path(t)/'Logs',reader_factory=Feed)
                time.sleep(.1);engine.stop.set();engine.thread.join(3)
            self.assertFalse(engine.thread.is_alive());meta=json.loads((engine.last_folder/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'],'write_error');self.assertIn('injected',meta['end_reason'])
            self.assertEqual(len(list((Path(t)/'Logs').iterdir())),1)
            with self.assertRaisesRegex(ValueError,'写盘错误'):sessionlab.analyze_session(engine.last_folder)

    def test_recovery_committed_prefix_only_and_original_retained(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            root=Path(t);f=root/'Logs'/'crash';f.mkdir(parents=True)
            data=b'a,b\r\n1,2\r\n';(f/'inputs.csv').write_bytes(data+b'incomplete')
            storage.atomic_json(f/'session.json',dict(status='recording'))
            storage.atomic_json(f/'recording_checkpoint.json',dict(version=1,pid=os.getpid(),rows=1,committed_bytes=len(data),closed=False,updated_utc='2026-10-03T12:00:00Z'))
            before=(f/'inputs.csv').read_bytes()
            with self.assertRaisesRegex(ValueError,'仍在运行'):storage.recover_session(f,root)
            with patch('storage.process_alive',return_value=False):out=storage.recover_session(f,root)
            self.assertEqual((out/'inputs.csv').read_bytes(),data);self.assertEqual((f/'inputs.csv').read_bytes(),before)
            self.assertEqual(json.loads((out/'session.json').read_text())['samples'],1)

    def test_compressed_backup_verified_and_inventory_notes_separate(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            root=Path(t);folder=clean_session(root/'Logs'/'test');before=(folder/'session.json').read_bytes()
            stats=storage.compress_session(folder)
            self.assertEqual(stats['source_sha256'],hashlib.sha256((folder/'inputs.csv').read_bytes()).hexdigest())
            library.save_note(root,str(folder.relative_to(root)),'练习',True);v=library.inventory(root)[0]
            self.assertEqual(v['note'],'练习');self.assertTrue(v['traffic']);self.assertEqual((folder/'session.json').read_bytes(),before)
            with self.assertRaises(ValueError):library.save_note(root,'../escape','bad')

    def test_latency_counts_each_unique_sample_once(self):
        d=diagnostics.Diagnostics();sample=dict(et=1,_received_perf=time.perf_counter())
        for _ in range(3):d.paint(time.perf_counter(),sample,120)
        s=d.snapshot();self.assertEqual(s['latency']['count'],1);self.assertEqual(s['draw']['count'],3)
        self.assertEqual(s['interval']['count'],2)

    def test_optional_nan_does_not_drop_valid_input(self):
        data=fixture();data.telemetry.telemInfo[0].mFuel=float('nan');sample=app.extract(data)
        self.assertIsNotNone(sample);self.assertEqual(sample['conditions']['fuel_l'],'')

    def test_duplicate_polls_keep_first_receipt_and_session_performance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            sample=app.extract(fixture())
            class Feed:
                def read(self):return dict(sample)
                def close(self):pass
            engine=app.Engine(output=Path(t)/'Logs',reader_factory=Feed,settings=dict(app.DEFAULTS,fixed_hz=1000))
            try:
                time.sleep(.06)
                with engine.lock:first=engine.latest.copy()
                time.sleep(.06)
                with engine.lock:second=engine.latest.copy()
                self.assertIsNotNone(first['_received_perf']);self.assertEqual(first['_received_perf'],second['_received_perf'])
            finally:
                engine.stop.set();engine.thread.join(3)
                if engine.recorder.report_thread:engine.recorder.report_thread.join(3)
            self.assertTrue((engine.last_folder/'performance.json').exists())

    def test_waiting_for_game_is_not_counted_as_missed_poll_work(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            class Offline:
                def __init__(self):raise OSError('no game map')
            engine=app.Engine(output=t,reader_factory=Offline,settings=dict(app.DEFAULTS,fixed_hz=4000))
            time.sleep(.55);engine.stop.set();engine.thread.join(2)
            self.assertLess(engine.missed_cycles,20);self.assertEqual(engine.actual_rates(),(0,0))

    def test_lock_selected_reference_keeps_new_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            value=app.App.__new__(app.App)
            class Var:
                def __init__(self,v):self.v=v
                def get(self):return self.v
                def set(self,v):self.v=v
            value.reference_locked=Var(False);value.reference_auto=Var(True);value.reference_on=Var(False)
            value.reference_kind=Var('fastest');value.reference_settings={};value.reference_generation=0
            class Engine:pass
            value.engine=Engine();value.engine.lock=threading.Lock();value.engine.reference=ReferenceLap(ref_value(),'old')
            value.engine.reference_points=[];value.engine.reference_revision=0
            path=Path(t)/'chosen.lap.json';path.write_text(json.dumps(ref_value()))
            with patch.object(app,'ROOT',Path(t)),patch.object(app.filedialog,'askopenfilename',return_value=str(path)):
                value.select_reference()
            self.assertEqual(value.reference_settings['path'],str(path));self.assertTrue(value.reference_locked.get())


if __name__=='__main__':unittest.main(verbosity=2)
