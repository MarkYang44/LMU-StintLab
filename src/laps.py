"""Offline fastest-lap export. Never runs on the telemetry polling thread."""
import bisect
import csv
import html
import json
import math
from pathlib import Path
import statistics
import threading

FORMAT = 'inputscope.fastest-lap'
DATA_COLUMNS = ['distance_m','lap_time_s','throttle','brake','filtered_throttle','filtered_brake','speed_kmh']


def safe_name(value):
    return ''.join('_' if c in '<>:"/\\|?*' or ord(c)<32 else c for c in str(value)).strip(' .')[:40] or 'Unknown'


def write_json(path, value):
    path = Path(path)
    pending = path.with_name(path.name+'.'+str(threading.get_ident())+'.pending')
    pending.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    pending.replace(path)


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            try:
                numbers = {'time_s','session_time_s','lap','lap_distance_m','throttle','brake',
                           'steering','filtered_throttle','filtered_brake','filtered_steering','speed_kmh',
                           'lap_start_s','lap_invalidated','in_pits','track_length_m',
                           'world_x_m','world_y_m','world_z_m','fuel_l','tyre_compound','track_temp_c',
                           'wetness','tc_level','abs_level','tc_active','abs_active','gear'}
                values = {key:float(value) for key,value in row.items() if key in numbers and value not in ('',None)}
                if not all(math.isfinite(v) for v in values.values()):
                    raise ValueError('Non-finite telemetry')
                values['utc'] = row['utc']
                if not {'session_time_s','lap','lap_distance_m','throttle','brake',
                        'filtered_throttle','filtered_brake','speed_kmh'}.issubset(values):
                    raise ValueError('Required telemetry columns missing')
                yield values
            except (ValueError,TypeError,KeyError) as error:
                raise ValueError('CSV contains an incomplete or invalid telemetry row') from error


def lap_key(row):
    start = row.get('lap_start_s')
    if start is not None and 0<=start<=row['session_time_s']+.1:
        return ('timer',start)
    return ('counter',int(row['lap']))


def extract_best(csv_path,on_candidate=None,include_flagged=False):
    """Require two observed boundaries, or an exact recorded first-lap start.

    Legacy CSVs use successive lap-counter transitions and never promote the
    first or last partial group. Scoring distance can lag the telemetry timer;
    discard the previous lap's leading tail and interpolate its staircase.
    """
    inferred_length = 0
    known_lengths = []
    for row in read_rows(csv_path):
        inferred_length = max(inferred_length,row['lap_distance_m'])
        length = row.get('track_length_m',0)
        if length>100 and len(known_lengths)<1000:
            known_lengths.append(length)
    length = statistics.median(known_lengths) if known_lengths else inferred_length
    if length<=100:
        return None,[], 'No usable track distance'
    best = None
    candidates = []
    group = []
    key = None
    seen_boundary = False

    def complete(next_row):
        nonlocal best
        timer = key[0]=='timer' and lap_key(next_row)[0]=='timer'
        start = key[1] if timer else group[0]['session_time_s']
        end = lap_key(next_row)[1] if timer else next_row['session_time_s']
        duration = end-start
        number = int(group[0]['lap'])
        checked = all('lap_invalidated' in r and 'in_pits' in r for r in group)
        reason = None
        intervals = [b['session_time_s']-a['session_time_s'] for a,b in zip(group,group[1:])]
        positive = [d for d in intervals if d>0]
        cadence = statistics.median(positive) if positive else 0
        threshold = min(2.5,max(1.5,cadence*3))
        tolerance = max(.05,min(1.5,cadence*1.5))
        if duration<=0 or end>next_row['session_time_s']+.1:
            reason = 'timing reset'
        elif not seen_boundary and (not timer or abs(group[0]['session_time_s']-start)>tolerance):
            reason = 'start of lap missing'
        elif len(group)<3 or not positive or any(d<=0 for d in intervals):
            reason = 'insufficient or nonmonotonic samples'
        elif max(positive+[next_row['session_time_s']-group[-1]['session_time_s']])>threshold:
            reason = 'telemetry gap'
        elif not include_flagged and any(r.get('lap_invalidated',0)>0 for r in group):
            reason = 'invalidated lap'
        elif not include_flagged and any(r.get('in_pits',0)>0 for r in group):
            reason = 'pit lane lap'
        # Initial high distances may belong to the preceding lap's stale scoring
        # update. Only a genuine near-zero section followed by near-full distance
        # constitutes a recorded complete circuit.
        beginning = next((i for i,r in enumerate(group)
                          if -20<=r['lap_distance_m']<=min(80,length*.05)),None)
        usable = group[beginning:] if beginning is not None else []
        if reason is None and (not usable or max(r['lap_distance_m'] for r in usable)<length*.95):
            reason = 'incomplete distance coverage'
        if reason is None and any(b['lap_distance_m']<a['lap_distance_m']-20
                                  for a,b in zip(usable,usable[1:])):
            reason = 'distance moved backwards or reset'
        info = dict(number=number,time_s=round(duration,6),eligible=reason is None,
                    exclusion=reason,validity='verified' if checked else 'unverified_legacy',
                    lap_invalidated=any(r.get('lap_invalidated',0)>0 for r in group),
                    in_pits=any(r.get('in_pits',0)>0 for r in group))
        candidates.append(info)
        if reason is None:
            value = dict(**info,start_s=start,end_s=end,rows=list(group),
                        next_row=dict(next_row),length_m=length,
                        timing_source='game_lap_start' if timer else 'lap_counter_estimate',
                        distance_source='game_track_length' if known_lengths else 'recorded_maximum_estimate',
                        first_distance_index=beginning,cadence_s=cadence)
            if on_candidate:on_candidate(value)
            if best is None or duration<best['time_s']:best=value

    for row in read_rows(csv_path):
        next_key = lap_key(row)
        if group and next_key!=key:
            complete(row)
            group = []
            seen_boundary = True
        key = next_key
        group.append(row)
    if group:
        candidates.append(dict(number=int(group[0]['lap']),eligible=False,exclusion='end of lap missing'))
    return best,candidates,None


def comparison_data(best):
    rows = best['rows']
    start,end,length = best['start_s'],best['end_s'],best['length_m']
    knots = [(start,0)]
    for r in rows[best['first_distance_index']:]:
        t,d = r['session_time_s'],max(0,min(length,r['lap_distance_m']))
        if start<t<end and d>knots[-1][1]+.01:
            knots.append((t,d))
    knots.append((end,length))
    times = [t for t,_ in knots]
    control_names = ('throttle','brake','filtered_throttle','filtered_brake','speed_kmh')

    def boundary(t,a,b,d):
        fraction = max(0,min(1,(t-a['session_time_s'])/max(1e-9,b['session_time_s']-a['session_time_s'])))
        return [round(d,3),round(t-start,6),*[round(a[n]+fraction*(b[n]-a[n]),6) for n in control_names]]

    data = [boundary(start,rows[0],rows[min(1,len(rows)-1)],0)]
    index = 0
    for row in rows:
        t = row['session_time_s']
        if not start<t<end:
            continue
        index = max(index,bisect.bisect_right(times,t)-1)
        index = min(index,len(knots)-2)
        a,b = knots[index:index+2]
        d = a[1]+(b[1]-a[1])*(t-a[0])/(b[0]-a[0])
        data.append([round(d,3),round(t-start,6),*[round(row[n],6) for n in control_names]])
    data.append(boundary(end,rows[-1],best['next_row'],length))
    return data


def curve_svg(lap):
    meta,info,data = lap['session'],lap['lap'],lap['data']
    title = f"{meta['track']} · {meta['vehicle']} · 第 {info['number']} 圈 · {info['time_s']:.3f} s"
    output = ['<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="620" viewBox="0 0 1600 620">',
              '<rect width="1600" height="620" fill="#0c111a"/>',
              '<g font-family="Arial,Microsoft YaHei,sans-serif" fill="#dce6f7">',
              '<text x="65" y="44" font-size="25">'+html.escape(title)+'</text>',
              '<text x="65" y="73" font-size="15">'+html.escape(f"{meta.get('driver','')} · {meta.get('started_utc','')} · "+('已记录有效性' if info['validity']=='verified' else '旧日志：有效性未验证')+' · 原始输入 / 距离对齐')+'</text>']
    for column,name,color,top in ((2,'THROTTLE / 油门','#34e59a',125),(3,'BRAKE / 刹车','#ff596b',365)):
        output.append(f'<text x="65" y="{top-15}" font-size="18" fill="{color}">{name}</text>')
        for percent in (0,50,100):
            y = top+170*(1-percent/100)
            output.append(f'<path d="M65 {y}H1545" stroke="#27354b"/><text x="18" y="{y+5}" font-size="13">{percent}%</text>')
        # Per-pixel extrema retain braking spikes in the exported full-lap image.
        buckets = {}
        for row in data:
            x = 65+round(row[0]/info['track_length_m']*1480)
            low,high = buckets.get(x,(row[column],row[column]))
            buckets[x] = min(low,row[column]),max(high,row[column])
        path = []
        for x,(low,high) in sorted(buckets.items()):
            path.extend((f'{x},{top+170*(1-low):.2f}',f'{x},{top+170*(1-high):.2f}'))
        output.append(f'<polyline points="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="1.8"/>')
        for i in range(6):
            x = 65+i*1480/5
            output.append(f'<text x="{x-10}" y="{top+196}" font-size="13">{info["track_length_m"]*i/5:.0f} m</text>')
    output.append('</g></svg>')
    return ''.join(output)


def trajectory_data(best, data):
    """A bounded 50 Hz map track; full XYZ samples remain in the source CSV."""
    start,end = best['start_s'],best['end_s']
    times = [r[1] for r in data]
    points = []
    def add(t,x,z,force=False):
        t = max(0,min(end-start,t))
        if points and (t<=points[-1][0] or not force and t-points[-1][0]<.02-1e-8):
            return
        index = min(len(data)-1,bisect.bisect_left(times,t))
        a,b = data[max(0,index-1)],data[index]
        f = max(0,min(1,(t-a[1])/max(1e-9,b[1]-a[1])))
        d = a[0]+f*(b[0]-a[0])
        points.append([round(t,6),round(d,3),round(x,3),round(z,3)])
    rows = best['rows']
    for row in rows:
        if all(k in row for k in ('world_x_m','world_z_m')) and start<=row['session_time_s']<end:
            add(row['session_time_s']-start,row['world_x_m'],row['world_z_m'])
    a,b = rows[-1],best['next_row']
    if all(k in row for row in (a,b) for k in ('world_x_m','world_z_m')) and 0<b['session_time_s']-a['session_time_s']<=1.5:
        f = max(0,min(1,(end-a['session_time_s'])/(b['session_time_s']-a['session_time_s'])))
        add(end-start,a['world_x_m']+f*(b['world_x_m']-a['world_x_m']),
            a['world_z_m']+f*(b['world_z_m']-a['world_z_m']),True)
    if len(points)<3 or max(max(p[k] for p in points)-min(p[k] for p in points) for k in (2,3))<10:
        return None
    return dict(columns=['lap_time_s','distance_m','world_x_m','world_z_m'],points=points,
                source='recorded_world_xz',max_gap_s=1.5,sample_target_hz=50)


def write_compare(path, template, laps=(), status=None,reference_id=None):
    value = dict(laps=list(laps),status=status)
    if reference_id is not None:value['reference_id']=reference_id
    payload = json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    template = Path(template)
    source = template.read_text(encoding='utf-8').replace('/*LAP_DATA*/null',payload)
    if '/*TRACK_VIEW_JS*/' in source:
        source = source.replace('/*TRACK_VIEW_JS*/',track_script(template.parent))
    if '/*VEHICLE_VIEW_JS*/' in source:
        from vehiclelab import script
        source=source.replace('/*VEHICLE_VIEW_JS*/',script(template.parent))
    path = Path(path)
    pending = path.with_name(path.name+'.'+str(threading.get_ident())+'.pending')
    pending.write_text(source,encoding='utf-8')
    pending.replace(path)


def track_script(folder):
    folder = Path(folder)
    catalog = (folder/'tracks'/'catalog.json').read_text(encoding='utf-8').replace('<','\\u003c')
    return (folder/'laplab.js').read_text(encoding='utf-8')+'\n'+(folder/'trackview.js').read_text(encoding='utf-8').replace('/*TRACK_CATALOG*/null',catalog)


def library_laps(root, current=None):
    """Only embed two compatible sessions. Further laps can be imported locally."""
    summaries = []
    root=Path(root)
    roots=[root]
    if root.name in ('Logs','ImportedLogs','RecoveredLogs'):
        roots=[root.parent/n for n in ('Logs','ImportedLogs','RecoveredLogs')]
    for path in (p for folder in roots for p in folder.glob('*/fastest_lap_summary.json')):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if value.get('status')=='saved':
                summaries.append((path.parent/value['file'],value))
        except (OSError,ValueError):
            continue
    if current is None and summaries:
        newest = max(summaries,key=lambda pair:pair[1]['session'].get('started_utc',''))[0]
        current = json.loads(newest.read_text(encoding='utf-8'))
    if current is None:
        return []
    compatible = [(path,v) for path,v in summaries if path.parent.name+':'+str(v['lap']['number'])!=current['id']
                  and all(v['session'].get(k)==current['session'].get(k) for k in ('track','vehicle'))]
    previous = json.loads(min(compatible,key=lambda pair:pair[1]['lap']['time_s'])[0].read_text(encoding='utf-8')) if compatible else None
    return [current,previous] if previous else [current]


def finished_metadata(folder):
    folder = Path(folder)
    metadata = json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if metadata.get('status')=='recording':
        raise ValueError('Wait until this session has finished recording')
    if metadata.get('status')=='write_error':
        raise ValueError('Recording has a writer error; no reliable reference can be exported')
    return metadata


def lap_record(folder,best,metadata=None,native=None,kind='fastest'):
    """Common full-resolution payload for fastest and explicitly selected laps."""
    folder=Path(folder)
    if metadata is None:metadata=finished_metadata(folder)
    info = {k:best[k] for k in ('number','time_s','validity','timing_source','distance_source','cadence_s')}
    info.update(track_length_m=round(best['length_m'],3),start_session_time_s=best['start_s'],
                end_session_time_s=best['end_s'],sample_count=sum(best['start_s']<=r['session_time_s']<best['end_s'] for r in best['rows']),
                boundary_interpolation=True,lap_number_source='LMU mLapNumber / inputs.csv',
                lap_invalidated=bool(best.get('lap_invalidated')),in_pits=bool(best.get('in_pits')))
    result = dict(format=FORMAT,version=1,id=folder.name+':'+str(info['number']),
                  session={k:metadata.get(k,'') for k in ('track','vehicle','driver','started_utc',
                           'ended_utc','session','source','end_reason')},lap=info,
                  data_columns=DATA_COLUMNS,data=comparison_data(best),reference_kind=kind)
    result['trajectory'] = trajectory_data(best,result['data'])
    from sessionlab import lap_conditions,actions
    if native is None and (folder/'native_channels.json').exists():native=json.loads((folder/'native_channels.json').read_text(encoding='utf-8'))
    result['conditions']=lap_conditions(best['rows'],native,best['start_s'],native.get('event_offset_s',0) if native else 0)
    result['actions']=actions(best['rows'])
    from vehiclelab import lap_telemetry,load_recording
    result['vehicle_telemetry']=lap_telemetry(best,load_recording(folder))
    if result['trajectory'] and metadata.get('position_source'):result['trajectory']['source'] = metadata['position_source']
    if native:
        result['native_context'] = dict(metadata=metadata.get('native_metadata',{}),source=metadata.get('native_source',{}),channels={})
        for channel,series in native['channels'].items():
            offset = native.get('event_offset_s',0) if series['event'] else 0
            rows = series['data'];times = [r[0]-offset for r in rows]
            first = max(0,bisect.bisect_right(times,best['start_s'])-1)
            last = bisect.bisect_right(times,best['end_s'])
            result['native_context']['channels'][channel] = dict(unit=series['unit'],event=series['event'],
                frequency_hz=series['frequency_hz'],data=[[round(r[0]-offset-best['start_s'],6),*r[1:]] for r in rows[first:last]])
    return result


def write_lap_csv(path,best,metadata):
    with Path(path).open('w',encoding='utf-8',newline='') as stream:
        fields=list(dict.fromkeys(k for r in best['rows'] for k in r))
        basic={k:metadata.get(k,'') for k in ('track','vehicle','driver','started_utc')}
        writer=csv.DictWriter(stream,fieldnames=[*basic,'lap_time_s',*fields]);writer.writeheader()
        for row in best['rows']:
            if best['start_s']<=row['session_time_s']<best['end_s']:
                writer.writerow(dict(**basic,lap_time_s=round(row['session_time_s']-best['start_s'],6),**row))


def complete_laps(folder):
    """Only structurally complete laps; racing validity flags remain explicit."""
    folder=Path(folder);finished_metadata(folder)
    _,candidates,error=extract_best(folder/'inputs.csv',include_flagged=True)
    counts={}
    for v in candidates:counts[v['number']]=counts.get(v['number'],0)+1
    for v in candidates:
        if v['eligible'] and counts[v['number']]>1:v.update(eligible=False,exclusion='ambiguous repeated lap number')
    return dict(laps=[v for v in candidates if v['eligible']],candidates=candidates,error=error)


def export_selected_laps(folder,numbers,template=None):
    """Extract one or two specified complete laps; never rewrites original exports."""
    if (not isinstance(numbers,(list,tuple)) or not 1<=len(numbers)<=2 or
            any(isinstance(n,bool) or not isinstance(n,int) or n<0 for n in numbers)):
        raise ValueError('请选择一个或两个非负整数圈号')
    if len(set(numbers))!=len(numbers):raise ValueError('圈 A 和圈 B 必须选择不同圈')
    folder=Path(folder);metadata=finished_metadata(folder);selected={};counts={}
    def collect(best):
        if best['number'] in numbers:selected[best['number']]=best
    _,candidates,error=extract_best(folder/'inputs.csv',collect,include_flagged=True)
    for v in candidates:counts[v['number']]=counts.get(v['number'],0)+1
    for n in numbers:
        if counts.get(n,0)>1:raise ValueError(f'第 {n} 圈的圈号重复，无法唯一提取')
        if n not in selected:
            item=next((v for v in candidates if v['number']==n),None)
            reason={'start of lap missing':'缺少圈起点','end of lap missing':'缺少圈终点','telemetry gap':'遥测存在缺口',
                'incomplete distance coverage':'距离覆盖不完整','timing reset':'计时重置',
                'insufficient or nonmonotonic samples':'采样不足或时间倒退','distance moved backwards or reset':'距离倒退或重置'}.get(item.get('exclusion') if item else '',error or '记录中没有该圈')
            raise ValueError(f'第 {n} 圈不是可提取的完整圈：{reason}')
    native=json.loads((folder/'native_channels.json').read_text(encoding='utf-8')) if (folder/'native_channels.json').exists() else None
    records=[lap_record(folder,selected[n],metadata,native,'selected') for n in numbers]
    output=folder/'SelectedLaps';output.mkdir(exist_ok=True);exports=[]
    for n,value in zip(numbers,records):
        stem=f"Selected_Lap_{n}_{safe_name(metadata.get('vehicle'))}_{safe_name(metadata.get('track'))}"
        json_path=output/(stem+'.lap.json');csv_path=output/(stem+'.csv')
        write_json(json_path,value);write_lap_csv(csv_path,selected[n],metadata)
        exports.append(dict(number=n,json=str(json_path),csv=str(csv_path)))
    page=None
    if template is not None:
        page=output/('Compare_Laps_'+('_'.join(map(str,numbers)))+'.html')
        write_compare(page,template,records,'selected_complete_laps',reference_id=records[0]['id'])
    return dict(folder=str(output),exports=exports,comparison=str(page) if page else None)


def export_fastest(folder, template, library=None):
    folder=Path(folder);metadata=finished_metadata(folder)
    best,candidates,error = extract_best(folder/'inputs.csv')
    summary = dict(status='saved' if best else 'no_complete_lap',candidates=candidates,error=error)
    result = None
    if best:
        result=lap_record(folder,best,metadata);info=result['lap']
        name = f"Fastest_Lap_{info['number']}_{safe_name(metadata['vehicle'])}_{safe_name(metadata['track'])}.lap.json"
        write_json(folder/name,result)
        write_lap_csv(folder/'fastest_lap.csv',best,metadata)
        (folder/'fastest_lap.svg').write_text(curve_svg(result),encoding='utf-8')
        summary.update(file=name,lap=info,session=result['session'],conditions=result['conditions'])
    write_json(folder/'fastest_lap_summary.json',summary)
    selection = library_laps(library,result) if library and result else ([result] if result else [])
    write_compare(folder/'fastest_lap.html',template,selection,summary['status'])
    return result,summary
