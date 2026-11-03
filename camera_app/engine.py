"""Single camera owner, bounded latest-frame preview and independent vision worker."""
import collections
import concurrent.futures
import json
import logging
import math
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput

from vision import Vision
from encoded_outputs import CameraOutputs
from rtp import validate_transport

LOG = logging.getLogger('camera')
from configuration import DEFAULTS, RECONFIGURE, validate_settings


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if hasattr(value, 'tolist'):
        return clean(value.tolist())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class CameraEngine:
    supports_rtp = True
    def __init__(self, base):
        self.base = Path(base)
        self.data = self.base / 'data'
        self.data.mkdir(exist_ok=True)
        self.settings_path = self.data / 'settings.json'
        self.settings = dict(DEFAULTS)
        if self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                self.validate_settings(saved)
                self.settings.update(saved)
            except Exception:
                LOG.exception('Ignoring invalid saved settings')
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.jobs = queue.Queue(maxsize=16)
        self.vision = Vision(self.base / 'models')
        self.ai_settings_path = self.data / 'analysis.json'
        if self.ai_settings_path.exists():
            try:
                self.vision.configure(json.loads(self.ai_settings_path.read_text()))
            except Exception:
                LOG.exception('Ignoring invalid saved analysis settings')
        self.jpeg = None
        self.frame = None
        self.analysis_frame = None
        self.metadata = {}
        self.analysis = {}
        self.ai_timestamp = 0
        self.analysis_frame_at = 0
        self.last_analysis_supply = 0
        self.last_frame_at = 0
        self.last_preview_at = 0
        self.preview_sequence = 0
        self.capture_times = collections.deque(maxlen=120)
        self.preview_times = collections.deque(maxlen=60)
        self.events = collections.deque(maxlen=50)
        self.status = 'starting'
        self.error = None
        self.camera = None
        self.controls = {}
        self.properties = {}
        self.crop = None
        self.encoder = None
        self.encoded_output = None
        self.encoder_generation = 0
        self.rtp_output = None
        self.rtp_options = None
        self.rtp_last = None
        self.output = None
        self.recording = None
        self.metadata_file = None
        self.running = True
        self.started = time.monotonic()
        self.thermal_mode = 'normal'
        self.throttled = 0
        self.stream_clients = 0
        self.threads = [threading.Thread(target=self.capture_loop, daemon=True, name='capture'),
                        threading.Thread(target=self.analysis_loop, daemon=True, name='vision'),
                        threading.Thread(target=self.watchdog, daemon=True, name='watchdog')]
        for thread in self.threads:
            thread.start()

    def event(self, message):
        with self.lock:
            self.events.appendleft(dict(time=datetime.now(timezone.utc).isoformat(), message=message))
        LOG.info(message)

    validate_settings = staticmethod(validate_settings)

    def save_settings(self):
        temporary = self.settings_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.settings, indent=2))
        temporary.replace(self.settings_path)

    def submit(self, action, values=None):
        if not self.running:
            raise RuntimeError('Camera is stopping')
        future = concurrent.futures.Future()
        try:
            self.jobs.put_nowait((future, action, values))
        except queue.Full:
            raise RuntimeError('Camera is busy; retry shortly')
        try:
            return future.result(timeout=25)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise RuntimeError('Camera operation timed out; check status before retrying')

    def configure_camera(self):
        s = self.settings
        config = self.camera.create_video_configuration(
            main={'size': (s['width'], s['height']), 'format': 'RGB888'},
            lores={'size': (640, 360), 'format': 'YUV420'},
            transform=Transform(hflip=bool(s['rotation']), vflip=bool(s['rotation'])),
            buffer_count=6, controls={'FrameRate': s['fps']})
        self.camera.configure(config)
        self.controls = clean(self.camera.camera_controls)
        self.properties = clean(self.camera.camera_properties)
        self.crop = self.camera.camera_controls['ScalerCrop'][2]
        self.apply_controls(s)
        self.camera.start()
        self.vision.reset_geometry()
        with self.lock:
            self.frame = self.analysis_frame = self.jpeg = None
            self.analysis = {}
            self.capture_times.clear()
            self.preview_times.clear()

    def apply_controls(self, settings):
        hardware = {k: v for k, v in settings.items() if k in self.camera.camera_controls}
        if settings['AeEnable']:
            hardware.pop('ExposureTime', None)
            hardware.pop('AnalogueGain', None)
        else:
            maximum = min(int(1_000_000/settings['fps']), int(self.camera.camera_controls['ExposureTime'][1]))
            if settings['ExposureTime'] > maximum:
                raise ValueError(f'Exposure must be <= {maximum} us at this frame rate')
        if settings['AwbEnable']:
            hardware.pop('ColourGains', None)
        if settings['AfMode'] != 0:
            hardware.pop('LensPosition', None)
        if self.crop and self.crop[2] > 0:
            x, y, w, h = self.crop
            cw, ch = int(w/settings['zoom']), int(h/settings['zoom'])
            hardware['ScalerCrop'] = (x+(w-cw)//2, y+(h-ch)//2, cw, ch)
        self.camera.set_controls(hardware)

    def execute(self, action, values):
        if action == 'settings':
            self.validate_settings(values)
            candidate = {**self.settings, **values}
            if (candidate['width'], candidate['height']) not in ((640, 360), (1280, 720), (1920, 1080)):
                raise ValueError('Unsupported resolution pair')
            if not candidate['AeEnable'] and candidate['ExposureTime'] > int(1_000_000/candidate['fps']):
                raise ValueError('Exposure is longer than the frame duration')
            changed = {k for k in values if candidate[k] != self.settings[k]}
            if self.encoder and changed & (RECONFIGURE | {'record_bitrate'}):
                raise ValueError('Stop recording and RTP before changing resolution, FPS, rotation, HDR or bitrate')
            previous = self.settings
            try:
                self.settings = candidate
                if changed & RECONFIGURE:
                    self.camera.stop()
                    self.configure_camera()
                else:
                    self.apply_controls(candidate)
            except Exception:
                self.settings = previous
                if changed & RECONFIGURE:
                    try:
                        self.camera.stop()
                    except Exception:
                        pass
                    self.configure_camera()
                else:
                    self.apply_controls(previous)
                raise
            self.save_settings()
            self.event('Camera settings updated')
            return dict(self.settings)
        if action == 'autofocus':
            if 'AfMode' not in self.camera.camera_controls:
                raise ValueError('Autofocus is not available')
            self.camera.set_controls({'AfMode': 1, 'AfTrigger': 0})
            self.settings['AfMode'] = 1
            self.save_settings()
            return {'started': True}
        if action == 'snapshot_full':
            if self.encoder:
                raise ValueError('Stop recording and RTP before taking a full-resolution photo')
            self.check_storage()
            name = self.filename('photo', '.jpg')
            still_controls = {k:v for k,v in self.settings.items() if k in self.camera.camera_controls}
            if self.settings['AeEnable']:
                still_controls.pop('ExposureTime', None)
                still_controls.pop('AnalogueGain', None)
            if self.settings['AwbEnable']:
                still_controls.pop('ColourGains', None)
            if self.settings['AfMode'] != 0:
                still_controls.pop('LensPosition', None)
            if self.settings['zoom'] > 1:
                w, h = self.camera.camera_properties['PixelArraySize']
                cw, ch = int(w/self.settings['zoom']), int(h/self.settings['zoom'])
                still_controls['ScalerCrop'] = ((w-cw)//2, (h-ch)//2, cw, ch)
            config = self.camera.create_still_configuration(
                main={'size':tuple(self.camera.camera_properties['PixelArraySize']), 'format':'RGB888'},
                buffer_count=2, controls=still_controls,
                transform=Transform(hflip=bool(self.settings['rotation']), vflip=bool(self.settings['rotation'])))
            try:
                metadata = clean(self.camera.switch_mode_and_capture_file(config, str(self.data/name), delay=2))
            except Exception:
                self.camera.stop()
                self.configure_camera()
                raise
            self.apply_controls(self.settings)
            self.vision.reset_geometry()
            (self.data/Path(name).with_suffix('.json')).write_text(json.dumps(dict(metadata=metadata,settings=self.settings,full_resolution=True),indent=2))
            self.event('Saved full-resolution photo: ' + name)
            return {'name':name}
        if action == 'snapshot':
            self.check_storage()
            request = self.camera.capture_request()
            try:
                frame = request.make_array('main').copy()
                metadata = clean(request.get_metadata())
            finally:
                request.release()
            name = self.filename('photo', '.jpg')
            ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise RuntimeError('JPEG encoding failed')
            (self.data/name).write_bytes(jpeg.tobytes())
            (self.data/Path(name).with_suffix('.json')).write_text(json.dumps(dict(metadata=metadata, settings=self.settings, analysis=self.analysis,
                analysis_age_ms=round((time.monotonic()-self.ai_timestamp)*1000) if self.ai_timestamp else None), indent=2))
            self.event('Saved ' + name)
            return {'name': name}
        if action == 'record_start':
            if self.recording:
                raise ValueError('Recording is already active')
            self.check_storage()
            name = self.filename('video', '.mp4')
            output = FfmpegOutput(f'-movflags +frag_keyframe+empty_moov+default_base_moof {self.data/name}')
            output.error_callback = lambda exc: self.event('Recording output error: ' + str(exc))
            try:
                if self.encoder:self.encoded_output.add_file(output)
                else:self.ensure_encoder(file_output=output)
            except Exception:
                try:output.stop()
                except Exception:pass
                self.release_idle_encoder()
                raise
            self.output = output
            self.metadata_file = (self.data/Path(name).with_suffix('.jsonl')).open('w')
            self.metadata_file.write(json.dumps({'type':'header','settings':self.settings,'started':datetime.now(timezone.utc).isoformat()})+'\n')
            self.recording = dict(name=name, started=time.monotonic(), last_metadata=0)
            self.event('Recording started: ' + name)
            return {'name': name}
        if action == 'record_stop':
            return self.stop_recording()
        if action == 'rtp_start':
            if self.rtp_output:raise ValueError('RTP is already active')
            options=validate_transport(values)
            try:
                self.ensure_encoder()
                self.rtp_output=self.encoded_output.add_rtp(options)
                self.rtp_options=options
            except Exception:
                self.release_idle_encoder()
                raise
            self.event('RTP sender started')
            return self.transport_status()
        if action == 'rtp_stop':
            return self.stop_rtp()
        if action == 'restart':
            if self.encoder:
                raise ValueError('Stop recording and RTP before restarting the camera')
            self.camera.stop()
            self.configure_camera()
            self.event('Camera restarted')
            return {'restarted': True}
        raise ValueError('Unknown camera action')

    def ensure_encoder(self,file_output=None):
        if self.encoder:return
        encoder=H264Encoder(bitrate=int(self.settings['record_bitrate']),framerate=self.settings['fps'],iperiod=self.settings['fps'],repeat=True)
        if hasattr(encoder,'preset'):encoder.preset='ultrafast'
        if hasattr(encoder,'threads'):encoder.threads=2
        output=CameraOutputs()
        if file_output:output.add_file(file_output)
        try:self.camera.start_encoder(encoder,output,name='main')
        except Exception:
            output.stop()
            raise
        self.encoder=encoder;self.encoded_output=output;self.encoder_generation+=1

    def release_idle_encoder(self):
        if self.encoder and not self.recording and not self.rtp_output:
            encoder=self.encoder
            try:self.camera.stop_encoder(encoder)
            finally:self.encoder=self.encoded_output=None

    def transport_status(self):
        sender=self.rtp_output
        return dict(supported=True,active=bool(sender),options=dict(self.rtp_options or {}),
                    stats=sender.status() if sender else self.rtp_last,
                    auto_resume=False,codec='H264',payload_type=96)

    def stop_rtp(self):
        if not self.rtp_output:raise ValueError('No active RTP sender')
        self.rtp_last=self.rtp_output.status()
        try:self.encoded_output.remove_rtp()
        finally:
            self.rtp_output=None;self.release_idle_encoder()
        self.event('RTP sender stopped')
        return self.transport_status()

    def stop_recording(self):
        if not self.recording:
            raise ValueError('No active recording')
        name = self.recording['name']
        try:
            self.encoded_output.remove_file()
        finally:
            if self.metadata_file:
                self.metadata_file.close()
            self.recording = self.output = self.metadata_file = None
            self.release_idle_encoder()
        self.event('Recording saved: ' + name)
        return {'name': name}

    def check_storage(self):
        if shutil.disk_usage(self.data).free < 256*1024*1024:
            raise ValueError('Less than 256 MB free; download or remove recordings on the Pi')

    @staticmethod
    def filename(prefix, suffix):
        return prefix + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S-%fZ') + suffix

    def capture_loop(self):
        while self.running:
            try:
                self.camera = Picamera2()
                self.configure_camera()
                self.status, self.error = 'running', None
                self.event('Camera ready: ' + str(self.properties.get('Model', 'unknown')))
                while self.running:
                    for _ in range(4):
                        try:
                            future, action, values = self.jobs.get_nowait()
                        except queue.Empty:
                            break
                        if not future.set_running_or_notify_cancel():
                            continue
                        try:
                            future.set_result(self.execute(action, values))
                        except Exception as exc:
                            LOG.exception('Camera operation %s failed', action)
                            future.set_exception(exc)
                    request = self.camera.capture_request()
                    now = time.monotonic()
                    preview_due = self.frame is None or now-self.last_preview_at >= 1/self.effective_preview_fps() - 0.002
                    analysis_due = self.analysis_frame is None or now-self.last_analysis_supply >= self.effective_ai_interval()/2000
                    try:
                        frame = request.make_array('main').copy() if preview_due else None
                        small = cv2.cvtColor(request.make_array('lores'), cv2.COLOR_YUV2BGR_I420) if analysis_due else None
                        metadata = clean(request.get_metadata())
                    finally:
                        request.release()
                    now = time.monotonic()
                    with self.lock:
                        if frame is not None:
                            self.frame = frame
                        if small is not None:
                            self.analysis_frame = small
                            self.analysis_frame_at = self.last_analysis_supply = now
                        self.metadata = metadata
                        self.last_frame_at = now
                        self.capture_times.append(now)
                    if preview_due:
                        ok, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self.settings['jpeg_quality']])
                        if ok:
                            with self.condition:
                                self.jpeg = jpeg.tobytes()
                                self.preview_sequence += 1
                                self.last_preview_at = now
                                self.preview_times.append(now)
                                self.condition.notify_all()
                    if self.recording and now - self.recording['last_metadata'] >= 1:
                        self.recording['last_metadata'] = now
                        self.metadata_file.write(json.dumps({'type':'frame','time':datetime.now(timezone.utc).isoformat(), 'metadata':metadata})+'\n')
                        self.metadata_file.flush()
                        if self.output.output_broken:
                            self.stop_recording()
                            self.event('Recording stopped after output failure')
                        elif shutil.disk_usage(self.data).free < 256*1024*1024:
                            self.stop_recording()
                            self.event('Recording stopped: low disk space')
            except Exception as exc:
                self.status, self.error = 'recovering', str(exc)
                self.event('Capture error; retrying: ' + str(exc))
                LOG.exception('Capture loop failed')
            finally:
                if self.recording:
                    try:
                        self.stop_recording()
                    except Exception:
                        LOG.exception('Recording cleanup failed')
                if self.rtp_output:
                    try:self.stop_rtp()
                    except Exception:LOG.exception('RTP cleanup failed')
                if self.camera:
                    try:
                        self.camera.close()
                    except Exception:
                        LOG.exception('Camera close failed')
                self.camera = None
                self.encoder = self.encoded_output = None
            time.sleep(2)

    def analysis_loop(self):
        while self.running:
            start = time.monotonic()
            try:
                with self.lock:
                    frame = self.analysis_frame.copy() if self.analysis_frame is not None else None
                    frame_at = self.analysis_frame_at
                if frame is not None:
                    result = self.vision.process(frame)
                    with self.lock:
                        self.analysis = result
                        self.ai_timestamp = frame_at
            except Exception as exc:
                LOG.exception('Analysis failed')
                with self.lock:
                    self.analysis = {'error': str(exc), 'boxes': []}
            time.sleep(max(0.02, self.effective_ai_interval()/1000 - (time.monotonic()-start)))

    def effective_preview_fps(self):
        limit = {'normal':30, 'warm':8, 'hot':5}[self.thermal_mode]
        if self.stream_clients == 0:
            limit = min(limit, 2)
        return min(self.settings['preview_fps'], limit)

    def effective_ai_interval(self):
        minimum = {'normal':0, 'warm':700, 'hot':1500}[self.thermal_mode]
        return max(self.vision.options['interval_ms'], minimum)

    def watchdog(self):
        while self.running:
            time.sleep(3)
            try:
                temperature = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
                previous = self.thermal_mode
                if temperature >= 85:
                    self.thermal_mode = 'hot'
                elif temperature >= 80 or (previous == 'hot' and temperature >= 78):
                    self.thermal_mode = 'warm'
                elif temperature < 74:
                    self.thermal_mode = 'normal'
                if previous != self.thermal_mode:
                    self.event('Thermal workload mode: '+self.thermal_mode)
                output = subprocess.check_output(['vcgencmd','get_throttled'], text=True, timeout=2)
                self.throttled = int(output.strip().split('=')[1], 16)
            except Exception:
                LOG.debug('Thermal telemetry unavailable', exc_info=True)
            last_progress = self.last_frame_at or self.started
            if time.monotonic()-last_progress > 30:
                LOG.error('No frames for 30 seconds; exiting for systemd recovery')
                os._exit(1)

    @staticmethod
    def rate(times):
        return round((len(times)-1)/(times[-1]-times[0]), 1) if len(times)>1 and times[-1]>times[0] else 0

    def get_status(self):
        with self.lock:
            now = time.monotonic()
            recording = None
            if self.recording:
                path = self.data/self.recording['name']
                recording = dict(name=path.name, seconds=round(now-self.recording['started'], 1), bytes=path.stat().st_size if path.exists() else 0)
            frame_age = round((now-self.last_frame_at)*1000) if self.last_frame_at else None
            status = dict(status=self.status, error=self.error, settings=dict(self.settings),
                          metadata=dict(self.metadata), properties=dict(self.properties), controls=self.controls,
                          capture_fps=self.rate(self.capture_times) if frame_age is not None and frame_age < 3000 else 0,
                          preview_fps=self.rate(self.preview_times) if frame_age is not None and frame_age < 3000 else 0,
                          frame_age_ms=frame_age,
                          analysis_age_ms=round((now-self.ai_timestamp)*1000) if self.ai_timestamp else None,
                          analysis=self.analysis, ai_options=dict(self.vision.options),
                          capabilities=dict(objects=self.vision.net is not None, faces=not self.vision.face.empty(),
                                            qr=True, motion=True, tracking=True, model_error=self.vision.model_error),
                          recording=recording, events=list(self.events), uptime_s=round(now-self.started))
            status['transport'] = self.transport_status()
            encoder=self.encoder
            status['encoding'] = dict(active=bool(encoder),generation=self.encoder_generation,
                frames_encoded=getattr(encoder,'frames_encoded',0),single_encoder=True,
                consumers=(["recording"] if self.recording else [])+(["rtp"] if self.rtp_output else []))
            status['thermal'] = dict(mode=self.thermal_mode, throttled_hex=hex(self.throttled),
                                     current_flags=self.throttled & 0xffff,
                                     effective_preview_fps=self.effective_preview_fps(),
                                     effective_ai_interval_ms=self.effective_ai_interval(),
                                     stream_clients=self.stream_clients)
        try:
            status['temperature_c'] = round(int(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000, 1)
        except Exception:
            status['temperature_c'] = None
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        status['memory_available_mb'] = int(memory['MemAvailable'].split()[0])//1024
        status['disk_free_mb'] = shutil.disk_usage(self.data).free//(1024*1024)
        status['load'] = list(os.getloadavg())
        return status

    def frames(self):
        sequence = -1
        with self.lock:
            self.stream_clients += 1
        try:
            while self.running:
                with self.condition:
                    self.condition.wait_for(lambda: not self.running or (self.preview_sequence != sequence and self.jpeg is not None), timeout=5)
                    if not self.running:
                        break
                    if self.jpeg is None or self.preview_sequence == sequence:
                        continue
                    data, sequence = self.jpeg, self.preview_sequence
                yield b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n'
        finally:
            with self.lock:
                self.stream_clients -= 1

    def close(self):
        """Let the capture owner finalize its encoder before the process exits."""
        with self.condition:
            self.status = 'stopping'
            self.running = False
            self.condition.notify_all()
        deadline = time.monotonic() + 20
        for thread in self.threads:
            thread.join(timeout=max(0, deadline-time.monotonic()))
        while True:
            try:
                future, _, _ = self.jobs.get_nowait()
            except queue.Empty:
                break
            if not future.done():
                future.set_exception(RuntimeError('Camera stopped before this operation ran'))
        if any(thread.is_alive() for thread in self.threads):
            LOG.error('Camera workers did not finish within the shutdown deadline')
