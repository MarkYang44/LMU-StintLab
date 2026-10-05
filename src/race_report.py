"""Independent, cached and atomic native race report generation."""
import hashlib
import json
import shutil
from pathlib import Path
import threading
from race_art import select_car
from race_images import pages
from race_model import build_model,describe,elapsed,lap_status,lap_time,read_json
from reporting import serialized
from storage import atomic_json

RENDER_VERSION=6


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
def generate(folder,car_directory=None,renderer=None):
    folder=Path(folder).resolve();meta=read_json(folder/'session.json',{})
    if meta.get('status')=='recording':raise ValueError('请等该场记录结束后再生成图片')
    from renderer_config import resolve
    # Synthetic demos and explicitly selected compatibility previews stay self-contained.
    mode=renderer or ('native' if meta.get('source')=='Synthetic demo' or folder.parent.name=='DemoLogs' else None)
    config=resolve(mode)
    art=select_car(meta.get('vehicle',''),car_directory)
    inputs={name:digest(folder/name) for name in ('inputs.csv','session.json','race_events.csv','race_summary.json') if (folder/name).is_file()}
    fingerprint=dict(version=RENDER_VERSION,inputs=inputs,car=None,renderer=config['mode'])
    if config['mode']=='racecom':
        executable=Path(config['executable']);base=executable.parent
        fingerprint['runtime']={str(path.relative_to(base)):digest(path) for path in [executable,base/'image_generate_config.json',
            base/'_customization'/'racecom_hooks.py',base/'_customization'/'car_calibration.json',base/'Source'/'LMU Logo.png'] if path.is_file()}
        car_path=base/'Source'/'Cars'
        fingerprint['artwork']={path.name:digest(path) for path in car_path.iterdir() if path.is_file() and path.suffix.casefold() in ('.jpg','.png','.jpeg')} if car_path.is_dir() else {}
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
        old_mode=receipt.get('fingerprint',{}).get('renderer') or ('racecom' if 'RaceCom' in receipt.get('generator','') else 'native')
        if receipt.get('files') and old_mode!=config['mode']:
            # A renderer change is reviewable and reversible, including old v0.1.4 PNGs.
            prior=hashlib.sha256(json.dumps(receipt,sort_keys=True).encode('utf-8')).hexdigest()[:12]
            backup=folder/'_report_history'/('renderer-'+prior)
            backup.mkdir(parents=True,exist_ok=True)
            for name in ('圈速单.png','比赛日志.png','race_log.json','race_log.txt','race_images.json'):
                if (folder/name).is_file() and not (backup/name).exists():shutil.copy2(folder/name,backup/name)
        atomic_json(folder/'race_log.json',model)
        lines=['LMU STINTRIX · 比赛日志',f"{model['session_type']} / {meta.get('track','')} / {meta.get('vehicle','')}",
            f"车手：{meta.get('driver','')}  开始：{meta.get('started_utc','')}",model['note'],'','圈速单：']
        lines += [f"Lap {lap['num']}  {lap_time(lap['time'])}  S1 {lap['s1']}  S2 {lap['s2']}  S3 {lap['s3']}  {lap_status(lap)}" for lap in model['laps']]
        lines += ['','时间线：']+[elapsed(e['time']-model['origin'])+'  '+describe(e) for e in model['events']]
        write_text(folder/'race_log.txt','\n'.join(lines)+'\n')
        if config['mode']=='racecom':
            from racecom_bridge import render
            for name,path in render(folder,model,config['executable']).items():files[name]=digest(path)
        else:
            for name,canvas in pages(model,art):
                pending=folder/(name+'.'+str(threading.get_ident())+'.pending')
                try:canvas.save(pending);pending.replace(folder/name)
                finally:pending.unlink(missing_ok=True)
                files[name]=digest(folder/name)
        for name in ('race_log.json','race_log.txt'):files[name]=digest(folder/name)
        receipt=dict(version=1,status='complete',generator='RaceCom original / light' if config['mode']=='racecom' else 'Stintrix compatibility / Windows GDI+',fingerprint=fingerprint,
            files=files,lap_count=len(model['laps']),event_count=len(model['events']),original_files_retained=True,
            car_image='private calibrated artwork' if art else 'unavailable')
        atomic_json(folder/'race_images.json',receipt)
        (folder/'race_images_error.txt').unlink(missing_ok=True)
        return receipt
    except Exception as error:
        write_text(folder/'race_images_error.txt',str(error));raise
