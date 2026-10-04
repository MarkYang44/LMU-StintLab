"""Extract a fresh portable ZIP and verify it without the source virtualenv."""
import argparse
import json
from pathlib import Path
import subprocess
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    version=(ROOT/'VERSION').read_text().strip();archive=ROOT/'dist'/f'LMU-StintLab-v{version}-windows-x64.zip'
    target=ROOT/'_local'/'validation'/uuid.uuid4().hex[:12];target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            resolved=(target/name).resolve()
            if not resolved.is_relative_to(target.resolve()):raise ValueError('Unsafe ZIP member')
        source.extractall(target)
    bundle=target/'LMU-StintLab';exe=bundle/'LMU-StintLab.exe';report=target/'doctor.json'
    subprocess.run([str(exe),'--doctor','--doctor-output',str(report)],cwd=bundle,check=True,timeout=60)
    result=json.loads(report.read_text(encoding='utf-8'));assert result['ok'],result
    print('Independent portable environment: PASS',flush=True)
    if args.smoke:
        subprocess.run([str(exe),'--release-smoke'],cwd=bundle,check=True,timeout=180)
        result=json.loads((bundle/'data'/'release-smoke.json').read_text(encoding='utf-8'))
        assert result['ok'],result
        print('Synthetic complete-lap recording and offline exports: PASS',flush=True)
    print('Validation folder: '+str(bundle))

if __name__=='__main__':main()
