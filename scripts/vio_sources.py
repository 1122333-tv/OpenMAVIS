"""Import frozen Basalt/OKVIS artifacts without executing either project."""
import json
import shutil
from pathlib import Path
import yaml
from vio_artifacts import sha, dump, load_trajectory, csv_rows

def choose(root,*names):
    paths=[root/n for n in names if (root/n).is_file()]
    if not paths: raise ValueError('Missing source artifact: '+str(root)+' / '+', '.join(names))
    if len({sha(p) for p in paths})>1: raise ValueError('Conflicting source artifacts: '+str(paths))
    return paths[0]

def stage(root,m,name,default):
    s=m.get('stages',{}).get(name,{})
    if s.get('status') not in ('complete','reused'): raise ValueError('Source prerequisite incomplete: '+name)
    path=(root/s.get('directory',default)).resolve()
    if root not in path.parents: raise ValueError('Source stage escapes run')
    return path

def inspect(root,kind):
    root=Path(root).resolve()
    try:m=yaml.safe_load((root/'manifest.yaml').read_text())
    except (OSError,yaml.YAMLError) as e:raise ValueError('Source manifest unavailable or invalid: '+str(root)) from e
    if not isinstance(m,dict):raise ValueError('Invalid source manifest mapping: '+str(root))
    files={root/'manifest.yaml':kind+'_manifest.yaml'}
    if kind=='basalt':
        prep=stage(root,m,'prepare','01_preparation'); ref=stage(root,m,'gt','02_mocap_alignment'); vio=stage(root,m,'vio','03_vio')
        preparation=choose(prep,'preparation.json','outputs/preparation.json'); p=json.loads(preparation.read_text())
        dataset=next((d for d in [prep/'dataset',prep/'outputs/dataset'] if (d/'mav0').is_dir()),None)
        identity=m.get('dataset') or m.get('parameters',{}).get('dataset')
        if not identity or not p.get('source') or Path(identity).resolve()!=Path(p['source']).resolve(): raise ValueError('Dataset identity mismatch')
        cal=choose(prep,'inputs/calibration.json','calibration.json','outputs/calibration.json')
        export=choose(prep,'inputs/delivery/export_manifest.json','inputs/export_manifest.json','export_manifest.json')
        gt=choose(ref,'state_groundtruth_estimate0/data.csv','outputs/state_groundtruth_estimate0/data.csv')
        basalt=choose(vio,'outputs/oak4p_trajectory.csv','oak4p_trajectory.csv'); algorithms={'basalt':basalt}
        files.update({gt:'groundtruth/data.csv',gt.with_name('conversion.json'):'groundtruth/conversion.json',basalt:'basalt_trajectory.csv'})
        for n in ['total_offset.json','time_alignment.json']:
            candidate=next((ref/sub/n for sub in ['time_alignment','outputs/time_alignment'] if (ref/sub/n).is_file()),None)
            if candidate: files[candidate]='time_alignment/'+n
    else:
        if m.get('format')!='okvis-vio' or m.get('version')!=2: raise ValueError('Only OKVIS version-2 runs supported')
        prep=stage(root,m,'prepare','01_preparation'); ref=stage(root,m,'reference','02_reference'); vio=stage(root,m,'vio','03_vio')
        preparation=choose(prep,'outputs/preparation.json'); p=json.loads(preparation.read_text())
        dataset=prep/'outputs/dataset'; identity=m.get('parameters',{}).get('dataset')
        bp=json.loads(choose(prep,'inputs/basalt_preparation.json').read_text())
        if not identity or Path(bp['source']).resolve()!=Path(identity).resolve(): raise ValueError('OKVIS/Basalt dataset identity mismatch')
        if p['cam_time_offset_ns']!=bp['cam_time_offset_ns']: raise ValueError('OKVIS/Basalt offset mismatch')
        cal=choose(prep,'outputs/calibration.json'); export=choose(prep,'inputs/export_manifest.json')
        gt=choose(ref,'inputs/groundtruth/data.csv'); basalt=choose(ref,'inputs/basalt_trajectory.csv')
        algorithms={'basalt':basalt,'okvis':choose(vio,'outputs/trajectory_euroc.csv')}
        for path in sorted((ref/'inputs').rglob('*')):
            if path.is_file():files[path]=str(path.relative_to(ref/'inputs'))
        files[algorithms['okvis']]='okvis_trajectory.csv'
        files[choose(prep,'inputs/basalt_preparation.json')]='basalt_preparation.json'
        for key,h in p.get('index_sha256',{}).items():
            if sha(dataset/'mav0'/key/'data.csv')!=h: raise ValueError('OKVIS CSV snapshot hash mismatch: '+key)
        for s in ['prepare','reference','vio']:
            d=root/m['stages'][s]['directory']
            relevant={str(cal.relative_to(d))} if s=='prepare' else ({str(algorithms['okvis'].relative_to(d))} if s=='vio' else set(m['stages'][s].get('artifact_sha256',{})))
            for name in relevant:
                expected=m['stages'][s].get('artifact_sha256',{}).get(name)
                if expected and sha(d/name)!=expected: raise ValueError('Source snapshot changed: '+name)
    if dataset is None or not (dataset/'mav0').is_dir(): raise ValueError('Missing/broken prepared dataset')
    if (dataset/'mav0/cam0/data.csv').is_file():
        image_rows=csv_rows(dataset/'mav0/cam0/data.csv')
        expected=p.get('reference_transfer_first_timestamp_ns',p.get('first_camera_timestamp_ns'))
        if expected is not None and (not image_rows or int(image_rows[0][0])!=expected):
            raise ValueError('Prepared image timestamps differ from grouping record (possible repeated shift)')
        if p.get('groups') is not None and len(image_rows)!=p['groups']:raise ValueError('Prepared group count differs from source record')
    if type(p.get('cam_time_offset_ns')) is not int: raise ValueError('Missing integer camera offset')
    c=json.loads(cal.read_text())['value0']; e=json.loads(export.read_text())
    if e.get('schema_version')!=1 or e.get('camera_order')!=['cam0','cam1','cam2','cam3']: raise ValueError('Physical camera order/schema not confirmed')
    if p.get('group_time_reference') and p.get('calibration_time_reference') and p['group_time_reference']!=p['calibration_time_reference'] and 'reference_offset_adjustment_ns' not in p:
        raise ValueError('Missing group-reference time transfer')
    adjustment=p.get('reference_offset_adjustment_ns',0)
    if c['cam_time_offset_ns']!=p['cam_time_offset_ns'] and c['cam_time_offset_ns']+adjustment!=p['cam_time_offset_ns']:
        raise ValueError('Calibration/group time offset conflicts')
    if not gt.with_name('conversion.json').is_file() or not json.loads(gt.with_name('conversion.json').read_text()).get('valid_segments_ns'):
        raise ValueError('Missing GT valid-segment conversion metadata')
    ground=load_trajectory(gt)
    for path in algorithms.values():
        poses=load_trajectory(path)
        if max(poses[0][0],ground[0][0])>=min(poses[-1][0],ground[-1][0]):raise ValueError('Reference trajectories do not overlap IMU GT')
    files.update({preparation:'preparation.json',cal:'calibration.json',export:'export_manifest.json'})
    records={str(path):sha(path) for path in files}
    return dict(root=root,kind=kind,manifest=m,preparation=p,dataset=dataset.resolve(),identity=str(identity),calibration=cal,export=export,gt=gt,algorithms=algorithms,files=files,source_hashes=records,offset=p['cam_time_offset_ns'])

def import_reference(info,directory):
    records={}
    for source,relative in info['files'].items():
        target=Path(directory)/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        records[relative]=dict(source=str(source),sha256=sha(source))
    dump(Path(directory)/'sources.json',dict(files=records,gt_policy='Imported unchanged; no time or pose transform'))

def verify_sources(records):
    for path,h in records.items():
        if sha(path)!=h: raise ValueError('Source changed during run: '+path)
