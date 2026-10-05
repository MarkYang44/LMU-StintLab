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
                self.assertIsNotNone(box.popup);self.assertIsNone(box.grab_current())
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

    def test_existing_modal_grab_untouched_and_resize_closes_flyout(self):
        import tkinter as tk
        from control_fields import Select
        from control_widgets import Pill
        root=tk.Tk();dialog=tk.Toplevel(root);box=Select(dialog,values=['A','B']);box.pack()
        try:
            root.update();dialog.grab_set();box.open();root.update()
            self.assertIs(root.grab_current(),dialog)
            box.close();self.assertIs(root.grab_current(),dialog)
            box.open();root.update();dialog.geometry('450x250');root.update()
            self.assertIsNone(box.popup);self.assertIs(root.grab_current(),dialog)
            self.assertIsNone(box.owner_binding)
        finally:root.destroy()

    def test_outside_mouse_click_remains_actionable_and_one_popup_at_a_time(self):
        import tkinter as tk
        from control_fields import Select
        from control_widgets import Pill
        root=tk.Tk();root.geometry('650x450');clicked=[]
        first=Select(root,values=['A','B']);first.pack()
        second=Select(root,values=['C','D']);second.pack()
        button=Pill(root,'Navigate',lambda:clicked.append('navigate'));button.pack()
        errors=[];root.report_callback_exception=lambda *args:errors.append(args)
        try:
            root.update();first.open();root.update()
            self.assertIsNone(root.grab_current())
            button.event_generate('<ButtonPress-1>',x=8,y=8);root.update()
            button.event_generate('<ButtonRelease-1>',x=8,y=8);root.update()
            self.assertEqual(clicked,['navigate']);self.assertIsNone(first.popup)
            first.open();root.update();second.open();root.update()
            self.assertIsNone(first.popup);self.assertIsNotNone(second.popup)
            # Use actual bound mouse events, rather than calling choose directly.
            panel=second.panel;panel.event_generate('<ButtonPress-1>',x=20,y=second.row_h+10);root.update()
            self.assertEqual(second.get(),'D');self.assertIsNone(second.popup)
            self.assertIsNone(root._stintlab_active_select)
            for _ in range(15):first.open();root.update();first.close();root.update()
            self.assertIsNone(first.owner_click);self.assertIsNone(first.owner_focus)
            self.assertFalse(errors)
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

    def test_catalog_verification_and_scoped_current_user_repair(self):
        import windows_integration as integration
        import paths,json
        from tools.audit_publication import allowed
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as folder:
            directory=Path(folder);exe=directory/'LMU-StintLab.exe';exe.write_bytes(b'fixture')
            link=directory/'LMU StintLab.lnk';private=directory/'private';private.mkdir()
            with patch.object(integration,'executable',return_value=exe),patch.object(integration,'shortcut_path',return_value=link),patch.object(paths,'data_directory',return_value=private),patch.object(sys,'frozen',True,create=True),patch.object(integration.os,'getlogin',return_value='fixture-user'):
                self.assertFalse(integration.needs_repair())
                with patch.object(integration,'catalog_entry',return_value=None):result=integration.register(verify=True)
                self.assertFalse(result['recognized']);self.assertTrue(integration.needs_repair())
                with patch.object(integration,'catalog_entry',return_value={'Name':'LMU StintLab','AppID':integration.APP_ID}):
                    result=integration.register(verify=True)
                self.assertTrue(result['recognized']);self.assertFalse(integration.needs_repair())
                with patch.object(integration.os,'getlogin',return_value='other-user'):self.assertTrue(integration.needs_repair())
                with patch.object(integration,'executable',return_value=directory/'temporary-bundle.exe'):self.assertFalse(integration.needs_repair())
                with patch.object(integration,'DESCRIPTION','Foreign app'):self.assertFalse(integration.needs_repair())
                marker=private/'desktop_registration.json';marker.write_text('{broken')
                self.assertTrue(integration.needs_repair())
                with patch.object(sys,'frozen',False):self.assertFalse(integration.needs_repair())
                integration.register(True,verify=True);self.assertFalse(integration.needs_repair())
                self.assertFalse(json.loads(marker.read_text())['recognized'])
            self.assertFalse(allowed('src/desktop_registration.json'))

    def test_registration_status_does_not_claim_unrecognized_application(self):
        from control_center import ControlCenter
        from types import SimpleNamespace
        class Status:
            def set(self,value):self.value=value
        status=Status();center=SimpleNamespace(status=status)
        ControlCenter.registration_result(center,dict(removed=False,recognized=False))
        self.assertIn('尚未列出',status.value)
        ControlCenter.registration_result(center,dict(removed=False,recognized=True))
        self.assertIn('已识别',status.value)
        ControlCenter.registration_result(center,dict(removed=True,recognized=False))
        self.assertIn('已移除',status.value)
