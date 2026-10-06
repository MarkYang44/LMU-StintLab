"""DPI, event-loop lifecycle and the real Windows icon resources."""
import os
from pathlib import Path
import struct
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))


@unittest.skipUnless(os.name=='nt','Windows desktop')
class DesktopTests(unittest.TestCase):
    def setUp(self):(ROOT/'_local').mkdir(exist_ok=True)
    def test_brand_and_navigation_fit_from_100_to_200_percent_dpi(self):
        import tkinter as tk
        from control_center import ControlCenter
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            for dpi in (96,120,144,192):
                root=tk.Tk();root.tk.call('tk','scaling',dpi/72)
                with patch('control_center.ROOT',Path(directory)),patch('hud.Engine') as engine:
                    center=ControlCenter(root)
                    try:
                        root.update();brand=center.shell.brand;nav=center.shell.navigation
                        for item in brand.find_all():
                            if brand.type(item)=='text':
                                box=brand.bbox(item);self.assertGreaterEqual(box[0],-3);self.assertLessEqual(box[2],brand.winfo_width())
                        for item in nav.find_all():
                            if nav.type(item)=='text':self.assertLessEqual(nav.bbox(item)[2],nav.winfo_width())
                        self.assertEqual(root.attributes('-alpha'),1.0);engine.assert_not_called()
                    finally:center.close()
    def test_rapid_navigation_and_external_switch_updates_settle_without_idle_frames(self):
        import tkinter as tk
        from control_center import ControlCenter
        from control_widgets import Switch
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
            try:
                for page in (1,3,2,4,0):center.show_page(page);center.root.update()
                variable=tk.BooleanVar(center.root,value=False)
                switch=Switch(center.content,'fixture',variable,lambda:None);switch.pack(fill='x')
                variable.set(True);center.root.update();variable.set(False);variable.set(True)
                deadline=time.monotonic()+.45
                while time.monotonic()<deadline:center.root.update();time.sleep(.01)
                self.assertEqual(switch.value,1);self.assertFalse(switch.motion.jobs)
                self.assertEqual(center.shell.navigation.position,0);self.assertFalse(center.shell.navigation.motion.jobs)
                self.assertFalse(center.shell.motion.jobs);self.assertEqual(center.scroll.coords(center.content_item),[0,0])
                self.assertEqual(tuple(float(v) for v in center.scroll.cget('scrollregion').split())[:2],(0,0))
                variable.set(False);switch.destroy();center.root.update();self.assertFalse(switch.motion.jobs)
                self.assertFalse(errors)
            finally:center.close()
    def test_generated_icon_contains_all_real_png_sizes(self):
        from tools.build_brand import render,SIZES
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            folder=render(directory);blob=(folder/'stintrix.ico').read_bytes()
            self.assertEqual(struct.unpack_from('<HHH',blob),(0,1,len(SIZES)))
            for i,size in enumerate(SIZES):
                w,h,_,_,planes,bits,length,offset=struct.unpack_from('<BBBBHHII',blob,6+i*16)
                png=blob[offset:offset+length];self.assertEqual(png,(folder/f'stintrix-{size}.png').read_bytes())
                self.assertEqual((w or 256,h or 256,bits),(size,size,32));self.assertIn(planes,(0,1))
                self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n');self.assertEqual(struct.unpack_from('>II',png,16),(size,size))
                self.assertGreater(length,200)
    def test_only_exact_reviewed_assets_are_allowed_for_publication(self):
        from tools.audit_publication import allowed,audit,PUBLIC_ASSETS
        for name in PUBLIC_ASSETS:
            self.assertTrue(allowed(name));self.assertTrue(audit([name],lambda n:(ROOT/n).read_bytes())['ok'])
            self.assertFalse(audit([name],lambda _:b'personal image substituted')['ok'])
        for name in ('src/branding/personal.svg','src/branding/private.png','data/stintrix.svg','src/branding/stintrix.svg','src/interface_settings.json'):
            self.assertFalse(allowed(name))

    def pump(self,root,seconds=.6):
        until=time.monotonic()+seconds
        while time.monotonic()<until:root.update();time.sleep(.005)

    def list_fixture(self,root):
        from control_list import SessionList
        table=SessionList(root,('date','type','track','car','lap'),height=9,selectmode='extended');table.pack(fill='both',expand=True)
        table.replace([(str(i),(str(i),'Race','Spa','BMW','1:23.456')) for i in range(10000)])
        root.update();return table

    def test_wheel_accumulates_pixel_input_and_stops_with_no_idle_job(self):
        import tkinter as tk
        from types import SimpleNamespace
        root=tk.Tk();root.geometry('800x500');table=self.list_fixture(root)
        try:
            for _ in range(5):table.wheel(SimpleNamespace(delta=-120,state=0))
            self.assertAlmostEqual(table.scroller.target,table.rowheight*12)
            root.update();self.assertLess(table.offset,table.scroller.target)
            self.pump(root);self.assertAlmostEqual(table.offset,table.rowheight*12,delta=.3)
            self.assertIsNone(table.scroller.job);self.assertLess(len(table.viewport.find_all()),130)
            table.wheel(SimpleNamespace(delta=12000,state=0));self.pump(root)
            self.assertEqual(table.offset,0);self.assertIsNone(table.scroller.job)
            table.wheel(SimpleNamespace(delta=-120,state=0));table.destroy();root.update();self.assertIsNone(table.scroller.job)
        finally:root.destroy()

    def test_selection_is_immediate_multiselect_keyboard_and_filter_keep_ids(self):
        import tkinter as tk
        from types import SimpleNamespace
        root=tk.Tk();root.geometry('800x500');table=self.list_fixture(root)
        try:
            table.choose('3');table.choose('7',control=True)
            self.assertEqual(table.selection(),('3','7'));self.assertTrue(table.motion.jobs)
            table.choose('10',shift=True);self.assertEqual(table.selection(),('7','8','9','10'))
            table.cursor='10';table.key(SimpleNamespace(state=1),'Down');self.assertEqual(table.selection(),('7','8','9','10','11'))
            selected=table.selection();table.replace([(str(i),('','','','','')) for i in (7,11,99)],selected)
            root.update();self.assertEqual(table.selection(),('7','11'));self.assertEqual(table.indices,{'7':0,'11':1,'99':2})
            table.scroller.move(100000);self.assertEqual(table.offset,0)
            self.pump(root);self.assertFalse(table.motion.jobs)
        finally:root.destroy()

    def test_archive_checkboxes_select_without_modifiers_and_toggle_filtered_all(self):
        import tkinter as tk
        from types import SimpleNamespace
        from control_list import SessionList
        root=tk.Tk();root.geometry('800x500')
        table=SessionList(root,('date','type','track','car','lap'),selectmode='extended',checkboxes=True);table.pack(fill='both',expand=True)
        table.replace([(str(i),('','','','','')) for i in range(8)]);root.update()
        try:
            for i in (1,4):table.click(SimpleNamespace(x=table.gutter/2,y=(i+.5)*table.rowheight,state=0))
            self.assertEqual(table.selection(),('1','4'))
            table.toggle_focused(None);self.assertEqual(table.selection(),('1',))
            table.replace([(str(i),('','','','','')) for i in (1,4,7)],table.selection());root.update()
            table.header_click(SimpleNamespace(x=1));self.assertEqual(table.selection(),('1','4','7'))
            table.header_click(SimpleNamespace(x=1));self.assertEqual(table.selection(),())
            self.assertEqual(table.totalwidth,sum(table.actual.values())+table.gutter)
        finally:root.destroy()

    def test_control_center_exports_every_checked_session_and_reports_partial_failure(self):
        from control_center import ControlCenter
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter()
            try:
                center.show_page(4);center.root.update()
                self.assertTrue(center.tree.multiple);self.assertTrue(center.tree.checkboxes)
                center.items=[dict(key='Logs/'+str(i),date='',session_type='Race',track='Spa',vehicle='BMW',status='complete',time_s=None) for i in range(3)]
                center.populate();center.tree.selection_set(('0','1','2'));center.root.update()
                self.assertIn('已选 3 场',center.selected_count.get())
                captured=[]
                def export(root,key,target):
                    if key=='Logs/1':raise ValueError('fixture corrupt record')
                    return dict(path=str(target/(key[-1]+'.zip')))
                with patch('session_archive.export_session',side_effect=export) as worker:
                    with patch.object(center,'run_background',side_effect=lambda work,done:captured.append((work,done))),patch('control_center.filedialog.askdirectory',return_value=directory):
                        center.export_package();center.export_package()
                    self.assertEqual(len(captured),1)
                    result=captured[0][0]()
                    self.assertEqual([call.args[1] for call in worker.call_args_list],['Logs/0','Logs/1','Logs/2'])
                self.assertEqual((len(result['items']),len(result['errors'])),(2,1))
                with patch('control_center.os.startfile') as opened,patch('control_center.messagebox.showwarning') as warning:
                    captured[0][1](result,None);opened.assert_called_once_with(directory);warning.assert_called_once()
                self.assertFalse(center.exporting);self.assertIn('已导出 2 场',center.status.get())
            finally:center.close()

    def test_themes_persist_and_preserve_running_recorder_pure_hud_and_page(self):
        import control_center,tkinter as tk
        import control_theme
        from app_config import COLORS
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            folder=Path(directory)
            with patch('control_center.ROOT',folder),patch('hud.ROOT',folder),patch('engine.ROOT',folder),patch('recorder.make_report'):
                center=control_center.ControlCenter();errors=[];center.root.report_callback_exception=lambda *args:errors.append(args)
                try:
                    center.start(True);hud=center.hud;engine=hud.engine;recorder=engine.recorder
                    center.set_hud('mode','controls');self.pump(center.root,.2);count=recorder.samples
                    center.set_theme('light');self.pump(center.root,.3)
                    self.assertIs(center.hud,hud);self.assertIs(hud.engine,engine);self.assertIs(engine.recorder,recorder)
                    self.assertGreater(recorder.samples,count);self.assertEqual(hud.canvas.cget('bg'),'#000000')
                    center.show_page(1);center.root.update();center.search.set('Spa');center.set_theme('dark')
                    self.assertEqual(center.page,1);self.assertEqual(center.search.get(),'Spa')
                    center.set_theme('light');self.assertEqual(control_theme.T.mode,'light');self.assertEqual(COLORS,('#34e59a','#ff596b','#52b5ff'))
                    self.assertEqual(center.root.cget('bg'),control_theme.PALETTES['light']['BG']);self.assertFalse(errors)
                finally:
                    center.close()
                    try:
                        while center.root.winfo_exists():center.root.update();time.sleep(.01)
                    except tk.TclError:pass
            with patch('control_center.ROOT',folder),patch('hud.Engine') as engine:
                center=control_center.ControlCenter()
                try:self.assertEqual(control_theme.T.mode,'light');engine.assert_not_called()
                finally:center.close()

    @unittest.skipUnless(shutil.which('node'),'Node available for offline report theme check')
    def test_offline_report_theme_changes_without_storage_access(self):
        from control_theme import web_script,T
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('paths.data_directory',return_value=Path(directory)),patch.object(T,'mode','dark'):
            source=web_script(ROOT/'src')
        fixture="""
const colors={},events={},elements={},buttons=[];let resize=0;
global.window=global;global.dispatchEvent=()=>resize++;
global.localStorage={getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}};
global.document={documentElement:{dataset:{},style:{setProperty(k,v){colors[k]=v}}},head:{append(){}},
 createElement(){return {setAttribute(){}}},getElementById(id){return elements[id]},
 querySelector(){return {append(v){elements[v.id]=v;buttons.push(v)}}},addEventListener(k,v){events[k]=v}};
"""
        after="""
events.DOMContentLoaded();const first=StintrixTheme.mode;buttons[0].onclick();
process.stdout.write(JSON.stringify({first,mode:StintrixTheme.mode,bg:colors['--sl-bg'],fg:StintrixTheme.color('FG'),resize}));
"""
        result=subprocess.run([shutil.which('node'),'-'],input=fixture+source+after,capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout)
        self.assertEqual((value['first'],value['mode'],value['bg'],value['fg']),('dark','light','#e9e7e4','#262425'))
        self.assertEqual(value['resize'],3)


    def test_menu_brand_has_transparent_background_in_both_themes_and_app_stays_opaque(self):
        from PIL import Image,ImageStat
        from tools.build_brand import render
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            folder=render(directory)
            for name in ('menu-icon.png','menu-icon-light.png'):
                with Image.open(folder/name) as image:
                    self.assertEqual(image.mode,'RGBA');self.assertEqual(image.getpixel((0,0))[3],0)
                    self.assertEqual(image.getchannel('A').getextrema(),(0,255))
                    coverage=ImageStat.Stat(image.getchannel('A')).mean[0]/255
                    self.assertGreater(coverage,.08);self.assertLess(coverage,.65)
            with Image.open(folder/'stintrix-256.png') as image:
                self.assertEqual(image.getchannel('A').getextrema(),(255,255))
                self.assertEqual(image.getpixel((0,0)),(0,0,0,255))
