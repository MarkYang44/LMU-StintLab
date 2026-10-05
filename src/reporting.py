"""Streaming, atomic standalone reports. No full-race text/JSON copies in RAM."""
import base64
import csv
from functools import wraps
import json
import math
from pathlib import Path
import struct
import tempfile
import threading
import zlib

_lock=threading.RLock()
_encoder=json.JSONEncoder(ensure_ascii=False,separators=(',',':'),allow_nan=False)
REVIEW_COLUMNS=('time_s','lap','lap_distance_m','throttle','brake','steering',
    'filtered_throttle','filtered_brake','filtered_steering','speed_kmh',
    'world_x_m','world_z_m','track_length_m')


def serialized(function):
    @wraps(function)
    def run(*args,**kwargs):
        with _lock:return function(*args,**kwargs)
    return run


class JSONFile:
    def __init__(self,path):self.path=Path(path)


class VehicleJSON:
    def __init__(self,folder,meta):self.folder,self.meta=Path(folder),meta
    def chunks(self):
        from vehiclelab import COLUMNS,DEFAULT_PROFILE,number
        columns=[k for k in COLUMNS if k not in ('time_s','session_time_s')]
        with (self.folder/'vehicle.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=csv.DictReader(f);first=next(rows,None)
            origin=(number(first.get('session_time_s')) or 0)-(number(first.get('time_s')) or 0) if first else 0
            header=dict(version=1,columns=columns,record_hz=self.meta.get('vehicle_telemetry',{}).get('target_hz'),
                source=self.meta.get('source'),time_origin_s=origin,profile=self.meta.get('vehicle_profile',DEFAULT_PROFILE),
                strategy=self.meta.get('vehicle_strategy',{}),strategy_history=self.meta.get('vehicle_settings_history',[]))
            yield from json_chunks(header,open_object=True)
            yield b',"data":['
            last=-math.inf;comma=False
            for row in __import__('itertools').chain((first,) if first else (),rows):
                t=number(row.get('session_time_s'))
                if t is None or t<=last:raise ValueError('附加遥测时间戳无效')
                last=t
                if comma:yield b','
                yield from json_chunks([t,*[number(row.get(k)) for k in columns]])
                comma=True
            yield b']}'


def json_chunks(value,open_object=False):
    from buffers import NumericTable
    if isinstance(value,JSONFile):
        with value.path.open('rb') as f:
            yield from iter(lambda:f.read(65536),b'')
    elif isinstance(value,VehicleJSON):yield from value.chunks()
    elif isinstance(value,dict):
        yield b'{'
        for i,(key,item) in enumerate(value.items()):
            if i:yield b','
            yield _encoder.encode(key).encode('utf-8');yield b':'
            yield from json_chunks(item)
        if not open_object:yield b'}'
    elif isinstance(value,NumericTable):
        yield b'['
        for i,row in enumerate(value):
            if i:yield b','
            yield from json_chunks(row)
        yield b']'
    else:
        # Coalesce the encoder's tiny numeric tokens before calling zlib.
        pieces=[];size=0
        for piece in _encoder.iterencode(value):
            pieces.append(piece);size+=len(piece)
            if size>=32768:
                yield ''.join(pieces).encode('utf-8');pieces=[];size=0
        if pieces:yield ''.join(pieces).encode('utf-8')


def review_records(path):
    pack=struct.Struct('<13d');pending=bytearray()
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        for row in reader:
            values=[float(row.get(k) or (0 if i<10 else 'nan')) for i,k in enumerate(REVIEW_COLUMNS)]
            pending.extend(pack.pack(*values))
            if len(pending)>=65536:yield pending;pending=bytearray()
    if pending:yield pending


def _block(out,identifier,chunks):
    compressor=zlib.compressobj(6,zlib.DEFLATED,31);size=0
    with tempfile.SpooledTemporaryFile(max_size=1048576) as f:
        for chunk in chunks:
            size+=len(chunk);f.write(compressor.compress(chunk))
        f.write(compressor.flush());f.seek(0)
        out.write(f'<script type="application/octet-stream" id="{identifier}" data-bytes="{size}">')
        for chunk in iter(lambda:f.read(49152),b''):out.write(base64.b64encode(chunk).decode('ascii'))
        out.write('</script>\n')


def write_page(path,source,blocks):
    path=Path(path);pending=path.with_name(path.name+'.'+str(threading.get_ident())+'.pending')
    before,after=source.split('/*STINTRIX_BLOCKS*/',1)
    try:
        with pending.open('w',encoding='utf-8',newline='') as out:
            out.write(before)
            for identifier,chunks in blocks:_block(out,identifier,chunks)
            out.write(after)
        pending.replace(path)
    finally:
        if pending.exists():pending.unlink()


def script(assets):return (Path(assets)/'dataview.js').read_text(encoding='utf-8')


@serialized
def render_review(folder,assets,track_js,fastest=None,output=None):
    folder,assets=Path(folder),Path(assets)
    meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
    payload=dict(meta=meta,fastest=fastest)
    for key,name in [('analysis','session_analysis.json'),('native_channels','native_channels.json'),('endurance','endurance_analysis.json')]:
        path=folder/name;payload[key]=JSONFile(path) if path.exists() else None
    payload['vehicle_telemetry']=VehicleJSON(folder,meta) if (folder/'vehicle.csv').exists() else None
    with (folder/'inputs.csv').open(encoding='utf-8-sig',newline='') as f:
        first=next(csv.DictReader(f),None)
        payload['native_time_offset_s']=(float(first['time_s'])-float(first['session_time_s'])) if first else 0
    from control_theme import web_script
    source=(assets/'report.html').read_text(encoding='utf-8').replace('/*INTERFACE_THEME_JS*/',web_script(assets))
    for marker,text in [('/*DATA_VIEW_JS*/',script(assets)),('/*TRACK_VIEW_JS*/',track_js),
        ('/*VEHICLE_VIEW_JS*/',(assets/'vehicleview.js').read_text(encoding='utf-8')),
        ('/*ENDURANCE_VIEW_JS*/',(assets/'enduranceview.js').read_text(encoding='utf-8')),
        ('/*SESSION_DATA*/null','await StintrixData.jsonBlock("stintrix-meta")')]:source=source.replace(marker,text)
    write_page(output or folder/'review.html',source,[('stintrix-meta',json_chunks(payload)),('stintrix-inputs',review_records(folder/'inputs.csv'))])
