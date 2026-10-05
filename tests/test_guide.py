import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import guidebook


class GuideTests(unittest.TestCase):
    def test_snapshot_keeps_every_recommendation_source_and_unverified_marker(self):
        data=guidebook.catalog();self.assertEqual((len(data['tracks']),len(data['cars']),data['total_recommendations']),(18,24,144))
        self.assertEqual((data['content_version'],data['validated_recommendations']),('2026.09.22.1',0))
        keys=set()
        for track in data['tracks'].values():
            self.assertEqual(len(track['recommendations']),8)
            for rec in track['recommendations']:
                self.assertNotIn(rec['key'],keys);keys.add(rec['key']);self.assertIn(rec['car_slug'],data['cars'])
                self.assertIsNone(rec['review']['applicable_version']);self.assertIsNone(rec['review']['evidence_url']);self.assertTrue(rec['review']['sources'])
        self.assertEqual(len(keys),144)
        self.assertEqual(sum(len(car['recommendations']) for car in data['cars'].values()),144)

    def test_offline_page_is_complete_reusable_and_has_only_local_runtime_assets(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);page=guidebook.prepare(root,ROOT/'src');before=page.stat().st_mtime_ns;source=page.read_text(encoding='utf-8')
            self.assertNotIn('/*GUIDE_',source);self.assertNotIn('<script src=',source);self.assertNotIn('fonts.googleapis',source)
            self.assertEqual(guidebook.prepare(root,ROOT/'src'),page);self.assertEqual(page.stat().st_mtime_ns,before)
            self.assertEqual(len(list((root/'Guide/media').rglob('*.webp'))),42)
            self.assertIn('view=cars&theme=light&item=bmw-m4-lmgt3',guidebook.page_url(page,'cars','bmw-m4-lmgt3','light'))
            with self.assertRaises(ValueError):guidebook.page_url(page,'cars','../../private')
            picture=next((root/'Guide/media').rglob('*.webp'));picture.write_bytes(b'broken');guidebook.prepare(root,ROOT/'src')
            self.assertNotEqual(picture.read_bytes(),b'broken');self.assertFalse(list(root.rglob('*.pending')))

    def test_public_artwork_is_exact_and_arbitrary_photos_remain_denied(self):
        from tools.guide_assets import GUIDE_ASSETS
        from tools.audit_publication import audit,allowed
        self.assertEqual(len(GUIDE_ASSETS),42)
        for rel,expected in GUIDE_ASSETS.items():self.assertTrue(allowed(rel));self.assertEqual(guidebook.digest(ROOT/rel),expected)
        self.assertTrue(audit(GUIDE_ASSETS,lambda name:(ROOT/name).read_bytes())['ok'])
        rel=next(iter(GUIDE_ASSETS));self.assertFalse(audit([rel],lambda _:b'user photo')['ok'])
        self.assertFalse(allowed('src/guide/media/cars/personal.webp'));self.assertFalse(allowed('data/Guide/index.html'))

    @unittest.skipUnless(shutil.which('node'),'Node available')
    def test_browser_filters_favorites_chinese_aliases_and_escaping(self):
        source="""
const fs=require('fs'),assert=require('assert');const api=require('./src/guide/guide.js');
const data=JSON.parse(fs.readFileSync('./src/guide/catalog.json','utf8'));
const favs=api.favorites({tracks:['monza','monza','bad'],cars:['bmw-m4-lmgt3','bad']},data);
assert.deepEqual(favs.tracks,['monza']);assert.equal(api.rows(data,'tracks',{},favs).length,18);
assert.equal(api.rows(data,'cars',{},favs).length,24);
assert.equal(api.rows(data,'tracks',{query:'蒙扎'},favs)[0].item.slug,'monza');
assert.equal(api.rows(data,'cars',{favorite:'cars'},favs).length,1);
assert.equal(api.rows(data,'tracks',{favorite:'tracks'},favs).length,1);
assert(api.rows(data,'tracks',{group:'LMGT3'},favs).every(v=>v.recommendations.length===4));
assert(api.rows(data,'cars',{group:'LMGT3'},favs).every(v=>v.item.car_class==='LMGT3'));
assert.equal(api.safeURL('javascript:alert(1)'), '');assert.equal(api.safeURL('file:///private'), '');
assert.equal(api.esc('<img onerror="x">'),'&lt;img onerror=&quot;x&quot;&gt;');
"""
        result=subprocess.run([shutil.which('node'),'-'],input=source,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(os.name=='nt','Windows native guide navigation')
    def test_native_pages_are_lazy_and_do_not_start_telemetry_or_write_preferences(self):
        from control_center import ControlCenter,PAGES
        self.assertEqual(PAGES[-2:],('赛道指南','车型图鉴'))
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)),patch('hud.Engine') as engine,patch('control_guide.prepare') as prepare:
            center=ControlCenter()
            try:
                for index in (5,6,0,5):center.show_page(index);center.root.update()
                engine.assert_not_called();prepare.assert_not_called();self.assertFalse(list(Path(directory).glob('*settings.json')))
                center.guide_state['tracks']['query']='Monza';center.set_theme('light');center.root.update()
                self.assertEqual(center.guide_state['tracks']['query'],'Monza')
            finally:center.close()
