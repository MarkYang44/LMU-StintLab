"""Exercise the real recorder and offline exports using synthetic telemetry only."""
import json
from paths import data_directory

def run():
    from inputscope import Engine
    root=data_directory()
    engine=Engine(demo=True,output=root/'DemoLogs',settings={'mode':'fixed','fixed_hz':120})
    try:engine.stop.wait(43)
    finally:
        engine.stop.set();engine.wake.set();engine.thread.join(timeout=10)
    if engine.thread.is_alive():raise RuntimeError('Recorder did not stop')
    for worker in engine.recorder.pending_reports:worker.join(timeout=60)
    folder=engine.last_folder
    required=('inputs.csv','session.json','review.html','fastest_lap_summary.json','fastest_lap.html')
    checks={name:bool(folder and (folder/name).is_file()) for name in required}
    if folder and (folder/'fastest_lap_summary.json').exists():
        summary=json.loads((folder/'fastest_lap_summary.json').read_text(encoding='utf-8'))
        checks['complete_reference']=summary.get('status')=='saved'
    if all(checks.values()):
        from session_archive import export_session,import_session,_digest
        from library import inventory
        package=export_session(root,str(folder.relative_to(root)),root/'SessionPackages')
        restored=import_session(root/'archive-test-import',package['path'])
        from pathlib import Path
        imported=Path(restored['folder'])
        checks['archive_roundtrip']=all(_digest(folder/name)==_digest(imported/name) for name in required)
        checks['archive_in_library']=len(inventory(root/'archive-test-import'))==1
        checks['archive_duplicate']=import_session(root/'archive-test-import',package['path'])['status']=='skipped'
    result={'ok':all(checks.values()),'checks':checks,'synthetic_only':True}
    (root/'release-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['ok']:raise RuntimeError('Release smoke test failed: '+str(checks))
