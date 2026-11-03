"""Real Pi RTP blackout regression with a bounded, loss-accounted host UDP relay."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--prefix',default='rtp-recovery')
args=parser.parse_args()
if not args.prefix.replace('-','').replace('_','').isalnum():parser.error('Use an alphanumeric prefix')
OUT=ROOT/'artifacts';OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:8765/api/'
def get(path):
    r=requests.get(BASE+path,timeout=8);r.raise_for_status();return r.json()
def post(path,body):
    r=requests.post(BASE+path,json=body,headers={'X-Camera-Client':'1'},timeout=25);r.raise_for_status();return r.json()
initial=get('status')
if not initial.get('hardware') or initial.get('status')!='running':raise RuntimeError('Select the real running Pi')
if initial.get('recording') or initial['transport']['active']:raise RuntimeError('Stop recording/RTP first')
host=get('host')['ground_ip'];receiver=OUT/(args.prefix+'-receiver.json');relay_report=OUT/(args.prefix+'-relay.json')
receiver.with_suffix('.progress.json').unlink(missing_ok=True)
rx=relay=None
with receiver.with_suffix('.log').open('w') as rxlog,relay_report.with_suffix('.log').open('w') as relaylog:
    try:
        post('ai',dict(objects=True,faces=True,qr=True,motion=True,interval_ms=350))
        rx=subprocess.Popen([sys.executable,str(ROOT/'airlink/monitor.py'),'--bind',host,'--port','5614','--seconds','25','--output',str(receiver)],stdout=rxlog,stderr=rxlog)
        deadline=time.monotonic()+8
        while not receiver.with_suffix('.progress.json').exists() and time.monotonic()<deadline:
            if rx.poll() is not None:raise RuntimeError('Receiver failed before readiness')
            time.sleep(.05)
        if not receiver.with_suffix('.progress.json').exists():raise RuntimeError('No receiver readiness')
        relay=subprocess.Popen([sys.executable,str(ROOT/'airlink/impair.py'),'--bind',host,'--in-port','5613','--destination',host,'--out-port','5614','--seconds','26','--blackout-start','8','--blackout-seconds','2','--output',str(relay_report)],stdout=relaylog,stderr=relaylog)
        time.sleep(.25);post('transport',dict(enabled=True,host=host,port=5613,mtu=1200))
        rx.wait(timeout=35);relay.wait(timeout=5)
        assert rx.returncode==relay.returncode==0,(rx.returncode,relay.returncode)
        result=json.loads(receiver.read_text());drops=json.loads(relay_report.read_text())
        assert result['frames']>360 and not result['errors'],result
        assert drops['kernel_receive_drops']==drops['send_dropped']==0,drops
        assert result['rtp_input']['sequence_gaps']==drops['blackout_dropped']>0,(result['rtp_input'],drops)
        assert result['jitter']['num-lost']==drops['blackout_dropped'],(result['jitter'],drops)
        assert result['rtp_input']['reordered_packets']==result['rtp_input']['duplicate_packets']==0,result['rtp_input']
        assert result['max_decode_gap_ms']<4000,result['max_decode_gap_ms']
        print('PASS controlled blackout:',result['frames'],'frames; max gap',result['max_decode_gap_ms'],'ms; RTP input gaps',result['rtp_input']['sequence_gaps'],'intentional relay drops',drops['blackout_dropped'],'jitterbuffer reported lost',result['jitter']['num-lost'],flush=True)
    finally:
        for process in [rx,relay]:
            if process and process.poll() is None:process.terminate();process.wait(timeout=10)
        if get('status')['transport']['active']:post('transport',dict(enabled=False))
        post('ai',initial['ai_options'])
