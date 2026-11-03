"""The same camera API contract serves real hardware and offline sources."""
import hmac
import json
import time
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_from_directory
from storage import atomic_json
from version import VERSION


def create_camera_app(engine, token):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 16384

    @app.before_request
    def authorize():
        supplied = request.headers.get('X-Camera-Token', '')
        if not hmac.compare_digest(supplied, token):
            return jsonify(error='Camera authentication required'), 401


    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400


    @app.errorhandler(RuntimeError)
    def unavailable(exc):
        return jsonify(error=str(exc)), 503


    @app.errorhandler(Exception)
    def unexpected(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception('API request failed')
        return jsonify(error=str(exc)), 500


    @app.get('/api/clock')
    def clock():
        return jsonify(unix_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())

    @app.post('/api/transport')
    def transport():
        if not getattr(engine,'supports_rtp',False):raise ValueError('RTP requires the real Pi camera')
        values=request.get_json()
        if not isinstance(values,dict) or not isinstance(values.get('enabled'),bool):raise ValueError('enabled must be boolean')
        options={k:v for k,v in values.items() if k!='enabled'}
        if not values['enabled'] and options:raise ValueError('Stop RTP with enabled=false only')
        return jsonify(engine.submit('rtp_start',options) if values['enabled'] else engine.submit('rtp_stop'))

    @app.get('/api/status')
    def status():
        value=engine.get_status();value['api_version']=VERSION
        return jsonify(value)


    @app.get('/stream.mjpg')
    def stream():
        return Response(engine.frames(), mimetype='multipart/x-mixed-replace; boundary=frame',
                        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


    @app.get('/api/frame.jpg')
    def frame():
        with engine.lock:
            image = engine.jpeg
        if image is None:
            raise RuntimeError('Camera is starting')
        return Response(image, mimetype='image/jpeg', headers={'Cache-Control':'no-store'})


    @app.post('/api/settings')
    def settings():
        return jsonify(engine.submit('settings', request.get_json()))


    @app.post('/api/ai')
    def ai():
        values = request.get_json()
        if not isinstance(values, dict):
            raise ValueError('Expected an object')
        with engine.vision.lock:
            result = engine.vision.configure(values)
            atomic_json(engine.ai_settings_path,result)
        return jsonify(result)


    @app.post('/api/track')
    def track():
        values = request.get_json()
        if not isinstance(values, dict):
            raise ValueError('Expected an object')
        engine.vision.track(values.get('roi'))
        return jsonify(ok=True)


    @app.post('/api/action/<action>')
    def action(action):
        if action not in ('snapshot','snapshot_full','record_start','record_stop','restart','autofocus'):
            raise ValueError('Unknown action')
        return jsonify(engine.submit(action))


    @app.get('/api/media')
    def media():
        with engine.lock:
            active = engine.recording['name'] if engine.recording else None
        files = []
        for path in sorted(engine.data.iterdir(), key=lambda p: p.name, reverse=True):
            if path.is_file() and path.name.startswith(('photo-', 'video-')) and path.suffix in ('.jpg','.mp4','.json','.jsonl'):
                stat = path.stat()
                files.append(dict(name=path.name, bytes=stat.st_size, modified=stat.st_mtime,
                                  recording=bool(active and path.stem == Path(active).stem)))
        return jsonify(files=files[:200])


    @app.get('/api/media/<name>')
    def download(name):
        if not name.startswith(('photo-','video-')) or Path(name).name != name:
            raise ValueError('Invalid media filename')
        with engine.lock:
            if engine.recording and Path(name).stem == Path(engine.recording['name']).stem:
                raise ValueError('Stop recording before downloading this file')
        return send_from_directory(engine.data, name, as_attachment=True)

    return app
