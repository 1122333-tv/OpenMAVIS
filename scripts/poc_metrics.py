"""Frozen POC metric core adapted from OKVIS2; see poc_metrics_origin.json.

This module never imports or executes either reference project.
"""
import copy
import csv
import json
import hashlib
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from evo.core import filters, metrics, result
from evo.tools import file_interface
from capture_pipeline_common import ns_seconds
from vio_artifacts import dump as save, seconds as tum_time


def statistics(errors):
    x=np.asarray(errors,dtype=float)
    if not len(x):return None
    if not np.isfinite(x).all():raise ValueError('Non-finite metric errors')
    return dict(n=len(x),rmse=float(np.sqrt(np.mean(x*x))),mean=float(x.mean()),
                median=float(np.median(x)),std=float(x.std()),min=float(x.min()),
                max=float(x.max()),p95=float(np.quantile(x,.95)),p99=float(np.quantile(x,.99)),sse=float(x@x))


def timestamps(path):
    return np.array([ns_seconds(line.split()[0],allow_rounding=True)
                     for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')],dtype=np.int64)


def time_pairs(ts,delta,tolerance=.1):
    """Nearest endpoint to each start+delta; relative tolerance, integer ns."""
    step=round(delta*1e9);out=[]
    for i,t in enumerate(ts[:-1]):
        k=int(np.searchsorted(ts,t+step))
        candidates=[j for j in (k-1,k) if i<j<len(ts)]
        if not candidates:continue
        j=min(candidates,key=lambda j:abs(int(ts[j]-t)-step))
        if abs(int(ts[j]-t)-step)<=round(step*tolerance):out.append((i,j))
    return out


def segment_labels(ts,groundtruth,states=None):
    """Never form relative pairs across GT holes, missing output or state resets."""
    labels=np.zeros(len(ts),dtype=int)
    conv=groundtruth.with_name('conversion.json')
    spans=json.loads(conv.read_text()).get('valid_segments_ns',[]) if conv.exists() else []
    gt_labels=[]
    for t in ts:
        matches=[i for i,(a,b) in enumerate(spans) if a<=int(t)<=b]
        gt_labels.append(matches[0] if matches else -1)
    dt=np.diff(ts);nominal=int(np.median(dt)) if len(dt) else 0
    resets=[]
    if states and states.is_file():
        with states.open() as f:
            for r in csv.DictReader(f):
                if int(r.get('state_reset','0')):resets.append(int(r['timestamp_ns']))
    for i in range(1,len(ts)):
        split=(int(ts[i]-ts[i-1])>1.8*nominal or
               (bool(spans) and gt_labels[i]!=gt_labels[i-1]) or
               any(int(ts[i-1])<r<=int(ts[i]) for r in resets))
        labels[i]=labels[i-1]+int(split)
    return labels


def align(ref,est,ts,profile):
    est=copy.deepcopy(est)
    raw_cov=np.linalg.svd(np.cov(ref.positions_xyz.T),compute_uv=False)
    if profile=='static':
        ids=np.flatnonzero(ts-ts[0]<=1_000_000_000)
        rr=np.asarray([ref.poses_se3[i][:3,:3]@est.poses_se3[i][:3,:3].T for i in ids])
        r=Rotation.from_matrix(rr).mean().as_matrix()
        t=ref.positions_xyz[ids].mean(0)-r@est.positions_xyz[ids].mean(0)
        name='Initial common/native valid 1 s mean pose alignment; SE(3), no scale correction'
    else:
        r,t,s=est.align(ref,correct_scale=False)
        if abs(s-1)>1e-9:raise ValueError('Unexpected scale correction')
        return est,dict(method='Full matched-trajectory position SE(3) Umeyama; no scale correction',rotation=r.tolist(),translation=t.tolist(),reference_position_covariance_singular_values=raw_cov.tolist(),alignment_first_ns=int(ts[0]),alignment_last_ns=int(ts[-1]))
    tf=np.eye(4);tf[:3,:3]=r;tf[:3,3]=t;est.transform(tf)
    return est,dict(method=name,rotation=r.tolist(),translation=t.tolist(),reference_position_covariance_singular_values=raw_cov.tolist(),alignment_first_ns=int(ts[ids[0]]),alignment_last_ns=int(ts[ids[-1]]))


def metric_dir(name):
    if name=='ape_translation':return Path('ape')
    if name=='are_rotation':return Path('are')
    family,_,delta=name.split('_',2)
    return Path(family)/delta


def evaluate_matched(folder, profile, labels):
    """Evaluate already paired trajectories; all associations remain integer ns."""
    gt_file=folder/'mocap_at_vio.tum';est_file=folder/'vio_matched.tum'
    ts=timestamps(gt_file)
    if not np.array_equal(ts,timestamps(est_file)) or len(labels)!=len(ts):
        raise ValueError('Mismatched evaluation timestamps or continuity labels')
    ref=file_interface.read_tum_trajectory_file(gt_file)
    raw=file_interface.read_tum_trajectory_file(est_file)
    est,alignment=align(ref,raw,ts,profile)
    # Preserve exact timestamps when writing aligned poses, avoiding float epoch formatting.
    with (folder/'estimate_aligned.tum').open('w') as f:
        for t,p,q in zip(ts,est.positions_xyz,est.orientations_quat_wxyz):
            f.write(tum_time(int(t))+' '+' '.join(format(x,'.17g') for x in [*p,*q[1:],q[0]])+'\n')
    out=dict(alignment=alignment,metrics={},metric_units={},metric_records={},unavailable_metrics={},
             pairing=dict(segment_count=int(labels[-1]+1),
                          exclusions='GT invalid segments, output gaps >1.8 median periods, available state-reset events'))
    def emit(name,errors,unit,pairs,eligible=None):
        errors=np.asarray(errors,dtype=float);st=statistics(errors)
        endpoints=[(int(ts[i]),int(ts[j])) for i,j in pairs]
        digest=hashlib.sha256(''.join(f'{a},{b}\n' for a,b in endpoints).encode()).hexdigest()
        record=dict(status='OK' if st else 'NOT_APPLICABLE',unit=unit,stats=st,
                    pairs_sha256=digest,candidate_pairs=eligible,
                    rejected_pairs=eligible-len(pairs) if eligible is not None else None)
        out['metric_records'][name]=record;out['metric_units'][name]=unit
        if st:out['metrics'][name]=st
        else:out['unavailable_metrics'][name]='No valid pose pairs for this interval'
        with (folder/(name+'_errors.csv')).open('w') as f:
            w=csv.writer(f);w.writerow(['start_ns','end_ns','segment','error_'+unit])
            w.writerows((a,b,int(labels[j]),float(e)) for (a,b),(i,j),e in zip(endpoints,pairs,errors))
        save(folder/(name+'_extended_stats.json'),record)
        if st:
            res=result.Result();res.add_info(dict(title=name,label=name+' ('+unit+')'))
            res.add_stats(st);res.add_np_array('error_array',errors)
            file_interface.save_res_file(folder/(name+'.zip'),res,confirm_overwrite=False)
    for relation,name,unit in [(metrics.PoseRelation.translation_part,'ape_translation','m'),
                               (metrics.PoseRelation.rotation_angle_deg,'are_rotation','deg')]:
        metric=metrics.APE(relation);metric.process_data((ref,est))
        emit(name,metric.error,unit,[(i,i) for i in range(len(ts))])
    specs=[('0.1s',time_pairs(ts,.1)),('1s',time_pairs(ts,1.))]
    if profile=='motion':
        specs += [(f'{d:g}m',filters.filter_pairs_by_path(ref.poses_se3,d,d*.1,all_pairs=True)) for d in (.1,.5,1.)]
    for key,candidates in specs:
        pairs=[(i,j) for i,j in candidates if labels[i]==labels[j]]
        errors=[metrics.RPE.rpe_base(ref.poses_se3[i],ref.poses_se3[j],est.poses_se3[i],est.poses_se3[j]) for i,j in pairs]
        trans=[np.linalg.norm(e[:3,3]) for e in errors]
        angles=np.rad2deg(Rotation.from_matrix(np.array([e[:3,:3] for e in errors])).magnitude()) if errors else []
        emit('rpe_translation_'+key,trans,'m',pairs,len(candidates))
        emit('rre_rotation_'+key,angles,'deg',pairs,len(candidates))
    if profile=='static':
        pos=raw.positions_xyz;rs=Rotation.from_quat(raw.orientations_quat_wxyz[:,[1,2,3,0]])
        n0=np.flatnonzero(ts-ts[0]<=1e9);n1=np.flatnonzero(ts[-1]-ts<=1e9)
        out['static_stability']=dict(
            position_jitter_about_whole_run_mean_m=statistics(np.linalg.norm(pos-pos.mean(0),axis=1)),
            rotation_jitter_about_whole_run_mean_deg=statistics(np.rad2deg((rs.mean().inv()*rs).magnitude())),
            end_minus_start_mean_position_m=float(np.linalg.norm(pos[n1].mean(0)-pos[n0].mean(0))),
            end_minus_start_mean_rotation_deg=float(np.rad2deg((rs[n0].mean().inv()*rs[n1].mean()).magnitude())))
    return out


def common_labels(common, native):
    """Union of all algorithms' discontinuities on the common timestamps."""
    changes=np.zeros(max(0,len(common)-1),dtype=bool)
    for record in native.values():
        values=np.array([record[t] for t in common])
        changes |= np.diff(values)!=0
    return np.r_[0,np.cumsum(changes)].astype(int)
