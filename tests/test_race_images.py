"""Synthetic official scoring, native output and loss-free race packaging."""
import csv
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from race_journal import RaceJournal,capture
from race_model import build_model,lap_time
from race_report import digest,generate
from race_art import select_car
from tests import test_core


def sample(et=0,lap=0,start=0,completed=0,**updates):
    value=dict(et=et,session=10,lap=lap,lap_start=start,lap_invalidated=False,in_pits=False,finish=0,speed=150,
        race_state=dict(_key=(et,),completed_laps=completed,place=3,scoring_lap_start=start,last_lap=None,
            sector1=None,sector12=None,phase=5,penalties=0,pit_stops=0,impact_et=None,
            impact_magnitude=None,path_lateral=0,track_edge=8))
    state=updates.pop('state',{});value.update(updates);value['race_state'].update(state);return value


class RaceImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def folder(self,legacy=False):return test_core.Tests().lap_csv(self.root/'session',legacy=legacy)
    def events(self,folder):
        with (folder/'race_events.csv').open(encoding='utf-8',newline='') as stream:
            return [(row['event'],json.loads(row['payload_json'])) for row in csv.DictReader(stream)]

    def test_capture_cached_scoring_and_cumulative_sector_meaning(self):
        data=test_core.fixture();info=data.scoring.scoringInfo;p=data.scoring.vehScoringInfo[1];car=data.telemetry.telemInfo[0]
        p.mLastLapTime=100;p.mLastSector1=30;p.mLastSector2=65;p.mTotalLaps=1;p.mPlace=2;info.mGamePhase=5
        a=capture(data,car,p,info)
        self.assertEqual((a['sector1'],a['sector12']),(30,65))
        p.mTotalLaps=2;p.mPlace=1 # frozen scoring timestamp: finish updates still retained
        b=capture(data,car,p,info,a)
        self.assertEqual((b['completed_laps'],b['place']),(2,1))
        self.assertNotIn('SteamID',str(b))

    def test_only_observed_race_grid_is_presented_as_starting_position(self):
        s=sample(session=0,state=dict(phase=2,place=2));j=RaceJournal(self.root,s);j.observe(s)
        self.assertIsNone(j.summary['grid_place'])
        j.observe(sample(.1,session=10,state=dict(phase=2,place=3)))
        j.observe(sample(.2,session=10,state=dict(phase=5,place=1)))
        self.assertEqual((j.summary['grid_place'],j.summary['finish_place']),(3,1));j.finish('test')

    def test_official_lap_final_scoring_and_zero_based_counter(self):
        s=sample();j=RaceJournal(self.root,s);j.observe(s)
        j.observe(sample(9.9));j.observe(sample(10,1,10,1,state=dict(last_lap=10,sector1=3,sector12=7)))
        # Final official lap arrives before the telemetry lap timer advances.
        j.observe(sample(22,1,10,2,finish=1,state=dict(last_lap=12,sector1=4,sector12=8,scoring_lap_start=22)))
        j.finish('finish flag 1');laps=[p for name,p in self.events(self.root) if name=='official_lap']
        self.assertEqual([(p['num'],p['time'],p['s1'],p['s2'],p['s3']) for p in laps],[(1,10,3,4,3),(2,12,4,4,4)])
        self.assertEqual(laps[0]['telemetry_lap'],0)
        self.assertEqual(json.loads((self.root/'race_summary.json').read_text(encoding='utf-8'))['finish_flag'],1)

    def test_delayed_invalid_lap_does_not_inherit_next_lap_validity(self):
        j=RaceJournal(self.root,sample());j.observe(sample());j.observe(sample(5,lap_invalidated=True))
        j.observe(sample(10,1,10,0));j.observe(sample(10.2,1,10,1,state=dict(last_lap=None)))
        j.finish('test');p=next(p for name,p in self.events(self.root) if name=='official_lap')
        self.assertFalse(p['valid']);self.assertEqual(p['time'],10);self.assertIsNone(p['s1'])

    def test_skipped_laps_cannot_relabel_multi_lap_telemetry_as_one_complete_lap(self):
        j=RaceJournal(self.root,sample());j.observe(sample())
        j.observe(sample(30,3,30,3,state=dict(last_lap=10,sector1=3,sector12=7)))
        j.finish('test');p=next(p for name,p in self.events(self.root) if name=='official_lap')
        self.assertEqual((p['num'],p['time'],p['start'],p['missed_laps']),(3,10,20,2))
        self.assertTrue(p['partial']);self.assertIsNone(p['telemetry_lap'])
        f=self.folder()
        # Use the synthetic journal with the CSV to exercise a missing anchor.
        (f/'race_events.csv').write_bytes((self.root/'race_events.csv').read_bytes())
        m=build_model(f);lap=next(lap for lap in m['laps'] if lap['timing_source']=='official')
        self.assertEqual(lap['num'],3);self.assertTrue(lap['partial']);self.assertFalse(lap['best'])

    def test_contact_dedup_and_offtrack_estimate_are_not_official_warnings(self):
        initial=sample(5,start=0,state=dict(impact_et=3,impact_magnitude=1))
        j=RaceJournal(self.root,initial);j.observe(initial)
        for et in (6,6.1,6.6,7):
            j.observe(sample(et,state=dict(impact_et=et,impact_magnitude=3,path_lateral=10)))
        j.observe(sample(9,state=dict(impact_et=9,impact_magnitude=3)))
        j.finish('test');s=json.loads((self.root/'race_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(s['impact_count'],2);self.assertEqual(s['offtrack_estimate_count'],1)
        events=self.events(self.root);self.assertEqual(sum(name=='impact' for name,_ in events),2)
        self.assertIn('非官方警告',next(p['definition'] for name,p in events if name=='offtrack_estimate'))

    def test_unchanged_samples_emit_no_repeated_events_and_writer_closes_on_error(self):
        j=RaceJournal(self.root,sample());j.observe(sample())
        for _ in range(10000):j.observe(sample())
        self.assertEqual(j.rows,1)
        with patch.object(j,'emit',side_effect=OSError('full')):
            with self.assertRaises(OSError):j.finish('test')
        self.assertFalse(j.writer.thread.is_alive())

    def test_legacy_missing_fields_and_partial_laps_remain_unknown(self):
        f=self.folder(True);m=build_model(f)
        self.assertFalse(m['scoring_available']);self.assertIsNone(m['fastest'])
        self.assertTrue(all(lap['valid'] is None and lap['s1'] is None for lap in m['laps']))
        self.assertTrue(m['laps'][0]['partial']);self.assertFalse(m['laps'][-1]['complete'])
        self.assertIsNone(m['laps'][-1]['time']);self.assertEqual(len(m['laps']),6)
        self.assertEqual(lap_time(59.9996),'1:00.000')
        self.assertEqual(m['origin'],5)

    def test_fastest_sheet_respects_existing_invalid_pit_partial_rules(self):
        m=build_model(self.folder())
        self.assertEqual(m['fastest']['num'],4)
        self.assertEqual(m['fastest']['time'],11)
        self.assertFalse(m['laps'][3]['best'])

    def test_official_number_and_sectors_override_only_matching_lap(self):
        f=self.folder();s=sample(10,1,10,1);j=RaceJournal(f,s);j.observe(s)
        j.observe(sample(22,2,22,2,state=dict(last_lap=12,sector1=3,sector12=8)));j.finish('test')
        m=build_model(f);lap=next(lap for lap in m['laps'] if lap['start']==10)
        self.assertEqual((lap['num'],lap['telemetry_lap'],lap['time'],lap['s1'],lap['s2'],lap['s3']),(2,1,12,3,5,4))
        self.assertEqual(m['lap_number_source'],'official');self.assertEqual(m['laps'][-1]['num'],6)
        self.assertTrue(any(e['event']=='official_lap' for e in m['events']))

    @unittest.skipUnless(os.name=='nt','Windows native raster')
    def test_real_png_atomic_cache_and_archive_roundtrip(self):
        f=self.folder();before={n:digest(f/n) for n in ('inputs.csv','session.json')}
        receipt=generate(f,car_directory=self.root/'empty')
        for name in ('圈速单.png','比赛日志.png'):
            raw=(f/name).read_bytes();self.assertEqual(raw[:8],b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II',raw[16:24])[0],1800)
        with patch('race_report.build_model',side_effect=AssertionError('cache miss')):self.assertEqual(generate(f,car_directory=self.root/'empty'),receipt)
        self.assertEqual(before,{n:digest(f/n) for n in before})
        (f/'圈速单.png').write_bytes(b'broken');generate(f,car_directory=self.root/'empty')
        self.assertEqual((f/'圈速单.png').read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
        from session_archive import export_session,import_session
        logs=self.root/'data'/'Logs';logs.mkdir(parents=True);target=logs/'test';f.rename(target)
        package=export_session(self.root/'data','Logs/test',self.root/'packages')
        restored=Path(import_session(self.root/'restored',package['path'])['folder'])
        self.assertTrue(all(digest(restored/name)==digest(target/name) for name in receipt['files']))

    @unittest.skipUnless(os.name=='nt','Windows native raster')
    def test_pagination_keeps_all_laps_events_and_source(self):
        f=self.folder();m=build_model(f)
        m['laps']=[dict(m['laps'][1],num=i+1) for i in range(80)]
        m['events']=[dict(time=i,event='pit_entry',data={}) for i in range(100)]
        with patch('race_report.build_model',return_value=m):receipt=generate(f,car_directory=self.root/'empty')
        self.assertEqual((receipt['lap_count'],receipt['event_count']),(80,100))
        self.assertEqual(len([name for name in receipt['files'] if name.endswith('.png')]),6)
        for title in ('圈速单','比赛日志'):self.assertTrue((f/(title+'_003.png')).is_file())
        self.assertEqual(len(json.loads((f/'race_log.json').read_text(encoding='utf-8'))['events']),100)

    def test_car_model_match_bounds_and_path_escape(self):
        art=self.root/'art';art.mkdir();(art/'BMW M4.png').write_bytes(b'fixture')
        catalog={'cars':{'BMW M4.png':{'aliases':['BMW M4 LMGT3'],'subject_bounds':[.13,.34,.74,.89]}}}
        (art/'car_calibration.json').write_text(json.dumps(catalog))
        selected=select_car('BMW M4 LMGT3',art);self.assertEqual(selected[0],art/'BMW M4.png')
        self.assertLess(selected[1][0],.13);self.assertGreater(selected[1][2],.74)
        self.assertIsNone(select_car('BMW M8',art))
        catalog['cars']['BMW M4.png']['subject_bounds']=[.8,0,.2,1]
        (art/'car_calibration.json').write_text(json.dumps(catalog));self.assertIsNone(select_car('BMW M4',art))
        catalog={'cars':{'../outside.png':{'aliases':['BMW M4'],'subject_bounds':[0,0,1,1]}}}
        (self.root/'outside.png').write_bytes(b'fixture');(art/'car_calibration.json').write_text(json.dumps(catalog))
        self.assertIsNone(select_car('BMW M4',art))

    def test_recording_rejected_and_raster_failure_keeps_source(self):
        f=self.folder();before=digest(f/'inputs.csv')
        with patch('race_report.pages',side_effect=OSError('native failure')):
            with self.assertRaises(OSError):generate(f,car_directory=self.root/'empty')
        self.assertEqual(digest(f/'inputs.csv'),before);self.assertTrue((f/'race_images_error.txt').is_file())
        self.assertFalse(list(f.glob('*.pending')))
        meta=json.loads((f/'session.json').read_text());meta['status']='recording';(f/'session.json').write_text(json.dumps(meta))
        with self.assertRaises(ValueError):generate(f)

    def test_automatic_report_also_runs_when_html_fails(self):
        import session_reports
        f=self.folder()
        with patch('session_reports.analyze_session'),patch('session_reports.endurance.analyze'),patch('session_reports.export_fastest',return_value=(None,None)),patch('session_reports.render_review',side_effect=OSError('HTML failed')),patch('race_report.generate') as render:
            with self.assertRaises(OSError):session_reports.make_report(f)
        render.assert_called_once_with(f)

    def test_engine_final_scoring_same_et_still_gets_recorded(self):
        import inputscope
        import threading
        import time
        base=inputscope.extract(test_core.fixture(et=0));last=[0];done=threading.Event()
        class Feed:
            def read(self):
                last[0]+=1
                if last[0]<4:return dict(base,**sample())
                return dict(base,**sample(0,completed=1,finish=1,state=dict(last_lap=100,sector1=30,sector12=65,place=1)))
            def close(self):pass
        with patch('recorder.make_report',side_effect=lambda folder:done.set()):
            engine=inputscope.Engine(output=self.root/'Logs',reader_factory=Feed)
            try:self.assertTrue(done.wait(3))
            finally:
                engine.stop.set();engine.wake.set();engine.thread.join(3)
                for worker in engine.recorder.pending_reports:worker.join(3)
        self.assertFalse(engine.thread.is_alive());self.assertEqual(engine.recorder.samples,1)
        summary=json.loads((engine.last_folder/'race_summary.json').read_text(encoding='utf-8'))
        self.assertEqual((summary['finish_flag'],summary['finish_place']),(1,1))
        self.assertTrue(any(name=='official_lap' for name,_ in self.events(engine.last_folder)))

    def test_recovery_keeps_only_committed_events(self):
        import storage
        f=self.root/'Logs'/'crash';f.mkdir(parents=True)
        (f/'inputs.csv').write_bytes(b'a,b\r\n1,2\r\nTAIL')
        committed=b'session_time_s,event,payload_json\r\n1,pit_entry,{}\r\n'
        (f/'race_events.csv').write_bytes(committed+b'TAIL')
        storage.atomic_json(f/'session.json',dict(status='recording',race_journal=dict(scoring_available=True)))
        storage.atomic_json(f/'recording_checkpoint.json',dict(version=1,pid=0,rows=1,committed_bytes=10,updated_utc='2026-10-04T00:00:00Z'))
        storage.atomic_json(f/'race_events_checkpoint.json',dict(committed_bytes=len(committed)))
        with patch('storage.process_alive',return_value=False):out=storage.recover_session(f,self.root)
        self.assertEqual((out/'race_events.csv').read_bytes(),committed)
        self.assertEqual((f/'race_events.csv').read_bytes(),committed+b'TAIL')
        self.assertTrue(json.loads((out/'race_summary.json').read_text(encoding='utf-8'))['recovered'])
