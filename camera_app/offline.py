"""Software test camera and prerecorded-input playback. No camera drivers needed."""
import collections
import copy
import json
import logging
import math
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from configuration import DEFAULTS, RECONFIGURE, RANGES, validate_settings
from recording import HostRecorder
from storage import atomic_json, load_json
from vision import Vision

LOG=logging.getLogger('offline')
HARDWARE_SETTINGS={'AeEnable','ExposureTime','AnalogueGain','ExposureValue','AwbEnable',
                   'AwbMode','ColourGains','AeMeteringMode','AeExposureMode','AfMode',
                   'LensPosition','HdrMode','NoiseReductionMode'}
SOFTWARE_SETTINGS=set(DEFAULTS)-HARDWARE_SETTINGS


class OfflineCamera:
    def __init__(self, directory, model_dir, library):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.data=self.directory/'media';self.data.mkdir(exist_ok=True)
        self.settings_path=self.directory/'settings.json'
        self.ai_settings_path=self.directory/'analysis.json'
        self.settings=copy.deepcopy(DEFAULTS)
        saved=load_json(self.settings_path,{})
        if saved:
            try:
                validate_settings(saved)
                self.settings.update(saved)
            except ValueError:LOG.warning('Ignoring invalid offline settings')
        self.lock=threading.RLock();self.condition=threading.Condition(self.lock)
        self.vision=Vision(model_dir)
        try:
            self.vision.configure(load_json(self.ai_settings_path,{'qr':True}))
        except ValueError:LOG.warning('Ignoring invalid offline analysis settings')
        self.library=library
        self.source={'kind':'simulator','name':'Synthetic test camera'}
        self.input_path=None;self.video=None;self.image=None;self.last_input=None
        self.paused=False;self.position_s=0;self.loops=0;self.source_index=0;self.phase=0
        self.source_generation=0
        self.active=True;self.running=True;self.status='starting';self.error=None
        self.jpeg=None;self.frame=None;self.analysis_frame=None
        self.analysis={};self.metadata={};self.ai_timestamp=0;self.analysis_frame_at=0
        self.last_frame_at=0;self.preview_sequence=0;self.stream_clients=0
        self.capture_times=collections.deque(maxlen=120)
        self.preview_times=collections.deque(maxlen=60)
        self.events=collections.deque(maxlen=50)
        self.started=time.monotonic();self.source_started=self.started
        self.recording=None;self.recorder=None;self.metadata_file=None
        self._wake=threading.Event()
        self.qr_image=None
        if hasattr(cv2,'QRCodeEncoder_create'):
            qr=cv2.QRCodeEncoder_create().encode('Camera Studio offline QR test')
            qr=cv2.copyMakeBorder(qr,4,4,4,4,cv2.BORDER_CONSTANT,value=255)
            self.qr_image=cv2.cvtColor(cv2.resize(qr,(264,264),interpolation=cv2.INTER_NEAREST),cv2.COLOR_GRAY2BGR)
        self.threads=[threading.Thread(target=self.capture_loop,daemon=True,name='offline-capture'),
                      threading.Thread(target=self.analysis_loop,daemon=True,name='offline-vision')]
        for thread in self.threads:thread.start()

    def event(self,message):
        self.events.appendleft(dict(time=datetime.now(timezone.utc).isoformat(),message=message))
        LOG.info(message)

    def set_active(self,value):
        with self.lock:
            if not value and self.recording:
                raise ValueError('Stop recording before changing source')
            self.active=value
            self._wake.set()

    def switch(self,kind,input_id=None):
        if kind not in ('simulator','replay'):
            raise ValueError('Unknown offline source')
        path=entry=None
        if kind=='replay':path,entry=self.library.get(input_id)
        candidate=None;image=None
        if path is not None:
            if entry['kind']=='image':image=cv2.imread(str(path))
            else:
                candidate=cv2.VideoCapture(str(path))
                if not candidate.isOpened():
                    candidate.release();raise ValueError('Replay cannot be opened')
        try:
            with self.lock:
                if self.recording:raise ValueError('Stop recording before changing source')
                if self.video:self.video.release()
                self.video=candidate;self.image=image;self.input_path=path
                self.source=({'kind':'simulator','name':'Synthetic test camera'} if kind=='simulator' else
                             dict(kind='replay',name=entry['name'],input_id=input_id,input=entry))
                self.last_input=None;self.phase=0;self.source_index=0;self.position_s=0;self.loops=0
                self.paused=False;self.source_started=time.monotonic();self.source_generation+=1
                self.frame=self.jpeg=self.analysis_frame=None;self.analysis={}
                self.capture_times.clear();self.preview_times.clear();self.vision.reset_geometry()
                self.active=True;self._wake.set();self.event('Source: '+self.source['name'])
        except Exception:
            if candidate:candidate.release()
            raise

    def playback(self,values):
        if not isinstance(values,dict) or set(values)-{'paused','seek_s'}:
            raise ValueError('Playback accepts paused and seek_s')
        with self.lock:
            if self.source['kind']!='replay':raise ValueError('Choose a replay input first')
            if 'paused' in values:
                if not isinstance(values['paused'],bool):raise ValueError('paused must be boolean')
                self.paused=values['paused']
            if 'seek_s' in values:
                value=values['seek_s'];duration=self.source['input'].get('duration_s')
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or not duration or value>=duration:
                    raise ValueError('Seek position is outside the input duration')
                if self.video:
                    self.video.set(cv2.CAP_PROP_POS_MSEC,value*1000)
                    self.source_index=int(value*self.source['input']['fps'])
                    self.last_input=None;self.phase=0;self.position_s=value
                    self.vision.reset_geometry()
            return self.playback_status()

    def playback_status(self):
        return dict(paused=self.paused,position_s=round(self.position_s,2),loops=self.loops,
                    duration_s=self.source.get('input',{}).get('duration_s'))

    def synthetic(self,elapsed):
        frame=np.full((720,1280,3),(27,31,34),np.uint8)
        colors=[(235,235,235),(20,210,210),(210,210,20),(20,210,20),(210,20,210),(20,20,210),(210,20,20),(20,20,20)]
        for i,color in enumerate(colors):frame[88:210,i*160:(i+1)*160]=color
        cv2.putText(frame,'CAMERA STUDIO / SOFTWARE TEST SOURCE',(36,48),cv2.FONT_HERSHEY_SIMPLEX,.8,(198,238,158),2)
        cv2.putText(frame,'SIMULATED - NO CAMERA HARDWARE',(36,265),cv2.FONT_HERSHEY_SIMPLEX,.9,(235,235,235),2)
        cv2.putText(frame,f'Elapsed {elapsed:07.2f}s  |  Frame {self.source_index}',(36,310),cv2.FONT_HERSHEY_SIMPLEX,.7,(145,155,158),1)
        x=int(350+(math.sin(elapsed*.6)+1)*300);y=380
        cv2.rectangle(frame,(x,y),(x+130,y+110),(70,110,235),-1)
        for i in range(8):cv2.line(frame,(x+i*16,y),(x+i*16,y+110),(240,240,240),2)
        cv2.putText(frame,'TRACK ME',(x+8,y+65),cv2.FONT_HERSHEY_SIMPLEX,.55,(10,20,20),2)
        if self.qr_image is not None:frame[330:594,30:294]=self.qr_image
        ramp=np.tile(np.arange(256,dtype=np.uint8),(60,1))
        frame[600:660,36:1244]=cv2.cvtColor(cv2.resize(ramp,(1208,60)),cv2.COLOR_GRAY2BGR)
        cv2.putText(frame,'Software transforms only. Exposure, autofocus and HDR require Raspberry Pi.',(36,700),cv2.FONT_HERSHEY_SIMPLEX,.55,(145,155,158),1)
        return frame

    def read_source(self):
        if self.source['kind']=='simulator':
            self.source_index+=1
            return self.synthetic(time.monotonic()-self.source_started)
        if self.image is not None:return self.image.copy()
        if self.paused and self.last_input is not None:return self.last_input.copy()
        native_fps=self.source['input']['fps']
        self.phase+=native_fps/self.settings['fps']
        reads=int(self.phase);self.phase-=reads
        if self.last_input is None:reads=max(1,reads)
        for _ in range(reads):
            ok,frame=self.video.read()
            if not ok:
                self.video.set(cv2.CAP_PROP_POS_FRAMES,0);self.source_index=0;self.loops+=1
                ok,frame=self.video.read()
            if not ok:raise RuntimeError('Replay decoder stopped producing frames')
            self.last_input=frame;self.source_index+=1
        self.position_s=self.source_index/native_fps
        return self.last_input.copy()

    def transform(self,frame):
        s=self.settings;h,w=frame.shape[:2]
        if s['zoom']>1:
            cw,ch=int(w/s['zoom']),int(h/s['zoom']);x,y=(w-cw)//2,(h-ch)//2
            frame=frame[y:y+ch,x:x+cw]
        frame=cv2.resize(frame,(s['width'],s['height']),interpolation=cv2.INTER_AREA)
        if s['rotation']:frame=cv2.rotate(frame,cv2.ROTATE_180)
        if s['Contrast']!=1 or s['Brightness']!=0:
            frame=np.clip(frame.astype(np.float32)*s['Contrast']+s['Brightness']*128,0,255).astype(np.uint8)
        if s['Saturation']!=1:
            hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV);hsv[:,:,1]=np.clip(hsv[:,:,1].astype(float)*s['Saturation'],0,255).astype(np.uint8)
            frame=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        if s['Sharpness']!=1:
            blurred=cv2.GaussianBlur(frame,(0,0),1)
            amount=s['Sharpness']-1
            frame=cv2.addWeighted(frame,1+amount,blurred,-amount,0)
        return frame

    def capture_loop(self):
        deadline=time.monotonic();last_preview=0;last_analysis=0
        while self.running:
            if not self.active:
                self._wake.wait(.5);self._wake.clear();deadline=time.monotonic();continue
            try:
                with self.lock:
                    frame=self.transform(self.read_source());now=time.monotonic()
                    self.frame=frame;self.last_frame_at=now;self.capture_times.append(now)
                    self.metadata=dict(Source=self.source['kind'],Hardware=False,
                        SourceFrame=self.source_index,SourcePositionSeconds=self.position_s,
                        HostMonotonicNs=time.monotonic_ns(),FrameDuration=int(1_000_000/self.settings['fps']))
                    if now-last_analysis>.12:
                        self.analysis_frame=cv2.resize(frame,(640,360));self.analysis_frame_at=now;last_analysis=now
                    target=self.settings['preview_fps'] if self.stream_clients else min(2,self.settings['preview_fps'])
                    if now-last_preview>=1/target-.002:
                        ok,jpeg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,self.settings['jpeg_quality']])
                        if ok:
                            self.jpeg=jpeg.tobytes();self.preview_sequence+=1;self.preview_times.append(now)
                            self.condition.notify_all();last_preview=now
                    if self.recorder:
                        self.recorder.submit(frame)
                        if now-self.recording['last_metadata']>=1:
                            self.recording['last_metadata']=now
                            self.metadata_file.write(json.dumps(dict(type='frame',metadata=self.metadata))+'\n');self.metadata_file.flush()
                            if shutil.disk_usage(self.data).free<256*1024*1024:self._stop_recording()
                    self.status='running';self.error=None
                    fps=self.settings['fps']
                deadline+=1/fps
                if deadline<time.monotonic()-.2:deadline=time.monotonic()
                self._wake.wait(max(0,deadline-time.monotonic()));self._wake.clear()
            except Exception as exc:
                LOG.exception('Offline capture failed')
                with self.lock:
                    self.status='error';self.error=str(exc)
                    if self.recorder:
                        try:self._stop_recording()
                        except Exception:LOG.exception('Recorder cleanup failed')
                self._wake.wait(.5);self._wake.clear()

    def analysis_loop(self):
        while self.running:
            start=time.monotonic()
            try:
                with self.lock:
                    frame=self.analysis_frame.copy() if self.active and self.analysis_frame is not None else None
                    stamp=self.analysis_frame_at;generation=self.source_generation
                if frame is not None:
                    result=self.vision.process(frame)
                    with self.lock:
                        if generation==self.source_generation:self.analysis=result;self.ai_timestamp=stamp
            except Exception as exc:
                LOG.exception('Offline vision failed')
                with self.lock:self.analysis={'error':str(exc),'boxes':[]}
            time.sleep(max(.02,self.vision.options['interval_ms']/1000-(time.monotonic()-start)))

    def submit(self,action,values=None):
        with self.lock:
            if action=='settings':
                validate_settings(values)
                changed={k for k,v in values.items() if v!=self.settings[k]}
                if changed&HARDWARE_SETTINGS:
                    raise ValueError('These settings require camera hardware: '+', '.join(sorted(changed&HARDWARE_SETTINGS)))
                candidate={**self.settings,**values}
                if (candidate['width'],candidate['height']) not in ((640,360),(1280,720),(1920,1080)):
                    raise ValueError('Unsupported resolution pair')
                if self.recording and changed&(RECONFIGURE|{'record_bitrate'}):
                    raise ValueError('Stop recording before changing capture format or bitrate')
                self.settings=candidate;atomic_json(self.settings_path,self.settings)
                if changed&{'width','height','zoom','rotation'}:
                    self.vision.reset_geometry();self.source_generation+=1;self.analysis={}
                self._wake.set();self.event('Software image settings updated')
                return dict(self.settings)
            if action in ('autofocus','snapshot_full'):
                raise ValueError('This feature requires the real camera')
            if action=='restart':
                if self.recording:raise ValueError('Stop recording before restarting')
                source=dict(self.source)
                self.switch(source['kind'],source.get('input_id'))
                return {'restarted':True}
            if action=='snapshot':
                if self.frame is None:raise RuntimeError('Wait for the first offline frame')
                self.check_storage();name=self.filename('photo','.jpg')
                ok,data=cv2.imencode('.jpg',self.frame,[cv2.IMWRITE_JPEG_QUALITY,95])
                if not ok:raise RuntimeError('Snapshot encoding failed')
                (self.data/name).write_bytes(data.tobytes())
                atomic_json(self.data/Path(name).with_suffix('.json'),dict(source=self.source,hardware=False,metadata=self.metadata,settings=self.settings,analysis=self.analysis))
                self.event('Saved offline photo: '+name);return {'name':name}
            if action=='record_start':
                if self.recording:raise ValueError('Recording is already active')
                self.check_storage();name=self.filename('video','.mp4')
                self.recorder=HostRecorder(self.data/name,self.settings['width'],self.settings['height'],self.settings['fps'],self.settings['record_bitrate'])
                self.recording=dict(name=name,started=time.monotonic(),last_metadata=0)
                self.metadata_file=(self.data/Path(name).with_suffix('.jsonl')).open('w')
                self.metadata_file.write(json.dumps(dict(type='header',hardware=False,source=self.source,settings=self.settings,codec='H264 / GStreamer x264'))+'\n')
                self.event('Offline recording started: '+name);return {'name':name}
            if action=='record_stop':return self._stop_recording()
            raise ValueError('Unknown camera action')

    def _stop_recording(self):
        if not self.recording:raise ValueError('No active recording')
        name=self.recording['name'];recorder=self.recorder
        self.recorder=None;self.recording=None
        try:
            recorder.stop()
        finally:
            self.metadata_file.close();self.metadata_file=None
        self.event('Offline recording saved: '+name)
        return dict(name=name,encoded_frames=recorder.frames,dropped_frames=recorder.dropped)

    def check_storage(self):
        if shutil.disk_usage(self.data).free<256*1024*1024:raise ValueError('Less than 256 MB free')

    @staticmethod
    def filename(prefix,suffix):
        return prefix+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ')+suffix

    @staticmethod
    def rate(values):
        return round((len(values)-1)/(values[-1]-values[0]),1) if len(values)>1 and values[-1]>values[0] else 0

    def get_status(self):
        with self.lock:
            now=time.monotonic()
            recording=None
            if self.recording:
                path=self.data/self.recording['name']
                recording=dict(name=path.name,seconds=round(now-self.recording['started'],1),bytes=path.stat().st_size if path.exists() else 0,
                               dropped_frames=self.recorder.dropped,encoded_frames=self.recorder.frames)
            result=dict(status=self.status,error=self.error,settings=copy.deepcopy(self.settings),metadata=dict(self.metadata),
                controls={k:[*RANGES.get(k,(0,1)),self.settings[k]] for k in SOFTWARE_SETTINGS},
                supported_settings=sorted(SOFTWARE_SETTINGS),properties={'Model':'Software test source'},
                capture_fps=self.rate(self.capture_times),preview_fps=self.rate(self.preview_times),
                frame_age_ms=round((now-self.last_frame_at)*1000) if self.last_frame_at else None,
                analysis_age_ms=round((now-self.ai_timestamp)*1000) if self.ai_timestamp else None,
                analysis=self.analysis,ai_options=dict(self.vision.options),
                capabilities=dict(objects=self.vision.net is not None,faces=not self.vision.face.empty(),qr=True,motion=True,tracking=True,full_resolution=False),
                recording=recording,events=list(self.events),uptime_s=round(now-self.started),temperature_c=None,
                thermal=dict(mode='offline',current_flags=0,effective_preview_fps=self.settings['preview_fps'],effective_ai_interval_ms=self.vision.options['interval_ms']),
                source=dict(self.source),playback=self.playback_status(),hardware=False)
        mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        result['memory_available_mb']=int(mem['MemAvailable'].split()[0])//1024
        result['disk_free_mb']=shutil.disk_usage(self.data).free//(1024*1024)
        return result

    def frames(self):
        sequence=-1
        with self.lock:self.stream_clients+=1
        try:
            while self.running and self.active:
                with self.condition:
                    self.condition.wait_for(lambda:not self.running or not self.active or (self.jpeg is not None and self.preview_sequence!=sequence),timeout=2)
                    if not self.active or not self.running:break
                    if self.jpeg is None or sequence==self.preview_sequence:continue
                    image=self.jpeg;sequence=self.preview_sequence
                yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(image)).encode()+b'\r\n\r\n'+image+b'\r\n'
        finally:
            with self.lock:self.stream_clients-=1

    def close(self):
        self.running=False;self._wake.set()
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:thread.join(timeout=3)
        with self.lock:
            if self.recording:self._stop_recording()
            if self.video:self.video.release()
