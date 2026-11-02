"""Local host state and input library. No arbitrary file paths are accepted by the API."""
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

import cv2


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with os.fdopen(os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


class InputLibrary:
    EXTENSIONS = {'.mp4','.avi','.mov','.mkv','.webm','.jpg','.jpeg','.png'}

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory/'index.json'
        self.lock = threading.RLock()
        self.entries = load_json(self.index_path, {})
        if not isinstance(self.entries, dict):
            self.entries = {}

    def list(self):
        with self.lock:
            return [dict(id=key, **{k:v for k,v in value.items() if k!='filename'})
                    for key,value in self.entries.items() if (self.directory/value['filename']).is_file()]

    def get(self, identifier):
        with self.lock:
            if identifier not in self.entries:
                raise ValueError('Input not found in the host library')
            entry = dict(self.entries[identifier])
            path = self.directory/entry['filename']
            if path.resolve().parent != self.directory.resolve() or not path.is_file():
                raise ValueError('Input file is unavailable')
            return path, entry

    def add(self, source, display_name=None, stream=None):
        source = Path(source)
        extension = source.suffix.lower()
        if extension not in self.EXTENSIONS:
            raise ValueError('Supported inputs: MP4, AVI, MOV, MKV, WebM, JPEG and PNG')
        with self.lock:
            if shutil.disk_usage(self.directory).free < 1024*1024*1024:
                raise ValueError('Less than 1 GB free on the host')
            identifier = uuid.uuid4().hex
            target = self.directory/(identifier+extension)
            try:
                if stream is not None:
                    with target.open('wb') as handle:
                        shutil.copyfileobj(stream, handle, length=1024*1024)
                else:
                    shutil.copyfile(source, target)
                if target.stat().st_size == 0:
                    raise ValueError('Input is empty')
                if extension in {'.jpg','.jpeg','.png'}:
                    image = cv2.imread(str(target))
                    if image is None:
                        raise ValueError('Image cannot be decoded')
                    h,w=image.shape[:2];fps=0;frames=1;kind='image'
                else:
                    video = cv2.VideoCapture(str(target))
                    try:
                        ok,image=video.read()
                        if not ok:
                            raise ValueError('Video cannot be decoded')
                        h,w=image.shape[:2]
                        fps=float(video.get(cv2.CAP_PROP_FPS)) or 25
                        frames=int(video.get(cv2.CAP_PROP_FRAME_COUNT))
                        kind='video'
                    finally:
                        video.release()
                if w*h > 16777216:
                    raise ValueError('Input exceeds the 16-megapixel decode limit')
                entry=dict(name=(display_name or source.name)[:160],filename=target.name,
                           kind=kind,width=w,height=h,fps=round(fps,3),frames=frames,
                           duration_s=round(frames/fps,2) if fps>0 else None,bytes=target.stat().st_size)
                self.entries[identifier]=entry
                atomic_json(self.index_path,self.entries)
                return dict(id=identifier,**{k:v for k,v in entry.items() if k!='filename'})
            except Exception:
                target.unlink(missing_ok=True)
                raise

    def seed(self, paths):
        for path in paths:
            path=Path(path)
            if path.is_file() and not any(e['name']==path.name for e in self.entries.values()):
                self.add(path)
