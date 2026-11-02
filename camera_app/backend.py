"""Raspberry Pi entry point. Importing the host app never imports Picamera2."""
import json
import logging
import os
from pathlib import Path
from werkzeug.serving import make_server
from camera_api import create_camera_app


def main():
    from engine import CameraEngine
    base = Path(__file__).resolve().parent
    token = json.loads((base/'runtime.json').read_text())['token']
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    engine = CameraEngine(base)
    app = create_camera_app(engine, token)
    server = make_server('0.0.0.0', int(os.environ.get('CAMERA_PORT','8081')), app, threaded=True)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == '__main__':
    main()
