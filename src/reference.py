"""Immutable distance-aligned reference lookup; no file I/O on sampling thread."""
import bisect
import json
import math
from pathlib import Path
from sessionlab import condition_check
from array import array
from buffers import NumericTable


class ReferenceLap:
    def __init__(self, value, path=''):
        if value.get('format') != 'inputscope.fastest-lap' or value.get('version') != 1:
            raise ValueError('请选择 InputScope 最快圈 .lap.json')
        self.session = value['session']
        self.info = value['lap']
        if self.info.get('lap_invalidated') or self.info.get('in_pits'):
            raise ValueError('带无效或进站标记的完整圈仅供复盘，不能用作 HUD 参考')
        self.length = float(self.info['track_length_m'])
        self.duration = float(self.info['time_s'])
        self.data = value['data']
        if not math.isfinite(self.length) or not math.isfinite(self.duration) or self.length <= 100 or self.duration <= 0 or len(self.data) < 3:
            raise ValueError('参考圈边界无效')
        last_d, last_t = -1, -1
        for r in self.data:
            if (len(r) != 7 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in r)
                    or not 0 <= r[0] <= self.length+.1 or r[0] < last_d
                    or not last_t < r[1] <= self.duration+.001
                    or any(not 0 <= x <= 1 for x in r[2:6]) or r[6] < 0):
                raise ValueError('参考圈采样值或顺序无效')
            last_d,last_t = r[:2]
        if (self.data[0][0] > .1 or self.data[0][1] > .001
                or abs(last_d-self.length) > .1 or abs(last_t-self.duration) > .001):
            raise ValueError('参考圈缺少完整边界')
        self.data = NumericTable(self.data,7)
        self.distances = array('d',(r[0] for r in self.data))
        self.path = str(path)
        self.conditions=value.get('conditions',{})
        self.kind=value.get('reference_kind','fastest')
        self.trajectory=value.get('trajectory') or {}
        self.cells={}
        if self.trajectory.get('source')=='recorded_world_xz':
            points=self.trajectory.get('points',[])
            if not isinstance(points,list) or any(not isinstance(p,(list,tuple)) or len(p)!=4 or
                not all(isinstance(x,(int,float)) and math.isfinite(x) for x in p) for p in points):
                raise ValueError('参考圈坐标格式无效')
            for a,b in zip(points,points[1:]):
                if not 0<b[0]-a[0]<=.25 or b[1]<a[1] or math.hypot(b[2]-a[2],b[3]-a[3])>100:continue
                cells={(math.floor(p[2]/50),math.floor(p[3]/50)) for p in (a,b)}
                for cell in cells:
                    self.cells.setdefault(cell,[]).append((a,b))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 100*1024*1024:
            raise ValueError('参考圈文件超过 100 MB')
        return cls(json.loads(path.read_text(encoding='utf-8')),path)

    def compatible(self, sample):
        return (all(str(self.session.get(k,'')).strip().casefold() == str(sample.get(k,'')).strip().casefold()
                    for k in ('track','vehicle'))
                and abs(sample.get('track_length',0)-self.length) <= max(30,self.length*.01))

    def at(self, distance):
        if not math.isfinite(distance) or not 0 <= distance <= self.length:
            return None
        i = bisect.bisect_left(self.distances,distance)
        if not i:
            return self.data[0]
        a,b = self.data[i-1],self.data[min(i,len(self.data)-1)]
        f = (distance-a[0])/max(1e-9,b[0]-a[0])
        return tuple(x+(y-x)*f for x,y in zip(a,b))

    def sample(self, sample):
        if (not self.compatible(sample) or not condition_check(sample.get('conditions',{}),self.conditions)['allowed'] or sample.get('in_pits') or sample.get('lap_invalidated')
                or sample.get('finish',0) or sample.get('lap_start') is None):
            return None
        r = self.at(sample['distance']/sample['track_length']*self.length)
        elapsed = sample['et']-sample['lap_start']
        if r is None or elapsed < 0:
            return None
        return (*r[2:6],elapsed-r[1])

    def project(self,position,distance):
        if not position or not self.cells or len(position)!=3 or not all(math.isfinite(x) for x in position):return None
        x,z=position[0],position[2];cell=(math.floor(x/50),math.floor(z/50));best=None
        for dx in (-1,0,1):
            for dz in (-1,0,1):
                for a,b in self.cells.get((cell[0]+dx,cell[1]+dz),[]):
                    if min(abs(a[1]-distance),abs(b[1]-distance))>120:continue
                    vx,vz=b[2]-a[2],b[3]-a[3];f=max(0,min(1,((x-a[2])*vx+(z-a[3])*vz)/max(1e-9,vx*vx+vz*vz)))
                    lateral=math.hypot(x-a[2]-f*vx,z-a[3]-f*vz);d=a[1]+f*(b[1]-a[1]);score=lateral+abs(d-distance)*.02
                    if lateral<=30 and (best is None or score<best[0]):best=(score,d,lateral)
        return best[1:] if best else None


class DistanceAligner:
    def __init__(self):
        self.previous=None;self.last_distance=None;self.score_distance=None;self.score_et=None;self.state={'mode':'无数据','confidence':0}
        self.condition_key=None;self.lap_fuel=None

    def match_conditions(self,sample):
        key=tuple(sample.get(k) for k in ('track','vehicle','lap','lap_start'))
        conditions=dict(sample.get('conditions',{}))
        if key!=self.condition_key:
            self.condition_key=key
            self.lap_fuel=conditions.get('fuel_l') if 0<=sample.get('distance',-1)<=max(30,sample.get('track_length',0)*.03) else None
        conditions['fuel_l']=self.lap_fuel
        return conditions

    def update(self,sample,reference):
        conditions=self.match_conditions(sample)
        if not reference or not reference.compatible(sample):self.state={'mode':'未匹配','confidence':0};return None
        check=condition_check(conditions,reference.conditions)
        if not check['allowed']:self.state={'mode':'条件不匹配','confidence':0,'conditions':check};return None
        if sample.get('in_pits') or sample.get('lap_invalidated') or sample.get('finish'):
            self.previous=None;self.state={'mode':'进站/无效/结束','confidence':0,'conditions':check};return None
        d=sample['distance']/sample['track_length']*reference.length;t=sample['et'];previous=self.previous
        if not math.isfinite(t) or not math.isfinite(sample.get('speed',float('nan'))) or not 0<=d<=reference.length:self.state={'mode':'起终点外/无效值','confidence':0};return None
        lapkey=(sample.get('lap'),sample.get('lap_start'))
        reset=previous is None or previous['key']!=lapkey or t<=previous['et'] or t-previous['et']>.25
        if reset:self.score_distance=d;self.score_et=t;self.last_distance=d
        if previous and previous['key']==lapkey and (t<=previous['et'] or t-previous['et']>.25):
            self.previous={'key':lapkey,'et':t,'position':sample.get('position')}
            self.state={'mode':'遥测缺口','confidence':0,'conditions':check};return None
        if previous and not reset and sample.get('position') and previous.get('position'):
            movement=math.dist(sample['position'],previous['position'])
            if movement>max(10,(t-previous['et'])*150):
                self.previous=None;self.state={'mode':'坐标跳变','confidence':0};return None
        if d!=self.score_distance:self.score_distance=d;self.score_et=t
        projection=reference.project(sample.get('position'),d)
        if projection:
            aligned,lateral=projection;mode='位置投影';confidence=max(.35,.95-lateral/40)
        else:
            age=t-self.score_et;aligned=d+sample['speed']/3.6*min(.15,max(0,age))
            aligned=min(reference.length,aligned);mode='距离估算' if age<=.15 else '距离过期';confidence=.5 if age<=.15 else .2
        if not reset:
            expected=self.last_distance+sample['speed']/3.6*(t-previous['et'])
            if abs(aligned-expected)>25:
                self.previous=None;self.state={'mode':'距离跳变','confidence':0};return None
            aligned=max(self.last_distance,min(reference.length,expected+(aligned-expected)*min(1,(t-previous['et'])*15)))
        self.previous={'key':lapkey,'et':t,'position':sample.get('position')};self.last_distance=aligned
        self.state=dict(mode=mode,confidence=confidence,distance_m=aligned,conditions=check,matching_conditions=conditions)
        return aligned


def best_reference(root, sample, current=None,kind='fastest'):
    """Read summaries first; load only the winning compatible lap."""
    found = []
    folders=('DemoLogs',) if sample.get('demo') else ('Logs','ImportedLogs','RecoveredLogs')
    for folder in folders:
        for path in (Path(root)/folder).glob('*/'+('session_analysis.json' if kind=='stable' else 'fastest_lap_summary.json')):
            try:
                v = json.loads(path.read_text(encoding='utf-8'))
                if kind=='stable':
                    if not v.get('stable_reference_file'):continue
                    ref=ReferenceLap.load(path.parent/v['stable_reference_file']);s=ref.session;info=ref.info;file=ref.path
                    conditions=ref.conditions
                else:s=v['session'];info=v['lap'];file=path.parent/v['file'];conditions=v.get('conditions',{})
                if (all(str(s.get(k,'')).strip().casefold()
                        == str(sample.get(k,'')).strip().casefold() for k in ('track','vehicle'))
                        and abs(info['track_length_m']-sample['track_length']) <= max(30,sample['track_length']*.01)):
                    check=condition_check(sample.get('conditions',{}),conditions)
                    if check['allowed']:found.append((len(check['unknown']),float(info['time_s']),Path(file)))
            except (OSError,ValueError,KeyError,TypeError):
                continue
    for _,_,path in sorted(found,key=lambda v:v[:2]):
        if current and str(path)==current.path:
            return current
        try:
            return ReferenceLap.load(path)
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return None
