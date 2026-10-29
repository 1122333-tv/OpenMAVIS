#!/usr/bin/env python3
"""Run each frozen OKVIS2 source once; references are never executed or modified."""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import subprocess
import sys
from vio_artifacts import ROOT, dump, sha
from vio_sources import inspect, verify_sources

ORDER=['small_move','big_move','dynamic_background','static_H_30s','static_V_30s','static_H_30s_humanmove']

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-state',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--case',choices=ORDER);ap.add_argument('--remaining',action='store_true')
    a=ap.parse_args()
    if bool(a.case)==a.remaining:ap.error('Choose --case or --remaining')
    root=a.output.resolve();source=a.source_state.resolve()
    # Never put new artifacts inside the reference batch.
    if root==source.parent or source.parent in root.parents:ap.error('Output overlaps reference batch')
    root.mkdir(parents=True,exist_ok=True)
    lock=(root/'batch.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state_path=root/'state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if state['source_state']!=str(source) or sha(source)!=state['source_state_sha256']:raise ValueError('Reference batch changed')
    else:
        src=json.loads(source.read_text())
        if src['status']!='complete':raise ValueError('Reference batch incomplete')
        protected={str(source):sha(source)};cases={}
        for name in ORDER:
            record=src['runs'][name];run=Path(record['run']);info=inspect(run,'okvis')
            if record['status']!='complete':raise ValueError('Incomplete source: '+name)
            basalt=inspect(Path(record['basalt_run']),'basalt')
            protected.update(info['source_hashes']);protected.update(basalt['source_hashes'])
            for camera in ['cam0','cam1','cam2','cam3','imu0']:
                p=info['dataset']/'mav0'/camera/'data.csv';protected[str(p)]=sha(p)
            cases[name]=dict(source_run=str(run),basalt_run=record['basalt_run'],profile=record['profile'],status='pending')
        state=dict(status='prepared',source_state=str(source),source_state_sha256=sha(source),
                   created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),runs=cases,
                   policy={'repeats':1,'imu_bias':'estimate-from-zero','references':'frozen online VIO; never rerun','gui':False,'realtime':False})
        dump(root/'protected_inputs.json',protected);dump(state_path,state)
    protected=json.loads((root/'protected_inputs.json').read_text());verify_sources(protected)
    names=[a.case] if a.case else ORDER
    for name in names:
        r=state['runs'][name]
        if r['status'] in ('complete','diagnostic_complete'):continue
        if r['status']!='pending':raise ValueError('Prior attempt retained; explicit review required before any rerun: '+name)
        out=root/'runs'/name;cmd=[sys.executable,str(ROOT/'scripts/run_vio_pipeline.py'),'--okvis-run',r['source_run'],
            '--imu-bias-policy','estimate-from-zero','--evaluation-profile',r['profile'],'--output',str(out),'--run-name','poc1026_'+name]
        r.update(status='running',command=cmd,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat());state['status']='running';dump(state_path,state)
        print('Running '+name,flush=True)
        with (root/(name+'_pipeline.log')).open('w') as log:p=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        runs=sorted(out.glob('run_*'))
        if len(runs)!=1:raise ValueError('Expected exactly one new run: '+name)
        r.update(status='complete' if p.returncode==0 else 'diagnostic_complete' if p.returncode==2 else 'failed',
                 run=str(runs[0]),returncode=p.returncode,ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        verify_sources(protected);dump(root/'preservation.json',dict(protected_files=len(protected),changed=[],checked_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
        state['status']='complete' if all(x['status'] in ('complete','diagnostic_complete') for x in state['runs'].values()) else 'partial'
        dump(state_path,state);print(name+': '+r['status'],flush=True)
        if p.returncode not in (0,2):return p.returncode
    return 0

if __name__=='__main__':sys.exit(main())
