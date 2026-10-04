"""All eligible laps, reproducibility and genuine median-lap references."""
import bisect
import json
import math
from pathlib import Path
import statistics
from laps import comparison_data,trajectory_data,extract_best,DATA_COLUMNS,FORMAT,write_json,safe_name

CONDITION_RULES={'fuel_l':2,'tyre_compound':0,'track_temp_c':5,'wetness':.1,'tc_level':0,'abs_level':0}
NATIVE_NAMES={'fuel_l':'Fuel Level','tyre_compound':'TyresCompound','track_temp_c':'Track Temperature',
              'wetness':'Minimum Path Wetness','tc_level':'TCLevel','abs_level':'ABSLevel'}


def condition_check(a,b):
    known=[];unknown=[];different=[]
    for key,tolerance in CONDITION_RULES.items():
        x,y=a.get(key),b.get(key)
        if not isinstance(x,(int,float)) or not isinstance(y,(int,float)) or not all(map(math.isfinite,(x,y))):unknown.append(key)
        else:
            known.append(key)
            if abs(x-y)>tolerance:different.append(key)
    return dict(allowed=not different,known=known,unknown=unknown,different=different)


def lap_conditions(rows,native=None,start=0,offset=0):
    result={}
    for k in CONDITION_RULES:
        r=next((r for r in rows if k in r),None)
        if r:result[k]=r[k]
    if native:
        for key,name in NATIVE_NAMES.items():
            s=native.get('channels',{}).get(name)
            if s and s['data']:
                shift=offset if s['event'] else 0
                times=[r[0]-shift for r in s['data']];i=max(0,bisect.bisect_right(times,start)-1)
                if times[i]<=start+.2:result[key]=s['data'][i][1]
    return result


def spread(values):
    if not values:return dict(count=0,median=None,std=None,min=None,max=None)
    return dict(count=len(values),median=statistics.median(values),std=statistics.pstdev(values),min=min(values),max=max(values))


def actions(rows):
    """Time-based debounce; cannot infer grip or the cause of a correction."""
    results={}
    for prefix,names in [('raw',('throttle','brake','steering')),('filtered',('filtered_throttle','filtered_brake','filtered_steering'))]:
        throttle,brake,steering=names;slopes=[];corrections=0;lift=0;last_sign=0;last_change=-100
        extreme=rows[0].get(steering,0) if rows else 0
        for a,b in zip(rows,rows[1:]):
            dt=b['session_time_s']-a['session_time_s'];t=b['session_time_s']
            if not 0<dt<=.2:continue
            change=(b[brake]-a[brake])/dt
            if a[brake]>.05 and change<-.02:slopes.append(-change*100)
            value=b.get(steering,0);ds=value-extreme
            sign=1 if ds>.025 else -1 if ds<-.025 else 0
            if sign and sign!=last_sign:
                if last_sign and t-last_change>.08:corrections+=1
                last_change=t;last_sign=sign;extreme=value
            elif last_sign==1:extreme=max(extreme,value)
            elif last_sign==-1:extreme=min(extreme,value)
            if a[throttle]>.8 and b[throttle]<.6:lift+=1
        # Sustained lifts, not only adjacent abrupt transitions.
        armed=False;since=None;lift=0
        for r in rows:
            if r[throttle]>.8:armed=True;since=None
            elif armed and r[throttle]<.6:
                if since is None:since=r['session_time_s']
                if r['session_time_s']-since>=.06:lift+=1;armed=False
        results[prefix]=dict(brake_release_pct_s=statistics.median(slopes) if slopes else None,
            steering_corrections=corrections,throttle_lifts=lift)
    dt_sum=0;differences=[0,0,0];abs_time=tc_time=0;abs_known=tc_known=False
    for a,b in zip(rows,rows[1:]):
        dt=b['session_time_s']-a['session_time_s']
        if not 0<dt<=.2:continue
        dt_sum+=dt
        for i,(r,f) in enumerate(zip(('throttle','brake','steering'),('filtered_throttle','filtered_brake','filtered_steering'))):
            if r in a and f in a:differences[i]+=abs(a[r]-a[f])*dt
        if 'abs_active' in a:abs_known=True;abs_time+=bool(a['abs_active'])*dt
        if 'tc_active' in a:tc_known=True;tc_time+=bool(a['tc_active'])*dt
    results.update(input_difference_pct=[v/max(1e-9,dt_sum)*100 for v in differences],
        abs_active_s=abs_time if abs_known else None,tc_active_s=tc_time if tc_known else None)
    return results


def analyze_session(folder):
    folder=Path(folder);meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if meta.get('status')=='recording':raise ValueError('请等本场记录结束后再分析')
    if meta.get('status')=='write_error':raise ValueError('该记录存在写盘错误，保留原 CSV 供检查，不生成可信参考')
    native=json.loads((folder/'native_channels.json').read_text(encoding='utf-8')) if (folder/'native_channels.json').exists() else None
    from vehiclelab import load_recording,lap_telemetry
    vehicle_bundle=load_recording(folder)
    summaries=[];recent=[]
    clock_origin=None
    def collect(best):
        nonlocal clock_origin
        if clock_origin is None:clock_origin=best['rows'][0]['session_time_s']-best['rows'][0].get('time_s',best['rows'][0]['session_time_s'])
        condition=lap_conditions(best['rows'],native,best['start_s'],native.get('event_offset_s',0) if native else 0)
        action=actions(best['rows']);data=comparison_data(best)
        brake=next((r[0] for r in data if r[3]>=.05),None)
        full=next((r[0] for r in data if r[2]>=.9),None)
        info=dict(number=best['number'],time_s=best['time_s'],validity=best['validity'],conditions=condition,
            action=action,minimum_speed=min(r[6] for r in data),first_brake_m=brake,first_full_m=full,
            start_time_s=best['start_s']-clock_origin,end_time_s=best['end_s']-clock_origin,
            profile=[data[round(i*(len(data)-1)/max(1,min(1001,len(data))-1))] for i in range(min(1001,len(data)))])
        vehicle=lap_telemetry(best,vehicle_bundle)
        if vehicle:info['vehicle_summary']=vehicle['summary']
        summaries.append(info)
        # Keep at most five actual candidates; representative is an observed lap.
        recent.append(info);del recent[:-5]
    _,candidates,error=extract_best(folder/'inputs.csv',collect,retain_best=False)
    latest=recent[-1]['conditions'] if recent else {}
    training=[i for i in recent if condition_check(i['conditions'],latest)['allowed']]
    times=[i['time_s'] for i in training];stats=spread(times);reference=None
    if len(training)>=3:
        info=min(training,key=lambda i:abs(i['time_s']-stats['median']))
        selected=[]
        def select(best):
            if best['number']==info['number'] and abs(best['start_s']-clock_origin-info['start_time_s'])<1e-6:
                selected.append(best)
        extract_best(folder/'inputs.csv',select,retain_best=False)
        best=selected[0]
        refinfo={k:best[k] for k in ('number','time_s','validity','timing_source','distance_source','cadence_s')}
        refinfo.update(track_length_m=best['length_m'],sample_count=len(best['rows']),start_session_time_s=best['start_s'],end_session_time_s=best['end_s'])
        data=comparison_data(best)
        reference=dict(format=FORMAT,version=1,id=folder.name+':stable:'+str(info['number']),session={k:meta.get(k,'') for k in ('track','vehicle','driver','started_utc','source')},
            lap=refinfo,data_columns=DATA_COLUMNS,data=data,conditions=info['conditions'],reference_kind='stable',
            stability=stats,actions=info['action'],trajectory=trajectory_data(best,data))
        reference['vehicle_telemetry']=lap_telemetry(best,vehicle_bundle)
        if reference['trajectory'] and meta.get('position_source'):reference['trajectory']['source']=meta['position_source']
        name=f"Stable_Lap_{info['number']}_{safe_name(meta['vehicle'])}_{safe_name(meta['track'])}.lap.json"
        write_json(folder/name,reference)
    else:name=None
    detail=dict(version=1,laps=summaries,candidates=candidates,error=error,recent_stability=stats,
        stable_reference_file=name,conditions_unknown=condition_check(latest,latest)['unknown'],
        metrics={k:spread([i[k] for i in training if i[k] is not None]) for k in ('minimum_speed','first_brake_m','first_full_m')},
        note='最近最多五个完整圈；明确条件不同的圈排除。稳定参考为实测中位附近的一圈；不足三圈不生成。交通需人工标记。动作计数是阈值统计，不自动认定驾驶错误。')
    write_json(folder/'session_analysis.json',detail);return detail
