"""Fail closed: only public source/documentation, never local racing data."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'.gitignore','.gitattributes','README.md','LICENSE','THIRD_PARTY_NOTICES.md','VERSION',
    'requirements.txt','requirements-build.txt','requirements-lock.txt','Setup.cmd','Start.cmd','Start Clean.cmd','Start Clean Controls.cmd','Start Demo.cmd','Demo.cmd'}
PRIVATE_PARTS={'data','logs','demologs','importedlogs','recoveredlogs','selectedlaps','diagnostics','_local','_backup','_verification','__pycache__','.venv','vendor','runtime','racecomrenderer','_racecom','_report_history'}
PRIVATE_NAMES={'local_settings.json','settings.json','reference_settings.json','vehicle_settings.json','endurance_settings.json','last_native_import.json','session.json','recording_checkpoint.json','vehicle_checkpoint.json',
    'race_log.json','race_summary.json','race_images.json','race_events_checkpoint.json','race_images_error.txt','car_calibration.json',
    'renderer_settings.json','image_generate_config.json','interface_settings.json','guide_settings.json','desktop_registration.json','storage_settings.json','storage_compression.json','archive_settings.json'}
DENIED_SUFFIXES={'.csv','.duckdb','.db','.log','.gz','.zip','.7z','.exe','.dll','.pyd','.pyc','.pdf','.png','.jpg','.svg'}
SECRET_PATTERNS=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'gh[pousr]_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{30,}',rb'AKIA[0-9A-Z]{16}',rb'sk-[A-Za-z0-9_-]{40,}']
PUBLIC_ASSETS={'src/branding/stx-app.png': '8f1d9730f44ee12cc63136f31484cbc77a9ae7c8c0baa1f19718f0ba3bfc6896', 'src/branding/stx-menu.png': 'c55573b6ea082572ea7302ab5073a21369c84e68188cb186bea8351e3f8ca738', 'src/branding/stx-menu-light.png': '5bc03c16a0d037fb6bc09a12c9adf524b337180841fde3e8c0c8153fce374864'}
sys.path.insert(0,str(ROOT))
from tools.guide_assets import GUIDE_ASSETS
PUBLIC_ASSETS.update(GUIDE_ASSETS)

PRIVATE_PATTERNS=[rb'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s]+',rb'(?i)[A-Z]:[\\/]+(?:SteamLibrary|SPD)[\\/]+']

def git_command(*args):
    """Trust this exact checkout per invocation, including cross-owner installs."""
    return ['git','-c','safe.directory=','-c','safe.directory='+ROOT.as_posix(),*args]

def allowed(name):
    path=PurePosixPath(name);parts=[p.casefold() for p in path.parts]
    if any(p in PRIVATE_PARTS for p in parts) or path.name.casefold() in PRIVATE_NAMES:return False
    if name in PUBLIC_ASSETS:return True
    if path.suffix.casefold() in DENIED_SUFFIXES or name.endswith('.lap.json'):return False
    if len(path.parts)==1:return name in ROOT_FILES
    return (path.parts[0]=='src' and path.suffix in ('.py','.js','.html','.css','.json','.txt')) or (path.parts[0]=='tools' and path.suffix in ('.py','.ps1','.cmd')) or (path.parts[0]=='tests' and path.suffix=='.py') or (path.parts[0]=='docs' and path.suffix=='.md') or (path.parts[0]=='.github' and path.suffix in ('.yml','.yaml','.md'))

def audit(files,read):
    failures=[];total=0
    for name in files:
        if not allowed(name):failures.append(name+': outside publication allowlist');continue
        blob=read(name);total+=len(blob)
        if name in PUBLIC_ASSETS:
            if hashlib.sha256(blob).hexdigest()!=PUBLIC_ASSETS[name]:failures.append(name+': reviewed asset checksum mismatch')
            continue
        try:blob.decode('utf-8-sig')
        except UnicodeError:failures.append(name+': non-text content');continue
        if len(blob)>2_000_000:failures.append(name+': unexpectedly large source file')
        if any(re.search(p,blob) for p in SECRET_PATTERNS):failures.append(name+': possible credential')
        # The audit contains the denial rules as patterns, so exclude its own literals.
        if name!='tools/audit_publication.py' and any(re.search(p,blob) for p in PRIVATE_PATTERNS):failures.append(name+': machine-specific private path or identifier')
    return dict(ok=not failures,files=len(files),bytes=total,failures=failures)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--working-tree',action='store_true');parser.add_argument('--json',action='store_true');args=parser.parse_args()
    if args.working_tree:
        files=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and not any(part in ('.git','.venv','_local','dist','build','data','__pycache__') for part in p.relative_to(ROOT).parts) and allowed(p.relative_to(ROOT).as_posix())]
        read=lambda name:(ROOT/name).read_bytes()
    else:
        files=subprocess.check_output(git_command('ls-files','-z'),cwd=ROOT).decode('utf-8').split('\0');files=[f for f in files if f]
        read=lambda name:subprocess.check_output(git_command('show',':'+name),cwd=ROOT)
    result=audit(files,read);print(json.dumps(result,indent=2) if args.json else f"Publication audit: {'PASS' if result['ok'] else 'FAIL'}; {result['files']} public files, {result['bytes']} bytes"+('\n'+'\n'.join(result['failures']) if result['failures'] else ''))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
