"""Extract a fresh portable ZIP and verify it without the source virtualenv."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'src'))
from tools.build import bundle_audit

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--archive',type=Path);args=parser.parse_args()
    version=(ROOT/'VERSION').read_text().strip()
    archive=args.archive or ROOT/'dist'/f'LMU-StintLab-v{version}-windows-x64.zip'
    target=ROOT/'_local'/'validation'/uuid.uuid4().hex[:12];target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            resolved=(target/name).resolve()
            if not resolved.is_relative_to(target.resolve()):raise ValueError('Unsafe ZIP member')
        source.extractall(target)
    bundle=target/'LMU-StintLab';bundle_audit(bundle)
    manifest=json.loads((bundle/'build-manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']==version
    actual={p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file() and p.name!='build-manifest.json'}
    assert actual==set(manifest['files'])
    for name,digest in manifest['files'].items():
        h=hashlib.sha256()
        with (bundle/name).open('rb') as stream:
            for block in iter(lambda:stream.read(1048576),b''):h.update(block)
        assert h.hexdigest()==digest,name
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(bundle/'LMU-StintLab.exe'))
    modules=set()
    for name in archive.toc:
        if name.endswith('.pyz'):modules.update(archive.open_embedded_archive(name).toc)
    assert {'library','laps','session_archive'}<=modules
    assert not any(name.split('.')[0] in {'doctor','release_smoke','tests','tools'} for name in modules)
    assert {'control_shell','control_motion','control_list','control_theme','branding'}<=modules
    import pefile
    executable=pefile.PE(str(bundle/'LMU-StintLab.exe'))
    resources={entry.id:entry for entry in executable.DIRECTORY_ENTRY_RESOURCE.entries}
    icons=[]
    for entry in resources[3].directory.entries:
        data=entry.directory.entries[0].data.struct
        icons.append(executable.get_data(data.OffsetToData,data.Size))
    import struct
    ico=(bundle/'_internal/src/branding/stintlab.ico').read_bytes();count=struct.unpack_from('<H',ico,4)[0];expected=[]
    for i in range(count):
        length,offset=struct.unpack_from('<II',ico,6+i*16+8);expected.append(ico[offset:offset+length])
    assert set(icons)==set(expected) and count==6,'EXE icon differs from reviewed GTD icon'
    from tools.audit_publication import PUBLIC_ASSETS
    assert hashlib.sha256(ico).hexdigest()==PUBLIC_ASSETS['src/branding/gtd.ico']
    assert hashlib.sha256((bundle/'_internal/src/branding/menu-icon.png').read_bytes()).hexdigest()==PUBLIC_ASSETS['src/branding/gtd-menu.png']
    executable.close()
    print('Portable manifest, privacy and development-code exclusion: PASS',flush=True)
    if args.smoke:
        from tests.portable_smoke import run
        run(bundle,target/'synthetic-data')
        print('Shipping EXE, normal shutdown, complete-lap reports and archive roundtrip: PASS',flush=True)
    print('Validation folder: '+str(bundle))

if __name__=='__main__':main()
