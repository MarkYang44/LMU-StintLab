"""Fetch exact official PyPI wheels, verify SHA256, then install locally."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def choose_wheel(files):
    suffixes=('none-any.whl','none-win_amd64.whl','cp313-cp313-win_amd64.whl')
    wheels=[f for f in files if any(f['filename'].endswith(s) for s in suffixes) and not f.get('yanked')]
    if len(wheels)!=1:raise ValueError('Expected one compatible Windows x64 / Python 3.13 wheel')
    return wheels[0]

def fetch(url):
    if not url.startswith(('https://pypi.org/','https://files.pythonhosted.org/')):
        raise ValueError('Unexpected dependency host')
    request=urllib.request.Request(url,headers={'User-Agent':'LMU-StintLab-Setup/0.1.3'})
    with urllib.request.urlopen(request,timeout=30) as response:return response.read()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--build',action='store_true');args=parser.parse_args()
    requirement=ROOT/('requirements-lock.txt' if args.build else 'requirements.txt')
    cache=ROOT/'_local'/'wheels';cache.mkdir(parents=True,exist_ok=True)
    for line in requirement.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+==[0-9.]+',line):raise ValueError('Only pinned dependencies are accepted')
        name,version=line.split('==')
        info=json.loads(fetch(f'https://pypi.org/pypi/{name}/{version}/json'))
        wheel=choose_wheel(info['urls']);filename=wheel['filename']
        if Path(filename).name!=filename:raise ValueError('Invalid wheel filename')
        target=cache/filename
        blob=target.read_bytes() if target.exists() else fetch(wheel['url'])
        if hashlib.sha256(blob).hexdigest()!=wheel['digests']['sha256']:
            # A bad cached download is never installed. Retry using verified bytes.
            blob=fetch(wheel['url'])
            if hashlib.sha256(blob).hexdigest()!=wheel['digests']['sha256']:raise ValueError('Checksum mismatch: '+filename)
        target.write_bytes(blob);print(name+' '+version+': SHA256 verified',flush=True)
    subprocess.run([sys.executable,'-m','pip','install','--no-index','--find-links',str(cache),
        '--disable-pip-version-check','-r',str(requirement)],check=True,cwd=ROOT)

if __name__=='__main__':main()
