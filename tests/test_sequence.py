"""Input sequence accounting is independent of GStreamer loss-event statistics."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airlink'))
from sequence import SequenceCounter
class SequenceTests(unittest.TestCase):
    def test_wrap_gap_reorder_duplicate_and_session(self):
        counter=SequenceCounter()
        for number in [65534,65535,0,3,3,2,4]:counter.observe(number,1)
        counter.observe(50000,2);counter.observe(50001,2)
        self.assertEqual(counter.status(),dict(sequence_gaps=2,reordered_packets=1,duplicate_packets=1))
        for session in range(3,20):counter.observe(100,session)
        self.assertLessEqual(len(counter.sessions),8)
if __name__=='__main__':unittest.main()
