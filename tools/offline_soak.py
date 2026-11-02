"""Bounded synthetic-source soak. No Pi, no real imagery, isolated temporary data."""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
import cv2

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'camera_app'))
from host import create_host_app
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds',type=int,default=60);parser.add_argument('--output',type=Path)
args=parser.parse_args()
if not 10<=args.seconds<=3600:parser.error('seconds must be 10..3600')
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);app=create_host_app(root/'data',False,root/'runtime.json')
    manager=app.extensions['camera_manager'];engine=manager.offline
    try:
        deadline=time.monotonic()+5
        while engine.frame is None and time.monotonic()<deadline:time.sleep(.05)
        engine.vision.configure(dict(objects=True,faces=True,qr=True,motion=True,interval_ms=350))
        with engine.lock:engine.stream_clients+=1
        started=time.monotonic();record=engine.submit('record_start');samples=[];stop_result=None;last_sequence=0;preview_frames=0
        while time.monotonic()-started<args.seconds:
            time.sleep(1);s=engine.get_status()
            assert s['status']=='running' and s['frame_age_ms']<2000,s
            assert 'error' not in s['analysis'],s['analysis']
            with engine.lock:sequence=engine.preview_sequence
            preview_frames+=sequence-last_sequence if last_sequence else 0;last_sequence=sequence
            samples.append(dict(elapsed_s=round(time.monotonic()-started,2),capture_fps=s['capture_fps'],frame_age_ms=s['frame_age_ms'],inference_ms=s['analysis'].get('inference_ms')))
            if stop_result is None and time.monotonic()-started>min(15,args.seconds/2):stop_result=engine.submit('record_stop')
        if stop_result is None:stop_result=engine.submit('record_stop')
        cap=cv2.VideoCapture(str(engine.data/record['name']));decoded=0
        while True:
            ok,frame=cap.read()
            if not ok:break
            decoded+=1
        cap.release();assert decoded==stop_result['encoded_frames'],(decoded,stop_result)
        report=dict(source='synthetic Ubuntu host; no Pi or RF',duration_s=round(time.monotonic()-started,2),preview_frames_generated=preview_frames,
                    capture_fps_min=min(s['capture_fps'] for s in samples[3:]),frame_age_max_ms=max(s['frame_age_ms'] for s in samples),
                    recorded_frames=decoded,dropped_recording_frames=stop_result['dropped_frames'],samples=samples)
        if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
        print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))
    finally:manager.close()
