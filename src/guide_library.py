"""Native guide queries and private preferences, independent of GUI and telemetry."""
import json
from pathlib import Path
from storage import atomic_json

ALIASES={'bahrain':'巴林','barcelona':'巴塞罗那 加泰罗尼亚','le-mans':'勒芒 萨尔特','paul-ricard':'保罗里卡尔','cota':'美洲 奥斯汀','daytona':'代托纳','fuji':'富士','imola':'伊莫拉','interlagos':'英特拉格斯 因特拉格斯','lusail':'卢赛尔 罗赛尔','monza':'蒙扎','portimao':'波尔蒂芒 阿尔加维','sebring':'赛百灵 塞布林','silverstone-international':'银石','spa':'斯帕 弗朗科尔尚','laguna-seca':'拉古纳塞卡','road-atlanta':'亚特兰大之路 罗德亚特兰大','long-beach':'长滩'}


class Library:
    def __init__(self,data,path):
        self.data=data;self.path=Path(path);self.language='zh';self.favorites={'tracks':set(),'cars':set()}
        self.recommendations={rec['key']:dict(rec,track_slug=track['slug']) for track in data['tracks'].values() for rec in track['recommendations']}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8-sig'))
            if isinstance(value,dict):
                self.language='en' if value.get('language')=='en' else 'zh'
                for kind in self.favorites:
                    values=value.get(kind,[])
                    if isinstance(values,list):self.favorites[kind]={v for v in values if isinstance(v,str) and v in data[kind]}
        except (OSError,ValueError):pass

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(self.path,dict(version=1,language=self.language,**{k:sorted(v) for k,v in self.favorites.items()}))

    def favorite(self,kind,slug):
        if kind not in self.favorites or slug not in self.data[kind]:raise ValueError('Unknown guide item')
        previous=set(self.favorites[kind])
        if slug in previous:self.favorites[kind].remove(slug)
        else:self.favorites[kind].add(slug)
        try:self.save()
        except OSError:self.favorites[kind]=previous;raise

    def set_language(self,value):
        previous=self.language;self.language='en' if value=='en' else 'zh'
        try:self.save()
        except OSError:self.language=previous;raise

    def text(self,item,key):return item.get(key+'_zh' if self.language=='zh' else key) or item.get(key,'') or ''
    def tr(self,zh,en):return en if self.language=='en' else zh

    def match(self,rec,state):
        return (not state.get('group') or rec['car_class']==state['group']) and (not state.get('car') or rec['car_slug']==state['car']) and (state.get('favorite')!='cars' or rec['car_slug'] in self.favorites['cars'])

    def rows(self,view,state):
        query=state.get('query','').strip().casefold();out=[]
        for item in self.data[view].values():
            searchable=' '.join(str(item.get(k,'')) for k in ('name','slug','car_class','location','location_zh'))+' '+ALIASES.get(item['slug'],'')
            if query and query not in searchable.casefold():continue
            if view=='cars':
                if state.get('group') and state['group']!=item['car_class']:continue
                if state.get('car') and state['car']!=item['slug']:continue
                if state.get('favorite') and item['slug'] not in self.favorites['cars']:continue
                out.append((item,[]))
            else:
                if state.get('favorite')=='tracks' and item['slug'] not in self.favorites['tracks']:continue
                recs=[self.recommendations[r['key']] for r in item['recommendations'] if self.match(r,state)]
                if recs:out.append((item,recs))
        return out

    def item(self,key):
        if key.startswith('car:'):return self.data['cars'].get(key[4:]),None
        rec=self.recommendations.get(key)
        return (self.data['cars'][rec['car_slug']],rec) if rec else (None,None)

    def name(self,key):
        car,rec=self.item(key)
        return '' if not car else ((self.data['tracks'][rec['track_slug']]['name']+' · ') if rec else '')+car['name']+(' · Sleeper' if rec and rec['sleeper'] else '')

    def toggle_comparison(self,selection,key):
        if not self.item(key)[0]:raise ValueError('Unknown comparison item')
        if key in selection:selection.remove(key);return True
        if len(selection)>=3:return False
        selection.append(key);return True
