#!/usr/bin/env python3
"""Reproducible prepared four-camera replay. Standard library only."""
import argparse,csv,datetime,hashlib,json,math,os,shlex,shutil,statistics,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT.parent/'basalt-monado/results/20260921_171047_017923_DOHC2_debug/run_20260922T105652_d91c1b/01_preparation/dataset'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()
def summarize(out,code,full,init_deadline=None):
    path=out/'frames.csv';rows=[]
    if path.exists():
        with path.open() as stream: rows=list(csv.DictReader(stream))
    initialized=[i for i,r in enumerate(rows) if r['imu_initialized']=='1'];first=initialized[0] if initialized else None
    post=rows[first:] if first is not None else []
    ok=sum(r['state']=='2' for r in post);ratio=ok/len(post) if post else 0
    changes=sum(a['map_id']!=b['map_id'] for a,b in zip(post,post[1:]));loss_init=sum(a['imu_initialized']=='1' and b['imu_initialized']=='0' for a,b in zip(post,post[1:]))
    longest=0.;start=None
    for i,r in enumerate(post):
        t=int(r['corrected_ns'])*1e-9
        if r['state']!='2' and start is None:start=t
        if start is not None:
            longest=max(longest,t-start)
            if r['state']=='2':start=None
    resets=int(post[-1]['resets'])-int(post[0]['resets']) if post and 'resets' in post[0] else None
    trajectories={}
    for name in ['trajectory_body.txt','keyframes_body.txt']:
        p=out/name; data=[list(map(float,l.split())) for l in p.read_text().splitlines() if l.strip() and not l.startswith('#')] if p.exists() else []
        valid=bool(data) and all(len(r)==8 and all(math.isfinite(x) for x in r) for r in data) and all(a[0]<b[0] for a,b in zip(data,data[1:]))
        trajectories[name]={'rows':len(data),'finite_strict_time':valid}
    source=json.loads((out/'input_summary.json').read_text()) if (out/'input_summary.json').exists() else {}
    complete=len(rows)==source.get('requested_frames',-1)
    timing_ok=bool(rows) and all(int(r['corrected_ns'])-int(r['raw_ns'])==source.get('cam_time_offset_ns') for r in rows) and all(int(a['imu_last_ns'])<int(b['imu_first_ns']) for a,b in zip(rows,rows[1:])) and all(int(r['imu_last_ns'])>=int(r['corrected_ns']) for r in rows)
    log=(out/'run.log').read_text(errors='replace') if (out/'run.log').exists() else ''
    reset_log_events=log.count('LM: Active map reset recieved')
    diagnostics=[];events=[];tracking=[]
    def read_csv(name):
        p=out/name
        with p.open() as f:return list(csv.DictReader(f))
    if (out/'diagnostics.csv').exists():diagnostics=read_csv('diagnostics.csv')
    if (out/'imu_events.csv').exists():events=read_csv('imu_events.csv')
    if (out/'tracking_events.csv').exists():tracking=read_csv('tracking_events.csv')
    camera_observations=[sum(max(0,int(r[f'local_after_cam{c}'])) for r in diagnostics) for c in range(4)]
    imu_events=sum(r['stage']=='imu_initialized' for r in events)
    bootstrap_bad=sum(r['event']=='keyframe_insert_begin' and r.get('imu_initialized')=='0' and
                      (r.get('state')!='2' or r.get('pose_valid')!='1') for r in tracking)
    detailed_ok=not (out/'diagnostics.csv').exists() or len(diagnostics)==len(rows) and all(camera_observations) and imu_events>0 and bootstrap_bad==0

    deadline_ok=init_deadline is None or first is not None and first<=init_deadline
    passed=detailed_ok and deadline_ok and code==0 and full and complete and timing_ok and first is not None and ratio>=.95 and rows[-1]['state']=='2' and rows[-1]['imu_initialized']=='1' and changes==0 and loss_init==0 and resets==0 and all(v['finite_strict_time'] for v in trajectories.values())
    summary={**source,'exit_code':code,'processed_frames':len(rows),'full_window_ok_ratio':sum(r['state']=='2' for r in rows)/len(rows) if rows else 0,'init_deadline_frame':init_deadline,'init_deadline_passed':deadline_ok,'timing_and_imu_partition_valid':timing_ok,'reset_log_events':reset_log_events,'ok_frames':sum(r['state']=='2' for r in rows),'first_imu_initialized_frame':first,'post_init_ok_ratio':ratio,'post_init_resets':resets,'total_resets':int(rows[-1]['resets']) if rows and 'resets' in rows[-1] else None,'post_init_map_changes':changes,'post_init_initialization_losses':loss_init,'longest_post_init_non_ok_seconds':longest,'final_state':int(rows[-1]['state']) if rows else None,'max_map_count':max((int(r['maps']) for r in rows),default=0),'observed_map_ids':sorted(set(int(r['map_id']) for r in rows)),'feature_min_per_camera':[min((int(r[f'cam{c}_features']) for r in rows),default=0) for c in range(4)],'trajectories':trajectories,'acceptance':'PASS' if passed else ('SHORT_RUN_ONLY' if not full and code==0 else 'NOT_PASSED'),'trajectory_semantics':'IMU/body to reference world; corrected camera time in seconds; trajectory_body uses largest map and first keyframe body origin; keyframes_body uses largest map world frame. Frames in other maps/lost frames may be omitted.'}
    summary['detailed_evidence']={'recorded':bool(diagnostics),'local_optimized_observations_per_camera':camera_observations,
        'actual_imu_initialization_events':imu_events,'unreliable_bootstrap_keyframe_attempts':bootstrap_bad,
        'post_init_unique_points_median':statistics.median(int(r['unique_inliers']) for r in diagnostics[first:]) if diagnostics and first is not None else None,
        'max_frame_preintegration_seconds':max((float(r['preintegration_dt']) for r in diagnostics),default=None)}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dataset',type=Path,default=DEFAULT);ap.add_argument('--settings',type=Path,default=ROOT/'Examples/Multi-Inertial/OAK4P_layout0921.yaml');ap.add_argument('--cam-time-offset-ns',type=int,default=2631359);ap.add_argument('--max-frames',type=int);ap.add_argument('--viewer',action='store_true');ap.add_argument('--realtime',action='store_true');ap.add_argument('--output',type=Path);ap.add_argument('--binary',type=Path,default=ROOT/'Examples/Multi-Inertial/multi_inertial_prepared');ap.add_argument('--diagnostics',action='store_true');ap.add_argument('--max-init-frame',type=int);args=ap.parse_args()
    out=(args.output or ROOT/'results'/('layout0921_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:6])).absolute()
    if out.exists():ap.error('Output already exists: '+str(out))
    out.parent.mkdir(parents=True,exist_ok=True)
    cmd=[str(args.binary.resolve()),'--vocabulary',str(ROOT/'Vocabulary/ORBvoc.txt'),'--settings',str(args.settings.resolve()),'--dataset',str(args.dataset.resolve()),'--cam-time-offset-ns',str(args.cam_time_offset_ns),'--output',str(out)]
    if args.max_frames is not None and args.max_frames<=0:ap.error('max-frames must be positive')
    if args.max_frames:cmd+=['--max-frames',str(args.max_frames)]
    if args.viewer:cmd+=['--viewer']
    if args.diagnostics:cmd+=['--diagnostics']
    if args.realtime:cmd+=['--realtime']
    tracked=subprocess.check_output(['git','diff','HEAD','--binary'],cwd=ROOT)
    status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)
    hashes={str(p):sha(p) for p in [args.settings.resolve()]+list(args.dataset.glob('mav0/*/data.csv'))}
    sources={str(p.relative_to(ROOT)):sha(p) for p in list((ROOT/'scripts').glob('*'))+list((ROOT/'Examples/Multi-Inertial').glob('*.cc')) if p.is_file()}
    provenance={'command':cmd,'command_shell':shlex.join(cmd),'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'git_status':status,'input_sha256':hashes,'implementation_sha256':sources,'executable_sha256':sha(Path(cmd[0])),'library_sha256':sha(args.binary.resolve().parents[2]/'lib/libORB_SLAM3.so'),'dataset':str(args.dataset.resolve()),'cam_time_offset_ns':args.cam_time_offset_ns,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    provenance['dependency_sha256']={str(p):sha(p) for p in [ROOT/'Thirdparty/g2o/lib/libg2o.so',ROOT/'Thirdparty/DBoW2/lib/libDBoW2.so']}
    provenance['runtime_environment']={k:os.environ.get(k) for k in ['DISPLAY','PANGOLIN_WINDOW_URI']}
    provenance['runtime_environment']['OMP_NUM_THREADS']='1'
    snapshot_files={path.relative_to(ROOT):path.read_bytes() for path in list((ROOT/'scripts').glob('*.py'))+list((ROOT/'scripts').glob('*.sh'))+list((ROOT/'Examples/Multi-Inertial').glob('*prepared*.cc'))}
    print('Output:',out,flush=True)
    # Temporary sibling log preserves failures that happen before the executable creates output.
    log=out.with_suffix('.log')
    started=time.monotonic()
    with log.open('x') as f:
        proc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,cwd=ROOT,env={**os.environ,'OMP_NUM_THREADS':'1'})
    provenance['wall_seconds']=time.monotonic()-started
    provenance['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    out.mkdir(exist_ok=True);log.rename(out/'run.log')
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n');(out/'working-tree.patch').write_bytes(tracked)
    (out/'settings.yaml').write_bytes(args.settings.read_bytes())
    prep=args.dataset.parent/'preparation.json'
    if prep.exists():(out/'preparation.json').write_bytes(prep.read_bytes())
    delivery=args.dataset.parent/'inputs/delivery'
    if delivery.exists():
        (out/'calibration_provenance').mkdir()
        for name in ['calibration.json','export_manifest.json']:
            source=delivery/name
            if source.exists():(out/'calibration_provenance'/name).write_bytes(source.read_bytes())
    snapshot=out/'source_snapshot';snapshot.mkdir()
    for relative,content in snapshot_files.items():
        target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    build=args.binary.resolve().parents[2]
    if (build/'build_source_snapshot').exists():shutil.copytree(build/'build_source_snapshot',out/'build_source_snapshot')
    for name in ['build_provenance.json','build.patch']:
        if (build/name).exists():(out/name).write_bytes((build/name).read_bytes())
    summary=summarize(out,proc.returncode,args.max_frames is None,args.max_init_frame)
    print(json.dumps(summary,indent=2));return proc.returncode or (0 if summary['acceptance'] in ['PASS','SHORT_RUN_ONLY'] else 2)
if __name__=='__main__':sys.exit(main())
