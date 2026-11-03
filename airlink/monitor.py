"""Ground RTP decoder and clock-calibrated software latency monitor.

Requires Ubuntu python3-gi / gir1.2-gstreamer-1.0. No camera pixels are saved.
Latency starts at the Pi encoder output and ends at decoded host appsink:
exposure, ISP, encoding and display scanout are deliberately NOT included.
"""
import argparse
import ipaddress
import json
import signal
import struct
import sys
import threading
import time
from pathlib import Path
import requests
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst


def calibrate(base,attempts=8):
    samples=[]
    try:
        source=requests.get(base+'/api/status',timeout=2);source.raise_for_status()
        if not source.json().get('hardware'):return None
    except (requests.RequestException,ValueError):return None
    for _ in range(attempts):
        start=time.time_ns()
        try:
            response=requests.get(base+'/api/clock',timeout=2);response.raise_for_status();remote=response.json()['unix_ns']
            end=time.time_ns();samples.append((end-start,remote-(start+end)//2))
        except (requests.RequestException,ValueError,KeyError):pass
    if not samples:return None
    rtt,offset=min(samples)
    return dict(offset_ns=offset,min_rtt_ms=round(rtt/1e6,3),offset_uncertainty_ms=round(rtt/2e6,3))


def wire(data):
    if len(data)<12 or data[0]>>6!=2:return None
    seq,stamp,ssrc=struct.unpack('!HII',data[2:12]);offset=12+4*(data[0]&15);sent=None
    if data[0]&16 and len(data)>=offset+4:
        profile,words=struct.unpack('!HH',data[offset:offset+4])
        if profile==0xCD01 and words>=2 and len(data)>=offset+12:sent=struct.unpack('!Q',data[offset+4:offset+12])[0]
    return seq,stamp,ssrc,sent


from timing import latency_summary
from sequence import SequenceCounter


def run(args):
    Gst.init(None);lock=threading.RLock();stopping=threading.Event();started=time.monotonic()
    state=dict(frames=0,packets=0,bytes=0,first_frame_s=None,max_decode_gap_ms=0,width=None,height=None)
    sequences=SequenceCounter();stamps={};latencies=[];frame_times=[];errors=[];warnings=[];calibration=None
    command=(f'udpsrc address={args.bind} port={args.port} buffer-size=212992 caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" '
        '! queue name=ingress max-size-buffers=256 max-size-bytes=307200 max-size-time=0 leaky=downstream '
        f'! rtpjitterbuffer name=jitter latency={args.jitter_ms} drop-on-latency=true do-lost=true '
        '! rtph264depay wait-for-keyframe=true ! h264parse ! avdec_h264 ! videoconvert '
        '! video/x-raw,format=RGB ! appsink name=frames emit-signals=true sync=false max-buffers=2 drop=true')
    pipeline=Gst.parse_launch(command);jitter=pipeline.get_by_name('jitter');sink=pipeline.get_by_name('frames')
    def packet_probe(pad,info):
        buf=info.get_buffer()
        if buf:
            with lock:
                state['packets']+=1;state['bytes']+=buf.get_size()
                if buf.get_size()>=12:
                    header=buf.extract_dup(0,12);sequences.observe(struct.unpack('!H',header[2:4])[0],struct.unpack('!I',header[8:12])[0])
        return Gst.PadProbeReturn.OK
    def timestamp_probe(pad,info):
        buf=info.get_buffer()
        if buf:
            parsed=wire(buf.extract_dup(0,buf.get_size()))
            if parsed and parsed[3]:
                with lock:
                    stamps[buf.pts]=parsed[3]
                    while len(stamps)>600:stamps.pop(next(iter(stamps)))
        return Gst.PadProbeReturn.OK
    def sample_ready(element):
        sample=element.emit('pull-sample')
        if sample is None:return Gst.FlowReturn.EOS
        buf=sample.get_buffer();now=time.monotonic();wall=time.time_ns()
        caps=sample.get_caps().get_structure(0)
        with lock:
            state['frames']+=1
            if state['first_frame_s'] is None:state['first_frame_s']=round(now-started,4)
            if frame_times:state['max_decode_gap_ms']=max(state['max_decode_gap_ms'],round((now-frame_times[-1])*1000,3))
            frame_times.append(now);state['width']=caps.get_value('width');state['height']=caps.get_value('height')
            stamp=stamps.pop(buf.pts,None)
            if stamp is not None and calibration:latencies.append((wall-stamp+calibration['offset_ns'])/1e6)
        return Gst.FlowReturn.OK
    jitter.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER,packet_probe)
    jitter.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER,timestamp_probe)
    sink.connect('new-sample',sample_ready)
    signal.signal(signal.SIGTERM,lambda *_:stopping.set())
    signal.signal(signal.SIGINT,lambda *_:stopping.set())
    pipeline.set_state(Gst.State.PLAYING)
    calibration=calibrate(args.control_url) if args.control_url else None
    bus=pipeline.get_bus()
    try:
        while time.monotonic()-started<args.seconds and not stopping.is_set():
            message=bus.timed_pop_filtered(200*Gst.MSECOND,Gst.MessageType.ERROR|Gst.MessageType.WARNING|Gst.MessageType.EOS)
            if message:
                if message.type==Gst.MessageType.ERROR:
                    err,debug=message.parse_error();errors.append(str(err));break
                if message.type==Gst.MessageType.WARNING:
                    err,debug=message.parse_warning()
                    if len(warnings)<20:warnings.append(str(err))
                if message.type==Gst.MessageType.EOS:break
            if args.output and int(time.monotonic()-started)%5==0:
                with lock:progress=dict(state,elapsed_s=round(time.monotonic()-started,2),latency_samples=len(latencies),jitter=jitter.get_property('stats').to_string())
                target=args.output.with_suffix('.progress.json');target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(progress,indent=2))
    finally:
        stats=jitter.get_property('stats')
        jitter_stats={k:stats.get_value(k) for k in ['num-pushed','num-lost','num-late','num-duplicates','avg-jitter'] if stats.has_field(k)}
        pipeline.set_state(Gst.State.NULL)
    after=calibrate(args.control_url) if args.control_url else None
    duration=time.monotonic()-started
    active_fps=(len(frame_times)-1)/(frame_times[-1]-frame_times[0]) if len(frame_times)>1 else 0
    report=dict(state,rtp_input=sequences.status(),duration_s=round(duration,3),decoded_fps=round(active_fps,3),errors=errors,warnings=warnings,jitter=jitter_stats,
        latency=latency_summary(latencies,calibration,after),
        receiver=dict(bind=args.bind,port=args.port,jitter_ms=args.jitter_ms),pixels_saved=False)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
    return 0 if state['frames']>0 and not errors else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind',default='127.0.0.1');parser.add_argument('--port',type=int,default=5600)
    parser.add_argument('--seconds',type=float,default=30);parser.add_argument('--jitter-ms',type=int,default=30)
    parser.add_argument('--control-url',default='http://127.0.0.1:8765');parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:ipaddress.IPv4Address(args.bind)
    except ValueError:parser.error('bind must be IPv4')
    if not 1024<=args.port<=65535 or not 1<=args.seconds<=3600 or not 0<=args.jitter_ms<=200:parser.error('Invalid port, duration or jitter')
    raise SystemExit(run(args))
