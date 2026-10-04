"""Copy legacy user data locally; preserve sources and fail on record collisions."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
FOLDERS=('Logs','ImportedLogs','RecoveredLogs','DemoLogs','Diagnostics')
FILES=('settings.json','reference_settings.json','vehicle_settings.json','endurance_settings.json',
       'library_notes.json','last_native_import.json','FastestLapCompare.html','DemoFastestLapCompare.html')
SETTINGS=set(FILES[:6])

def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def rewrite_local_paths(value,source,target):
    if isinstance(value,dict):return {k:rewrite_local_paths(v,source,target) for k,v in value.items()}
    if isinstance(value,list):return [rewrite_local_paths(v,source,target) for v in value]
    if isinstance(value,str):
        try:
            candidate=Path(value)
            if candidate.is_absolute():
                # Windows TEMP and old shortcuts can use 8.3 names such as
                # RUNNER~1 while the migration roots have resolved long names.
                candidate=candidate.resolve()
                if candidate.is_relative_to(source):return str(target/candidate.relative_to(source))
        except (OSError,ValueError):pass
    return value

def migrate(source,target,backup):
    source=Path(source).resolve();target=Path(target).resolve();backup=Path(backup).resolve()
    if not (source/'src'/'inputscope.py').is_file():raise ValueError('Source is not a legacy InputScope folder')
    if source==target or source.is_relative_to(target) or target.is_relative_to(source):raise ValueError('Source and destination must not overlap')
    if backup.is_relative_to(source):raise ValueError('Backup must be outside the original folder')
    pairs=[]
    for name in FOLDERS:
        for file in (source/name).rglob('*'):
            if file.is_file():pairs.append((file,target/file.relative_to(source)))
    for name in FILES:
        file=source/name
        if file.is_file():pairs.append((file,target/name))
    for file in (source/'src'/'tracks').rglob('*'):
        if file.is_file():pairs.append((file,target/'assets'/'tracks'/file.relative_to(source/'src'/'tracks')))
    for name in ('README.md','使用说明.md','赛道地图来源.md'):
        file=source/name
        if file.is_file():pairs.append((file,target/'legacy_docs'/name))
    # Verify every resolved path before writing, including junctions and symlinks.
    prepared=[]
    for file,destination in pairs:
        if not file.resolve().is_relative_to(source) or not destination.resolve().is_relative_to(target):raise ValueError('Linked file escapes migration roots')
        sha=digest(file)
        if destination.exists() and digest(destination)!=sha and destination.relative_to(target).as_posix() not in SETTINGS:
            raise ValueError('Destination has a different record; no files were copied')
        prepared.append((file,destination,sha))
    backup.mkdir(parents=True,exist_ok=False);target.mkdir(parents=True,exist_ok=True)
    manifest={'source':str(source),'target':str(target),'started_utc':datetime.now(timezone.utc).isoformat(),'files':[],'rewritten_settings':[]}
    for file,destination,sha in prepared:
        relative=destination.relative_to(target)
        if destination.exists() and digest(destination)!=sha:
            prior=backup/'previous_data'/relative;prior.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,prior)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.exists() or digest(destination)!=sha:shutil.copy2(file,destination)
        if digest(file)!=sha or digest(destination)!=sha:raise ValueError('Source changed during migration; close the HUD and retry')
        manifest['files'].append({'source':str(file.relative_to(source)),'destination':str(relative),'sha256':sha,'bytes':file.stat().st_size})
    for name in SETTINGS:
        path=target/name
        if not path.exists():continue
        value=json.loads(path.read_text(encoding='utf-8-sig'));updated=rewrite_local_paths(value,source,target)
        if updated!=value:
            prior=backup/'before_path_rewrite'/name;prior.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,prior)
            path.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8');manifest['rewritten_settings'].append(name)
    manifest.update(status='complete',copied_files=len(prepared),copied_bytes=sum(v['bytes'] for v in manifest['files']))
    (backup/'migration-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args()
    from paths import data_directory
    backup=ROOT/'_local'/'migrations'/datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    result=migrate(args.source,data_directory(),backup)
    print(json.dumps({'status':result['status'],'copied_files':result['copied_files'],'copied_bytes':result['copied_bytes'],'rewritten_settings':result['rewritten_settings'],'manifest':str(backup/'migration-manifest.json')},indent=2))

if __name__=='__main__':main()
