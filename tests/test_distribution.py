"""Privacy boundaries, portable assets and independent SDK distribution."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from tools.audit_publication import audit,allowed,git_command
from tools.install_dependencies import choose_wheel
from tools.migrate_inputscope import migrate,digest,rewrite_local_paths
from tools.build import bundle_audit,ASSET_NAMES
import paths

class DistributionTests(unittest.TestCase):
    def test_private_files_are_rejected_even_inside_source(self):
        for name in ('data/a.json','src/Logs/session.json','src/sample.lap.json','docs/race.csv','src/local_settings.json','src/vendor/secret.py','_verification/result.json','src/record.duckdb'):
            with self.subTest(name=name):self.assertFalse(allowed(name))

    def test_staged_personal_path_and_secret_are_detected(self):
        blobs={'src/ordinary.py':('path = '+repr('D:'+chr(92)+'Users'+chr(92)+'private_user'+chr(92)+'lap')).encode(),
               'README.md':('gh'+'p_'+'a'*36).encode()}
        result=audit(list(blobs),blobs.__getitem__)
        self.assertFalse(result['ok']);self.assertEqual(len(result['failures']),2)

    def test_public_text_passes_and_binary_fails(self):
        self.assertTrue(audit(['README.md'],lambda _:b'Public documentation')['ok'])
        self.assertFalse(audit(['src/module.py'],lambda _:b'\xff')['ok'])

    def test_git_ignores_nested_and_root_private_data(self):
        names=['data/Logs/input.csv','src/Logs/session.json','local_settings.json','dist/test.zip','_local/wheels/test.whl','src/a.lap.json','src/tracks/sources/map.pdf',
               'src/race_log.json','src/race_summary.json','src/race_images.json','src/car_calibration.json']
        result=subprocess.run(git_command('check-ignore','--stdin','-z'),cwd=ROOT,input=('\0'.join(names)+'\0').encode(),capture_output=True)
        self.assertEqual(set(result.stdout.decode().strip('\0').split('\0')),set(names))

    def test_cross_owner_checkout_is_audited_without_global_config_changes(self):
        env=dict(os.environ,GIT_TEST_ASSUME_DIFFERENT_OWNER='1',GIT_CONFIG_COUNT='1',
                 GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0='')
        before=subprocess.run(['git','config','--global','--get-all','safe.directory'],capture_output=True)
        blocked=subprocess.run(['git','-c','safe.directory=','rev-parse','--show-toplevel'],cwd=ROOT,env=env,capture_output=True)
        self.assertNotEqual(blocked.returncode,0)
        self.assertIn(b'dubious ownership',blocked.stderr)
        result=subprocess.run([sys.executable,str(ROOT/'tools'/'audit_publication.py'),'--json'],cwd=ROOT,env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        after=subprocess.run(['git','config','--global','--get-all','safe.directory'],capture_output=True)
        self.assertEqual((before.returncode,before.stdout),(after.returncode,after.stdout))

    def test_git_command_trusts_only_exact_project_directory(self):
        command=git_command('show',':README.md')
        self.assertEqual(command,['git','-c','safe.directory=','-c','safe.directory='+ROOT.as_posix(),'show',':README.md'])
        self.assertNotIn('safe.directory=*',command)

    def test_default_data_is_separate_from_assets(self):
        with patch.dict(os.environ,{},clear=True),patch.object(paths,'local_settings',return_value={}):
            self.assertEqual(paths.data_directory(),paths.APP_ROOT/'data')
            self.assertNotEqual(paths.data_directory(),paths.ASSETS)

    def test_environment_override_beats_machine_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'LMU_STINTRIX_DATA_DIR':directory}),patch.object(paths,'local_settings',return_value={'data_directory':'another'}):
                self.assertEqual(paths.data_directory(),Path(directory).resolve())

    def test_frozen_assets_use_internal_but_data_uses_exe_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);module=root/'_internal'
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(module),create=True),patch.object(sys,'executable',str(root/'LMU-Stintrix.exe')):
                spec=importlib.util.spec_from_file_location('frozen_paths',ROOT/'src'/'paths.py')
                loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
            self.assertEqual(loaded.APP_ROOT,root);self.assertEqual(loaded.ASSETS,module/'src')

    def test_sdk_layout_matches_lmu_and_license_is_present(self):
        from pyLMUSharedMemory.lmu_data import LMUObjectOut
        self.assertEqual(ctypes.sizeof(LMUObjectOut),324820)
        self.assertEqual(LMUObjectOut.telemetry.offset,128464)
        self.assertIn('MIT License',(ROOT/'src'/'pyLMUSharedMemory'/'License.txt').read_text())

    def test_public_assets_have_no_unlicensed_base_maps(self):
        self.assertEqual(json.loads((paths.ASSETS/'tracks'/'catalog.json').read_text(encoding='utf-8')),[])
        self.assertTrue(all((paths.ASSETS/name).is_file() for name in ASSET_NAMES))
        self.assertFalse((paths.ASSETS/'tracks'/'sources').exists())

    def test_private_maps_override_public_defaults_without_changing_public_assets(self):
        from laps import track_script
        public_before=(paths.ASSETS/'tracks'/'catalog.json').read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);catalog=root/'assets'/'tracks'/'catalog.json';catalog.parent.mkdir(parents=True)
            with patch.object(paths,'data_directory',return_value=root):
                self.assertEqual(paths.track_catalog_path(),paths.ASSETS/'tracks'/'catalog.json')
                catalog.write_text('[{"id":"fixture-private-map","points":[]}]',encoding='utf-8')
                self.assertEqual(paths.track_catalog_path(),catalog)
                self.assertIn('fixture-private-map',track_script(paths.ASSETS))
        self.assertEqual(public_before,(paths.ASSETS/'tracks'/'catalog.json').read_bytes())

    def test_migration_preserves_records_and_preferences_and_relinks_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'old';target=root/'new'/'data';backup=root/'backup'
            (source/'src'/'tracks').mkdir(parents=True);(source/'src'/'inputscope.py').write_text('')
            session=source/'Logs'/'fixture';session.mkdir(parents=True)
            (session/'inputs.csv').write_bytes(b'time_s,throttle\n0,1\n')
            (session/'session.json').write_text('{"driver":"Synthetic fixture"}')
            (session/'Fastest.lap.json').write_text('{}')
            (source/'settings.json').write_text('{"fixed_hz":2400,"input_channel":"raw","draw_mode":"sync"}')
            (source/'reference_settings.json').write_text(json.dumps({'path':str(session/'Fastest.lap.json'),'locked':True}))
            (source/'FastestLapCompare.html').write_text('<html>legacy fixture</html>')
            (source/'src'/'tracks'/'catalog.json').write_text('[{"id":"synthetic-private-map"}]')
            before={p.relative_to(source):digest(p) for p in source.rglob('*') if p.is_file()}
            result=migrate(source,target,backup)
            self.assertEqual(result['status'],'complete')
            for name in ('inputs.csv','session.json','Fastest.lap.json'):
                self.assertEqual(digest(session/name),digest(target/'Logs'/'fixture'/name))
            self.assertEqual(json.loads((target/'settings.json').read_text())['fixed_hz'],2400)
            self.assertEqual(json.loads((target/'reference_settings.json').read_text())['path'],str((target/'Logs'/'fixture'/'Fastest.lap.json').resolve()))
            self.assertEqual((target/'FastestLapCompare.html').read_text(),'<html>legacy fixture</html>')
            self.assertTrue((target/'assets'/'tracks'/'catalog.json').exists())
            self.assertEqual(before,{p.relative_to(source):digest(p) for p in source.rglob('*') if p.is_file()})

    def test_reference_rewrite_resolves_windows_short_or_linked_aliases(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory).resolve();source=root/'Long Source';target=root/'new'/'data'
            reference=source/'Logs'/'fixture'/'Fastest.lap.json';reference.parent.mkdir(parents=True);reference.write_text('{}')
            alias=root/'SHORT~1'/'Logs'/'fixture'/'Fastest.lap.json'
            external=root/'external.lap.json';external.write_text('{}')
            original_resolve=Path.resolve
            def resolve(path,*args,**kwargs):
                return reference if path==alias else original_resolve(path,*args,**kwargs)
            value=dict(path=str(alias),nested=[str(external),'fastest','relative/file.json'])
            with patch.object(Path,'resolve',autospec=True,side_effect=resolve):
                updated=rewrite_local_paths(value,source,target)
            self.assertEqual(updated['path'],str(target/'Logs'/'fixture'/'Fastest.lap.json'))
            self.assertEqual(updated['nested'],value['nested'])
            self.assertEqual(value['path'],str(alias))

    @unittest.skipUnless(sys.platform=='win32','Windows path alias regression')
    def test_migration_with_real_windows_short_source_and_destination_paths(self):
        with tempfile.TemporaryDirectory(prefix='Stintrix_LongPath_Test_') as directory:
            root=Path(directory).resolve();source=root/'Long Source Folder';target=root/'Long Destination Folder'
            (source/'src').mkdir(parents=True);(source/'src'/'inputscope.py').write_text('')
            folder=source/'Logs'/'fixture';folder.mkdir(parents=True)
            (folder/'inputs.csv').write_text('time_s,throttle\n0,1\n');(folder/'Fastest.lap.json').write_text('{}')
            target.mkdir()
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetShortPathNameW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_ulong]
            kernel.GetShortPathNameW.restype=ctypes.c_ulong
            def short(path):
                buffer=ctypes.create_unicode_buffer(32768)
                count=kernel.GetShortPathNameW(str(path),buffer,len(buffer))
                if not 0<count<len(buffer):self.skipTest('Filesystem does not provide short path aliases')
                return Path(buffer.value)
            old_alias,new_alias=short(source),short(target)
            if str(old_alias)==str(source):self.skipTest('8.3 name creation is disabled on this volume')
            (source/'reference_settings.json').write_text(json.dumps({'path':str(old_alias/'Logs'/'fixture'/'Fastest.lap.json'),'locked':True}))
            before=(source/'reference_settings.json').read_bytes()
            migrate(old_alias,new_alias,root/'backup')
            value=json.loads((target/'reference_settings.json').read_text())
            self.assertEqual(value['path'],str((target/'Logs'/'fixture'/'Fastest.lap.json').resolve()))
            self.assertEqual(Path(value['path']).read_bytes(),b'{}')
            self.assertEqual((source/'reference_settings.json').read_bytes(),before)

    def test_migration_collision_stops_before_copying_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'old';target=root/'new';backup=root/'backup'
            (source/'src').mkdir(parents=True);(source/'src'/'inputscope.py').write_text('')
            for folder,payload in ((source,b'legacy'),(target,b'existing')):
                session=folder/'Logs'/'fixture';session.mkdir(parents=True);(session/'inputs.csv').write_bytes(payload)
            (source/'settings.json').write_text('{"fixed_hz":2400}')
            with self.assertRaises(ValueError):migrate(source,target,backup)
            self.assertEqual((target/'Logs'/'fixture'/'inputs.csv').read_bytes(),b'existing')
            self.assertFalse((target/'settings.json').exists());self.assertFalse(backup.exists())

    def test_wheel_selection_rejects_other_platforms_and_ambiguity(self):
        files=[{'filename':'example-1-cp313-cp313-win_amd64.whl'}, {'filename':'example-1-cp313-cp313-manylinux_x86_64.whl'}]
        self.assertEqual(choose_wheel(files),files[0])
        with self.assertRaises(ValueError):choose_wheel(files[1:])
        with self.assertRaises(ValueError):choose_wheel([files[0],files[0]])

    def test_bundle_audit_rejects_accidentally_copied_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'_internal').mkdir();(root/'_internal'/'app.dll').write_bytes(b'dll')
            self.assertTrue(bundle_audit(root))
            (root/'session.json').write_text('{}')
            with self.assertRaises(ValueError):bundle_audit(root)

    def test_portable_bundle_rejects_developer_files_but_keeps_user_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'docs').mkdir()
            (root/'Start.cmd').write_text('start')
            (root/'docs'/'USAGE.md').write_text('usage')
            self.assertTrue(bundle_audit(root))
            for name in ('Check.cmd','Build.cmd','Publish.cmd','tests/test_core.py',
                         'tools/doctor.py','docs/RELEASE.md','docs/PERFORMANCE.md'):
                with self.subTest(name=name):
                    file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('developer')
                    try:
                        with self.assertRaisesRegex(ValueError,'Development'):bundle_audit(root)
                    finally:file.unlink()

    def test_publication_keeps_development_files_in_their_own_directories(self):
        for name in ('tests/test_core.py','tests/portable_smoke.py','tools/Build.cmd','tools/doctor.py'):
            with self.subTest(name=name):self.assertTrue(allowed(name))
        for name in ('tests.py','tests_distribution.py','Build.cmd','Check.cmd','Publish.cmd','build.py'):
            with self.subTest(name=name):self.assertFalse(allowed(name))

if __name__=='__main__':unittest.main()
