"""Host integration tests: synthetic fixtures only; no Raspberry Pi requests."""
import io
import json
import logging
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'camera_app'))
from configuration import validate_settings
from host import create_host_app
from host_services import validate_camera_url
from vision import Vision, validate_analysis_options

logging.getLogger('werkzeug').setLevel(logging.ERROR)

class ValidationTests(unittest.TestCase):
    def test_invalid_camera_settings(self):
        for value in [None,{}, {'fps':True},{'fps':12.5},{'fps':30.0},{'width':400},{'zoom':float('nan')},{'ColourGains':[True,1]},{'HdrMode':2},{'rotation':90},{'unknown':1}]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_settings(value)
    def test_invalid_analysis(self):
        for value in [None,[],{'objects':1},{'confidence':float('inf')},{'interval_ms':1},{'faces':'yes'},{'extra':True}]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_analysis_options(value)
    def test_camera_url_boundary(self):
        for value in ['http://192.168.1.20:8081','http://camera.local:8081','http://127.0.0.1:8081']:
            self.assertEqual(validate_camera_url(value),value)
        for value in ['https://example.com','file:///etc/passwd','http://u:p@10.0.0.2','http://169.254.169.254','http://10.0.0.2/x','http://0.0.0.0','http://224.0.0.1','http://10.0.0.2:99999']:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_camera_url(value)
    def test_synthetic_tracking_and_loss(self):
        v=Vision(ROOT/'camera_app/models');rng=np.random.default_rng(42)
        texture=rng.integers(0,255,(60,80,3),dtype=np.uint8)
        image=np.full((360,640,3),80,np.uint8);image[100:160,100:180]=texture
        v.process(image);v.track(dict(x=100/640,y=100/360,w=80/640,h=60/360))
        shifted=np.full_like(image,80);shifted[110:170,120:200]=texture
        result=v.process(shifted);b=next(b for b in result['boxes'] if b['kind']=='track')
        self.assertAlmostEqual(b['x'],120/640,places=2)
        self.assertTrue(v.process(np.full_like(image,80))['tracking']['lost'])
    def test_synthetic_motion(self):
        v=Vision(ROOT/'camera_app/models');v.configure({'motion':True})
        frame=np.full((360,640,3),100,np.uint8)
        for _ in range(14):v.process(frame)
        frame[80:160,120:220]=250
        self.assertGreater(v.process(frame)['motion_pct'],1)

class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.directory=Path(cls.tmp.name)
        cls.app=create_host_app(cls.directory/'data',False,cls.directory/'runtime.json')
        cls.manager=cls.app.extensions['camera_manager'];cls.client=cls.app.test_client()
        cls.headers={'X-Camera-Client':'1'}
        cls.wait(lambda:cls.manager.offline.jpeg is not None)
    @classmethod
    def tearDownClass(cls):
        cls.manager.close();cls.tmp.cleanup()
    @classmethod
    def wait(cls,predicate,timeout=8):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.05)
        raise AssertionError('Timed out waiting for offline operation')
    def post(self,path,data,expected=200):
        response=self.client.post(path,json=data,headers=self.headers)
        self.assertEqual(response.status_code,expected,response.get_data(as_text=True))
        return response.get_json()
    def status(self):return self.client.get('/api/status').get_json()
    def test_01_capture_and_auth(self):
        status=self.status();self.assertFalse(status['hardware']);self.assertEqual(status['status'],'running')
        self.assertGreaterEqual(status['frame_age_ms'],0)
        self.assertEqual(self.client.post('/api/settings',json={'zoom':2}).status_code,403)
        import requests
        self.assertEqual(requests.get(self.manager.local_url+'/api/status',timeout=3).status_code,401)
        self.assertEqual(self.client.get('/api/frame.jpg').status_code,200)
        self.assertGreater(self.client.get('/api/clock').get_json()['unix_ns'],0)
        self.assertEqual(self.client.get('/latency-target').status_code,200)
        self.post('/api/transport',{'enabled':True,'host':'127.0.0.1'},400)
        with self.client.get('/stream.mjpg',buffered=False) as response:
            self.assertIn(b'Content-Type: image/jpeg',next(response.response))
    def test_02_settings_qr_and_hardware_rejection(self):
        self.post('/api/settings',{'ExposureTime':12345},400)
        self.post('/api/action/snapshot_full',{},400)
        self.post('/api/settings',{'width':640,'height':360,'fps':15})
        self.post('/api/settings',{'width':1280},400)
        self.post('/api/ai',{'qr':True,'interval_ms':100})
        self.wait(lambda:'Camera Studio offline QR test' in self.status().get('analysis',{}).get('qr',[]))
    def test_03_presets_and_profile(self):
        preset=self.post('/api/presets',{'name':'Synthetic test'},201)
        exported=self.client.get('/api/presets/'+preset['id']).get_json()
        self.assertEqual(exported['format'],'camera-studio-preset')
        self.post('/api/settings',{'Brightness':.3})
        self.post('/api/presets/'+preset['id']+'/apply',{})
        self.assertEqual(self.status()['settings']['Brightness'],0)
        result=self.post('/api/profiles/pi3a-light/apply',{})
        self.assertTrue(result['applied'])
        self.post('/api/benchmarks',{'analysis':[],'input_id':'unknown'},400)
    def test_04_snapshot_record_decode(self):
        photo=self.post('/api/action/snapshot',{})['name']
        response=self.client.get('/api/media/'+photo)
        self.assertIsNotNone(cv2.imdecode(np.frombuffer(response.data,np.uint8),cv2.IMREAD_COLOR))
        video=self.post('/api/action/record_start',{})['name']
        self.post('/api/source',{'mode':'simulator'},400)
        self.assertEqual(self.client.get('/api/media/'+video).status_code,400)
        time.sleep(1.4)
        result=self.post('/api/action/record_stop',{})
        self.assertGreater(result['encoded_frames'],5)
        cap=cv2.VideoCapture(str(self.manager.offline.data/video))
        try:
            decoded=0
            while True:
                ok,frame=cap.read()
                if not ok:break
                decoded+=1;self.assertEqual(frame.shape[:2],(360,640))
            self.assertEqual(decoded,result['encoded_frames'])
        finally:cap.release()
        response=self.client.get('/api/media/view/'+video,headers={'Range':'bytes=0-63'})
        self.assertEqual(response.status_code,206);self.assertEqual(len(response.data),64)
    def test_05_library_replay_benchmark(self):
        frame=self.manager.offline.synthetic(1)
        ok,encoded=cv2.imencode('.png',frame);self.assertTrue(ok)
        response=self.client.post('/api/inputs',data={'file':(io.BytesIO(encoded.tobytes()),'synthetic.png')},headers=self.headers)
        self.assertEqual(response.status_code,201);identifier=response.get_json()['id']
        self.post('/api/source',{'mode':'replay','input_id':identifier})
        self.wait(lambda:self.status()['metadata'].get('Source')=='replay')
        self.post('/api/playback',{'paused':True})
        self.post('/api/benchmarks',{'input_id':identifier,'analysis':[]},400)
        self.post('/api/benchmarks',{'input_id':identifier,'analysis':{'qr':True}},202)
        self.wait(lambda:self.manager.benchmarks.list()['job']['status']!='running',20)
        job=self.manager.benchmarks.list()['job'];self.assertEqual(job['status'],'complete',job)
        with self.client.get('/api/reports/'+job['id']+'.json') as response:report=response.get_json()
        self.assertIn('Camera Studio offline QR test',report['summary']['qr_payloads'])
        with self.client.get('/api/reports/'+job['id']+'.csv') as response:self.assertEqual(response.status_code,200)
        # An independent generated clip exercises seek, pause and looping.
        path=self.directory/'replay-fixture.avi'
        writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),15,(640,360))
        self.assertTrue(writer.isOpened())
        for i in range(30):writer.write(cv2.resize(self.manager.offline.synthetic(i/15),(640,360)))
        writer.release()
        entry=self.manager.library.add(path)
        self.post('/api/source',{'mode':'replay','input_id':entry['id']})
        self.post('/api/playback',{'seek_s':.2,'paused':True})
        self.assertTrue(self.status()['playback']['paused'])
        self.post('/api/playback',{'seek_s':999},400)
        self.post('/api/playback',{'seek_s':1.8,'paused':False})
        self.wait(lambda:self.status()['playback']['loops']>0)
        self.post('/api/source',{'mode':'simulator'})
        # A bad token/unavailable former source must not trap the user in Pi mode.
        with patch.object(self.manager,'json_request',side_effect=ValueError('Camera authentication required')):
            self.manager.switch({'mode':'simulator'})
    def test_06_offline_never_contacts_pi(self):
        original=self.manager.camera_url;self.manager.camera_url='http://192.168.99.99:8081'
        try:
            with patch('host.requests.request',wraps=__import__('requests').request) as called:
                self.assertEqual(self.client.get('/api/status').status_code,200)
                self.assertTrue(all('127.0.0.1' in args.args[1] for args in called.call_args_list))
        finally:self.manager.camera_url=original

if __name__=='__main__':unittest.main()
