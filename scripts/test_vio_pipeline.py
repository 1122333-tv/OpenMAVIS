import base64
import copy
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import yaml
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from vio_artifacts import dump, load_trajectory, normalize_online, normalize_final, write_trajectory, sha
from vio_sources import inspect, choose, verify_sources, import_reference
from convert_rig_to_openmavis import convert, load_settings, pose_matrix
from interpolate_mocap_to_vio import interpolate
from compare_vio_trajectories import evaluate, reference_pairs
from generate_vio_report import generate

REPO=Path(__file__).resolve().parents[1]

class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        import math
        self.cal={'value0':dict(intrinsics=[dict(camera_type='kb4',intrinsics=dict(fx=400+i*20,fy=410+i,cx=320,cy=240,k1=0,k2=0,k3=0,k4=0)) for i in range(4)],
          T_imu_cam=[dict(px=i*.2,py=.1,pz=.05,qw=math.cos(i*.15),qx=0,qy=0,qz=math.sin(i*.15)) for i in range(4)],
          resolution=[[640,480] for i in range(4)],calib_accel_bias=[0]*9,calib_gyro_bias=[0]*12,
          gyro_noise_std=[.000282]*3,accel_noise_std=[.016]*3,gyro_bias_std=[.0001]*3,accel_bias_std=[.001]*3,
          imu_update_rate=500,cam_time_offset_ns=2631359)}
        os.environ['MPLCONFIGDIR']=str(self.root/'plot_cache')
    def online(self,changes=None):
        rows=[dict(frame=i,corrected_ns=1000000359+i*33333000,pose_valid=1,imu_initialized=1,state=2,map_id=0,resets=0,vio_only=1,loop_enabled=0,loop_corrections=0,merge_corrections=0,loop_gba_runs=0,tx=i*.1,ty=0,tz=0,qw=1,qx=0,qy=0,qz=0) for i in range(6)]
        if changes:changes(rows)
        p=self.root/'online.csv'
        with p.open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
        return normalize_online(p,self.root/'online')
    def test_online_integer_time_and_status(self):
        result=self.online(lambda r:r[0].update(imu_initialized=0))
        self.assertEqual(result['accepted_poses'],5);self.assertEqual(load_trajectory(self.root/'online/trajectory_euroc.csv')[0][0],1033333359)
    def test_no_pose_and_not_ok_excluded(self):
        result=self.online(lambda r:(r[0].update(pose_valid=0),r[1].update(state=3)))
        self.assertEqual(result['excluded'],{'no_pose':1,'not_OK':1})
    def test_multiple_initialized_epochs_not_stitched(self):
        result=self.online(lambda r:[x.update(resets=1,map_id=2) for x in r[3:]])
        self.assertFalse(result['common_eligible']);self.assertEqual(result['initialized_coordinate_segments'],2);self.assertFalse((self.root/'online/trajectory_euroc.csv').exists())
    def test_initialization_loss_splits_epoch(self):
        result=self.online(lambda r:r[2].update(imu_initialized=0));self.assertEqual(result['initialized_coordinate_segments'],2)
    def test_runtime_loop_cannot_be_hidden(self):
        with self.assertRaisesRegex(ValueError,'VIO'):self.online(lambda r:r[3].update(loop_enabled=1))
    def test_nonfinite_online_rejected(self):
        with self.assertRaisesRegex(ValueError,'body pose'):self.online(lambda r:r[3].update(tx=float('nan')))
    def test_duplicate_online_time(self):
        with self.assertRaises(ValueError):self.online(lambda r:r[2].update(corrected_ns=r[1]['corrected_ns']))
    def final(self,times,export='1.000000'):
        f=self.root/'frames.csv';f.write_text('corrected_ns\n'+'\n'.join(map(str,times))+'\n')
        p=self.root/'final.txt';p.write_text(export+' 0 0 0 0 0 0 1\n');return normalize_final(p,f,self.root/'final')
    def test_microsecond_time_recovery(self):
        self.final([1000000359]);self.assertEqual(load_trajectory(self.root/'final/trajectory_euroc.csv')[0][0],1000000359)
    def test_microsecond_recovery_limit(self):
        with self.assertRaises(ValueError):self.final([1000000502])
    def test_ambiguous_recovery(self):
        with self.assertRaises(ValueError):self.final([999999900,1000000100])
    def test_duplicate_final_time(self):
        with self.assertRaises(ValueError):self.final([1000000000],export='1.000000 0 0 0 0 0 0 1\n1.000000')
    def conversion(self,mutate=None):
        c=copy.deepcopy(self.cal)
        if mutate:mutate(c['value0'])
        p=self.root/'calibration.json';dump(p,c);output=self.root/'settings.yaml'
        convert(p,REPO/'Examples/Multi-Inertial/OAK4P_layout0921_repaired.yaml',output,2631359,30)
        return load_settings(output)
    def test_transform_direction_and_different_cameras(self):
        cfg=self.conversion();c=self.cal['value0'];expected=np.linalg.inv(pose_matrix(c['T_imu_cam'][0]))@pose_matrix(c['T_imu_cam'][1])
        self.assertTrue(np.allclose(np.reshape(cfg['Stereo.T_c1_c2']['data'],(4,4)),expected));self.assertNotEqual(cfg['Camera1.fx'],cfg['Camera4.fx'])
        self.assertEqual(cfg['System.VIOOnly'],1);self.assertEqual(cfg['loopClosing'],0)
    def test_unsupported_camera_rejected(self):
        with self.assertRaisesRegex(ValueError,'KB4'):self.conversion(lambda c:c['intrinsics'][2].update(camera_type='eucm'))
    def test_anisotropic_noise_rejected(self):
        with self.assertRaisesRegex(ValueError,'isotropic'):self.conversion(lambda c:c.update(accel_noise_std=[1,2,3]))
    def test_nonzero_imu_correction_rejected(self):
        with self.assertRaisesRegex(ValueError,'correction'):self.conversion(lambda c:c['calib_gyro_bias'].__setitem__(0,1))
    def test_different_resolution_rejected(self):
        with self.assertRaisesRegex(ValueError,'resolutions'):self.conversion(lambda c:c['resolution'].__setitem__(1,[800,600]))
    def fixture(self,new=False):
        root=self.root/'source';root.mkdir();prep=root/'01_preparation';ref=root/'02_mocap_alignment';vio=root/'03_vio';prep.mkdir();ref.mkdir();vio.mkdir()
        identity=str(self.root/'raw');pr=prep/('outputs/preparation.json' if new else 'preparation.json')
        dump(pr,dict(source=identity,cam_time_offset_ns=2631359))
        (prep/('outputs/dataset/mav0' if new else 'dataset/mav0')).mkdir(parents=True)
        dump(prep/'inputs/calibration.json',self.cal);dump(prep/'inputs/export_manifest.json',dict(schema_version=1,camera_order=['cam0','cam1','cam2','cam3']))
        gt=ref/('outputs/state_groundtruth_estimate0' if new else 'state_groundtruth_estimate0');gt.mkdir(parents=True)
        gtrows=[(1000000000+i*10000000,[i*.1,(i%2)*.1,0,1,0,0,0]) for i in range(6)]
        write_trajectory(gtrows,gt);(gt/'trajectory_euroc.csv').rename(gt/'data.csv');dump(gt/'conversion.json',dict(valid_segments_ns=[[1000000000,1050000000]]))
        vt=vio/'outputs' if new else vio;vt.mkdir(exist_ok=True);write_trajectory(gtrows,vt);(vt/'trajectory_euroc.csv').rename(vt/'oak4p_trajectory.csv')
        m=dict(dataset=identity,stages={k:dict(status='complete',directory=n) for k,n in [('prepare','01_preparation'),('gt','02_mocap_alignment'),('vio','03_vio')]});(root/'manifest.yaml').write_text(yaml.safe_dump(m))
        return root
    def test_basalt_old_layout(self):self.assertEqual(inspect(self.fixture(),'basalt')['offset'],2631359)
    def test_basalt_new_layout(self):self.assertEqual(inspect(self.fixture(True),'basalt')['offset'],2631359)
    def test_incomplete_source(self):
        root=self.fixture();m=yaml.safe_load((root/'manifest.yaml').read_text());m['stages']['vio']['status']='failed';(root/'manifest.yaml').write_text(yaml.safe_dump(m))
        with self.assertRaisesRegex(ValueError,'incomplete'):inspect(root,'basalt')
    def test_broken_dataset(self):
        root=self.fixture();(root/'01_preparation/dataset/mav0').rmdir()
        with self.assertRaisesRegex(ValueError,'dataset'):inspect(root,'basalt')
    def test_conflicting_snapshots(self):
        root=self.fixture();dump(root/'01_preparation/outputs/preparation.json',dict(source='conflict'))
        with self.assertRaisesRegex(ValueError,'Conflicting'):inspect(root,'basalt')
    def test_double_offset_conflict(self):
        root=self.fixture();p=root/'01_preparation/preparation.json';d=json.loads(p.read_text());d['cam_time_offset_ns']*=2;dump(p,d)
        with self.assertRaisesRegex(ValueError,'offset'):inspect(root,'basalt')
    def test_unknown_okvis_version(self):
        root=self.fixture();p=root/'manifest.yaml';m=yaml.safe_load(p.read_text());m.update(format='okvis-vio',version=1);p.write_text(yaml.safe_dump(m))
        with self.assertRaisesRegex(ValueError,'version-2'):inspect(root,'okvis')
    def okvis_fixture(self):
        import shutil
        basalt=self.fixture();info=inspect(basalt,'basalt');root=self.root/'okvis';root.mkdir()
        prep=root/'01_preparation';ref=root/'02_reference';vio=root/'03_vio'
        for p in [prep/'inputs',prep/'outputs',vio/'outputs']:p.mkdir(parents=True)
        for c in ['cam0','cam1','cam2','cam3','imu0']:
            p=info['dataset']/'mav0'/c;p.mkdir();(p/'data.csv').write_text('#timestamp,filename\n1000000000,x.png\n')
        (prep/'outputs/dataset').symlink_to(info['dataset'],target_is_directory=True)
        dump(prep/'outputs/preparation.json',dict(cam_time_offset_ns=2631359,index_sha256={c:sha(info['dataset']/'mav0'/c/'data.csv') for c in ['cam0','cam1','cam2','cam3','imu0']}))
        shutil.copyfile(info['calibration'],prep/'outputs/calibration.json');shutil.copyfile(info['export'],prep/'inputs/export_manifest.json')
        shutil.copyfile(basalt/'01_preparation/preparation.json',prep/'inputs/basalt_preparation.json')
        import_reference(info,ref/'inputs');shutil.copyfile(info['algorithms']['basalt'],vio/'outputs/trajectory_euroc.csv')
        m=dict(format='okvis-vio',version=2,parameters=dict(dataset=info['identity'],basalt_run=str(basalt)),stages={k:dict(status='complete',directory=n,artifact_sha256={}) for k,n in [('prepare','01_preparation'),('reference','02_reference'),('vio','03_vio')]})
        m['stages']['vio']['artifact_sha256']['outputs/trajectory_euroc.csv']=sha(vio/'outputs/trajectory_euroc.csv')
        (root/'manifest.yaml').write_text(yaml.safe_dump(m));return root,basalt
    def test_okvis_snapshot_import(self):
        root,_=self.okvis_fixture();self.assertEqual(set(inspect(root,'okvis')['algorithms']),{'basalt','okvis'})
    def test_okvis_csv_hash_drift(self):
        root,b=self.okvis_fixture();(b/'01_preparation/dataset/mav0/cam2/data.csv').write_text('changed')
        with self.assertRaisesRegex(ValueError,'CSV'):inspect(root,'okvis')
    def test_okvis_trajectory_snapshot_drift(self):
        root,_=self.okvis_fixture();p=root/'03_vio/outputs/trajectory_euroc.csv';p.write_text(p.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):inspect(root,'okvis')
    def test_output_cannot_follow_link_into_basalt(self):
        import subprocess
        root,b=self.okvis_fixture();output=b/'01_preparation/dataset/new_output'
        r=subprocess.run([sys.executable,str(REPO/'scripts/run_vio_pipeline.py'),'--okvis-run',str(root),'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(r.returncode,2);self.assertFalse(output.exists());self.assertIn('outside source',r.stderr)
    def test_insufficient_evaluation_has_no_fake_zero(self):
        gt=self.root/'gt';gt.mkdir();poses=[(1000000000+i*10000000,[i*.1,0,0,1,0,0,0]) for i in range(3)]
        write_trajectory(poses,gt);(gt/'trajectory_euroc.csv').rename(gt/'data.csv');dump(gt/'conversion.json',dict(valid_segments_ns=[[1000000000,1020000000]]))
        r,s=evaluate('few',poses,self.root/'few',gt/'data.csv',1000000000);self.assertEqual(r['metrics'],{});self.assertIsNone(s)
    def test_source_hash_drift(self):
        p=self.root/'x';p.write_text('before');h={str(p):sha(p)};p.write_text('after')
        with self.assertRaisesRegex(ValueError,'changed'):verify_sources(h)
    def test_evo_known_rigid_transform_and_stats(self):
        from evo.tools import file_interface
        gt=self.root/'gt';gt.mkdir();rows=[(1000000000+i*10000000,[i*.1,np.sin(i*.6)*.2,0,1,0,0,0]) for i in range(20)]
        write_trajectory(rows,gt);(gt/'trajectory_euroc.csv').rename(gt/'data.csv');dump(gt/'conversion.json',dict(valid_segments_ns=[[1000000000,1190000000]]))
        estimates=[(t,[v[0]+2,v[1]-3,0,1,0,0,0]) for t,v in rows]
        r,s=evaluate('synthetic',estimates,self.root/'eval',gt/'data.csv',1000000000)
        self.assertLess(r['metrics']['ape_translation']['rmse'],1e-10);self.assertGreater(r['metrics']['rpe_translation_0.1m']['n'],0)
        self.assertEqual(r['metrics']['ape_translation']['n'],20)
    def test_rpe_does_not_cross_gt_segments(self):
        from evo.core.trajectory import PoseTrajectory3D
        ref=PoseTrajectory3D(positions_xyz=np.array([[i*.1,0,0] for i in range(8)]),orientations_quat_wxyz=np.array([[1,0,0,0]]*8),timestamps=np.arange(8,dtype=float))
        pairs,keep=reference_pairs(ref,.1,list(range(8)),[[0,3],[4,7]])
        self.assertFalse(any(i<=3<j for (i,j),k in zip(pairs,keep) if k))
    def test_gt_gap_never_extrapolates(self):
        gt=self.root/'gt';gt.mkdir();rows=[(1000000000+i*10000000,[i*.1,0,0,1,0,0,0]) for i in range(10)]
        write_trajectory(rows,gt);(gt/'trajectory_euroc.csv').rename(gt/'data.csv');dump(gt/'conversion.json',dict(valid_segments_ns=[[1000000000,1030000000],[1060000000,1090000000]]))
        traj=self.root/'est';write_trajectory(rows+[(1100000000,[1,0,0,1,0,0,0])],traj)
        result=interpolate(gt/'data.csv',traj/'trajectory.tum',self.root/'interpolate');self.assertEqual(result['accepted_poses'],8)
    def test_dynamic_dependency_snapshot_and_missing_library(self):
        from unittest.mock import patch
        from vio_artifacts import dynamic_libraries
        p=self.root/'lib.so';p.write_text('dependency')
        with patch('vio_artifacts.subprocess.check_output',return_value=f'lib.so => {p} (0x0)\n'):
            self.assertEqual(dynamic_libraries('binary')['files'][str(p)]['sha256'],sha(p))
        with patch('vio_artifacts.subprocess.check_output',return_value='lib.so => not found\n'):
            with self.assertRaisesRegex(ValueError,'Unresolved'):dynamic_libraries('binary')
    def test_missing_source_manifest_generates_failure_report(self):
        import subprocess
        output=self.root/'outputs'
        r=subprocess.run([sys.executable,str(REPO/'scripts/run_vio_pipeline.py'),'--basalt-run',str(self.root/'missing_source'),'--output',str(output)],capture_output=True,text=True)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        run=next(output.glob('run_*'));self.assertEqual(yaml.safe_load((run/'manifest.yaml').read_text())['status'],'failed')
        self.assertIn('Source manifest unavailable',(run/'report/index.html').read_text())
    def test_group_record_detects_already_shifted_csv(self):
        root=self.fixture();p=root/'01_preparation/preparation.json';d=json.loads(p.read_text());d['first_camera_timestamp_ns']=1000000000;dump(p,d)
        path=root/'01_preparation/dataset/mav0/cam0';path.mkdir();(path/'data.csv').write_text('1002631359,x.png\n')
        with self.assertRaisesRegex(ValueError,'repeated shift'):inspect(root,'basalt')
    def test_group_count_conflict(self):
        root=self.fixture();p=root/'01_preparation/preparation.json';d=json.loads(p.read_text());d['groups']=2;dump(p,d)
        path=root/'01_preparation/dataset/mav0/cam0';path.mkdir();(path/'data.csv').write_text('1000000000,x.png\n')
        with self.assertRaisesRegex(ValueError,'group count'):inspect(root,'basalt')
    def test_reference_clock_mismatch(self):
        root=self.fixture();poses=[(2000000000+i*10000000,[i*.1,0,0,1,0,0,0]) for i in range(6)]
        target=self.root/'shifted';write_trajectory(poses,target);(root/'03_vio/oak4p_trajectory.csv').write_text((target/'trajectory_euroc.csv').read_text())
        with self.assertRaisesRegex(ValueError,'overlap'):inspect(root,'basalt')
    def test_saved_resource_statistics_and_config_changes(self):
        from generate_vio_report import saved_resources,configuration_changes
        r=self.root/'run';p=r/'03_vio/diagnostics';p.mkdir(parents=True)
        (p/'resource_usage.txt').write_text('Maximum resident set size (kbytes): 2048\nUser time (seconds): 1.2\nSystem time (seconds): 0.3\n')
        p=r/'03_vio/outputs/replay';p.mkdir(parents=True);(p/'frames.csv').write_text('corrected_ns,track_ms\n1000000000,10\n1100000000,20\n')
        stats=saved_resources(r);self.assertEqual(stats['peak_rss_kib'],2048);self.assertEqual(stats['track_ms_median'],15);self.assertEqual(stats['processed_input_duration_s'],.1)
        p=r/'01_preparation';(p/'inputs').mkdir(parents=True);(p/'outputs').mkdir()
        (p/'inputs/algorithm_template.yaml').write_text('%YAML:1.0\nSystem.VIOOnly: 0\n');(p/'outputs/openmavis.yaml').write_text('%YAML:1.0\nSystem.VIOOnly: 1\n')
        self.assertEqual(configuration_changes(r),[dict(key='System.VIOOnly',template=0,generated=1)])
    def test_evo_gui_algorithm_labels_and_frozen_inputs(self):
        from unittest.mock import patch
        from compare_vio_trajectories import show_gui
        r=self.root/'run';r.mkdir();names=['openmavis','basalt','okvis'];m=dict(format='openmavis-vio',version=1,algorithms=names)
        (r/'manifest.yaml').write_text(yaml.safe_dump(m));before={}
        for n in names:
            p=r/'04_vio_comparison/common'/n;p.mkdir(parents=True)
            for f in ['ape_translation.zip','vio_matched.tum','mocap_at_vio.tum']:(p/f).write_text('synthetic test '+n);before[str(p/f)]=sha(p/f)
        with patch('compare_vio_trajectories.subprocess.run') as run:show_gui(r)
        last=run.call_args;argv=last.args[0];self.assertEqual(argv[2:5],[n+'.tum' for n in names]);self.assertEqual(last.kwargs['cwd'],r/'report/evo_gui/trajectories')
        self.assertTrue(all(sha(p)==h for p,h in before.items()))
    def test_partial_failure_report_self_contained(self):
        root=self.root/'run';root.mkdir();m=dict(format='openmavis-vio',version=1,status='failed',parameters={},stages={},invocation=['test'],error='<script>bad</script>');(root/'manifest.yaml').write_text(yaml.safe_dump(m))
        generate(root);page=(root/'report/index.html').read_text();self.assertNotIn('<script>bad</script>',page);self.assertIn('&lt;script&gt;',page);self.assertNotIn('src="http',page)

if __name__=='__main__':unittest.main()
