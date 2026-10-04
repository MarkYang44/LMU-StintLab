"""Lossless session recording and asynchronous report completion."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import endurance
import vehiclelab
from app_config import COLUMNS, DRAW_HZ, EXTRA_COLUMNS, POLL_HZ
from library import session_label
from sampling import DEFAULTS, drawing_rate
from session_reports import make_report
from storage import BatchWriter, StorageError, atomic_json


class Recorder:
    def __init__(self, output, vehicle_settings=None,endurance_settings=None):
        self.output = Path(output)
        self.folder = None
        self.file = None
        self.last_flush = 0
        self.samples = 0
        self.batch = None
        self.vehicle_settings=vehiclelab.settings(vehicle_settings)
        self.endurance_settings=endurance.settings(endurance_settings)
        self.vehicle_batch=None;self.vehicle_last=None;self.vehicle_last_sample=None
        self.last_et = None
        self.meta = {}
        self.report_thread = None
        self.pending_reports = []
        self.meta_lock = threading.RLock()
        self.meta_io_lock = threading.Lock()

    def start(self, sample, settings=None, target_hz=None):
        self.batch=None
        self.vehicle_batch=None;self.vehicle_last=None;self.vehicle_last_sample=None
        safe = ''.join('_' if c in '<>:"/\\|?*' else c for c in sample['track'])[:60]
        self.folder = self.output / (datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f') + '_'
                                     + session_label(sample.get('session')) + '_' + safe)
        self.folder.mkdir(parents=True)
        self.meta = {k: sample[k] for k in ('track', 'driver', 'vehicle', 'session', 'player_id')}
        self.meta.update(started_utc=datetime.now(timezone.utc).isoformat(), status='recording',
                         input_units='Throttle/brake 0..1; steering -1..1 left to right',
                         position_units='LMU world XYZ in metres; top-down map uses XZ',
                         nominal_poll_hz=POLL_HZ, nominal_draw_hz=DRAW_HZ,
                         source=('Synthetic demo' if sample.get('demo') else
                                 'LMU_Data / pyLMUSharedMemory'))
        self.origin = sample['et']
        self.meta['endurance_settings']=dict(self.endurance_settings)
        self.meta['endurance_units']=dict(speed='km/h',rain='severity 0..1, not mm/h',wetness='path statistics 0..1',
            temperatures='Celsius',wind='SDK raw world XYZ vector; units unverified',pit_state='0 none / 1 request / 2 entering / 3 stopped / 4 exiting')
        self.meta['vehicle_telemetry']=dict(version=1,target_hz=self.vehicle_settings['record_hz'],
            file='vehicle.csv',units='tyre Celsius / pressure kPa / mWear fraction; fuel L; battery and virtual energy percent; power kW',
            temperature_mapping='FL/RL inner=right, FR/RR inner=left; SDK surface arrays left/centre/right',
            freshness='fresh frames only; capped rate; lap and pit transitions retained')
        self.meta['vehicle_profile']=self.vehicle_settings['profiles'].get(sample['vehicle'],self.vehicle_settings['profiles'].get('*',vehiclelab.DEFAULT_PROFILE))
        self.meta['vehicle_strategy']={k:self.vehicle_settings[k] for k in ('history_laps','rate_mode','target_mode','target_value','reserve_l','extra_finish_laps')}
        self.last_et = None
        self.samples = 0
        self.set_sampling(settings or DEFAULTS, target_hz or POLL_HZ, 0)
        self.save_meta()
        try:
            self.batch = BatchWriter(self.folder,COLUMNS,on_checkpoint=self.save_meta)
            if sample.get('vehicle_data'):
                self.vehicle_batch=BatchWriter(self.folder,vehiclelab.COLUMNS,on_checkpoint=self.save_meta,
                    filename='vehicle.csv',checkpoint_name='vehicle_checkpoint.json')
        except StorageError as e:
            if self.batch:self.batch.finish()
            self.meta.update(status='write_error',end_reason=str(e));self.save_meta();raise
        self.file = self.batch.file

    def set_sampling(self, settings, target_hz, elapsed):
        with self.meta_lock:self._set_sampling(settings,target_hz,elapsed)

    def _set_sampling(self, settings, target_hz, elapsed):
        if self.meta.get('sampling_settings') != settings:
            self.meta['sampling_settings'] = dict(settings)
            self.meta.setdefault('settings_history', []).append(dict(time_s=elapsed, settings=dict(settings)))
        if self.meta.get('nominal_poll_hz') != target_hz or 'poll_rate_history' not in self.meta:
            self.meta['nominal_poll_hz'] = target_hz
            self.meta.setdefault('poll_rate_history', []).append(dict(time_s=elapsed, target_hz=target_hz))
        self.meta['nominal_draw_hz'] = drawing_rate(settings, target_hz)
        self.meta['draw_mode'] = settings['draw_mode']

    def save_meta(self):
        with self.meta_io_lock:
            with self.meta_lock:
                self.meta['samples'] = self.samples
                if self.batch:self.meta['written_samples']=self.batch.rows
                if self.vehicle_batch:self.meta['written_vehicle_samples']=self.vehicle_batch.rows
                snapshot=json.loads(json.dumps(self.meta,ensure_ascii=False))
            atomic_json(self.folder/'session.json',snapshot)

    def add(self, sample):
        if sample['et'] == self.last_et:
            return False
        self.last_et = sample['et']
        elapsed = sample['et'] - self.origin
        self.batch.add([f'{elapsed:.6f}', datetime.now(timezone.utc).isoformat(),
                              f'{sample["et"]:.6f}', sample['lap'], f'{sample["distance"]:.3f}',
                              *[f'{v:.6f}' for v in sample['controls']], f'{sample["speed"]:.3f}',
                              f'{sample["lap_start"]:.6f}' if 'lap_start' in sample else '',
                              int(sample['lap_invalidated']) if 'lap_invalidated' in sample else '',
                              int(sample['in_pits']) if 'in_pits' in sample else '',
                              f'{sample["track_length"]:.3f}' if 'track_length' in sample else '',
                              *([f'{value:.3f}' for value in sample['position']]
                                if sample.get('position') is not None else ['','','']),
                              *[sample.get('conditions',{}).get(k,'') for k in EXTRA_COLUMNS]])
        if self.vehicle_batch:
            transition=self.vehicle_last_sample is not None and (any(sample.get(k)!=self.vehicle_last_sample.get(k) for k in ('lap_start','lap_invalidated','in_pits','finish')) or any(sample.get('vehicle_data',{}).get(k)!=self.vehicle_last_sample.get('vehicle_data',{}).get(k) for k in ('pit_state','speed_limiter')))
            if self.vehicle_last is None or sample['et']-self.vehicle_last>=1/self.vehicle_settings['record_hz']-1e-8 or transition:
                self.vehicle_batch.add(vehiclelab.sample_row({**sample,'vehicle':sample.get('vehicle_data',{})},self.origin))
                self.vehicle_last=sample['et']
            self.vehicle_last_sample=sample
        with self.meta_lock:
            self.samples += 1
            self.meta['duration_s'] = elapsed
            self.meta['effective_sample_hz'] = (self.samples - 1) / elapsed if elapsed > 0 else 0
        return True

    def finish(self, reason, failure=None):
        if self.file is None:
            return None
        error=failure
        try:self.meta['writer_stats']=self.batch.finish()
        except OSError as e:error=str(e)
        if self.vehicle_batch:
            try:
                if self.vehicle_last_sample and self.vehicle_last_sample['et']!=self.vehicle_last:
                    self.vehicle_batch.add(vehiclelab.sample_row({**self.vehicle_last_sample,'vehicle':self.vehicle_last_sample.get('vehicle_data',{})},self.origin))
            except OSError as e:error=str(e)
            try:self.meta['vehicle_writer_stats']=self.vehicle_batch.finish()
            except OSError as e:error=str(e)
        self.file = None
        self.meta.update(status='write_error' if error else 'complete', end_reason=error or reason,
                         ended_utc=datetime.now(timezone.utc).isoformat())
        self.save_meta()
        folder = self.folder
        # Reporting is independent from sampling and retains the full CSV.
        if not error:
            self.report_thread = threading.Thread(target=self._report, args=(folder,), daemon=False)
            self.pending_reports=[t for t in self.pending_reports if t.is_alive()]+[self.report_thread]
            self.report_thread.start()
        else:(folder/'report_error.txt').write_text(error,encoding='utf-8')
        return folder

    @staticmethod
    def _report(folder):
        try:
            make_report(folder)
        except Exception as error:
            (folder / 'report_error.txt').write_text(str(error), encoding='utf-8')
