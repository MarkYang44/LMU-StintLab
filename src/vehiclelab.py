"""Tyre and stint telemetry, with explicit units and gap-safe fuel estimates."""
import bisect
from collections import deque
import csv
import json
import math
from pathlib import Path
import statistics
from buffers import NullableTable

WHEELS=('fl','fr','rl','rr')
TYRE_FIELDS=('pressure_kpa','inner_c','middle_c','outer_c','carcass_c','wear_fraction','optimal_c','flat','detached')
SENSORS=('fuel_l','fuel_capacity_l','battery_soc_pct','virtual_energy_pct','regen_kw','electric_power_kw','motor_state',
         'completed_laps','max_laps','remaining_s','race_session','speed_kmh','pit_state','speed_limiter','pit_stops',
         'track_length_m','rain_severity','ambient_temp_c','track_temp_c','wetness','wetness_min','wetness_max',
         'wind_x_raw','wind_y_raw','wind_z_raw','tyre_front_index','tyre_rear_index')
COLUMNS=('time_s','session_time_s','lap','lap_distance_m','lap_start_s','lap_invalidated','in_pits',
         *SENSORS,*(w+'_'+f for w in WHEELS for f in TYRE_FIELDS))
DEFAULT_PROFILE=dict(alerts=False,temp_min=60.,temp_max=110.,pressure_min=130.,pressure_max=200.,wear_min=20.)
DEFAULTS=dict(tyres_enabled=False,strategy_enabled=False,record_hz=10,history_laps=5,rate_mode='conservative',
              target_mode='auto',target_value=20.,reserve_l=2.,extra_finish_laps=1.,profiles={})


def number(value,low=-math.inf,high=math.inf):
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and low<=value<=high else None


def settings(value=None):
    value=value or {};result={**DEFAULTS,**value};result['profiles']=dict(value.get('profiles',{}))
    for key,lo,hi in [('record_hz',1,50),('history_laps',1,20),('target_value',0,10000),('reserve_l',0,500),('extra_finish_laps',0,5)]:
        v=number(result[key],lo,hi)
        if v is None:raise ValueError(key+' 超出范围')
        if key in ('record_hz','history_laps') and v!=int(v):raise ValueError(key+' 必须是整数')
        result[key]=int(v) if key in ('record_hz','history_laps') else v
    for key,choices in [('target_mode',('auto','laps','time')),('rate_mode',('median','conservative'))]:
        if result[key] not in choices:raise ValueError(key+' 选项无效')
    for name,p in result['profiles'].items():result['profiles'][name]=profile(p)
    for key in ('tyres_enabled','strategy_enabled'):result[key]=bool(result[key])
    return result


def profile(value=None):
    p={**DEFAULT_PROFILE,**(value or {})}
    for k,lo,hi in [('temp_min',-50,300),('temp_max',-50,300),('pressure_min',0,1000),('pressure_max',0,1000),('wear_min',0,100)]:
        v=number(p[k],lo,hi)
        if v is None:raise ValueError('轮胎阈值超出范围：'+k)
        p[k]=v
    if p['temp_min']>=p['temp_max'] or p['pressure_min']>=p['pressure_max']:raise ValueError('下限必须小于上限')
    p['alerts']=bool(p['alerts']);return p


def load_settings(path):
    try:return settings(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError):return settings()


def extract_vehicle(car,info,player):
    out={}
    for i,w in enumerate(car.mWheels):
        key=WHEELS[i];pressure=number(w.mPressure,0,1000)
        temps=[number(v,150,650) for v in w.mTemperature]
        available=any(v is not None for v in temps) or pressure is not None and pressure>0 or w.mFlat or w.mDetached
        out[key+'_pressure_kpa']=pressure if available else None
        inner,outer=(2,0) if i in (0,2) else (0,2)
        for f,j in [('inner_c',inner),('middle_c',1),('outer_c',outer)]:out[key+'_'+f]=temps[j]-273.15 if temps[j] is not None else None
        carcass=number(w.mTireCarcassTemperature,150,650)
        out[key+'_carcass_c']=carcass-273.15 if carcass is not None else None
        out[key+'_wear_fraction']=number(w.mWear,0,1) if available else None
        out[key+'_optimal_c']=number(w.mOptimalTemp,1,300) if available else None
        out[key+'_flat']=int(bool(w.mFlat)) if available else None
        out[key+'_detached']=int(bool(w.mDetached)) if available else None
    out.update(fuel_l=number(car.mFuel,0,2000),fuel_capacity_l=number(car.mFuelCapacity,.1,2000))
    state=int(car.mElectricBoostMotorState);soc=number(car.mBatteryChargeFraction,0,1)
    out['battery_soc_pct']=soc*100 if soc is not None and (state in (1,2,3) or soc>0) else None
    # LMU's native extension is a fraction; never treat it as battery SoC.
    virtual=number(car.mVirtualEnergy,0,1);out['virtual_energy_pct']=virtual*100 if virtual is not None else None
    out['regen_kw']=number(car.mRegen,-10000,10000) if state in (1,2,3) else None
    torque=number(car.mElectricBoostMotorTorque,-1e5,1e5);rpm=number(car.mElectricBoostMotorRPM,-1e6,1e6)
    out['electric_power_kw']=torque*rpm*math.tau/60000 if state in (1,2,3) and torque is not None and rpm is not None else None
    out['motor_state']=state if state in (1,2,3) else None
    out['completed_laps']=int(player.mTotalLaps) if 0<=player.mTotalLaps<100000 else None
    out['max_laps']=int(info.mMaxLaps) if 0<info.mMaxLaps<100000 else None
    remaining=number(info.mEndET-info.mCurrentET,0,1e7)
    out['remaining_s']=remaining if info.mEndET>0 else None
    out['race_session']=int(10<=int(info.mSession)<=13)
    out.update(speed_kmh=number(math.sqrt(sum(float(getattr(car.mLocalVel,a))**2 for a in ('x','y','z')))*3.6,0,1500),
        pit_state=number(player.mPitState,0,4),speed_limiter=number(car.mSpeedLimiter,0,1),pit_stops=number(player.mNumPitstops,0,10000),
        track_length_m=number(info.mLapDist,100,100000),rain_severity=number(info.mRaining,0,1),
        ambient_temp_c=number(info.mAmbientTemp,-100,100),track_temp_c=number(info.mTrackTemp,-100,150),
        wetness=number(info.mAvgPathWetness,0,1),wetness_min=number(info.mMinPathWetness,0,1),wetness_max=number(info.mMaxPathWetness,0,1),
        tyre_front_index=int(car.mFrontTireCompoundIndex),tyre_rear_index=int(car.mRearTireCompoundIndex))
    for a in ('x','y','z'):out['wind_'+a+'_raw']=number(getattr(info.mWind,a),-1000,1000)
    return out


def demo_vehicle(t):
    v=dict(fuel_l=max(0,45-t*.04),fuel_capacity_l=100,battery_soc_pct=55+15*math.sin(t*.3),
           virtual_energy_pct=max(0,100-t*.05),regen_kw=max(0,math.sin(t*.65)*-80),
           electric_power_kw=math.sin(t*.65)*100,motor_state=2 if math.sin(t*.65)>0 else 3,
           completed_laps=int(t//20),max_laps=20,remaining_s=None,race_session=1)
    for i,w in enumerate(WHEELS):
        temp=78+6*math.sin(t*.15+i)
        v.update({w+'_pressure_kpa':165+4*math.sin(t*.03+i),w+'_inner_c':temp+3,w+'_middle_c':temp,
            w+'_outer_c':temp-3,w+'_carcass_c':74+2*math.sin(t*.04+i),w+'_wear_fraction':max(0,1-t*.00002),
            w+'_optimal_c':85,w+'_flat':0,w+'_detached':0})
    phase=t%100;inside=28<=phase<36;still=30<=phase<34
    v.update(speed_kmh=0 if still else 60 if inside else 160,pit_state=3 if still else 2 if inside else 0,
        speed_limiter=int(inside),pit_stops=int(t//100)+int(phase>=36),track_length_m=2000,
        rain_severity=min(1,max(0,(t-10)/120)),ambient_temp_c=23.,track_temp_c=30-t*.01,
        wetness=min(1,max(0,(t-25)/180)),wetness_min=min(1,max(0,(t-25)/220)),wetness_max=min(1,max(0,(t-25)/150)),
        wind_x_raw=2+math.sin(t*.05),wind_y_raw=0.,wind_z_raw=3.,tyre_front_index=0,tyre_rear_index=0)
    v['fuel_l']=max(0,45-t*.04+10*int(t//100)+max(0,min(10,(phase-30)*2.5)))
    return v


def tyre_alerts(values,p):
    messages=[]
    for w in WHEELS:
        label=w.upper()
        if values.get(w+'_detached'):messages.append(label+' 车轮脱落')
        elif values.get(w+'_flat'):messages.append(label+' 爆胎')
        if not p['alerts']:continue
        t=values.get(w+'_middle_c');pressure=values.get(w+'_pressure_kpa');wear=values.get(w+'_wear_fraction')
        if t is not None and (t<p['temp_min'] or t>p['temp_max']):messages.append(label+(' 胎温低' if t<p['temp_min'] else ' 胎温高'))
        if pressure is not None and not p['pressure_min']<=pressure<=p['pressure_max']:messages.append(label+' 胎压超限')
        if wear is not None and wear*100<p['wear_min']:messages.append(label+' 胎况低')
    return messages


def boundary(samples,t,key,tolerance=.3):
    points=[(s['et'],s.get('vehicle',{}).get(key)) for s in samples]
    points=[(x,y) for x,y in points if y is not None]
    if not points:return None
    exact=next((v for x,v in points if abs(x-t)<1e-6),None)
    if exact is not None:return exact
    if len(points)<2:return points[0][1] if abs(points[0][0]-t)<.02 else None
    i=bisect.bisect_left([x for x,_ in points],t);a,b=points[max(0,min(i-1,len(points)-2)):max(0,min(i-1,len(points)-2))+2]
    if b[0]-a[0]>1.5 or min(abs(a[0]-t),abs(b[0]-t))>tolerance:return None
    return a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0])


class FuelPlanner:
    def __init__(self,config=None):
        self.config=settings(config);self.key=None;self.group=None;self.previous=None;self.history=deque(maxlen=20)
        self.baseline_et=None;self.revision=0

    def configure(self,config):
        self.config=settings(config);self.baseline_et=None;self.revision+=1

    def update(self,s):
        name=s.get('vehicle_name',s.get('vehicle') if isinstance(s.get('vehicle'),str) else '')
        key=(s.get('track'),name,s.get('session'),s.get('driver'),s.get('player_id'))
        if self.key!=key or self.previous and s['et']<self.previous['et']:
            self.key=key;self.group=None;self.previous=None;self.history.clear();self.baseline_et=None
        if self.previous and self.previous['et']==s['et']:return
        if self.baseline_et is None:self.baseline_et=s['et']
        start=s.get('lap_start');length=s.get('track_length',0)
        if start is None or not 0<=start<=s['et']+.1:self.previous=s;return
        if self.group and self.group['start']!=start:
            g=self.group;fuel_end=boundary([*g['tail'],s],start,'fuel_l')
            energy_end=boundary([*g['tail'],s],start,'virtual_energy_pct')
            fuel_used=g['fuel_start']-fuel_end if g['fuel_start'] is not None and fuel_end is not None else None
            energy_used=g['energy_start']-energy_end if g['energy_start'] is not None and energy_end is not None else None
            complete=g['observed'] and g['count']>=3 and length>100 and g['near_start'] and g['distance']>=length*.95
            if complete and not g['bad'] and start>g['start'] and fuel_used is not None and fuel_used>0:
                self.history.append(dict(number=g['number'],time_s=start-g['start'],fuel_used_l=fuel_used,
                    energy_used_pct=energy_used if energy_used is not None and energy_used>0 and not g['energy_reset'] else None))
            self.group=None
        if self.group is None:
            initial=[self.previous,s] if self.previous else [s]
            self.group=dict(start=start,number=s['lap'],observed=abs(s['et']-start)<=.3,
                fuel_start=boundary(initial,start,'fuel_l'),energy_start=boundary(initial,start,'virtual_energy_pct'),
                count=0,distance=0,near_start=False,bad=False,energy_reset=False,tail=deque(maxlen=4))
        g=self.group
        g['bad']|=bool(s.get('in_pits') or s.get('lap_invalidated'))
        if self.previous:
            g['bad']|=s['et']-self.previous['et']>1.5
            for field,flag,tolerance in [('fuel_l','bad',.2),('virtual_energy_pct','energy_reset',.5)]:
                a=self.previous.get('vehicle',{}).get(field);b=s.get('vehicle',{}).get(field)
                if a is not None and b is not None and b>a+tolerance:g[flag]=True
        d=s.get('distance',0)
        near=-20<=d<=min(80,length*.05)
        if near and not g['near_start']:g['distance']=0
        if g['near_start']:
            if g['tail'] and d<g['tail'][-1].get('distance',d)-20:g['bad']=True
            g['distance']=max(g['distance'],d)
        g['near_start']|=near
        g['count']+=1;g['tail'].append(s);self.previous=s

    def estimate(self,s):
        v=s.get('vehicle',{});recent=list(self.history)[-self.config['history_laps']:]
        fuel=v.get('fuel_l');values=[r['fuel_used_l'] for r in recent]
        median=statistics.median(values) if values else None
        rate=max(values) if values and self.config['rate_mode']=='conservative' else median
        duration=statistics.median(r['time_s'] for r in recent) if recent else None
        progress=max(0,min(1,s.get('distance',0)/max(1,s.get('track_length',1))))
        remaining=None;source='自动赛程未知'
        mode=self.config['target_mode'];target=self.config['target_value']
        if s.get('finish') in (1,2,3):remaining=0.;source='本场已结束'
        elif mode=='laps':
            done=v.get('completed_laps')
            if done is not None:remaining=max(0,target-done-progress);source='手动总圈数'
        else:
            seconds=(max(0,target*60-(s['et']-(self.baseline_et if self.baseline_et is not None else s['et']))) if mode=='time' else v.get('remaining_s'))
            if mode=='auto' and not v.get('race_session'):seconds=None
            max_laps=v.get('max_laps') if mode=='auto' and v.get('race_session') else None
            done=v.get('completed_laps')
            candidates=[]
            if max_laps and done is not None:candidates.append(max(0,max_laps-done-progress));source='游戏比赛圈数'
            if seconds is not None and duration:
                candidates.append(max(0,math.ceil(progress+seconds/duration)-progress)+self.config['extra_finish_laps'])
                source='手动剩余时长' if mode=='time' else '游戏计时赛（估算）'
            if candidates:remaining=min(candidates)
        required=remaining*rate+self.config['reserve_l'] if remaining is not None and rate is not None and remaining>0 else 0. if remaining==0 else None
        margin=fuel-required if fuel is not None and required is not None else None
        capacity=v.get('fuel_capacity_l')
        energy=[r['energy_used_pct'] for r in recent if r.get('energy_used_pct') is not None]
        energy_rate=max(energy) if energy and self.config['rate_mode']=='conservative' else statistics.median(energy) if energy else None
        return dict(history=recent,count=len(recent),fuel_l=fuel,median_l=median,rate_l=rate,rate_mode=self.config['rate_mode'],
            remaining_laps=remaining,remaining_source=source,range_laps=fuel/rate if fuel is not None and rate else None,
            required_l=required,margin_l=margin,add_l=max(0,-margin) if margin is not None else None,
            exceeds_capacity=required>capacity if required is not None and capacity is not None else False,
            reserve_l=self.config['reserve_l'],energy_rate_pct=energy_rate,
            energy_range_laps=v.get('virtual_energy_pct')/energy_rate if v.get('virtual_energy_pct') is not None and energy_rate else None)


def sample_row(s,origin):
    basic=dict(time_s=s['et']-origin,session_time_s=s['et'],lap=s['lap'],lap_distance_m=s['distance'],
        lap_start_s=s.get('lap_start'),lap_invalidated=int(bool(s['lap_invalidated'])) if s.get('lap_invalidated') is not None else None,in_pits=int(bool(s['in_pits'])) if s.get('in_pits') is not None else None)
    return [basic.get(k,s.get('vehicle',{}).get(k)) for k in COLUMNS]


NATIVE_CHANNELS=('Fuel Level','Virtual Energy','SoC','Regen Rate','TyresPressure','Tyres Wear',
                 'TyresTempLeft','TyresTempCentre','TyresTempRight','TyresCarcassTemp',
                 'Ambient Temperature','Track Temperature','Minimum Path Wetness','Maximum Path Wetness','Average Path Wetness','Rain Severity')


def native_values(series,t,lookup,offset=0):
    """Use declared native units; unknown units remain missing, never guessed."""
    out={k:None for k in SENSORS}
    out.update({w+'_'+f:None for w in WHEELS for f in TYRE_FIELDS})
    def values(name,kind):
        s=series.get(name)
        if not s:return None
        raw=lookup(s,t,offset if s['event'] else 0)
        if raw is None:return None
        unit=s['unit'].strip().casefold().replace(' ','')
        maps={'fuel':{'l':1,'litre':1,'liter':1,'litres':1,'liters':1},
            'pressure':{'kpa':1,'pa':.001,'bar':100,'psi':6.894757293},
            'percent':{'%':1,'percent':1,'pct':1,'fraction':100,'ratio':100,'1':100},
            'wear':{'%':.01,'percent':.01,'fraction':1,'ratio':1,'1':1},
            'power':{'kw':1,'w':.001}}
        if kind=='temp':
            if unit in ('k','kelvin'):return [number(v-273.15,-123.15,376.85) for v in raw]
            if unit in ('c','°c','celsius','degc'):return [number(v,-123.15,376.85) for v in raw]
            return None
        multiplier=maps[kind].get(unit)
        if multiplier is None:return None
        low,high={'fuel':(0,2000),'pressure':(0,1000),'percent':(0,100),'wear':(0,1),'power':(-10000,10000)}[kind]
        return [number(v*multiplier,low,high) for v in raw]
    for name,key,kind in [('Fuel Level','fuel_l','fuel'),('Virtual Energy','virtual_energy_pct','percent'),
                          ('SoC','battery_soc_pct','percent'),('Regen Rate','regen_kw','power')]:
        v=values(name,kind)
        if v:out[key]=v[0]
    for name,key,kind in [('Ambient Temperature','ambient_temp_c','temp'),('Track Temperature','track_temp_c','temp'),
        ('Minimum Path Wetness','wetness_min','wear'),('Maximum Path Wetness','wetness_max','wear'),
        ('Average Path Wetness','wetness','wear'),('Rain Severity','rain_severity','wear')]:
        converted=values(name,kind)
        if converted:out[key]=converted[0]
    for name,field,kind in [('TyresPressure','pressure_kpa','pressure'),('Tyres Wear','wear_fraction','wear'),
                           ('TyresTempCentre','middle_c','temp'),('TyresCarcassTemp','carcass_c','temp')]:
        v=values(name,kind)
        if v and len(v)==4:
            for w,x in zip(WHEELS,v):out[w+'_'+field]=x
    left=values('TyresTempLeft','temp');right=values('TyresTempRight','temp')
    if left and right and len(left)==len(right)==4:
        for i,w in enumerate(WHEELS):
            out[w+'_inner_c']=right[i] if i in (0,2) else left[i]
            out[w+'_outer_c']=left[i] if i in (0,2) else right[i]
    return out


def load_recording(folder):
    path=Path(folder)/'vehicle.csv'
    if not path.exists():return None
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);columns=[k for k in COLUMNS if k not in ('time_s','session_time_s')]
        origin=None
        def records():
            nonlocal origin
            last=-math.inf
            for r in reader:
                t=number(r.get('session_time_s'))
                if t is None or t<=last:raise ValueError('附加遥测时间戳无效')
                last=t
                if origin is None:origin=t-(number(r.get('time_s')) or 0)
                yield [t,*[number(r.get(k)) for k in columns]]
        from analysis_spool import DiskTable
        data=DiskTable(records(),len(columns)+1,path.parent,nullable=True)
    meta=json.loads((Path(folder)/'session.json').read_text(encoding='utf-8'))
    return dict(version=1,columns=columns,data=data,record_hz=meta.get('vehicle_telemetry',{}).get('target_hz'),
        source=meta.get('source'),time_origin_s=origin or 0,profile=meta.get('vehicle_profile',DEFAULT_PROFILE),
        strategy=meta.get('vehicle_strategy',{}),strategy_history=meta.get('vehicle_settings_history',[]))


def lap_telemetry(best,bundle=None):
    if bundle:
        rows=bundle['data']
        a=max(0,bisect.bisect_left(rows,best['start_s'],key=lambda r:r[0])-1)
        b=min(len(rows),bisect.bisect_right(rows,best['end_s'],key=lambda r:r[0])+1)
        payload={**bundle,'data':[[round(rows[i][0]-best['start_s'],6),*rows[i][1:]] for i in range(a,b)]}
    else:
        columns=['fuel_l'];data=[];last=-math.inf
        for r in best['rows']:
            if 'fuel_l' in r and r['session_time_s']-last>=.1-1e-8:
                data.append([round(r['session_time_s']-best['start_s'],6),r['fuel_l']]);last=r['session_time_s']
        if not data:return None
        payload=dict(version=1,columns=columns,data=data,record_hz=None,source='已有输入 CSV 的燃油通道',profile=DEFAULT_PROFILE)
    payload['summary']=summarize(payload,0,best['time_s']);return payload


def summarize(bundle,start,end):
    columns=bundle['columns'];rows=bundle['data'];result={}
    for j,k in enumerate(columns,1):
        first=previous=None;low=math.inf;high=-math.inf;integral=weight=0.
        for r in rows:
            t,v=r[0],r[j]
            if not start<=t<=end or v is None:continue
            if first is None:first=v
            if previous is not None:
                dt=t-previous[0]
                if 0<dt<=1.5:integral+=(previous[1]+v)*.5*dt;weight+=dt
            low=min(low,v);high=max(high,v);previous=(t,v)
        if previous is None:continue
        result[k]=dict(min=low,max=high,mean=integral/weight if weight else first,start=first,end=previous[1])
    for key in ('fuel_l','virtual_energy_pct'):
        j=columns.index(key)+1 if key in columns else None
        if j is None:continue
        points=[(r[0],r[j]) for r in rows if r[j] is not None]
        def at(t):
            if not points:return None
            exact=next((v for x,v in points if abs(x-t)<1e-6),None)
            if exact is not None:return exact
            if len(points)<2:return points[0][1] if abs(points[0][0]-t)<.02 else None
            i=bisect.bisect_left(points,t,key=lambda p:p[0]);p=max(0,min(i-1,len(points)-2));a,b=points[p:p+2]
            if b[0]-a[0]>1.5 or min(abs(a[0]-t),abs(b[0]-t))>.3:return None
            return a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0])
        a=at(start);b=at(end)
        reset=any(y[j] is not None and x[j] is not None and y[j]>x[j]+(.2 if key=='fuel_l' else .5) for x,y in zip(rows,rows[1:]) if start<=y[0]<=end)
        gaps=any(y[0]-x[0]>1.5 for x,y in zip(rows,rows[1:]) if x[0]<end and y[0]>start)
        result[key+'_used']=dict(value=a-b if a is not None and b is not None and not reset and not gaps else None,
            reset=reset,gap=gaps,boundary_estimate=True)
    return result


def script(folder):return (Path(folder)/'vehicleview.js').read_text(encoding='utf-8')
