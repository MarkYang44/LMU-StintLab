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
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)),patch('hud.Engine') as engine,patch('webbrowser.open') as browser:
            center=ControlCenter()
            try:
                for index in (5,6,0,5):center.show_page(index);center.root.update()
                engine.assert_not_called();browser.assert_not_called();self.assertFalse(list(Path(directory).glob('*settings.json')))
                center.guide_state['tracks']['query']='Monza';center.set_theme('light');center.root.update()
                self.assertEqual(center.guide_state['tracks']['query'],'Monza')
            finally:center.close()

    def test_native_preferences_filters_and_comparison_preserve_original_metadata(self):
        from guide_library import Library
        from tools.audit_publication import allowed
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            path=Path(directory)/'guide_settings.json';library=Library(guidebook.catalog(),path)
            self.assertFalse(path.exists());self.assertEqual(len(library.rows('tracks',{})),18)
            self.assertEqual(len(library.rows('cars',{})),24)
            self.assertEqual(library.rows('tracks',{'query':'斯帕'})[0][0]['slug'],'spa')
            self.assertTrue(all(len(recs)==4 for _,recs in library.rows('tracks',{'group':'LMGT3'})))
            library.favorite('cars','bmw-m4-lmgt3');library.favorite('tracks','monza');library.set_language('en')
            fresh=Library(library.data,path);self.assertEqual(fresh.language,'en');self.assertEqual(len(fresh.rows('cars',{'favorite':'cars'})),1)
            self.assertEqual(len(fresh.rows('tracks',{'favorite':'tracks'})),1)
            selection=[]
            for key in list(library.recommendations)[:3]:self.assertTrue(library.toggle_comparison(selection,key))
            self.assertFalse(library.toggle_comparison(selection,list(library.recommendations)[3]));self.assertEqual(len(selection),3)
            _,rec=library.item(selection[0]);self.assertIn(library.data['tracks'][rec['track_slug']]['name'],library.name(selection[0]));self.assertIsNone(rec['review']['applicable_version'])
            self.assertFalse(allowed('data/guide_settings.json'));self.assertFalse(allowed('guide_settings.json'))

    @unittest.skipUnless(os.name=='nt','Windows native card integration')
    def test_native_cards_pictures_expansion_comparison_and_release_need_no_browser(self):
        import time
        from control_center import ControlCenter
        from guide_cards import Picture
        def pump(center,duration=.24):
            deadline=time.monotonic()+duration;limit=deadline+2
            while time.monotonic()<limit:
                center.root.update();time.sleep(.01)
                guide=center.guide_page
                if time.monotonic()>=deadline and (not guide or (guide.job is None and guide.card_job is None)):break
        def walk(widget):
            yield widget
            for child in widget.winfo_children():yield from walk(child)
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)),patch('webbrowser.open') as browser:
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.show_page(6);page=center.guide_page;self.assertEqual(page.card_count,3)
                page.variables['query'].set('BMW');pump(center);self.assertEqual(len(page.rows),2)
                page.favorite('cars','bmw-m4-lmgt3');self.assertTrue((Path(directory)/'guide_settings.json').is_file())
                page.select('car:bmw-m4-lmgt3');page.select('car:bmw-m-hybrid-v8');page.compare();pump(center)
                self.assertEqual((page.state['mode'],page.card_count),('compare',2))
                center.scroll.yview_moveto(.4);pump(center)
                pictures=[v for v in walk(page.results) if isinstance(v,Picture)]
                self.assertTrue(any(v.photo for v in pictures));self.assertFalse([v.error for v in pictures if v.error])
                center.set_theme('light');pump(center);self.assertEqual(center.guide_page.state['comparison'],['car:bmw-m4-lmgt3','car:bmw-m-hybrid-v8'])
                center.guide_page.jump('tracks','monza');page=center.guide_page;page.state['expanded']=['track:monza'];page.render();pump(center)
                self.assertEqual(len([v for v in walk(page.results) if isinstance(v,Picture)]),9)
                page.variables['group'].set('LMGT3');page.filter_changed();pump(center)
                self.assertEqual(len([v for v in walk(page.results) if isinstance(v,Picture)]),5)
                center.show_page(0);pump(center);self.assertTrue(page.closed);self.assertEqual(page.variables["query"].trace_info(),[])
                self.assertTrue(all(not v.photo for v in pictures));browser.assert_not_called();self.assertFalse(errors,errors)
            finally:center.close()


    @unittest.skipUnless(os.name=='nt','Windows native source disclosure')
    def test_sources_default_collapsed_copy_and_rebuild_state_without_browser(self):
        from control_center import ControlCenter
        from guide_cards import Sources
        import i18n,control_theme
        def walk(widget):
            yield widget
            for child in widget.winfo_children():yield from walk(child)
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)),patch('webbrowser.open') as browser:
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.show_page(6);center.root.update_idletasks()
                sources=[widget for widget in walk(center.guide_page.results) if isinstance(widget,Sources)]
                self.assertEqual(len(sources),3)
                self.assertTrue(all(not widget.opened and not widget.built and not widget.panel.winfo_manager() for widget in sources))
                first=sources[0];pairs=list(first.pairs);flag=first.flag
                first.toggle();center.root.update_idletasks()
                self.assertTrue(first.opened and first.built);self.assertEqual(first.panel.winfo_manager(),'pack')
                first.copy();self.assertEqual(center.root.clipboard_get(),'\n'.join(url for _,url in pairs))
                children=first.panel.winfo_children();first.toggle();first.toggle()
                self.assertEqual(first.panel.winfo_children(),children)
                center.toggle_language();center.set_theme('light');center.root.update_idletasks()
                replacement=next(widget for widget in walk(center.guide_page.results) if isinstance(widget,Sources) and widget.flag==flag)
                self.assertTrue(replacement.opened);self.assertEqual([url for _,url in replacement.pairs],[url for _,url in pairs])
                self.assertIn('Sources',replacement.heading.label)
                replacement.toggle();self.assertFalse(replacement.panel.winfo_manager())
                center.set_theme('dark');center.root.update_idletasks()
                replacement=next(widget for widget in walk(center.guide_page.results) if isinstance(widget,Sources) and widget.flag==flag)
                self.assertFalse(replacement.opened);self.assertFalse(replacement.built)
                center.show_page(5);center.root.update_idletasks()
                self.assertTrue(all(not widget.opened for widget in walk(center.guide_page.results) if isinstance(widget,Sources)))
                browser.assert_not_called();self.assertFalse(errors,errors)
            finally:
                center.close();i18n.set_language('zh');control_theme.set_mode('dark')
