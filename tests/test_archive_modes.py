"""Fast legacy import, 7z fidelity and retained path/corruption boundaries."""
import json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
import archive_preferences,session_archive as packs,sevenzip
from tests import test_archives as fixtures
from library import inventory

class ArchiveModeTests(unittest.TestCase):
    def test_fast_legacy_zip_skips_hash_and_existing_scans_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            data,folder=fixtures.ArchiveTests().fixture(directory);before=fixtures.ArchiveTests().hashes(folder)
            package=packs.export_session(data,'Logs/Fixture',Path(directory)/'out')['path'];target=Path(directory)/'import'
            with patch.object(packs,'_matches',side_effect=AssertionError('existing hash scan')),patch.object(packs,'_digest',side_effect=AssertionError('file hash')),patch.object(packs,'_identity',side_effect=AssertionError('manifest hash')),patch.object(packs.hashlib,'sha256',side_effect=AssertionError('sample hash')):
                result=packs.import_session(target,package,verify=False)
            restored=Path(result['folder']);actual=fixtures.ArchiveTests().hashes(restored)
            self.assertEqual({n:actual[n] for n in before},before)
            self.assertEqual(json.loads((restored/'_archive_receipt.json').read_text())['verification'],'fast')
            again=packs.import_session(target,package,verify=False);self.assertNotEqual(again['folder'],result['folder'])
            self.assertEqual(fixtures.ArchiveTests().hashes(folder),before)
    def test_optional_full_verification_rejects_wrong_manifest_digest_but_fast_does_not(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            data,_=fixtures.ArchiveTests().fixture(directory);package=packs.export_session(data,'Logs/Fixture',Path(directory)/'out')['path']
            modified=fixtures.ArchiveTests().rewrite(package,Path(directory)/'modified.zip',lambda n,b:b.replace(b'fixture',b'changed') if n=='session/review.html' else b)
            with self.assertRaisesRegex(ValueError,'校验失败'):packs.import_session(Path(directory)/'full',modified,verify=True)
            result=packs.import_session(Path(directory)/'fast',modified,verify=False)
            self.assertIn('changed',(Path(result['folder'])/'review.html').read_text())
    def test_fast_path_still_rejects_traversal_links_unknown_files_and_bad_metadata(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            data,_=fixtures.ArchiveTests().fixture(directory);package=packs.export_session(data,'Logs/Fixture',Path(directory)/'out')['path']
            for name in ('../outside.txt','session/C:bad','unexpected.txt'):
                bad=fixtures.ArchiveTests().rewrite(package,Path(directory)/'bad.zip',extras=[(name,b'bad')])
                with self.assertRaises(ValueError):packs.import_session(Path(directory)/'fast',bad,verify=False)
            self.assertFalse((Path(directory)/'outside.txt').exists())
    def test_sevenzip_roundtrip_both_modes_preserves_nested_unicode_images_and_notes(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            data,folder=fixtures.ArchiveTests().fixture(directory)
            nested=folder/'session'/'子目录';nested.mkdir(parents=True)
            (nested/'图像.png').write_bytes(b'\x89PNG\r\n\x1a\nUNCHANGED');(nested/'@选项 - test.txt').write_text('赛车 🏎️\n原始精度 .123456789012345',encoding='utf-8')
            before=fixtures.ArchiveTests().hashes(folder);package=packs.export_session(data,'Logs/Fixture',Path(directory)/'out',format='7z')
            self.assertTrue(package['path'].endswith('.stintrix.7z'))
            for verify in (False,True):
                target=Path(directory)/str(verify);result=packs.import_session(target,package['path'],verify=verify);restored=Path(result['folder'])
                actual=fixtures.ArchiveTests().hashes(restored);self.assertEqual({n:actual[n] for n in before},before)
                item=inventory(target)[0];self.assertTrue(item['traffic']);self.assertIn('测试备注',item['note'])
                if verify:self.assertEqual(packs.import_session(target,package['path'])['status'],'skipped')
            self.assertEqual(fixtures.ArchiveTests().hashes(folder),before)
    def test_sevenzip_corrupt_stream_rolls_back_even_in_fast_mode(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            data,_=fixtures.ArchiveTests().fixture(directory);package=packs.export_session(data,'Logs/Fixture',Path(directory)/'out',format='7z')['path']
            blob=bytearray(Path(package).read_bytes());blob[len(blob)//2]^=0xff;p=Path(directory)/'broken.7z';p.write_bytes(blob)
            target=Path(directory)/'target'
            with self.assertRaises((ValueError,OSError)):packs.import_session(target,p,verify=False)
            self.assertFalse(inventory(target));self.assertFalse(list((target/'ImportedLogs').glob('.stintrix-*')))
    def test_preferences_default_fast_and_zip_and_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);self.assertEqual(archive_preferences.load(root),dict(format='zip',verify=False))
            archive_preferences.save(root,'7z',True);self.assertEqual(archive_preferences.load(root),dict(format='7z',verify=True))
            with self.assertRaises(ValueError):archive_preferences.save(root,'rar',False)
    def test_untrusted_sevenzip_tool_is_never_executed(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);(root/'tools').mkdir();(root/'tools/7zr.exe').write_bytes(b'fake')
            with patch.object(sevenzip,'ASSETS',root):
                with self.assertRaisesRegex(ValueError,'校验失败'):sevenzip.executable()
    def test_menu_defaults_and_persisted_fast_option_are_available_in_both_languages(self):
        if os.name!='nt':self.skipTest('Windows native menu')
        from control_center import ControlCenter
        import i18n
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.show_page(4);center.root.update()
                self.assertFalse(center.archive_verify.get());self.assertEqual(center.archive_format.get(),'ZIP')
                self.assertNotEqual(i18n.catalog()['导入时完整校验'],'导入时完整校验')
                archive_preferences.save(directory,'7z',True)
                center.show_page(0);center.show_page(4);center.root.update()
                self.assertTrue(center.archive_verify.get());self.assertEqual(center.archive_format.get(),'7z')
            finally:center.close()
            self.assertFalse(errors,errors)
