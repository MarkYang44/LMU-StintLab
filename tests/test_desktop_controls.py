"""Behavior and lifecycle coverage for native form controls and Windows links."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))


@unittest.skipUnless(os.name=='nt','Windows native Tk and Shell links')
class DesktopTests(unittest.TestCase):
    def test_selector_keyboard_scroll_editing_cancel_and_lifecycle(self):
        import tkinter as tk
        from types import SimpleNamespace
        from control_fields import Select,Field
        from control_theme import set_mode
        for theme in ('dark','light'):
            set_mode(theme);root=tk.Tk();root.geometry('700x500');errors=[]
            root.report_callback_exception=lambda *args:errors.append(args)
            variable=tk.StringVar(root,value='item 00');selected=[]
            box=Select(root,textvariable=variable,values=[f'item {i:02d}' for i in range(25)])
            box.pack();box.bind('<<ComboboxSelected>>',lambda _:selected.append(variable.get()))
            field=Field(root,textvariable=tk.StringVar(root,value='123'));field.pack()
            editable=Select(root,values=['BMW','Ferrari'],state='normal');editable.pack()
            def pump(duration=.25):
                end=time.monotonic()+duration
                while time.monotonic()<end:root.update();time.sleep(.005)
            def key(name,char='',state=0):return SimpleNamespace(keysym=name,char=char,state=state)
            try:
                pump();box.open();pump()
                self.assertIsNotNone(box.popup);self.assertIs(box.grab_current(),box.popup)
                box.key(key('End'));self.assertEqual(box.active,24);self.assertEqual(box.offset,18)
                box.key(key('Return'));pump();self.assertEqual(variable.get(),'item 24');self.assertEqual(selected,['item 24'])
                box.open();pump();box.key(key('Home'));box.key(key('Escape'));pump()
                self.assertEqual(variable.get(),'item 24');self.assertIsNone(box.popup)
                box.configure(values=['Alpha','Bravo','Charlie']);box.open();pump()
                box.key(key('b','b'));self.assertEqual(box.active,1);box.key(key('Return'));pump()
                self.assertEqual(variable.get(),'Bravo');self.assertEqual(selected[-1],'Bravo')
                editable.edit.insert(0,'Custom model');self.assertEqual(editable.get(),'Custom model')
                box.configure(state='disabled');box.open();self.assertIsNone(box.popup)
                box.configure(state='readonly');box.open();pump()
                popup=box.popup;panel_motion=box.popup_motion;trace=box.trace
                box.destroy();pump()
                self.assertFalse(popup.winfo_exists());self.assertIsNone(root.grab_current())
                self.assertFalse(variable.trace_info());self.assertFalse(panel_motion.jobs)
                self.assertFalse(box.motion.jobs);self.assertFalse(errors)
                self.assertFalse(field.motion.jobs)
            finally:root.destroy();set_mode('dark')

    def test_local_grab_restored_and_resize_closes_flyout(self):
        import tkinter as tk
        from control_fields import Select
        root=tk.Tk();dialog=tk.Toplevel(root);box=Select(dialog,values=['A','B']);box.pack()
        try:
            root.update();dialog.grab_set();box.open();root.update()
            box.close();self.assertIs(root.grab_current(),dialog)
            box.open();root.update();dialog.geometry('450x250');root.update()
            self.assertIsNone(box.popup);self.assertIs(root.grab_current(),dialog)
            self.assertIsNone(box.owner_binding)
        finally:root.destroy()

    def test_shortcut_creation_repair_removal_and_foreign_link_protection(self):
        import windows_integration as integration
        (ROOT/'_local').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            directory=Path(folder)/"测试 folder '$ literal";directory.mkdir()
            exe=directory/'LMU-StintLab.exe';exe.write_bytes(b'fixture-not-executed')
            link=directory/'LMU StintLab.lnk'
            with patch.object(integration,'executable',return_value=exe),patch.object(integration,'shortcut_path',return_value=link):
                first=integration.register();self.assertTrue(link.is_file())
                self.assertEqual(Path(first['target']),exe);self.assertEqual(Path(first['path']),link)
                integration.register();self.assertTrue(link.is_file())
                integration.register(True);self.assertFalse(link.exists())
                with patch.object(integration,'DESCRIPTION','Another application'):integration.register()
                original=link.read_bytes()
                with self.assertRaises(OSError):integration.register()
                with self.assertRaises(OSError):integration.register(True)
                self.assertEqual(link.read_bytes(),original)
                self.assertFalse(list(directory.glob('StintLab-*.lnk')))
