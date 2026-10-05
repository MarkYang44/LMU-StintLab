"""Public synthetic fixtures for session policy, renderer adaptation and launchpad."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from recording_policy import should_record
from racecom_bridge import adapt,lap_rows,write_xlsx,render
from race_model import build_model
from tests import test_core
from storage import atomic_json


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def model(self):return build_model(test_core.Tests().lap_csv(self.root/'session'))

    def test_recording_policy_retains_only_qualifying_and_race(self):
        self.assertEqual([n for n in range(20) if should_record(n)],list(range(5,9))+list(range(10,14)))
        for value in (None,True,False,8.0,'10',-1):self.assertFalse(should_record(value))
        self.assertTrue(should_record(0,demo=True))

    def test_bridge_preserves_unknown_fields_and_excludes_pit_from_best(self):
        model=self.model();value=adapt(model)
        self.assertEqual(value['impact_count'],'未知');self.assertIsNone(value['session_best_lap'])
        self.assertIsNone(value['start_place']);self.assertTrue(all(l['s1'] is None for l in value['laps']))
        valid=[lap for lap in value['laps'] if lap['valid']]
        self.assertEqual(min(valid,key=lambda lap:lap['time'])['num'],4)
        pit=next(lap for lap in value['laps'] if lap['num']==3)
        self.assertFalse(pit['valid']);self.assertTrue(pit['game_valid']);self.assertIn('统计无效',pit['note'])
        self.assertNotIn(5,[lap['num'] for lap in value['laps']])

    def test_workbook_is_original_inline_string_shape_and_escapes_metadata(self):
        value=adapt(self.model());value['laps'][0]['note']='A & <B> 中文'
        path=self.root/'laps.xlsx';write_xlsx(path,lap_rows(value))
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(len(archive.namelist()),5)
            tree=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            values=[node.text for node in tree.findall('.//s:t',ns)]
            self.assertEqual(values[:7],['圈','圈速','Δ','S1','S2','S3','备注']);self.assertIn('A & <B> 中文',values)
        self.assertFalse(list(self.root.glob('*.pending')))

    def test_unfinished_and_disqualified_race_does_not_claim_a_finishing_position(self):
        from race_model import describe
        model=self.model()
        for flag,text in ((2,'DNF'),(3,'DQ')):
            model['summary'].update(finish_flag=flag,finish_place=5)
            value=adapt(model)
            self.assertIsNone(value['finish_place']);self.assertEqual(value['observed_finish_place'],5)
            self.assertEqual(value['stintrix_finish_text'],text)
            self.assertIn(text,describe(dict(event='recording_end',data={'finish_flag':flag})))

    def test_renderer_pair_failure_retains_both_existing_images(self):
        model=self.model();folder=self.root/'output';folder.mkdir()
        for name in ('圈速单.png','比赛日志.png'):(folder/name).write_bytes(b'old')
        calls=[]
        def fake(args,cwd):
            calls.append(args)
            if len(calls)==1:Path(args[2]).write_bytes(b'\x89PNG\r\n\x1a\nfixture');return 0
            return 1
        with patch('racecom_bridge.run',side_effect=fake):
            with self.assertRaises(RuntimeError):render(folder,model,self.root/'Image Generate.exe')
        self.assertTrue(all((folder/name).read_bytes()==b'old' for name in ('圈速单.png','比赛日志.png')))
        self.assertFalse(list(folder.glob('*.pending')))

    def test_empty_session_generates_log_without_inventing_a_lap(self):
        model=self.model();model['laps']=[];model['fastest']=None
        def fake(args,cwd):Path(args[2]).write_bytes(b'\x89PNG\r\n\x1a\nfixture');return 0
        folder=self.root/'output';folder.mkdir()
        with patch('racecom_bridge.run',side_effect=fake):outputs=render(folder,model,self.root/'Image Generate.exe')
        self.assertEqual(set(outputs),{'比赛日志.png'})
        self.assertEqual(json.loads((folder/'_racecom/race_log.json').read_text(encoding='utf-8'))['laps'],[])

    def test_no_silent_style_fallback_when_original_renderer_is_unconfigured(self):
        import renderer_config
        with patch('renderer_config.data_directory',return_value=self.root):
            with self.assertRaisesRegex(ValueError,'尚未配置'):renderer_config.resolve()
            self.assertEqual(renderer_config.resolve('native')['mode'],'native')

    def test_corrupt_renderer_preferences_never_silently_choose_native(self):
        import renderer_config
        for value in ([],{'mode':'typo','executable':None}):
            atomic_json(self.root/'renderer_settings.json',value)
            with patch('renderer_config.data_directory',return_value=self.root):
                with self.assertRaisesRegex(ValueError,'尚未配置'):renderer_config.resolve()

    def test_private_renderer_path_stays_portable_within_data(self):
        import renderer_config
        runtime=self.root/'RaceComRenderer';(runtime/'Source').mkdir(parents=True)
        exe=runtime/'Image Generate.exe';exe.write_bytes(b'fixture');(runtime/'Source/LMU Logo.png').write_bytes(b'fixture')
        renderer_config.save(dict(mode='racecom',executable=str(exe)),self.root)
        saved=json.loads((self.root/'renderer_settings.json').read_text(encoding='utf-8'))
        self.assertFalse(Path(saved['executable']).is_absolute());self.assertEqual(renderer_config.load(self.root)['executable'],str(exe))

    def test_module_edits_preserve_profile_positions_and_sampling(self):
        import control_settings,vehiclelab,sampling
        vehicle=vehiclelab.settings(dict(tyres_position=[17,19],profiles={'*':{'temp_min':50,'temp_max':105}}))
        atomic_json(self.root/'vehicle_settings.json',vehicle)
        sampling.save_settings(self.root/'settings.json',dict(sampling.DEFAULTS,fixed_hz=2400))
        before=(self.root/'settings.json').read_bytes()
        with patch('control_settings.ROOT',self.root):value=control_settings.apply('vehicle',{'reserve_l':'4'})
        self.assertEqual(value['tyres_position'],[17,19]);self.assertEqual(value['profiles']['*']['temp_min'],50)
        self.assertEqual((self.root/'settings.json').read_bytes(),before)

    @unittest.skipUnless(os.name=='nt','Windows Tk')
    def test_control_center_tabs_do_not_start_engine_or_write_preferences(self):
        import control_center
        with patch('control_center.ROOT',self.root),patch('hud.Engine') as engine:
            center=control_center.ControlCenter()
            try:
                for n in (1,2,3,4,0):center.show_page(n);center.root.update()
                engine.assert_not_called();self.assertFalse(list(self.root.glob('*settings.json')))
            finally:center.close()

    @unittest.skipUnless(os.name=='nt','Windows Tk')
    def test_demo_hud_shares_interpreter_and_stopping_keeps_center_alive(self):
        import control_center,hud,engine
        errors=[]
        with patch('control_center.ROOT',self.root),patch('hud.ROOT',self.root),patch('engine.ROOT',self.root),patch('recorder.make_report'):
            center=control_center.ControlCenter();center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.start(True);view=center.hud
                self.assertIs(view.root.tk,center.root.tk)
                center.set_hud('mode','controls');self.assertEqual(view.hud_mode.get(),'controls')
                deadline=time.monotonic()+3
                while not view.engine.recorder.samples and time.monotonic()<deadline:center.root.update();time.sleep(.01)
                self.assertGreater(view.engine.recorder.samples,0);center.stop_hud()
                deadline=time.monotonic()+5
                while view.root.winfo_exists() and time.monotonic()<deadline:center.root.update();time.sleep(.01)
                self.assertFalse(view.root.winfo_exists());self.assertTrue(center.root.winfo_exists());self.assertFalse(errors)
            finally:
                center.close()
                import tkinter as tk
                try:
                    while center.root.winfo_exists():center.root.update();time.sleep(.01)
                except tk.TclError:pass

    def test_publication_excludes_renderer_preferences_and_private_adapter_data(self):
        from tools.audit_publication import allowed
        for name in ('src/renderer_settings.json','src/image_generate_config.json','data/RaceComRenderer/Image Generate.exe','src/_racecom/race_log.json'):
            self.assertFalse(allowed(name))
