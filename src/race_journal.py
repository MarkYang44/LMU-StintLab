"""Compact race events and official scoring; no input-rate CSV expansion."""
import json
import math
from itertools import islice
from pathlib import Path
from storage import BatchWriter, atomic_json

EVENT_COLUMNS = ('session_time_s', 'event', 'payload_json')


def positive(value):
    return float(value) if isinstance(value,(int,float)) and math.isfinite(value) and value>0 else None


def text(value):
    return bytes(value).split(b'\0',1)[0].decode('utf-8','replace')


def capture(data, car, player, info, cache=None):
    """Cache scoring-grid work at the producer's scoring cadence, not poll Hz."""
    key=(float(info.mCurrentET),int(info.mSession),int(player.mID),int(info.mGamePhase),
         int(player.mTotalLaps),int(player.mPlace),int(player.mNumPenalties),int(player.mNumPitstops),
         float(player.mLastLapTime),float(player.mLastSector1),float(player.mLastSector2),float(player.mLapStartET))
    if cache is not None and cache.get('_key')==key:
        state=cache
    else:
        best=None;driver=''
        for vehicle in islice(data.scoring.vehScoringInfo,min(104,max(0,int(info.mNumVehicles)))):
            lap=positive(vehicle.mBestLapTime)
            if lap is not None and (best is None or lap<best):best,driver=lap,text(vehicle.mDriverName)
        state=dict(_key=key,completed_laps=int(player.mTotalLaps),place=int(player.mPlace) or None,
            scoring_lap_start=float(player.mLapStartET),last_lap=positive(player.mLastLapTime),
            sector1=positive(player.mLastSector1),sector12=positive(player.mLastSector2),
            penalties=int(player.mNumPenalties),pit_stops=int(player.mNumPitstops),
            phase=int(info.mGamePhase),team=text(player.mVehicleName),vehicle_class=text(player.mVehicleClass),
            session_best_lap=best,session_best_driver=driver,
            path_lateral=float(player.mPathLateral),track_edge=float(player.mTrackEdge))
    return dict(state,impact_et=positive(car.mLastImpactET),impact_magnitude=positive(car.mLastImpactMagnitude))


class RaceJournal:
    """Stream transitions only. Keep at most a few pending lap contexts in RAM."""
    def __init__(self,folder,sample):
        self.folder=Path(folder);self.origin=sample['et'];self.previous=None
        self.current=None;self.closed=[];self.signature=None;self.last_impact=None
        self.offtrack_since=None;self.offtrack_logged=False;self.rows=0
        self.summary=dict(version=1,source='LMU_Data scoring / telemetry',available=bool(sample.get('race_state')),
            impact_count=0,offtrack_estimate_count=0,start_place=None,grid_place=None,finish_place=None,
            finish_flag=0,recording_started_mid_session=None,
            note='名次与分段来自游戏；出界仅为边界估算，非 Race Control 警告。碰撞按接触事件合并。')
        self.writer=BatchWriter(folder,EVENT_COLUMNS,capacity=8192,filename='race_events.csv',
            checkpoint_name='race_events_checkpoint.json')

    def emit(self,et,event,payload):
        self.writer.add([f'{et:.6f}',event,json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False)])
        self.rows+=1

    def observe(self,sample):
        state=sample.get('race_state') or {};et=sample['et'];start=sample.get('lap_start')
        self.last_et=et;self.summary['finish_flag']=int(sample.get('finish',0))
        signature=(state.get('_key'),start,sample.get('lap_invalidated'),sample.get('in_pits'),
                   sample.get('finish'),state.get('impact_et'))
        if signature==self.signature:return
        if self.signature is None:self.emit(et,'recording_start',{'session':sample['session']})
        self.signature=signature
        if self.current is None or start!=self.current['start']:
            if self.current is not None and start is not None and self.current['start'] is not None and start>self.current['start']:
                context=dict(self.current,end=start,time=start-self.current['start'])
                self.closed.append(context);self.closed=self.closed[-4:]
                self.emit(start,'lap_boundary',context)
            self.current=dict(start=start,telemetry_lap=int(sample['lap']),invalidated=False,in_pits=False,
                              partial=start is None or et-start>.3)
        self.current['invalidated']|=bool(sample.get('lap_invalidated'))
        self.current['in_pits']|=bool(sample.get('in_pits'))
        old=self.previous
        if state and old is None:
            self.summary.update(start_place=state.get('place'),recording_started_mid_session=state.get('phase',0)>=5,
                team=state.get('team',''),vehicle_class=state.get('vehicle_class',''))
            self.last_impact=state.get('impact_et')
        if state:
            if sample.get('session') in (10,11,12,13) and state.get('phase') in (2,3,4) and state.get('place'):
                self.summary['grid_place']=state['place']
            self.summary.update(finish_place=state.get('place'),finish_flag=int(sample.get('finish',0)),
                session_best_lap=state.get('session_best_lap'),session_best_driver=state.get('session_best_driver',''))
            if old:
                for key,event in [('place','position'),('phase','phase'),('penalties','penalties'),('pit_stops','pit_stop')]:
                    if state.get(key)!=old.get(key):self.emit(et,event,{'from':old.get(key),'to':state.get(key)})
                completed=state.get('completed_laps',0);previous=old.get('completed_laps',0)
                if completed>previous:
                    end=state.get('scoring_lap_start',et)
                    context=next((c for c in reversed(self.closed) if abs(c['end']-end)<.3),None)
                    if context is None:context=dict(self.current)
                    duration=state.get('last_lap')
                    if context.get('invalidated') or duration is None:
                        duration=context.get('time') or (et-context['start'] if context.get('start') is not None else None)
                    s1,s12=state.get('sector1'),state.get('sector12');total=state.get('last_lap')
                    if completed-previous>1:
                        # Only the last official lap survived the scoring gap.
                        # The old telemetry context may span several laps.
                        context=dict(start=end-total if total and end>=total else None,
                            telemetry_lap=None,partial=True,in_pits=False,invalidated=False)
                        duration=total
                    sectors=[s1,positive(s12-s1) if s1 and s12 else None,positive(total-s12) if total and s12 else None]
                    if total is None or s1 is None or s12 is None or not 0<s1<s12<total:sectors=[None]*3
                    self.emit(et,'official_lap',dict(num=completed,time=positive(duration),
                        valid=False if context.get('invalidated') or total is None else True,
                        start=context.get('start'),telemetry_lap=context.get('telemetry_lap'),
                        s1=sectors[0],s2=sectors[1],s3=sectors[2],partial=context.get('partial',True),
                        in_pits=context.get('in_pits',False),missed_laps=max(0,completed-previous-1)))
            impact=state.get('impact_et')
            if impact is not None and impact!=self.last_impact:
                if impact>self.origin and state.get('impact_magnitude') and (
                        self.last_impact is None or self.last_impact<=self.origin or impact-self.last_impact>1):
                    self.summary['impact_count']+=1
                    self.emit(impact,'impact',{'magnitude':state['impact_magnitude']})
                self.last_impact=impact
            edge=state.get('track_edge',0);lateral=state.get('path_lateral',0)
            off=(math.isfinite(edge) and math.isfinite(lateral) and edge>0 and abs(lateral)>abs(edge)+.7
                 and not sample.get('in_pits') and sample.get('speed',0)>20)
            if off:
                if self.offtrack_since is None:self.offtrack_since=et
                if not self.offtrack_logged and et-self.offtrack_since>=.5:
                    self.offtrack_logged=True;self.summary['offtrack_estimate_count']+=1
                    self.emit(et,'offtrack_estimate',{'definition':'边界估算，非官方警告'})
            else:self.offtrack_since=None;self.offtrack_logged=False
            self.previous=state
        if old and bool(sample.get('in_pits'))!=getattr(self,'in_pits',False):
            self.emit(et,'pit_entry' if sample.get('in_pits') else 'pit_exit',{})
        self.in_pits=bool(sample.get('in_pits'))
        if sample.get('lap_invalidated') and not getattr(self,'invalidated',False):
            self.emit(et,'lap_invalidated',{'telemetry_lap':int(sample['lap'])})
        self.invalidated=bool(sample.get('lap_invalidated'))

    def finish(self,reason):
        try:
            self.emit(getattr(self,'last_et',self.origin),'recording_end',{'reason':reason,'finish_flag':self.summary['finish_flag']})
        finally:
            stats=self.writer.finish()
        self.summary['event_rows']=self.rows
        self.summary['writer_stats']=stats
        atomic_json(self.folder/'race_summary.json',self.summary)
        return stats
