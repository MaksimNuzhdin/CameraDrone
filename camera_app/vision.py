"""CPU vision on the latest reduced frame; independent from capture/encoding."""
import threading
import time
import math
from pathlib import Path

import cv2
import numpy as np

CLASSES = ['background', 'aeroplane', 'bicycle', 'bird', 'boat', 'bottle',
           'bus', 'car', 'cat', 'chair', 'cow', 'diningtable', 'dog', 'horse',
           'motorbike', 'person', 'pottedplant', 'sheep', 'sofa', 'train', 'tvmonitor']


def box(x, y, w, h, width, height, label, confidence=1.0):
    return dict(x=max(0, x / width), y=max(0, y / height),
                w=min(w / width, 1 - max(0, x / width)),
                h=min(h / height, 1 - max(0, y / height)),
                label=label, confidence=float(confidence))


DEFAULT_ANALYSIS = dict(objects=False, faces=False, qr=False, motion=False, confidence=0.5, interval_ms=350)


def validate_analysis_options(values):
    if not isinstance(values, dict):
        raise ValueError("Analysis options must be an object")
    unknown = set(values) - set(DEFAULT_ANALYSIS)
    if unknown:
        raise ValueError('Unknown analysis options: ' + ', '.join(sorted(unknown)))
    for name in ('objects', 'faces', 'qr', 'motion'):
        if name in values and not isinstance(values[name], bool):
            raise ValueError(name + ' must be boolean')
    if 'confidence' in values:
        value = values['confidence']
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 0.2 <= value <= 0.95:
            raise ValueError('Confidence must be a number between 0.2 and 0.95')
    if 'interval_ms' in values:
        value = values['interval_ms']
        if isinstance(value, bool) or not isinstance(value,int) or not 100 <= value <= 3000:
            raise ValueError('Analysis interval must be an integer from 100 to 3000 ms')


class Vision:
    def __init__(self, model_dir):
        cv2.setNumThreads(2)
        self.lock = threading.RLock()
        self.options = dict(DEFAULT_ANALYSIS)
        self.net = None
        self.model_error = None
        try:
            self.net = cv2.dnn.readNetFromCaffe(
                str(Path(model_dir) / 'deploy.prototxt'),
                str(Path(model_dir) / 'mobilenet_iter_73000.caffemodel'))
        except Exception as exc:
            self.model_error = str(exc)
        cascade_paths = [Path('/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml')]
        if hasattr(cv2, 'data'):
            cascade_paths.append(Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml')
        cascade_path = next((p for p in cascade_paths if p.is_file()), None)
        self.face = cv2.CascadeClassifier(str(cascade_path)) if cascade_path else cv2.CascadeClassifier()
        self.qr = cv2.QRCodeDetector()
        self.background = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=True)
        self.motion_frames = 0
        self.template = None
        self.tracking_box = None
        self.track_score = 0
        self.track_lost = False
        self.last_frame = None

    def configure(self, values):
        with self.lock:
            validate_analysis_options(values)
            if values.get('objects') and self.net is None:
                raise ValueError('Object detection model unavailable: ' + str(self.model_error))
            if values.get('faces') and self.face.empty():
                raise ValueError('Face model unavailable')
            if values.get('motion') and not self.options['motion']:
                self.background = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=True)
                self.motion_frames = 0
            self.options.update(values)
            return dict(self.options)

    def track(self, roi):
        with self.lock:
            if roi is None:
                self.template = self.tracking_box = None
                self.track_lost = False
                return
            if self.last_frame is None:
                raise ValueError('Wait for the first analysis frame')
            if not isinstance(roi, dict) or any(k not in roi or isinstance(roi[k], bool) or not isinstance(roi[k], (int,float)) or not math.isfinite(roi[k]) for k in ('x','y','w','h')):
                raise ValueError('ROI must contain finite numeric x, y, w and h values')
            h, w = self.last_frame.shape[:2]
            x, y, bw, bh = [float(roi[k]) for k in ('x', 'y', 'w', 'h')]
            if not (0 <= x < 1 and 0 <= y < 1 and bw > 0 and bh > 0 and x + bw <= 1.001 and y + bh <= 1.001):
                raise ValueError('ROI must fit inside the image')
            x, y, bw, bh = int(x*w), int(y*h), int(bw*w), int(bh*h)
            if min(bw, bh) < 12:
                raise ValueError('Select an area at least 12 analysis pixels wide and high')
            gray = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2GRAY)
            self.template = gray[y:y+bh, x:x+bw].copy()
            if self.template.std() < 4:
                self.template = None
                raise ValueError('Choose an area with more texture')
            self.tracking_box = (x, y, bw, bh)
            self.track_lost = False
            self.track_score = 1.0

    def reset_geometry(self):
        with self.lock:
            self.template = self.tracking_box = self.last_frame = None
            self.track_lost = False
            self.motion_frames = 0
            self.background = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=True)

    def process(self, frame):
        start = time.monotonic()
        with self.lock:
            self.last_frame = frame.copy()
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            histogram = cv2.calcHist([gray], [0], None, [32], [0, 256]).ravel().astype(int).tolist()
            result = dict(boxes=[], qr=[], histogram=histogram,
                          brightness=round(float(gray.mean()), 1),
                          sharpness=round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1),
                          dark_pct=round(float(np.mean(gray < 12)*100), 1),
                          clipped_pct=round(float(np.mean(gray > 245)*100), 1), motion_pct=0)
            if self.options['objects'] and self.net is not None:
                self.net.setInput(cv2.dnn.blobFromImage(frame, 0.007843, (300, 300), 127.5))
                detections = self.net.forward()
                for d in detections[0, 0]:
                    score = float(d[2]); cls = int(d[1])
                    if score >= self.options['confidence'] and 0 < cls < len(CLASSES):
                        x1, y1, x2, y2 = np.clip(d[3:7], 0, 1)
                        result['boxes'].append(dict(x=float(x1), y=float(y1), w=float(x2-x1),
                                                    h=float(y2-y1), label=CLASSES[cls], confidence=score, kind='object'))
            if self.options['faces'] and not self.face.empty():
                for x, y, bw, bh in self.face.detectMultiScale(gray, 1.15, 5, minSize=(24, 24)):
                    result['boxes'].append(dict(box(int(x), int(y), int(bw), int(bh), w, h, 'face'), kind='face'))
            if self.options['qr']:
                found, decoded, points, _ = self.qr.detectAndDecodeMulti(frame)
                if not found:
                    value, polygon, _ = self.qr.detectAndDecode(frame)
                    if polygon is not None:
                        found, decoded, points = True, (value,), polygon[np.newaxis, ...]
                if found and points is not None:
                    for value, polygon in zip(decoded, points):
                        x, y, bw, bh = cv2.boundingRect(polygon.astype(np.float32))
                        result['boxes'].append(dict(box(x, y, bw, bh, w, h, 'QR'), kind='qr'))
                        if value:
                            result['qr'].append(value[:2048])
            if self.options['motion']:
                mask = self.background.apply(frame)
                self.motion_frames += 1
                mask = cv2.threshold(mask, 240, 255, cv2.THRESH_BINARY)[1]
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                if self.motion_frames > 10:
                    result['motion_pct'] = round(float(np.mean(mask > 0)*100), 1)
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
                        if cv2.contourArea(c) > w*h*0.005:
                            result['boxes'].append(dict(box(*cv2.boundingRect(c), w, h, 'motion'), kind='motion'))
            if self.template is not None and not self.track_lost:
                x, y, bw, bh = self.tracking_box
                margin = max(40, bw//2, bh//2)
                sx, sy = max(0, x-margin), max(0, y-margin)
                ex, ey = min(w, x+bw+margin), min(h, y+bh+margin)
                search = gray[sy:ey, sx:ex]
                scores = cv2.matchTemplate(search, self.template, cv2.TM_CCOEFF_NORMED)
                _, score, _, position = cv2.minMaxLoc(scores)
                self.track_score = float(score)
                if score < 0.55:
                    self.track_lost = True
                else:
                    x, y = sx+position[0], sy+position[1]
                    self.tracking_box = (x, y, bw, bh)
                    result['boxes'].append(dict(box(x, y, bw, bh, w, h, 'tracking', score), kind='track'))
            result['tracking'] = dict(active=self.template is not None, lost=self.track_lost, confidence=self.track_score)
            result['inference_ms'] = round((time.monotonic()-start)*1000, 1)
            return result
