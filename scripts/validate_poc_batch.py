#!/usr/bin/env python3
"""Independent audit of saved scalar statistics, frame pairs, poses and HTML assets."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from vio_artifacts import dump, sha, read_dicts
from capture_pipeline_common import ns_seconds
from vio_sources import verify_sources

def tum(path):
    ts=[];poses=[]
    for row in path.read_text().splitlines():
        if not row.strip() or row.startswith('#'):continue
        values=row.split();ts.append(ns_seconds(values[0],allow_rounding=True));v=np.array(list(map(float,values[1:])))
        T=np.eye(4);T[:3,:3]=Rotation.from_quat(v[3:]).as_matrix();T[:3,3]=v[:3];poses.append(T)
    return ts,poses

def validate(root,partial=False):
    root=Path(root).resolve();state=json.loads((root/'state.json').read_text());checks=[];metric_count=0;scalar_count=0;pair_count=0;images=0
    protected=json.loads((root/'protected_inputs.json').read_text());verify_sources(protected)
    for name,record in state['runs'].items():
        if record['status'] not in ('complete','diagnostic_complete'):
            if partial:continue
            raise AssertionError('Incomplete run: '+name)
        run=Path(record['run']);s=json.loads((run/'03_vio/outputs/summary.json').read_text())
        c=json.loads((run/'04_vio_comparison/summary/summary.json').read_text())
        assert s['input_frames']==s['processed_frames'],name
        rows=read_dicts(run/'03_vio/outputs/replay/frames.csv')
        assert all(int(r['corrected_ns'])-int(r['raw_ns'])==5449054 for r in rows),name
        online=read_dicts(run/'03_vio/outputs/replay/online_body.csv')
        assert len(online)==len(rows)
        assert all(r['vio_only']=='1' and r['loop_enabled']=='0' and all(int(r[k])==0 for k in ['loop_corrections','merge_corrections','loop_gba_runs']) for r in online)
        accepted=[r for r in online if r['pose_valid']=='1' and r['imu_initialized']=='1' and r['state']=='2']
        assert len(accepted)==s['online']['accepted_poses']
        pairs_by_metric={};common_times=[];common_gt=[]
        for scope in ['native','common']:
            for algorithm,metrics in c[scope].items():
                folder=run/'04_vio_comparison'/scope/algorithm
                if not metrics.get('metrics'):continue
                ts,gt=tum(folder/'mocap_at_vio.tum');et,est=tum(folder/'estimate_aligned.tum');assert ts==et
                indices={t:i for i,t in enumerate(ts)};labels=json.loads((folder/'segments.json').read_text())
                if scope=='common':common_times.append(ts);common_gt.append(sha(folder/'mocap_at_vio.tum'))
                for metric,stats in metrics['metrics'].items():
                    unit=metrics['metric_units'][metric];errors=read_dicts(folder/(metric+'_errors.csv'))
                    values=np.array([float(r['error_'+unit]) for r in errors]);assert len(values)==stats['n']
                    expected={'rmse':float(np.sqrt(np.mean(values**2))),'p95':float(np.quantile(values,.95)),
                              'mean':float(np.mean(values)),'median':float(np.median(values)),'std':float(np.std(values)),
                              'min':float(np.min(values)),'max':float(np.max(values)),'sse':float(values@values)}
                    for key,value in expected.items():
                        assert np.isclose(value,stats[key],rtol=1e-11,atol=1e-12),(name,scope,algorithm,metric,key)
                        scalar_count+=1
                    pair_text=''.join(f"{r['start_ns']},{r['end_ns']}\n" for r in errors)
                    digest=hashlib.sha256(pair_text.encode()).hexdigest()
                    assert digest==metrics['metric_records'][metric]['pairs_sha256']
                    if scope=='common':pairs_by_metric.setdefault(metric,[]).append(digest)
                    for row in errors:
                        i,j=indices[int(row['start_ns'])],indices[int(row['end_ns'])]
                        assert labels[i]==labels[j]==int(row['segment'])
                    # Reconstruct selected pose errors independently from saved aligned poses.
                    for index in sorted({0,len(errors)//2,len(errors)-1}):
                        row=errors[index];i,j=indices[int(row['start_ns'])],indices[int(row['end_ns'])]
                        if metric.startswith(('ape_','are_')):
                            E=np.linalg.inv(gt[j])@est[j]
                        else:
                            E=np.linalg.inv(np.linalg.inv(gt[i])@gt[j])@(np.linalg.inv(est[i])@est[j])
                        expected_error=float(np.linalg.norm(E[:3,3])) if unit=='m' else float(np.rad2deg(Rotation.from_matrix(E[:3,:3]).magnitude()))
                        assert np.isclose(expected_error,values[index],rtol=1e-7,atol=1e-9),(name,algorithm,metric,expected_error,values[index])
                    metric_count+=1;pair_count+=len(errors)
        if c['common_timestamps']['status']=='available':
            assert len(common_times)==3 and all(t==common_times[0] for t in common_times)
            assert len(common_times[0])==c['common_timestamps']['n'] and len(set(common_gt))==1
            assert all(len(v)==3 and len(set(v))==1 for v in pairs_by_metric.values())
        for report in [run/'report/index.html']:
            page=report.read_text()
            assert not re.search(r'<(?:img|script)[^>]+src=["\']https?://',page)
            for raw in re.findall(r'src="data:image/[^;]+;base64,([^\"]+)"',page):
                with Image.open(io.BytesIO(base64.b64decode(raw))) as im:im.verify()
                images+=1
        checks.append(dict(scene=name,frames=len(rows),accepted=len(accepted),common=c['common_timestamps'],tracking=s['acceptance']))
    report=root/'report/index.html'
    if report.exists():
        page=report.read_text()
        for raw in re.findall(r'src="data:image/[^;]+;base64,([^\"]+)"',page):
            with Image.open(io.BytesIO(base64.b64decode(raw))) as im:im.verify()
            images+=1
        generation=json.loads((root/'report/generation.json').read_text())
        verify_sources(generation['source_sha256'])
    result=dict(status='PASS',partial=partial,runs=checks,protected_files=len(protected),metric_arrays=metric_count,
                verified_scalars=scalar_count,verified_error_rows=pair_count,decoded_embedded_images=images,
                browser_rendering='Not tested: browser URL policy rejected file://; static structure and image validation only')
    dump(root/('validation_partial.json' if partial else 'validation.json'),result);print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--batch',type=Path,required=True);ap.add_argument('--partial',action='store_true')
    a=ap.parse_args();validate(a.batch,a.partial)
