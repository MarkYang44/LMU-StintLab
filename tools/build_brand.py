"""Render the reviewed vector with Windows GDI+; no image library in the app."""
import json
from pathlib import Path
import re
import struct
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SIZES=(16,20,24,32,40,48,64,128,256)


def shapes(source):
    result=[]
    for node in ET.parse(source).getroot():
        kind=node.tag.rsplit('}',1)[-1]
        if kind=='path':
            tokens=re.findall(r'[MLCZ]|-?\d+(?:\.\d+)?',node.attrib['d'])
            result.append(dict(kind=kind,fill=node.attrib['fill'],tokens=tokens))
        elif kind=='circle':result.append(dict(kind=kind,**node.attrib))
    return result


def render(destination=None):
    target=Path(destination or ROOT/'_local/branding');target.mkdir(parents=True,exist_ok=True)
    config=target/'vectors.json';config.write_text(json.dumps(shapes(ROOT/'src/branding/stintlab.svg')))
    script=target/'render.ps1'
    script.write_text(r'''param([string]$Directory)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$shapes=Get-Content -LiteralPath (Join-Path $Directory 'vectors.json') -Raw | ConvertFrom-Json
foreach ($size in @(16,20,24,32,40,48,64,128,256)) {
    $scale=[single]($size*4/512)
    $big=[System.Drawing.Bitmap]::new([int]($size*4),[int]($size*4))
    $g=[System.Drawing.Graphics]::FromImage($big)
    $g.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.ScaleTransform($scale,$scale)
    foreach ($shape in $shapes) {
        $brush=New-Object System.Drawing.SolidBrush([System.Drawing.ColorTranslator]::FromHtml($shape.fill))
        if ($shape.kind -eq 'circle') {
            $r=[single]$shape.r
            $g.FillEllipse($brush,([single]$shape.cx-$r),([single]$shape.cy-$r),($r*2),($r*2))
        } else {
            $path=New-Object System.Drawing.Drawing2D.GraphicsPath
            $tokens=$shape.tokens;$i=0;$x=[single]0;$y=[single]0
            while ($i -lt $tokens.Count) {
                $command=$tokens[$i];$i++
                if ($command -eq 'M') {
                    $x=[single]::Parse($tokens[$i],[cultureinfo]::InvariantCulture);$y=[single]::Parse($tokens[$i+1],[cultureinfo]::InvariantCulture);$i+=2;$path.StartFigure()
                } elseif ($command -eq 'L') {
                    $nx=[single]::Parse($tokens[$i],[cultureinfo]::InvariantCulture);$ny=[single]::Parse($tokens[$i+1],[cultureinfo]::InvariantCulture);$i+=2
                    $path.AddLine($x,$y,$nx,$ny);$x=$nx;$y=$ny
                } elseif ($command -eq 'C') {
                    $v=@();foreach ($j in 0..5) {$v += [single]::Parse($tokens[$i+$j],[cultureinfo]::InvariantCulture)};$i+=6
                    $path.AddBezier($x,$y,$v[0],$v[1],$v[2],$v[3],$v[4],$v[5]);$x=$v[4];$y=$v[5]
                } elseif ($command -eq 'Z') {$path.CloseFigure()} else {throw 'Unsupported vector command'}
            }
            $g.FillPath($brush,$path);$path.Dispose()
        }
        $brush.Dispose()
    }
    $g.Dispose()
    $small=[System.Drawing.Bitmap]::new([int]$size,[int]$size)
    $graphics=[System.Drawing.Graphics]::FromImage($small)
    $graphics.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.CompositingMode=[System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $graphics.DrawImage($big,0,0,$size,$size)
    $small.Save((Join-Path $Directory ("stintlab-$size.png")),[System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose();$small.Dispose();$big.Dispose()
}
''',encoding='utf-8')
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),str(target)],check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    blobs=[(target/f'stintlab-{size}.png').read_bytes() for size in SIZES]
    offset=6+16*len(SIZES);directory=[]
    for size,blob in zip(SIZES,blobs):
        directory.append(struct.pack('<BBBBHHII',size if size<256 else 0,size if size<256 else 0,0,0,1,32,len(blob),offset));offset+=len(blob)
    (target/'stintlab.ico').write_bytes(struct.pack('<HHH',0,1,len(SIZES))+b''.join(directory)+b''.join(blobs))
    return target


if __name__=='__main__':print(render())
