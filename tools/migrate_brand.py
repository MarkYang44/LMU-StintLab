"""Rebrand generated HTML presentation, preserving embedded recording bytes."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from legacy_identity import BLOCK_PREFIX,REPO_NAME

def update_html(source):
    replacements=((REPO_NAME,'LMU-Stintrix'),(REPO_NAME[4:],'Stintrix'),(REPO_NAME[4:].upper(),'STINTRIX'),(BLOCK_PREFIX[:-1],'stintrix'))
    opaque=[]
    pattern=re.compile(r'(<script\b[^>]*\btype=["\']application/(?:octet-stream|json)["\'][^>]*>)(.*?)(</script>)',re.I|re.S)
    def protect(match):
        index=len(opaque);opaque.append(match.group(2))
        return match.group(1)+f'__OPAQUE_PAYLOAD_{index}__'+match.group(3)
    value=pattern.sub(protect,source)
    # Legacy inline comparison payloads are data, not interface text.
    inline=re.compile(r'^(const (?:initial|meta|rows|payload|session)=)([\[{].*)(;\s*)$',re.M)
    def protect_inline(match):
        index=len(opaque);opaque.append(match.group(2))
        return match.group(1)+f'__OPAQUE_PAYLOAD_{index}__'+match.group(3)
    value=inline.sub(protect_inline,value)
    for old,new in replacements:value=value.replace(old,new)
    for index,payload in enumerate(opaque):value=value.replace(f'__OPAQUE_PAYLOAD_{index}__',payload)
    # Confirm every protected telemetry block is byte-identical after substitution.
    original=[m.group(2) for m in pattern.finditer(source)]
    rewritten=[m.group(2) for m in pattern.finditer(value)]
    if original!=rewritten:raise ValueError('Embedded recording payload changed')
    return value

def migrate(data,backup):
    data=Path(data).resolve();backup=Path(backup).resolve()
    if backup==data or backup.is_relative_to(data):raise ValueError('Backup must be outside live data')
    backup.mkdir(parents=True,exist_ok=False);receipt=[]
    for path in sorted(data.rglob('*.html')):
        relative=path.relative_to(data)
        if any(part in ('RaceComRenderer','_racecom','_report_history') for part in relative.parts):continue
        metadata=path.parent/'session.json'
        if metadata.exists() and json.loads(metadata.read_text(encoding='utf-8')).get('status')=='recording':continue
        original=path.read_text(encoding='utf-8');updated=update_html(original)
        if original==updated:continue
        saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,saved)
        pending=path.with_name(path.name+'.brand.pending');pending.write_text(updated,encoding='utf-8');pending.replace(path)
        receipt.append(dict(path=relative.as_posix(),original_sha256=hashlib.sha256(saved.read_bytes()).hexdigest(),updated_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (backup/'manifest.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('data');parser.add_argument('backup');args=parser.parse_args()
    print(json.dumps(dict(updated=len(migrate(args.data,args.backup)))))
