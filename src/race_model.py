"""Streaming lap summaries and compact event-log reconciliation."""
import csv
import json
import math
from pathlib import Path
from library import session_label


def number(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) else None


def read_json(path, default):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default


def lap_summaries(path):
    """O(laps) memory; keep neither input samples nor per-sample intervals."""
    result=[];current=None;seen_boundary=False;previous_et=None
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            et=number(row.get('session_time_s'));lap=number(row.get('lap'))
            if et is None or lap is None:raise ValueError('记录包含无效时间或圈号')
            start=number(row.get('lap_start_s'))
            timer=start is not None and 0<=start<=et+.1
            key=('timer',start) if timer else ('counter',int(lap))
            if current is None or key!=current['_key']:
                if current:
                    end=start if timer and current['_key'][0]=='timer' else et
                    duration=end-current['start']
                    current.update(time=duration if duration>0 else None,partial=current['partial'] or duration<=0,
                                   complete=duration>0)
                    if int(lap)>current['telemetry_lap']+1:
                        current.update(time=None,complete=False,partial=True,missing_lap_boundary=True)
                    result.append(current);seen_boundary=True
                current=dict(_key=key,num=int(lap),telemetry_lap=int(lap),start=start if timer else et,
                    time=None,valid=None,s1=None,s2=None,s3=None,partial=not seen_boundary and (not timer or et-start>.3),
                    complete=False,in_pits=False,timing_source='lap_start' if timer else 'counter_estimate',
                    samples=0,max_gap_s=0,observed_start=et,validity_known=True,invalidated=False)
                previous_et=None
            current['samples']+=1
            if previous_et is not None:current['max_gap_s']=max(current['max_gap_s'],et-previous_et)
            previous_et=et
            current['validity_known'] &= number(row.get('lap_invalidated')) is not None
            current['invalidated'] |= (number(row.get('lap_invalidated')) or 0)>0
            current['in_pits'] |= (number(row.get('in_pits')) or 0)>0
    if current:result.append(current)
    for lap in result:
        lap.pop('_key')
        lap['valid']=not lap.pop('invalidated') if lap.pop('validity_known') else None
    return result


def build_model(folder):
    folder=Path(folder);meta=read_json(folder/'session.json',{})
    if meta.get('status')=='recording':raise ValueError('请等该场记录结束后再生成图片')
    laps=lap_summaries(folder/'inputs.csv');events=[]
    path=folder/'race_events.csv'
    if path.exists():
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for row in csv.DictReader(stream):
                et=number(row.get('session_time_s'))
                try:payload=json.loads(row['payload_json'])
                except (ValueError,KeyError):raise ValueError('比赛事件记录损坏，请保留原文件') from None
                if et is None or not isinstance(payload,dict):raise ValueError('比赛事件时间或内容无效')
                events.append(dict(time=et,event=row['event'],data=payload))
    official=[e for e in events if e['event']=='official_lap']
    for event in official:
        value=event['data'];start=number(value.get('start'))
        matches=[lap for lap in laps if start is not None and abs(lap['start']-start)<.3]
        target=matches[0] if len(matches)==1 else None
        if target is None:
            target=dict(num=value['num'],telemetry_lap=value.get('telemetry_lap'),start=start,time=None,
                valid=None,s1=None,s2=None,s3=None,partial=True,complete=True,in_pits=False,
                timing_source='official',samples=0,max_gap_s=None)
            laps.append(target)
        # Official lap count is one-based even when telemetry counters start at 0.
        target.update({key:value.get(key) for key in ('num','time','valid','s1','s2','s3','in_pits')})
        target.update(complete=True,partial=bool(value.get('partial',True)),timing_source='official')
        target['missed_laps']=value.get('missed_laps',0)
    laps.sort(key=lambda lap:lap['start'] if lap['start'] is not None else float('inf'))
    # Give an unfinished telemetry group its expected next official lap number.
    # The original telemetry counter remains separately available for matching.
    anchors=[e for e in official if isinstance(e['data'].get('telemetry_lap'),int)]
    if anchors:
        offset=anchors[0]['data']['num']-anchors[0]['data']['telemetry_lap']
        for lap in laps:
            if lap['timing_source']!='official':lap['num']=lap['telemetry_lap']+offset
    candidates=[lap for lap in laps if lap['complete'] and not lap['partial'] and not lap['in_pits'] and lap['valid'] is True
                and (lap['timing_source']=='official' or lap['max_gap_s']<=2.5)
                and number(lap['time']) is not None and lap['time']>0]
    fastest=min(candidates,key=lambda lap:lap['time']) if candidates else None
    for lap in laps:
        lap['best']=lap is fastest
        lap['delta']=lap['time']-fastest['time'] if fastest and lap['time'] else None
    sectors=[min((lap[key] for lap in candidates if number(lap[key]) is not None and lap[key]>0),default=None)
             for key in ('s1','s2','s3')]
    summary=read_json(folder/'race_summary.json',{})
    if summary.get('recovered'):
        summary['impact_count']=sum(e['event']=='impact' for e in events)
        summary['offtrack_estimate_count']=sum(e['event']=='offtrack_estimate' for e in events)
    # Older CSVs can recover lap boundaries and pit/invalidated markers only.
    # Missing scoring, collisions or sectors are never invented.
    if not events:
        for lap in laps:
            if lap['complete']:
                events.append(dict(time=lap['start']+(lap['time'] or 0),event='reconstructed_lap',data=lap.copy()))
    events=[e for e in events if e['event']!='lap_boundary' or not any(
        number(o['data'].get('start')) is not None and number(e['data'].get('start')) is not None
        and abs(o['data']['start']-e['data']['start'])<.3 for o in official)]
    events.sort(key=lambda e:e['time'])
    origin=min([e['time'] for e in events]+[lap['observed_start'] for lap in laps if 'observed_start' in lap],default=0)
    return dict(format='stintlab.race-report',version=1,session=meta,session_type=session_label(meta.get('session')),
        summary=summary,laps=laps,events=events,origin=origin,fastest=fastest,sector_bests=sectors,
        scoring_available=bool(summary.get('available')),lap_number_source='official' if official else 'telemetry',
        note='分段 / 名次来自游戏；缺失字段显示未知。出界仅为边界估算，非官方警告；碰撞按接触事件合并。')


def lap_time(value):
    value=number(value)
    if value is None or value<=0:return '—'
    millis=round(value*1000);minutes,remainder=divmod(millis,60000)
    return f'{minutes}:{remainder/1000:06.3f}'


def lap_status(lap):
    flags=[]
    if lap['valid'] is False:flags.append('无效')
    elif lap['valid'] is None:flags.append('有效性未知')
    if lap['partial'] or not lap['complete']:flags.append('部分记录' if lap['complete'] else '未完成')
    if lap['in_pits']:flags.append('PIT')
    if lap.get('missed_laps'):flags.append('缺圈')
    if lap['best']:flags.append('最快圈')
    return ' / '.join(flags) or '有效'


def describe(event):
    name=event['event'];p=event['data']
    if name in ('official_lap','reconstructed_lap'):
        flags=(' · 无效' if p.get('valid') is False else '')+(' · 部分记录' if p.get('partial') else '')
        return f"完成第 {p.get('num','?')} 圈 · {lap_time(p.get('time'))}"+flags+(' · 期间缺圈 '+str(p['missed_laps']) if p.get('missed_laps') else '')
    if name=='position':return f"名次变化 · P{p.get('from','?')} → P{p.get('to','?')}"
    if name=='impact':return '发生碰撞 · 合并连续接触'
    if name=='offtrack_estimate':return '检测到持续越过估算边界 · 非官方警告'
    if name=='penalties':return f"待执行处罚数量变化 · {p.get('from','?')} → {p.get('to','?')}"
    if name=='pit_stop':return f"游戏进站计数变化 · {p.get('from','?')} → {p.get('to','?')}"
    if name=='pit_entry':return '进入维修区'
    if name=='pit_exit':return '驶离维修区'
    if name=='lap_invalidated':return '当前圈被游戏标记为无效'
    if name=='recording_start':return '开始记录'
    if name=='recording_end':
        result={2:'未完赛（DNF）',3:'取消资格（DQ）'}.get(p.get('finish_flag'))
        return '结束记录 · '+(result or str(p.get('reason','')))
    if name=='phase':
        phases={0:'赛前',1:'侦察圈',2:'发车格',3:'暖胎圈',4:'倒计时',5:'绿旗',6:'全场黄旗',7:'暂停比赛',8:'比赛结束',9:'暂停'}
        return '赛事阶段 · '+phases.get(p.get('to'),str(p.get('to')))
    if name=='lap_boundary':return '圈计时边界 · '+lap_time(p.get('time'))
    return str(name)


def elapsed(value):
    seconds=max(0,int(value));hours,remainder=divmod(seconds,3600);minutes,seconds=divmod(remainder,60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'
