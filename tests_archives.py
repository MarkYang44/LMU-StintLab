"""Session ZIP round trips, corruption rollback and hostile Windows paths."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import warnings
import zipfile
from unittest.mock import patch,Mock
ROOT=Path(__file__).parent;sys.path.insert(0,str(ROOT/'src'))
import session_archive as packs
from library import inventory,save_note
from laps import export_fastest,export_selected_laps,complete_laps
from reference import ReferenceLap
import tests as base_tests


class ArchiveTests(unittest.TestCase):
    def fixture(self,base,name='Fixture'):
        data=Path(base)/'data';folder=data/'Logs'/name
        base_tests.Tests().lap_csv(folder)
        export_fastest(folder,ROOT/'src'/'compare.html')
        export_selected_laps(folder,[1,4],ROOT/'src'/'compare.html')
        (folder/'review.html').write_text('<html>fixture review</html>',encoding='utf-8')
        (folder/'vehicle.csv').write_bytes(b'time_s,fuel_l\r\n0,50\r\n')
        save_note(data,str(folder.relative_to(data)),'测试备注 "brake, throttle"',True)
        return data,folder

    def hashes(self,folder):
        return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob('*') if p.is_file()}

    def rewrite(self,source,target,change=None,extras=()):
        with zipfile.ZipFile(source) as old,zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as new:
            for item in old.infolist():
                data=old.read(item.filename)
                if change:data=change(item.filename,data)
                new.writestr(item,data)
            for name,data in extras:new.writestr(name,data)
        return target

    def test_roundtrip_preserves_all_bytes_notes_and_complete_lap_features(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,folder=self.fixture(t);before=self.hashes(folder)
            package=packs.export_session(data,'Logs/Fixture',Path(t)/'exports')
            target=Path(t)/'restored';result=packs.import_session(target,package['path'])
            restored=Path(result['folder']);actual=self.hashes(restored)
            self.assertEqual({k:actual[k] for k in before},before)
            self.assertEqual(self.hashes(folder),before)
            item=inventory(target)[0];self.assertTrue(item['traffic']);self.assertIn('测试备注',item['note'])
            self.assertEqual(item['source'],'ImportedLogs');self.assertEqual(len(complete_laps(restored)['laps']),4)
            self.assertEqual(ReferenceLap.load(restored/item['fastest_file']).info['number'],4)
            self.assertEqual(packs.import_session(target,package['path'])['status'],'skipped')
            self.assertEqual(len(inventory(target)),1)
            self.assertEqual(packs.import_session(data,package['path'])['status'],'skipped')
            save_note(target,item['key'],'updated locally',False)
            again=packs.export_session(target,item['key'],Path(t)/'exports')
            other=Path(t)/'second';packs.import_session(other,again['path'])
            self.assertEqual(inventory(other)[0]['note'],'updated locally')
            self.assertFalse(inventory(other)[0]['traffic'])

    def test_compression_keeps_full_raw_stream_and_excludes_other_records_and_settings(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,folder=self.fixture(t)
            with (folder/'inputs.csv').open('ab') as f:
                for _ in range(64):f.write(b'0,unchanged full precision\r\n'*2048)
            (folder/'working.pending').write_text('unfinished')
            (data/'settings.json').write_text('{"fixed_hz":2400}')
            (data/'Logs'/'Other').mkdir();(data/'Logs'/'Other'/'private.txt').write_text('other session')
            package=packs.export_session(data,'Logs/Fixture',Path(t)/'out')
            self.assertLess(package['bytes'],package['source_bytes']/3)
            with zipfile.ZipFile(package['path']) as z:
                self.assertNotIn('session/working.pending',z.namelist())
                self.assertFalse(any('settings.json' in n or 'private.txt' in n for n in z.namelist()))
                self.assertEqual(z.read('session/inputs.csv'),(folder/'inputs.csv').read_bytes())

    def test_corrupt_payload_rolls_back_and_batch_continues(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,_=self.fixture(t);good=Path(packs.export_session(data,'Logs/Fixture',Path(t)/'out')['path'])
            bad=self.rewrite(good,Path(t)/'corrupt.zip',lambda name,b:b.replace(b'fixture',b'broken!') if name=='session/review.html' else b)
            target=Path(t)/'new'
            with self.assertRaisesRegex(ValueError,'校验失败'):packs.import_session(target,bad)
            self.assertEqual(list((target/'ImportedLogs').iterdir()),[])
            results=packs.transfer_batch([bad,good],lambda p:packs.import_session(target,p))
            self.assertEqual(len(results['errors']),1);self.assertEqual(len(results['items']),1)
            self.assertEqual(len(inventory(target)),1)
            def bad_metadata(name,b):
                if name=='manifest.json':
                    m=json.loads(b);m['original_key']=None;return json.dumps(m).encode()
                return b
            malformed=self.rewrite(good,Path(t)/'malformed.zip',bad_metadata)
            results=packs.transfer_batch([malformed,good],lambda p:packs.import_session(target,p))
            self.assertEqual(len(results['errors']),1);self.assertEqual(results['items'][0]['status'],'skipped')

    def test_hostile_paths_duplicates_symlinks_and_unknown_members_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,_=self.fixture(t);good=Path(packs.export_session(data,'Logs/Fixture',Path(t)/'out')['path'])
            attacks=['../outside.txt','session/../../outside.txt','/absolute.txt','session/C:evil','session/CON.txt',
                     'session/a\\b.txt','session/trailing.','session/Inputs.csv','unexpected.txt']
            symlink=zipfile.ZipInfo('session/link');symlink.create_system=3;symlink.external_attr=(0o120777<<16)
            for index,name in enumerate([*attacks,symlink,'session/inputs.csv']):
                with self.subTest(name=str(name)),warnings.catch_warnings():
                    warnings.simplefilter('ignore');bad=self.rewrite(good,Path(t)/f'bad-{index}.zip',extras=[(name,b'outside')])
                    with self.assertRaises((ValueError,zipfile.BadZipFile)):packs.import_session(Path(t)/'new',bad)
            self.assertFalse((Path(t)/'outside.txt').exists());self.assertEqual(inventory(Path(t)/'new'),[])

    def test_recording_invalid_manifest_and_limits_fail_without_published_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,folder=self.fixture(t);out=Path(t)/'out'
            with self.assertRaisesRegex(ValueError,'内部'):packs.export_session(data,'Logs/Fixture',folder/'exports')
            self.assertFalse((folder/'exports').exists())
            package=Path(packs.export_session(data,'Logs/Fixture',out)['path'])
            def change(name,b):
                if name=='manifest.json':
                    m=json.loads(b);m['archive_id']='0'*64;return json.dumps(m).encode()
                return b
            bad=self.rewrite(package,Path(t)/'manifest.zip',change)
            with self.assertRaisesRegex(ValueError,'清单校验'):packs.import_session(Path(t)/'new',bad)
            with patch.object(packs,'MAX_BYTES',100):
                with self.assertRaisesRegex(ValueError,'32 GiB'):packs.import_session(Path(t)/'new',package)
            meta=json.loads((folder/'session.json').read_text());meta['status']='recording'
            (folder/'session.json').write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError,'录制结束'):packs.export_session(data,'Logs/Fixture',out)
            self.assertFalse(list(out.glob('*.pending')))

    def test_changed_same_name_or_modified_import_never_overwrites_old_data(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,folder=self.fixture(t);out=Path(t)/'out';target=Path(t)/'new'
            first=Path(packs.export_session(data,'Logs/Fixture',out)['path'])
            old=Path(packs.import_session(target,first)['folder']);before=self.hashes(old)
            (folder/'review.html').write_text('changed report')
            second=Path(packs.export_session(data,'Logs/Fixture',out)['path'])
            new=Path(packs.import_session(target,second)['folder'])
            self.assertNotEqual(new,old);self.assertEqual(self.hashes(old),before)
            (old/'inputs.csv').write_text('modified locally')
            third=Path(packs.import_session(target,first)['folder'])
            self.assertNotEqual(third,old);self.assertEqual((old/'inputs.csv').read_text(),'modified locally')
            self.assertEqual(len(inventory(target)),3)

    def test_recording_package_bad_metadata_and_full_disk_are_atomic(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as t:
            data,_=self.fixture(t);good=Path(packs.export_session(data,'Logs/Fixture',Path(t)/'out')['path'])
            target=Path(t)/'new'
            with patch.object(packs.shutil,'disk_usage',return_value=type('Disk',(),{'free':0})()):
                with self.assertRaisesRegex(OSError,'磁盘空间'):packs.import_session(target,good)
            with zipfile.ZipFile(good) as z:
                metadata=json.loads(z.read('session/session.json'));manifest=json.loads(z.read('manifest.json'))
            for key,value in [('status','recording'),('started_utc',None)]:
                m=dict(metadata);m[key]=value;payload=json.dumps(m).encode()
                declared=json.loads(json.dumps(manifest));declared['files']['session.json']=dict(bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest())
                declared['archive_id']=packs._identity(declared['files'],declared['note'])
                def change(name,b):
                    return payload if name=='session/session.json' else json.dumps(declared).encode() if name=='manifest.json' else b
                bad=self.rewrite(good,Path(t)/(key+'.zip'),change)
                with self.assertRaises(ValueError):packs.import_session(target,bad)
                self.assertEqual(list((target/'ImportedLogs').iterdir()),[])

    def test_normal_hud_exit_waits_for_archive_worker_before_destroying_tk(self):
        hud=base_tests.app.App.__new__(base_tests.app.App)
        hud.closing=False;hud.render_stop=threading.Event();hud.draw_job=None;hud.root=Mock()
        reader=Mock();reader.is_alive.return_value=False
        hud.engine=SimpleNamespace(stop=threading.Event(),thread=reader,recorder=SimpleNamespace(pending_reports=[]))
        hud.render_waiter=Mock();worker=Mock();worker.is_alive.return_value=True;hud.archive_workers=[worker]
        hud.close();hud.root.destroy.assert_not_called();hud.root.after.assert_called_once_with(25,hud.close)
        self.assertTrue(hud.engine.stop.is_set())
        worker.is_alive.return_value=False;hud.close();hud.root.destroy.assert_called_once()
        hud.render_waiter.close.assert_called_once()


if __name__=='__main__':unittest.main()
