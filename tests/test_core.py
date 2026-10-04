import csv
import ctypes
import json
import mmap
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import inputscope as app
import laps as lap_export
from pyLMUSharedMemory.lmu_data import LMUObjectOut


def fixture(et=10, finish=0):
    data = LMUObjectOut()
    info = data.scoring.scoringInfo
    info.mTrackName = b'Test Track'
    info.mSession = 10
    info.mNumVehicles = 2
    info.mInRealtime = True
    data.scoring.vehScoringInfo[0].mID = 1
    player = data.scoring.vehScoringInfo[1]
    player.mID = 42
    player.mIsPlayer = True
    player.mDriverName = b'Test Driver'
    player.mLapDist = 123.4
    player.mFinishStatus = finish
    telem = data.telemetry
    telem.activeVehicles = 2
    telem.playerHasVehicle = True
    telem.telemInfo[0].mID = 42
    telem.telemInfo[1].mID = 1
    car = telem.telemInfo[0]
    car.mVehicleModel = b'Test Car'
    car.mElapsedTime = et
    car.mLapNumber = 3
    car.mUnfilteredThrottle = 0.7
    car.mUnfilteredBrake = 0.2
    car.mUnfilteredSteering = -0.4
    car.mFilteredThrottle = 0.6
    car.mFilteredBrake = 0.1
    car.mFilteredSteering = -0.3
    car.mLocalVel.z = 10
    car.mPos.x,car.mPos.y,car.mPos.z = 123.45,5.6,-789.01
    return data


class Tests(unittest.TestCase):
    def lap_csv(self,folder,legacy=False,gap=False,all_invalid=False):
        folder = Path(folder)
        folder.mkdir(parents=True,exist_ok=True)
        metadata = dict(track='Test Track',vehicle='BMW M4 LMGT3',driver='Test driver',
                        session=10,started_utc='2026-10-03T10:00:00+00:00',
                        ended_utc='2026-10-03T10:02:00+00:00',source='test',status='complete',
                        end_reason='finish flag 1')
        (folder/'session.json').write_text(json.dumps(metadata),encoding='utf-8')
        fields = list(app.COLUMNS[:app.COLUMNS.index('lap_start_s')] if legacy else app.COLUMNS)
        with (folder/'inputs.csv').open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader()
            for n,(start,duration) in enumerate(((0,10),(10,12),(22,8),(30,9),(39,11),(50,10))):
                for i in range(int(duration*10)):
                    t = i/10
                    if n==0 and t<5 or n==5 and t>1:
                        continue
                    if gap and n in (1,4) and 3<t<6:
                        continue
                    row = dict(time_s=start+t,utc='2026-10-03T10:00:00Z',
                               session_time_s=start+t,lap=n,lap_distance_m=t/duration*1000,
                               throttle=.7,brake=.2,steering=0,filtered_throttle=.6,
                               filtered_brake=.1,filtered_steering=0,speed_kmh=150)
                    if not legacy:
                        row.update(lap_start_s=start,lap_invalidated=int(all_invalid or n==2),
                                   in_pits=int(n==3),track_length_m=1000,
                                   world_x_m=200*math.cos(t/duration*math.tau),world_y_m=5,
                                   world_z_m=120*math.sin(t/duration*math.tau))
                    writer.writerow(row)
        return folder

    def test_fastest_lap_excludes_partial_invalid_pit_and_gapped_laps(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            folder = self.lap_csv(Path(temp)/'session')
            result,summary = lap_export.export_fastest(folder,app.ASSETS/'compare.html')
            self.assertEqual(result['lap']['number'],4)
            self.assertEqual(result['lap']['time_s'],11)
            self.assertEqual(result['lap']['validity'],'verified')
            self.assertEqual(result['session']['vehicle'],'BMW M4 LMGT3')
            self.assertEqual(result['session']['track'],'Test Track')
            self.assertEqual(result['data'][0][:2],[0,0])
            self.assertEqual(result['data'][-1][:2],[1000,11])
            trajectory = result['trajectory']
            self.assertEqual(trajectory['columns'],['lap_time_s','distance_m','world_x_m','world_z_m'])
            self.assertEqual(trajectory['points'][0],[0,0,200,0])
            self.assertEqual(trajectory['points'][-1],[11,1000,200,0])
            self.assertTrue(all(b[0]>a[0] for a,b in zip(trajectory['points'],trajectory['points'][1:])))
            reasons = {v['number']:v.get('exclusion') for v in summary['candidates']}
            self.assertEqual(reasons[0],'start of lap missing')
            self.assertEqual(reasons[2],'invalidated lap')
            self.assertEqual(reasons[3],'pit lane lap')
            self.assertEqual(reasons[5],'end of lap missing')
            with (folder/'fastest_lap.csv').open(encoding='utf-8') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows),110)
            self.assertTrue(all(int(float(r['lap']))==4 for r in rows))
            self.assertEqual(rows[0]['track'],'Test Track')
            self.assertEqual(rows[0]['vehicle'],'BMW M4 LMGT3')
            self.assertTrue((folder/summary['file']).exists())
            self.assertIn('Lap_4_BMW M4 LMGT3_Test Track',summary['file'])
            self.assertTrue((folder/'fastest_lap.svg').read_text(encoding='utf-8').startswith('<svg'))
            self.assertTrue((folder/'fastest_lap.html').is_file())
            gapped = self.lap_csv(Path(temp)/'gapped',gap=True)
            best,candidates,_ = lap_export.extract_best(gapped/'inputs.csv')
            self.assertIsNone(best)
            self.assertTrue(any(v.get('exclusion')=='telemetry gap' for v in candidates))
            invalid = self.lap_csv(Path(temp)/'invalid',all_invalid=True)
            result,summary = lap_export.export_fastest(invalid,app.ASSETS/'compare.html')
            self.assertIsNone(result)
            self.assertEqual(summary['status'],'no_complete_lap')
            self.assertFalse((invalid/'fastest_lap.csv').exists())

    def test_legacy_fastest_lap_marks_unknown_validity_and_escapes_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            folder = self.lap_csv(Path(temp)/'legacy',legacy=True)
            meta = json.loads((folder/'session.json').read_text())
            meta['driver'] = '</script><script>danger()</script>'
            (folder/'session.json').write_text(json.dumps(meta))
            result,summary = lap_export.export_fastest(folder,app.ASSETS/'compare.html')
            self.assertEqual(result['lap']['number'],2)
            self.assertEqual(result['lap']['validity'],'unverified_legacy')
            self.assertEqual(result['lap']['timing_source'],'lap_counter_estimate')
            self.assertEqual(result['lap']['distance_source'],'recorded_maximum_estimate')
            self.assertIsNone(result['trajectory'])
            self.assertNotIn('</script><script>danger()', (folder/'fastest_lap.html').read_text(encoding='utf-8'))
            self.assertIn('&lt;/script&gt;', (folder/'fastest_lap.svg').read_text(encoding='utf-8'))
            with (folder/'inputs.csv').open(encoding='utf-8') as stream:
                self.assertEqual(list(csv.DictReader(stream))[0]['lap'],'0')

    def test_fastest_library_uses_only_compatible_previous_session(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            first = self.lap_csv(Path(temp)/'first')
            one,_ = lap_export.export_fastest(first,app.ASSETS/'compare.html')
            second = self.lap_csv(Path(temp)/'second')
            two,_ = lap_export.export_fastest(second,app.ASSETS/'compare.html')
            third = self.lap_csv(Path(temp)/'third')
            meta = json.loads((third/'session.json').read_text())
            meta.update(vehicle='Different car',started_utc='2026-10-03T11:00:00+00:00')
            (third/'session.json').write_text(json.dumps(meta))
            other,_ = lap_export.export_fastest(third,app.ASSETS/'compare.html')
            self.assertEqual([v['id'] for v in lap_export.library_laps(temp,two)],[two['id'],one['id']])
            self.assertEqual([v['id'] for v in lap_export.library_laps(temp)],[other['id']])

    def test_recorder_finish_automatically_exports_fastest_lap(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            source = self.lap_csv(Path(temp)/'source')
            recorder = app.Recorder(Path(temp)/'output')
            for row in lap_export.read_rows(source/'inputs.csv'):
                sample = dict(track='Test Track',vehicle='BMW M4 LMGT3',driver='Test driver',
                              session=10,player_id=42,et=row['session_time_s'],lap=int(row['lap']),
                              distance=row['lap_distance_m'],speed=row['speed_kmh'],finish=0,
                              controls=[row['throttle'],row['brake'],0,row['filtered_throttle'],row['filtered_brake'],0],
                              lap_start=row['lap_start_s'],lap_invalidated=bool(row['lap_invalidated']),
                              in_pits=bool(row['in_pits']),track_length=row['track_length_m'])
                if recorder.file is None:
                    recorder.start(sample)
                recorder.add(sample)
            folder = recorder.finish('finish flag 1')
            recorder.report_thread.join(5)
            self.assertFalse(recorder.report_thread.is_alive())
            self.assertFalse((folder/'fastest_lap_error.txt').exists())
            self.assertFalse((folder/'report_error.txt').exists())
            summary = json.loads((folder/'fastest_lap_summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['status'],'saved')
            self.assertEqual(summary['lap']['number'],4)
            self.assertIn('fastest_lap.html',(folder/'review.html').read_text(encoding='utf-8'))

    def test_control_layout_fits_all_sizes_and_clean_mode_keeps_full_chart(self):
        for w,h in ((440,170),(640,228),(840,300)):
            layout = app.hud_layout(w,h)
            px0,py0,px1,py1 = layout['panel']
            x0,x1,y0,y1 = layout['plot']
            self.assertLess(x1,px0)
            self.assertGreater(x1,x0)
            self.assertGreater(y1,y0)
            for a,b,c,d in layout['pedals']:
                self.assertTrue(px0<a<c<px1 and py0<b<d<py1)
            cx,cy,radius = layout['wheel']
            self.assertTrue(px0<cx-radius<cx+radius<px1)
            self.assertTrue(py0<cy-radius<cy+radius<py1)
            clean = app.hud_layout(w,h,True)
            self.assertIsNone(clean['panel'])
            self.assertEqual(clean['plot'],(2,w-2,2,h-2))

    def test_clean_controls_layout_and_switches_preserve_normal_window(self):
        for w,h in ((320,80),(600,100),(640,228),(840,300)):
            layout = app.hud_layout(w,h,True,True)
            px0,py0,px1,py1 = layout['panel']
            self.assertTrue(0<layout['plot'][1]<px0<px1<w)
            for a,b,c,d in layout['pedals']:
                self.assertTrue(px0<a<c<px1 and py0<b<d<py1)
            cx,cy,radius = layout['wheel']
            self.assertTrue(px0<cx-radius<cx+radius<px1)
            self.assertTrue(py0<cy-radius<cy+radius<py1)

        class Window:
            def __init__(self):
                self.size,self.opacity = (840,300),.75
            def winfo_width(self): return self.size[0]
            def winfo_height(self): return self.size[1]
            def geometry(self,value): self.size = tuple(map(int,value.split('x')))
            def attributes(self,name,*value):
                if value: self.opacity = value[0]
                return self.opacity
            def minsize(self,*size): self.minimum = size
            def configure(self,**options): self.background = options['bg']
        class Canvas:
            def pack_forget(self): pass
            def pack(self,**options): pass
            def configure(self,**options): self.background = options['bg']
        hud = object.__new__(app.App)
        hud.root,hud.canvas = Window(),Canvas()
        hud.hud_mode = app.tk.StringVar(master=app.tk.Tcl(),value='normal')
        hud.applied_hud_mode = 'normal'
        hud.toggle_clean(with_controls=True)
        self.assertEqual(hud.root.size,(600,100))
        self.assertEqual(hud.root.opacity,1)
        self.assertEqual(hud.canvas.background,'#000000')
        hud.toggle_clean()
        self.assertEqual(hud.root.size,(440,100))
        self.assertEqual(hud.normal_size,(840,300))
        hud.toggle_clean()
        self.assertEqual(hud.root.size,(840,300))
        self.assertEqual(hud.root.opacity,.75)
        hud.toggle_clean()
        hud.toggle_clean(with_controls=True)
        hud.toggle_clean(with_controls=True)
        self.assertEqual(hud.root.size,(840,300))
        self.assertEqual(hud.root.opacity,.75)
        hud.apply_clean_mode()
        self.assertEqual(hud.hud_mode.get(),'normal')

    def test_540_degree_mapping_and_clockwise_rotation(self):
        self.assertEqual([app.steering_angle(v) for v in (-1,0,1)],[-270,0,270])
        self.assertEqual(app.steering_angle(1.01),270)
        self.assertEqual(app.steering_angle(-1.01),-270)
        x,y = app.rotate_wheel([(0,-1)],10,20,5,90)
        self.assertAlmostEqual(x,15)
        self.assertAlmostEqual(y,20)

    def test_control_render_uses_current_input_and_reuses_vector_items(self):
        class Canvas:
            def __init__(self):
                self.items = {}
                self.updates = 0
                self.tk = app.tk.Tcl()
                self._w = 'testcanvas'
                self.tk.createcommand(self._w,self.dispatch)
            def dispatch(self,verb,item,*coords):
                if verb=='coords':
                    self.coords(int(item),*[float(value) for value in coords])
            def create(self,*coords,**options):
                item = len(self.items)+1
                self.items[item] = [coords,options]
                return item
            create_rectangle = create_oval = create_polygon = create_line = create_text = create
            def coords(self,item,*coords):
                self.items[item][0] = coords
                self.updates += 1
            def itemconfigure(self,item,**options):
                self.items[item][1].update(options)
        hud = object.__new__(app.App)
        hud.canvas = Canvas()
        hud.live_items = {}
        hud.wheel_display = None
        layout = app.hud_layout(640,228)
        hud.paint_controls(layout,[.7,.2,-.4])
        brake,throttle = (hud.live_items[key][0] for key in ('brake_bar','throttle_bar'))
        self.assertEqual(hud.canvas.items[brake][1]['fill'],app.COLORS[1])
        self.assertEqual(hud.canvas.items[throttle][1]['fill'],app.COLORS[0])
        self.assertEqual(hud.canvas.items[brake][0],app.pedal_fill(layout['pedals'][0],.2))
        self.assertEqual(hud.canvas.items[throttle][0],app.pedal_fill(layout['pedals'][1],.7))
        self.assertEqual(hud.wheel_display.angle,-108)
        count = len(hud.canvas.items)
        updates = hud.canvas.updates
        hud.paint_controls(layout,[.7,.2,-.4])
        self.assertEqual(len(hud.canvas.items),count)
        self.assertEqual(hud.canvas.updates,updates)
        hud.paint_controls(layout,[0,1,1])
        self.assertEqual(len(hud.canvas.items),count)
        self.assertEqual(hud.wheel_display.angle,270)
        self.assertEqual(hud.canvas.items[throttle][1]['state'],'hidden')
        cx,cy,radius = layout['wheel']
        for kind,item,points in hud.wheel_display.parts:
            coords = hud.canvas.items[item][0]
            for x,y in zip(coords[::2],coords[1::2]):
                self.assertLessEqual(abs(x-cx),radius+1)
                self.assertLessEqual(abs(y-cy),radius+1)

        hud.canvas = Canvas()
        hud.live_items = {}
        hud.wheel_display = None
        hud.paint_controls(app.hud_layout(600,100,True,True),[.7,.2,-.4],clean=True)
        self.assertEqual(set(hud.live_items),{'brake_bar','throttle_bar'})
        self.assertFalse(any('text' in options for _,options in hud.canvas.items.values()))
        self.assertEqual(hud.wheel_display.angle,-108)
        self.assertTrue(any(options.get('fill')=='#000000'
                            for _,options in hud.canvas.items.values()))

    def test_sampling_limits_and_saved_settings(self):
        for rate in (1,120,4000):
            self.assertEqual(app.validate_settings(dict(fixed_hz=rate))['fixed_hz'],rate)
            self.assertEqual(app.validate_settings(dict(draw_hz=rate))['draw_hz'],rate)
        for value in (0,4001,12.5,float('nan')):
            with self.assertRaises(ValueError):
                app.validate_settings(dict(fixed_hz=value))
            with self.assertRaises(ValueError):
                app.validate_settings(dict(draw_hz=value))
        # Existing settings files upgrade to synchronized drawing automatically.
        old = app.validate_settings(dict(fixed_hz=1000,draw_hz=120))
        self.assertEqual(old['draw_mode'],'sync')
        self.assertEqual(old['input_channel'],'raw')
        self.assertEqual(app.drawing_rate(old,1000),1000)
        with self.assertRaises(ValueError):
            app.validate_settings(dict(draw_mode='invalid'))
        with self.assertRaises(ValueError):
            app.validate_settings(dict(input_channel='invalid'))
        with self.assertRaises(ValueError):
            app.validate_settings(dict(min_hz=200,max_hz=100))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            path = Path(temp)/'settings.json'
            app.save_settings(path,dict(app.DEFAULTS,mode='dynamic',min_hz=1,max_hz=4000,
                                        input_channel='filtered'))
            self.assertEqual(app.load_settings(path)['max_hz'],4000)
            self.assertEqual(app.load_settings(path)['input_channel'],'filtered')

    def test_hud_channel_switch_updates_whole_history_and_controls_in_all_modes(self):
        from collections import deque
        import threading
        from unittest.mock import Mock, patch
        engine = object.__new__(app.Engine)
        engine.points,engine.plot_points = deque(),deque()
        engine.reference_points,engine.reference_revision = deque(),0
        engine.reference_enabled,engine.reference_latest = False,None
        engine.plot_hz,engine.plot_y_scale,engine.plot_revision = 237,400,0
        engine.lock = threading.Lock()
        sample = app.extract(fixture())
        for timestamp in (98,99):
            engine.add_plot_point(timestamp,sample['controls'])
        original_points = tuple(engine.points)
        engine.latest = sample
        engine.target_hz = 1
        engine.demo = False
        engine.recorder = Mock(file=object())
        engine.actual_rates = Mock(return_value=(1,1))
        hud = object.__new__(app.App)
        hud.engine = engine
        hud.root,hud.canvas = Mock(),Mock()
        hud.canvas.winfo_width.return_value = 640
        hud.canvas.winfo_height.return_value = 228
        hud.settings = app.validate_settings(dict(fixed_hz=1))
        hud.closing,hud.drawing,hud.clickthrough = False,False,False
        hud.chrome_key,hud.trace_key,hud.live_key = None,None,None
        hud.trace_expiry = 0
        hud.live_items = {}
        hud.wheel_display = None
        hud.render_clock = app.FrameDeadline(0)
        hud.paint_chrome,hud.paint_controls,hud.paint_trace,hud.live_item = Mock(),Mock(),Mock(),Mock()
        hud.actual_draw_rate = Mock(return_value=1)
        interpreter = app.tk.Tcl()
        hud.input_channel = app.tk.StringVar(master=interpreter,value='raw')
        hud.hud_mode = app.tk.StringVar(master=interpreter,value='normal')
        hud.window = app.tk.StringVar(master=interpreter,value='10')
        hud.reference_on = app.tk.BooleanVar(master=interpreter,value=False)
        for mode in ('normal','curves','controls'):
            hud.hud_mode.set(mode)
            for channel,expected in (('raw',[.7,.2,-.4]),('filtered',[.6,.1,-.3]),
                                      ('raw',[.7,.2,-.4])):
                hud.input_channel.set(channel)
                hud.drawing = False
                hud.canvas.reset_mock()
                hud.paint_controls.reset_mock()
                hud.paint_trace.reset_mock()
                hud.live_item.reset_mock()
                with patch.object(app.time,'monotonic',return_value=100):
                    hud.draw()
                self.assertIn('trace',[args[0] for args,_ in hud.canvas.delete.call_args_list])
                layout = app.hud_layout(640,228,mode!='normal',mode=='controls')
                _,_,top,bottom = layout['plot']
                self.assertEqual(hud.paint_trace.call_count,3)
                for lane,call in enumerate(hud.paint_trace.call_args_list):
                    coords = call.args[0]
                    fraction = (expected[lane]+1)/2 if lane==2 else expected[lane]
                    expected_y = bottom-fraction*(bottom-top)
                    self.assertTrue(all(abs(y-expected_y)<1e-9 for y in coords[1::2]))
                if mode=='curves':
                    hud.paint_controls.assert_not_called()
                else:
                    self.assertEqual(hud.paint_controls.call_args.args[1],expected)
                keys = [call.args[0] for call in hud.live_item.call_args_list]
                self.assertEqual('input_channel' in keys,mode=='normal')
                self.assertEqual(tuple(engine.points),original_points)
                self.assertEqual(hud.drawing_target(),1)
        engine.reference_enabled = True
        engine.reference_points.extend([(99,.8,.4,.65,.25,.123),(99.02,.8,.4,.65,.25,.123)])
        engine.reference_latest = (.8,.4,.65,.25,.123)
        hud.reference_on.set(True)
        for mode in ('normal','curves','controls'):
            for channel,expected in (('raw',[.8,.4]),('filtered',[.65,.25])):
                hud.hud_mode.set(mode);hud.input_channel.set(channel)
                hud.drawing=False;hud.trace_key=None;hud.canvas.reset_mock();hud.live_item.reset_mock()
                with patch.object(app.time,'monotonic',return_value=100):hud.draw()
                calls=[call for call in hud.canvas.create_line.call_args_list if call.kwargs.get('dash')==(3,4)]
                self.assertEqual(len(calls),2)
                _,_,top,bottom=app.hud_layout(640,228,mode!='normal',mode=='controls')['plot']
                for call,value in zip(calls,expected):
                    self.assertTrue(all(abs(y-(bottom-value*(bottom-top)))<1e-9 for y in call.args[1::2]))
                self.assertEqual(bool(hud.live_item.call_args_list),mode=='normal')

    def test_channel_preference_is_saved_without_reconfiguring_or_splitting_recording(self):
        import threading
        from unittest.mock import Mock, patch
        hud = object.__new__(app.App)
        settings = app.validate_settings(dict(fixed_hz=2400,min_hz=120,max_hz=1000))
        hud.settings = settings
        hud.input_channel = app.tk.StringVar(master=app.tk.Tcl(),value='raw')
        hud.engine = Mock(settings=settings,target_hz=2400)
        original_recording = hud.engine.recorder
        hud.render_wake = threading.Event()
        hud.root = Mock()
        hud.drawing = False
        hud.draw_job = 'pending'
        hud.trace_key = 'cached'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp, patch.object(app,'ROOT',Path(temp)):
            hud.toggle_input_channel()
            checked = app.load_settings(Path(temp)/'settings.json')
            self.assertEqual(checked['input_channel'],'filtered')
            self.assertEqual(hud.input_channel.get(),'filtered')
            self.assertEqual({k:v for k,v in checked.items() if k!='input_channel'},
                             {k:v for k,v in settings.items() if k!='input_channel'})
            self.assertIs(hud.engine.settings,settings)
            hud.engine.update_settings.assert_not_called()
            hud.engine.recorder.finish.assert_not_called()
            self.assertIs(hud.engine.recorder,original_recording)
            self.assertTrue(hud.render_wake.is_set())
            self.assertIsNone(hud.trace_key)
            hud.root.after_cancel.assert_called_once_with('pending')
            hud.root.after_idle.assert_called_once()
            hud.toggle_input_channel()
            self.assertEqual(app.load_settings(Path(temp)/'settings.json')['input_channel'],'raw')

    def test_dynamic_sampling_change_hold_brake_and_stale_frames(self):
        settings = app.validate_settings(dict(mode='dynamic',min_hz=30,max_hz=500,hold_s=1,
                                              change_pct_s=10,brake_pct=5))
        policy = app.AdaptiveSampler(settings,0)
        sample = app.extract(fixture())
        sample['controls'] = [0,0,0,0,0,0]
        policy.observe(sample,0)
        self.assertEqual(policy.rate(0),500)
        self.assertEqual(policy.rate(1.1),30)
        sample = dict(sample,et=10.1,controls=[0.1,0,0,0,0,0])
        policy.observe(sample,1.2)
        self.assertEqual(policy.rate(1.2),500)
        policy.observe(sample,1.8)
        self.assertEqual(policy.rate(2.21),30)
        sample = dict(sample,et=10.2,controls=[0.1,0.2,0,0,0,0])
        policy.observe(sample,2.3)
        self.assertEqual(policy.rate(2.3),500)
        policy.observe(sample,3.0)
        self.assertEqual(policy.rate(3.31),30)
        self.assertEqual(policy.rate(2.4,fresh=False),30)

    def test_drawing_tracks_dynamic_target_and_allows_manual_override(self):
        settings = app.validate_settings(dict(mode='dynamic',min_hz=1,max_hz=4000,hold_s=0.1))
        policy = app.AdaptiveSampler(settings,0)
        self.assertEqual(app.drawing_rate(settings,policy.rate(0)),4000)
        self.assertEqual(app.drawing_rate(settings,policy.rate(0.2)),1)
        sample = dict(et=1,controls=[0,0.2,0])
        policy.observe(sample,0.3)
        self.assertEqual(app.drawing_rate(settings,policy.rate(0.3)),4000)
        manual = app.validate_settings(dict(settings,draw_mode='manual',draw_hz=333))
        self.assertEqual(app.drawing_rate(manual,4000),333)

    def test_frame_deadlines_change_immediately_and_skip_overdue_frames(self):
        clock = app.FrameDeadline(0)
        clock.set_rate(1,0)
        self.assertEqual(clock.complete(0),1)
        self.assertTrue(clock.set_rate(4000,0.02))
        self.assertEqual(clock.deadline,0.02)
        # A slow frame produces one future deadline, with no catch-up queue.
        deadline = clock.complete(0.023)
        self.assertGreater(deadline,0.023)
        self.assertLessEqual(deadline,0.02325)
        self.assertGreater(clock.missed_cycles,0)
        self.assertFalse(clock.set_rate(4000,0.023))
        self.assertEqual(clock.deadline,deadline)
        self.assertTrue(clock.set_rate(60,0.03))
        self.assertAlmostEqual(clock.complete(0.03),0.03+1/60)

    def test_high_rate_plot_envelope_preserves_spike_and_twenty_seconds(self):
        engine = object.__new__(app.Engine)
        from collections import deque
        import threading
        engine.points = deque(maxlen=80001)
        engine.plot_points = deque(maxlen=80001)
        engine.plot_hz = 237
        engine.plot_y_scale = 400
        engine.plot_revision = 0
        engine.lock = threading.Lock()
        for i in range(80000):
            engine.add_plot_point(i/4000,[0,1 if i==40005 else 0,0,
                                          .8 if i==50003 else 0,.25 if i==40005 else 0,-.3])
        self.assertGreaterEqual(engine.points[-1][0]-engine.points[0][0],19.99)
        self.assertTrue(any(point[8]==1 for point in engine.points))
        self.assertEqual(len(engine.points),80000)
        self.assertTrue(any(point[8]==1 for point in engine.plot_points))
        self.assertTrue(any(point[16]==.8 for point in engine.plot_points))
        self.assertTrue(any(point[17]==.25 for point in engine.plot_points))
        engine.configure_plot(816,5)
        self.assertGreater(engine.plot_hz,240)
        self.assertTrue(any(point[8]==1 for point in engine.plot_points))
        self.assertTrue(any(point[16]==.8 for point in engine.plot_points))
        self.assertTrue(any(point[17]==.25 for point in engine.plot_points))
        self.assertLessEqual(len(engine.plot_points),engine.plot_hz*20+1)
        engine.add_plot_point(21,[0,0,0,0,0,0])
        self.assertTrue(all(21-p[0]<=20 for p in engine.points))

    def test_reconfiguration_wakes_one_hz_sampler_without_splitting_log(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            engine = app.Engine(demo=True,output=temp,settings=dict(fixed_hz=1))
            time.sleep(0.05)
            engine.update_settings(dict(fixed_hz=200))
            time.sleep(0.25)
            engine.stop.set()
            engine.thread.join(3)
            if engine.recorder.report_thread:
                engine.recorder.report_thread.join(3)
            folders = list(Path(temp).iterdir())
            self.assertEqual(len(folders),1)
            meta = json.loads((folders[0]/'session.json').read_text())
            self.assertGreater(meta['samples'],20)
            self.assertEqual(meta['settings_history'][0]['settings']['fixed_hz'],1)
            self.assertEqual(meta['settings_history'][-1]['settings']['fixed_hz'],200)
            self.assertEqual(meta['nominal_draw_hz'],200)
            self.assertEqual(meta['draw_mode'],'sync')

    def test_four_k_polling_does_not_fabricate_frames_from_one_hundred_hz_source(self):
        class Feed:
            def __init__(self):
                self.start = time.monotonic()
                self.base = app.extract(fixture())
            def read(self):
                return dict(self.base,et=int((time.monotonic()-self.start)*100)/100)
            def close(self):
                pass
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            engine = app.Engine(output=temp,reader_factory=Feed,settings=dict(fixed_hz=4000))
            time.sleep(0.25)
            engine.stop.set()
            engine.thread.join(3)
            if engine.recorder.report_thread:
                engine.recorder.report_thread.join(3)
            meta = json.loads((engine.last_folder/'session.json').read_text())
            self.assertLess(meta['samples'],40)
            self.assertGreater(len(engine.poll_times),meta['samples']*2)
            self.assertLess(meta['effective_sample_hz'],110)

    def test_display_simplification_preserves_a_brief_pedal_spike(self):
        straight = [v for i in range(100) for v in (i, 0)]
        self.assertEqual(app.reduce_trace(straight), [0, 0, 99, 0])
        spike = straight.copy()
        spike[101] = 50
        reduced = app.reduce_trace(spike)
        self.assertIn((50, 50), list(zip(reduced[::2], reduced[1::2])))
        self.assertEqual(spike[101], 50)
        vertical_spike = [0, 0, 0.0005, 200, 0.001, 100]
        self.assertEqual(app.reduce_trace(vertical_spike), vertical_spike)

    def test_trace_simplification_bounds_error_and_handles_long_flat_waveforms(self):
        import math
        coords = [v for i in range(10000) for v in (i/10,20*math.sin(i/137))]
        reduced = app.reduce_trace(coords)
        segments = list(zip(reduced[::2],reduced[1::2]))
        self.assertLess(len(segments),1000)
        segment = 0
        for x,y in zip(coords[::2],coords[1::2]):
            while segment+2<len(segments) and segments[segment+1][0]<x:
                segment += 1
            a,b = segments[segment:segment+2]
            interpolated = a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])
            self.assertLessEqual(abs(interpolated-y),0.350001)
        # Regression for repeated flat and near-vertical edges at high sampling rates.
        stepped = [v for i in range(20000) for v in (i/4000,100 if i%17==0 else 0)]
        simplified = app.reduce_trace(stepped)
        self.assertTrue(any(y==100 for y in simplified[1::2]))

    def test_player_matching_uses_id_not_array_position(self):
        sample = app.extract(fixture())
        self.assertEqual(sample['player_id'], 42)
        self.assertEqual(sample['controls'], [0.7, 0.2, -0.4, 0.6, 0.1, -0.3])
        self.assertEqual(sample['speed'], 36)
        self.assertEqual(sample['position'],[123.45,5.6,-789.01])
        self.assertIn('lap_invalidated',sample)
        self.assertIn('lap_start',sample)
        data = fixture()
        data.telemetry.telemInfo[0].mID = 99
        self.assertIsNone(app.extract(data))
        data = fixture()
        data.telemetry.telemInfo[0].mUnfilteredBrake = float('nan')
        self.assertIsNone(app.extract(data))

    def test_invalid_position_does_not_drop_valid_input_sample(self):
        data = fixture()
        data.telemetry.telemInfo[0].mPos.z = float('nan')
        sample = app.extract(data)
        self.assertIsNotNone(sample)
        self.assertIsNone(sample['position'])
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            recorder = app.Recorder(temp)
            recorder.start(sample)
            recorder.add(sample)
            recorder.add(dict(sample,et=10.1,position=[100,5,200]))
            folder = recorder.finish('position test')
            recorder.report_thread.join(3)
            with (folder/'inputs.csv').open(encoding='utf-8') as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual(len(records),2)
            self.assertEqual([records[0][k] for k in ('world_x_m','world_y_m','world_z_m')],['','',''])
            self.assertEqual(records[1]['world_z_m'],'200.000')
            self.assertEqual(records[0]['throttle'],'0.700000')

    def test_map_trajectory_is_bounded_and_retains_end_boundary(self):
        rows=[]
        for i in range(40001):
            t=i/4000
            rows.append(dict(session_time_s=t,world_x_m=200*math.cos(t/10*math.tau),
                             world_z_m=120*math.sin(t/10*math.tau)))
        best=dict(start_s=0,end_s=10,rows=rows[:-1],next_row=rows[-1])
        data=[[r['session_time_s']*100,r['session_time_s'],0,0,0,0,150] for r in rows]
        trajectory = lap_export.trajectory_data(best,data)
        self.assertLessEqual(len(trajectory['points']),502)
        self.assertEqual(trajectory['points'][-1],[10,1000,200,0])
        self.assertTrue(all(abs(math.hypot(p[2]/200,p[3]/120)-1)<.00002
                            for p in trajectory['points']))
        missing=dict(best,rows=[dict(session_time_s=i) for i in range(10)],next_row={'session_time_s':10})
        self.assertIsNone(lap_export.trajectory_data(missing,data))

    def test_review_and_compare_embed_local_map_assets(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            folder = self.lap_csv(Path(temp)/'session')
            before = (folder/'inputs.csv').read_bytes()
            app.make_report(folder)
            review = (folder/'review.html').read_text(encoding='utf-8')
            comparison = (folder/'fastest_lap.html').read_text(encoding='utf-8')
            for document in (review,comparison):
                self.assertIn('id="track-map"',document)
                self.assertIn('class View',document)
                self.assertNotIn('/*TRACK_VIEW_JS*/',document)
                self.assertNotIn('/*TRACK_CATALOG*/',document)
                self.assertNotIn('<script src=',document)
                self.assertIn('const trackCatalog=',document)
            self.assertEqual((folder/'inputs.csv').read_bytes(),before)

    def test_actual_windows_map_is_read_only_and_not_created(self):
        name = 'LMU_InputScope_Test_' + str(time.time_ns())
        with self.assertRaises(OSError):
            app.SharedReader(name)
        data = fixture()
        with mmap.mmap(-1, ctypes.sizeof(data), tagname=name) as producer:
            producer.write(bytes(data))
            reader = app.SharedReader(name)
            try:
                self.assertEqual(reader.read()['player_id'], 42)
                self.assertEqual(producer[:], bytes(data))
                self.assertEqual(reader.read()['player_id'], 42)
                data.telemetry.telemInfo[0].mElapsedTime += 0.01
                data.telemetry.telemInfo[0].mUnfilteredBrake = 0.9
                producer.seek(0)
                producer.write(bytes(data))
                self.assertEqual(reader.read()['controls'][1],0.9)
                data.scoring.scoringInfo.mInRealtime = False
                producer.seek(0)
                producer.write(bytes(data))
                self.assertIsNone(reader.read())
                self.assertEqual(producer[:],bytes(data))
            finally:
                reader.close()

    def test_log_preserves_all_unique_frames_and_report_escapes_markup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            recorder = app.Recorder(temp)
            sample = app.extract(fixture())
            sample['driver'] = '</script><script>danger()</script>'
            recorder.start(sample)
            for i in range(1000):
                sample['et'] = 10 + i / 60
                self.assertTrue(recorder.add(sample))
                self.assertFalse(recorder.add(sample))
            folder = recorder.finish('test completed')
            with (folder / 'inputs.csv').open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1000)
            for _ in range(100):
                if (folder / 'review.html').exists():
                    break
                time.sleep(0.02)
            self.assertTrue((folder / 'review.html').is_file())
            text = (folder / 'review.html').read_text(encoding='utf-8')
            self.assertNotIn('</script><script>danger()', text)
            meta = json.loads((folder / 'session.json').read_text())
            self.assertEqual(meta['samples'], 1000)
            self.assertEqual(meta['status'], 'complete')
            self.assertAlmostEqual(meta['effective_sample_hz'], 60, places=4)

    def test_engine_finalizes_session_and_does_not_restart_after_finish(self):
        class Feed:
            def __init__(self):
                self.index = 0
            def read(self):
                self.index += 1
                return app.extract(fixture(10 + min(self.index, 12) / 100,
                                           1 if self.index >= 12 else 0))
            def close(self):
                pass
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
            engine = app.Engine(output=temp, reader_factory=Feed)
            time.sleep(0.4)
            engine.stop.set()
            engine.thread.join(3)
            if engine.recorder.report_thread:
                engine.recorder.report_thread.join(3)
            folders = list(Path(temp).iterdir())
            self.assertEqual(len(folders), 1)
            meta = json.loads((folders[0] / 'session.json').read_text())
            self.assertEqual(meta['samples'], 12)
            self.assertEqual(meta['end_reason'], 'finish flag 1')


if __name__ == '__main__':
    # Tcl fixture cycles must be collected on their creating thread.
    import gc
    gc.disable()
    result=unittest.main(verbosity=2,exit=False).result
    gc.collect()
    sys.exit(not result.wasSuccessful())
