"""Copy reviewed GTD icons, extracting existing PNG frames losslessly."""
from pathlib import Path
import shutil
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.audit_publication import audit
SIZES=(16,32,48,64,128,256)

def render(destination=None):
    source=ROOT/'src/branding'
    names=['src/branding/gtd.ico','src/branding/gtd-menu.png']
    result=audit(names,lambda name:(ROOT/name).read_bytes())
    if not result['ok']:raise ValueError('Unreviewed brand asset: '+str(result['failures']))
    target=Path(destination or ROOT/'_local/branding');target.mkdir(parents=True,exist_ok=True)
    blob=(source/'gtd.ico').read_bytes()
    if struct.unpack_from('<HHH',blob)!=(0,1,len(SIZES)):raise ValueError('Invalid icon directory')
    for index,size in enumerate(SIZES):
        w,h,_,_,planes,bits,length,offset=struct.unpack_from('<BBBBHHII',blob,6+index*16)
        frame=blob[offset:offset+length]
        if (w or 256,h or 256,bits)!=(size,size,32) or planes not in (0,1) or frame[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid icon frame')
        (target/f'stintrix-{size}.png').write_bytes(frame)
    shutil.copyfile(source/'gtd.ico',target/'stintrix.ico')
    shutil.copyfile(source/'gtd-menu.png',target/'menu-icon.png')
    return target

if __name__=='__main__':print(render())
