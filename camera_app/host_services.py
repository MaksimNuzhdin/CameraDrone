"""Host orchestration: explicit sources, local inputs, presets and profiles."""
import copy
import ipaddress
import json
import re
import secrets
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from werkzeug.serving import make_server

from benchmark import Benchmarks
from camera_api import create_camera_app
from configuration import validate_settings
from offline import OfflineCamera
from storage import InputLibrary, atomic_json, load_json
from vision import validate_analysis_options


def validate_camera_url(value):
    if not isinstance(value,str):raise ValueError('Camera URL must be text')
    parsed=urlparse(value)
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use a plain local camera URL, for example http://192.168.1.20:8081')
    hostname=parsed.hostname or ''
    try:
        address=ipaddress.ip_address(hostname)
        if not (address.is_private or address.is_loopback) or address.is_link_local or address.is_unspecified or address.is_multicast:
            raise ValueError('Only local/private camera addresses are supported')
    except ValueError as exc:
        if not re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.local',hostname):
            raise ValueError('Use a private IP address or a .local hostname') from exc
    try:port=parsed.port
    except ValueError:raise ValueError('Invalid camera port')
    if port is not None and not 1<=port<=65535:raise ValueError('Invalid camera port')
    return value.rstrip('/')


class CameraManager:
    def __init__(self,base,directory,seed_inputs=False,runtime_path=None):
        self.base=Path(base);self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        runtime=Path(runtime_path) if runtime_path else self.base/'runtime.json'
        self.runtime_path=runtime
        if not runtime.exists():
            atomic_json(runtime,dict(token=secrets.token_urlsafe(32),camera_url='http://camera.local:8081'))
            runtime.chmod(0o600)
        self.config=load_json(runtime,{})
        self.token=self.config['token']
        self.camera_url=validate_camera_url(self.config.get('camera_url','http://camera.local:8081'))
        self.library=InputLibrary(self.directory/'inputs')
        if seed_inputs:
            self.library.seed(sorted((self.base.parent/'artifacts').glob('video-*.mp4'))[:2])
        self.offline=OfflineCamera(self.directory/'offline',self.base/'models',self.library)
        offline_app=create_camera_app(self.offline,self.token)
        self.server=make_server('127.0.0.1',0,offline_app,threaded=True);self.server.daemon_threads=True
        self.local_url='http://127.0.0.1:'+str(self.server.server_port)
        self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='local-camera-api');self.server_thread.start()
        self.mode='simulator';self.generation=0
        self.session_path=self.directory/'session.json'
        saved=load_json(self.session_path,{})
        if saved.get('mode')=='pi':self.mode='pi';self.offline.set_active(False)
        elif saved.get('mode')=='replay':
            try:self.offline.switch('replay',saved.get('input_id'));self.mode='replay'
            except ValueError:pass
        self.presets_path=self.directory/'presets.json'
        self.presets=load_json(self.presets_path,{})
        self.profiles=load_json(self.base/'profiles.json',{})
        self.benchmarks=Benchmarks(self.directory/'reports',self.base/'models',self.library)

    @property
    def endpoint(self):return self.camera_url if self.mode=='pi' else self.local_url

    def describe(self):
        return dict(mode=self.mode,epoch=self.generation,camera_url=self.camera_url,
                    inputs=self.library.list(),profiles=[dict(id=k,**v) for k,v in self.profiles.items()],
                    source_name='Raspberry Pi camera' if self.mode=='pi' else self.offline.source['name'])

    def request(self,method,path,payload=None,stream=False):
        return requests.request(method,self.endpoint+path,json=payload,headers={'X-Camera-Token':self.token},
                                stream=stream,timeout=(1.5,35 if method=='POST' else 8))

    def json_request(self,method,path,payload=None):
        try:
            with self.request(method,path,payload) as response:
                data=response.json()
                if not response.ok:raise ValueError(data.get('error','Camera request failed'))
                return data
        except requests.RequestException as exc:raise RuntimeError('Camera unavailable: '+str(exc)) from exc

    def switch(self,values):
        if not isinstance(values,dict) or set(values)-{'mode','input_id','camera_url'}:
            raise ValueError('Source accepts mode, input_id and camera_url')
        mode=values.get('mode')
        if mode not in ('pi','simulator','replay'):raise ValueError('Choose pi, simulator or replay')
        url=validate_camera_url(values.get('camera_url',self.camera_url))
        # Check before changing local state; a failed switch must leave the current source intact.
        if mode=='replay':self.library.get(values.get('input_id'))
        with self.lock:
            try:
                current=self.json_request('GET','/api/status')
            except (RuntimeError,ValueError):
                current={}
            if current.get('recording'):raise ValueError('Stop recording before changing source')
            if mode=='pi':self.offline.set_active(False)
            else:self.offline.switch(mode,values.get('input_id'))
            self.camera_url=url;self.mode=mode;self.generation+=1
            atomic_json(self.session_path,dict(mode=mode,input_id=values.get('input_id')))
            self.config['camera_url']=url;atomic_json(self.runtime_path,self.config);self.runtime_path.chmod(0o600)
            return self.describe()

    @staticmethod
    def validate_preset(preset):
        if not isinstance(preset,dict) or preset.get('format')!='camera-studio-preset' or preset.get('version')!=1:
            raise ValueError('Expected a Camera Studio preset, version 1')
        name=preset.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>80:
            raise ValueError('Preset name must be 1–80 characters')
        validate_settings(preset.get('camera'))
        camera=preset['camera']
        if 'width' in camera and 'height' in camera and (camera['width'],camera['height']) not in ((640,360),(1280,720),(1920,1080)):
            raise ValueError('Invalid preset resolution pair')
        validate_analysis_options(preset.get('analysis',{}))
        return {k:copy.deepcopy(preset[k]) for k in ('format','version','name','camera','analysis') if k in preset}

    def save_preset(self,values):
        if not isinstance(values,dict):raise ValueError('Expected a preset object')
        if 'preset' in values:
            preset=self.validate_preset(values['preset'])
        else:
            status=self.json_request('GET','/api/status')
            preset=self.validate_preset(dict(format='camera-studio-preset',version=1,name=values.get('name'),camera=status['settings'],analysis=status['ai_options']))
        identifier=uuid.uuid4().hex
        with self.lock:
            self.presets[identifier]=preset;atomic_json(self.presets_path,self.presets)
        return dict(id=identifier,**preset)

    def apply_configuration(self,preset):
        current=self.json_request('GET','/api/status')
        camera=dict(preset['camera']);skipped=[]
        if current.get('supported_settings') is not None:
            skipped=sorted(set(camera)-set(current['supported_settings']))
            camera={k:v for k,v in camera.items() if k in current['supported_settings']}
        if current.get('recording'):raise ValueError('Stop recording before applying a complete profile')
        applied=False
        try:
            if camera:self.json_request('POST','/api/settings',camera);applied=True
            if preset.get('analysis'):self.json_request('POST','/api/ai',preset['analysis'])
        except Exception:
            if applied:
                original=current['settings']
                if current.get('supported_settings') is not None:original={k:v for k,v in original.items() if k in current['supported_settings']}
                self.json_request('POST','/api/settings',original)
            raise
        return dict(applied=True,skipped_hardware_settings=skipped)

    def close(self):
        self.server.shutdown();self.offline.close()
