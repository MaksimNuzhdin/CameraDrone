"""Ten minute real preview + object detection soak, with a one-minute recording."""
import json
import threading
import time
from pathlib import Path

import requests

BASE='http://127.0.0.1:8765'
HEADERS={'X-Camera-Client':'1'}
OUT=Path(__file__).resolve().parents[1]/'artifacts'
OUT.mkdir(exist_ok=True)
duration=600
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
    stop.set();thread.join(timeout=12)
    stats['duration_s']=round(time.monotonic()-started,1)
    samples=stats['samples']
    stats['summary']=dict(capture_fps_min=min(s['capture_fps'] for s in samples),
                          capture_fps_max=max(s['capture_fps'] for s in samples),
                          temperature_max_c=max(s['temperature_c'] for s in samples),
                          frame_age_max_ms=max(s['frame_age_ms'] for s in samples))
    (OUT/'soak-results.json').write_text(json.dumps(stats,indent=2))
assert stats['stream_error'] is None,stats['stream_error']
assert stats['jpeg_frames']>duration*4,stats['jpeg_frames']
assert stats['duration_s']>=duration
assert stats['summary']['capture_fps_min']>24,stats['summary']
print('PASS soak',json.dumps(stats['summary']),stats['jpeg_frames'],'preview frames',flush=True)
