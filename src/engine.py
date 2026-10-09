"""Sampling engine, bounded display history and live telemetry analysis."""
import math
import threading
import time

import endurance
import vehiclelab
from recording_policy import should_record
from app_config import ROOT
from buffers import ControlHistory, NumericRing, window_rate
from diagnostics import Diagnostics
from recorder import Recorder
from reference import DistanceAligner
from sampling import AdaptiveSampler, DEFAULTS, PreciseWait, validate_settings
from storage import StorageError, atomic_json
from telemetry import SharedReader


class Engine:
    def __init__(self, demo=False, output=None, reader_factory=SharedReader, settings=None, rate_wake=None,vehicle_settings=None,endurance_settings=None):
        self.demo = demo
        self.reader_factory = reader_factory
        self.recorder = Recorder(output or ROOT / ('DemoLogs' if demo else 'Logs'),vehicle_settings,endurance_settings)
        self.endurance_monitor=endurance.Monitor(endurance_settings)
        self.fuel_planner=vehiclelab.FuelPlanner(vehicle_settings)
        self.vehicle_latest=None;self.vehicle_estimate={}
        self.settings = validate_settings(settings or DEFAULTS)
        self.target_hz = self.settings['fixed_hz'] if self.settings['mode']=='fixed' else self.settings['max_hz']
        self.points = ControlHistory(80001)
        self.reference = None
        self.reference_enabled = False
        self.reference_points = NumericRing(6,24001)
        self.reference_latest = None
        self.reference_revision = 0
        self.aligner = DistanceAligner()
        self.reference_state = {'mode':'关闭','confidence':0}
        self.diagnostics = Diagnostics()
        self.plot_points = NumericRing(19,80001)
        self.plot_hz = math.ceil(592*4/10)
        self.plot_y_scale = 102*4
        self.plot_revision = 0
        self.sample_times = NumericRing(1,12001)
        self.poll_times = NumericRing(1,12001)
        self._rates_at = -math.inf
        self._rates = (0, 0)
        self.reason = ''
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.rate_wake = rate_wake if rate_wake is not None else threading.Event()
        self.status = 'DEMO · synthetic input' if demo else 'Waiting for LMU · 自动记录'
        self.latest = None
        self.last_folder = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def update_settings(self, settings):
        self.settings = validate_settings(settings)
        self.wake.set()
        self.rate_wake.set()

    def actual_rates(self):
        now = time.monotonic()
        if now-self._rates_at >= 0.25:
            horizon = max(2.5, 2.5/self.target_hz)
            with self.lock:
                self._rates = (window_rate(self.poll_times, now-horizon),
                               window_rate(self.sample_times, now-horizon))
            self._rates_at = now
        return self._rates

    def add_plot_point(self, now, controls):
        # Retain all captured samples for 20 seconds. Display buckets depend on pixel
        # precision (four buckets per pixel), not a fixed 240 Hz temporal ceiling.
        # Keep both channels on the same timestamps: a display switch can redraw
        # the entire history without mixing old raw points with new filtered ones.
        raw, filtered = controls[:3], controls[3:6]
        point = (now,*raw,*raw,*raw,*filtered,*filtered,*filtered)
        self.points.append(point)
        while self.points and now-self.points[0][0] > 20:
            self.points.popleft()
        self._add_display_point(point)

    def _add_display_point(self, point):
        now = point[0]
        bucket = int(now*self.plot_hz)
        if self.plot_points and int(self.plot_points[-1][0]*self.plot_hz)==bucket:
            old = self.plot_points.pop()
            merged = [now]
            for offset in (1, 10):
                controls = point[offset:offset+3]
                low = [min(a,b) for a,b in zip(old[offset+3:offset+6],controls)]
                high = [max(a,b) for a,b in zip(old[offset+6:offset+9],controls)]
                merged.extend((*controls,*low,*high))
            point = tuple(merged)
            def signature(value):
                return tuple(round(v*self.plot_y_scale/(2 if i%3==2 else 1))
                             for offset in (1,10)
                             for i,v in enumerate(value[offset+3:offset+9]))
            if signature(old) != signature(point):
                self.plot_revision += 1
            self.plot_points.append(point)
        else:
            self.plot_points.append(point)
            self.plot_revision += 1
        while self.plot_points and now-self.plot_points[0][0] > 20:
            self.plot_points.popleft()

    def configure_plot(self, width, window, height=None):
        hz = min(4000, max(1, math.ceil(width*4/window)))
        scale = self.plot_y_scale if height is None else max(4,height*4)
        if hz != self.plot_hz or scale != self.plot_y_scale:
            with self.lock:
                self.plot_hz = hz
                self.plot_y_scale = scale
                self.plot_revision += 1
                self.plot_points.clear()
                for point in self.points:
                    self._add_display_point(point)

    def finish_recording(self,reason,failure=None):
        folder=self.recorder.finish(reason,failure)
        if folder:
            self.last_folder=folder
            if self.recorder.meta.get('status')=='write_error':self.recording_failure=self.recorder.meta['end_reason']
            snapshot=self.diagnostics.snapshot()
            poll,fresh=self.actual_rates()
            snapshot.update(poll_hz=poll,fresh_hz=fresh,sampling_target=self.target_hz,
                missed_poll_cycles=self.missed_cycles,alignment=self.reference_state)
            atomic_json(folder/'performance.json',snapshot)
        return folder

    def run(self):
        reader = None
        last_fresh = time.monotonic()
        last_seen_et = None
        last_received_perf = None
        ended_key = None
        key = None
        start = time.monotonic()
        config = self.settings
        sampler = AdaptiveSampler(config, start)
        waiter = PreciseWait(self.stop, self.wake)
        period = 1 / self.target_hz
        deadline = time.perf_counter()
        self.missed_cycles = 0
        while not self.stop.is_set():
            now = time.monotonic()
            self.recorder.retry_reports(now)
            if config is not self.settings:
                config = self.settings
                sampler.configure(config, now)
                deadline = time.perf_counter()
            try:
                if self.demo:
                    t = now - start
                    controls = [max(0, math.sin(t * 0.65)), max(0, -math.sin(t * 0.65)) ** 3,
                                math.sin(t * 0.8) * 0.65]
                    sample = dict(track='Demo Circuit', driver='DEMO', vehicle='Synthetic', session=10,
                                  player_id=0, et=t, lap=int(t // 20) + 1, distance=(t % 20) * 100,
                                  controls=controls * 2, speed=160, finish=0, demo=True,
                                  position=[300*math.cos(t/20*math.tau),0,200*math.sin(t/20*math.tau)],
                                  lap_start=int(t//20)*20,lap_invalidated=False,in_pits=False,track_length=2000)
                    sample['vehicle_data']=vehiclelab.demo_vehicle(t)
                    sample['in_pits']=sample['vehicle_data']['pit_state'] in (2,3,4)
                    sample['speed']=sample['vehicle_data']['speed_kmh']
                    sample['conditions']={'fuel_l':sample['vehicle_data']['fuel_l'],'gear':4,'tyre_compound':0,'track_temp_c':sample['vehicle_data']['track_temp_c'],'wetness':sample['vehicle_data']['wetness']}
                else:
                    if reader is None:
                        reader = self.reader_factory()
                    read_started=time.perf_counter()
                    sample = reader.read()
                    self.diagnostics.note('read',time.perf_counter()-read_started)
                with self.lock:
                    self.poll_times.append((now,))
                sampler.observe(sample, now)
                self.target_hz = sampler.rate(now, sample is not None and now-last_fresh <= 3)
                self.reason = sampler.reason
                if sample is not None:
                    next_key = tuple(sample[k] for k in ('track', 'session', 'driver', 'player_id'))
                    reset = last_seen_et is not None and sample['et'] < last_seen_et - 0.5
                    if next_key != key or reset:
                        self.finish_recording('session changed')
                        self.recording_failure=None
                        ended_key = None
                        key = next_key
                        # A new session may begin with the same elapsed time as
                        # its predecessor. Its first frame is still new data.
                        last_seen_et = None
                        with self.lock:
                            self.points.clear()
                            self.reference_points.clear()
                            self.reference_latest = None
                            self.aligner=DistanceAligner()
                            self.reference_state={'mode':'新场次','confidence':0}
                            self.reference_revision += 1
                            self.plot_points.clear()
                            self.plot_revision += 1
                            self.sample_times.clear()
                    fresh = sample['et'] != last_seen_et
                    last_seen_et = sample['et']
                    if fresh:
                        last_fresh = now
                        last_received_perf=time.perf_counter()
                    sample=dict(sample,_received_perf=last_received_perf)
                    recording=should_record(sample['session'],self.demo)
                    if recording and self.recorder.file is None and ended_key != key and sample['finish'] == 0 and fresh:
                        self.recorder.start(sample, config, self.target_hz)
                        self.recorder.meta['vehicle_strategy']['started_at_s']=(self.fuel_planner.baseline_et if self.fuel_planner.baseline_et is not None else sample['et'])-sample['et']
                        self.session_missed_base = self.missed_cycles
                    if self.recorder.file is not None and fresh:
                        self.recorder.set_sampling(config, self.target_hz, sample['et']-self.recorder.origin)
                        with self.recorder.meta_lock:self.recorder.meta['missed_poll_cycles'] = self.missed_cycles - self.session_missed_base
                        self.recorder.add(sample)
                    elif self.recorder.file is not None:
                        self.recorder.observe_race(sample)
                    with self.lock:
                        if fresh:
                            vehicle_sample = dict(sample, vehicle_name=sample['vehicle'],
                                                  vehicle=sample.get('vehicle_data',{}))
                            self.endurance_monitor.update(vehicle_sample)
                            self.fuel_planner.update(vehicle_sample)
                            self.vehicle_latest=sample.get('vehicle_data')
                            self.vehicle_estimate=self.fuel_planner.estimate(vehicle_sample)
                            self.add_plot_point(now, sample['controls'])
                            aligned=self.aligner.update(sample,self.reference) if self.reference_enabled else None
                            self.reference_state=self.aligner.state if self.reference_enabled else {'mode':'关闭','confidence':0}
                            if aligned is not None:
                                reference_sample = dict(sample,
                                    distance=aligned/self.reference.length*sample['track_length'],
                                    conditions=self.reference_state['matching_conditions'])
                                self.reference_latest = self.reference.sample(reference_sample)
                            else:
                                self.reference_latest = None
                            if self.reference_latest:
                                point = (now,*self.reference_latest)
                                if self.reference_points and int(self.reference_points[-1][0]*self.plot_hz)==int(now*self.plot_hz):
                                    old = self.reference_points[-1]
                                    self.reference_points[-1] = point
                                    if any(round(a*self.plot_y_scale)!=round(b*self.plot_y_scale) for a,b in zip(old[1:5],point[1:5])):
                                        self.reference_revision += 1
                                else:
                                    self.reference_points.append(point)
                                    self.reference_revision += 1
                                while self.reference_points and now-self.reference_points[0][0]>20:
                                    self.reference_points.popleft()
                            self.sample_times.append((now,))
                        self.latest = sample
                    if fresh:
                        self.status = ('DEMO' if self.demo else 'REC' if recording else 'LIVE · 此阶段不录制') + ' · ' + sample['track']
                    if ended_key == key:
                        self.status = ('ERROR · '+self.recording_failure if getattr(self,'recording_failure',None) else 'SAVED · 比赛记录已保存')
                    if sample['finish'] in (1, 2, 3) and self.recorder.file:
                        self.finish_recording('finish flag ' + str(sample['finish']))
                        ended_key = key
                        self.status = 'SAVED · 比赛记录已保存'
                if now - last_fresh > 3:
                    self.finish_recording('left session / data timeout')
                    self.status = 'Waiting for fresh telemetry · 记录已保存' if self.last_folder else 'Waiting for LMU'
                    with self.lock:
                        self.latest = None
                        self.vehicle_latest=None
                        self.reference_latest = None
                        self.reference_state={'mode':'遥测超时','confidence':0}
                        self.aligner=DistanceAligner()
                    if reader:
                        reader.close()
                        reader = None
                    last_fresh = now
            except StorageError as error:
                self.recording_failure=str(error)
                self.finish_recording('writer failed',str(error))
                ended_key=key
                self.status='ERROR · '+str(error)[:110]
            except OSError:
                self.status = 'Waiting for LMU · 启动游戏并进入赛道'
                self.target_hz = sampler.rate(now, fresh=False)
                self.reason = sampler.reason
                self.stop.wait(0.5)
                deadline=time.perf_counter()
            except Exception as error:
                self.status = 'ERROR · ' + str(error)[:110]
                self.finish_recording('reader error')
                if reader:
                    reader.close()
                    reader = None
                self.stop.wait(0.5)
                deadline=time.perf_counter()
            new_period = 1 / self.target_hz
            if new_period != period:
                period = new_period
                deadline = time.perf_counter()
                self.rate_wake.set()
            deadline += period
            remaining = deadline - time.perf_counter()
            if remaining < -period:
                skipped = int(-remaining / period)
                self.missed_cycles += skipped
                deadline += skipped * period
            if waiter.until(deadline):
                deadline = time.perf_counter()
        self.finish_recording('application closed')
        if reader:
            reader.close()
        waiter.close()
