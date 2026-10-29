"""Explicit raw-IMU bias policy and immutable calibration checks."""
import copy
import json
import unittest
import test_vio_pipeline as legacy
from convert_rig_to_openmavis import convert
from vio_artifacts import dump, sha

REPO=legacy.REPO

class BiasPolicy(unittest.TestCase):
    setUp=legacy.Pipeline.setUp

    def test_raw_bias_opt_in_preserves_calibration_and_geometry(self):
        c=copy.deepcopy(self.cal);c['value0']['calib_accel_bias'][:3]=[.1,.2,.3]
        c['value0']['calib_gyro_bias'][:3]=[.001,.002,.003]
        source=self.root/'cal.json';dump(source,c);before=sha(source)
        result=convert(source,REPO/'Examples/Multi-Inertial/OAK4P_layout0921_repaired.yaml',self.root/'out.yaml',2631359,30,'estimate-from-zero')
        self.assertEqual(before,sha(source));self.assertFalse(result['imu_correction']['fixed_bias_applied'])
        self.assertTrue(result['imu_correction']['raw_samples_unchanged'])
        self.assertEqual(result['imu_correction']['source_accel'][:3],[.1,.2,.3])
        self.assertEqual(result['imu_correction']['initial_gyro_bias'],[0,0,0])

    def test_opt_in_still_rejects_scale_misalignment_and_nan(self):
        for index,value in [(3,.01),(0,float('nan'))]:
            c=copy.deepcopy(self.cal);c['value0']['calib_gyro_bias'][index]=value
            source=self.root/'cal.json';source.write_text(json.dumps(c))
            with self.assertRaisesRegex(ValueError,'correction'):
                convert(source,REPO/'Examples/Multi-Inertial/OAK4P_layout0921_repaired.yaml',self.root/'out.yaml',2631359,30,'estimate-from-zero')

if __name__=='__main__':unittest.main()
