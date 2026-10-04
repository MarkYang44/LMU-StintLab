"""Optional, private car artwork. No third-party artwork ships with StintLab."""
import json
import math
from pathlib import Path
import re
from paths import data_directory


def normalized(value):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', str(value).casefold())


def select_car(vehicle, directory=None):
    directory=Path(directory or data_directory()/'assets'/'cars').resolve()
    try:catalog=json.loads((directory/'car_calibration.json').read_text(encoding='utf-8-sig'))['cars']
    except (OSError,ValueError,KeyError,TypeError):return None
    wanted=normalized(vehicle)
    if not wanted:return None
    for filename,entry in catalog.items():
        # Match a model/explicit alias. A brand match could show the wrong car.
        if wanted not in {normalized(Path(filename).stem),*[normalized(v) for v in entry.get('aliases',[])]}:continue
        path=(directory/filename).resolve()
        if not path.is_relative_to(directory) or not path.is_file():continue
        bounds=entry.get('subject_bounds')
        if not isinstance(bounds,list) or len(bounds)!=4:continue
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in bounds):continue
        l,t,r,b=bounds
        if not l<r or not t<b:continue
        # Leave breathing room around the calibrated whole vehicle, then fit
        # this rectangle into the card without distorting its aspect ratio.
        margin=.04
        return path,(max(0,l-margin),max(0,t-margin),min(1,r+margin),min(1,b+margin))
    return None
