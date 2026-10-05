"""Language persistence, live UI state and old release migration coverage."""
import ast,json,os,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))

class LanguageTests(unittest.TestCase):
    def test_locale_updates_preserve_theme_unknown_preferences_and_stored_values(self):
        import i18n,control_theme
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            path=Path(folder)/'interface_settings.json'
            path.write_text(json.dumps(dict(theme='light',language='zh',custom={'keep':42})))
            try:
                i18n.save(path,'en');control_theme.save(path,'dark')
                value=json.loads(path.read_text());self.assertEqual(value['language'],'en')
                self.assertEqual(value['custom'],{'keep':42});self.assertEqual(value['theme'],'dark')
                self.assertEqual(i18n.tr('标准面板'),'Standard panel')
                self.assertEqual(i18n.tr('驾驶员个人名字'),'驾驶员个人名字')
                self.assertEqual(i18n.tr('圈速单.png'),'圈速单.png')
                i18n.load(path);self.assertEqual(i18n.language,'en')
                with self.assertRaises(ValueError):i18n.save(path,'typo')
                path.write_text('[]');i18n.load(path);self.assertEqual(i18n.language,'zh')
            finally:i18n.set_language('zh');control_theme.set_mode('dark')

    def test_public_brand_and_translations_have_no_stale_ui_identity(self):
        import i18n,subprocess
        for name in ('control_center.py','control_shell.py','control_profile.py','management.py'):
            source=(ROOT/'src'/name).read_text(encoding='utf-8')
            self.assertNotIn('StintLab',source);self.assertNotIn('STINTLAB',source)
            for node in ast.walk(ast.parse(source)):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                    self.assertIn(node.args[0].value,i18n.catalog())
        for file in (ROOT/'src').glob('*.html'):
            self.assertNotIn('StintLab',file.read_text(encoding='utf-8'))

    def test_old_session_zip_imports_without_rewriting_recording_payloads(self):
        from tests.test_archives import ArchiveTests
        import session_archive as packages
        from legacy_identity import ARCHIVE_FORMAT
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            source,session=ArchiveTests().fixture(folder)
            package=packages.export_session(source,'Logs/'+session.name,Path(folder)/'packages')
            self.assertTrue(package['path'].endswith('.stintrix.zip'))
            old=Path(folder)/'old.zip'
            with zipfile.ZipFile(package['path']) as current,zipfile.ZipFile(old,'w') as output:
                for entry in current.infolist():
                    data=current.read(entry)
                    if entry.filename=='manifest.json':
                        manifest=json.loads(data);manifest['format']=ARCHIVE_FORMAT;data=json.dumps(manifest).encode()
                    output.writestr(entry,data)
            restored=packages.import_session(Path(folder)/'imported',old)
            self.assertEqual(restored['status'],'imported')
            target=Path(restored['folder'])
            for file in session.rglob('*'):
                if file.is_file():self.assertEqual(file.read_bytes(),(target/file.relative_to(session)).read_bytes())

    def test_html_rebrand_preserves_compressed_and_inline_driver_payloads(self):
        from tools.migrate_brand import update_html
        sample='<title>LMU StintLab</title><script type="application/octet-stream" id="stintlab-meta">StintLabBASE64</script>\nconst initial={"driver":"StintLab driver","format":"inputscope.fastest-lap"};\nconst theme=StintLabTheme;'
        updated=update_html(sample)
        self.assertIn('<title>LMU Stintrix</title>',updated)
        self.assertIn('id="stintrix-meta">StintLabBASE64</script>',updated)
        self.assertIn('"driver":"StintLab driver"',updated)
        self.assertIn('const theme=StintrixTheme;',updated)

    @unittest.skipUnless(os.name=='nt','Windows native UI')
    def test_language_switch_preserves_live_hud_and_page_filter_and_translates_all_pages(self):
        import tkinter as tk,i18n,control_center
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            data=Path(folder)
            with patch('control_center.ROOT',data),patch('hud.ROOT',data),patch('engine.ROOT',data),patch('recorder.make_report'):
                center=control_center.ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
                def pump(seconds):
                    end=time.monotonic()+seconds
                    while time.monotonic()<end:center.root.update();time.sleep(.01)
                try:
                    center.start(True);hud=center.hud;engine=hud.engine;recorder=engine.recorder
                    center.set_hud('mode','controls');pump(.2);before=recorder.samples
                    center.show_page(1);center.search.set('Spa');center.toggle_language();pump(.25)
                    self.assertEqual(i18n.language,'en');self.assertEqual(center.page,1);self.assertEqual(center.search.get(),'Spa')
                    self.assertIs(center.hud,hud);self.assertIs(hud.engine,engine);self.assertIs(engine.recorder,recorder)
                    self.assertGreater(recorder.samples,before);self.assertEqual(hud.canvas.cget('bg'),'#000000')
                    self.assertEqual(center.title.cget('text'),'Session Review')
                    for page,title in enumerate(('Run & HUD','Session Review','Lap Comparison','Sampling & Telemetry','Reports & Data','Circuit Guide','Car Catalog')):
                        center.show_page(page);center.root.update();self.assertEqual(center.title.cget('text'),title)
                    self.assertEqual(center.guide_page.library.language,'en')
                    center.show_page(0);self.assertEqual(center.mode_label.get(),'纯净 · 曲线 + 踏板 / 方向盘')
                    texts=[center.shell.navigation.itemcget(item,'text') for item in center.shell.navigation.find_all() if center.shell.navigation.type(item)=='text']
                    self.assertIn('Sampling & Telemetry',texts)
                    center.toggle_language();self.assertEqual(center.title.cget('text'),'运行与 HUD')
                    self.assertFalse(errors)
                finally:
                    center.close()
                    try:
                        while center.root.winfo_exists():center.root.update();time.sleep(.01)
                    except tk.TclError:pass
                    i18n.set_language('zh')

    @unittest.skipUnless(os.name=='nt','Windows Shell links')
    def test_owned_old_shortcut_migrates_only_after_new_catalog_verification(self):
        import windows_integration as integration,paths
        from legacy_identity import LINK_DESCRIPTION,EXE_NAME
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            directory=Path(folder);oldexe=directory/EXE_NAME;oldexe.write_bytes(b'old')
            newexe=directory/'LMU-Stintrix.exe';newexe.write_bytes(b'new')
            link=directory/'LMU Stintrix.lnk';old=directory/'old.lnk'
            with patch.object(integration,'APP_ROOT',directory),patch.object(integration,'executable',return_value=newexe),patch.object(integration,'shortcut_path',return_value=link),patch.object(integration,'legacy_shortcut',return_value=old),patch.object(paths,'data_directory',return_value=directory/'private'):
                with patch.object(integration,'DESCRIPTION',LINK_DESCRIPTION):
                    with integration.ShellLink() as shell:shell.configure(oldexe);shell.save(old)
                self.assertTrue(integration.owns_legacy_link())
                with patch.object(sys,'frozen',True,create=True):self.assertTrue(integration.needs_repair())
                with patch.object(integration,'catalog_entry',return_value=None):integration.register(verify=True)
                self.assertTrue(old.exists())
                with patch.object(integration,'catalog_entry',return_value={'Name':'LMU Stintrix','AppID':integration.APP_ID}):integration.register(verify=True)
                self.assertFalse(old.exists());self.assertEqual(Path(integration.inspect(link)['target']),newexe)
                with patch.object(integration,'DESCRIPTION','Foreign application'):
                    with integration.ShellLink() as shell:shell.configure(oldexe);shell.save(old)
                self.assertFalse(integration.owns_legacy_link())
