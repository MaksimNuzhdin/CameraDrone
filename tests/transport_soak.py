"""Pi-to-Ubuntu RTP soak with one encoder, AI and an initial recording.

Run with system Python (GStreamer GI required), real Pi selected, no active
recording/RTP. All generated reports remain private under artifacts/.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--seconds',type=int,default=1800)
parser.add_argument('--record-seconds',type=int,default=60)
parser.add_argument('--port',type=int,default=5610)
parser.add_argument('--base-url',default='http://127.0.0.1:8765')
parser.add_argument('--prefix',default='rtp-soak')
args=parser.parse_args()
if not 30<=args.seconds<=3600 or not 1<=args.record_seconds<=args.seconds or not 1024<=args.port<=65535:parser.error('Invalid duration or port')
if not args.prefix.replace('-','').replace('_','').isalnum():parser.error('prefix must be alphanumeric with - or _')
base=args.base_url.rstrip('/');out=ROOT/'artifacts';out.mkdir(exist_ok=True)

def get(path):
    response=requests.get(base+'/api/'+path,timeout=8);response.raise_for_status();return response.json()
def post(path,body):
    response=requests.post(base+'/api/'+path,json=body,headers={'X-Camera-Client':'1'},timeout=35);response.raise_for_status();return response.json()

initial=get('status')
if not initial.get('hardware') or initial.get('status')!='running':raise RuntimeError('Select a running real Pi')
if initial.get('recording') or initial.get('transport',{}).get('active'):raise RuntimeError('Stop current recording and RTP first')
info=get('host');destination=info.get('ground_ip')
if not destination:raise RuntimeError('No host IPv4 route to the Pi')
receiver=None;log=None;samples=[];record=None;summary={};failure=None
report_path=out/(args.prefix+'-receiver.json')
try:
    post('profiles/pi5-balanced/apply',{})
    post('ai',dict(objects=True,faces=True,qr=True,motion=True,interval_ms=350))
    report_path.with_suffix('.progress.json').unlink(missing_ok=True)
    log=(out/(args.prefix+'-receiver.log')).open('w')
    receiver=subprocess.Popen([sys.executable,str(ROOT/'airlink/monitor.py'),'--bind',destination,'--port',str(args.port),'--seconds',str(args.seconds+3),'--control-url',base,'--output',str(report_path)],stdout=log,stderr=subprocess.STDOUT)
    ready=report_path.with_suffix('.progress.json');deadline=time.monotonic()+10
    while not ready.exists() and time.monotonic()<deadline:
        if receiver.poll() is not None:raise RuntimeError('Ground receiver failed; see its log')
        time.sleep(.1)
    if not ready.exists():raise RuntimeError('Ground receiver did not become ready')
    post('transport',dict(enabled=True,host=destination,port=args.port,mtu=1200))
    generation=get('status')['encoding']['generation']
    record=post('action/record_start',{})['name'];started=time.monotonic()
    while time.monotonic()-started<args.seconds:
        s=get('status');elapsed=time.monotonic()-started
        if s['status']!='running' or s['frame_age_ms'] is None or s['frame_age_ms']>2000:raise AssertionError(s['status'])
        if not s['transport']['active'] or s['encoding']['generation']!=generation:raise AssertionError('Encoder/transport session unexpectedly changed')
        if s.get('analysis',{}).get('error'):raise AssertionError(s['analysis']['error'])
        sample=dict(elapsed_s=round(elapsed,2),capture_fps=s['capture_fps'],frame_age_ms=s['frame_age_ms'],temperature_c=s['temperature_c'],memory_available_mb=s['memory_available_mb'],thermal=s['thermal'],transport=s['transport']['stats'],inference_ms=s.get('analysis',{}).get('inference_ms'),recording=bool(s['recording']))
        samples.append(sample)
        (out/(args.prefix+'-progress.json')).write_text(json.dumps(dict(samples=samples,recording=record),indent=2))
        if record and elapsed>=args.record_seconds:post('action/record_stop',{});summary['recording_name']=record;record=None
        if receiver.poll() is not None:raise RuntimeError('Receiver stopped early')
        if len(samples)%12==0:print(json.dumps(sample),flush=True)
        time.sleep(5)
    if record:post('action/record_stop',{});summary['recording_name']=record;record=None
    receiver.wait(timeout=15)
    if receiver.returncode:raise RuntimeError('Ground decode failed')
    decoded=json.loads(report_path.read_text());steady=[s for s in samples if s['elapsed_s']>=10]
    summary.update(duration_s=round(time.monotonic()-started,2),capture_fps_min=min(s['capture_fps'] for s in samples),capture_fps_steady_min=min(s['capture_fps'] for s in steady),temperature_max_c=max(s['temperature_c'] for s in samples),frame_age_max_ms=max(s['frame_age_ms'] for s in samples),receiver=decoded,single_encoder=True)
    assert summary['capture_fps_steady_min']>24,summary['capture_fps_steady_min']
    assert decoded['decoded_fps']>24 and decoded['frames']>args.seconds*24,decoded['frames']
    assert not decoded['errors'] and decoded['jitter'].get('num-lost',0)==0,decoded['jitter']
    assert decoded['max_decode_gap_ms']<1500,decoded['max_decode_gap_ms']
    assert samples[-1]['transport']['dropped_packets']==0 and samples[-1]['transport']['invalid_frames']==0
except BaseException as exc:
    failure=f'{type(exc).__name__}: {exc}'
    raise
finally:
    if receiver and receiver.poll() is None:receiver.terminate();receiver.wait(timeout=10)
    if log:log.close()
    try:
        current=get('status')
        if current.get('recording'):post('action/record_stop',{})
        if current.get('transport',{}).get('active'):post('transport',dict(enabled=False))
        post('settings',initial['settings']);post('ai',initial['ai_options'])
    finally:
        (out/(args.prefix+'-results.json')).write_text(json.dumps(dict(summary=summary,error=failure,samples=samples),indent=2))
print('PASS real RTP soak',json.dumps({k:v for k,v in summary.items() if k!='receiver'}),flush=True)
