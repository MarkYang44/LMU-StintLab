"""Fetch one pinned, public-domain official console binary; no system install."""
import hashlib,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sevenzip import VERSION,URL,SHA256

def install():
    target=ROOT/'_local/dependencies/7zip'/VERSION/'7zr.exe';target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==SHA256:return target
    request=urllib.request.Request(URL,headers={'User-Agent':'LMU-Stintrix-Setup'})
    with urllib.request.urlopen(request,timeout=60) as response:blob=response.read(8*1024**2)
    if hashlib.sha256(blob).hexdigest()!=SHA256:raise ValueError('Official 7zr SHA256 mismatch')
    pending=target.with_suffix('.pending');pending.write_bytes(blob);pending.replace(target)
    return target

if __name__=='__main__':print('Official 7zr '+VERSION+': SHA256 verified; '+str(install()))
