"""Ten minute real preview + object detection soak, with a one-minute recording."""
import json
import argparse
import threading
import time
from pathlib import Path

import requests

BASE='http://127.0.0.1:8765'
HEADERS={'X-Camera-Client':'1'}
OUT=Path(__file__).resolve().parents[1]/'artifacts'
OUT.mkdir(exist_ok=True)
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--duration',type=int,default=600,help='Seconds, 30..3600; default 600')
args=parser.parse_args()
if not 30<=args.duration<=3600:parser.error('duration must be 30..3600 seconds')
duration=args.duration
warmup_s=10
stats={'jpeg_frames':0,'received_bytes':0,'stream_error':None,'samples':[]}
stop=threading.Event()

def post(path,body):
    r=requests.post(BASE+'/api/'+path,json=body,headers=HEADERS,timeout=35);r.raise_for_status();return r.json()

def stream():
    try:
        with requests.get(BASE+'/stream.mjpg',stream=True,timeout=(5,10)) as r:
            r.raise_for_status();pending=b''
            for chunk in r.iter_content(65536):
                stats['received_bytes']+=len(chunk)
                pending+=chunk
                stats['jpeg_frames']+=pending.count(b'--frame\r\n')
                pending=pending[-8:]
                if stop.is_set():break
    except Exception as exc:stats['stream_error']=str(exc)

initial_response=requests.get(BASE+'/api/status',timeout=10)
initial_response.raise_for_status()
initial=initial_response.json()
if not initial.get('hardware') or initial.get('status')!='running':
    raise RuntimeError('Select a running Raspberry Pi camera before the hardware soak')
if initial.get('recording'):
    raise RuntimeError('Stop the current recording before the hardware soak')
if initial['settings']['fps']<25:
    raise RuntimeError('Select a camera profile of at least 25 FPS before this soak')
post('ai',dict(objects=True,faces=False,qr=False,motion=False,interval_ms=350))
post('action/record_start',{})
thread=threading.Thread(target=stream,daemon=True);thread.start()
started=time.monotonic();recording=True
try:
    while time.monotonic()-started<duration:
        s=requests.get(BASE+'/api/status',timeout=10).json()
        sample={k:s.get(k) for k in ['status','capture_fps','preview_fps','frame_age_ms','analysis_age_ms','temperature_c','memory_available_mb','disk_free_mb','uptime_s']}
        sample['elapsed']=round(time.monotonic()-started,1)
        sample['inference_ms']=s.get('analysis',{}).get('inference_ms')
        sample['thermal']=s.get('thermal')
        if sample['status']!='running' or sample['frame_age_ms'] is None or sample['frame_age_ms']>2000:
            raise AssertionError(sample)
        if s.get('analysis',{}).get('error'):raise AssertionError(s['analysis'])
        stats['samples'].append(sample)
        if recording and time.monotonic()-started>=60:
            stats['recording']=post('action/record_stop',{});recording=False
        if len(stats['samples'])%6==0:print(json.dumps(sample),flush=True)
        (OUT/'soak-progress.json').write_text(json.dumps(stats,indent=2))
        time.sleep(5)
finally:
    if recording:post('action/record_stop',{})
    post('ai',initial['ai_options'])
    stop.set();thread.join(timeout=12)
    stats['duration_s']=round(time.monotonic()-started,1)
    samples=stats['samples']
    steady=[s for s in samples if s['elapsed']>=warmup_s]
    stats['summary']=dict(capture_fps_min=min(s['capture_fps'] for s in samples),
                          capture_fps_max=max(s['capture_fps'] for s in samples),
                          warmup_s=warmup_s,
                          capture_fps_steady_min=min(s['capture_fps'] for s in steady),
                          capture_fps_steady_max=max(s['capture_fps'] for s in steady),
                          temperature_max_c=max(s['temperature_c'] for s in samples),
                          frame_age_max_ms=max(s['frame_age_ms'] for s in samples))
    (OUT/'soak-results.json').write_text(json.dumps(stats,indent=2))
assert stats['stream_error'] is None,stats['stream_error']
assert stats['jpeg_frames']>duration*4,stats['jpeg_frames']
assert stats['duration_s']>=duration
assert stats['summary']['capture_fps_steady_min']>24,stats['summary']
print('PASS soak',json.dumps(stats['summary']),stats['jpeg_frames'],'preview frames',flush=True)
