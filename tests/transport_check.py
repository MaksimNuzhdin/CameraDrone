"""Real Pi RTP lifecycle/guard regression; restores settings and creates private MP4."""
import json
import time
from pathlib import Path
import requests

BASE='http://127.0.0.1:8765/api/'
OUT=Path(__file__).resolve().parents[1]/'artifacts'
OUT.mkdir(exist_ok=True)
results=[]

def call(path,body=None,expected=200):
    response=requests.request('GET' if body is None else 'POST',BASE+path,json=body,
        headers={'X-Camera-Client':'1'},timeout=35)
    assert response.status_code==expected,(path,response.status_code,response.text[:300])
    return response.json()

def check(name,fn):
    detail=fn();results.append(dict(name=name,ok=True,detail=detail));print('PASS',name,detail or '',flush=True)

initial=call('status')
assert initial.get('hardware') and initial.get('status')=='running','Select a real running Pi'
assert not initial.get('recording') and not initial.get('transport',{}).get('active'),'Stop recording/RTP first'
destination=call('host')['ground_ip']
try:
    for host in ['8.8.8.8','224.0.0.1','169.254.169.254','240.0.0.1','0.0.0.1']:
        call('transport',dict(enabled=True,host=host),400)
    results.append(dict(name='invalid destinations rejected',ok=True))
    check('start sender',lambda:call('transport',dict(enabled=True,host=destination,port=5620,mtu=1200)))
    generation=call('status')['encoding']['generation']
    call('transport',dict(enabled=True,host=destination),400)
    for path,body in [('settings',{'fps':15}),('settings',{'record_bitrate':1500000}),
        ('action/snapshot_full',{}),('action/restart',{}),('source',{'mode':'simulator'}),
        ('profiles/pi3a-light/apply',{})]:call(path,body,400)
    results.append(dict(name='encoding guards and duplicate start',ok=True))
    time.sleep(2)
    assert call('status')['transport']['stats']['frames']>10
    name=call('action/record_start',{})['name'];time.sleep(3)
    assert call('status')['encoding']['generation']==generation
    call('transport',dict(enabled=False))
    status=call('status');assert status['recording'] and status['encoding']['generation']==generation
    results.append(dict(name='stop RTP preserves recording',ok=True))
    call('transport',dict(enabled=True,host=destination,port=5620));time.sleep(2)
    call('action/record_stop',{})
    status=call('status');assert status['transport']['active'] and status['encoding']['generation']==generation
    results.append(dict(name='stop recording preserves RTP',ok=True,recording=name))
    call('transport',dict(enabled=False));assert not call('status')['encoding']['active']
    call('transport',dict(enabled=False),400)
    results.append(dict(name='last consumer releases encoder',ok=True))
finally:
    status=call('status')
    if status.get('recording'):call('action/record_stop',{})
    if status.get('transport',{}).get('active'):call('transport',dict(enabled=False))
    call('settings',initial['settings'])
    (OUT/'transport-functional-results.json').write_text(json.dumps(results,indent=2))
print('PASS transport lifecycle:',len(results),'checks')
