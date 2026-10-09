"""Bounded exact analysis, live snapshots and low-memory report recovery."""
import csv,gc,json,math,random,sys,tempfile,tracemalloc,unittest
from array import array
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from analysis_spool import DiskTable,LapRows,Slice,median
from buffers import CompactRow,NumericRing,packed_window,window_rows,trace_lane
import report_worker

class MemoryTests(unittest.TestCase):
    def test_spilled_rows_preserve_double_missing_fields_and_variable_utc_with_lazy_slices(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            rows=LapRows(directory);layout={'session_time_s':0,'throttle':1,'fuel_l':2};expected=[]
            for i in range(3000):
                row=CompactRow(layout,[i*.012345678901234,.123456789012345,math.nan if i%3 else 12.0],('UTC车手\n'*((i%6)+1))+str(i))
                rows.append(row);expected.append(dict(row))
            rows.seal();self.assertIsInstance(rows[1:],Slice)
            self.assertEqual([dict(r) for r in rows],expected)
            self.assertEqual([dict(r) for r in rows[::-37]],[dict(r) for r in list(rows)[::-37]])
            self.assertLessEqual(sum(len(v) for v in rows.table._cache.values()),131072)
            rows.close();self.assertFalse(list(Path(directory).iterdir()))
    def test_exact_median_matches_statistics_for_duplicate_and_uneven_intervals(self):
        import statistics
        rng=random.Random(73)
        for n in range(1,100):
            values=[rng.choice([.001,.1,1.,rng.random()]) for _ in range(n)]
            self.assertEqual(median(array('d',values)),statistics.median(values))
    def test_packed_snapshot_preserves_both_channels_extrema_wrap_and_gap_without_boxed_history(self):
        ring=NumericRing(19,513)
        for i in range(1800):ring.append([i*.01,*[math.sin(i+k) for k in range(18)]])
        for cutoff in (0,13,17.93,50):
            old=window_rows(ring,cutoff);new=packed_window(ring,cutoff)
            self.assertEqual(list(new),old)
            for offset in (1,10):
                for lane in range(3):self.assertEqual(list(trace_lane(new,offset,lane)),list(trace_lane(old,offset,lane)))
        previous=list(new);ring.append([100]*19);self.assertEqual(list(new),previous)
    def test_snapshot_heap_is_bounded_by_exact_numeric_bytes(self):
        ring=NumericRing(19,4097)
        for i in range(4000):ring.append([i,*([.123456789012345]*18)])
        def peak(function):
            gc.collect();tracemalloc.start();value=function();_,maximum=tracemalloc.get_traced_memory();tracemalloc.stop();return maximum,value
        old,a=peak(lambda:window_rows(ring,0));new,b=peak(lambda:packed_window(ring,0))
        self.assertEqual(a,list(b));self.assertLess(new,old*.3)
    def test_pressure_defers_without_spawning_and_resumes_without_rewriting_recording(self):
        from recorder import Recorder
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);folder=root/'Logs/Synthetic';folder.mkdir(parents=True)
            (folder/'session.json').write_text('{"status":"complete"}',encoding='utf-8');(folder/'inputs.csv').write_bytes(b'original')
            with patch('report_worker.can_report',return_value=False),patch('report_worker.subprocess.run') as spawn:
                with self.assertRaises(report_worker.ReportDeferred):report_worker.run(folder,root)
                spawn.assert_not_called()
            with patch('recorder.make_report',side_effect=report_worker.ReportDeferred('memory')):Recorder._report(folder)
            self.assertTrue((folder/'report_pending.json').exists());self.assertFalse((folder/'report_error.txt').exists())
            with patch('report_worker.can_report',return_value=False):self.assertEqual(report_worker.resume_pending(root),0)
            with patch('report_worker.can_report',return_value=True),patch('session_reports.make_report') as make:
                self.assertEqual(report_worker.resume_pending(root),1);make.assert_called_once_with(folder,isolated=True)
            self.assertFalse((folder/'report_pending.json').exists());self.assertEqual((folder/'inputs.csv').read_bytes(),b'original')
    def test_real_isolated_worker_generates_complete_reports_and_exits(self):
        from tests.test_core import Tests
        import session_reports
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);folder=Tests().lap_csv(root/'Logs/Synthetic');original=(folder/'inputs.csv').read_bytes()
            (root/'renderer_settings.json').write_text('{"mode":"native"}',encoding='utf-8')
            with patch('session_reports.ROOT',root),patch('report_worker.can_report',return_value=True):session_reports.make_report(folder,isolated=True)
            self.assertTrue((folder/'review.html').is_file());self.assertTrue((folder/'fastest_lap_summary.json').is_file())
            self.assertTrue((folder/'比赛日志.png').is_file());self.assertEqual((folder/'inputs.csv').read_bytes(),original)
            self.assertFalse((folder/'report_worker.log').exists())

    def test_hidden_native_guide_releases_images_and_restores_them_on_show(self):
        import os,time
        if os.name!='nt':self.skipTest('Windows native menu')
        from control_center import ControlCenter
        from guide_cards import Picture
        def walk(w):
            yield w
            for c in w.winfo_children():yield from walk(c)
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory,patch('control_center.ROOT',Path(directory)):
            center=ControlCenter()
            def wait(condition):
                end=time.monotonic()+3
                while time.monotonic()<end:
                    center.root.update();time.sleep(.005)
                    if condition():return
                self.fail('Guide image did not settle')
            try:
                center.show_page(6);center.scroll.yview_moveto(.25)
                pictures=[w for w in walk(center.content) if isinstance(w,Picture)]
                wait(lambda:any(p.photo for p in pictures));center.hide();center.root.update()
                self.assertTrue(all(p.photo is None and p.loading is None for p in pictures))
                center.root.deiconify();wait(lambda:any(p.photo for p in pictures))
            finally:center.close()
