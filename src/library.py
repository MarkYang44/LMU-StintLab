"""Plugin-local inventory and notes. Never edits original session metadata."""
import json
from pathlib import Path
from storage import atomic_json


def inventory(root):
    root=Path(root).resolve();out=[]
    try:notes=json.loads((root/'library_notes.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):notes={}
    for name in ('Logs','ImportedLogs','RecoveredLogs','DemoLogs'):
        for meta_path in (root/name).glob('*/session.json'):
            folder=meta_path.parent.resolve()
            if not folder.is_relative_to(root):continue
            try:
                meta=json.loads(meta_path.read_text(encoding='utf-8'));summary={};analysis={}
                for file,target in [('fastest_lap_summary.json',summary),('session_analysis.json',analysis)]:
                    path=folder/file
                    if path.exists():target.update(json.loads(path.read_text(encoding='utf-8')))
                key=str(folder.relative_to(root));note=notes.get(key,{})
                lap=summary.get('lap',{});stable=analysis.get('recent_stability',{})
                out.append(dict(key=key,folder=str(folder),track=meta.get('track',''),vehicle=meta.get('vehicle',''),
                    date=meta.get('started_utc',''),driver=meta.get('driver',''),status=meta.get('status',''),source=name,
                    lap=lap.get('number'),time_s=lap.get('time_s'),fastest_file=summary.get('file'),
                    stable_file=analysis.get('stable_reference_file'),stability_s=stable.get('std'),
                    note=str(note.get('text','')),traffic=bool(note.get('traffic',False)),
                    size_mb=(folder/'inputs.csv').stat().st_size/1048576 if (folder/'inputs.csv').exists() else 0))
            except (OSError,ValueError,TypeError):continue
    return sorted(out,key=lambda x:x['date'],reverse=True)


def save_note(root,key,text,traffic=False):
    root=Path(root).resolve();path=(root/key).resolve()
    if not path.is_relative_to(root):raise ValueError('记录不在插件目录')
    try:notes=json.loads((root/'library_notes.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):notes={}
    notes[key]=dict(text=str(text)[:2000],traffic=bool(traffic));atomic_json(root/'library_notes.json',notes)
