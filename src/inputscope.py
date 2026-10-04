"""LMU input overlay and streaming session recorder. Local use only."""
import csv
import ctypes
import json
import math
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from sampling import (DEFAULTS, PRESETS, AdaptiveSampler, PreciseWait, FrameDeadline, drawing_rate,
                      load_settings, save_settings, validate_settings)
from laps import export_fastest, library_laps, write_compare, track_script
from reference import ReferenceLap, best_reference, DistanceAligner
from sessionlab import analyze_session,lap_conditions
from telemetry_import import import_recording
from storage import BatchWriter, StorageError, atomic_json, recover_session, compress_session
from diagnostics import Diagnostics
import vehiclelab
import endurance
from paths import ASSETS,data_directory,telemetry_directory

ROOT = data_directory()
ROOT.mkdir(parents=True,exist_ok=True)
COLORS = ('#34e59a', '#ff596b', '#52b5ff')
INPUT_CHANNELS = {'raw': (1, '原始'), 'filtered': (10, '游戏过滤后')}
POLL_HZ = DRAW_HZ = 120
COLUMNS = ('time_s', 'utc', 'session_time_s', 'lap', 'lap_distance_m', 'throttle', 'brake',
           'steering', 'filtered_throttle', 'filtered_brake', 'filtered_steering', 'speed_kmh',
           'lap_start_s','lap_invalidated','in_pits','track_length_m',
           'world_x_m','world_y_m','world_z_m')
EXTRA_COLUMNS=('fuel_l','tyre_compound','track_temp_c','wetness','tc_level','abs_level','tc_active','abs_active','gear')
COLUMNS=(*COLUMNS,*EXTRA_COLUMNS)


def steering_angle(value):
    """The requested 540 degree total visual lock is -270 left to +270 right."""
    return max(-1,min(1,value))*270


def rotate_wheel(points, cx, cy, scale, degrees):
    angle = math.radians(degrees)
    cosine,sine = math.cos(angle),math.sin(angle)
    return [coordinate for x,y in points for coordinate in
            (cx+scale*(x*cosine-y*sine),cy+scale*(x*sine+y*cosine))]


def hud_layout(w, h, clean=False, controls=False):
    s = min(w/640,h/228)
    if clean:
        if controls:
            s = min(w/600,h/100)
            panel = (w-170*s,2,w-2,h-2)
            px0 = panel[0]
            return dict(scale=s,plot=(2,px0-12*s,2,h-2),panel=panel,
                        pedals=((px0+8*s,8*s,px0+20*s,h-8*s),
                                (px0+32*s,8*s,px0+44*s,h-8*s)),
                        wheel=(px0+113*s,h/2,min(40*s,(h-12*s)/2)))
        return dict(scale=s,plot=(2,w-2,2,h-2),panel=None)
    panel = (w-194*s,89*s,w-14*s,h-27*s)
    x0,y0,x1,y1 = panel
    radius = min(36*s,(y1-y0-42*s)/2)
    return dict(scale=s,plot=(24*s,w-210*s,94*s,h-32*s),panel=panel,
                pedals=((x0+15*s,y0+25*s,x0+29*s,y1-23*s),
                        (x0+43*s,y0+25*s,x0+57*s,y1-23*s)),
                wheel=(x0+119*s,(y0+y1)/2,radius))


def pedal_fill(bounds, value):
    x0,y0,x1,y1 = bounds
    return (x0,y1-(y1-y0)*max(0,min(1,value)),x1,y1)


class WheelDisplay:
    """Cached vector interpretation of the Fanatec BMW M4 GT3 front face.

    Reference: Fanatec's official product photo, P_SW_BMW_GT3_H-01.webp.
    The open shoulders, side grips, flat bottom and three colored rotaries
    are drawn here; no vendor raster asset or image processing is needed.
    """
    def __init__(self, canvas, cx, cy, radius, background='#121d2b'):
        self.canvas,self.cx,self.cy,self.scale = canvas,cx,cy,radius/1.13
        self.parts = []
        self.angle = None
        canvas.tk.eval('''namespace eval ::inputscope {}
            proc ::inputscope::wheel_coords {canvas updates} {
                foreach coords $updates { $canvas coords {*}$coords }
            }''')
        def polygon(points,fill,outline='',smooth=False,width=1):
            item = canvas.create_polygon(*rotate_wheel(points,cx,cy,self.scale,0),
                                         fill=fill,outline=outline,smooth=smooth,
                                         splinesteps=12,width=width,tags='wheel')
            self.parts.append(('polygon',item,points))
        def line(points,color,width=1):
            item = canvas.create_line(*rotate_wheel(points,cx,cy,self.scale,0),
                                      fill=color,width=width,capstyle='round',tags='wheel')
            self.parts.append(('polygon',item,points))
        def circle(x,y,radius,fill,outline='',width=1):
            item = canvas.create_oval(0,0,1,1,fill=fill,outline=outline,width=width,tags='wheel')
            self.parts.append(('circle',item,(x,y,radius)))
        # The silhouette's grip and lower rim surround the carbon control plate.
        polygon([(-.83,-.66),(-.98,-.56),(-1.03,-.14),(-1.02,.23),(-.94,.55),
                 (-.79,.75),(-.45,.84),(0,.86),(.45,.84),(.79,.75),(.94,.55),
                 (1.02,.23),(1.03,-.14),(.98,-.56),(.83,-.66),(.38,-.42),
                 (0,-.40),(-.38,-.42)],'#0a1018','#657386',True)
        for sign in (-1,1):
            polygon([(sign*x,y) for x,y in ((.92,-.45),(1.02,-.15),(1,.25),
                     (.91,.51),(.78,.44),(.80,.10),(.76,-.19),(.80,-.43))],
                    '#252e3a','#465362',True)
            # Transparent-looking hand openings use the control card's solid tint.
            polygon([(sign*x,y) for x,y in ((.76,-.44),(.56,-.34),(.52,-.07),
                     (.69,-.04),(.82,-.13),(.84,-.31))],background,'',True)
            polygon([(sign*x,y) for x,y in ((.81,.11),(.64,.11),(.56,.37),
                     (.59,.52),(.73,.52),(.84,.33))],background,'',True)
            line([(sign*.97,-.17),(sign*.94,.18),(sign*.87,.36)],'#566271')
        polygon([(-.56,-.35),(-.36,-.40),(.36,-.40),(.56,-.35),(.55,.40),
                 (.43,.49),(0,.53),(-.43,.49),(-.55,.40)],'#17212e','#435164',True)
        polygon([(-.65,.61),(-.35,.55),(0,.59),(.35,.55),(.65,.61),
                 (.65,.70),(.35,.74),(0,.75),(-.35,.74),(-.65,.70)],background,'',True)
        # Twelve small backlit buttons, matching the reference's wing arrangement.
        for sign in (-1,1):
            for x,y,color in ((.76,-.53,'#4bb8ff'),(.61,-.46,'#4bb8ff'),
                              (.49,-.32,'#eed94c'),(.46,-.08,'#eed94c'),
                              (.48,.10,'#ff5677'),(.50,.27,'#ff5677')):
                circle(sign*x,y,.037,'#0c1725',color)
        for x,y,color in ((-.23,-.19,'#ff596b'),(.23,-.19,'#52b5ff'),(0,.34,'#34e59a')):
            circle(x,y,.135,'#0a121e',color,1.3)
            line([(x,y+.035),(x+.015,y-.095)],color,1.6)
        # Round central badge and tiny blue/white quadrants keep the front view legible.
        circle(0,.03,.115,'#d4dce7','#070d15')
        polygon([(0,.03),(0,-.05),(.08,-.05),(.08,.03)],'#3aa7e8')
        polygon([(0,.03),(0,.11),(-.08,.11),(-.08,.03)],'#3aa7e8')
        self.set_angle(0)

    def set_angle(self, angle):
        if angle == self.angle:
            return
        self.angle = angle
        radians = math.radians(angle)
        cosine,sine = math.cos(radians),math.sin(radians)
        updates = []
        for kind,item,points in self.parts:
            if kind == 'circle':
                x,y,r = points
                x,y = (self.cx+self.scale*(x*cosine-y*sine),
                       self.cy+self.scale*(x*sine+y*cosine))
                radius = r*self.scale
                coords = (x-radius,y-radius,x+radius,y+radius)
            else:
                coords = [coordinate for x,y in points for coordinate in
                          (self.cx+self.scale*(x*cosine-y*sine),
                           self.cy+self.scale*(x*sine+y*cosine))]
            updates.append((item,*coords))
        # One Tk bridge call per wheel, rather than releasing/reacquiring the GIL
        # for every button and grip at high telemetry rates.
        self.canvas.tk.call('::inputscope::wheel_coords',self.canvas._w,tuple(updates))


def reduce_trace(coords, tolerance=0.35):
    """Linear-time monotonic simplification, with a bounded vertical pixel error.

    Keep actual endpoints and vertical pedal edges. A recursive whole-line RDP
    search can become quadratic on high-rate flat/vertical input traces.
    """
    count = len(coords) // 2
    if count < 3:
        return coords
    output = list(coords[:2])
    ax, ay = px, py = coords[:2]
    low, high = -math.inf, math.inf
    def emit(x,y):
        if output[-2:] != [x,y]:
            output.extend((x,y))
    for index in range(1,count):
        x,y = coords[2*index:2*index+2]
        if x < px:
            return coords
        dx = x-ax
        if dx > 0 and not low <= (y-ay)/dx <= high:
            emit(px,py)
            ax,ay = px,py
            low,high = -math.inf,math.inf
            dx = x-ax
        if dx == 0:
            if y != ay:
                emit(px,py)
                emit(x,y)
                ax,ay = x,y
                low,high = -math.inf,math.inf
        else:
            low = max(low,(y-ay-tolerance)/dx)
            high = min(high,(y-ay+tolerance)/dx)
        px,py = x,y
    emit(px,py)
    return output


def decode(value):
    return bytes(value).split(b'\0', 1)[0].decode('utf-8', 'replace')


def extract(data):
    info = data.scoring.scoringInfo
    telemetry = data.telemetry
    if not info.mInRealtime or not telemetry.playerHasVehicle:
        return None
    count = min(104, max(0, int(info.mNumVehicles)))
    player = next((v for v in data.scoring.vehScoringInfo[:count] if v.mIsPlayer), None)
    if player is None:
        return None
    vehicles = telemetry.telemInfo[:min(104, int(telemetry.activeVehicles))]
    car = next((v for v in vehicles if v.mID == player.mID), None)
    if car is None or not math.isfinite(car.mElapsedTime):
        return None
    values = [float(getattr(car, 'm' + prefix + name))
              for prefix in ('Unfiltered', 'Filtered') for name in ('Throttle', 'Brake', 'Steering')]
    if not all(math.isfinite(v) for v in values):
        return None
    if any(abs(v) > 1.01 for v in values) or any(values[i] < -0.01 for i in (0, 1, 3, 4)):
        return None
    position = [float(getattr(car.mPos, axis)) for axis in ('x','y','z')]
    return {'track': decode(info.mTrackName), 'driver': decode(player.mDriverName),
            'vehicle': decode(car.mVehicleModel) or decode(car.mVehicleName), 'session': int(info.mSession),
            'player_id': int(player.mID), 'et': float(car.mElapsedTime),
            'lap': int(car.mLapNumber), 'distance': float(player.mLapDist),
            'controls': values, 'position':position if all(math.isfinite(v) for v in position) else None,
            'speed': math.sqrt(sum(float(getattr(car.mLocalVel, a)) ** 2
                                                      for a in ('x', 'y', 'z'))) * 3.6,
            'finish': int(player.mFinishStatus),
            'lap_start':float(car.mLapStartET),'lap_invalidated':bool(car.mLapInvalidated),
            'in_pits':bool(player.mInPits),'track_length':float(info.mLapDist),
            'conditions':{'fuel_l':float(car.mFuel) if math.isfinite(car.mFuel) and car.mFuel>=0 else '',
                'tyre_compound':int(car.mFrontTireCompoundIndex),
                'track_temp_c':float(info.mTrackTemp) if math.isfinite(info.mTrackTemp) else '',
                'wetness':float(info.mAvgPathWetness) if math.isfinite(info.mAvgPathWetness) and 0<=info.mAvgPathWetness<=1 else '',
                'tc_level':int(car.mTC),'abs_level':int(car.mABS),'tc_active':int(car.mTCActive),
                'abs_active':int(car.mABSActive),'gear':int(car.mGear)},
            'vehicle_data':vehiclelab.extract_vehicle(car,info,player)}


class SharedReader:
    """Open an EXISTING map with FILE_MAP_READ; never create or alter it."""
    def __init__(self, map_name='LMU_Data'):
        from pyLMUSharedMemory.lmu_data import LMUObjectOut
        self.structure = LMUObjectOut
        self.size = ctypes.sizeof(LMUObjectOut)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
        self.kernel.OpenFileMappingW.restype = ctypes.c_void_p
        self.kernel.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                            ctypes.c_uint32, ctypes.c_size_t]
        self.kernel.MapViewOfFile.restype = ctypes.c_void_p
        self.kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.OpenFileMappingW(4, False, map_name)
        if not self.handle:
            raise OSError('Waiting for LMU shared memory')
        self.pointer = self.kernel.MapViewOfFile(self.handle, 4, 0, 0, self.size)
        if not self.pointer:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise OSError('Cannot read LMU shared memory')
        self.cached_sample = None
        self.cached_at = 0

    def read(self):
        if (self.cached_sample is not None and time.monotonic()-self.cached_at < 0.25
                and self.cached_id.value == self.cached_sample['player_id']
                and self.cached_et.value == self.cached_sample['et'] and self.cached_realtime.value):
            return self.cached_sample
        # Discard a snapshot if the producer changed it while it was copied.
        for _ in range(3):
            a = ctypes.string_at(self.pointer, self.size)
            b = ctypes.string_at(self.pointer, self.size)
            if a == b:
                data = self.structure.from_buffer_copy(a)
                sample = extract(data)
                self.cached_sample = sample
                self.cached_at = time.monotonic()
                if sample is not None:
                    index = next(i for i,car in enumerate(data.telemetry.telemInfo[:104])
                                 if car.mID == sample['player_id'])
                    telem_type, car_type = type(data.telemetry), type(data.telemetry.telemInfo[0])
                    address = (self.pointer+self.structure.telemetry.offset+telem_type.telemInfo.offset
                               +index*ctypes.sizeof(car_type))
                    fields = {entry[0]:entry[1] for entry in car_type._fields_}
                    self.cached_id = fields['mID'].from_address(address+car_type.mID.offset)
                    self.cached_et = fields['mElapsedTime'].from_address(address+car_type.mElapsedTime.offset)
                    score_type, info_type = type(data.scoring), type(data.scoring.scoringInfo)
                    address = self.pointer+self.structure.scoring.offset+score_type.scoringInfo.offset
                    field = next(entry[1] for entry in info_type._fields_ if entry[0]=='mInRealtime')
                    self.cached_realtime = field.from_address(address+info_type.mInRealtime.offset)
                return sample
        return None

    def close(self):
        if getattr(self, 'pointer', None):
            self.kernel.UnmapViewOfFile(self.pointer)
            self.pointer = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def make_report(folder):
    try:analyze_session(folder)
    except Exception as e:(folder/'analysis_error.txt').write_text(str(e),encoding='utf-8')
    try:endurance.analyze(folder)
    except Exception as e:(folder/'endurance_error.txt').write_text(str(e),encoding='utf-8')
    fastest = None
    try:
        library = folder.parent
        _,fastest = export_fastest(folder,ASSETS/'compare.html',library)
        if library in (ROOT/'Logs',ROOT/'DemoLogs',ROOT/'ImportedLogs'):
            selection = library_laps(library)
            write_compare(ROOT/('DemoFastestLapCompare.html' if library.name=='DemoLogs' else
                               'FastestLapCompare.html'),ASSETS/'compare.html',selection)
    except Exception as error:
        (folder/'fastest_lap_error.txt').write_text(str(error),encoding='utf-8')
    render_review(folder, fastest)


def render_review(folder, fastest=None):
    """Upgrade a review page without rewriting its CSV or lap exports."""
    template = (ASSETS / 'report.html').read_text(encoding='utf-8')
    template = template.replace('/*TRACK_VIEW_JS*/', track_script(ASSETS))
    template = template.replace('/*VEHICLE_VIEW_JS*/',vehiclelab.script(ASSETS))
    template = template.replace('/*ENDURANCE_VIEW_JS*/',(ASSETS/'enduranceview.js').read_text(encoding='utf-8'))
    metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    # Embed the CSV as text, not as hundreds of thousands of JSON objects.
    payload = json.dumps({'meta': metadata, 'fastest':fastest,
                         'analysis':json.loads((folder/'session_analysis.json').read_text(encoding='utf-8')) if (folder/'session_analysis.json').exists() else None,
                         'native_channels':json.loads((folder/'native_channels.json').read_text(encoding='utf-8')) if (folder/'native_channels.json').exists() else None,
                         'vehicle_telemetry':vehiclelab.load_recording(folder),
                         'endurance':json.loads((folder/'endurance_analysis.json').read_text(encoding='utf-8')) if (folder/'endurance_analysis.json').exists() else None,
                         'csv': (folder / 'inputs.csv').read_text(encoding='utf-8')},
                         ensure_ascii=False).replace('<', '\\u003c')
    (folder / 'review.html').write_text(template.replace('/*SESSION_DATA*/null', payload), encoding='utf-8')


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
        self.folder = self.output / (datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f') + '_' + safe)
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
        self.points = deque(maxlen=80001)
        self.reference = None
        self.reference_enabled = False
        self.reference_points = deque(maxlen=24001)
        self.reference_latest = None
        self.reference_revision = 0
        self.aligner = DistanceAligner()
        self.reference_state = {'mode':'关闭','confidence':0}
        self.diagnostics = Diagnostics()
        self.plot_points = deque(maxlen=80001)
        self.plot_hz = math.ceil(592*4/10)
        self.plot_y_scale = 102*4
        self.plot_revision = 0
        self.sample_times = deque(maxlen=12001)
        self.poll_times = deque(maxlen=12001)
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
                polls = [t for t in self.poll_times if now-t <= horizon]
                fresh = [t for t in self.sample_times if now-t <= horizon]
            def rate(values):
                return (len(values)-1)/(values[-1]-values[0]) if len(values)>1 else 0
            self._rates = (rate(polls), rate(fresh))
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
                    self.poll_times.append(now)
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
                    if self.recorder.file is None and ended_key != key and sample['finish'] == 0 and fresh:
                        self.recorder.start(sample, config, self.target_hz)
                        self.recorder.meta['vehicle_strategy']['started_at_s']=(self.fuel_planner.baseline_et if self.fuel_planner.baseline_et is not None else sample['et'])-sample['et']
                        self.session_missed_base = self.missed_cycles
                    if self.recorder.file is not None and fresh:
                        self.recorder.set_sampling(config, self.target_hz, sample['et']-self.recorder.origin)
                        with self.recorder.meta_lock:self.recorder.meta['missed_poll_cycles'] = self.missed_cycles - self.session_missed_base
                        self.recorder.add(sample)
                    with self.lock:
                        if fresh:
                            self.endurance_monitor.update({**sample,'vehicle_name':sample['vehicle'],'vehicle':sample.get('vehicle_data',{})})
                            self.fuel_planner.update({**sample,'vehicle_name':sample['vehicle'],'vehicle':sample.get('vehicle_data',{})})
                            self.vehicle_latest=sample.get('vehicle_data')
                            self.vehicle_estimate=self.fuel_planner.estimate({**sample,'vehicle':sample.get('vehicle_data',{})})
                            self.add_plot_point(now, sample['controls'])
                            aligned=self.aligner.update(sample,self.reference) if self.reference_enabled else None
                            self.reference_state=self.aligner.state if self.reference_enabled else {'mode':'关闭','confidence':0}
                            reference_sample=dict(sample)
                            if aligned is not None:
                                reference_sample['distance']=aligned/self.reference.length*sample['track_length']
                                reference_sample['conditions']=self.reference_state['matching_conditions']
                            self.reference_latest = self.reference.sample(reference_sample) if aligned is not None else None
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
                            self.sample_times.append(now)
                        self.latest = sample
                    if fresh:
                        self.status = ('DEMO' if self.demo else 'REC') + ' · ' + sample['track']
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


class App:
    def __init__(self, demo=False, clean=False, clean_controls=False):
        self.root = tk.Tk()
        self.root.title('LMU StintLab' + (' · DEMO' if demo else ''))
        self.root.geometry('640x228+70+70')
        self.root.minsize(440, 160)
        self.root.overrideredirect(True)
        self.root.configure(bg='#0c111a')
        self.top = tk.BooleanVar(value=True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 1.0)
        self.clickthrough = False
        self.f7_down = False
        self.f6_down = False
        self.f8_down = False
        self.f9_down = False
        self.f10_down = False
        self.f11_down = False
        self.settings = load_settings(ROOT / 'settings.json')
        self.vehicle_settings=vehiclelab.load_settings(ROOT/'vehicle_settings.json')
        self.endurance_settings=endurance.load_settings(ROOT/'endurance_settings.json')
        for kind in ('pit','stint','weather'):setattr(self,kind+'_on',tk.BooleanVar(value=self.endurance_settings[kind+'_enabled']))
        self.tyres_on=tk.BooleanVar(value=self.vehicle_settings['tyres_enabled'])
        self.strategy_on=tk.BooleanVar(value=self.vehicle_settings['strategy_enabled'])
        try:
            self.reference_settings = json.loads((ROOT/'reference_settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):
            self.reference_settings = dict(enabled=False,automatic=True,path='')
        self.reference_on = tk.BooleanVar(value=bool(self.reference_settings.get('enabled',False)))
        self.reference_auto = tk.BooleanVar(value=bool(self.reference_settings.get('automatic',True)))
        self.reference_loading = False
        self.reference_generation = 0
        self.reference_scan_at = 0
        self.reference_match_key = None
        self.reference_message = ''
        self.reference_kind = tk.StringVar(value=self.reference_settings.get('kind','fastest'))
        self.reference_locked = tk.BooleanVar(value=bool(self.reference_settings.get('locked',False)))
        self.input_channel = tk.StringVar(value=self.settings['input_channel'])
        self.settings_dialog = None
        self.hud_mode = tk.StringVar(value='normal')
        self.applied_hud_mode = 'normal'
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.user32.GetParent.argtypes = [ctypes.c_void_p]
        self.user32.GetParent.restype = ctypes.c_void_p
        self.user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        self.drag_origin = None
        def begin_drag(event):
            scale = min(self.canvas.winfo_width()/640, self.canvas.winfo_height()/228)
            if self.hud_mode.get() == 'normal' and event.y < 32*scale:
                if event.x > self.canvas.winfo_width() - 36*scale:
                    self.close()
                    return
                if event.x > self.canvas.winfo_width() - 76*scale:
                    menu.tk_popup(event.x_root, event.y_root)
                    return
            self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())
        def move_drag(event):
            if self.drag_origin:
                x, y = event.x_root - self.drag_origin[0], event.y_root - self.drag_origin[1]
                self.root.geometry(f'{x:+d}{y:+d}')
        menu = tk.Menu(self.root, tearoff=False, bg='#172236', fg='#eef4ff')
        menu.add_command(label='打开记录', command=self.open_logs)
        menu.add_command(label='打开 CSV 复盘', command=self.review_csv)
        menu.add_command(label='最快圈曲线对比', command=self.open_fastest_compare)
        menu.add_command(label='比赛记录管理 / 稳定性分析',command=self.show_library)
        menu.add_command(label='性能诊断 / 实赛测量',command=self.show_diagnostics)
        menu.add_command(label='导入官方 DuckDB 比赛记录（只读）', command=self.import_native_dialog)
        menu.add_checkbutton(label='比赛中最快圈参考（F6）',variable=self.reference_on,command=self.apply_reference)
        menu.add_checkbutton(label='自动匹配同车同赛道最快圈',variable=self.reference_auto,command=self.apply_reference)
        menu.add_command(label='手动选择参考圈 .lap.json',command=self.select_reference)
        menu.add_checkbutton(label='锁定当前参考圈',variable=self.reference_locked,command=self.apply_reference)
        menu.add_radiobutton(label='参考类型：最快完整圈',variable=self.reference_kind,value='fastest',command=self.apply_reference)
        menu.add_radiobutton(label='参考类型：典型稳定圈（至少 3 圈）',variable=self.reference_kind,value='stable',command=self.apply_reference)
        menu.add_command(label='演示 / 真实遥测', command=self.toggle_demo)
        menu.add_command(label='采样与刷新设置（F10）', command=self.show_sampling_settings)
        vehicle_menu=tk.Menu(menu,tearoff=False,bg='#172236',fg='#eef4ff')
        vehicle_menu.add_checkbutton(label='四轮轮胎 HUD',variable=self.tyres_on,command=lambda:self.vehicle_panels.toggle('tyres'))
        vehicle_menu.add_checkbutton(label='燃油与能量 HUD',variable=self.strategy_on,command=lambda:self.vehicle_panels.toggle('strategy'))
        vehicle_menu.add_command(label='车型阈值与策略设置',command=lambda:self.vehicle_panels.settings_dialog())
        menu.add_cascade(label='轮胎与燃油 / 能量',menu=vehicle_menu)
        endurance_menu=tk.Menu(menu,tearoff=False,bg='#172236',fg='#eef4ff')
        for kind,label in [('pit','进站分析 HUD'),('stint','Stint 长距离 HUD'),('weather','天气与赛道 HUD')]:
            endurance_menu.add_checkbutton(label=label,variable=getattr(self,kind+'_on'),command=lambda k=kind:self.endurance_panels.toggle(k))
        endurance_menu.add_command(label='进站 / Stint / 天气设置',command=lambda:self.endurance_panels.settings_dialog())
        menu.add_cascade(label='进站 / Stint / 天气',menu=endurance_menu)
        menu.add_separator()
        for label,channel in (('输入：原始（F7 切换）','raw'),
                              ('输入：游戏过滤后（F7 切换）','filtered')):
            menu.add_radiobutton(label=label,variable=self.input_channel,value=channel,
                                 command=self.apply_input_channel)
        menu.add_separator()
        for label,mode in (('普通面板','normal'),('纯净：仅曲线（F9）','curves'),
                           ('纯净：曲线＋踏板/方向盘（F11）','controls')):
            menu.add_radiobutton(label=label,variable=self.hud_mode,value=mode,
                                 command=self.apply_clean_mode)
        menu.add_separator()
        self.window = tk.StringVar(value='10')
        for seconds in ('5', '10', '20'):
            menu.add_radiobutton(label=seconds + ' 秒波形', variable=self.window, value=seconds)
        menu.add_separator()
        menu.add_command(label='小面板 440 × 170', command=lambda: self.root.geometry('440x170'))
        menu.add_command(label='标准面板 640 × 228', command=lambda: self.root.geometry('640x228'))
        menu.add_command(label='高清面板 840 × 300', command=lambda: self.root.geometry('840x300'))
        for opacity in (0.75, 0.90, 1.0):
            menu.add_command(label=f'不透明度 {int(opacity * 100)}%',
                             command=lambda value=opacity: self.root.attributes('-alpha', value))
        menu.add_command(label='鼠标穿透 / 解锁（F8）', command=self.toggle_clickthrough)
        self.canvas = tk.Canvas(self.root, bg='#0c111a', highlightthickness=0)
        self.canvas.bind('<Button-1>', begin_drag)
        self.canvas.bind('<B1-Motion>', move_drag)
        self.canvas.bind('<Button-3>', lambda event: menu.tk_popup(event.x_root, event.y_root))
        self.canvas.pack(fill='both', expand=True)
        self.chrome_key = None
        self.trace_key = None
        self.trace_expiry = 0
        self.live_key = None
        self.live_items = {}
        self.wheel_display = None
        self.root.update_idletasks()
        handle = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = self.user32.GetWindowLongW(handle, -20)
        self.user32.SetWindowLongW(handle, -20, (style | 0x40000) & ~0x80)
        self.user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        self.gdi32 = ctypes.WinDLL('gdi32')
        self.gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        self.gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
        self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self.render_wake = threading.Event()
        self.engine = Engine(demo, settings=self.settings, rate_wake=self.render_wake,vehicle_settings=self.vehicle_settings,endurance_settings=self.endurance_settings)
        self.engine.diagnostics_gui = True
        self.diagnostics = self.engine.diagnostics
        self.engine.reference_enabled = self.reference_on.get()
        self.draw_times = deque(maxlen=12001)
        self._draw_rate = 0
        self._draw_rate_at = -math.inf
        self.closing = False
        from vehiclehud import Panels
        self.vehicle_panels=Panels(self,ROOT)
        from endurancehud import Panels as EndurancePanels
        self.endurance_panels=EndurancePanels(self,ROOT)
        self.render_clock = FrameDeadline(time.perf_counter())
        self.render_stop = threading.Event()
        self.render_waiter = PreciseWait(self.render_stop,self.render_wake)
        self.draw_job = None
        self.drawing = False
        self.gui_yield_at = time.perf_counter()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        if clean or clean_controls:
            self.hud_mode.set('controls' if clean_controls else 'curves')
            self.apply_clean_mode()
        self.draw()
        self.root.after(25,self.poll_keys)
        self.root.after(500,self.refresh_reference)

    def apply_reference(self):
        self.reference_generation += 1
        if self.reference_locked.get() and self.engine.reference:self.reference_settings['path']=self.engine.reference.path
        self.reference_settings.update(enabled=self.reference_on.get(),automatic=self.reference_auto.get(),
            kind=self.reference_kind.get(),locked=self.reference_locked.get())
        (ROOT/'reference_settings.json').write_text(json.dumps(self.reference_settings,ensure_ascii=False,indent=2),encoding='utf-8')
        with self.engine.lock:
            self.engine.reference_enabled = self.reference_on.get()
            self.engine.reference_points.clear()
            self.engine.reference_latest = None
            self.engine.reference_revision += 1
            self.engine.aligner=DistanceAligner()
        self.reference_match_key = None
        self.trace_key = None

    def toggle_reference(self):
        self.reference_on.set(not self.reference_on.get())
        self.apply_reference()

    def select_reference(self):
        path = filedialog.askopenfilename(title='选择完整参考圈',initialdir=ROOT/'Logs',filetypes=[('InputScope fastest lap','*.lap.json')])
        if not path:return
        try:
            reference = ReferenceLap.load(path)
        except Exception as error:
            messagebox.showerror('参考圈读取失败',str(error));return
        self.reference_auto.set(False)
        self.reference_locked.set(True)
        self.reference_on.set(True)
        self.reference_settings['path'] = path
        with self.engine.lock:self.engine.reference = reference
        self.apply_reference()

    def refresh_reference(self):
        if self.closing:return
        with self.engine.lock:
            sample = self.engine.latest
            if sample:sample=dict(sample,conditions=self.engine.aligner.match_conditions(sample))
        key = (sample.get('track'),sample.get('vehicle'),sample.get('track_length')) if sample else None
        if self.reference_on.get() and not self.reference_loading and (self.reference_match_key != key or
                sample and self.reference_auto.get() and not self.reference_locked.get() and time.monotonic()>=self.reference_scan_at):
            self.reference_match_key = key
            automatic = self.reference_auto.get() and not self.reference_locked.get()
            kind = self.reference_kind.get()
            path = self.reference_settings.get('path','')
            self.reference_loading = True
            self.reference_scan_at = time.monotonic()+10
            generation = self.reference_generation
            engine = self.engine
            with engine.lock:current = engine.reference
            def load():
                try:
                    reference = best_reference(ROOT,sample,current,kind) if automatic and sample else ReferenceLap.load(path) if not automatic and path else None
                    message = '无匹配参考圈' if reference is None else ''
                except Exception as error:reference,message = None,str(error)
                if self.closing:return
                def done():
                    self.reference_loading = False
                    if engine is not self.engine or key != self.reference_match_key or generation!=self.reference_generation:return
                    with engine.lock:
                        if engine.reference is not reference:
                            engine.reference = reference
                            engine.reference_points.clear()
                            engine.reference_latest = None
                            engine.reference_revision += 1
                            engine.aligner=DistanceAligner()
                    self.reference_message = message
                self.root.after(0,done)
            threading.Thread(target=load,daemon=True).start()
        self.root.after(1000,self.refresh_reference)

    def import_native_dialog(self):
        path = filedialog.askopenfilename(title='只读导入已结束的 LMU DuckDB 记录',
            initialdir=telemetry_directory(),
            filetypes=[('LMU native telemetry','*.duckdb')])
        if not path:return
        dialog=tk.Toplevel(self.root);dialog.title('官方日志导入');dialog.geometry('490x285');dialog.attributes('-topmost',True)
        tk.Label(dialog,text='源数据库只读，输出保存在 InputScope / ImportedLogs。\n可留空使用日志内元数据；圈长未知时只做估算。',justify='left').pack(padx=12,pady=12)
        fields={}
        for key,label in (('track','赛道（可选）'),('vehicle','车辆（可选）'),('driver','车手（可选）'),('track_length','圈长 m（可选）')):
            row=tk.Frame(dialog);row.pack(fill='x',padx=12,pady=3);tk.Label(row,text=label,width=18,anchor='w').pack(side='left');v=tk.StringVar();tk.Entry(row,textvariable=v).pack(side='left',fill='x',expand=True);fields[key]=v
        status=tk.Label(dialog,text='',wraplength=460,justify='left');status.pack(pady=8)
        def begin():
            values={k:v.get().strip() for k,v in fields.items() if v.get().strip()}
            if 'track_length' in values:
                try:
                    length=float(values['track_length'])
                    if not math.isfinite(length) or not 100<length<100000:raise ValueError()
                except ValueError:status.config(text='圈长应为 100–100000 m 之间的数字');return
            button.config(state='disabled');status.config(text='正在只读导入并生成完整复盘 / 最快圈…')
            def run():
                try:
                    folder=import_recording(path,ROOT,values);make_report(folder)
                    error=None
                except Exception as e:folder,error=None,str(e)
                if self.closing:return
                def done():
                    if not dialog.winfo_exists():return
                    button.config(state='normal')
                    if error:status.config(text=error)
                    else:
                        dialog.destroy();self.reference_match_key=None;os.startfile(folder/'review.html')
                self.root.after(0,done)
            threading.Thread(target=run,daemon=True).start()
        button=tk.Button(dialog,text='开始导入',command=begin);button.pack()

    def drawing_target(self):
        return drawing_rate(self.settings,self.engine.target_hz)

    def actual_draw_rate(self):
        now = time.monotonic()
        if now-self._draw_rate_at >= 0.25:
            horizon = max(2.5,2.5/self.drawing_target())
            times = [t for t in self.draw_times if now-t<=horizon]
            self._draw_rate = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0
            self._draw_rate_at = now
        return self._draw_rate

    def toggle_clean(self, with_controls=False):
        mode = 'controls' if with_controls else 'curves'
        self.hud_mode.set('normal' if self.hud_mode.get()==mode else mode)
        self.apply_clean_mode()

    def toggle_input_channel(self):
        self.input_channel.set('filtered' if self.input_channel.get()=='raw' else 'raw')
        self.apply_input_channel()

    def apply_input_channel(self):
        checked = dict(self.settings, input_channel=self.input_channel.get())
        # This is a HUD preference only. Do not reset the sampler or recorder.
        self.settings = checked
        try:
            save_settings(ROOT/'settings.json', checked)
        except OSError as error:
            messagebox.showerror('无法保存输入通道', '本次切换已生效，但无法保存下次启动的选项：\n'+str(error))
        # An explicit switch remains responsive even at a 1 Hz drawing target.
        self.trace_key = None
        self.render_wake.set()
        if not self.drawing:
            if self.draw_job is not None:
                self.root.after_cancel(self.draw_job)
            self.draw_job = self.root.after_idle(self.queue_draw)

    def apply_clean_mode(self):
        mode = self.hud_mode.get()
        if mode == self.applied_hud_mode:
            return
        was_clean = self.applied_hud_mode != 'normal'
        self.canvas.pack_forget()
        if mode != 'normal':
            if not was_clean:
                self.normal_size = (self.root.winfo_width(), self.root.winfo_height())
                self.normal_opacity = self.root.attributes('-alpha')
            self.root.minsize(*( (320,80) if mode=='controls' else (240,60) ))
            self.root.geometry('600x100' if mode=='controls' else '440x100')
            self.root.configure(bg='#000000')
            self.root.attributes('-alpha', 1.0)
            self.canvas.configure(bg='#000000')
            self.canvas.pack(fill='both', expand=True)
        else:
            self.root.minsize(440, 160)
            width, height = self.normal_size
            self.root.geometry(f'{width}x{height}')
            self.root.configure(bg='#0c111a')
            self.root.attributes('-alpha', self.normal_opacity)
            self.canvas.configure(bg='#0c111a')
            self.canvas.pack(fill='both', expand=True)
        self.applied_hud_mode = mode
        self.chrome_key = None

    def toggle_clickthrough(self):
        self.root.update_idletasks()
        window = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = self.user32.GetWindowLongW(window, -20)
        self.clickthrough = not self.clickthrough
        style = (style | 0x80000 | 0x20) if self.clickthrough else (style & ~0x20)
        self.user32.SetWindowLongW(window, -20, style)

    def open_logs(self):
        path = self.engine.last_folder or self.engine.recorder.output
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def show_library(self):
        from management import show_library
        show_library(self,ROOT,render_review,make_report)

    def show_diagnostics(self):
        from management import show_diagnostics
        show_diagnostics(self,ROOT)

    def open_fastest_compare(self):
        demo = self.engine.demo
        path = ROOT/('DemoFastestLapCompare.html' if demo else 'FastestLapCompare.html')
        def prepare():
            try:
                write_compare(path,ASSETS/'compare.html',
                              library_laps(ROOT/('DemoLogs' if demo else 'Logs')))
                os.startfile(str(path))
            except Exception as error:
                text = str(error)
                self.root.after(0,lambda:messagebox.showerror('最快圈对比',text))
        threading.Thread(target=prepare,daemon=True).start()

    def toggle_demo(self):
        if self.engine.recorder.file and not self.engine.demo:
            messagebox.showinfo('记录中', '请先结束当前真实记录，再切换演示。')
            return
        demo = not self.engine.demo
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        if self.engine.thread.is_alive():
            return
        self.engine = Engine(demo, settings=self.settings, rate_wake=self.render_wake,vehicle_settings=self.vehicle_settings,endurance_settings=self.endurance_settings)
        self.diagnostics=self.engine.diagnostics
        self.engine.reference_enabled = self.reference_on.get()
        self.reference_match_key = None
        self.render_wake.set()
        self.root.title('LMU StintLab' + (' · DEMO' if demo else ''))

    def show_sampling_settings(self):
        if self.settings_dialog and self.settings_dialog.winfo_exists():
            self.settings_dialog.lift()
            return
        dialog = tk.Toplevel(self.root)
        self.settings_dialog = dialog
        dialog.title('InputScope · 采样与刷新设置')
        dialog.configure(bg='#111a29')
        dialog.attributes('-topmost', True)
        dialog.resizable(False, False)
        panel = tk.Frame(dialog, bg='#111a29', padx=22, pady=18)
        panel.pack(fill='both', expand=True)
        tk.Label(panel,text='采样与刷新',bg='#111a29',fg='#eef4ff',font=('Segoe UI',15,'bold')).grid(row=0,column=0,columnspan=2,sticky='w')
        variables = {key:tk.StringVar(value=str(value)) for key,value in self.settings.items()
                     if key != 'input_channel'}
        modes = tk.Frame(panel,bg='#111a29')
        modes.grid(row=1,column=0,columnspan=2,sticky='w',pady=(10,6))
        inputs = {}
        def mode_changed():
            dynamic = variables['mode'].get()=='dynamic'
            for key,widget in inputs.items():
                enabled = ((key=='draw_hz' and variables['draw_mode'].get()=='manual')
                           or (key=='fixed_hz' and not dynamic)
                           or (key not in ('draw_hz','fixed_hz') and dynamic))
                widget.configure(state='normal' if enabled else 'disabled')
        for text,value in (('固定采样','fixed'),('动态采样','dynamic')):
            tk.Radiobutton(modes,text=text,value=value,variable=variables['mode'],command=mode_changed,
                           bg='#111a29',fg='#dce7f8',selectcolor='#26364f',activebackground='#111a29',activeforeground='#ffffff').pack(side='left',padx=(0,15))
        for row,(key,label,maximum,increment) in enumerate((
                ('fixed_hz','固定目标（1–4000 Hz）',4000,1),
                ('min_hz','动态最低（1–4000 Hz）',4000,1),
                ('max_hz','动态最高（1–4000 Hz）',4000,1),
                ('change_pct_s','变化阈值（百分点 / 秒）',10000,0.1),
                ('hold_s','降频延迟（秒）',30,0.1),
                ('brake_pct','刹车升频（%，0 为关闭）',100,1),
                ('draw_hz','手动 HUD 绘制（1–4000 Hz）',4000,1)), start=3):
            tk.Label(panel,text=label,bg='#111a29',fg='#becde3',anchor='w').grid(row=row,column=0,sticky='w',pady=5,padx=(0,28))
            entry = tk.Spinbox(panel,textvariable=variables[key],from_=0 if key=='brake_pct' else 0.1 if key in ('hold_s','change_pct_s') else 1,
                               to=maximum,increment=increment,width=12,bg='#24334b',fg='#f4f7ff',insertbackground='#ffffff',
                               disabledbackground='#182233',disabledforeground='#62748e',buttonbackground='#35465e',relief='flat')
            entry.grid(row=row,column=1,sticky='e',pady=5)
            inputs[key] = entry
        presets = tk.Frame(panel,bg='#111a29')
        presets.grid(row=2,column=0,columnspan=2,sticky='w',pady=(0,8))
        def preset(name):
            for key,value in PRESETS[name].items():
                variables[key].set(str(value))
            mode_changed()
        for name in PRESETS:
            tk.Button(presets,text=name+'预设',command=lambda value=name:preset(value),bg='#26364f',fg='#dce7f8',relief='flat',padx=10).pack(side='left',padx=(0,7))
        tk.Checkbutton(panel,text='HUD 绘制跟随采样频率（推荐）',variable=variables['draw_mode'],
                       onvalue='sync',offvalue='manual',command=mode_changed,
                       bg='#111a29',fg='#dce7f8',selectcolor='#26364f',activebackground='#111a29',
                       activeforeground='#ffffff').grid(row=10,column=0,columnspan=2,sticky='w',pady=(7,0))
        info = tk.Label(panel,text='',bg='#111a29',fg='#52b5ff',justify='left',anchor='w')
        info.grid(row=11,column=0,columnspan=2,sticky='w',pady=(13,5))
        tk.Label(panel,text='同步模式：HUD 与采样目标一起升降频，无 240 Hz 上限。\n实际新数据受游戏限制，可见帧率受显示器和系统性能限制。\n动态模式：输入变化或刹车升频，平稳后延迟降频。',
                 bg='#111a29',fg='#8fa2be',justify='left',anchor='w').grid(row=12,column=0,columnspan=2,sticky='w',pady=(2,12))
        error = tk.Label(panel,text='',bg='#111a29',fg='#ff8194',wraplength=400,justify='left')
        error.grid(row=13,column=0,columnspan=2,sticky='w')
        def mark_pending(*_):
            error.configure(text='参数已修改，点击“应用并保存”生效。',fg='#e8bf7e')
        for variable in variables.values():
            variable.trace_add('write',mark_pending)
        def apply():
            try:
                checked = validate_settings(dict({key:var.get() for key,var in variables.items()},
                                                 input_channel=self.input_channel.get()))
                save_settings(ROOT/'settings.json', checked)
                self.settings = checked
                self.engine.update_settings(checked)
                error.configure(text='已应用并保存；采集不中断。',fg='#34e59a')
            except (ValueError,OSError) as problem:
                error.configure(text=str(problem),fg='#ff8194')
        actions = tk.Frame(panel,bg='#111a29')
        actions.grid(row=14,column=0,columnspan=2,sticky='e',pady=(10,0))
        tk.Button(actions,text='关闭',command=dialog.destroy,bg='#26364f',fg='#dce7f8',relief='flat',padx=16).pack(side='left',padx=6)
        tk.Button(actions,text='应用并保存',command=apply,bg='#315a84',fg='#ffffff',relief='flat',padx=16).pack(side='left')
        def refresh():
            if not dialog.winfo_exists():
                return
            poll, fresh = self.engine.actual_rates()
            draw = self.actual_draw_rate()
            info.configure(text=f'采样目标 {self.engine.target_hz} / 绘制目标 {self.drawing_target()} Hz  ·  {self.engine.reason}\n实际轮询 {poll:.1f}  /  新数据 {fresh:.1f}  /  绘制 {draw:.1f} Hz')
            dialog.after(250,refresh)
        mode_changed()
        refresh()

    def review_csv(self):
        path = filedialog.askopenfilename(title='打开完整输入记录', initialdir=str(self.engine.recorder.output),
                                          filetypes=[('Input CSV', 'inputs.csv')])
        if path:
            try:
                make_report(Path(path).parent)
                os.startfile(str(Path(path).parent / 'review.html'))
            except Exception as error:
                messagebox.showerror('无法打开记录', str(error))

    def rounded(self, x0, y0, x1, y1, radius=12, **options):
        r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
        return self.canvas.create_polygon(
            x0+r,y0, x1-r,y0, x1,y0, x1,y0+r, x1,y1-r, x1,y1,
            x1-r,y1, x0+r,y1, x0,y1, x0,y1-r, x0,y0+r, x0,y0,
            smooth=True, splinesteps=24, **options)

    def paint_chrome(self, w, h, clean, controls=False):
        """Cache vector glass surfaces outside the live refresh path."""
        key = (w, h, clean, controls)
        if key == self.chrome_key:
            return
        self.chrome_key = key
        c = self.canvas
        c.delete('chrome')
        s = min(w/640, h/228)
        handle = self.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        if clean:
            self.user32.SetWindowRgn(handle, None, True)
            if controls:
                for bounds in hud_layout(w,h,True,True)['pedals']:
                    c.create_rectangle(*bounds,fill='#111820',outline='#273748',tags='chrome')
                c.tag_lower('chrome')
            return
        region = self.gdi32.CreateRoundRectRgn(0, 0, w+1, h+1, round(32*s), round(32*s))
        if region and not self.user32.SetWindowRgn(handle, region, True):
            self.gdi32.DeleteObject(region)
        # Soft glass tint and a cool upper reflection, kept opaque for legibility.
        for step in range(48):
            t = step / 47
            rgb = tuple(round(a * (1-t) + b * t) for a, b in zip((44,57,76), (13,20,32)))
            color = '#%02x%02x%02x' % rgb
            c.create_rectangle(0, step*h/48, w, (step+1)*h/48+1,
                               fill=color, outline='', tags='chrome')
        self.rounded(1, 1, w-1, h-1, 16*s, fill='', outline='#708199', width=1, tags='chrome')
        c.create_line(23*s, 1, w-23*s, 1, fill='#b0bed0', tags='chrome')
        c.create_text(18*s, 18*s, text='INPUTSCOPE', fill='#f1f5fb', anchor='w',
                      font=('Segoe UI', -max(10,round(12*s)), 'bold'), tags='chrome')
        self.rounded(w-74*s, 7*s, w-40*s, 29*s, 10*s, fill='#39465a', outline='#59667b', tags='chrome')
        c.create_text(w-57*s, 17*s, text='•••', fill='#e4ecf8', font=('Segoe UI', -round(13*s)), tags='chrome')
        c.create_text(w-22*s, 17*s, text='×', fill='#aab9cf', font=('Segoe UI', -round(18*s)), tags='chrome')
        card_width = (w-44*s)/3
        for lane, (name, tint, color) in enumerate(zip(('THROTTLE / 油门', 'BRAKE / 刹车', 'STEERING / 转向'),
                                                     ('#263f3d','#44353f','#2b3d52'), COLORS)):
            x = 14*s + lane*(card_width+8*s)
            self.rounded(x, 37*s, x+card_width, 82*s, 12*s, fill=tint, outline='#526174', tags='chrome')
            c.create_line(x+12*s, 38*s, x+card_width-12*s, 38*s, fill='#6b7c8b', tags='chrome')
            c.create_oval(x+10*s, 47*s, x+15*s, 52*s, fill=color, outline='', tags='chrome')
            c.create_text(x+21*s, 50*s, text=name if w>=560 else ('油门','刹车','转向')[lane],
                          fill='#c1cbda', anchor='w', font=('Segoe UI', -max(9,round(10*s))), tags='chrome')
        layout = hud_layout(w,h)
        x0,x1,y0,y1 = layout['plot']
        self.rounded(14*s,89*s,x1+10*s,h-27*s,12*s,fill='#121d2b',outline='#42516a',tags='chrome')
        c.create_line(28*s,90*s,x1-4*s,90*s,fill='#6a7d95',tags='chrome')
        for grid in range(1,4):
            y = y0+(y1-y0)*grid/4
            c.create_line(x0,y,x1,y,fill='#243245', tags='chrome')
        for grid in range(1,6):
            x = x0+(x1-x0)*grid/6
            c.create_line(x,y0,x,y1,fill='#1c2a3d', tags='chrome')
        px0,py0,px1,py1 = layout['panel']
        self.rounded(px0,py0,px1,py1,12*s,fill='#121d2b',outline='#42516a',tags='chrome')
        c.create_line(px0+12*s,py0+s,px1-12*s,py0+s,fill='#6a7d95',tags='chrome')
        for bounds,label,color in zip(layout['pedals'],('B','T'),(COLORS[1],COLORS[0])):
            bx0,by0,bx1,by1 = bounds
            self.rounded(bx0-2*s,by0-2*s,bx1+2*s,by1+2*s,4*s,
                         fill='#182536',outline='#35465e',tags='chrome')
            c.create_text((bx0+bx1)/2,py0+12*s,text=label,fill=color,
                          font=('Segoe UI',-max(8,round(9*s)),'bold'),tags='chrome')
        cx,cy,radius = layout['wheel']
        c.create_oval(cx-radius-3*s,cy-radius-3*s,cx+radius+3*s,cy+radius+3*s,
                      outline='#25384c',width=1,tags='chrome')
        c.create_line(cx,cy-radius-3*s,cx,cy-radius+2*s,fill='#52b5ff',width=1.5,tags='chrome')
        c.create_text(cx,py0+12*s,text='M4 GT3 · 540°',fill='#91a8c5',
                      font=('Segoe UI',-max(7,round(8*s))),tags='chrome')
        c.tag_lower('chrome')

    def poll_keys(self):
        if self.closing:return
        failure=getattr(self.engine,'recording_failure',None)
        if failure and failure!=getattr(self,'reported_recording_failure',None):
            self.reported_recording_failure=failure
            self.root.after_idle(lambda message=failure:messagebox.showerror('记录已停止：写盘失败',message,parent=self.root))
        elif not failure:self.reported_recording_failure=None
        key_state = self.user32.GetAsyncKeyState(0x75)
        f6 = bool(key_state & 0x8000)
        if (key_state & 1) or (f6 and not self.f6_down):self.toggle_reference()
        self.f6_down = f6
        key_state = self.user32.GetAsyncKeyState(0x76)
        f7 = bool(key_state & 0x8000)
        if (key_state & 1) or (f7 and not self.f7_down):
            self.toggle_input_channel()
        self.f7_down = f7
        key_state = self.user32.GetAsyncKeyState(0x77)
        f8 = bool(key_state & 0x8000)
        if (key_state & 1) or (f8 and not self.f8_down):
            self.toggle_clickthrough()
        self.f8_down = f8
        key_state = self.user32.GetAsyncKeyState(0x78)
        f9 = bool(key_state & 0x8000)
        if (key_state & 1) or (f9 and not self.f9_down):
            self.toggle_clean()
        self.f9_down = f9
        key_state = self.user32.GetAsyncKeyState(0x79)
        f10 = bool(key_state & 0x8000)
        if (key_state & 1) or (f10 and not self.f10_down):
            self.show_sampling_settings()
        self.f10_down = f10
        key_state = self.user32.GetAsyncKeyState(0x7a)
        f11 = bool(key_state & 0x8000)
        if (key_state & 1) or (f11 and not self.f11_down):
            self.toggle_clean(with_controls=True)
        self.f11_down = f11
        if self.render_clock.set_rate(self.drawing_target(),time.perf_counter()):
            if not self.drawing:
                if self.draw_job is not None:
                    self.root.after_cancel(self.draw_job)
                self.draw_job = self.root.after_idle(self.queue_draw)
        self.root.after(25,self.poll_keys)

    def draw(self, event=None):
        if self.closing or self.drawing:
            return
        self.drawing = True
        self.paint_started=time.perf_counter()
        self.draw_job = None
        self.render_clock.set_rate(self.drawing_target(),time.perf_counter())
        remaining = self.render_clock.deadline-time.perf_counter()
        if 0 < remaining < 0.003:
            # The last fraction of a millisecond uses an interruptible native wait,
            # releasing the GIL, rather than rounding every frame up to one ms.
            if self.render_waiter.until(self.render_clock.deadline):
                self.render_clock.set_rate(self.drawing_target(),time.perf_counter())
        c = self.canvas
        mode = self.hud_mode.get()
        channel = self.input_channel.get()
        point_offset,channel_label = INPUT_CHANNELS[channel]
        clean = mode != 'normal'
        controls = mode == 'controls'
        w, h = max(4, c.winfo_width()), max(4, c.winfo_height())
        if self.live_key != (w,h,mode):
            c.delete('live')
            c.delete('wheel')
            self.live_items.clear()
            self.wheel_display = None
            self.live_key = (w,h,mode)
        self.paint_chrome(w, h, clean, controls)
        s = min(w/640,h/228)
        window = float(self.window.get())
        now = time.monotonic()
        layout = hud_layout(w,h,clean,controls)
        x0,x1,y0,y1 = layout['plot']
        self.engine.configure_plot(x1-x0,window,y1-y0)
        with self.engine.lock:
            trace_key = (id(self.engine),self.engine.plot_revision,self.engine.reference_revision,w,h,mode,window,channel)
            rebuild = trace_key != self.trace_key or now >= self.trace_expiry
            points = [p for p in self.engine.plot_points if now-p[0]<=window] if rebuild else ()
            latest = self.engine.latest
            reference_points = [p for p in self.engine.reference_points if now-p[0]<=window] if rebuild and self.engine.reference_enabled else ()
            reference_latest = self.engine.reference_latest
            if hasattr(self,'diagnostics'):self.paint_sample=latest
        if rebuild:
            c.delete('trace')
            self.trace_key = trace_key
            self.trace_expiry = points[0][0]+window if points else math.inf
        else:
            c.move('trace',-(now-self.trace_time)/window*(x1-x0),0)
        self.trace_time = now
        input_offset = 3 if channel=='filtered' else 0
        values = latest['controls'][input_offset:input_offset+3] if latest else [0, 0, 0]
        if not clean:
            self.live_item('input_channel',c.create_text,111*s,18*s,
                           text=f'/  LMU · {channel_label} · F7',fill='#a9bdd7',anchor='w',
                           font=('Segoe UI',-max(9,round(10*s))))
        if not clean or controls:
            self.paint_controls(layout,values,clean=clean)
        for lane, (name, color, value) in enumerate(zip(('油门', '刹车', '转向'), COLORS, values)):
            value_text = f'{value * 100:+.0f}%' if lane == 2 else f'{value * 100:.0f}%'
            if not clean:
                card_width = (w-44*s)/3
                self.live_item('value'+str(lane),c.create_text,25*s+lane*(card_width+8*s),68*s,text=value_text,
                               fill=color,anchor='w',font=('Segoe UI',-round(21*s),'bold'))
            coords = []
            previous = None
            for point in points:
                if previous is not None and point[0] - previous > 3:
                    if len(coords) >= 4:
                        self.paint_trace(coords, lane, clean)
                    coords = []
                x = x1 - (now - point[0]) / window * (x1 - x0)
                low, high = point[point_offset+lane+3], point[point_offset+lane+6]
                height = (y1-y0)/(2 if lane==2 else 1)
                # Sub-quarter-pixel ranges are visually indistinguishable. Larger
                # ranges still emit both extrema, preserving brief pedal spikes.
                displayed = (low,high) if (high-low)*height>=0.25 else (point[point_offset+lane],)
                for v in displayed:
                    fraction = (v + 1) / 2 if lane == 2 else v
                    coords.extend((x, y1 - fraction * (y1 - y0)))
                previous = point[0]
            if len(coords) >= 4:
                self.paint_trace(coords, lane, clean)
        if rebuild:
            offset=3 if channel=='filtered' else 1
            for lane,color in enumerate(('#b4f7d9','#ffc0c8')):
                coords=[];previous=None
                for point in reference_points:
                    if previous is not None and point[0]-previous>.15:
                        if len(coords)>=4:c.create_line(*reduce_trace(coords),fill=color,width=max(1,s),dash=(3,4),tags='trace')
                        coords=[]
                    coords.extend((x1-(now-point[0])/window*(x1-x0),y1-point[offset+lane]*(y1-y0)));previous=point[0]
                if len(coords)>=4:c.create_line(*reduce_trace(coords),fill=color,width=max(1,s),dash=(3,4),tags='trace')
        poll_hz, sample_hz = self.engine.actual_rates()
        draw_hz = self.actual_draw_rate()
        failure=getattr(self.engine,'recording_failure',None)
        state = 'ERROR / 记录停止' if failure else 'DEMO' if self.engine.demo else 'REC' if self.engine.recorder.file else 'WAIT / SAVED'
        lock = '穿透' if self.clickthrough else '可拖动'
        if not clean:
            self.live_item('state',c.create_oval,16*s,h-17*s,21*s,h-12*s,
                           fill=COLORS[1] if failure else COLORS[0] if self.engine.recorder.file else '#8da1bd',outline='')
            mode = 'DYN' if self.settings['mode']=='dynamic' else 'FIX'
            self.live_item('rates',c.create_text,28*s,h-14*s,
                           text=f'{state} {mode}{self.engine.target_hz}   ·   新{sample_hz:.0f} / 绘{draw_hz:.0f} Hz',
                           fill='#a9b9d0',anchor='w',font=('Segoe UI',-max(9,round(10*s))))
            alignment=getattr(self.engine,'reference_state',{})
            approximate=isinstance(alignment,dict) and (alignment.get('confidence',1)<.6 or alignment.get('conditions',{}).get('unknown'))
            self.live_item('keys',c.create_text,w-16*s,h-14*s,
                           text=('写盘异常 · 该段已停止' if failure else f'REF{"≈" if approximate else ""} {reference_latest[-1]:+.3f}s · F6' if self.reference_on.get() and reference_latest else
                                 ('REF '+self.engine.reference_state.get('mode','未匹配')+' · F6' if self.reference_on.get() else f'{int(window)}s   ·   F8 {lock}   ·   F9 纯净')),
                           fill='#889ab4',anchor='e',font=('Segoe UI',-max(9,round(10*s))))
        # Tk queues canvas painting as an idle task. Acknowledge after that task,
        # without a nested update_idletasks loop consuming future render callbacks.
        self.draw_job = self.root.after_idle(self.finish_draw)

    def finish_draw(self):
        self.draw_job = None
        self.drawing = False
        if self.closing:
            return
        self.draw_times.append(time.monotonic())
        if hasattr(self,'diagnostics'):self.diagnostics.paint(self.paint_started,self.paint_sample,self.drawing_target())
        deadline = self.render_clock.complete(time.perf_counter())
        delay = max(0,int((deadline-time.perf_counter())*1000))
        now = time.perf_counter()
        # Windows/Tk must periodically leave its zero-delay event queue to accept
        # native input and positive timers. Yield one ms per four ms of busy drawing,
        # while allowing submillisecond frames between yields.
        if delay == 0 and now-self.gui_yield_at >= 0.004:
            delay = 1
        if delay:
            self.gui_yield_at = now
        # Zero-delay timers can starve positive timers and input on Windows Tk.
        # Idle continuations let normal UI events run between high-rate frames.
        self.draw_job = self.root.after(delay,self.draw) if delay else self.root.after_idle(self.queue_draw)

    def queue_draw(self):
        # The idle stage queues a timer rather than drawing inside an idle handler.
        # This keeps update_idletasks from recursively consuming future frames.
        if not self.closing:
            self.draw_job = self.root.after(0,self.draw)

    def live_item(self, key, create, *coords, **options):
        cached = self.live_items.get(key)
        if cached is None:
            self.live_items[key] = (create(*coords,**options,tags='live'),options,coords)
        else:
            if cached[2] != coords:
                self.canvas.coords(cached[0],*coords)
            if cached[1] != options:
                changed = {name:value for name,value in options.items() if cached[1].get(name)!=value}
                self.canvas.itemconfigure(cached[0],**changed)
            self.live_items[key] = (cached[0],options,coords)

    def paint_controls(self, layout, values, clean=False):
        # Called once in the same render pass and with the same selected input snapshot
        # as the waveforms. These controls have no separate refresh timer.
        s = layout['scale']
        for bounds,value,color,key in zip(layout['pedals'],(values[1],values[0]),
                                         (COLORS[1],COLORS[0]),('brake','throttle')):
            self.live_item(key+'_bar',self.canvas.create_rectangle,*pedal_fill(bounds,value),
                           fill=color,outline='',state='normal' if value>0 else 'hidden')
            if not clean:
                self.live_item(key+'_percent',self.canvas.create_text,(bounds[0]+bounds[2])/2,
                               layout['panel'][3]-10*s,text=f'{value*100:.0f}%',fill=color,
                               font=('Segoe UI',-max(8,round(9*s)),'bold'))
        if self.wheel_display is None:
            self.wheel_display = WheelDisplay(self.canvas,*layout['wheel'],
                                              background='#000000' if clean else '#121d2b')
        angle = steering_angle(values[2])
        self.wheel_display.set_angle(angle)
        if not clean:
            self.live_item('wheel_degrees',self.canvas.create_text,layout['wheel'][0],
                           layout['panel'][3]-10*s,text=f'{angle:+.0f}°',fill='#b9d9fa',
                           font=('Segoe UI',-max(8,round(10*s)),'bold'))

    def paint_trace(self, coords, lane, clean):
        coords = reduce_trace(coords)
        if not clean:
            self.canvas.create_line(*coords, fill=('#204b44','#502d3b','#23435d')[lane],
                                    width=4, capstyle='round', joinstyle='bevel', tags='trace')
        self.canvas.create_line(*coords, fill=COLORS[lane], width=1.8 if not clean else 2,
                                capstyle='round', joinstyle='bevel', tags='trace')

    def close(self):
        self.closing = True
        self.render_stop.set()
        if self.draw_job is not None:
            self.root.after_cancel(self.draw_job)
            self.draw_job = None
        self.engine.stop.set()
        self.engine.thread.join(timeout=3)
        if self.engine.thread.is_alive():
            self.root.after(25, self.close)
            return
        # Keep Tk and its variables alive on the GUI thread until all exports finish.
        if any(t.is_alive() for t in self.engine.recorder.pending_reports):
            self.root.after(25,self.close)
            return
        self.render_waiter.close()
        self.root.destroy()


def main():
    if '--release-smoke' in sys.argv:
        from release_smoke import run
        run();return
    if '--doctor' in sys.argv:
        from doctor import check
        result=check();print(json.dumps(result,ensure_ascii=False,indent=2))
        if '--doctor-output' in sys.argv:
            target=Path(sys.argv[sys.argv.index('--doctor-output')+1])
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        if not result['ok']:raise SystemExit(1)
        return
    if '--version' in sys.argv:
        print('LMU StintLab 0.1.0');return
    if '--import-duckdb' in sys.argv:
        index=sys.argv.index('--import-duckdb')
        if index+1>=len(sys.argv):raise ValueError('--import-duckdb 后需要已结束的 .duckdb 文件路径')
        folder=import_recording(sys.argv[index+1],ROOT)
        make_report(folder)
        (ROOT/'last_native_import.json').write_text(json.dumps({'folder':str(folder)},ensure_ascii=False),encoding='utf-8')
        return
    # Keep the high-rate reader from holding Python's GIL for the default 5 ms
    # timeslice while the GUI is trying to draw a submillisecond frame.
    sys.setswitchinterval(0.0005)
    # Opt in before creating Tk windows; render to real pixels instead of bitmap scaling.
    dpi = ctypes.WinDLL('user32', use_last_error=True)
    try:
        dpi.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if not dpi.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            dpi.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            dpi.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            dpi.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        dpi.SetProcessDPIAware()
    timer = ctypes.WinDLL('winmm')
    requested = timer.timeBeginPeriod(1) == 0
    try:
        App('--demo' in sys.argv, clean='--clean' in sys.argv,
            clean_controls='--clean-controls' in sys.argv).root.mainloop()
    finally:
        if requested:
            timer.timeEndPeriod(1)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        (ROOT / 'startup_error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
