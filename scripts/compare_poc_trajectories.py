"""POC comparison of frozen online VIO tracks on identical integer-ns samples."""
import csv
import json
from pathlib import Path
import numpy as np
from vio_artifacts import dump, load_trajectory, write_trajectory, read_dicts, manifest, sha
from interpolate_mocap_to_vio import interpolate
from poc_metrics import timestamps, segment_labels, common_labels, evaluate_matched

COLORS={'openmavis':'#007F6D','okvis':'#B35B00','basalt':'#0072B2'}
STYLES={'openmavis':'-','okvis':'-.','basalt':'--'}
LABELS={'openmavis':'OpenMAVIS','okvis':'OKVIS2','basalt':'Basalt'}

def unavailable(reason):
    return dict(metrics={},unavailable_metrics={'all':reason},interpolation={'accepted_poses':0})

def evaluate(folder, profile, labels):
    try:
        record=evaluate_matched(folder,profile,labels)
    except Exception as error:
        # Degenerate motion is an unavailable estimate, never a fabricated zero.
        from evo.core.geometry import GeometryException
        if not isinstance(error,GeometryException):raise
        record=unavailable(str(error))
    dump(folder/'segments.json',list(map(int,labels)))
    dump(folder/'metrics.json',record)
    return record

def plot_scope(output,scope,records,origin):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    dest=output/scope if scope=='common' else output/'native/combined'
    dest.mkdir(parents=True,exist_ok=True)
    def base(name):return name.split('_epoch_')[0]
    def broken(x,y,labels):
        cuts=np.flatnonzero(np.diff(labels)!=0)+1
        return np.insert(x,cuts,np.nan),np.insert(y,cuts,np.nan,axis=0)
    with plt.rc_context({'figure.facecolor':'white','axes.facecolor':'white','font.size':10}):
        keys=list(dict.fromkeys(k for r in records.values() for k in r.get('metric_records',{})))
        for key in keys:
            fig,ax=plt.subplots(figsize=(11,3.5),layout='constrained');plotted=False
            for name,r in records.items():
                path=output/scope/name/(key+'_errors.csv')
                if not path.is_file():continue
                rows=read_dicts(path)
                if not rows:continue
                unit=r['metric_units'][key];factor=100 if unit=='m' else 1
                x=np.array([(int(v['end_ns'])-origin)*1e-9 for v in rows])
                y=np.array([float(v['error_'+unit])*factor for v in rows])
                x,y=broken(x,y,np.array([int(v['segment']) for v in rows]))
                s=r['metrics'][key];b=base(name)
                ax.plot(x,y,color=COLORS[b],ls=STYLES[b],lw=1,
                        label=f"{LABELS.get(name,name)}: RMSE {s['rmse']*factor:.3f}, P95 {s['p95']*factor:.3f}")
                plotted=True
            if plotted:
                ax.set(xlabel='Seconds since first input group',ylabel='Error ('+('cm' if unit=='m' else 'deg')+')',title=scope+' / '+key,ylim=(0,None))
                ax.grid(alpha=.2);ax.legend(fontsize=8);fig.savefig(dest/(key+'.png'),dpi=150)
            plt.close(fig)
        fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained');gt_drawn=False
        for name,r in records.items():
            folder=output/scope/name;p=folder/'estimate_aligned.tum'
            if not p.is_file():continue
            ts=timestamps(p);labels=np.array(json.loads((folder/'segments.json').read_text()))
            x,pos=broken((ts-origin)*1e-9,np.loadtxt(p,ndmin=2)[:,1:4],labels)
            b=base(name)
            for i,ax in enumerate(axes.flat):
                ax.plot(pos[:,0] if i==3 else x,pos[:,2] if i==3 else pos[:,i],color=COLORS[b],ls=STYLES[b],lw=1,label=LABELS.get(name,name))
            if not gt_drawn:
                _,gt=broken((ts-origin)*1e-9,np.loadtxt(folder/'mocap_at_vio.tum',ndmin=2)[:,1:4],labels)
                for i,ax in enumerate(axes.flat):ax.plot(gt[:,0] if i==3 else x,gt[:,2] if i==3 else gt[:,i],color='#333333',ls=':',lw=1.3,label='Mocap GT')
                gt_drawn=True
        if gt_drawn:
            for i,ax in enumerate(axes.flat):
                ax.set(xlabel='World X (m)' if i==3 else 'Seconds since first input',ylabel='World '+('Z' if i==3 else 'XYZ'[i])+' (m)');ax.grid(alpha=.2);ax.legend(fontsize=8)
                if i==3:ax.set_aspect('equal',adjustable='datalim')
            fig.suptitle(scope+' body trajectories; Y up, XZ horizontal; no scale correction')
            fig.savefig(dest/'trajectories.png',dpi=150)
        plt.close(fig)

def compare(run):
    run=Path(run);m=manifest(run);output=run/'04_vio_comparison';output.mkdir(parents=True,exist_ok=True)
    if (output/'summary/summary.json').exists():raise ValueError('Existing comparison; use a new --from-run run')
    profile=m['parameters']['evaluation_profile']
    prep=json.loads((run/'01_preparation/outputs/preparation.json').read_text());origin=prep['first_corrected_ns']
    summary=json.loads((run/'03_vio/outputs/summary.json').read_text());online=summary['online']
    frames=read_dicts(run/'03_vio/outputs/replay/frames.csv');end=int(frames[-1]['corrected_ns']) if frames else prep['last_corrected_ns']
    gt=run/'02_reference/inputs/groundtruth/data.csv'
    tracks={name:load_trajectory(run/'02_reference/inputs'/(name+'_trajectory.csv')) for name in m['algorithms'] if name!='openmavis'}
    tracks={name:[p for p in rows if origin<=p[0]<=end] for name,rows in tracks.items()}
    if online['common_eligible']:
        tracks={'openmavis':load_trajectory(run/'03_vio/outputs/online/trajectory_euroc.csv'),**tracks}
    else:
        for p in sorted((run/'03_vio/outputs/online/coordinate_segments').glob('*/trajectory_euroc.csv')):
            tracks['openmavis_epoch_'+p.parent.name]=load_trajectory(p)
    result=dict(profile=profile,alignment='Initial valid 1 s mean pose SE(3)' if profile=='static' else 'Full matched position SE(3)',
        scale_corrected=False,origin_ns=origin,evaluation_window_ns=[origin,end],native={},common={},
        common_timestamps=dict(status='unavailable',n=0),quality_status='NOT_GATED',mocap_acquisition_qa='See frozen acquisition QA in batch report',
        time_offset='Frozen per-recording IMU/body GT; no refit or repeated transform',
        trajectory_policy='Online snapshots only; OpenMAVIS OK + IMU initialized; initialized coordinate segments never stitched',
        imu_policy_note='OpenMAVIS/OKVIS2 raw IMU, zero initial bias and online estimation; Basalt reference applies fixed calibration then estimates residual bias',
        continuity_policy='Union of all native GT boundaries, output gaps >1.8 median periods, available reset evidence',
        reset_evidence={'basalt':'Frozen basalt_states.csv if available','okvis':'No explicit reset stream; timestamp gaps checked','openmavis':'Online audit, coordinate epochs and timestamp gaps'})
    labels_by_name={};matched={}
    for name,poses in tracks.items():
        folder=output/'native'/name
        if not poses:
            result['native'][name]=unavailable('Empty trajectory');labels_by_name[name]={};matched[name]=[];continue
        write_trajectory(poses,folder)
        try:info=interpolate(gt,folder/'trajectory.tum',folder)
        except ValueError as error:
            if 'Fewer than 5 valid' not in str(error):raise
            result['native'][name]=unavailable(str(error));labels_by_name[name]={};matched[name]=[];continue
        ts=timestamps(folder/'vio_matched.tum')
        states=run/'02_reference/inputs/basalt_states.csv' if name=='basalt' else None
        labels=segment_labels(ts,gt,states);labels_by_name[name]=dict(zip(map(int,ts),map(int,labels)))
        accepted=set(map(int,ts));matched[name]=[p for p in poses if p[0] in accepted]
        record=evaluate(folder,profile,labels);record['interpolation']=info
        result['native'][name]=record;dump(folder/'metrics.json',record)
    if not online['common_eligible']:
        reason='OpenMAVIS has zero or multiple initialized coordinate segments; no selection/stitching'
        result['native'].setdefault('openmavis',unavailable(reason));result['common_timestamps']['reason']=reason
    else:
        common=sorted(set.intersection(*(set(labels_by_name[n]) for n in m['algorithms'])))
        result['common_timestamps'].update(n=len(common),first_ns=common[0] if common else None,last_ns=common[-1] if common else None)
        if len(common)<5:result['common_timestamps']['reason']='Fewer than five exact common GT-matchable timestamps'
        else:
            labels=common_labels(common,labels_by_name);selected=set(common)
            for name in m['algorithms']:
                folder=output/'common'/name;write_trajectory([p for p in matched[name] if p[0] in selected],folder)
                info=interpolate(gt,folder/'trajectory.tum',folder)
                if list(map(int,timestamps(folder/'vio_matched.tum')))!=common:raise ValueError('Common timestamp drift')
                record=evaluate(folder,profile,labels);record['interpolation']=info;result['common'][name]=record;dump(folder/'metrics.json',record)
            records=list(result['common'].values())
            if all(r.get('metrics') for r in records):
                gt_hashes={sha(output/'common'/name/'mocap_at_vio.tum') for name in m['algorithms']}
                if len(gt_hashes)!=1:raise ValueError('Common GT differs')
                for key,metric in records[0]['metric_records'].items():
                    if len({r['metric_records'][key]['pairs_sha256'] for r in records})!=1:raise ValueError('Common frame pairs differ: '+key)
                result['common_pairs_verified']=True;result['common_timestamps']['status']='available'
            else:result['common_timestamps']['reason']='Insufficient alignment motion'
    result['evaluator_sources']={p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('poc_metrics.py'),Path(__file__).with_name('poc_metrics_origin.json'),Path(__file__).with_name('interpolate_mocap_to_vio.py')]}
    dump(output/'summary/summary.json',result)
    for scope in ['common','native']:
        if result[scope]:plot_scope(output,scope,result[scope],origin)
    return result
