"""Independent, cached and atomic native race report generation."""
import hashlib
import json
from pathlib import Path
import threading
from race_art import select_car
from race_images import pages
from race_model import build_model,describe,elapsed,lap_status,lap_time,read_json
from reporting import serialized
from storage import atomic_json

RENDER_VERSION=3


def digest(path):
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1048576),b''):sha.update(chunk)
    return sha.hexdigest()


def write_text(path,value):
    pending=path.with_name(path.name+'.'+str(threading.get_ident())+'.pending')
    try:pending.write_text(value,encoding='utf-8');pending.replace(path)
    finally:pending.unlink(missing_ok=True)


@serialized
def generate(folder,car_directory=None):
    folder=Path(folder).resolve();meta=read_json(folder/'session.json',{})
    if meta.get('status')=='recording':raise ValueError('请等该场记录结束后再生成图片')
    art=select_car(meta.get('vehicle',''),car_directory)
    inputs={name:digest(folder/name) for name in ('inputs.csv','session.json','race_events.csv','race_summary.json') if (folder/name).is_file()}
    fingerprint=dict(version=RENDER_VERSION,inputs=inputs,car=None)
    if art:fingerprint['car']=dict(sha256=digest(art[0]),bounds=art[1])
    # JSON turns tuples into lists; keep the same canonical representation.
    fingerprint=json.loads(json.dumps(fingerprint))
    receipt=read_json(folder/'race_images.json',{})
    if receipt.get('fingerprint')==fingerprint and receipt.get('files') and all(
            Path(name).name==name and (folder/name).is_file() and digest(folder/name)==sha
            for name,sha in receipt['files'].items()):return receipt
    model=build_model(folder)
    files={}
    try:
        atomic_json(folder/'race_log.json',model)
        lines=['LMU STINTLAB · 比赛日志',f"{model['session_type']} / {meta.get('track','')} / {meta.get('vehicle','')}",
            f"车手：{meta.get('driver','')}  开始：{meta.get('started_utc','')}",model['note'],'','圈速单：']
        lines += [f"Lap {lap['num']}  {lap_time(lap['time'])}  S1 {lap['s1']}  S2 {lap['s2']}  S3 {lap['s3']}  {lap_status(lap)}" for lap in model['laps']]
        lines += ['','时间线：']+[elapsed(e['time']-model['origin'])+'  '+describe(e) for e in model['events']]
        write_text(folder/'race_log.txt','\n'.join(lines)+'\n')
        for name,canvas in pages(model,art):
            pending=folder/(name+'.'+str(threading.get_ident())+'.pending')
            try:canvas.save(pending);pending.replace(folder/name)
            finally:pending.unlink(missing_ok=True)
            files[name]=digest(folder/name)
        for name in ('race_log.json','race_log.txt'):files[name]=digest(folder/name)
        receipt=dict(version=1,status='complete',generator='StintLab native / Windows GDI+',fingerprint=fingerprint,
            files=files,lap_count=len(model['laps']),event_count=len(model['events']),original_files_retained=True,
            car_image='private calibrated artwork' if art else 'unavailable')
        atomic_json(folder/'race_images.json',receipt)
        (folder/'race_images_error.txt').unlink(missing_ok=True)
        return receipt
    except Exception as error:
        write_text(folder/'race_images_error.txt',str(error));raise
