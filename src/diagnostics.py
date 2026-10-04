"""Bounded timing measurements, reported off the sampling thread."""
from collections import deque
import math
import threading
import time


def distribution(values):
    a=sorted(x for x in values if math.isfinite(x))
    if not a:return dict(count=0,p50_ms=None,p95_ms=None,p99_ms=None,max_ms=None)
    return dict(count=len(a),**{name:a[min(len(a)-1,round((len(a)-1)*q))]*1000
        for name,q in [('p50_ms',.5),('p95_ms',.95),('p99_ms',.99),('max_ms',1)]})


class Diagnostics:
    def __init__(self):
        self.lock=threading.Lock();self.values={k:deque(maxlen=12000) for k in ('read','draw','latency','interval')}
        self.last_paint=None;self.last_et=None;self.frames=0;self.stutters=0;self.last_received=None

    def note(self,kind,duration):
        with self.lock:self.values[kind].append((time.monotonic(),duration))

    def paint(self,started,sample,target):
        now=time.perf_counter();wall=time.monotonic()
        with self.lock:
            self.values['draw'].append((wall,now-started));self.frames+=1
            if self.last_paint is not None:
                dt=now-self.last_paint;self.values['interval'].append((wall,dt))
                if dt>max(.025,3/max(1,target)):self.stutters+=1
            self.last_paint=now
            if sample and sample.get('_received_perf') is not None and sample['et']!=self.last_et:
                self.values['latency'].append((wall,max(0,now-sample['_received_perf'])))
                self.last_et=sample['et'];self.last_received=wall-max(0,now-sample['_received_perf'])

    def snapshot(self,horizon=5):
        now=time.monotonic()
        with self.lock:
            result={k:distribution([v for t,v in rows if now-t<=horizon]) for k,rows in self.values.items()}
            result.update(frames=self.frames,stutters=self.stutters,window_s=horizon,
                data_age_ms=(now-self.last_received)*1000 if self.last_received is not None else None)
        result['latency_definition']='plugin receipt to Tk idle paint completion; excludes wheel hardware/game/display scanout'
        result['renderer']='Tk CPU canvas; GPU migration needs comparative implementation, not inferred from target Hz'
        return result
