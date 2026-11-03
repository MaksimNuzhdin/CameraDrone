"""Reject software latency claims when reboot/NTP invalidates clock calibration."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airlink'))
from timing import latency_summary

class ClockTests(unittest.TestCase):
    def test_stable_clocks(self):
        before=dict(offset_ns=1_000_000,offset_uncertainty_ms=2)
        after=dict(offset_ns=2_000_000,offset_uncertainty_ms=2)
        result=latency_summary([10,20,30],before,after)
        self.assertTrue(result['valid']);self.assertEqual(result['p50_ms'],20)
    def test_drift_and_negative_estimates_are_not_latency(self):
        before=dict(offset_ns=0,offset_uncertainty_ms=2)
        after=dict(offset_ns=200_000_000,offset_uncertainty_ms=2)
        for values,clock in [([10,20,30],after),([-100,-80],before),([],before)]:
            result=latency_summary(values,before,clock)
            self.assertFalse(result['valid']);self.assertIsNone(result['p50_ms']);self.assertTrue(result['invalid_reason'])

if __name__=='__main__':unittest.main()
