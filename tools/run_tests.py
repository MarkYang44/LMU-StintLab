"""Run Tcl and worker fixtures in separate processes; no personal fixtures."""
import argparse
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def flatten(suite):
    for case in suite:
        if isinstance(case,unittest.TestSuite):yield from flatten(case)
        else:yield case

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser();parser.add_argument('--quick',action='store_true');args=parser.parse_args()
    modules=['tests_distribution'] if args.quick else ['tests','tests_upgrades','tests_laplab','tests_selected_laps','tests_vehicle','tests_endurance','tests_distribution','tests_lightweight']
    names=[case.id() for module in modules for case in flatten(unittest.defaultTestLoader.loadTestsFromName(module))]
    failed=[]
    for name in names:
        result=subprocess.run([sys.executable,'-m','unittest',name,'-q'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
        print(('PASS' if result.returncode==0 else 'FAIL')+' '+name,flush=True)
        if result.returncode:failed.append(name);print(result.stdout+result.stderr,flush=True)
    print(f'{len(names)-len(failed)}/{len(names)} passed');return int(bool(failed))

if __name__=='__main__':raise SystemExit(main())
