#!/usr/bin/env python3
"""Run immutable OpenMAVIS VIO/evo/report stages from frozen reference runs."""
import argparse
import datetime
import json
import importlib.metadata
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import uuid
import yaml
from vio_artifacts import ROOT, STAGES, dump, sha, hashes, manifest, csv_rows, normalize_online, normalize_final, dynamic_libraries
from vio_sources import inspect, import_reference, verify_sources
from convert_rig_to_openmavis import convert
from run_prepared import summarize

def git_info():
    def get(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True)
    return dict(head=get('rev-parse','HEAD').strip(),status=get('status','--short'),diff=get('diff','HEAD','--binary'))

def source_hint(root):
    # Hints only protect paths and choose an output label; definitive validation
    # happens inside prepare so broken source manifests still get a report.
    try:
        value=yaml.safe_load((Path(root)/'manifest.yaml').read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,yaml.YAMLError):return {}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sources=ap.add_mutually_exclusive_group()
    sources.add_argument('--basalt-run',type=Path);sources.add_argument('--okvis-run',type=Path)
    ap.add_argument('--from-run',type=Path);ap.add_argument('--step',choices=['all','prepare','vio','compare','report'],default='all')
    ap.add_argument('--binary',type=Path,default=None);ap.add_argument('--config',type=Path)
    ap.add_argument('--imu-bias-policy',choices=['require-zero','estimate-from-zero'])
    ap.add_argument('--output',type=Path);ap.add_argument('--run-name',default='vio')
    ap.add_argument('--max-frames',type=int);ap.add_argument('--show-gui',action='store_true');ap.add_argument('--evo-show-gui',action='store_true');ap.add_argument('--realtime',action='store_true')
    args=ap.parse_args()
    if args.max_frames is not None and args.max_frames<=0:ap.error('--max-frames must be positive')
    if not args.run_name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.run_name):ap.error('Unsafe run name')
    prior=manifest(args.from_run) if args.from_run else None
    if prior:
        if args.basalt_run or args.okvis_run or args.config or args.imu_bias_policy:ap.error('--from-run uses frozen input/config; overrides forbidden')
        if args.step in ('all','prepare'):ap.error('--from-run requires vio/compare/report')
        if args.step in ('compare','report') and (args.max_frames is not None or args.show_gui or args.realtime or args.binary):ap.error('VIO options cannot relabel reused trajectories')
        params=prior['parameters'].copy()
    else:
        source=args.basalt_run or args.okvis_run
        if not source:ap.error('Choose --basalt-run or --okvis-run')
        if args.step not in ('all','prepare'):ap.error('Later stages require --from-run')
        source=source.resolve();sm=source_hint(source)
        identity=sm.get('dataset') or sm.get('parameters',{}).get('dataset')
        params=dict(source_run=str(source),source_kind='basalt' if args.basalt_run else 'okvis',dataset_identity=str(identity or source.name),
                    algorithm_template=str((args.config or ROOT/'Examples/Multi-Inertial/OAK4P_layout0921_repaired.yaml').resolve()),
                    imu_bias_policy=args.imu_bias_policy or 'require-zero')
    base=(args.output or ROOT/'results'/Path(params['dataset_identity']).name).resolve()
    protected=[Path(params['source_run']).resolve(),Path(params['dataset_identity']).resolve()]
    # Resolve possible dataset links before creating anything: an OKVIS link can
    # target a different protected Basalt run outside the OKVIS directory.
    source_root=Path(params['source_run']).resolve()
    sm=source_hint(source_root)
    prep_hint=source_root/sm.get('stages',{}).get('prepare',{}).get('directory','01_preparation')
    for hint in [prep_hint/'dataset',prep_hint/'outputs/dataset']:
        if hint.exists() or hint.is_symlink():protected.append(hint.resolve())
    basalt_hint=sm.get('parameters',{}).get('basalt_run')
    if basalt_hint:protected.append(Path(basalt_hint).resolve())
    if prior:protected += [Path(args.from_run).resolve(),Path(params['prepared_dataset']).resolve()]
    if any(base==p or p in base.parents for p in protected):ap.error('Output must be outside source data/runs')
    run=base/('run_'+datetime.datetime.now().strftime('%Y%m%dT%H%M%S')+'_'+args.run_name+'_'+uuid.uuid4().hex[:6]);run.mkdir(parents=True)
    m=dict(format='openmavis-vio',version=1,status='running',parameters=params,stages={},invocation=sys.argv,python=sys.executable,
           started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),software=git_info(),from_run=str(args.from_run.resolve()) if prior else None)
    m['software']['python_version']=sys.version
    m['software']['packages']={}
    for package in ['numpy','PyYAML','matplotlib','Pillow','evo','PyQt6']:
        try:m['software']['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:m['software']['packages'][package]=None
    provenance=run/'provenance';provenance.mkdir()
    for p in (ROOT/'scripts').glob('*.py'):shutil.copyfile(p,provenance/p.name)
    shutil.copytree(ROOT/'scripts/vendor',provenance/'vendor')
    m['implementation_sha256']=hashes(provenance)
    m['runtime_environment']={k:os.environ.get(k) for k in ['DISPLAY','QT_QPA_PLATFORM','PANGOLIN_WINDOW_URI']}
    m['runtime_environment']['OMP_NUM_THREADS']='1'
    def save(): (run/'manifest.yaml').write_text(yaml.safe_dump(m,sort_keys=False,allow_unicode=True))
    save();print('Run: '+str(run),flush=True)
    binary=(args.binary or (Path(params['binary']) if prior and 'binary' in params else ROOT/'build-vio/Examples/Multi-Inertial/multi_inertial_prepared')).resolve()
    def command(stage,argv,cwd=None):
        m['stages'][stage].setdefault('commands',[]).append(list(map(str,argv)));save()
        with (run/STAGES[stage]/'logs/stage.log').open('a') as stream:
            started=time.monotonic()
            p=subprocess.run(list(map(str,argv)),cwd=cwd or ROOT,env={**os.environ,'OMP_NUM_THREADS':'1','MPLBACKEND':'Agg','MPLCONFIGDIR':str(run/'plot_cache')},stdout=stream,stderr=subprocess.STDOUT)
        m['stages'][stage].setdefault('command_results',[]).append(dict(exit_code=p.returncode,wall_seconds=time.monotonic()-started));save()
        if p.returncode:raise RuntimeError(f'{stage} command exit {p.returncode}; see {run/STAGES[stage]/"logs/stage.log"}')
    def stage(name,action):
        directory=run/STAGES[name]
        for sub in ['inputs','outputs','logs','diagnostics']:(directory/sub).mkdir(parents=True,exist_ok=True)
        m['stages'][name]=dict(status='running',directory=STAGES[name]);save();t=time.monotonic()
        try:
            action(directory);m['stages'][name]['status']='complete';m['stages'][name]['artifact_sha256']=hashes(directory)
        except BaseException as e:
            m['stages'][name].update(status='failed',error=str(e));raise
        finally:m['stages'][name]['wall_seconds']=time.monotonic()-t;save()
    def reuse(name):
        record=prior['stages'].get(name,{})
        if record.get('status') not in ('complete','reused'):raise ValueError('Cannot reuse incomplete stage: '+name)
        source=Path(args.from_run)/STAGES[name]
        for p,h in record.get('artifact_sha256',{}).items():
            if sha(source/p)!=h:raise ValueError('Frozen prerequisite changed: '+p)
        shutil.copytree(source,run/STAGES[name],symlinks=True)
        m['stages'][name]=dict(status='reused',directory=STAGES[name],source=str(source.resolve()),artifact_sha256=hashes(run/STAGES[name]));save()
    def check_indices():
        prep=json.loads((run/'01_preparation/outputs/preparation.json').read_text())
        for c,h in prep['index_sha256'].items():
            if sha(Path(params['prepared_dataset'])/'mav0'/c/'data.csv')!=h:raise ValueError('Prepared CSV changed: '+c)
    def check_binary():
        if not binary.is_file():raise ValueError('Missing isolated binary; build with scripts/build_vio.sh or pass --binary')
        build=binary.parents[2];record=build/'build_provenance.json'
        if not record.is_file():raise ValueError('Binary has no source build provenance; rebuild isolated output')
        b=json.loads(record.read_text())
        for relative,h in b['source_sha256'].items():
            if relative.startswith(('src/','include/','Examples/')) and sha(ROOT/relative)!=h:raise ValueError('Binary/source mismatch: '+relative)
        params['binary']=str(binary)
        m['binary']=dict(path=str(binary),sha256=sha(binary),library_sha256=sha(build/'lib/libORB_SLAM3.so'),vocabulary_sha256=sha(ROOT/'Vocabulary/ORBvoc.txt'),build_provenance_sha256=sha(record),dynamic_libraries=dynamic_libraries(binary))
    def prepare(directory):
        info=inspect(params['source_run'],params['source_kind']);params.update(prepared_dataset=str(info['dataset']),cam_time_offset_ns=info['offset'],dataset_identity=info['identity'])
        if any(base==p or p in base.parents for p in [info['dataset'],Path(info['identity']).resolve()]):raise ValueError('Output overlaps prepared/source dataset')
        m['source_hashes']=info['source_hashes'];import_reference(info,run/'02_reference/inputs')
        shutil.copyfile(info['calibration'],directory/'inputs/calibration.json');shutil.copyfile(info['export'],directory/'inputs/export_manifest.json')
        shutil.copyfile(params['algorithm_template'],directory/'inputs/algorithm_template.yaml')
        (directory/'outputs/dataset').symlink_to(info['dataset'],target_is_directory=True)
        times=[int(r[0]) for r in csv_rows(info['dataset']/'mav0/cam0/data.csv')]
        if len(times)<2 or any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Invalid image times')
        fps=round(1e9/statistics.median(b-a for a,b in zip(times,times[1:])))
        conversion=convert(directory/'inputs/calibration.json',directory/'inputs/algorithm_template.yaml',directory/'outputs/openmavis.yaml',info['offset'],fps,params.get('imu_bias_policy','require-zero'))
        check_binary()
        cmd=[binary,'--vocabulary',ROOT/'Vocabulary/ORBvoc.txt','--settings',directory/'outputs/openmavis.yaml','--dataset',info['dataset'],'--cam-time-offset-ns',info['offset'],'--output',directory/'outputs/input_validation','--validate-only']
        command('prepare',cmd)
        indices={c:sha(info['dataset']/'mav0'/c/'data.csv') for c in ['cam0','cam1','cam2','cam3','imu0']}
        m['source_hashes'].update({str(info['dataset']/'mav0'/c/'data.csv'):h for c,h in indices.items()})
        dump(directory/'outputs/preparation.json',dict(groups=len(times),index_sha256=indices,cam_time_offset_ns=info['offset'],first_corrected_ns=times[0]+info['offset'],last_corrected_ns=times[-1]+info['offset'],conversion=conversion))
        m['algorithms']=['openmavis',*info['algorithms']];verify_sources(info['source_hashes'])
    def reference(directory):
        m['reference_policy']='Frozen IMU/body GT, already time/pose transformed; no refit or repeated transform'
    def estimate(directory):
        check_indices();check_binary();shutil.copyfile(run/'01_preparation/outputs/openmavis.yaml',directory/'inputs/openmavis.yaml')
        shutil.copyfile(binary.parents[2]/'build_provenance.json',directory/'inputs/build_provenance.json')
        out=directory/'outputs/replay'
        cmd=[binary,'--vocabulary',ROOT/'Vocabulary/ORBvoc.txt','--settings',directory/'inputs/openmavis.yaml','--dataset',params['prepared_dataset'],'--cam-time-offset-ns',params['cam_time_offset_ns'],'--output',out,'--diagnostics','--online-output']
        if args.max_frames:cmd += ['--max-frames',args.max_frames]
        if args.show_gui:cmd += ['--viewer']
        if args.realtime:cmd += ['--realtime']
        t=time.monotonic()
        try:command('vio',['/usr/bin/time','-v','-o',directory/'diagnostics/resource_usage.txt',*cmd])
        finally:
            if out.exists():shutil.copyfile(directory/'logs/stage.log',out/'run.log')
        summary=summarize(out,0,args.max_frames is None,299 if 'DOHC2_debug' in params['dataset_identity'] else None)
        online=normalize_online(out/'online_body.csv',directory/'outputs/online')
        if online['input_rows']!=summary['processed_frames']:raise ValueError('Online/processed rows differ')
        if (out/'trajectory_body.txt').is_file():normalize_final(out/'trajectory_body.txt',out/'frames.csv',directory/'outputs/final_map')
        summary.update(online=online,show_gui=args.show_gui,realtime=args.realtime,wall_seconds=time.monotonic()-t,requested_max_frames=args.max_frames)
        dump(directory/'outputs/summary.json',summary);m['tracking_acceptance']=summary['acceptance'];m['vio_summary']=summary
    def compare(directory):
        from compare_vio_trajectories import compare
        m['comparison']=compare(run);m['comparison_availability']=m['comparison']['common_timestamps']['status']
    try:
        if prior:
            m['algorithms']=prior['algorithms'];m['source_hashes']=prior['source_hashes'];m['binary']=prior.get('binary',{});reuse('prepare');reuse('reference');check_indices()
        else:stage('prepare',prepare);stage('reference',reference)
        if args.step in ('all','vio'):stage('vio',estimate)
        elif args.step in ('compare','report'):
            reuse('vio');m['tracking_acceptance']=prior.get('tracking_acceptance');m['vio_summary']=prior.get('vio_summary')
        if args.step in ('all','compare'):stage('compare',compare)
        elif args.step=='report':reuse('compare');m['comparison']=prior.get('comparison');m['comparison_availability']=prior.get('comparison_availability')
        verify_sources(m.get('source_hashes',{}));m['source_hashes_unchanged']=True;m['status']='complete'
    except BaseException as e:
        m.update(status='failed',error=str(e));print('Pipeline error: '+str(e),file=sys.stderr,flush=True)
    finally:
        m['ended_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
        from generate_vio_report import generate
        try:stage('report',lambda directory:generate(run))
        except Exception as e:m.update(status='failed',report_error=str(e));save();print('Report error: '+str(e),file=sys.stderr)
    print('Report: '+str(run/'report/index.html'),flush=True)
    if args.evo_show_gui and m.get('comparison_availability')=='available':
        from compare_vio_trajectories import show_gui
        try:
            show_gui(run);m['evo_gui']=dict(status='complete',command_record=str(run/'report/evo_gui/commands.json'))
        except Exception as e:
            m['evo_gui']=dict(status='failed',error=str(e));m['status']='failed';print('evo GUI error: '+str(e),file=sys.stderr)
        save();generate(run);m['stages']['report']['artifact_sha256']=hashes(run/'report');save()
    return 1 if m['status']=='failed' else (2 if m.get('tracking_acceptance')=='NOT_PASSED' or m.get('comparison_availability')=='unavailable' else 0)

if __name__=='__main__':sys.exit(main())
