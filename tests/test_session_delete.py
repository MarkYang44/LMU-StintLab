"""Synthetic permanent deletion, cancellation and filesystem containment."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import session_delete
from library import inventory

class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'_local');self.root=Path(self.temp.name)/'data';self.root.mkdir()
        self.folder=self.root/'Logs'/'Synthetic Race';self.folder.mkdir(parents=True)
        (self.folder/'session.json').write_text(json.dumps(dict(status='complete',track='Test Circuit',vehicle='Synthetic',session=10,started_utc='2026-01-01T12:00:00Z')),encoding='utf-8')
        (self.folder/'inputs.csv').write_bytes(b't,throttle,brake\n0,1,0\n')
        (self.folder/'lap.lap.json').write_bytes(b'{"fixture":true}')
        self.key=inventory(self.root)[0]['key']
        (self.root/'library_notes.json').write_text(json.dumps({self.key:dict(text='delete this note'), 'Logs/Other':dict(text='keep')}),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def test_delete_removes_entire_selected_session_and_only_its_note(self):
        other=self.root/'Logs'/'Other';other.mkdir();(other/'keep.txt').write_bytes(b'keep')
        session_delete.remove(self.root,self.key)
        self.assertFalse(self.folder.exists());self.assertEqual((other/'keep.txt').read_bytes(),b'keep')
        self.assertEqual(json.loads((self.root/'library_notes.json').read_text()),{'Logs/Other':dict(text='keep')})
        self.assertFalse(inventory(self.root));self.assertFalse((self.root/'_Trash').exists())
    def test_recording_and_unsafe_keys_cannot_remove_sessions(self):
        for status in ('recording','write_error'):
            (self.folder/'session.json').write_text(json.dumps(dict(status=status)),encoding='utf-8')
            with self.assertRaises(ValueError):session_delete.remove(self.root,self.key)
            self.assertTrue(self.folder.exists())
        for key in ('../data','Logs/../Synthetic Race','Logs','_Trash/anything','C:/outside','Logs/Synthetic Race/child'):
            with self.assertRaises(ValueError):session_delete.remove(self.root,key)
        self.assertTrue((self.folder/'inputs.csv').exists())
    def test_linked_descendant_and_permission_error_do_not_claim_success(self):
        blocked=self.folder/'lap.lap.json';original=Path.is_symlink
        with patch.object(Path,'is_symlink',lambda path:path==blocked or original(path)):
            with self.assertRaises(ValueError):session_delete.remove(self.root,self.key)
        self.assertTrue(blocked.exists())
        with patch('session_delete.shutil.rmtree',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):session_delete.remove(self.root,self.key)
        self.assertTrue((self.folder/'inputs.csv').exists())

    @unittest.skipUnless(os.name=='nt','Native Windows menu')
    def test_review_confirmation_cancel_and_delete(self):
        from control_center import ControlCenter
        import control_delete
        def pump(center,condition):
            end=time.monotonic()+4
            while time.monotonic()<end:
                center.root.update();time.sleep(.005)
                if condition():return
            self.fail('Menu operation did not settle')
        with patch('control_center.ROOT',self.root):
            center=ControlCenter()
            try:
                center.show_page(1);pump(center,lambda:bool(center.tree.get_children()) and not center.tasks.busy)
                center.tree.selection_set(('0',))
                with patch('control_delete.messagebox.askyesno',return_value=False) as ask:
                    control_delete.remove(center);ask.assert_called_once();self.assertTrue(self.folder.exists())
                    self.assertIn('Test Circuit',ask.call_args.args[1])
                with patch('control_delete.messagebox.askyesno',return_value=True):
                    control_delete.remove(center)
                    pump(center,lambda:not self.folder.exists() and not center.tasks.busy)
                self.assertFalse((self.root/'_Trash').exists())
            finally:center.close()
