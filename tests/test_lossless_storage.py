"""Full precision, bounded loaders, duplicate epochs and transparent archives."""
import gc,json,math,os,sys,tempfile,tracemalloc,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import json_store,session_compression as compression,telemetry_import as native
from analysis_spool import DiskTable,Column
from reporting import json_chunks

def plain(value):return json.loads(b''.join(json_chunks(value)))

class LosslessStorageTests(unittest.TestCase):
    def test_stream_boundaries_unicode_null_and_float64_match_standard_json(self):
        value={'text':'赛车, "\n\u0000 '+('🛰️'*31),'duplicate':2,
            'data':[[i*.01234567890123456,None if i%5 else 1.234567890123456e-120,i] for i in range(1300)],
            'channels':{'wheels':{'data':[[0,None,None],[.01,2.,None]]}},'tail':True}
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            p=Path(directory)/'test.json';p.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            for chunk in (1,7,65536):
                loaded=json_store.load(p,chunk_size=chunk)
                self.assertIsInstance(loaded['data'],DiskTable);self.assertEqual(plain(loaded),value)
                self.assertIsNone(loaded['data'][1][1]);self.assertEqual(loaded['data'][-1][0],value['data'][-1][0])
            self.assertEqual(json_store.load(p,fields=('text','tail'),chunk_size=11),{'text':value['text'],'tail':True})
    def test_irregular_nonfinite_big_integers_and_invalid_syntax_keep_semantics(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            p=Path(directory)/'test.json'
            for data in ([[1.,2.],[3.,None],[4.]],[[1.,2.],[True,3.]],[[1.,2.],[2**90,3.]],[[1.,2.],[math.nan,math.inf]],[]):
                text=json.dumps({'data':data});p.write_text(text,encoding='utf-8')
                self.assertEqual(json.dumps(plain(json_store.load(p)),allow_nan=True),json.dumps(json.loads(text),allow_nan=True)) if all(math.isfinite(x) for r in data for x in r if type(x)==float) else self.assertTrue(math.isnan(json_store.load(p)['data'][1][0]))
            for text in ('{"data":[[1,2],]}','{"x":1e+}','[1,','{"x":1}junk','{"x":"unterminated','{"x":1,}', '[truefalse]'):
                p.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError):json_store.load(p,chunk_size=3)
    def test_large_matrix_loader_does_not_retain_boxed_rows(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            p=Path(directory)/'matrix.json'
            with p.open('w',encoding='utf-8') as out:
                out.write('{"data":[')
                for i in range(20000):out.write((',' if i else '')+json.dumps([i*.01,.123456789012345,None,i]))
                out.write(']}')
            def peak(fn):
                gc.collect();tracemalloc.start();value=fn();_,n=tracemalloc.get_traced_memory();tracemalloc.stop();return n,value
            old,a=peak(lambda:json.loads(p.read_text(encoding='utf-8')));new,b=peak(lambda:json_store.load(p))
            self.assertLess(new,old*.3);self.assertEqual(plain(b),a)
    def test_native_batch_duplicate_boundary_and_lookup_preserve_source_hash(self):
        import duckdb
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory);p=root/'source.duckdb';db=duckdb.connect(str(p))
            db.execute('CREATE TABLE metadata(key VARCHAR,value VARCHAR)');db.execute('CREATE TABLE channelsList(channelName VARCHAR,frequency DOUBLE,unit VARCHAR)')
            db.execute('CREATE TABLE eventsList(eventName VARCHAR,unit VARCHAR)')
            db.execute("INSERT INTO channelsList VALUES ('Fuel Level',120,'L')")
            db.execute('CREATE TABLE "Fuel Level" AS SELECT CASE WHEN i=8192 THEN 8191.0/120 ELSE i/120.0 END ts,i*CAST(.123456789012345 AS DOUBLE) AS "value" FROM range(16400) t(i)')
            db.close();sha=native.fingerprint(p);_,series,_=native.read_native(p,root);s=series['Fuel Level'];s['times']=Column(s['data'])
            self.assertIsInstance(s['data'],DiskTable);self.assertEqual(len(s['data']),16399)
            self.assertEqual(s['data'][8191],[8191/120,8192*.123456789012345])
            self.assertEqual(s['data'][-1],[16399/120,16399*.123456789012345])
            for target in (0,8191/120,100.5,.1,90):
                s.pop('_lookup_target',None);expected=native.lookup(s,target);self.assertEqual(native.lookup(s,target),expected)
            self.assertEqual(native.fingerprint(p),sha);s['data'].close()
    def test_compression_hashes_archives_and_permanent_deletion(self):
        if os.name!='nt':self.skipTest('Windows LZX')
        from session_archive import export_session,import_session
        from session_delete import remove
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory)/'data';folder=root/'Logs'/'Synthetic';folder.mkdir(parents=True)
            (folder/'session.json').write_text(json.dumps(dict(status='complete',track='Synthetic',vehicle='Test',session=10)),encoding='utf-8')
            csv=b'time_s,throttle\n'+b'0.123456789012345,0.987654321012345\n'*9000
            (folder/'inputs.csv').write_bytes(csv);(folder/'preview.png').write_bytes(b'already compressed image')
            before=compression.physical_size(folder/'inputs.csv');result=compression.compress(folder)
            self.assertTrue(result['supported']);self.assertFalse(result['errors']);self.assertGreater(result['saved_bytes'],0)
            self.assertEqual((folder/'inputs.csv').read_bytes(),csv);self.assertLess(compression.physical_size(folder/'inputs.csv'),before)
            self.assertEqual(result['files'][0]['sha256'],compression.digest(folder/'inputs.csv'))
            archive=export_session(root,'Logs/Synthetic',Path(directory)/'exports');restored=import_session(Path(directory)/'restored',archive['path'])
            self.assertEqual((Path(restored['folder'])/'inputs.csv').read_bytes(),csv)
            self.assertEqual((folder/'preview.png').read_bytes(),b'already compressed image')
            second=compression.compress(folder);self.assertEqual(second['saved_bytes'],0)
            remove(root,'Logs/Synthetic');self.assertFalse(folder.exists())
    def test_recording_guard_and_unsupported_filesystem_never_run_compact(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            p=Path(directory);meta=p/'session.json';meta.write_text('{"status":"recording"}')
            with patch('session_compression.subprocess.run') as spawn:
                with self.assertRaises(ValueError):compression.compress(p)
                spawn.assert_not_called()
            meta.write_text('{"status":"complete"}')
            with patch('session_compression.ntfs',return_value=False),patch('session_compression.subprocess.run') as spawn:
                self.assertFalse(compression.compress(p)['supported']);spawn.assert_not_called()
    def test_stable_filter_reads_headers_and_loads_only_winner(self):
        import reference
        with tempfile.TemporaryDirectory(dir=ROOT/'_local') as directory:
            root=Path(directory)
            for name,track,time in [('irrelevant','Other',10),('slow','Test',21),('winner','Test',20)]:
                folder=root/'Logs'/name;folder.mkdir(parents=True)
                (folder/'session_analysis.json').write_text('{"stable_reference_file":"stable.lap.json","laps":[1,2,3]}')
                value=dict(format='inputscope.fastest-lap',version=1,session={'track':track,'vehicle':'Car'},lap={'time_s':time,'track_length_m':1000},conditions={},
                    data=[[0,0,0,0,0,0,0],[500,time/2,.2,.3,.4,.5,200],[1000,time,1,0,1,0,200]])
                (folder/'stable.lap.json').write_text(json.dumps(value))
            actual=reference.ReferenceLap.load
            with patch.object(reference.ReferenceLap,'load',side_effect=actual) as load:
                chosen=reference.best_reference(root,dict(track='Test',vehicle='Car',track_length=1000),kind='stable')
                self.assertEqual(chosen.duration,20);self.assertEqual(load.call_count,1)
