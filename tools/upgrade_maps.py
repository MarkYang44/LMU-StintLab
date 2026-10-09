"""Upgrade only the bounded map renderer in existing local offline reports."""
import argparse,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from paths import ASSETS,data_directory
from storage import atomic_json
PATTERN=re.compile(rb'const InputScopeTrack=\(\(\)=>\{\r?\n.*?\r?\n\}\)\(\);',re.S)

def replace_renderer(content,renderer):
    matches=list(PATTERN.finditer(content))
    if len(matches)!=1:raise ValueError('Expected exactly one offline map renderer')
    match=matches[0];prefix=content[:match.start()];suffix=content[match.end():]
    result=prefix+renderer+suffix
    # Embedded recordings, catalogs, replay state and other code stay byte-identical.
    assert result[:len(prefix)]==prefix and result[len(prefix)+len(renderer):]==suffix
    return result,match.group()

def upgrade(data,dry_run=False,receipt=None):
    data=Path(data).resolve();renderer=PATTERN.search((ASSETS/'trackview.js').read_bytes()).group();result=dict(updated=[],skipped=[])
    for path in sorted(data.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in ('.html','.js'):continue
        if path.is_symlink() or not path.resolve().is_relative_to(data):continue
        if path.suffix=='.js' and path.name!='trackview.js':continue
        parents=path.relative_to(data).parts
        if len(parents)>2 and parents[0] in ('Logs','ImportedLogs','RecoveredLogs','DemoLogs'):
            meta=data/parents[0]/parents[1]/'session.json'
            try:
                if json.loads(meta.read_text(encoding='utf-8-sig')).get('status') in ('recording','write_error'):continue
            except (OSError,ValueError):continue
        content=path.read_bytes()
        if b'const InputScopeTrack=' not in content:continue
        updated,_=replace_renderer(content,renderer)
        if updated==content:continue
        result['updated'].append(dict(path=path.relative_to(data).as_posix(),before_sha256=hashlib.sha256(content).hexdigest(),after_sha256=hashlib.sha256(updated).hexdigest()))
        if not dry_run:
            pending=path.with_name(path.name+'.map-upgrade.pending')
            if pending.exists():raise ValueError('An unfinished upgrade already exists')
            pending.write_bytes(updated);pending.replace(path)
            if receipt:atomic_json(receipt,result)
    if receipt:atomic_json(receipt,result)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-dir',type=Path);parser.add_argument('--dry-run',action='store_true');parser.add_argument('--receipt',type=Path);args=parser.parse_args()
    result=upgrade(args.data_dir or data_directory(),args.dry_run,args.receipt)
    print(('Would upgrade ' if args.dry_run else 'Upgraded ')+str(len(result['updated']))+' derived map renderers. CSV/JSON recordings are unchanged.')
if __name__=='__main__':main()
