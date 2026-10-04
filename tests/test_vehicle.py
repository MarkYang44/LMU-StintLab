"""SDK units, qualified fuel history, durable auxiliary recording and exports."""
import csv
import hashlib
import json
import math
import os
import threading
from types import SimpleNamespace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import vehiclelab as v,inputscope as app,laps,storage,sessionlab
from tests.test_core import fixture
from tests import test_core as base_tests


def sample(t,fuel=None,**changes):
    data=v.demo_vehicle(t);data.update(fuel_l=50-.2*t if fuel is None else fuel,virtual_energy_pct=100-.1*t,
        completed_laps=int(t//10),max_laps=10,remaining_s=None)
    s=dict(track='Test Track',vehicle_name='Test Car',vehicle=data,driver='D',session=10,player_id=1,et=t,
        lap=int(t//10)+1,lap_start=int(t//10)*10,distance=(t%10)*100,track_length=1000,
        lap_invalidated=False,in_pits=False,finish=0)
    s.update(changes);return s


def driven(config=None,change=None):
    planner=v.FuelPlanner(config)
    for i in range(2001):
        s=sample(i/100)
        if change:change(s)
        planner.update(s)
    return planner,s


class VehicleTests(unittest.TestCase):
    def test_sdk_temperature_mapping_pressure_and_wear(self):
        data=fixture();car=data.telemetry.telemInfo[0]
        for w in car.mWheels:w.mPressure=170;w.mTemperature[:]=[343.15,353.15,363.15];w.mTireCarcassTemperature=333.15;w.mWear=.95;w.mOptimalTemp=85
        out=app.extract(data)['vehicle_data']
        self.assertAlmostEqual(out['fl_inner_c'],90);self.assertAlmostEqual(out['fr_inner_c'],70)
        self.assertAlmostEqual(out['rl_outer_c'],70);self.assertAlmostEqual(out['rr_outer_c'],90)
        self.assertAlmostEqual(out['fl_carcass_c'],60);self.assertEqual(out['fl_pressure_kpa'],170)
        self.assertEqual(out['fl_wear_fraction'],.95);self.assertEqual(out['fl_optimal_c'],85)

    def test_energy_units_separate_battery_virtual_and_power(self):
        data=fixture();car=data.telemetry.telemInfo[0];car.mBatteryChargeFraction=.6;car.mVirtualEnergy=.8
        car.mElectricBoostMotorState=3;car.mElectricBoostMotorTorque=-100;car.mElectricBoostMotorRPM=6000;car.mRegen=40
        out=app.extract(data)['vehicle_data']
        self.assertEqual(out['battery_soc_pct'],60);self.assertAlmostEqual(out['virtual_energy_pct'],80,places=4)
        self.assertAlmostEqual(out['electric_power_kw'],-math.tau*10);self.assertEqual(out['regen_kw'],40)

    def test_missing_invalid_and_unavailable_values_remain_missing(self):
        data=fixture();car=data.telemetry.telemInfo[0];car.mWheels[0].mTemperature[0]=math.nan
        car.mWheels[0].mWear=math.nan;car.mVirtualEnergy=2;car.mFuel=math.nan
        out=app.extract(data)['vehicle_data'];self.assertIsNone(out['fl_middle_c']);self.assertIsNone(out['fl_pressure_kpa'])
        self.assertIsNone(out['fl_wear_fraction']);self.assertIsNone(out['fuel_l']);self.assertIsNone(out['battery_soc_pct']);self.assertIsNone(out['virtual_energy_pct'])

    def test_safety_flags_survive_zero_pressure_and_disabled_thresholds(self):
        data=fixture();data.telemetry.telemInfo[0].mWheels[0].mFlat=True
        out=app.extract(data)['vehicle_data'];self.assertEqual(out['fl_pressure_kpa'],0)
        self.assertIn('FL 爆胎',v.tyre_alerts(out,v.DEFAULT_PROFILE))

    def test_custom_thresholds_do_not_alarm_by_default(self):
        values=v.demo_vehicle(0);values['fl_middle_c']=150;values['fr_pressure_kpa']=250
        self.assertEqual(v.tyre_alerts(values,v.DEFAULT_PROFILE),[])
        p=v.profile({'alerts':True});messages=v.tyre_alerts(values,p)
        self.assertIn('FL 胎温高',messages);self.assertIn('FR 胎压超限',messages)

    def test_settings_validate_and_do_not_share_profiles(self):
        self.assertFalse(v.settings()['tyres_enabled'])
        for options in ({'record_hz':0},{'record_hz':10.5},{'history_laps':21},{'reserve_l':-1},{'target_mode':'wrong'},{'profiles':{'C':{'temp_min':120,'temp_max':80}}}):
            with self.assertRaises(ValueError):v.settings(options)
        a=v.settings();a['profiles']['C']={};self.assertNotIn('C',v.settings()['profiles'])

    def test_fuel_complete_laps_predict_with_safety_margin(self):
        planner,s=driven();estimate=planner.estimate(s)
        self.assertEqual(estimate['count'],2);self.assertAlmostEqual(estimate['rate_l'],2)
        self.assertAlmostEqual(estimate['remaining_laps'],8);self.assertAlmostEqual(estimate['required_l'],18)
        self.assertAlmostEqual(estimate['range_laps'],23);self.assertAlmostEqual(estimate['margin_l'],28)
        self.assertAlmostEqual(estimate['energy_rate_pct'],1)

    def test_current_partial_lap_and_mid_lap_start_not_promoted(self):
        planner=v.FuelPlanner()
        for i in range(500,1501):planner.update(sample(i/100))
        self.assertEqual(len(planner.history),0)

    def test_invalid_pit_and_refuelling_laps_are_excluded(self):
        for mode in ('invalid','pit','refuelling'):
            def change(s):
                if mode=='invalid' and 3<s['et']<4:s['lap_invalidated']=True
                if mode=='pit' and 3<s['et']<4:s['in_pits']=True
                if mode=='refuelling' and s['et']>=4:s['vehicle']['fuel_l']+=10
            planner,_=driven(change=change)
            self.assertEqual([r['number'] for r in planner.history],[2],mode)

    def test_gaps_distance_resets_and_session_changes_clear_or_exclude(self):
        planner=v.FuelPlanner()
        for i in range(1001):
            if 200<i<500:continue
            planner.update(sample(i/100))
        self.assertFalse(planner.history)
        planner,s=driven();s['vehicle_name']='Other Car';planner.update(s);self.assertFalse(planner.history)
        planner,s=driven();planner.update(sample(.01));self.assertFalse(planner.history)

    def test_repeated_frames_do_not_create_history(self):
        planner=v.FuelPlanner();s=sample(0)
        for _ in range(100):planner.update(s)
        self.assertEqual(planner.group['count'],1)

    def test_no_valid_consumption_does_not_invent_fuel_estimate(self):
        planner,s=driven(change=lambda s:s['vehicle'].update(fuel_l=50))
        estimate=planner.estimate(s);self.assertIsNone(estimate['rate_l']);self.assertIsNone(estimate['required_l'])

    def test_timed_strategy_counts_from_zero_and_adds_finish_lap(self):
        planner,s=driven({'target_mode':'time','target_value':.5})
        estimate=planner.estimate(s);self.assertAlmostEqual(estimate['remaining_laps'],2)
        self.assertAlmostEqual(estimate['required_l'],6)

    def test_practice_or_unknown_schedule_is_not_a_race_prediction(self):
        planner,s=driven();s['vehicle']['race_session']=0
        estimate=planner.estimate(s);self.assertIsNone(estimate['required_l']);self.assertIsNotNone(estimate['range_laps'])
        s['vehicle'].update(race_session=1,max_laps=None,remaining_s=None);self.assertIsNone(planner.estimate(s)['remaining_laps'])

    def test_finished_session_needs_no_additional_fuel(self):
        planner,s=driven();s['finish']=1;estimate=planner.estimate(s)
        self.assertEqual(estimate['remaining_laps'],0);self.assertEqual(estimate['required_l'],0);self.assertEqual(estimate['add_l'],0)

    def test_conservative_vs_median_and_capacity_limit(self):
        planner,s=driven();planner.history[0]['fuel_used_l']=3
        self.assertEqual(planner.estimate(s)['rate_l'],3)
        planner.configure({'rate_mode':'median'});self.assertEqual(planner.estimate(s)['rate_l'],2.5)
        s['vehicle']['fuel_capacity_l']=10;self.assertTrue(planner.estimate(s)['exceeds_capacity'])

    def test_native_declared_units_convert_without_guessing(self):
        series={'TyresPressure':dict(unit='bar',event=False,data=[[0,1.7,1.8,1.9,2.0]]),
            'TyresTempLeft':dict(unit='K',event=False,data=[[0,343.15,353.15,363.15,373.15]]),
            'TyresTempRight':dict(unit='°C',event=False,data=[[0,90,80,70,60]]),
            'Virtual Energy':dict(unit='fraction',event=False,data=[[0,.75]]),'SoC':dict(unit='%',event=False,data=[[0,60]])}
        look=lambda s,t,offset:s['data'][0][1:]
        out=v.native_values(series,0,look);self.assertEqual(out['fl_pressure_kpa'],170)
        self.assertEqual(out['fl_inner_c'],90);self.assertAlmostEqual(out['fr_inner_c'],80)
        self.assertEqual(out['virtual_energy_pct'],75);self.assertEqual(out['battery_soc_pct'],60)
        series['Virtual Energy']['unit']='MJ';self.assertIsNone(v.native_values(series,0,look)['virtual_energy_pct'])

    def test_csv_sidecar_retains_input_frames_and_final_sample(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            recorder=app.Recorder(Path(t)/'logs');s=sample(0)
            def original(s):return {**s,'vehicle':'Test Car','vehicle_data':s['vehicle'],'controls':[.7,.1,0,.6,.1,0],'speed':150}
            recorder.start(original(s))
            for i in range(1000):recorder.add(original(sample(i/100)))
            with patch.object(app.Recorder,'_report',staticmethod(lambda f:None)):folder=recorder.finish('test');recorder.report_thread.join()
            with (folder/'inputs.csv').open(encoding='utf-8',newline='') as f:inputs=list(csv.DictReader(f))
            with (folder/'vehicle.csv').open(encoding='utf-8',newline='') as f:extra=list(csv.DictReader(f))
            self.assertEqual(len(inputs),1000);self.assertEqual(len(extra),101)
            self.assertEqual(float(extra[-1]['session_time_s']),9.99)
            self.assertEqual(inputs[0]['throttle'],'0.700000');self.assertEqual(float(extra[10]['fuel_l']),49.8)
            bundle=v.load_recording(folder);self.assertEqual(bundle['time_origin_s'],0)
            checkpoint=json.loads((folder/'vehicle_checkpoint.json').read_text());self.assertTrue(checkpoint['closed']);self.assertEqual(checkpoint['rows'],101)

    def test_export_selected_keeps_tyre_data_and_all_original_bytes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=base_tests.Tests().lap_csv(Path(t)/'session');self.write_vehicle(folder)
            original={p:p.read_bytes() for p in folder.iterdir() if p.is_file()}
            result=laps.export_selected_laps(folder,[1,4],ROOT/'src/compare.html')
            records=[json.loads(Path(e['json']).read_text(encoding='utf-8')) for e in result['exports']]
            self.assertTrue(all(r['vehicle_telemetry']['data'] for r in records));self.assertIn('fl_inner_c',records[0]['vehicle_telemetry']['columns'])
            self.assertAlmostEqual(records[0]['vehicle_telemetry']['summary']['fuel_l_used']['value'],2.4)
            self.assertEqual({p:p.read_bytes() for p in original},original)
            self.assertIn('InputScopeVehicle',Path(result['comparison']).read_text(encoding='utf-8'))

    def test_auxiliary_writer_failure_closes_both_writers_and_rejects_analysis(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            recorder=app.Recorder(Path(t)/'logs');s=sample(0)
            original={**s,'vehicle':'Test Car','vehicle_data':s['vehicle'],'controls':[.7,.1,0,.6,.1,0],'speed':150}
            recorder.start(original)
            recorder.add(original)
            class Bad:
                def writerows(self,rows):raise OSError('injected auxiliary disk failure')
            recorder.vehicle_batch.csv=Bad()
            original.update(et=.2);recorder.add(original)
            input_writer,extra_writer=recorder.batch,recorder.vehicle_batch
            folder=recorder.finish('test')
            self.assertFalse(input_writer.thread.is_alive());self.assertFalse(extra_writer.thread.is_alive())
            meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['status'],'write_error');self.assertIn('auxiliary',meta['end_reason'])
            self.assertTrue((folder/'inputs.csv').exists());self.assertTrue((folder/'report_error.txt').exists())
            with self.assertRaisesRegex(ValueError,'写盘错误'):sessionlab.analyze_session(folder)

    def test_recovery_copies_only_auxiliary_committed_prefix_without_touching_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            root=Path(t);folder=root/'Logs'/'crash';folder.mkdir(parents=True)
            inputs=b'a,b\r\n1,2\r\n';extra=b'time_s,fuel_l\r\n0,40\r\n'
            (folder/'inputs.csv').write_bytes(inputs+b'partial');(folder/'vehicle.csv').write_bytes(extra+b'partial')
            storage.atomic_json(folder/'session.json',dict(status='recording'))
            cp=dict(version=1,pid=os.getpid(),rows=1,committed_bytes=len(inputs),closed=False,updated_utc='2026-10-04T00:00:00Z')
            storage.atomic_json(folder/'recording_checkpoint.json',cp)
            storage.atomic_json(folder/'vehicle_checkpoint.json',{**cp,'committed_bytes':len(extra)})
            before={p:p.read_bytes() for p in folder.iterdir()}
            with patch('storage.process_alive',return_value=False):out=storage.recover_session(folder,root)
            self.assertEqual((out/'inputs.csv').read_bytes(),inputs);self.assertEqual((out/'vehicle.csv').read_bytes(),extra)
            self.assertEqual(json.loads((out/'session.json').read_text())['vehicle_recovered_samples'],1)
            self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_normal_shutdown_waits_for_every_pending_export_before_destroying_tk(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            release=threading.Event();recorder=app.Recorder(Path(t)/'logs')
            def original(t):
                s=sample(t);return {**s,'vehicle':'Test Car','vehicle_data':s['vehicle'],'controls':[.7,.1,0,.6,.1,0],'speed':150}
            with patch.object(app.Recorder,'_report',staticmethod(lambda folder:release.wait(5))):
                for value in (0,1):
                    s=original(value);recorder.start(s);recorder.add(s);recorder.finish('test')
                self.assertEqual(len(recorder.pending_reports),2)
                gui=SimpleNamespace(root=Mock(),render_stop=threading.Event(),draw_job=None,render_waiter=Mock(),
                    engine=SimpleNamespace(stop=threading.Event(),thread=Mock(),recorder=recorder))
                gui.engine.thread.is_alive.return_value=False;gui.close=lambda:app.App.close(gui)
                try:
                    gui.close();gui.root.destroy.assert_not_called();gui.render_waiter.close.assert_not_called()
                    gui.root.after.assert_called_with(25,gui.close)
                finally:
                    release.set()
                    for worker in recorder.pending_reports:worker.join(2)
                gui.close();gui.root.destroy.assert_called_once();gui.render_waiter.close.assert_called_once()

    def test_legacy_optional_telemetry_is_not_fabricated(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=base_tests.Tests().lap_csv(Path(t)/'session',legacy=True);best=laps.extract_best(folder/'inputs.csv')[0]
            self.assertIsNone(v.load_recording(folder));self.assertIsNone(v.lap_telemetry(best))

    def test_summary_gaps_refuelling_and_boundaries_are_explicit(self):
        payload=dict(columns=['fuel_l'],data=[[0,10],[1,9],[4,8],[5,7]])
        summary=v.summarize(payload,0,5);self.assertTrue(summary['fuel_l_used']['gap']);self.assertIsNone(summary['fuel_l_used']['value'])
        payload['data']=[[0,10],[1,9],[2,12],[3,11]];summary=v.summarize(payload,0,3)
        self.assertTrue(summary['fuel_l_used']['reset']);self.assertIsNone(summary['fuel_l_used']['value'])

    def test_stable_reference_keeps_same_telemetry_as_selected_export(self):
        from tests.test_upgrades import clean_session
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=clean_session(Path(t)/'session');self.write_vehicle(folder)
            analysis=sessionlab.analyze_session(folder);record=json.loads((folder/analysis['stable_reference_file']).read_text(encoding='utf-8'))
            self.assertEqual(record['reference_kind'],'stable');self.assertIn('vehicle_telemetry',record)
            self.assertIn('vehicle_summary',analysis['laps'][0])

    @staticmethod
    def write_vehicle(folder):
        with (folder/'vehicle.csv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(v.COLUMNS)
            for i in range(601):
                s=sample(i/10);writer.writerow(v.sample_row(s,0))


if __name__=='__main__':unittest.main(verbosity=2)
