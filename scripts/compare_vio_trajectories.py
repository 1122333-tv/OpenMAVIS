"""evo evaluation on frozen IMU GT, exact common timestamps, and saved online poses."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
from vio_artifacts import dump, load_trajectory, write_trajectory, read_dicts, manifest, sha
from interpolate_mocap_to_vio import interpolate
from extend_evo_stats import read_stats

def gt_segment(t,intervals):
    return next((i for i,(a,b) in enumerate(intervals) if a<=t<=b),None)

def reference_pairs(reference,delta,times,intervals):
    from evo.core.metrics import id_pairs_from_delta, MetricsException
    from evo.core.units import Unit
    try:pairs=id_pairs_from_delta(reference.poses_se3,delta,Unit.meters,.1,all_pairs=True)
    except MetricsException as e:
        if 'empty' in str(e).lower():return [],[]
        raise
    segment=[gt_segment(t,intervals) for t in times]
    keep=[segment[i] is not None and segment[i]==segment[j] for i,j in pairs]
    return pairs,keep

def evaluate(name,poses,directory,gt,origin):
    from evo import main_ape
    from evo.core import metrics
    from evo.core.units import Unit
    from evo.tools import file_interface
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if (directory/'metrics.json').exists():raise ValueError('Existing evaluation; create a new --from-run comparison')
    out=dict(metrics={},unavailable_metrics={},interpolation=dict(input_vio_poses=len(poses),accepted_poses=0))
    if not poses:
        out['unavailable_metrics']['all']='Empty evaluation window';dump(directory/'metrics.json',out);return out,None
    write_trajectory(poses,directory)
    try:out['interpolation']=interpolate(gt,directory/'trajectory.tum',directory)
    except ValueError as e:
        if 'Fewer than 5 valid' not in str(e):raise
        out['interpolation']=json.loads((directory/'interpolation.json').read_text());out['unavailable_metrics']['all']=str(e)
        dump(directory/'metrics.json',out);return out,None
    ref=file_interface.read_tum_trajectory_file(directory/'mocap_at_vio.tum')
    est=file_interface.read_tum_trajectory_file(directory/'vio_matched.tum')
    times=[int(x[0]) for x in load_trajectory(directory/'mocap_at_vio.csv')]
    if min(np.linalg.matrix_rank(ref.positions_xyz-ref.positions_xyz.mean(axis=0),tol=1e-8),np.linalg.matrix_rank(est.positions_xyz-est.positions_xyz.mean(axis=0),tol=1e-8))<2:
        out['unavailable_metrics']['all']='Insufficient non-collinear alignment motion';dump(directory/'metrics.json',out);return out,None
    conversion=json.loads(Path(gt).with_name('conversion.json').read_text());intervals=conversion['valid_segments_ns']
    commands=[];arrays={}
    ape=main_ape.ape(ref,est,metrics.PoseRelation.translation_part,align=True,correct_scale=False,ref_name='mocap',est_name=name)
    # evo mutates est by applying SE(3), with scale fixed to one.
    file_interface.save_res_file(directory/'ape_translation.zip',ape,confirm_overwrite=False)
    out['metrics']['ape_translation']=read_stats(directory/'ape_translation.zip');arrays['ape_translation']=ape.np_arrays['error_array']
    commands.append(dict(api='evo.main_ape.ape',align=True,correct_scale=False,pose_relation='translation_part',reference=str(directory/'mocap_at_vio.tum'),estimate=str(directory/'vio_matched.tum')))
    out['alignment_transformation']=ape.np_arrays['alignment_transformation_sim3'].tolist()
    for delta in [.1,.5,1]:
        key=f'rpe_translation_{delta:g}m';pairs,keep=reference_pairs(ref,delta,times,intervals)
        if not any(keep):out['unavailable_metrics'][key]='No within-valid-segment reference-distance pairs';continue
        metric=metrics.RPE(metrics.PoseRelation.translation_part,delta,Unit.meters,.1,True,True)
        metric.process_data((ref,est))
        metric.error=metric.error[np.asarray(keep)];metric.E=[e for e,k in zip(metric.E,keep) if k]
        kept=[p for p,k in zip(pairs,keep) if k];metric.delta_ids=[j for i,j in kept]
        result=metric.get_result('mocap',name);ends=np.array([j for i,j in kept])
        result.add_np_array('timestamps',est.timestamps[ends]);result.add_np_array('seconds_from_start',est.timestamps[ends]-est.timestamps[0])
        result.add_trajectory('mocap',copy.deepcopy(ref));result.add_trajectory(name,copy.deepcopy(est))
        file_interface.save_res_file(directory/(key+'.zip'),result,confirm_overwrite=False)
        out['metrics'][key]=read_stats(directory/(key+'.zip'));arrays[key]=(metric.error,ends)
        dump(directory/(key+'_pairs.json'),dict(pairs=[[times[i],times[j]] for i,j in kept],discarded_cross_segment_pairs=sum(not k for k in keep)))
        commands.append(dict(api='evo.core.metrics.RPE',delta=delta,delta_unit='m',rel_delta_tol=.1,all_pairs=True,pairs_from_reference=True,valid_segment_filter=True))
    for key,stats in out['metrics'].items():dump(directory/(key+'_extended_stats.json'),dict(stats=stats,source=key+'.zip'))
    dump(directory/'commands.json',commands);dump(directory/'metrics.json',out)
    (directory/'evaluation.log').write_text('\n'.join(f'{k}: {json.dumps(v)}' for k,v in out['metrics'].items())+'\n')
    dump(directory/'plot_data.json',dict(timestamp_ns=times,reference_xyz=ref.positions_xyz.tolist(),aligned_estimate_xyz=est.positions_xyz.tolist(),ape=arrays['ape_translation'].tolist()))
    return out,dict(times=times,ref=ref.positions_xyz,est=est.positions_xyz,errors=arrays)

def plots(series,directory,origin):
    if not series:return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    directory=Path(directory);colors=['#0072B2','#B35B00','#007F6D','#7F4283'];styles=['-','--','-.',':']
    def gap(t,v):
        t=np.asarray(t);v=np.asarray(v);ix=np.flatnonzero(np.diff(t)>1.5*np.median(np.diff(t)))+1
        return np.insert(t,ix,np.nan),np.insert(v,ix,np.nan,axis=0)
    with plt.rc_context({'figure.facecolor':'white','axes.facecolor':'white','font.size':10,'axes.spines.top':False,'axes.spines.right':False}):
        fig,axes=plt.subplots(2,2,figsize=(12,7),layout='constrained')
        first=next(iter(series.values()));t=(np.array(first['times'],dtype=np.int64)-origin)*1e-9
        for c,ax in enumerate(axes.flat):
            if c<3:
                x,y=gap(t,first['ref'][:,c]);ax.plot(x,y,color='black',lw=1.3,label='mocap');ax.set(xlabel='Seconds since first input (IMU clock)',ylabel='XYZ'[c]+' [m]')
            else:
                _,y=gap(t,first['ref']);ax.plot(y[:,0],y[:,1],color='black',lw=1.3,label='mocap');ax.set(xlabel='Mocap world X [m]',ylabel='Mocap world Y [m]');ax.set_aspect('equal',adjustable='datalim')
            for i,(name,s) in enumerate(series.items()):
                x,y=gap((np.array(s['times'],dtype=np.int64)-origin)*1e-9,s['est'])
                ax.plot(x if c<3 else y[:,0],y[:,c] if c<3 else y[:,1],color=colors[i%4],ls=styles[i%4],lw=1,label=name)
            ax.grid(color='#dddddd');ax.legend(fontsize=9)
        fig.suptitle('Body trajectories: SE(3) aligned, no scale correction')
        fig.savefig(directory/'trajectories.png',dpi=160);plt.close(fig)
        fig,ax=plt.subplots(figsize=(12,4),layout='constrained')
        for i,(name,s) in enumerate(series.items()):
            x,y=gap((np.array(s['times'],dtype=np.int64)-origin)*1e-9,s['errors']['ape_translation'])
            ax.plot(x,y,label=name,color=colors[i%4],ls=styles[i%4],lw=1)
        ax.set(xlabel='Seconds since first input (IMU clock)',ylabel='APE translation [m]');ax.grid(color='#dddddd');ax.legend();fig.savefig(directory/'ape_translation.png',dpi=160);plt.close(fig)
        fig,axes=plt.subplots(3,1,figsize=(12,8),layout='constrained')
        for ax,delta in zip(axes,[.1,.5,1]):
            key=f'rpe_translation_{delta:g}m'
            for i,(name,s) in enumerate(series.items()):
                if key not in s['errors']:continue
                errors,ids=s['errors'][key];ax.scatter((np.array(s['times'],dtype=np.int64)[ids]-origin)*1e-9,errors,s=6,label=name,color=colors[i%4],marker=['o','s','^','d'][i%4])
            ax.set(ylabel=f'RPE {delta:g} m [m]');ax.grid(color='#dddddd')
            if ax.collections:ax.legend(fontsize=9)
        axes[-1].set_xlabel('Pair end time since first input [s]');fig.savefig(directory/'rpe_translation.png',dpi=160);plt.close(fig)

def compare(run):
    run=Path(run);m=manifest(run);directory=run/'04_vio_comparison';directory.mkdir(parents=True,exist_ok=True)
    os.environ['MPLCONFIGDIR']=str(run/'plot_cache');os.environ['MPLBACKEND']='Agg'
    prep=json.loads((run/'01_preparation/outputs/preparation.json').read_text());origin=prep['first_corrected_ns']
    gt=run/'02_reference/inputs/groundtruth/data.csv'
    summary=json.loads((run/'03_vio/outputs/summary.json').read_text());online=summary['online']
    tracks={name:load_trajectory(run/'02_reference/inputs'/(name+'_trajectory.csv')) for name in m['algorithms'] if name!='openmavis'}
    frames=read_dicts(run/'03_vio/outputs/replay/frames.csv')
    end=int(frames[-1]['corrected_ns']) if frames else prep['last_corrected_ns']
    tracks={name:[p for p in poses if origin<=p[0]<=end] for name,poses in tracks.items()}
    if online['common_eligible']:tracks={'openmavis':load_trajectory(run/'03_vio/outputs/online/trajectory_euroc.csv'),**tracks}
    result=dict(alignment='SE(3), no scale',time_offset='Frozen source IMU GT; no refit',origin_ns=origin,evaluation_window_ns=[origin,end],native={},common={},common_timestamps=dict(status='unavailable',n=0),trajectory_policy='OpenMAVIS online OK + IMU initialized; reference online snapshots')
    accepted={}
    for name,poses in tracks.items():
        r,s=evaluate(name,poses,directory/'native'/name,gt,origin);result['native'][name]=r
        if s:plots({name:s},directory/'native'/name,origin)
        csv=directory/'native'/name/'mocap_at_vio.csv'
        accepted[name]={t for t,v in load_trajectory(csv)} if csv.is_file() and r['interpolation'].get('accepted_poses',0)>0 else set()
    if not online['common_eligible']:
        result['common_timestamps']['reason']='OpenMAVIS has zero or multiple initialized coordinate segments; no selection/stitching'
        for segment in (run/'03_vio/outputs/online/coordinate_segments').glob('*'):
            r,s=evaluate('openmavis_epoch_'+segment.name,load_trajectory(segment/'trajectory_euroc.csv'),directory/'native'/('openmavis_epoch_'+segment.name),gt,origin)
            result['native']['openmavis_epoch_'+segment.name]=r
            if s:plots({'openmavis_epoch_'+segment.name:s},directory/'native'/('openmavis_epoch_'+segment.name),origin)
    else:
        common=sorted(set.intersection(*accepted.values()))
        result['common_timestamps'].update(n=len(common),first_ns=common[0] if common else None,last_ns=common[-1] if common else None)
        if len(common)<5:result['common_timestamps']['reason']='Fewer than five exact common GT-matchable timestamps'
        else:
            selected=set(common);series={}
            for name,poses in tracks.items():
                r,s=evaluate(name,[p for p in poses if p[0] in selected],directory/'common'/name,gt,origin);result['common'][name]=r
                if s:series[name]=s
            result['common_timestamps']['status']='available' if len(series)==len(tracks) else 'unavailable'
            if len(series)!=len(tracks):result['common_timestamps']['reason']='Insufficient alignment motion for one or more algorithms'
            plots(series,directory/'common',origin)
    final=run/'03_vio/outputs/final_map/trajectory_euroc.csv'
    if final.is_file():
        r,s=evaluate('openmavis_final_map',load_trajectory(final),directory/'final_map',gt,origin);result['final_map']=r
        if s:plots({'openmavis_final_map':s},directory/'final_map',origin)
    import evo
    result['evo_version']=evo.__version__;result['evaluators']={p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('interpolate_mocap_to_vio.py'),Path(__file__).with_name('extend_evo_stats.py')]}
    dump(directory/'summary/summary.json',result);return result

def show_gui(run):
    run=Path(run);m=manifest(run);directory=run/'04_vio_comparison';gui=run/'report/evo_gui';gui.mkdir(parents=True,exist_ok=True)
    dump(gui/'config.json',dict(plot_backend='QtAgg',plot_usetex=False))
    env={**os.environ,'MPLBACKEND':'QtAgg','MPLCONFIGDIR':str(run/'plot_cache')}
    commands=[]
    for metric in ['ape_translation','rpe_translation_0.1m','rpe_translation_0.5m','rpe_translation_1m']:
        files=[directory/'common'/name/(metric+'.zip') for name in m['algorithms']];files=[p for p in files if p.is_file()]
        if files:
            # Stable algorithm filenames make the evo legend readable.
            import shutil
            folder=gui/metric;folder.mkdir(exist_ok=True);targets=[]
            for p in files:
                target=folder/(p.parent.name+'.zip');shutil.copyfile(p,target);targets.append(target)
            cmd=[Path(sys.executable).parent/'evo_res',*[p.name for p in targets],'--use_filenames','--use_rel_time','--plot','--config',gui/'config.json'];commands.append(dict(argv=list(map(str,cmd)),cwd=str(folder)))
            subprocess.run(list(map(str,cmd)),cwd=folder,env=env,check=True)
    poses=[directory/'common'/name/'vio_matched.tum' for name in m['algorithms']]
    if all(p.is_file() for p in poses):
        folder=gui/'trajectories';folder.mkdir(exist_ok=True)
        for name,p in zip(m['algorithms'],poses):shutil.copyfile(p,folder/(name+'.tum'))
        shutil.copyfile(directory/'common'/m['algorithms'][0]/'mocap_at_vio.tum',folder/'mocap.tum')
        cmd=[Path(sys.executable).parent/'evo_traj','tum',*[name+'.tum' for name in m['algorithms']],'--ref','mocap.tum','--align','--t_max_diff','0.000000001','--plot','--plot_mode','xyz','--config',gui/'config.json'];commands.append(dict(argv=list(map(str,cmd)),cwd=str(folder)))
        subprocess.run(list(map(str,cmd)),cwd=folder,env=env,check=True)
    dump(gui/'commands.json',commands)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True,type=Path);a=ap.parse_args();compare(a.run)
