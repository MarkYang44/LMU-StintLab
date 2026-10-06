"""User-facing draft preservation, last-request wins and bounded page lifetime."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))

@unittest.skipUnless(os.name=='nt','Native Windows UI')
class NavigationTests(unittest.TestCase):
    def pump(self,center,condition=lambda:True):
        until=time.monotonic()+3
        while time.monotonic()<until:
            center.root.update();time.sleep(.005)
            if condition():return
        self.fail('Navigation did not settle')
    def test_revisit_retains_unsaved_draft_and_refreshes_unedited_saved_values(self):
        from control_center import ControlCenter
        from sampling import save_settings,DEFAULTS
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            data=Path(directory);center=ControlCenter()
            try:
                center.show_page(3);center.root.update_idletasks()
                draft=center.pages.active.forms['sampling'];draft['fixed_hz'].set('777')
                save_settings(data/'settings.json',{**DEFAULTS,'max_hz':800})
                center.show_page(0);center.show_page(3);center.root.update_idletasks()
                actual=center.pages.active.forms['sampling']
                self.assertEqual(actual['fixed_hz'].get(),'777');self.assertEqual(float(actual['max_hz'].get()),800)
                self.assertEqual(len(center.pages.pages),2)
                center.set_theme('light');center.root.update_idletasks()
                self.assertFalse([page for page in center.pages.pages.values() if not page.frame.winfo_exists()])
            finally:center.close()
    def test_last_requested_page_wins_and_partial_build_is_cancelled(self):
        from control_center import ControlCenter
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                for page in (3,5,1,6,0,4):center.request_page(page)
                self.assertEqual(center.shell.navigation.selected,4)
                self.pump(center,lambda:center.page==4 and center.pages.pending is None)
                center.request_page(3);self.pump(center,lambda:center.page==3)
                center.request_page(6);self.pump(center,lambda:center.page==6 and center.guide_page.card_job is None and center.guide_page.card_count==3)
                old=center.guide_page
                center.request_page(0);self.pump(center,lambda:center.page==0 and center.pages.active.complete)
                self.assertTrue(old.closed);self.assertIsNone(old.card_job)
                self.assertLessEqual(len(center.pages.pages),2);self.assertFalse(errors,errors)
            finally:center.close()
    def test_image_decode_never_calls_tk_from_worker_and_disposed_result_is_ignored(self):
        from control_center import ControlCenter
        from guide_cards import Picture
        import threading
        def walk(widget):
            yield widget
            for child in widget.winfo_children():yield from walk(child)
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.show_page(6);center.root.update_idletasks()
                pictures=[widget for widget in walk(center.content) if isinstance(widget,Picture)]
                center.scroll.yview_moveto(.25);center.root.update_idletasks()
                jobs=[]
                with patch.object(center,'run_background',side_effect=lambda work,done:jobs.append((work,done))):
                    for picture in pictures:picture.render()
                self.assertTrue(jobs)
                output=[]
                worker=threading.Thread(target=lambda:output.extend(work() for work,_ in jobs));worker.start();worker.join(3)
                self.assertFalse(worker.is_alive());self.assertEqual(len(output),len(jobs))
                center.show_page(0)
                for (_,done),image in zip(jobs,output):done(image,None)
                self.assertTrue(all(not picture.photo for picture in pictures));self.assertFalse(errors)
            finally:center.close()

    def test_old_document_and_selection_disappear_before_deferred_page_build(self):
        from control_center import ControlCenter
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                center.show_page(1);center.root.update()
                old=center.content;self.assertTrue(old.winfo_ismapped())
                generation=center.scan_generation
                center.request_page(3);center.root.update_idletasks()
                self.assertFalse(old.winfo_ismapped())
                self.assertTrue(center.shell.covering);self.assertEqual(center.scroll.itemcget(center.content_item,'state'),'hidden')
                self.assertIsNotNone(center.pages.pending);self.assertIsNone(center.tree)
                self.assertGreater(center.scan_generation,generation)
                self.assertEqual(center.shell.navigation.position,3)
                self.assertEqual(center.shell.navigation.selected,3)
                center.request_page(6);center.request_page(0)
                self.pump(center,lambda:center.page==0 and center.pages.pending is None)
                self.assertFalse(center.shell.covering);self.assertEqual(center.scroll.itemcget(center.content_item,'state'),'normal')
                self.assertTrue(center.pages.active.frame.winfo_ismapped());self.assertFalse(errors,errors)
            finally:center.close()

    def test_move_repaints_only_menu_once_then_releases_callback_on_close(self):
        from control_center import ControlCenter
        from types import SimpleNamespace
        import tkinter as tk
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();presentation=center.presentation
            try:
                center.root.update();presentation.cancel()
                presentation.changed(SimpleNamespace(widget=center.content,type=tk.EventType.Configure))
                self.assertIsNone(presentation.job)
                with patch.object(presentation.user,'RedrawWindow',wraps=presentation.user.RedrawWindow) as redraw:
                    for value in range(4):center.root.geometry(f'+{140+value*4}+{110+value*3}');center.root.update_idletasks()
                    self.pump(center,lambda:presentation.job is None and redraw.call_count>0)
                    self.assertEqual(redraw.call_count,1)
                    self.assertEqual(redraw.call_args.args[0],center.root.winfo_id())
                    self.assertEqual(redraw.call_args.args[3],0x185)
                    for _ in range(12):center.root.update();time.sleep(.005)
                    self.assertEqual(redraw.call_count,1);self.assertIsNone(presentation.job)
                presentation.schedule();pending=presentation.job
            finally:center.close()
            self.assertIsNone(presentation.job);self.assertIsNone(presentation.root)
            self.assertIsNone(presentation.user)
