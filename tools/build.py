"""Independent Windows bundle: public assets only, never local racing data."""
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ASSET_NAMES=('report.html','compare.html','dataview.js','trackview.js','laplab.js','vehicleview.js','enduranceview.js','interface_theme.js','tracks/catalog.json','guide/catalog.json','guide/provenance.json')
STARTERS=('Start.cmd','Start Clean.cmd','Start Clean Controls.cmd','Start Demo.cmd','Demo.cmd')
PORTABLE_DOCS=('USAGE.md','PRIVACY.md')
PORTABLE_ROOT_FILES={'LMU-StintLab.exe','README.md','LICENSE','THIRD_PARTY_NOTICES.md','VERSION','build-manifest.json',*STARTERS}

def bundle_audit(folder):
    private={'data','logs','demologs','importedlogs','recoveredlogs','selectedlaps','diagnostics','.venv','_local','_backup','_verification','racecomrenderer','_racecom','_report_history'}
    denied={'local_settings.json','settings.json','session.json','reference_settings.json','vehicle_settings.json','endurance_settings.json','last_native_import.json',
        'race_log.json','race_summary.json','race_images.json','race_events_checkpoint.json','race_images_error.txt','car_calibration.json',
        'renderer_settings.json','image_generate_config.json','interface_settings.json','guide_settings.json'}
    for file in Path(folder).rglob('*'):
        if not file.is_file():continue
        rel=file.relative_to(folder)
        if rel.parts[0] not in {'_internal','licenses','docs'} and rel.as_posix() not in PORTABLE_ROOT_FILES:
            raise ValueError('Development or unexpected file in bundle: '+rel.as_posix())
        if rel.parts[0]=='docs' and rel.as_posix() not in {'docs/'+name for name in PORTABLE_DOCS}:
            raise ValueError('Development document in bundle: '+rel.as_posix())
        if any(p.casefold() in private for p in rel.parts) or file.name.casefold() in denied or file.name.endswith('.lap.json') or file.suffix.lower() in ('.csv','.duckdb','.db','.log','.gz'):
            raise ValueError('Private output in bundle: '+rel.as_posix())
    return True

def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,13) or struct.calcsize('P')!=8:
        raise SystemExit('Build requires Windows x64 and CPython 3.13. Run tools/Build.cmd.')
    subprocess.run([sys.executable,str(ROOT/'tools'/'audit_publication.py'),'--working-tree'],cwd=ROOT,check=True)
    version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
    build_id=uuid.uuid4().hex[:12]
    work=ROOT/'_local'/'build'/build_id;stage=ROOT/'dist'/('stage-'+build_id)
    work.mkdir(parents=True);stage.mkdir(parents=True)
    sys.path.insert(0,str(ROOT))
    from tools.build_brand import render
    brand=render(work/'branding')
    parts=tuple(int(n) for n in version.split('.'))+(0,)
    version_file=work/'version-info.txt'
    version_file.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers="+repr(parts)+",prodvers="+repr(parts)+",mask=0x3f,flags=0,OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=[StringFileInfo([StringTable('040904B0',[StringStruct('FileDescription','LMU StintLab Control Center'),StringStruct('ProductName','LMU StintLab'),StringStruct('OriginalFilename','LMU-StintLab.exe'),StringStruct('FileVersion','"+version+"'),StringStruct('ProductVersion','"+version+"')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])",encoding='utf-8')
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
        '--noupx','--name','LMU-StintLab','--paths',str(ROOT/'src'),
        '--icon',str(brand/'stintlab.ico'),'--version-file',str(version_file),
        '--workpath',str(work/'work'),'--specpath',str(work),'--distpath',str(stage),
        '--hidden-import','pyLMUSharedMemory.lmu_data','--collect-all','duckdb',
        '--exclude-module','doctor','--exclude-module','release_smoke',
        '--exclude-module','tests','--exclude-module','tools']
    for name in ASSET_NAMES:
        relative=Path(name)
        args.extend(['--add-data',str(ROOT/'src'/relative)+';'+(Path('src')/relative.parent).as_posix()])
    for name in ('stintlab.ico','stintlab-32.png','stintlab-48.png','stintlab-64.png','stintlab-128.png','menu-icon.png'):
        args.extend(['--add-data',str(brand/name)+';src/branding'])
    for image in (ROOT/'src/guide/media').rglob('*.webp'):
        args.extend(['--add-data',str(image)+';'+image.parent.relative_to(ROOT).as_posix()])
    args.append(str(ROOT/'src'/'inputscope.py'))
    subprocess.run(args,cwd=ROOT,check=True)
    bundle=stage/'LMU-StintLab'
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md','VERSION',*STARTERS):
        shutil.copy2(ROOT/name,bundle/name)
    shutil.copy2(ROOT/'docs'/'PORTABLE.md',bundle/'README.md')
    (bundle/'docs').mkdir()
    for name in PORTABLE_DOCS:shutil.copy2(ROOT/'docs'/name,bundle/'docs'/name)
    licenses=bundle/'licenses';licenses.mkdir()
    shutil.copy2(ROOT/'src'/'pyLMUSharedMemory'/'License.txt',licenses/'pyLMUSharedMemory-MIT.txt')
    for file in (ROOT/'src'/'licenses').glob('*.txt'):shutil.copy2(file,licenses/file.name)
    dependencies={}
    for name in ('duckdb','pillow','pyinstaller','altgraph','packaging','pefile','pyinstaller-hooks-contrib','pywin32-ctypes','setuptools'):
        distribution=metadata.distribution(name);dependencies[name]=distribution.version
        for file in distribution.files or ():
            if any(key in file.name.casefold() for key in ('license','copying','notice')) and file.suffix.casefold() in ('.txt','.md',''):
                source=Path(distribution.locate_file(file))
                if source.is_file():shutil.copy2(source,licenses/(name+'-'+source.name))
    bundle_audit(bundle)
    manifest={'project':'LMU-StintLab','version':version,'python':sys.version.split()[0],
        'platform':'windows-x64','dependencies':dependencies,'files':{}}
    for file in sorted(bundle.rglob('*')):
        if file.is_file():manifest['files'][file.relative_to(bundle).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    (bundle/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=ROOT/'dist'/f'LMU-StintLab-v{version}-windows-x64.zip'
    pending=archive.with_name(archive.name+'.pending')
    with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for file in sorted(bundle.rglob('*')):
            if file.is_file():output.write(file,Path('LMU-StintLab')/file.relative_to(bundle))
    pending.replace(archive)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print('Portable bundle: '+str(archive));print('SHA256: '+digest)

if __name__=='__main__':main()
