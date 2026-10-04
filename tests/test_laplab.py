"""Native LMU table fixtures and reference correctness/integrity checks."""
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from reference import ReferenceLap
import telemetry_import as native
import laps
import inputscope


def fixture(path,explicit=False,missing=False):
    db=native.driver(ROOT).connect(str(path))
    db.execute('BEGIN TRANSACTION')
    db.execute('CREATE TABLE metadata(key VARCHAR,value VARCHAR)')
    db.executemany('INSERT INTO metadata VALUES (?,?)', [('TrackName','Native Test Circuit'),('CarName','Test GT3'),
        ('DriverName','Test Driver'),('TrackLength','2000'),('RecordingTime','2026-10-03T12:00:00Z'),('CarSetup','{"Fuel":20}')])
    db.execute('CREATE TABLE channelsList(channelName VARCHAR,frequency DOUBLE,unit VARCHAR)')
    db.execute('CREATE TABLE eventsList(eventName VARCHAR,unit VARCHAR)')
    names={n:(50,'%' if 'Steering' not in n else 'ratio') for n in native.CONTROLS.values()}
    names.update({'Lap Dist':(10,'m'),'Ground Speed':(50,'m/s'),'Fuel Level':(5,'L'),
                  'GPS Latitude':(10,'deg'),'GPS Longitude':(10,'deg'),'Tyres Wear':(5,'%')})
    if missing:names.pop('Throttle Pos Unfiltered')
    for name,(hz,unit) in names.items():
        db.execute('INSERT INTO channelsList VALUES (?,?,?)',[name,hz,unit])
        ncols=4 if name=='Tyres Wear' else 1
        cols=['value'+str(i+1) for i in range(4)] if ncols==4 else ['value']
        db.execute('CREATE TABLE '+native.quote(name)+' ('+('ts DOUBLE,' if explicit else '')+','.join(c+' DOUBLE' for c in cols)+')')
        rows=[]
        for i in range(70*hz+1):
            t=i/hz;p=(t%20)/20
            if name=='Lap Dist':v=p*2000
            elif name=='Ground Speed':v=40+5*math.cos(p*math.tau)
            elif name=='Fuel Level':v=25-t*.05
            elif name=='GPS Latitude':v=45+.002*math.sin(p*math.tau)
            elif name=='GPS Longitude':v=-110+.003*math.cos(p*math.tau)
            elif name=='Tyres Wear':v=95-t*.01
            elif 'Steering' in name:v=math.sin(p*math.tau)*.5
            elif 'Brake' in name:v=80 if .15<p<.3 else 0
            else:v=100 if p<.15 or p>.32 else 5
            rows.append(([t] if explicit else [])+[v+k*.1 for k in range(ncols)])
        db.executemany('INSERT INTO '+native.quote(name)+' VALUES ('+','.join('?' for _ in rows[0])+')',rows)
    for name,values in {'Lap':[(0,1),(20,2),(40,3),(60,4)],'ABS':[(0,0),(5,1),(6,0)],'In Pits':[(0,0)]}.items():
        db.execute('INSERT INTO eventsList VALUES (?,?)',[name,''])
        db.execute('CREATE TABLE '+native.quote(name)+' (ts DOUBLE,value DOUBLE)')
        db.executemany('INSERT INTO '+native.quote(name)+' VALUES (?,?)',[(t+(0 if explicit else 100),v) for t,v in values])
    db.execute('COMMIT')
    db.close()


class UpgradeTests(unittest.TestCase):
    def test_reference_distance_lookup_channels_delta_and_guards(self):
        v=dict(format='inputscope.fastest-lap',version=1,session={'track':'Test','vehicle':'GT3'},
            lap={'track_length_m':1000,'time_s':20,'number':2},data=[[0,0,0,1,.1,.9,100],[500,10,1,0,.8,.2,120],[1000,20,0,1,.1,.9,100]])
        ref=ReferenceLap(v);r=ref.at(250)
        for actual,expected in zip(r,(250,5,.5,.5,.45,.55,110)):self.assertAlmostEqual(actual,expected)
        sample=dict(track='Test',vehicle='GT3',track_length=1000,distance=250,et=106,lap_start=100)
        self.assertEqual(ref.sample(sample)[-1],1)
        for actual,expected in zip(ref.sample(sample)[:4],(.5,.5,.45,.55)):self.assertAlmostEqual(actual,expected)
        for bad in ({'track':'Other'},{'vehicle':'Other'},{'track_length':2000},{'distance':-1},{'in_pits':True},{'lap_invalidated':True},{'finish':1},{'et':99}):
            self.assertIsNone(ref.sample(dict(sample,**bad)))
        self.assertIsNone(ref.at(float('nan')))
        broken=json.loads(json.dumps(v));broken['data'][1][1]=0
        with self.assertRaises(ValueError):ReferenceLap(broken)

    def test_native_implicit_and_explicit_time_mixed_rates_preserve_source(self):
        for explicit in (False,True):
            with self.subTest(explicit=explicit),tempfile.TemporaryDirectory(dir=ROOT) as temp:
                directory=Path(temp);source=directory/'native.duckdb';fixture(source,explicit)
                sha=native.fingerprint(source);stamp=source.stat().st_mtime_ns
                # Dependency is kept local; output goes in an isolated plugin test root.
                from unittest.mock import patch
                with patch.object(native,'driver',lambda _: __import__('_duckdb')):
                    output=native.import_recording(source,directory)
                self.assertEqual(native.fingerprint(source),sha)
                self.assertEqual(source.stat().st_mtime_ns,stamp)
                self.assertFalse(source.with_suffix('.duckdb.wal').exists())
                meta=json.loads((output/'session.json').read_text(encoding='utf8'))
                self.assertEqual(meta['native_source']['event_offset_s'],0 if explicit else 100)
                self.assertEqual(meta['position_source'],'gps_mercator_m')
                with (output/'inputs.csv').open(encoding='utf8') as f:rows=list(csv.DictReader(f))
                self.assertEqual(len(rows),3501)
                self.assertTrue(all(r['lap_invalidated']=='' for r in rows))
                self.assertAlmostEqual(float(rows[0]['speed_kmh']),162)
                self.assertEqual(float(rows[0]['throttle']),1)
                self.assertEqual(float(rows[1000]['lap_distance_m']),0)
                self.assertEqual(int(rows[1000]['lap']),2)
                self.assertGreater(abs(float(rows[0]['world_x_m'])),1e7)
                fastest,summary=laps.export_fastest(output,ROOT/'src'/'compare.html')
                self.assertEqual(summary['status'],'saved')
                self.assertAlmostEqual(fastest['lap']['time_s'],20)
                self.assertEqual(fastest['lap']['validity'],'unverified_legacy')
                self.assertEqual(fastest['trajectory']['source'],'gps_mercator_m')
                self.assertIn('ABS',fastest['native_context']['channels'])
                self.assertEqual(len(fastest['native_context']['channels']['Tyres Wear']['data'][0]),5)
                inputscope.render_review(output,summary)
                self.assertIn('Fuel Level',(output/'review.html').read_text(encoding='utf8'))

    def test_native_missing_raw_rejected_without_fake_samples(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            folder=Path(temp);source=folder/'missing.duckdb';fixture(source,missing=True);sha=native.fingerprint(source)
            with self.assertRaisesRegex(ValueError,'Throttle Pos Unfiltered'):native.import_recording(source,ROOT)
            self.assertEqual(native.fingerprint(source),sha)

    def test_native_lookup_does_not_cross_gaps_or_lap_resets(self):
        s=dict(data=[[0,1950],[.1,0],[.2,10]],times=[0,.1,.2],frequency_hz=10,event=False,distance=True)
        self.assertEqual(native.lookup(s,.05),[1950])
        self.assertAlmostEqual(native.lookup(s,.15)[0],5)
        s=dict(data=[[0,0],[2,1]],times=[0,2],frequency_hz=50,event=False)
        self.assertIsNone(native.lookup(s,1))
        s['event']=True
        self.assertEqual(native.lookup(s,1),[0])


if __name__=='__main__':unittest.main(verbosity=2)
