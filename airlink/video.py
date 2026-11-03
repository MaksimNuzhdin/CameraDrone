"""Standalone RTP/H264 transport bench. Never opens a CSI camera or changes WiFi."""
import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path

PROFILES=json.loads((Path(__file__).with_name('profiles.json')).read_text())
CAPS='application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000'

def sender(profile,host,port,buffers=None,h264=False):
    p=profile
    if h264:
        source=['fdsrc','fd=0','!','h264parse','!']
    else:
        source=['videotestsrc','is-live=true','pattern=ball']
        if buffers:source+=['num-buffers='+str(buffers)]
        source+=['!',f"video/x-raw,width={p['width']},height={p['height']},framerate={p['fps']}/1",'!',
                 'x264enc','tune=zerolatency','speed-preset=ultrafast',f"bitrate={p['bitrate_kbps']}",
                 f"key-int-max={p['fps']}",'bframes=0','byte-stream=true','!','h264parse','!']
    return ['gst-launch-1.0','-q','-e']+source+['rtph264pay','pt=96','config-interval=-1',f"mtu={p['mtu']}",'!',
            'udpsink',f'host={host}',f'port={port}','sync=false','async=false']

def receiver(profile,bind,port,headless=False,frames=None,output=None):
    command=['gst-launch-1.0','-q','-e','udpsrc',f'address={bind}',f'port={port}','buffer-size=212992',f'caps={CAPS}','!',
             'queue','max-size-buffers=256','max-size-bytes=307200','max-size-time=0','leaky=downstream','!',
             'rtpjitterbuffer',f"latency={profile['jitter_ms']}",'drop-on-latency=true','!',
             'rtph264depay','!','h264parse','!','avdec_h264','!','videoconvert','!']
    if frames:command+=['identity',f'eos-after={frames}','!']
    if output:command+=['video/x-raw,format=BGR','!','filesink',f'location={output}','sync=false']
    elif headless:command+=['fakesink','sync=false']
    else:command+=['autovideosink','sync=false']
    return command

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['send-test','send-h264-stdin','receive'])
    parser.add_argument('--profile',choices=PROFILES,default='bench')
    parser.add_argument('--host',default='127.0.0.1',help='Destination for sender; bind address for receiver')
    parser.add_argument('--port',type=int,default=5600)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--print-only',action='store_true')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Port must be 1024..65535')
    if args.mode=='receive':command=receiver(PROFILES[args.profile],args.host,args.port,args.headless)
    else:command=sender(PROFILES[args.profile],args.host,args.port,h264=args.mode=='send-h264-stdin')
    print(shlex.join(command),flush=True)
    if not args.print_only:
        if not shutil.which(command[0]):parser.error('Install GStreamer; see docs/SETUP.md')
        try:raise SystemExit(subprocess.call(command))
        except KeyboardInterrupt:pass
