"""Boundary/gap integrity, pit service, stint windows, weather and full exports."""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import endurance as e,vehiclelab as v,inputscope as app,laps
from tests.test_core import fixture

def sample(t,inside=False,speed=150,fuel=40,**changes):
    values=dict(speed_kmh=speed,fuel_l=fuel,virtual_energy_pct=80,track_length_m=1000,
        pit_state=3 if inside and speed<1 else 2 if inside else 0,speed_limiter=int(inside),
        rain_severity=0,wetness=0,track_temp_c=30,ambient_temp_c=20,tyre_front_index=0,tyre_rear_index=0)
    s=dict(et=t,track='T',vehicle_name='C',session=10,player_id=1,lap=int(t//10)+1,
        lap_start=int(t//10)*10,distance=(t%10)*100,in_pits=inside,lap_invalidated=False,vehicle=values)
    s.update(changes);return s

def write_fixture(folder):
    folder.mkdir(parents=True,exist_ok=True);durations=[10,10,10,14]+[10]*17
    starts=[0]
    for d in durations:starts.append(starts[-1]+d)
    rows=[];extra=[]
    for i in range(int(starts[-1]*20)+1):
        t=i/20;j=max(0,next((j for j,b in enumerate(starts[1:]) if t<b),len(starts)-1))
        if j==len(durations):start=starts[-1];duration=10
        else:start=starts[j];duration=durations[j]
        distance=(t-start)/duration*1000;inside=33<=t<39 or 124<=t<130
        still=34<=t<38 or 125<=t<129;fuel=50-.03*t+max(0,min(12,(t-34)*3))+max(0,min(6,(t-125)*1.5))
        vehicle=v.demo_vehicle(t);vehicle.update(speed_kmh=0 if still else 75 if inside else 150,
            pit_state=3 if still else 2 if inside else 0,speed_limiter=int(inside),fuel_l=fuel,
            track_length_m=1000,virtual_energy_pct=70+max(0,min(20,(t-34)*5)),
            rain_severity=max(0,min(1,(t-140)/100)),wetness=max(0,min(1,(t-150)/150)),
            track_temp_c=30-t*.002,ambient_temp_c=22,tyre_front_index=0,tyre_rear_index=0)
        r=dict(time_s=t,session_time_s=500+t,utc='',lap=j+1,lap_distance_m=distance,
            throttle=max(0,math.sin(t)),brake=max(0,-math.sin(t)),steering=math.sin(t*.5)*.5,
            filtered_throttle=max(0,math.sin(t))*.95,filtered_brake=max(0,-math.sin(t))*.95,filtered_steering=math.sin(t*.5)*.45,
            speed_kmh=vehicle['speed_kmh'],lap_start_s=500+start,lap_invalidated=0,in_pits=int(inside),track_length_m=1000,
            world_x_m=200*math.cos(distance/1000*math.tau),world_y_m=0,world_z_m=100*math.sin(distance/1000*math.tau),
            fuel_l=fuel,tyre_compound=0,track_temp_c=vehicle['track_temp_c'],wetness=vehicle['wetness'],gear=4)
        rows.append(r)
        if i%2==0:extra.append(v.sample_row(dict(et=500+t,lap=j+1,distance=distance,lap_start=500+start,lap_invalidated=False,in_pits=inside,vehicle=vehicle),500))
    with (folder/'inputs.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=app.COLUMNS);w.writeheader();w.writerows(rows)
    with (folder/'vehicle.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(v.COLUMNS);w.writerows(extra)
    meta=dict(status='finished',track='Test Track',driver='D',vehicle='Synthetic',session=10,player_id=1,
        source='Synthetic endurance verification',started_utc='2026-10-04T10:00:00Z',end_reason='fixture',
        endurance_settings=e.settings(dict(pit_limit_kmh=60)),vehicle_telemetry=dict(target_hz=10))
    (folder/'session.json').write_text(json.dumps(meta),encoding='utf-8');app.make_report(folder)
    return folder

class EnduranceTests(unittest.TestCase):
    def test_preferences_validate_and_default_panels_off(self):
        self.assertTrue(all(not e.settings()[k+'_enabled'] for k in ('pit','stint','weather')))
        for value in ({'pit_limit_kmh':-1},{'pace_window':1},{'warmup_laps':1.5},{'rain_change':0},{'alert_cooldown_s':1}):
            with self.assertRaises(ValueError):e.settings(value)

    def test_sdk_exact_pit_weather_fields_and_units(self):
        d=fixture();p=d.scoring.vehScoringInfo[1];info=d.scoring.scoringInfo;car=d.telemetry.telemInfo[0]
        p.mPitState=3;p.mInPits=True;p.mNumPitstops=2;car.mSpeedLimiter=1;info.mRaining=.25;info.mAvgPathWetness=.4
        info.mAmbientTemp=22;info.mTrackTemp=31;info.mWind.x=2;info.mWind.z=-4
        result=app.extract(d)['vehicle_data'];self.assertEqual(result['pit_state'],3);self.assertEqual(result['speed_limiter'],1)
        self.assertEqual(result['rain_severity'],.25);self.assertAlmostEqual(result['wetness'],.4)
        self.assertEqual(result['ambient_temp_c'],22);self.assertEqual(result['track_temp_c'],31);self.assertEqual(result['wind_z_raw'],-4)

    def test_full_pit_duration_stationary_refuel_and_speed_warning(self):
        m=e.Monitor({'pit_limit_kmh':60})
        for i in range(61):
            t=i/10;inside=1<=t<5;still=2<=t<4;fuel=40+max(0,min(10,(t-2)*5))
            m.update(sample(t,inside,0 if still else 70 if inside else 150,fuel),force=True)
            if t==1:self.assertTrue(m.snapshot()['pit_warning'])
        p=m.pits[0];self.assertAlmostEqual(p['duration_s'],4);self.assertAlmostEqual(p['stationary_s'],1.9)
        self.assertAlmostEqual(p['fuel_added_l'],10);self.assertGreater(p['overspeed_s'],1.8);self.assertEqual(p['stops'],1)
        self.assertEqual(m.current_stint,2)

    def test_first_frame_inside_pit_is_explicitly_partial(self):
        m=e.Monitor();m.update(sample(2,True,0));m.update(sample(2.1,True,0,fuel=41));m.update(sample(3,False))
        p=m.pits[0];self.assertTrue(p['partial_start']);self.assertIsNone(p['duration_s']);self.assertIsNone(p['fuel_added_l'])

    def test_gap_makes_totals_unavailable_and_resets_weather_trend(self):
        m=e.Monitor();m.update(sample(0));m.update(sample(1,True));m.update(sample(5,True,0,fuel=50));m.update(sample(6))
        p=m.pits[0];self.assertTrue(p['gap']);self.assertIsNone(p['duration_s']);self.assertIsNone(p['stationary_s']);self.assertIsNone(p['fuel_added_l'])
        self.assertLessEqual(m.snapshot()['trend_span_s'],1)

    def test_unknown_sensors_never_become_zero_service(self):
        m=e.Monitor();m.update(sample(0));a=sample(1,True);a['vehicle'].update(speed_kmh=None,fuel_l=None,virtual_energy_pct=None)
        m.update(a);m.update(sample(2));p=m.pits[0]
        self.assertIsNone(p['stationary_s']);self.assertIsNone(p['fuel_added_l']);self.assertIsNone(p['energy_added_pct'])
        row=v.sample_row(dict(et=1,lap=1,distance=0,vehicle={}),0);self.assertIsNone(row[v.COLUMNS.index('in_pits')])

    def test_duplicate_frames_and_session_reset(self):
        m=e.Monitor();s=sample(0);m.update(s);m.update(s);self.assertEqual(len(m.weather),1)
        m.update(sample(1,True));m.update(sample(2));self.assertEqual(len(m.pits),1)
        m.update(sample(0));self.assertFalse(m.pits);self.assertEqual(m.current_stint,1)

    def test_pace_windows_do_not_overlap_or_claim_causality(self):
        cfg=e.settings({'warmup_laps':1,'pace_window':2});records=[dict(number=i,time_s=100+i,context={}) for i in range(5)]
        self.assertIsNone(e.pace(records[:4],cfg)['drift_s']);p=e.pace(records,cfg);self.assertEqual(p['drift_s'],2)
        records[-1]['context']={'wetness':.5};records[-2]['context']={'wetness':0};self.assertTrue(e.pace(records,cfg)['conditions_changed'])

    def test_weather_threshold_cooldown_and_missing_values(self):
        m=e.Monitor({'rain_change':.1,'alert_cooldown_s':10})
        for i in range(31):
            s=sample(i);s['vehicle']['rain_severity']=i/30;m.update(s,force=True)
        a=[a for a in m.alerts if a['field']=='rain_severity'];self.assertGreaterEqual(len(a),2)
        self.assertTrue(all(y['time_s']-x['time_s']>=10 for x,y in zip(a,a[1:])))
        self.assertTrue(all(x['field']=='rain_severity' for x in m.alerts))

    def test_live_history_is_bounded_and_skips_excess_poll_frames(self):
        m=e.Monitor()
        for i in range(8001):m.update(sample(i/1000))
        self.assertLess(len(m.weather),20);self.assertLessEqual(len(m.laps),2000)

    def test_weather_begins_missing_then_acquires_an_anchor(self):
        m=e.Monitor();s=sample(0);s['vehicle']['rain_severity']=None;m.update(s)
        s=sample(1);s['vehicle']['rain_severity']=.2;m.update(s)
        s=sample(2);s['vehicle']['rain_severity']=.4;m.update(s)
        self.assertEqual(m.alerts[-1]['field'],'rain_severity');self.assertEqual(m.alerts[-1]['from_value'],.2)

    def test_out_of_order_sidecar_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=Path(t);(folder/'session.json').write_text('{"status":"complete"}')
            (folder/'vehicle.csv').write_text('session_time_s,time_s,pit_state\n2,0,0\n1,1,0\n')
            with self.assertRaisesRegex(ValueError,'递增'):e.analyze(folder)

    def test_stint_context_uses_converted_sidecar_not_raw_native_units(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=Path(t);(folder/'session.json').write_text('{"status":"complete"}')
            (folder/'session_analysis.json').write_text(json.dumps({'laps':[dict(number=1,time_s=10,start_time_s=0,end_time_s=10,conditions=dict(track_temp_c=303.15))]}))
            (folder/'vehicle.csv').write_text('session_time_s,time_s,track_temp_c\n500,0,30\n501,1,30\n')
            result=e.analyze(folder);self.assertEqual(result['stints'][0]['laps'],[])
            # Extend the sidecar duration so the already-qualified full lap is enclosed.
            with (folder/'vehicle.csv').open('a') as f:
                for i in range(2,11):f.write(f'{500+i},{i},30\n')
            result=e.analyze(folder);self.assertEqual(result['stints'][0]['laps'][0]['context']['track_temp_c'],30)

    def test_native_weather_conversion_requires_declared_units(self):
        series={'Track Temperature':dict(unit='K',event=False),'Average Path Wetness':dict(unit='%',event=False),'Rain Severity':dict(unit='mm/h',event=False)}
        data={'Track Temperature':[303.15],'Average Path Wetness':[20],'Rain Severity':[3]}
        def lookup(s,t,offset):return next(data[k] for k in series if series[k] is s)
        values=v.native_values(series,1,lookup);self.assertAlmostEqual(values['track_temp_c'],30);self.assertEqual(values['wetness'],.2);self.assertIsNone(values['rain_severity'])

    def test_offline_exports_stints_pit_loss_and_immutable_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=write_fixture(Path(t)/'session');p=json.loads((folder/'endurance_analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(len(p['pits']),2);self.assertEqual(len(p['stints']),3)
            first=p['pits'][0];self.assertAlmostEqual(first['duration_s'],6);self.assertAlmostEqual(first['fuel_added_l'],11.88,places=2)
            self.assertAlmostEqual(first['estimated_loss_s'],4);self.assertGreaterEqual(len(first['baseline_laps']),3)
            self.assertTrue(p['weather_alerts']);self.assertGreaterEqual(p['stints'][1]['pace']['count'],6)
            original={x:hashlib.sha256(x.read_bytes()).hexdigest() for x in (folder/'inputs.csv',folder/'vehicle.csv',folder/'session.json')}
            result=laps.export_selected_laps(folder,[1,8],ROOT/'src/compare.html');record=json.loads(Path(result['exports'][0]['json']).read_text(encoding='utf-8'))
            self.assertIn('rain_severity',record['vehicle_telemetry']['columns']);self.assertIn('InputScopeEndurance',(folder/'review.html').read_text(encoding='utf-8'))
            self.assertEqual({x:hashlib.sha256(x.read_bytes()).hexdigest() for x in original},original)

    def test_legacy_missing_and_write_error_records(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=Path(t);(folder/'session.json').write_text('{"status":"finished"}')
            self.assertFalse(e.analyze(folder)['available']);(folder/'session.json').write_text('{"status":"write_error"}')
            with self.assertRaises(ValueError):e.analyze(folder)

    def test_recording_preserves_extra_pit_transitions_between_rate_ticks(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=ROOT) as t,patch.object(app.Recorder,'_report',staticmethod(lambda folder:None)):
            rec=app.Recorder(Path(t),{'record_hz':1});s=sample(0)
            def convert(s):return {**s,'vehicle':'C','vehicle_data':s['vehicle'],'driver':'D','controls':[.5,0,0,.5,0,0],'speed':150,'finish':0,'track_length':1000}
            rec.start(convert(s));rec.add(convert(s));rec.add(convert(sample(.02,True)));rec.add(convert(sample(.04,False)))
            folder=rec.finish('test');rec.report_thread.join(1)
            with (folder/'vehicle.csv').open() as f:rows=list(csv.DictReader(f))
            self.assertEqual([int(r['in_pits']) for r in rows],[0,1,0])

if __name__=='__main__':unittest.main()
