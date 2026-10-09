"""Confirmed permanent deletion of exactly one validated local session."""
import json
from itertools import chain
from pathlib import Path
import shutil
from session_archive import COLLECTIONS,_safe_path
from storage import atomic_json

def remove(root,key):
    root=Path(root).resolve();relative=_safe_path(str(key).replace(chr(92),'/'))
    if len(relative.parts)!=2 or relative.parts[0] not in COLLECTIONS:raise ValueError('记录路径无效')
    relative=Path(*relative.parts);source=root/relative;folder=source.resolve()
    if folder==root or not folder.is_relative_to(root):raise ValueError('记录路径无效')
    for path in (source,source.parent):
        if path.is_symlink() or path.is_junction():raise ValueError('记录路径无效')
    if (folder/'.storage_compression.pending').exists():raise ValueError('该赛事正在压缩，请稍后重试')
    meta=json.loads((folder/'session.json').read_text(encoding='utf-8-sig'))
    if not isinstance(meta,dict):raise ValueError('比赛信息无效')
    if meta.get('status') in ('recording','write_error'):raise ValueError('请等记录完整保存后再操作')
    # No links are followed, and every resolved path stays in this exact session.
    for path in chain((folder,),folder.rglob('*')):
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(folder):
            raise ValueError('记录包含链接，不能删除')
    notes_path=root/'library_notes.json';notes=None
    if notes_path.is_symlink() or notes_path.is_junction():raise ValueError('记录路径无效')
    if notes_path.is_file():
        try:
            loaded=json.loads(notes_path.read_text(encoding='utf-8'))
            if isinstance(loaded,dict):
                notes=dict(loaded)
                for name in list(notes):
                    if name.replace(chr(92),'/').casefold()==relative.as_posix().casefold():notes.pop(name)
                if notes==loaded:notes=None
        except (OSError,ValueError):pass
    shutil.rmtree(folder)
    warning=''
    if notes is not None:
        try:atomic_json(notes_path,notes)
        except OSError as error:warning=str(error)
    return dict(key=relative.as_posix(),notes_warning=warning)


def remove_many(root,keys):
    """Deduplicate a frozen selection; report failures without hiding successes."""
    deleted=[];failed=[];warnings=[];seen=set()
    for key in keys:
        normalized=str(key).replace(chr(92),'/');identity=normalized.casefold()
        if identity in seen:continue
        seen.add(identity)
        try:
            result=remove(root,normalized);deleted.append(result['key'])
            if result['notes_warning']:warnings.append((normalized,result['notes_warning']))
        except (OSError,ValueError) as error:failed.append((normalized,str(error)))
    return dict(deleted=deleted,failed=failed,warnings=warnings)
