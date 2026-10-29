"""Exact four-KB4 conversion using the existing repaired algorithm template."""
import json
import math
from pathlib import Path
import numpy as np
import yaml
from vio_artifacts import sha, dump

class Matrix(dict): pass
class Loader(yaml.SafeLoader): pass
class Dumper(yaml.SafeDumper): pass
Loader.add_constructor('tag:yaml.org,2002:opencv-matrix',lambda loader,node:Matrix(loader.construct_mapping(node,deep=True)))
Dumper.add_representer(Matrix,lambda dumper,m:dumper.represent_mapping('tag:yaml.org,2002:opencv-matrix',m))

def load_settings(path): return yaml.load('\n'.join(s for s in Path(path).read_text().splitlines() if not s.startswith('%YAML:')),Loader=Loader)

def pose_matrix(p):
    q=np.array([p[k] for k in ['qx','qy','qz','qw']],float)
    if not np.isfinite(q).all() or abs(np.linalg.norm(q)-1)>1e-5: raise ValueError('Invalid calibration quaternion')
    x,y,z,w=q/np.linalg.norm(q);T=np.eye(4)
    T[:3,:3]=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
    T[:3,3]=[p[k] for k in ['px','py','pz']]
    if not np.isfinite(T).all(): raise ValueError('Nonfinite calibration transform')
    return T

def convert(calibration,template,output,offset,fps,imu_bias_policy='require-zero'):
    c=json.loads(Path(calibration).read_text())['value0']; cfg=load_settings(template)
    if any(len(c[k])!=4 for k in ['intrinsics','T_imu_cam','resolution']): raise ValueError('Four physical cameras required')
    if any(r!=c['resolution'][0] for r in c['resolution']): raise ValueError('Different camera resolutions unsupported')
    if any(type(v)!=int or v<=0 for v in c['resolution'][0]): raise ValueError('Invalid resolution')
    if imu_bias_policy not in ('require-zero','estimate-from-zero'):
        raise ValueError('Unknown IMU bias policy: '+imu_bias_policy)
    for key,size in [('calib_accel_bias',9),('calib_gyro_bias',12)]:
        if len(c[key])!=size or not all(math.isfinite(v) for v in c[key]):
            raise ValueError('Invalid IMU correction: '+key)
        if any(v!=0 for v in c[key][3:]):
            raise ValueError('Nonzero IMU scale/misalignment correction unsupported: '+key)
        if imu_bias_policy=='require-zero' and any(v!=0 for v in c[key]):
            raise ValueError('Nonzero IMU correction unsupported: '+key)
    transforms=[]
    for i,intr in enumerate(c['intrinsics']):
        if intr['camera_type']!='kb4': raise ValueError('Only exact KB4 conversion supported')
        a=intr['intrinsics']
        for k in ['fx','fy','cx','cy','k1','k2','k3','k4']:
            if not math.isfinite(a[k]): raise ValueError('Nonfinite camera intrinsic')
            cfg[f'Camera{i+1}.{k}']=float(a[k])
        if a['fx']<=0 or a['fy']<=0: raise ValueError('Nonpositive focal length')
        cfg[f'Camera{i+1}.overlappingBegin']=0;cfg[f'Camera{i+1}.overlappingEnd']=c['resolution'][0][0]
        transforms.append(pose_matrix(c['T_imu_cam'][i]))
    matrices={'Stereo.T_c1_c2':np.linalg.inv(transforms[0])@transforms[1],**{f'IMU.T_b_c{i+1}':transforms[i] for i in [0,2,3]}}
    for k,T in matrices.items():cfg[k]=Matrix(rows=4,cols=4,dt='f',data=T.reshape(-1).tolist())
    for source,target in [('gyro_noise_std','IMU.NoiseGyro'),('accel_noise_std','IMU.NoiseAcc'),('gyro_bias_std','IMU.GyroWalk'),('accel_bias_std','IMU.AccWalk')]:
        v=c[source]
        if len(v)!=3 or len(set(v))!=1 or not all(math.isfinite(x) and x>0 for x in v): raise ValueError('Positive isotropic noise required: '+source)
        cfg[target]=float(v[0])
    if not math.isfinite(c['imu_update_rate']) or c['imu_update_rate']<=0: raise ValueError('Invalid IMU frequency')
    cfg.update({'Camera.type':'KannalaBrandt8','Camera.width':c['resolution'][0][0],'Camera.height':c['resolution'][0][1],'Camera.fps':int(fps),'Camera.RGB':0,'IMU.Frequency':c['imu_update_rate'],'System.VIOOnly':1,'loopClosing':0,'System.LoadAtlasFromFile':'','System.SaveAtlasToFile':''})
    if type(offset)!=int or abs(offset)>=100_000_000 or fps<1: raise ValueError('Invalid timing')
    Path(output).write_text('%YAML:1.0\n---\n'+yaml.dump(cfg,Dumper=Dumper,sort_keys=False,default_flow_style=None))
    report=dict(calibration_sha256=sha(calibration),template_sha256=sha(template),camera_order=['cam0','cam1','cam2','cam3'],cam_time_offset_ns=offset,
                imu_bias_policy=imu_bias_policy,
                imu_correction=dict(source_accel=c['calib_accel_bias'],source_gyro=c['calib_gyro_bias'],
                    fixed_bias_applied=False,raw_samples_unchanged=True,initial_accel_bias=[0.,0.,0.],
                    initial_gyro_bias=[0.,0.,0.],online_bias_estimation=True,
                    implementation='Tracking constructs IMU::Bias(); LocalMapping estimates inertial biases'),
                transform_equation='T_b_c = camera -> physical IMU; Stereo = inverse(T_b_c0) * T_b_c1',matrices={k:T.tolist() for k,T in matrices.items()},fps=int(fps),filter_policy='OpenMAVIS valid-ray feature filter; reference algorithms retain their saved mask policies')
    dump(Path(output).with_name('calibration_conversion.json'),report);return report
