"""Encode reviewed STX artwork into Windows icon frames and menu resources."""
from io import BytesIO
from pathlib import Path
import struct
import sys
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.audit_publication import audit
SIZES=(16,32,48,64,128,256)

def render(destination=None):
    names=['src/branding/stx-app.png','src/branding/stx-menu.png']
    result=audit(names,lambda name:(ROOT/name).read_bytes())
    if not result['ok']:raise ValueError('Unreviewed brand asset: '+str(result['failures']))
    target=Path(destination or ROOT/'_local/branding');target.mkdir(parents=True,exist_ok=True)
    with Image.open(ROOT/names[0]) as artwork:
        if artwork.width!=artwork.height:raise ValueError('App artwork must be square')
        icon=artwork.convert('RGBA')
    frames=[]
    for size in SIZES:
        frame=icon.resize((size,size),Image.Resampling.LANCZOS)
        stream=BytesIO();frame.save(stream,format='PNG',optimize=True)
        png=stream.getvalue();frames.append(png)
        (target/f'stintrix-{size}.png').write_bytes(png)
    offset=6+16*len(SIZES);directory=[]
    for size,png in zip(SIZES,frames):
        directory.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(png),offset));offset+=len(png)
    (target/'stintrix.ico').write_bytes(struct.pack('<HHH',0,1,len(SIZES))+b''.join(directory)+b''.join(frames))
    with Image.open(ROOT/names[1]) as artwork:
        menu=ImageOps.contain(artwork.convert('RGB'),(512,256),Image.Resampling.LANCZOS)
        menu.save(target/'menu-icon.png',optimize=True)
    return target

if __name__=='__main__':print(render())
