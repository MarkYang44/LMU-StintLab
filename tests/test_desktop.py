"""DPI, event-loop lifecycle and the real Windows icon resources."""
import os
from pathlib import Path
import struct
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
            folder=render(directory);blob=(folder/'stintlab.ico').read_bytes()
            self.assertEqual(struct.unpack_from('<HHH',blob),(0,1,len(SIZES)))
            for i,size in enumerate(SIZES):
                w,h,_,_,planes,bits,length,offset=struct.unpack_from('<BBBBHHII',blob,6+i*16)
                png=blob[offset:offset+length];self.assertEqual(png,(folder/f'stintlab-{size}.png').read_bytes())
                self.assertEqual((w or 256,h or 256,planes,bits),(size,size,1,32))
                self.assertEqual(png[:8],b'\x89PNG\r\n\x1a\n');self.assertEqual(struct.unpack_from('>II',png,16),(size,size))
                self.assertGreater(length,200)
    def test_only_reviewed_brand_vector_is_allowed_for_publication(self):
        from tools.audit_publication import allowed
        self.assertTrue(allowed('src/branding/stintlab.svg'))
        for name in ('src/branding/personal.svg','src/branding/private.png','data/stintlab.svg'):
            self.assertFalse(allowed(name))
