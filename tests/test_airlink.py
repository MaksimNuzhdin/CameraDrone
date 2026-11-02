"""Actual encode/RTP/decode loopback, using a synthetic source and temporary files."""
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airlink'))
from video import PROFILES, sender, receiver

class TransportTest(unittest.TestCase):
    def test_rtp_decodes_synthetic_video(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        p=PROFILES['bench'];frame_size=p['width']*p['height']*3
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'decoded.bgr'
            with (Path(tmp)/'receiver.log').open('wb') as log:
                rx=subprocess.Popen(receiver(p,'127.0.0.1',port,frames=30,output=output),stdout=log,stderr=log)
                try:
                    time.sleep(.3)
                    tx=subprocess.run(sender(p,'127.0.0.1',port,buffers=60),capture_output=True,timeout=15)
                    self.assertEqual(tx.returncode,0,tx.stderr.decode())
                    rx.wait(timeout=10)
                    self.assertEqual(rx.returncode,0)
                    data=output.read_bytes();frames=len(data)//frame_size
                    self.assertGreaterEqual(frames,25)
                    self.assertEqual(len(data)%frame_size,0)
                    self.assertGreater(np.frombuffer(data,dtype=np.uint8).std(),5)
                    print(f'RTP loopback: {frames} decoded {p["width"]}x{p["height"]} frames')
                finally:
                    if rx.poll() is None:rx.kill();rx.wait()

if __name__=='__main__':unittest.main()
