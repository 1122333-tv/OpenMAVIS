"""Three-way exact timing, missing outputs and frozen-input checks."""
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import yaml
from unittest.mock import patch
from vio_artifacts import dump, sha, write_trajectory
from compare_poc_trajectories import compare

class ThreeWay(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.ts=1792993000000000001+np.arange(200,dtype=np.int64)*33333333
        self.rows=[(int(t),[float(np.sin(i/20)),float(np.cos(i/25)),i*.01,1,0,0,0]) for i,t in enumerate(self.ts)]

    def fixture(self,initialized=True):
        r=self.root/'run';r.mkdir()
        m=dict(format='openmavis-vio',version=1,parameters={'evaluation_profile':'motion'},algorithms=['openmavis','basalt','okvis'])
        (r/'manifest.yaml').write_text(yaml.safe_dump(m))
        dump(r/'01_preparation/outputs/preparation.json',dict(first_corrected_ns=int(self.ts[0]),last_corrected_ns=int(self.ts[-1])))
        dump(r/'03_vio/outputs/summary.json',dict(online={'common_eligible':initialized}))
        p=r/'03_vio/outputs/replay';p.mkdir(parents=True)
        (p/'frames.csv').write_text('corrected_ns\n'+'\n'.join(map(str,self.ts))+'\n')
        ref=r/'02_reference/inputs';gt=ref/'groundtruth';write_trajectory(self.rows,gt)
        (gt/'trajectory_euroc.csv').rename(gt/'data.csv')
        dump(gt/'conversion.json',dict(valid_segments_ns=[[int(self.ts[0]),int(self.ts[-1])]]))
        for name in ['okvis','basalt']:
            p=self.root/name;write_trajectory(self.rows,p);(ref/(name+'_trajectory.csv')).write_bytes((p/'trajectory_euroc.csv').read_bytes())
        (ref/'basalt_states.csv').write_text('timestamp_ns,state_reset\n'+str(self.ts[100])+',1\n')
        if initialized:write_trajectory([p for i,p in enumerate(self.rows) if i>=10 and i!=130],r/'03_vio/outputs/online')
        return r

    def test_three_way_late_initialization_pairs_and_resets(self):
        r=self.fixture();before={str(p):sha(p) for p in (r/'02_reference').rglob('*') if p.is_file()}
        with patch('compare_poc_trajectories.plot_scope'):s=compare(r)
        self.assertEqual(s['common_timestamps']['n'],189);self.assertTrue(s['common_pairs_verified'])
        self.assertEqual(s['common_timestamps']['first_ns'],int(self.ts[10]))
        for record in s['common'].values():
            self.assertEqual(record['metrics']['ape_translation']['n'],189)
            self.assertLess(record['metrics']['are_rotation']['rmse'],1e-10)
            self.assertEqual(record['pairing']['segment_count'],3)
        self.assertTrue(all(sha(p)==h for p,h in before.items()))

    def test_no_initialized_vio_has_no_common_ranking(self):
        r=self.fixture(False)
        with patch('compare_poc_trajectories.plot_scope'):s=compare(r)
        self.assertEqual(s['common_timestamps']['status'],'unavailable');self.assertEqual(s['common'],{})
        self.assertEqual(s['native']['openmavis']['metrics'],{});self.assertTrue(s['native']['basalt']['metrics'])

if __name__=='__main__':unittest.main()
