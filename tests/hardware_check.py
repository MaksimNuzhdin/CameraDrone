"""Exercise the real camera through the Ubuntu API; restores camera settings."""
import json
import time
from pathlib import Path

import cv2
import requests

BASE='http://127.0.0.1:8765/api/'
OUT=Path(__file__).resolve().parents[1]/'artifacts'
OUT.mkdir(exist_ok=True)
results=[]


def call(path, body=None, expected=200):
    r=requests.request('GET' if body is None else 'POST',BASE+path,
                       json=body,headers={'X-Camera-Client':'1'},timeout=35)
    if r.status_code!=expected:
        raise AssertionError(f'{path}: {r.status_code} {r.text[:500]}')
    return r.json()


def check(name, fn):
    try:
        detail=fn()
        results.append(dict(name=name,ok=True,detail=detail))
        print('PASS',name,detail or '',flush=True)
    except Exception as e:
        results.append(dict(name=name,ok=False,error=str(e)))
        print('FAIL',name,str(e),flush=True)


def settings(values):
    return call('settings',values)


def manual():
    settings({'AeEnable':False,'ExposureTime':5000,'AnalogueGain':2.0})
    time.sleep(1)
    m=call('status')['metadata']
    assert abs(m['ExposureTime']-5000)<500,m
    assert abs(m['AnalogueGain']-2)<.3,m
    settings({'AeEnable':True})
    return {k:m[k] for k in ('ExposureTime','AnalogueGain')}


def white_balance():
    settings({'AwbEnable':False,'ColourGains':[1.6,1.2]})
    time.sleep(1)
    gains=call('status')['metadata']['ColourGains']
    assert abs(gains[0]-1.6)<.1 and abs(gains[1]-1.2)<.1,gains
    settings({'AwbEnable':True})
    return gains


def modes():
    evidence=[]
    for w,h,fps in ((640,360,15),(1920,1080,30),(1280,720,30)):
        settings({'width':w,'height':h,'fps':fps})
        time.sleep(2)
        s=call('status'); assert s['status']=='running' and s['frame_age_ms']<2000,s
        r=requests.get(BASE+'frame.jpg',timeout=10);r.raise_for_status()
        path=OUT/f'frame-{w}x{h}.jpg';path.write_bytes(r.content)
        image=cv2.imread(str(path));assert image is not None and image.shape[:2]==(h,w)
        evidence.append(dict(size=[w,h],capture_fps=s['capture_fps']))
    return evidence


def photo():
    name=call('action/snapshot',{})['name']
    r=requests.get(BASE+'media/'+name,timeout=10);r.raise_for_status()
    path=OUT/name;path.write_bytes(r.content)
    assert cv2.imread(str(path)) is not None
    meta=call('media/'+name.replace('.jpg','.json'))
    assert 'ExposureTime' in meta['metadata']
    return name


def recording():
    name=call('action/record_start',{})['name']
    call('settings',{'width':1920,'height':1080},expected=400)
    call('settings',{'record_bitrate':8000000},expected=400)
    call('action/snapshot_full',{},expected=400)
    call('action/record_start',{},expected=400)
    call('media/'+name,expected=400)
    time.sleep(5)
    s=call('status');assert s['recording'] and s['recording']['bytes']>1000,s
    call('action/record_stop',{})
    r=requests.get(BASE+'media/'+name,timeout=20);r.raise_for_status()
    path=OUT/name;path.write_bytes(r.content)
    capture=cv2.VideoCapture(str(path));count=0
    while True:
        ok,frame=capture.read()
        if not ok:break
        assert frame.shape[:2]==(720,1280)
        count+=1
    capture.release();assert count>90,count
    return dict(name=name,decoded_frames=count,bytes=path.stat().st_size)


def full_photo():
    name=call('action/snapshot_full',{})['name']
    r=requests.get(BASE+'media/'+name,timeout=20);r.raise_for_status()
    path=OUT/name;path.write_bytes(r.content)
    image=cv2.imread(str(path));assert image is not None and image.shape[:2]==(2592,4608)
    metadata=call('media/'+name.replace('.jpg','.json'))
    assert metadata['full_resolution']
    time.sleep(1)
    s=call('status');assert s['frame_age_ms']<1000 and s['settings']['width']==1280
    return dict(name=name,size=[4608,2592])


def ai():
    call('ai',dict(objects=True,faces=True,qr=True,motion=True,interval_ms=350))
    time.sleep(5)
    s=call('status');a=s['analysis'];assert 'error' not in a,a
    assert a['inference_ms']>0 and s['capture_fps']>20,s
    return dict(inference_ms=a['inference_ms'],capture_fps=s['capture_fps'],boxes=a['boxes'])


def tracking():
    call('track',{'roi':{'x':.25,'y':.2,'w':.2,'h':.2}})
    time.sleep(1)
    s=call('status');assert s['analysis']['tracking']['active'],s['analysis']
    result=s['analysis']['tracking']
    call('track',{'roi':None})
    return result


def zoom():
    before=call('status')['metadata'].get('ScalerCrop')
    settings({'zoom':2})
    time.sleep(1)
    after=call('status')['metadata'].get('ScalerCrop')
    assert before and after and after[2]<before[2],(before,after)
    settings({'zoom':1})
    return dict(before=before,after=after)


original=call('status')['settings']
try:
    check('validation: unknown control',lambda:call('settings',{'NotAControl':1},expected=400))
    check('validation: invalid resolution',lambda:call('settings',{'width':123},expected=400))
    check('validation: invalid AI confidence',lambda:call('ai',{'confidence':2},expected=400))
    check('manual exposure and gain reach sensor',manual)
    check('manual white balance reaches ISP',white_balance)
    check('brightness / contrast / saturation / sharpness',lambda:settings({'Brightness':.1,'Contrast':1.2,'Saturation':.8,'Sharpness':1.3,'ExposureValue':.25,'NoiseReductionMode':2}))
    settings(original)
    check('digital zoom changes sensor crop',zoom)
    check('resolution and FPS reconfiguration',modes)
    check('180 degree rotation',lambda:settings({'rotation':180}))
    settings({'rotation':0})
    check('Pi 5 HDR enable',lambda:settings({'HdrMode':3}))
    time.sleep(1)
    check('Pi 5 HDR capture',lambda:call('status')['status']=='running' or (_ for _ in ()).throw(AssertionError('not running')))
    settings({'HdrMode':0})
    check('autofocus request',lambda:call('action/autofocus',{}))
    settings({'AfMode':0,'LensPosition':0})
    check('snapshot and metadata download',photo)
    check('12 MP photo and preview recovery',full_photo)
    check('H264 recording and MP4 decoding',recording)
    check('all analysis modes on live camera',ai)
    check('ROI tracking on live camera',tracking)
    check('camera restart',lambda:call('action/restart',{}))
finally:
    if call('status')['recording']:
        call('action/record_stop',{})
    settings(original)
    call('ai',dict(objects=True,faces=False,qr=False,motion=False,interval_ms=350))
    call('track',{'roi':None})
    (OUT/'hardware-results.json').write_text(json.dumps(results,indent=2))
assert all(r['ok'] for r in results), 'Some hardware checks failed; see artifacts/hardware-results.json'
