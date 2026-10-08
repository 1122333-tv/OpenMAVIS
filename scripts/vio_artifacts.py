"""Local canonical trajectory IO and immutable pipeline artifacts."""
import csv
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from decimal import Decimal
import yaml

ROOT = Path(__file__).resolve().parents[1]
STAGES = dict(prepare='01_preparation', reference='02_reference', vio='03_vio', compare='04_vio_comparison', report='report')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def dynamic_libraries(binary):
    """Freeze resolved Linux loader dependencies, including transitive libraries."""
    listing=subprocess.check_output(['ldd',str(binary)],text=True)
    if 'not found' in listing:raise ValueError('Unresolved dynamic library: '+listing)
    paths=set(re.findall(r'=> (/.+?) \(',listing))|set(re.findall(r'^\s*(/\S+) \(',listing,re.MULTILINE))
    if not paths:raise ValueError('No resolved dynamic dependencies')
    return dict(ldd=listing,files={p:dict(resolved=str(Path(p).resolve()),sha256=sha(p)) for p in sorted(paths)})

def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n'); temp.replace(path)

def csv_rows(path):
    with Path(path).open(newline='') as stream:
        return list(csv.reader(line for line in stream if line.strip() and not line.lstrip().startswith('#')))

def load_trajectory(path):
    result = []
    for row in csv_rows(path):
        if len(row) < 8: raise ValueError('Expected ns xyz wxyz: '+str(path))
        t = int(row[0]); v = list(map(float, row[1:8]))
        if not all(math.isfinite(x) for x in v) or abs(sum(x*x for x in v[3:])-1)>1e-5:
            raise ValueError('Invalid finite/unit body pose: '+str(path))
        if result and t <= result[-1][0]: raise ValueError('Non-increasing trajectory: '+str(path))
        result.append((t, v))
    if not result: raise ValueError('Empty trajectory: '+str(path))
    return result

def seconds(ns):
    sign = '-' if ns < 0 else ''; s, n = divmod(abs(ns), 1_000_000_000)
    return f'{sign}{s}.{n:09d}'

def write_trajectory(rows, directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory/'trajectory_euroc.csv').open('w') as stream:
        stream.write('#timestamp [ns],px,py,pz,qw,qx,qy,qz\n')
        writer = csv.writer(stream); writer.writerows([t, *v] for t,v in rows)
    with (directory/'trajectory.tum').open('w') as stream:
        for t,v in rows: stream.write(seconds(t)+' '+' '.join(format(x,'.17g') for x in [*v[:3],*v[4:],v[3]])+'\n')

def manifest(root):
    m = yaml.safe_load((Path(root)/'manifest.yaml').read_text())
    if not isinstance(m,dict) or m.get('format')!='openmavis-vio' or m.get('version')!=1:
        raise ValueError('Unsupported OpenMAVIS run')
    return m

def hashes(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file() and not p.is_symlink()}

def read_dicts(path):
    with Path(path).open(newline='') as stream: return list(csv.DictReader(stream))

def normalize_online(source, output):
    rows = read_dicts(source); selected = {}; excluded = {}; previous = None; epoch = 0
    audit = []
    for index,row in enumerate(rows):
        t = int(row['corrected_ns'])
        if int(row['frame'])!=index or previous and t<=int(previous['corrected_ns']):
            raise ValueError('Online frame sequence/time mismatch')
        if previous and (row['map_id']!=previous['map_id'] or row['resets']!=previous['resets'] or
                         previous['imu_initialized']=='1' and row['imu_initialized']=='0'): epoch += 1
        previous = row
        if row['vio_only']!='1' or row['loop_enabled']!='0' or any(int(row[k]) for k in ['loop_corrections','merge_corrections','loop_gba_runs']):
            raise ValueError('Runtime VIO lock/correction evidence failed')
        reason = ('no_pose' if row['pose_valid']!='1' else 'imu_not_initialized' if row['imu_initialized']!='1'
                  else 'not_OK' if row['state']!='2' else 'accepted')
        if row['pose_valid']=='1':
            pose = [float(row[k]) for k in ['tx','ty','tz','qw','qx','qy','qz']]
            if not all(math.isfinite(v) for v in pose) or abs(sum(v*v for v in pose[3:])-1)>1e-5:
                raise ValueError('Invalid online body pose')
        audit.append(dict(frame=index,timestamp_ns=t,coordinate_epoch=epoch,reason=reason))
        if reason=='accepted': selected.setdefault(epoch,[]).append((t,pose))
        else: excluded[reason] = excluded.get(reason,0)+1
    for epoch,poses in selected.items(): write_trajectory(poses,Path(output)/'coordinate_segments'/str(epoch))
    if len(selected)==1: write_trajectory(next(iter(selected.values())),output)
    summary = dict(input_rows=len(rows),accepted_poses=sum(map(len,selected.values())),excluded=excluded,
                   initialized_coordinate_segments=len(selected),coordinate_segments={str(k):len(v) for k,v in selected.items()},
                   common_eligible=len(selected)==1,mode='online body -> current world; integer corrected_ns; OK and IMU initialized only',
                   runtime_vio_lock_verified=bool(rows))
    dump(Path(output)/'online_audit.json',audit); dump(Path(output)/'trajectory_summary.json',summary)
    return summary

def normalize_final(source, frames, output):
    """Recover only the unique original frame behind microsecond export rounding."""
    import bisect
    times=[int(r['corrected_ns']) for r in read_dicts(frames)]; seen=set(); poses=[]; audit=[]
    if not times or any(a>=b for a,b in zip(times,times[1:])): raise ValueError('Invalid frame times')
    for line in Path(source).read_text().splitlines():
        if not line.strip() or line.startswith('#'): continue
        values=line.split()
        if len(values)!=8: raise ValueError('Expected final body TUM pose')
        d=Decimal(values[0])*1_000_000_000
        if not d.is_finite(): raise ValueError('Nonfinite final timestamp')
        t=int(d.to_integral_value()); j=bisect.bisect_left(times,t)
        candidates=[i for i in (j-1,j) if 0<=i<len(times) and abs(times[i]-t)<=501]
        if len(candidates)!=1 or candidates[0] in seen: raise ValueError('Ambiguous/duplicate/unmatched final timestamp')
        i=candidates[0]; seen.add(i); v=list(map(float,values[1:])); v=v[:3]+[v[6],*v[3:6]]
        if not all(math.isfinite(x) for x in v) or abs(sum(x*x for x in v[3:])-1)>1e-5: raise ValueError('Invalid final pose')
        if poses and times[i]<=poses[-1][0]: raise ValueError('Non-increasing final time')
        poses.append((times[i],v));audit.append(dict(exported_ns=t,corrected_ns=times[i],residual_ns=times[i]-t,frame=i))
    write_trajectory(poses,output);dump(Path(output)/'time_recovery.json',audit)
    return len(poses)
