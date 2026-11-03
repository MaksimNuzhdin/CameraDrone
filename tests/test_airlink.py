"""Actual encode/RTP/decode loopback, using a synthetic source and temporary files."""
import socket
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'airlink'))
from video import PROFILES, sender, receiver

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera_app'))
from rtp import RtpSender

class TransportTest(unittest.TestCase):
    def test_custom_sender_decodes_with_standard_gstreamer(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        p=PROFILES['bench'];size=p['width']*p['height']*3
        with tempfile.TemporaryDirectory() as tmp:
            raw=Path(tmp)/'source.h264';out=Path(tmp)/'decoded.bgr'
            command=['gst-launch-1.0','-q','-e','videotestsrc','num-buffers=60','!',
                'video/x-raw,width=640,height=360,framerate=15/1','!','x264enc','tune=zerolatency','speed-preset=ultrafast','key-int-max=15','byte-stream=true','aud=true','!',
                'h264parse','!','video/x-h264,stream-format=byte-stream,alignment=au','!','filesink','location='+str(raw)]
            subprocess.run(command,check=True,capture_output=True,timeout=15)
            nals=[x for x in re.split(b'\x00\x00\x00\x01|\x00\x00\x01',raw.read_bytes()) if x]
            units=[];current=[]
            for nal in nals:
                if nal[0]&31==9 and current:units.append(current);current=[]
                current.append(nal)
            if current:units.append(current)
            self.assertEqual(len(units),60)
            rx=subprocess.Popen(receiver(p,'127.0.0.1',port,frames=30,output=out),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            tx=RtpSender(dict(host='127.0.0.1',port=port))
            try:
                time.sleep(.3)
                for i,unit in enumerate(units):
                    tx.outputframe(b''.join(b'\0\0\0\1'+x for x in unit),keyframe=any(x[0]&31==5 for x in unit),timestamp=i*1_000_000//15)
                    time.sleep(1/15)
                rx.wait(timeout=10)
                self.assertEqual(rx.returncode,0,rx.stderr.read().decode())
                self.assertGreaterEqual(out.stat().st_size//size,25)
                self.assertEqual(tx.status()['dropped_packets'],0)
            finally:
                tx.close()
                if rx.poll() is None:rx.kill();rx.wait()
                rx.stderr.close()

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
