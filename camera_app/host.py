"""Ubuntu application with explicit real-camera, simulator and replay sources."""
import json
import logging
import os
import re
import signal
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory, stream_with_context
from werkzeug.exceptions import HTTPException
from werkzeug.serving import make_server

from host_services import CameraManager

BASE=Path(__file__).resolve().parent


def create_host_app(directory=None, seed_inputs=False, runtime_path=None):
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=512*1024*1024
    manager=CameraManager(BASE,directory or os.environ.get('CAMERA_HOST_DATA',BASE.parent/'host-data'),seed_inputs=seed_inputs,runtime_path=runtime_path)
    app.extensions['camera_manager']=manager

    @app.before_request
    def validate_request():
        if request.method=='POST':
            if request.headers.get('X-Camera-Client')!='1':
                return jsonify(error='Use the camera application to change settings'),403
            if request.path!='/api/inputs':
                if request.content_length and request.content_length>16384:
                    return jsonify(error='JSON request exceeds 16 KB'),413
                value=request.get_json()
                try:json.dumps(value,allow_nan=False)
                except (ValueError,TypeError):raise ValueError('Request must contain finite JSON values')

    @app.errorhandler(Exception)
    def errors(exc):
        if isinstance(exc,HTTPException):return jsonify(error=exc.description),exc.code
        if isinstance(exc,ValueError):return jsonify(error=str(exc)),400
        if isinstance(exc,(RuntimeError,requests.RequestException)):
            return jsonify(error=str(exc)),503
        app.logger.exception('Host request failed')
        return jsonify(error='Host operation failed; check the application log'),500

    @app.get('/')
    def index():return render_template('index.html')

    @app.get('/api/host')
    def host_info():return jsonify(manager.describe())

    @app.post('/api/source')
    def source():return jsonify(manager.switch(request.get_json()))

    @app.post('/api/playback')
    def playback():
        if manager.mode=='pi':raise ValueError('Playback is only available for local input files')
        return jsonify(manager.offline.playback(request.get_json()))

    @app.get('/api/inputs')
    def inputs():return jsonify(inputs=manager.library.list())

    @app.post('/api/inputs')
    def upload():
        upload=request.files.get('file')
        if not upload or not upload.filename:raise ValueError('Choose an input video or image')
        result=manager.library.add(Path(upload.filename).name,display_name=Path(upload.filename).name,stream=upload.stream)
        return jsonify(result),201

    @app.get('/api/presets')
    def presets():
        with manager.lock:return jsonify(presets=[dict(id=k,**v) for k,v in manager.presets.items()])

    @app.post('/api/presets')
    def save_preset():return jsonify(manager.save_preset(request.get_json())),201

    @app.get('/api/presets/<identifier>')
    def export_preset(identifier):
        if identifier not in manager.presets:raise ValueError('Preset not found')
        return Response(json.dumps(manager.presets[identifier],indent=2),mimetype='application/json',
                        headers={'Content-Disposition':'attachment; filename="camera-preset.json"'})

    @app.post('/api/presets/<identifier>/apply')
    def apply_preset(identifier):
        if identifier not in manager.presets:raise ValueError('Preset not found')
        return jsonify(manager.apply_configuration(manager.presets[identifier]))

    @app.post('/api/profiles/<identifier>/apply')
    def apply_profile(identifier):
        if identifier not in manager.profiles:raise ValueError('Profile not found')
        return jsonify(manager.apply_configuration(manager.profiles[identifier]))

    @app.get('/api/benchmarks')
    def benchmarks():return jsonify(manager.benchmarks.list())

    @app.post('/api/benchmarks')
    def start_benchmark():return jsonify(manager.benchmarks.start(request.get_json())),202

    @app.get('/api/reports/<filename>')
    def report(filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.(json|csv)',filename):raise ValueError('Invalid report name')
        return send_from_directory(manager.benchmarks.directory,filename,as_attachment=True)

    @app.get('/api/health')
    def health():return jsonify(application='Camera Studio',version='0.2.0',source=manager.mode,hardware_connected=None)

    def forward(path,streaming=False,inline=False):
        started=time.monotonic();epoch=manager.generation
        payload=request.get_json() if request.method=='POST' else None
        try:
            headers={'X-Camera-Token':manager.token}
            if request.headers.get('Range'):headers['Range']=request.headers['Range']
            upstream=requests.request(request.method,manager.endpoint+path,json=payload,headers=headers,
                stream=True,timeout=(1.5,35 if request.method=='POST' else 8))
        except requests.RequestException as exc:
            return jsonify(error='Selected source unavailable: '+str(exc),source=manager.mode),503
        headers={k:v for k,v in upstream.headers.items() if k.lower() in
                 ('content-type','content-disposition','cache-control','content-range','accept-ranges')}
        if inline:headers.pop('Content-Disposition',None)
        if streaming or path.startswith('/api/media/') or path.endswith('.jpg'):
            def generate():
                try:
                    for chunk in upstream.iter_content(chunk_size=8192):
                        if streaming and epoch!=manager.generation:break
                        yield chunk
                except requests.RequestException:
                    app.logger.info('Preview disconnected')
                finally:upstream.close()
            return Response(stream_with_context(generate()),status=upstream.status_code,headers=headers)
        try:
            value=upstream.json()
            if path=='/api/status' and upstream.ok:
                value['host']=dict(camera_url=manager.camera_url,api_roundtrip_ms=round((time.monotonic()-started)*1000,1))
                value['source_epoch']=epoch
                if manager.mode=='pi':
                    value['hardware']=True;value['source']=dict(kind='pi',name='Raspberry Pi camera')
                else:value['hardware']=False
            return jsonify(value),upstream.status_code
        except (ValueError,requests.RequestException):
            return jsonify(error='Selected source returned an incomplete response'),503
        finally:upstream.close()

    @app.get('/stream.mjpg')
    def stream():return forward('/stream.mjpg',streaming=True)

    @app.get('/api/media/view/<name>')
    def view_media(name):
        if Path(name).name!=name or not name.startswith(('photo-','video-')):raise ValueError('Invalid media name')
        return forward('/api/media/'+name,inline=True)

    @app.route('/api/<path:path>',methods=['GET','POST'])
    def camera_proxy(path):
        allowed={'GET':{'status','frame.jpg','media'},'POST':{'settings','ai','track','action/snapshot','action/snapshot_full',
                     'action/record_start','action/record_stop','action/restart','action/autofocus'}}
        if path not in allowed[request.method] and not (request.method=='GET' and path.startswith('media/') and '/' not in path[6:]):
            return jsonify(error='Unknown API route'),404
        return forward('/api/'+path)

    return app


if __name__=='__main__':
    def shutdown(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,shutdown)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    app=create_host_app()
    server=make_server('127.0.0.1',int(os.environ.get('CAMERA_HOST_PORT','8765')),app,threaded=True)
    server.daemon_threads=True
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:app.extensions['camera_manager'].close()
