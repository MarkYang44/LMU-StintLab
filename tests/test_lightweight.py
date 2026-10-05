"""Lossless buffers, standalone payloads and quoted CSV under writer backpressure."""
import base64,csv,gzip,json,math,re,struct,sys,tempfile,unittest
from collections import deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import buffers,inputscope,reporting,storage,vehiclelab
from tests import test_core as fixtures

def block(path,identifier):
    html=Path(path).read_text(encoding='utf-8')
    match=re.search(r'id="'+identifier+r'" data-bytes="(\d+)">([^<]*)</script>',html)
    value=gzip.decompress(base64.b64decode(match[2]));assert len(value)==int(match[1])
    return value

class LightweightTests(unittest.TestCase):
    def test_numeric_ring_matches_deque_across_growth_wrap_and_replace(self):
        ring=buffers.NumericRing(3,137);expected=deque(maxlen=137)
        for i in range(1500):
            row=(i/4000,math.sin(i),i*.001);ring.append(row);expected.append(row)
            if i%13==0:ring[-1]=row;expected[-1]=row
            if i%7==0:self.assertEqual(ring.popleft(),expected.popleft())
            if i%31==0 and expected:self.assertEqual(ring.pop(),expected.pop())
            self.assertEqual(tuple(ring),tuple(expected))
        ring.clear();self.assertEqual(len(ring._data),0);self.assertFalse(ring)

    def test_high_rate_history_keeps_every_sample_both_channels_and_single_frame_spike(self):
        engine=object.__new__(inputscope.Engine);engine.points=buffers.ControlHistory();engine.plot_points=buffers.NumericRing(19,80001)
        engine.plot_hz=237;engine.plot_y_scale=408;engine.plot_revision=0
        for i in range(80000):engine.add_plot_point(i/4000,[.25,1 if i==39999 else 0,-.123,.75,.5 if i==40000 else 0,.234])
        self.assertEqual(len(engine.points),80000);self.assertEqual(engine.points[39999][2],1)
        self.assertEqual(engine.points[40000][11],.5)
        self.assertTrue(any(r[8]==1 for r in engine.plot_points));self.assertTrue(any(r[17]==.5 for r in engine.plot_points))
        self.assertLess(len(engine.points._data)*8,5_000_000)
        engine.add_plot_point(21,[0]*6);self.assertTrue(all(21-r[0]<=20 for r in engine.points))

    def test_streamed_review_preserves_every_full_precision_sample_and_missing_coordinates(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            folder=fixtures.Tests().lap_csv(Path(t)/'session');before={p:p.read_bytes() for p in folder.iterdir() if p.is_file()}
            inputscope.render_review(folder)
            actual=block(folder/'review.html','stintrix-inputs');expected=b''.join(reporting.review_records(folder/'inputs.csv'))
            self.assertEqual(actual,expected);self.assertEqual(len(actual)%104,0)
            with (folder/'inputs.csv').open(newline='',encoding='utf-8') as f:
                source=list(csv.DictReader(f))
            self.assertEqual(len(actual)//104,len(source));values=struct.unpack('<13d',actual[:104])
            columns=['time_s','lap','lap_distance_m','throttle','brake','steering','filtered_throttle','filtered_brake','filtered_steering','speed_kmh','world_x_m','world_z_m','track_length_m']
            for numeric,text in zip(struct.iter_unpack('<13d',actual),source):
                for i,key in enumerate(columns):
                    if text.get(key) not in ('',None):self.assertEqual(numeric[i],float(text[key]))
                    elif i>=10:self.assertTrue(math.isnan(numeric[i]))
            self.assertEqual(values[3],float(source[0]['throttle']));self.assertEqual(values[6],float(source[0]['filtered_throttle']))
            self.assertEqual(json.loads(block(folder/'review.html','stintrix-meta'))['meta'],json.loads((folder/'session.json').read_text()))
            self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_streaming_sidecar_matches_loaded_vehicle_bundle_and_absent_values(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            f=Path(t);meta=dict(source='test',vehicle_profile={'alerts':False});storage.atomic_json(f/'session.json',meta)
            with (f/'vehicle.csv').open('w',newline='',encoding='utf-8') as out:
                w=csv.DictWriter(out,fieldnames=vehiclelab.COLUMNS);w.writeheader()
                for i in range(51):w.writerow(dict(time_s=i/10,session_time_s=100+i/10,fuel_l=20-i/50,lap=1))
            streamed=json.loads(b''.join(reporting.VehicleJSON(f,meta).chunks()))
            loaded=vehiclelab.load_recording(f);loaded['data']=[list(r) for r in loaded['data']]
            self.assertEqual(streamed,loaded)
            self.assertEqual(vehiclelab.summarize(streamed,100,105)['fuel_l_used']['value'],1)

    def test_packed_queue_preserves_quoted_newlines_unicode_and_writer_counts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            w=storage.BatchWriter(t,['index','text']);rows=[[i,'逗号, 双引号"\r\n第二行 '+str(i)] for i in range(3000)]
            for row in rows:w.add(row)
            self.assertEqual(w.finish()['written_rows'],len(rows))
            with (Path(t)/'inputs.csv').open(encoding='utf-8',newline='') as f:actual=list(csv.reader(f))[1:]
            self.assertEqual(actual,[[str(i),s] for i,s in rows])

    def test_reference_matrix_preserves_exact_double_values(self):
        rows=[[i*.012345678901234,j+.123456789012345] for i,j in enumerate(range(1000))]
        table=buffers.NumericTable(rows,2);self.assertEqual([list(r) for r in table],rows)
        nullable=buffers.NullableTable([[0,None],[.1,.123456789012345]],2)
        self.assertEqual(list(nullable),[(0,None),(.1,.123456789012345)])

if __name__=='__main__':unittest.main()
