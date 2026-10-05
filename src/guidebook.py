"""Self-contained GTD guide snapshot; no Flask, downloads or live telemetry."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
from urllib.parse import urlencode
from paths import ASSETS,data_directory
from control_theme import T,PALETTES


@lru_cache(maxsize=1)
def catalog(assets=None):
    value=json.loads((Path(assets or ASSETS)/'guide/catalog.json').read_text(encoding='utf-8'))
    if value.get('format')!='stintrix.guide' or value.get('version')!=1:raise ValueError('指南资料格式无效')
    return value


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def target(root,relative):
    path=root/relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or path.is_junction():raise ValueError('指南输出目录包含外部链接')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def prepare(root=None,assets=None):
    """Materialize one reusable offline page and only reviewed public images."""
    root=Path(root or data_directory()).resolve();assets=Path(assets or ASSETS)/'guide'
    folder=target(root,'Guide/index.html').parent
    provenance=json.loads((assets/'provenance.json').read_text(encoding='utf-8'))
    for rel,wanted in provenance['asset_hashes'].items():
        relative=Path(rel).relative_to('src/guide')
        if relative.parts[0]!='media' or relative.suffix!='.webp':raise ValueError('指南图片路径无效')
        source=assets/relative;destination=target(root,Path('Guide')/relative)
        if destination.is_file() and digest(destination)==wanted:continue
        if digest(source)!=wanted:raise ValueError('指南图片校验失败')
        pending=destination.with_suffix('.webp.pending')
        try:shutil.copyfile(source,pending);pending.replace(destination)
        finally:pending.unlink(missing_ok=True)
    html=(assets/'index.html').read_text(encoding='utf-8')
    css=(assets/'guide.css').read_text(encoding='utf-8');script=(assets/'guide.js').read_text(encoding='utf-8')
    payload=(assets/'catalog.json').read_text(encoding='utf-8').replace('<','\\u003c')
    html=html.replace('/*GUIDE_CSS*/',css).replace('/*GUIDE_SCRIPT*/',script).replace('/*GUIDE_DATA*/',payload)
    html=html.replace('/*GUIDE_PALETTES*/',json.dumps(PALETTES,ensure_ascii=False).replace('<','\\u003c'))
    path=folder/'index.html'
    if not path.is_file() or digest(path)!=hashlib.sha256(html.encode('utf-8')).hexdigest():
        pending=path.with_suffix('.html.pending')
        try:pending.write_text(html,encoding='utf-8',newline='\n');pending.replace(path)
        finally:pending.unlink(missing_ok=True)
    return path


def page_url(path,view='tracks',item='',theme=None):
    data=catalog();view=view if view in ('tracks','cars') else 'tracks'
    if item and item not in data[view]:raise ValueError('指南条目不存在')
    values=dict(view=view,theme=theme if theme in PALETTES else T.mode)
    if item:values['item']=item
    return Path(path).resolve().as_uri()+'#'+urlencode(values)
