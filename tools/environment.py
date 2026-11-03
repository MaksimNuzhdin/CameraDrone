"""Export reproducibility metadata without tokens, hostnames, IPs or serials."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
parser.add_argument('--source-root',type=Path,default=ROOT,help='Parent of deployed camera_app (defaults to this checkout)')
args=parser.parse_args();ROOT=args.source_root.expanduser().resolve()
os_release={}
for line in Path('/etc/os-release').read_text().splitlines():
    if '=' in line:
        key,value=line.split('=',1)
        if key in ('PRETTY_NAME','ID','VERSION_ID'):os_release[key]=value.strip('"')
versions={}
for package in ['picamera2','Flask','requests','numpy','opencv-python','opencv-python-headless']:
    try:versions[package]=importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:pass
try:
    result=subprocess.run(['dpkg-query','-W','-f=${Package}=${Version}\n','python3-picamera2','python3-opencv','python3-numpy','ffmpeg'],capture_output=True,text=True,timeout=5)
    debian={line.split('=',1)[0]:line.split('=',1)[1] for line in result.stdout.splitlines() if '=' in line}
except (OSError,subprocess.TimeoutExpired):debian={}
board=Path('/proc/device-tree/model')
source={}
for relative in ['camera_app/engine.py','camera_app/encoded_outputs.py','camera_app/rtp.py','camera_app/vision.py','camera_app/models/mobilenet_iter_73000.caffemodel']:
    path=ROOT/relative
    if path.is_file():source[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
report=dict(os=os_release,kernel=platform.release(),architecture=platform.machine(),python=platform.python_version(),
    board=board.read_text().rstrip('\0') if board.exists() else None,python_packages=versions,debian_packages=debian,source_sha256=source,
    privacy='No runtime credentials, host identity, network addresses, board serial or camera pixels included.')
if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
else:print(json.dumps(report,indent=2))
