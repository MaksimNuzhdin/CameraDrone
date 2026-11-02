"""Known-input tests for actual CV/AI output, independent from the live scene."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'camera_app'))
from vision import Vision

v=Vision(BASE/'camera_app/models')
results=[]

def check(name,fn):
    try:
        detail=fn();results.append(dict(name=name,ok=True,detail=detail));print('PASS',name,detail,flush=True)
    except Exception as exc:
        results.append(dict(name=name,ok=False,error=str(exc)));print('FAIL',name,exc,flush=True)

def objects():
    image=cv2.imread(str(BASE/'tests/object-sample.jpg'))
    v.configure(dict(objects=True,faces=False,qr=False,motion=False,confidence=.5))
    r=v.process(image)
    assert len(r['boxes'])>0,r
    return [(b['label'],round(b['confidence'],2)) for b in r['boxes']]

def faces():
    image=cv2.imread(str(BASE/'tests/face-sample.jpg'))
    v.configure(dict(objects=False,faces=True))
    r=v.process(image)
    assert any(b['kind']=='face' for b in r['boxes']),r
    return len(r['boxes'])

def qr():
    v.configure(dict(faces=False,qr=True))
    code=cv2.QRCodeEncoder_create().encode('CameraStudio-QR-test')
    code=cv2.copyMakeBorder(code,4,4,4,4,cv2.BORDER_CONSTANT,value=255)
    image=cv2.cvtColor(cv2.resize(code,(330,330),interpolation=cv2.INTER_NEAREST),cv2.COLOR_GRAY2BGR)
    r=v.process(image)
    assert 'CameraStudio-QR-test' in r['qr'],r
    return r['qr']

def motion():
    v.configure(dict(qr=False,motion=True))
    image=np.full((360,640,3),100,np.uint8)
    for _ in range(14):v.process(image)
    image[80:160,120:220]=250
    r=v.process(image)
    assert r['motion_pct']>1 and any(b['kind']=='motion' for b in r['boxes']),r
    return r['motion_pct']

def tracking():
    v.configure(dict(motion=False));v.reset_geometry()
    rng=np.random.default_rng(42)
    texture=rng.integers(0,255,(60,80,3),dtype=np.uint8)
    image=np.full((360,640,3),80,np.uint8);image[100:160,100:180]=texture
    v.process(image);v.track(dict(x=100/640,y=100/360,w=80/640,h=60/360))
    shifted=np.full_like(image,80);shifted[110:170,120:200]=texture
    r=v.process(shifted);b=next(b for b in r['boxes'] if b['kind']=='track')
    assert abs(b['x']-120/640)<.01 and abs(b['y']-110/360)<.01,b
    lost=v.process(np.full_like(image,80))['tracking'];assert lost['lost'],lost
    v.track(None)
    return dict(shifted_box=b,lost=lost['lost'])

check('MobileNet SSD known image',objects)
check('Face detector known image',faces)
check('QR decoding known payload',qr)
check('Motion after background warmup',motion)
check('Tracker translation and loss',tracking)
out=BASE/'artifacts';out.mkdir(exist_ok=True)
(out/'vision-results.json').write_text(json.dumps(results,indent=2))
assert all(r['ok'] for r in results)
