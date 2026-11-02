"""Repeatable, bounded host-side analysis of known input files."""
import csv
import json
import platform
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from storage import atomic_json, load_json
from vision import DEFAULT_ANALYSIS, Vision, validate_analysis_options


class Benchmarks:
    def __init__(self, directory, model_dir, library):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.model_dir=model_dir;self.library=library
        self.lock=threading.Lock();self.job=None

    def list(self):
        reports=[]
        for path in sorted(self.directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            report=load_json(path,{})
            if report.get('id'):reports.append({k:report.get(k) for k in ['id','name','created','summary','processor','options']})
        with self.lock:job=dict(self.job) if self.job else None
        return dict(job=job,reports=reports[:100])

    def start(self,values):
        if not isinstance(values,dict) or set(values)-{'input_id','analysis','stride','max_frames'}:
            raise ValueError('Unknown benchmark options')
        path,entry=self.library.get(values.get('input_id'))
        analysis=values.get('analysis',{'objects':True})
        validate_analysis_options(analysis)
        options={**DEFAULT_ANALYSIS,**analysis}
        validate_analysis_options(options)
        stride=values.get('stride',6);maximum=values.get('max_frames',300)
        if isinstance(stride,bool) or not isinstance(stride,int) or not 1<=stride<=120:
            raise ValueError('Frame stride must be an integer from 1 to 120')
        if isinstance(maximum,bool) or not isinstance(maximum,int) or not 1<=maximum<=1000:
            raise ValueError('Maximum analyzed frames must be from 1 to 1000')
        with self.lock:
            if self.job and self.job['status']=='running':raise ValueError('A benchmark is already running')
            identifier=uuid.uuid4().hex
            self.job=dict(id=identifier,status='running',analyzed_frames=0,input_name=entry['name'],error=None)
        thread=threading.Thread(target=self._run,args=(identifier,path,entry,options,stride,maximum),daemon=True,name='benchmark')
        thread.start()
        return dict(id=identifier)

    def _run(self,identifier,path,entry,options,stride,maximum):
        started=time.monotonic();video=None
        try:
            vision=Vision(self.model_dir);vision.configure(options)
            rows=[];classes=Counter();index=0
            image=cv2.imread(str(path)) if entry['kind']=='image' else None
            if image is None:video=cv2.VideoCapture(str(path))
            while len(rows)<maximum:
                if image is not None:
                    frame=image
                else:
                    ok,frame=video.read()
                    if not ok:break
                if index%stride==0:
                    result=vision.process(cv2.resize(frame,(640,360)))
                    classes.update(b['label'] for b in result['boxes'])
                    rows.append(dict(frame=index,time_s=round(index/entry['fps'],4) if entry['fps'] else 0,**result))
                    with self.lock:self.job['analyzed_frames']=len(rows)
                index+=1
                if image is not None:break
            if not rows:raise RuntimeError('No frames were analyzed')
            timing=[r['inference_ms'] for r in rows]
            summary=dict(analyzed_frames=len(rows),decoded_frames=index,elapsed_s=round(time.monotonic()-started,3),
                         inference_p50_ms=round(float(np.percentile(timing,50)),2),
                         inference_p95_ms=round(float(np.percentile(timing,95)),2),
                         detections=sum(len(r['boxes']) for r in rows),class_counts=dict(classes),
                         qr_payloads=sorted({q for r in rows for q in r['qr']}))
            report=dict(id=identifier,name=entry['name'],created=datetime.now(timezone.utc).isoformat(),
                        processor='Ubuntu host / '+platform.machine(),options=options,stride=stride,
                        summary=summary,frames=rows,limitations='Runtime and detections only. No ground-truth accuracy or Raspberry Pi performance is inferred.')
            atomic_json(self.directory/(identifier+'.json'),report)
            with (self.directory/(identifier+'.csv')).open('w',newline='') as handle:
                writer=csv.writer(handle);writer.writerow(['frame','time_s','inference_ms','detections','classes','brightness','sharpness','motion_pct'])
                for row in rows:
                    writer.writerow([row['frame'],row['time_s'],row['inference_ms'],len(row['boxes']),';'.join(b['label'] for b in row['boxes']),row['brightness'],row['sharpness'],row['motion_pct']])
            with self.lock:self.job.update(status='complete',summary=summary)
        except Exception as exc:
            with self.lock:self.job.update(status='error',error=str(exc))
        finally:
            if video:video.release()
