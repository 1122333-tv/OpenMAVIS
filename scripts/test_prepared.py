#!/usr/bin/env python3
import json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PreparedInputs(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.data=self.root/'data'
        for c in range(4):
            p=self.data/f'mav0/cam{c}';(p/'data').mkdir(parents=True)
            (p/'data.csv').write_text('#timestamp,filename\n1000000000,a.ppm\n1040000000,b.ppm\n')
            for n in ['a','b']:(p/f'data/{n}.ppm').write_bytes(b'P6\n1280 800\n255\n'+bytes([80,100,120])*(1280*800))
        p=self.data/'mav0/imu0';p.mkdir();(p/'data.csv').write_text('#timestamp,wx,wy,wz,ax,ay,az\n'+''.join(f'{t},0,0,0,0,0,-9.81\n' for t in range(900000000,1100000001,2000000)))
    def run_case(self,error=None,extra=()):
        cmd=[str(ROOT/'Examples/Multi-Inertial/multi_inertial_prepared'),'--vocabulary',str(ROOT/'Vocabulary/ORBvoc.txt'),'--settings',str(ROOT/'Examples/Multi-Inertial/OAK4P_layout0921.yaml'),'--dataset',str(self.data),'--output',str(self.root/'out'),'--cam-time-offset-ns','2631359','--validate-only',*extra]
        p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        if error:self.assertNotEqual(p.returncode,0,p.stdout);self.assertIn(error,p.stdout)
        else:self.assertEqual(p.returncode,0,p.stdout)
        return p
    def test_valid(self):
        self.run_case();s=json.loads((self.root/'out/input_summary.json').read_text());self.assertEqual(s['cam_time_offset_ns'],2631359);self.assertEqual(s['input_frames'],2)
    def test_mismatch(self):
        p=self.data/'mav0/cam2/data.csv';p.write_text(p.read_text().replace('1040000000','1040000001'));self.run_case('Camera timestamp mismatch')
    def test_duplicate(self):
        p=self.data/'mav0/cam1/data.csv';p.write_text(p.read_text().replace('1040000000','1000000000'));self.run_case('Non-monotonic timestamp')
    def test_missing(self):
        (self.data/'mav0/cam3/data/b.ppm').unlink();self.run_case('Missing image cam3 frame 1')
    def test_bad_image(self):
        (self.data/'mav0/cam2/data/b.ppm').write_text('broken');self.run_case('Invalid image cam2 frame 1')
    def test_imu_ends_early(self):
        p=self.data/'mav0/imu0/data.csv';p.write_text('#header\n900000000,0,0,0,0,0,-9.81\n1000000000,0,0,0,0,0,-9.81\n');self.run_case('IMU does not cover')
    def test_empty(self):
        (self.data/'mav0/cam0/data.csv').write_text('#header\n');self.run_case('Empty CSV')
    def test_nonfinite_imu(self):
        p=self.data/'mav0/imu0/data.csv';p.write_text(p.read_text().replace('-9.81','nan'));self.run_case('Invalid IMU value')
    def test_duplicate_imu(self):
        p=self.data/'mav0/imu0/data.csv';p.write_text(p.read_text().replace('902000000','900000000'));self.run_case('Non-monotonic IMU')
    def test_existing_output(self):
        (self.root/'out').mkdir();self.run_case('fresh directory')
if __name__=='__main__':unittest.main()
