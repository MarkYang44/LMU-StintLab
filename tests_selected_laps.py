"""Specified whole-lap extraction, regression and original-data integrity."""
import csv,json,math
from pathlib import Path
import shutil,sys,tempfile,unittest
ROOT=Path(__file__).parent;sys.path.insert(0,str(ROOT/'src'))
import laps
import tests as base_tests
from reference import ReferenceLap
TEMPLATE=ROOT/'src'/'compare.html'


class SelectedLapTests(unittest.TestCase):
    def session(self,t,**options):return base_tests.Tests().lap_csv(Path(t)/'session',**options)

    def load_rows(self,f):
        with (f/'inputs.csv').open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream);return reader.fieldnames,list(reader)

    def save_rows(self,f,fields,rows):
        with (f/'inputs.csv').open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)

    def test_selector_lists_only_complete_laps_and_keeps_flags(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);scan=laps.complete_laps(f)
            self.assertEqual([v['number'] for v in scan['laps']],[1,2,3,4])
            self.assertTrue(scan['laps'][1]['lap_invalidated']);self.assertTrue(scan['laps'][2]['in_pits'])
            self.assertEqual(laps.extract_best(f/'inputs.csv')[0]['number'],4)

    def test_pair_export_preserves_originals_and_matches_full_source_samples(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);laps.export_fastest(f,TEMPLATE)
            before={p:p.read_bytes() for p in f.iterdir() if p.is_file()}
            result=laps.export_selected_laps(f,[1,4],TEMPLATE)
            self.assertTrue(Path(result['comparison']).exists())
            for item,number,count in zip(result['exports'],(1,4),(120,110)):
                record=json.loads(Path(item['json']).read_text(encoding='utf-8'));ReferenceLap(record)
                self.assertEqual(record['reference_kind'],'selected');self.assertEqual(record['lap']['number'],number)
                self.assertEqual(record['session']['vehicle'],'BMW M4 LMGT3');self.assertEqual(record['session']['track'],'Test Track')
                self.assertEqual(len(record['data']),count+1);self.assertEqual(record['data'][0][0],0);self.assertEqual(record['data'][-1][0],1000)
                self.assertEqual(record['data'][10][2:6],[.7,.2,.6,.1]);self.assertTrue(record['trajectory']['points'])
                with Path(item['csv']).open(encoding='utf-8',newline='') as stream:rows=list(csv.DictReader(stream))
                self.assertEqual(len(rows),count);self.assertTrue(all(int(float(r['lap']))==number for r in rows))
                self.assertIn('steering',rows[0]);self.assertIn('filtered_steering',rows[0]);self.assertEqual(rows[0]['vehicle'],'BMW M4 LMGT3')
            self.assertEqual({p:p.read_bytes() for p in before},before)
            html=Path(result['comparison']).read_text(encoding='utf-8');self.assertIn('"reference_id":"session:1"',html)

    def test_partial_pair_fails_before_creating_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t)
            for numbers in ([1,0],[4,5],[1,99]):
                with self.assertRaisesRegex(ValueError,'不是可提取的完整圈'):laps.export_selected_laps(f,numbers,TEMPLATE)
            self.assertFalse((f/'SelectedLaps').exists())

    def test_delayed_timer_boundary_counts_only_actual_in_lap_samples(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);fields,rows=self.load_rows(f)
            previous=next(r for r in rows if r['lap']=='1')
            rows=[r for r in rows if float(r['session_time_s'])!=22]
            for when in (22,22.05):
                rows.append(dict(previous,session_time_s=str(when),time_s=str(when),lap_distance_m='995'))
            rows.sort(key=lambda r:float(r['session_time_s']));self.save_rows(f,fields,rows)
            result=laps.export_selected_laps(f,[1]);item=result['exports'][0]
            record=json.loads(Path(item['json']).read_text(encoding='utf-8'))
            with Path(item['csv']).open(encoding='utf-8',newline='') as stream:export=list(csv.DictReader(stream))
            self.assertEqual(record['lap']['sample_count'],120);self.assertEqual(len(export),120)
            self.assertEqual(len(record['data']),121)
            self.assertTrue(all(float(r['session_time_s'])<22 for r in export))

    def test_telemetry_gap_excludes_lap(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t,gap=True);self.assertNotIn(1,[v['number'] for v in laps.complete_laps(f)['laps']])
            with self.assertRaisesRegex(ValueError,'遥测存在缺口'):laps.export_selected_laps(f,[1])

    def test_repeated_or_invalid_selection_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t)
            for numbers in ([1,1],[],[True],[1.2],[-1],[1,2,3]):
                with self.assertRaises(ValueError):laps.export_selected_laps(f,numbers)
            self.assertFalse((f/'SelectedLaps').exists())

    def test_repeated_source_number_is_ambiguous(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);fields,rows=self.load_rows(f)
            for row in rows:
                if row['lap']=='4':row['lap']='1'
            self.save_rows(f,fields,rows)
            self.assertNotIn(1,[v['number'] for v in laps.complete_laps(f)['laps']])
            with self.assertRaisesRegex(ValueError,'圈号重复'):laps.export_selected_laps(f,[1])

    def test_flagged_complete_laps_export_but_cannot_be_hud_references(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);result=laps.export_selected_laps(f,[2,3],TEMPLATE)
            records=[json.loads(Path(v['json']).read_text(encoding='utf-8')) for v in result['exports']]
            self.assertTrue(records[0]['lap']['lap_invalidated']);self.assertTrue(records[1]['lap']['in_pits'])
            for record in records:
                with self.assertRaisesRegex(ValueError,'不能用作 HUD 参考'):ReferenceLap(record)

    def test_legacy_complete_laps_mark_unknown_validity(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t,legacy=True);result=laps.export_selected_laps(f,[1,4],TEMPLATE)
            for item in result['exports']:
                record=json.loads(Path(item['json']).read_text(encoding='utf-8'))
                self.assertEqual(record['lap']['validity'],'unverified_legacy');self.assertEqual(record['lap']['timing_source'],'lap_counter_estimate')
                self.assertFalse(record['lap']['lap_invalidated'])

    def test_unfinished_and_write_error_sessions_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t)
            for status in ('recording','write_error'):
                meta=json.loads((f/'session.json').read_text());meta['status']=status;(f/'session.json').write_text(json.dumps(meta))
                with self.assertRaises(ValueError):laps.complete_laps(f)
                with self.assertRaises(ValueError):laps.export_selected_laps(f,[1,4],TEMPLATE)
            self.assertFalse((f/'SelectedLaps').exists())

    def test_single_lap_extraction_keeps_more_than_summary_limit_and_pedal_spike(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=self.session(t);fields,rows=self.load_rows(f);original=next(r for r in rows if r['lap']=='1');expanded=[]
            for i in range(6000):
                row=dict(original,time_s=str(10+i/500),session_time_s=str(10+i/500),lap_distance_m=str(i/6000*1000),throttle='.01' if i==250 else '.7')
                expanded.append(row)
            rows=[r for r in rows if r['lap']!='1']+expanded;rows.sort(key=lambda r:float(r['session_time_s']));self.save_rows(f,fields,rows)
            result=laps.export_selected_laps(f,[1]);self.assertIsNone(result['comparison'])
            data=json.loads(Path(result['exports'][0]['json']).read_text(encoding='utf-8'))['data']
            self.assertEqual(len(data),6001);self.assertEqual(data[250][2],.01)

    def test_native_context_and_coordinates_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            from tests_laplab import fixture
            from telemetry_import import import_recording
            database=Path(t)/'synthetic.duckdb';fixture(database)
            original=import_recording(database,Path(t)/'generated')
            f=Path(t)/'native';f.mkdir()
            for name in ('inputs.csv','session.json','native_channels.json'):shutil.copyfile(original/name,f/name)
            result=laps.export_selected_laps(f,[2,3],TEMPLATE)
            for item in result['exports']:
                record=json.loads(Path(item['json']).read_text(encoding='utf-8'))
                self.assertEqual(record['trajectory']['source'],'gps_mercator_m');self.assertIn('ABS',record['native_context']['channels'])
                self.assertEqual(len(record['native_context']['channels']['Tyres Wear']['data'][0]),5)
                self.assertGreater(record['conditions']['fuel_l'],0)


if __name__=='__main__':unittest.main(verbosity=2)
