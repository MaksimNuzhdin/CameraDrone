"""Real-Pi restart/recording regression; requires explicit matching SSH target.

This intentionally restarts the selected Pi camera backend during a short recording.
It never deletes media and uses strict FFmpeg decoding to detect truncated tails.
"""
import argparse
import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
import requests

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pi-target',required=True,help='user@host, matching the selected Pi URL hostname')
parser.add_argument('--known-hosts',type=Path)
parser.add_argument('--base-url',default='http://127.0.0.1:8765')
parser.add_argument('--seconds',type=float,default=3.5)
args=parser.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_-]+@[A-Za-z0-9.:-]+',args.pi_target):parser.error('Invalid SSH target')
if not 3<=args.seconds<=15:parser.error('seconds must be 3..15')
base=args.base_url.rstrip('/')
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=8']
if args.known_hosts:ssh+=['-o','UserKnownHostsFile='+str(args.known_hosts.resolve())]
ssh.append(args.pi_target)

def ready():
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        try:
            response=requests.get(base+'/api/status',timeout=3)
            if response.ok:
                status=response.json();age=status.get('frame_age_ms')
                if status.get('hardware') and status.get('status')=='running' and age is not None and age<2000:return status
        except requests.RequestException:pass
        time.sleep(.2)
    raise RuntimeError('Real camera did not become ready')

initial=ready()
if initial.get('recording'):raise RuntimeError('Stop the current recording before this check')
if urlparse(initial['host']['camera_url']).hostname!=args.pi_target.rsplit('@',1)[1]:
    raise RuntimeError('SSH hostname must match the selected camera URL; refusing to restart a different host')
response=requests.post(base+'/api/action/record_start',json={},headers={'X-Camera-Client':'1'},timeout=35)
response.raise_for_status();name=response.json()['name']
if not re.fullmatch(r'video-[0-9TZ-]+\.mp4',name):raise RuntimeError('Unexpected recording name')
time.sleep(args.seconds)
started=time.monotonic()
subprocess.run(ssh+['systemctl --user restart camera-backend.service'],check=True,timeout=40)
status=ready();elapsed=round(time.monotonic()-started,2)
assert not status['recording']
assert status['settings']==initial['settings']
assert status['ai_options']==initial['ai_options']
command=['ffmpeg','-v','error','-xerror','-err_detect','explode','-i','camera_app/data/'+name,'-enc_time_base','1:90000','-fps_mode','passthrough','-progress','pipe:1','-f','null','-']
result=subprocess.run(ssh+[shlex.join(command)],capture_output=True,text=True,timeout=30)
if result.returncode or result.stderr.strip():raise AssertionError('Strict decoder failed: '+result.stderr)
counts=[int(line.split('=',1)[1]) for line in result.stdout.splitlines() if line.startswith('frame=')]
assert counts and max(counts)>=int(initial['settings']['fps']*args.seconds*.75),counts
report=dict(recovered_seconds=elapsed,recording_decoded_frames=max(counts),decoder_errors=0,settings_persisted=True)
out=Path(__file__).resolve().parents[1]/'artifacts';out.mkdir(exist_ok=True)
(out/'restart-recording-results.json').write_text(json.dumps(report,indent=2))
print('PASS restart during recording',json.dumps(report))
