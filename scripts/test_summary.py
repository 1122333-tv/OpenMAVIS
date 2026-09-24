import csv,importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('run_prepared',Path(__file__).with_name('run_prepared.py'));runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.out=Path(self.temp.name)
        (self.out/'input_summary.json').write_text(json.dumps({'requested_frames':3,'cam_time_offset_ns':10}))
        self.rows=[dict(frame=i,raw_ns=1000+100*i,corrected_ns=1010+100*i,imu_first_ns=1000+100*i,imu_last_ns=1020+100*i,state=2,imu_initialized=1,map_id=0,maps=1,resets=0,**{f'cam{c}_features':100 for c in range(4)}) for i in range(3)]
        for name in ['trajectory_body.txt','keyframes_body.txt']:(self.out/name).write_text('1 0 0 0 0 0 0 1\n2 0 0 0 0 0 0 1\n')
    def result(self):
        with (self.out/'frames.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(self.rows[0]));w.writeheader();w.writerows(self.rows)
        return runner.summarize(self.out,0,True)
    def test_pass(self):self.assertEqual(self.result()['acceptance'],'PASS')
    def test_recently_lost(self):self.rows[-1]['state']=3;self.assertEqual(self.result()['acceptance'],'NOT_PASSED')
    def test_reset_same_map(self):self.rows[-1]['resets']=1;self.assertEqual(self.result()['acceptance'],'NOT_PASSED')
    def test_double_shift(self):self.rows[1]['corrected_ns']+=10;self.assertEqual(self.result()['acceptance'],'NOT_PASSED')
    def test_duplicate_imu(self):self.rows[1]['imu_first_ns']=self.rows[0]['imu_last_ns'];self.assertEqual(self.result()['acceptance'],'NOT_PASSED')
    def test_no_imu_initialization(self):
        for r in self.rows:r['imu_initialized']=0
        self.assertEqual(self.result()['acceptance'],'NOT_PASSED')
if __name__=='__main__':unittest.main()
