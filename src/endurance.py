"""Pit lifecycle, descriptive stint pace and observed weather. No game writes."""
from collections import deque
import csv
import json
import math
from pathlib import Path
import statistics
from storage import atomic_json
from vehiclelab import number

DEFAULTS=dict(pit_enabled=False,stint_enabled=False,weather_enabled=False,pit_limit_kmh=0.,
    pit_tolerance_kmh=1.,stationary_kmh=1.,warmup_laps=2,pace_window=3,
    weather_window_s=60.,rain_change=.10,wetness_change=.05,temp_change_c=2.,alert_cooldown_s=60.)
FIELDS=('speed_kmh','pit_state','speed_limiter','pit_stops','track_length_m','rain_severity',
    'ambient_temp_c','track_temp_c','wetness','wetness_min','wetness_max','wind_x_raw','wind_y_raw',
    'wind_z_raw','tyre_front_index','tyre_rear_index')
WEATHER=('rain_severity','ambient_temp_c','track_temp_c','wetness','wetness_min','wetness_max',
    'wind_x_raw','wind_y_raw','wind_z_raw')

def settings(value=None):
    result={**DEFAULTS,**(value or {})}
    for key,low,high in [('pit_limit_kmh',0,200),('pit_tolerance_kmh',0,20),('stationary_kmh',.1,10),
        ('warmup_laps',0,10),('pace_window',2,20),('weather_window_s',10,600),('rain_change',.01,1),
        ('wetness_change',.01,1),('temp_change_c',.1,30),('alert_cooldown_s',10,600)]:
        v=number(result[key],low,high)
        if v is None:raise ValueError(key+' 超出范围')
        if key in ('warmup_laps','pace_window') and v!=int(v):raise ValueError(key+' 必须是整数')
        result[key]=int(v) if key in ('warmup_laps','pace_window') else v
    for k in ('pit','stint','weather'):result[k+'_enabled']=bool(result[k+'_enabled'])
    return result

def load_settings(path):
    try:return settings(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):return settings()

def compatible(a,b):
    """Only observed differences veto a descriptive pace reference."""
    for key,tol in [('wetness',.1),('track_temp_c',5),('tyre_front_index',0),('tyre_rear_index',0)]:
        x=a.get(key);y=b.get(key)
        if x is not None and y is not None and abs(x-y)>tol:return False
    return True

def pace(laps,config):
    times=[l['time_s'] for l in laps];w=config['pace_window'];n=config['warmup_laps']
    stable=laps[n:];early=stable[:w];late=stable[-w:]
    drift=statistics.median(l['time_s'] for l in late)-statistics.median(l['time_s'] for l in early) if len(stable)>=2*w else None
    pairs=[(a,b) for a,b in zip(stable,stable[1:]) if compatible(a.get('context',{}),b.get('context',{}))]
    return dict(count=len(times),median_s=statistics.median(times) if times else None,
        spread_s=statistics.pstdev(times) if times else None,warmup=laps[:n],early=early,late=late,
        drift_s=drift,conditions_changed=any(not compatible(a.get('context',{}),b.get('context',{})) for a,b in zip(laps,laps[1:])),
        comparable_pairs=len(pairs),note='后段减去稳定初段的中位圈速；至少两组独立窗口。油量、交通和天气影响未被消除，不能视为轮胎衰退。')

class Monitor:
    def __init__(self,config=None):
        self.config=settings(config);self.key=None;self.reset()

    def reset(self):
        self.previous=None;self.origin=None;self.active=None;self.pits=deque(maxlen=1000)
        self.laps=deque(maxlen=2000);self.group=None;self.weather=deque(maxlen=6001)
        self.alerts=deque(maxlen=1000);self.last_alert={};self.current_stint=1;self.stint_start=None
        self.weather_anchor=None;self.last_weather_et=None

    def configure(self,config):self.config=settings(config);self.weather_anchor=None

    def update(self,s,force=False):
        key=tuple(s.get(k) for k in ('track','vehicle_name','session','player_id'))
        if key!=self.key or self.previous and s['et']<self.previous['et']:
            self.reset();self.key=key
        old=self.previous;t=s['et'];v=s.get('vehicle',{})
        if old and t==old['et']:return
        if old and not force and t-old['et']<.1 and all(s.get(k)==old.get(k) for k in ('lap_start','in_pits','lap_invalidated')) and all(v.get(k)==old['vehicle'].get(k) for k in ('pit_state','speed_limiter')):return
        if self.origin is None:self.origin=t;self.stint_start=t
        gap=bool(old and t-old['et']>1.5)
        present=s.get('in_pits')
        inside=bool(present) if present is not None else v.get('pit_state') in (2,3,4) if v.get('pit_state') is not None else None
        was=self.active is not None
        if inside and not was:
            self.active=dict(number=len(self.pits)+1,entry_s=t-self.origin,entry_et=t,exit_s=None,
                partial_start=old is None or gap,partial_end=True,gap=gap,stationary_s=0.,stops=0,
                overspeed_s=0.,maximum_kmh=v.get('speed_kmh'),entry_lap=s.get('lap'),exit_lap=None,
                fuel_start=v.get('fuel_l'),energy_start=v.get('virtual_energy_pct'),fuel_added_l=0.,energy_added_pct=0.,
                service_observed=False,context={k:v.get(k) for k in (*WEATHER,'tyre_front_index','tyre_rear_index')})
            self.active.update(phase_durations_s={'2':0.,'3':0.,'4':0.},limits_used=[],phase_known=True)
            self.active.update(stationary_known=v.get('speed_kmh') is not None,fuel_known=v.get('fuel_l') is not None,energy_known=v.get('virtual_energy_pct') is not None)
            self.active['partial_start']|=bool(old and old.get('in_pits') is None)
        p=self.active
        if p:
            p['gap']|=gap
            speed=v.get('speed_kmh')
            p['stationary_known']&=speed is not None
            p['fuel_known']&=v.get('fuel_l') is not None;p['energy_known']&=v.get('virtual_energy_pct') is not None
            if inside and speed is not None:p['maximum_kmh']=max(p['maximum_kmh'] or 0,speed)
            dt=t-old['et'] if old and not gap else 0.
            previous_inside=old and (old.get('in_pits') or old['vehicle'].get('pit_state') in (2,3,4))
            stationary=inside and speed is not None and speed<=self.config['stationary_kmh']
            previously_still=previous_inside and old['vehicle'].get('speed_kmh') is not None and old['vehicle']['speed_kmh']<=self.config['stationary_kmh']
            if stationary and previously_still:p['stationary_s']+=dt
            if stationary and not previously_still:p['stops']+=1
            if previous_inside and dt:
                limit=self.config['pit_limit_kmh']
                if limit not in p['limits_used']:p['limits_used'].append(limit)
                state=old['vehicle'].get('pit_state')
                if state in (2,3,4):p['phase_durations_s'][str(int(state))]+=dt
                else:p['phase_known']=False
                if limit and old['vehicle'].get('speed_kmh') is not None and old['vehicle']['speed_kmh']>limit+self.config['pit_tolerance_kmh']:p['overspeed_s']+=dt
                for field,dest,tolerance in [('fuel_l','fuel_added_l',.001),('virtual_energy_pct','energy_added_pct',.001)]:
                    a=old['vehicle'].get(field);b=v.get(field)
                    if a is not None and b is not None and b-a>tolerance:p[dest]+=b-a;p['service_observed']=True
            if inside is False:
                p.update(exit_s=t-self.origin,exit_lap=s.get('lap'),partial_end=False,fuel_end=v.get('fuel_l'),energy_end=v.get('virtual_energy_pct'))
                p['duration_s']=None if p['partial_start'] or p['gap'] else p['exit_s']-p['entry_s']
                p['measured_interval_s']=p['exit_s']-p['entry_s']
                if p['gap'] or p['partial_start'] or not p['stationary_known']:p['stationary_s']=None
                if p['gap'] or p['partial_start'] or not p['fuel_known']:p['fuel_added_l']=None
                if p['gap'] or p['partial_start'] or not p['energy_known']:p['energy_added_pct']=None
                if p['gap'] or p['partial_start'] or not p['phase_known']:p['phase_durations_s']=None
                self.pits.append(p);self.active=None;self.current_stint+=1;self.stint_start=t
        self._lap(s,gap)
        self._weather(t,v,gap)
        self.previous={**s,'vehicle':dict(v)}

    def _lap(self,s,gap):
        t=s['et'];start=s.get('lap_start');v=s.get('vehicle',{})
        if start is None:return
        if self.group and start!=self.group['start']:
            g=self.group;length=v.get('track_length_m')
            complete=g['observed'] and not g['gap'] and g['near_start'] and length and g['distance']>=length*.95 and start>g['start']
            if complete:
                self.laps.append(dict(number=g['number'],time_s=start-g['start'],start_time_s=g['start']-self.origin,
                    end_time_s=start-self.origin,qualified=not g['bad'],in_pits=g['pit'],stint=g['stint'],context=g['context']))
            self.group=None
        if self.group is None:
            self.group=dict(start=start,number=s.get('lap'),observed=abs(t-start)<=.3,gap=False,bad=False,pit=False,
                distance=0,near_start=False,stint=self.current_stint,context={k:v.get(k) for k in (*WEATHER,'fuel_l','tyre_front_index','tyre_rear_index')})
        g=self.group;d=s.get('distance');length=v.get('track_length_m') or 1
        g['gap']|=gap;g['bad']|=bool(s.get('lap_invalidated') or s.get('in_pits'));g['pit']|=bool(s.get('in_pits'))
        if d is not None:
            g['near_start']|=-20<=d<=min(80,length*.05)
            if g['near_start']:g['distance']=max(g['distance'],d)

    def _weather(self,t,v,gap):
        if self.last_weather_et is not None and t-self.last_weather_et<.5 and not gap:return
        self.last_weather_et=t;point=dict(et=t,**{k:v.get(k) for k in WEATHER})
        if gap:self.weather.clear()
        self.weather.append(point)
        while self.weather and t-self.weather[0]['et']>600:self.weather.popleft()
        anchor=self.weather_anchor
        if anchor is None or gap:self.weather_anchor=point;return
        anchor={k:point.get(k) if anchor.get(k) is None else value for k,value in anchor.items()};self.weather_anchor=anchor
        for key,threshold in [('rain_severity',self.config['rain_change']),('wetness',self.config['wetness_change']),('track_temp_c',self.config['temp_change_c'])]:
            a=anchor.get(key);b=point.get(key)
            if a is not None and b is not None and abs(b-a)>=threshold and t-self.last_alert.get(key,-math.inf)>=self.config['alert_cooldown_s']:
                self.alerts.append(dict(time_s=t-self.origin,field=key,from_value=a,to_value=b));self.last_alert[key]=t
                anchor={**anchor,key:b};self.weather_anchor=anchor

    def snapshot(self):
        v=self.previous['vehicle'] if self.previous else {};t=self.previous['et'] if self.previous else 0
        p=dict(self.active) if self.active else dict(self.pits[-1]) if self.pits else None
        if self.active:
            p['measured_interval_s']=t-self.active['entry_et'];p['duration_s']=None if p['partial_start'] or p['gap'] else p['measured_interval_s']
            if p['gap'] or p['partial_start'] or not p['stationary_known']:p['stationary_s']=None
            if p['gap'] or p['partial_start'] or not p['fuel_known']:p['fuel_added_l']=None
            if p['gap'] or p['partial_start'] or not p['energy_known']:p['energy_added_pct']=None
        limit=self.config['pit_limit_kmh'];speed=v.get('speed_kmh');warning=bool(self.active and limit and speed is not None and speed>limit+self.config['pit_tolerance_kmh'])
        laps=[l for l in self.laps if l['qualified'] and l['stint']==self.current_stint]
        old=next((x for x in self.weather if t-x['et']<=self.config['weather_window_s']),None)
        trends={k:v[k]-old[k] if old and old.get(k) is not None and v.get(k) is not None else None for k in WEATHER}
        return dict(pit=p,pit_active=self.active is not None,pit_warning=warning,pit_limit_kmh=limit,stint=self.current_stint,
            stint_elapsed_s=t-(self.stint_start or 0),pace=pace(laps,self.config),weather={k:v.get(k) for k in WEATHER},
            trends=trends,trend_span_s=t-old['et'] if old else 0,alerts=list(self.alerts)[-5:],speed_kmh=speed,
            speed_limiter=v.get('speed_limiter'),pit_state=v.get('pit_state'),fuel_l=v.get('fuel_l'),tyre_front_index=v.get('tyre_front_index'))

def analyze(folder):
    folder=Path(folder);meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if meta.get('status') in ('recording','write_error'):raise ValueError('只分析已正常结束的记录')
    path=folder/'vehicle.csv';config=settings(meta.get('endurance_settings'));monitor=Monitor(config)
    if not path.exists():return dict(version=1,available=False,note='此记录没有进站／天气附加遥测。')
    analysis_path=folder/'session_analysis.json'
    source=json.loads(analysis_path.read_text(encoding='utf-8')).get('laps',[]) if analysis_path.exists() else []
    targets=deque(sorted(source,key=lambda l:l['start_time_s']));contexts={};previous_point=None
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);available=False;last_t=None;history=iter(sorted(meta.get('endurance_settings_history',[]),key=lambda c:c['time_s']));change=next(history,None)
        for r in reader:
            t=number(r.get('session_time_s'))
            if t is None:continue
            if last_t is not None and t<=last_t:raise ValueError('附加遥测时间戳必须严格递增')
            last_t=t
            v={k:number(r.get(k)) for k in (*FIELDS,'fuel_l','virtual_energy_pct')}
            available|=any(v.get(k) is not None for k in ('pit_state','rain_severity','ambient_temp_c','track_temp_c','wetness'))
            elapsed=number(r.get('time_s')) or 0
            while targets and targets[0]['start_time_s']<=elapsed:
                target=targets.popleft();start=target['start_time_s'];context={}
                for k in (*WEATHER,'fuel_l','tyre_front_index','tyre_rear_index'):
                    a=previous_point;b=(elapsed,v)
                    if abs(elapsed-start)<1e-6:context[k]=v.get(k)
                    elif a and 0<b[0]-a[0]<=1.5 and a[0]<=start<=b[0] and a[1].get(k) is not None and b[1].get(k) is not None:
                        context[k]=a[1][k] if k.endswith('_index') else a[1][k]+(b[1][k]-a[1][k])*(start-a[0])/(b[0]-a[0])
                    else:context[k]=None
                contexts[(target['number'],start)]=context
            previous_point=(elapsed,v)
            while change and change['time_s']<=elapsed:
                monitor.configure(change['settings']);change=next(history,None)
            flag=number(r.get('in_pits'));invalid=number(r.get('lap_invalidated'))
            monitor.update(dict(et=t,lap=number(r.get('lap')),lap_start=number(r.get('lap_start_s')),
                distance=number(r.get('lap_distance_m')),in_pits=flag,lap_invalidated=invalid,vehicle=v),force=True)
    pits=list(monitor.pits)
    if monitor.active:
        p=monitor.snapshot()['pit'];p.update(duration_s=None,exit_s=None)
        pits.append(p)
    config=monitor.config
    # The original whole-lap validator remains authoritative for pace.
    laps=[]
    for l in source:
        matched=next((x for x in monitor.laps if x['number']==l['number'] and abs(x['start_time_s']-l['start_time_s'])<.5),None)
        context=(matched or {}).get('context',{})
        if not context:context=contexts.get((l['number'],l['start_time_s']),{})
        stint=1+sum(p['exit_s'] is not None and p['exit_s']<=l['start_time_s'] for p in pits)
        laps.append({k:l[k] for k in ('number','time_s','start_time_s','end_time_s')}|dict(stint=stint,context=context,validity=l.get('validity','unknown')))
    for p in pits:
        affected=[l for l in monitor.laps if l['start_time_s']<=p['entry_s'] and l['end_time_s']>p['entry_s'] or p.get('exit_s') is not None and l['start_time_s']<p['exit_s'] and l['end_time_s']>p['entry_s']]
        nearby=sorted((l for l in laps if compatible(l['context'],p['context'])),key=lambda l:abs(l['start_time_s']-p['entry_s']))[:5]
        enclosed=affected and affected[0]['start_time_s']<=p['entry_s'] and p.get('exit_s') is not None and affected[-1]['end_time_s']>=p['exit_s']
        other=any(q is not p and any(l['start_time_s']<=q['entry_s']<l['end_time_s'] for l in affected) for q in pits)
        baseline=statistics.median(l['time_s'] for l in nearby) if len(nearby)>=3 else None
        loss=sum(l['time_s'] for l in affected)-len(affected)*baseline if enclosed and not other and baseline is not None and not p['gap'] and not p['partial_start'] else None
        p.update(estimated_loss_s=loss,baseline_s=baseline,baseline_laps=[l['number'] for l in nearby],affected_laps=[l['number'] for l in affected],
            loss_note='受影响完整圈相对邻近最多五个同胎种／相近湿度与赛道温度的完整有效圈中位数；至少三圈。包含交通、驾驶和油量差，不能作为官方进站损失。')
        p.pop('entry_et',None)
    stints=[];origin=monitor.origin or 0;end=monitor.previous['et']-origin if monitor.previous else 0
    starts=[0,*[p['exit_s'] for p in pits if p['exit_s'] is not None]]
    for i,start in enumerate(starts):
        finish=next((p['entry_s'] for p in pits if p['entry_s']>=start),end)
        selected=[l for l in laps if l['stint']==i+1 and l['start_time_s']>=start and l['end_time_s']<=finish]
        stints.append(dict(number=i+1,start_s=start,end_s=finish,partial_start=i==0,partial_end=finish==end,
            laps=selected,pace=pace(selected,config)))
    result=dict(version=1,available=available,config=config,settings_history=meta.get('endurance_settings_history',[]),pits=pits,stints=stints,weather_alerts=list(monitor.alerts),
        duration_s=end,note='进站边界精度取决于附加遥测频率；超过 1.5 秒的缺口使精确计时和补给量不可用。雨量是 0–1 强度；风为 SDK 原始世界坐标向量，单位未确认。Stint 仅统计完整有效且未进站的圈。')
    atomic_json(folder/'endurance_analysis.json',result);return result
