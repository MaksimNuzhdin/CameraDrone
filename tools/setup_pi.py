"""Provision Camera Studio on Raspberry Pi OS, without replacing the boot image.

--check is read-only. Package/service changes require explicit flags. Pair the
private runtime.json through deploy-studio.sh before installing the service.
"""
import argparse
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PACKAGES=['python3-picamera2','python3-flask','python3-requests','python3-opencv','opencv-data','ffmpeg']
MODULES=['picamera2','flask','requests','cv2','numpy']

def report():
    model_path=Path('/proc/device-tree/model')
    model=model_path.read_text().rstrip('\0') if model_path.exists() else None
    os_info={}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1);os_info[key]=value.strip('"')
    modules={name:importlib.util.find_spec(name) is not None for name in MODULES}
    return dict(board=model,architecture=platform.machine(),kernel=platform.release(),
        os=os_info.get('PRETTY_NAME'),supported_board=bool(model and model.startswith('Raspberry Pi')),
        supported_os=os_info.get('ID') in ('debian','raspbian'),modules=modules,
        ffmpeg=__import__('shutil').which('ffmpeg') is not None)

def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--install-packages',action='store_true')
    parser.add_argument('--install-service',action='store_true')
    args=parser.parse_args();state=report()
    print(json.dumps(state,indent=2))
    if not state['supported_board'] or not state['supported_os']:
        raise SystemExit('Use Raspberry Pi OS on a Raspberry Pi; refusing changes on this system.')
    if args.install_packages:
        prefix=[] if os.geteuid()==0 else ['sudo']
        subprocess.run(prefix+['apt-get','update'],check=True)
        subprocess.run(prefix+['apt-get','install','-y']+PACKAGES,check=True)
        state=report()
    if not all(state['modules'].values()) or not state['ffmpeg']:
        raise SystemExit('Missing dependencies; rerun with --install-packages or install the documented OS packages.')
    if args.install_service:
        if os.geteuid()==0:raise SystemExit('Install the user service as its normal camera user, not root.')
        runtime=ROOT/'camera_app/runtime.json'
        try:token=json.loads(runtime.read_text())['token']
        except (OSError,ValueError,KeyError):raise SystemExit('Pair private camera_app/runtime.json from the Ubuntu host first.')
        if not isinstance(token,str) or len(token)<32:raise SystemExit('Runtime token must have at least 32 characters.')
        runtime.chmod(0o600)
        subprocess.run([sys.executable,str(ROOT/'camera_app/fetch_models.py')],check=True)
        units=Path.home()/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
        unit='[Unit]\nDescription=Camera Studio Pi backend\nAfter=network.target\n[Service]\nExecStart='+quote(sys.executable)+' '+quote(ROOT/'camera_app/backend.py')+'\nRestart=on-failure\nRestartSec=3\nKillMode=mixed\nTimeoutStopSec=30\nUMask=0077\nEnvironment=PYTHONUNBUFFERED=1\n[Install]\nWantedBy=default.target\n'
        (units/'camera-backend.service').write_text(unit)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','enable','--now','camera-backend.service'],check=True)
        print('Enable boot startup once with: sudo loginctl enable-linger "$USER"')
    print('Pi software check complete. No EEPROM, boot order or radio driver changes were made.')

if __name__=='__main__':main()
