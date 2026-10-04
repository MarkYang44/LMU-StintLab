"""Read LMU's native channel/event tables, writing only a new plugin folder."""
import bisect
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import vehiclelab

FIELDS = ['time_s','utc','session_time_s','lap','lap_distance_m','throttle','brake','steering',
          'filtered_throttle','filtered_brake','filtered_steering','speed_kmh','lap_start_s',
          'lap_invalidated','in_pits','track_length_m','world_x_m','world_y_m','world_z_m','fuel_l','tyre_compound','track_temp_c','wetness','tc_level','abs_level','tc_active','abs_active','gear']
CONTROLS = {'throttle':'Throttle Pos Unfiltered','brake':'Brake Pos Unfiltered',
            'steering':'Steering Pos Unfiltered','filtered_throttle':'Throttle Pos',
            'filtered_brake':'Brake Pos','filtered_steering':'Steering Pos'}
EXTRAS = ('Fuel Level','Virtual Energy','Tyres Wear','TyresPressure','TyresTempCentre',
          'Ambient Temperature','Track Temperature','Path Lateral','TC','ABS','TCLevel','ABSLevel',
          'Gear','In Pits','TyresCompound','Minimum Path Wetness','Lap Time','Current LapTime')
EXTRAS=tuple(dict.fromkeys((*EXTRAS,*vehiclelab.NATIVE_CHANNELS)))


def driver(root):
    import duckdb
    return duckdb


def quote(name):
    return '"'+name.replace('"','""')+'"'


def fingerprint(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def read_native(path, root):
    path = Path(path).resolve()
    if path.suffix.lower() != '.duckdb':
        raise ValueError('请选择已结束录制的 .duckdb 文件')
    before = fingerprint(path)
    db = driver(root).connect(str(path),read_only=True,config={'enable_external_access':False,
            'autoinstall_known_extensions':False,'autoload_known_extensions':False,'threads':2})
    try:
        # Only physical tables, never views or user-defined SQL from the recording.
        tables = {r[0]:r[1] for r in db.execute("SELECT table_name,schema_name FROM duckdb_tables() WHERE NOT internal").fetchall()}
        def table(name):
            return quote(tables[name])+'.'+quote(name)
        if not {'metadata','channelsList','eventsList'} <= tables.keys():
            raise ValueError('不支持的 DuckDB 表结构：需要 metadata / channelsList / eventsList')
        meta = dict(db.execute('SELECT key,value FROM '+table('metadata')).fetchall())
        channels = db.execute('SELECT channelName,frequency,unit FROM '+table('channelsList')).fetchall()
        events = db.execute('SELECT eventName,unit FROM '+table('eventsList')).fetchall()
        series = {}
        for name,freq,unit,event in [(n,f,u,False) for n,f,u in channels]+[(n,0,u,True) for n,u in events]:
            if name not in tables or name not in {*CONTROLS.values(),'Ground Speed','Lap Dist','Lap','GPS Latitude','GPS Longitude',*EXTRAS,'Lap Invalidated'}:
                continue
            cols = [r[1] for r in db.execute('PRAGMA table_info('+"'"+table(name).replace("'","''")+"')").fetchall()]
            values = [v for v in cols if v=='value' or v.startswith('value') and v[5:].isdigit()]
            values.sort(key=lambda v:0 if v=='value' else int(v[5:]))
            if not values:
                continue
            has_time = 'ts' in cols
            if event and not has_time:
                raise ValueError('事件缺少 ts：'+name)
            if not event and (not isinstance(freq,(int,float)) or not math.isfinite(freq) or freq<=0 or freq>4000):
                raise ValueError('通道采样率无效：'+name)
            count = db.execute('SELECT count(*) FROM '+table(name)).fetchone()[0]
            if count>8000000:
                raise ValueError('单通道超过 800 万样本，请选择较短的已结束录制')
            result = db.execute('SELECT '+','.join(quote(c) for c in (['ts'] if has_time else [])+values)
                    +' FROM '+table(name)+' ORDER BY '+('ts' if has_time else 'rowid')).fetchall()
            data = []
            for i,r in enumerate(result):
                t = float(r[0]) if has_time else i/freq
                nums = [float(x) for x in (r[1:] if has_time else r)]
                if not all(math.isfinite(x) for x in [t,*nums]):
                    raise ValueError('非有限采样值：'+name)
                if data and t<data[-1][0]:
                    raise ValueError('时间顺序无效：'+name)
                if data and t==data[-1][0]:
                    data[-1] = [t,*nums]
                else:
                    data.append([t,*nums])
            series[name] = dict(unit=str(unit or ''),frequency_hz=freq,event=event,
                                explicit_time=has_time,data=data)
    finally:
        db.close()
    if fingerprint(path)!=before:
        raise ValueError('源日志仍在变化，请等待游戏结束录制后再导入')
    return meta,series,before


def lookup(s,t,offset=0):
    data=s['data'];times=s['times'];target=t+offset
    i=bisect.bisect_right(times,target)
    if not i:
        return None
    a=data[i-1]
    if s['event']:
        return a[1:]
    if i==len(data):
        return a[1:] if abs(target-a[0]) <= 1/max(1,s['frequency_hz'])+1e-7 else None
    b=data[i];dt=b[0]-a[0]
    if dt>max(.2,3/max(1,s['frequency_hz'])):
        return None
    # Distance is discontinuous at S/F; never interpolate through a lap reset.
    if s.get('distance') and b[1]<a[1]-50:
        return a[1:]
    f=(target-a[0])/max(1e-9,dt)
    return [x+(y-x)*f for x,y in zip(a[1:],b[1:])]


def input_scale(s,steer=False):
    unit=s['unit'].strip().lower();values=[r[1] for r in s['data']]
    if not values:
        raise ValueError('空输入通道')
    scale = .01 if unit in ('%','percent','percentage') else 1
    if unit not in ('','%','percent','percentage','ratio','normalized','1','-'):
        raise ValueError('不支持的输入单位：'+unit)
    if any(not (-1.001 if steer else -.001) <= v*scale <= 1.001 for v in values):
        raise ValueError('输入范围无效；需要比例或百分比单位')
    return scale


def import_recording(path,root,overrides=None):
    root=Path(root);path=Path(path);overrides=overrides or {}
    meta,series,sha=read_native(path,root)
    required={*CONTROLS.values(),'Ground Speed','Lap Dist'}
    missing=required-series.keys()
    if missing:
        raise ValueError('日志缺少所需通道：'+', '.join(sorted(missing))+'。不会用过滤后输入伪造原始输入。')
    for s in series.values():
        s['times']=[r[0] for r in s['data']]
    dist=series['Lap Dist'];dist['distance']=True
    resets=[r[0] for a,r in zip(dist['data'],dist['data'][1:]) if r[1]<a[1]-50]
    lap_events=series.get('Lap',{}).get('data',[])
    # Native sample-only tables begin at t=0. Match actual distance resets to Lap
    # event changes to recover the absolute event epoch, as LMU's catalog has no ts.
    event_offset=0
    if not dist['explicit_time'] and lap_events:
        changes=[b[0] for a,b in zip(lap_events,lap_events[1:]) if b[1]>a[1]]
        diffs=[b-a for a,b in zip(resets,changes)]
        if diffs:
            event_offset=statistics.median(diffs)
            if max(abs(x-event_offset) for x in diffs)>max(.3,2/dist['frequency_hz']):
                raise ValueError('圈事件与通道时间无法可靠对齐')
        else:
            event_offset=lap_events[0][0]
    controls={k:input_scale(series[n],k.endswith('steering')) for k,n in CONTROLS.items()}
    speedunit=series['Ground Speed']['unit'].lower().replace(' ','')
    if speedunit in ('m/s','ms-1','m.s-1'):speedscale=3.6
    elif speedunit in ('km/h','kmh','kph'):speedscale=1
    else:raise ValueError('Ground Speed 单位未知：'+speedunit)
    track=str(overrides.get('track') or meta.get('TrackName') or '').strip()
    vehicle=str(overrides.get('vehicle') or meta.get('CarName') or '').strip()
    if not track or not vehicle:
        raise ValueError('缺少 TrackName / CarName，可在导入窗口填写赛道与车辆')
    length=float(overrides.get('track_length') or meta.get('TrackLength') or 0)
    if length<100:length=0
    anchor=max((series[n] for n in CONTROLS.values()),key=lambda s:s['frequency_hz'])
    timeline=anchor['times']
    if len(timeline)>2000000:raise ValueError('输入超过 200 万帧，请选择较短记录')
    gps=all(n in series and series[n]['unit'].lower() in ('deg','degree','degrees','°') for n in ('GPS Latitude','GPS Longitude'))
    lat0=series['GPS Latitude']['data'][0][1] if gps else 0
    lon0=series['GPS Longitude']['data'][0][1] if gps else 0
    if gps and (abs(lat0)>90 or abs(lon0)>180):raise ValueError('GPS 经纬度范围无效')
    stamp=datetime.now(timezone.utc).isoformat()
    folder=root/'ImportedLogs'/('Native_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+sha[:8])
    folder.mkdir(parents=True,exist_ok=False)
    count=skipped=0
    vehicle_last=-math.inf
    try:
        with (folder/'inputs.csv').open('w',encoding='utf-8',newline='') as f,(folder/'vehicle.csv').open('w',encoding='utf-8',newline='') as vf:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
            vw=csv.writer(vf);vw.writerow(vehiclelab.COLUMNS)
            for t in timeline:
                values={k:lookup(series[n],t) for k,n in CONTROLS.items()}
                d=lookup(dist,t);speed=lookup(series['Ground Speed'],t)
                if any(v is None for v in values.values()) or d is None or speed is None:
                    skipped+=1;continue
                # Assign lap boundaries from distance, preserving native Lap number
                # when event alignment is available; validity remains unknown.
                lap_value=lookup(series['Lap'],t,event_offset) if 'Lap' in series else None
                number=int(lap_value[0]) if lap_value else 1+bisect.bisect_right(resets,t)
                row=dict(time_s=t-timeline[0],utc=stamp,session_time_s=t,lap=number,
                         lap_distance_m=d[0],speed_kmh=max(0,speed[0]*speedscale))
                row.update({k:max(-1 if k.endswith('steering') else 0,min(1,v[0]*controls[k])) for k,v in values.items()})
                if length:row['track_length_m']=length
                for name,key in (('In Pits','in_pits'),('Lap Invalidated','lap_invalidated')):
                    if name in series:
                        v=lookup(series[name],t,event_offset if series[name]['event'] and not dist['explicit_time'] else 0)
                        if v is not None:row[key]=int(bool(v[0]))
                for key,name in [('fuel_l','Fuel Level'),('tyre_compound','TyresCompound'),('track_temp_c','Track Temperature'),('wetness','Minimum Path Wetness'),('tc_level','TCLevel'),('abs_level','ABSLevel'),('tc_active','TC'),('abs_active','ABS'),('gear','Gear')]:
                    if name in series:
                        v=lookup(series[name],t,event_offset if series[name]['event'] and not dist['explicit_time'] else 0)
                        if v is not None:row[key]=v[0]
                if gps:
                    lat=lookup(series['GPS Latitude'],t);lon=lookup(series['GPS Longitude'],t)
                    if lat and lon:
                        if not -85<lat[0]<85 or not -180<=lon[0]<=180:raise ValueError('GPS 经纬度范围无效')
                        # A fixed global projection allows separate recordings to
                        # share coordinates; session-local GPS origins cannot.
                        row.update(world_x_m=6378137*math.radians(lon[0]),world_y_m=0,
                                   world_z_m=-6378137*math.log(math.tan(math.pi/4+math.radians(lat[0])/2)))
                writer.writerow(row);count+=1
                if t-vehicle_last>=.1-1e-8 or t==timeline[-1]:
                    values=vehiclelab.native_values(series,t,lookup,event_offset if not dist['explicit_time'] else 0)
                    values.update(speed_kmh=row['speed_kmh'],track_length_m=length)
                    extra=dict(et=t,lap=number,distance=d[0],vehicle=values,in_pits=row.get('in_pits'),lap_invalidated=row.get('lap_invalidated'))
                    vw.writerow(vehiclelab.sample_row(extra,timeline[0]));vehicle_last=t
        if count<3:raise ValueError('连续输入样本不足')
        extras={n:{k:v for k,v in s.items() if k not in ('times','distance')} for n,s in series.items() if n in EXTRAS}
        metadata=dict(track=track,vehicle=vehicle,driver=str(overrides.get('driver') or meta.get('DriverName') or 'Unknown'),
            started_utc=str(meta.get('RecordingTime') or stamp),ended_utc=stamp,status='finished',session='native_import',
            source='LMU native DuckDB (read-only import)',end_reason='native import',position_source='gps_mercator_m' if gps else None,
            native_metadata=meta,native_source=dict(path=str(path.resolve()),sha256=sha,event_offset_s=event_offset,
            time_alignment='native_ts' if dist['explicit_time'] else 'sample_index/frequency; Lap events aligned to distance resets',
            channel_rates={n:s['frequency_hz'] for n,s in series.items()},converted_rows=count,skipped_gap_rows=skipped,
            validity='not provided unless Lap Invalidated exists',resampling='continuous linear at native highest input cadence; events held; no upsampling beyond source input rate'))
        metadata['vehicle_telemetry']=dict(version=1,target_hz=10,file='vehicle.csv',source='declared native channel units',
            units='Celsius / kPa / wear fraction / fuel L / battery and virtual energy percent / power kW',
            unknown_units='unsupported or absent channel units remain blank; original native channels retained')
        (folder/'session.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'native_channels.json').write_text(json.dumps(dict(event_offset_s=event_offset if not dist['explicit_time'] else 0,channels=extras),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    except Exception:
        # Keep failed output separate and clearly marked; never touch source DB.
        (folder/'IMPORT_FAILED.txt').write_text('Import failed; original DuckDB unchanged.',encoding='utf-8')
        raise
    return folder
