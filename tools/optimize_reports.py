"""Upgrade derived offline pages only. Originals are backed up before replacement."""
import argparse
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import reporting
from laps import track_script,write_compare
from paths import ASSETS,data_directory
from storage import atomic_json


def embedded_chunks(path,identifier):
    """Decode one HTML block incrementally, including gzip CRC/truncation checks."""
    marker=re.compile(rb'<script type="application/octet-stream" id="'+identifier.encode('ascii')+rb'" data-bytes="(\d+)">')
    decoder=zlib.decompressobj(31);total=0
    with Path(path).open('rb') as f:
        data=b''
        while True:
            chunk=f.read(65536)
            if not chunk:raise ValueError('Missing embedded block: '+identifier)
            data+=chunk;match=marker.search(data)
            if match:
                expected=int(match[1]);data=data[match.end():];break
            data=data[-256:]
        while True:
            end=data.find(b'</script>')
            if end>=0:
                raw=decoder.decompress(base64.b64decode(data[:end],validate=True))+decoder.flush()
                total+=len(raw)
                if raw:yield raw
                if not decoder.eof or decoder.unused_data or total!=expected:raise ValueError('Incomplete gzip payload')
                return
            # Retain enough bytes to recognize a split end tag and align base64.
            count=max(0,(len(data)-16)//4*4)
            if count:
                raw=decoder.decompress(base64.b64decode(data[:count],validate=True));total+=len(raw)
                if raw:yield raw
                data=data[count:]
            chunk=f.read(65536)
            if not chunk:raise ValueError('Truncated HTML payload')
            data+=chunk


def digest(chunks):
    sha=hashlib.sha256()
    for chunk in chunks:sha.update(chunk)
    return sha.hexdigest()


def comparison_payload(path):
    # Legacy pages hold a single compact JSON statement, never execute their JS.
    with Path(path).open(encoding='utf-8') as f:
        for line in f:
            if line.startswith('const initial='):
                text=line[len('const initial='):]
                if text.startswith('await '):return json.loads(b''.join(embedded_chunks(path,'stintlab-laps')))
                return json.JSONDecoder().raw_decode(text)[0]
    raise ValueError('Unrecognized comparison page')


def upgrade(data,backup=None):
    data=Path(data).resolve()
    backup=Path(backup or ROOT/'_local'/'report-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')).resolve()
    if backup==data or backup.is_relative_to(data):raise ValueError('Backup must be outside the active data directory')
    backup.mkdir(parents=True,exist_ok=False)
    staged=backup/'staged';staged.mkdir()
    pages=[]
    for name in ('Logs','DemoLogs','ImportedLogs','RecoveredLogs'):
        for folder in (data/name).glob('*'):
            if not folder.is_dir() or not (folder/'session.json').exists():continue
            meta=json.loads((folder/'session.json').read_text(encoding='utf-8'))
            if meta.get('status')=='recording':continue
            for page in folder.rglob('*.html'):pages.append(page)
    pages.extend(p for p in data.glob('*.html') if p.is_file())
    result=dict(version=1,pages=[],skipped=[],backup=str(backup),before_bytes=0,after_bytes=0)
    track_js=track_script(ASSETS)
    for i,page in enumerate(sorted(pages)):
        rel=page.relative_to(data);target=staged/(str(i)+'.html')
        if page.name=='review.html' and (page.parent/'inputs.csv').exists():
            source_sha=digest(reporting.review_records(page.parent/'inputs.csv'))
            summary=page.parent/'fastest_lap_summary.json'
            fastest=json.loads(summary.read_text(encoding='utf-8')) if summary.exists() else None
            reporting.render_review(page.parent,ASSETS,track_js,fastest,output=target)
            if digest(embedded_chunks(target,'stintlab-inputs'))!=source_sha:raise ValueError('Review samples changed')
            payload=json.loads(b''.join(embedded_chunks(target,'stintlab-meta')))
            if payload['meta']!=json.loads((page.parent/'session.json').read_text(encoding='utf-8')):raise ValueError('Session metadata changed')
            for key,name in [('analysis','session_analysis.json'),('native_channels','native_channels.json'),('endurance','endurance_analysis.json')]:
                p=page.parent/name;expected=json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
                if payload[key]!=expected:raise ValueError('Embedded analysis changed')
        else:
            try:value=comparison_payload(page)
            except (ValueError,UnicodeError):result['skipped'].append(rel.as_posix());continue
            if not isinstance(value,dict):result['skipped'].append(rel.as_posix());continue
            write_compare(target,ASSETS/'compare.html',value.get('laps',()),value.get('status'),value.get('reference_id'),view_state=value)
            actual=json.loads(b''.join(embedded_chunks(target,'stintlab-laps')))
            if actual!=value:raise ValueError('Comparison data or replay state changed')
        before,after=page.stat().st_size,target.stat().st_size
        if after>=before:
            result['skipped'].append(rel.as_posix());target.unlink();continue
        saved=backup/'originals'/rel;saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(page,saved)
        old_sha=digest(iter_file(saved))
        # Same-directory replace is atomic even when the backup is on another drive.
        pending=page.with_name(page.name+'.upgrade.pending')
        shutil.copy2(target,pending);pending.replace(page)
        item=dict(path=rel.as_posix(),before_bytes=before,after_bytes=after,original_sha256=old_sha,
            updated_sha256=digest(iter_file(page)))
        result['pages'].append(item);result['before_bytes']+=before;result['after_bytes']+=after
        atomic_json(backup/'manifest.json',result)
        print('Verified '+str(len(result['pages']))+' pages',flush=True)
        target.unlink()
    atomic_json(backup/'manifest.json',result)
    return result


def iter_file(path):
    with Path(path).open('rb') as f:yield from iter(lambda:f.read(1048576),b'')


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data-dir',type=Path);p.add_argument('--backup-dir',type=Path);args=p.parse_args()
    result=upgrade(args.data_dir or data_directory(),args.backup_dir)
    print(json.dumps({k:v for k,v in result.items() if k not in ('pages','skipped')},indent=2))
    print('All CSV/JSON recordings and settings are untouched; old HTML pages are in the backup directory.')

if __name__=='__main__':main()
