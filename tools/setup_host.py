"""Install relocatable user service/desktop entry. No Pi connection or sudo."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--install-service',action='store_true')
args=parser.parse_args()
subprocess.run([sys.executable,str(root/'camera_app/fetch_models.py')],check=True)
if args.install_service:
    units=Path.home()/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
    # systemd uses its own quoting and specifier rules.
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    service='''[Unit]\nDescription=Camera Studio host application\nAfter=network.target\n[Service]\nType=simple\nWorkingDirectory={root}\nExecStart={python} {entry}\nRestart=on-failure\nRestartSec=3\nKillMode=mixed\nTimeoutStopSec=30\nUMask=0077\nEnvironment=PYTHONUNBUFFERED=1\n[Install]\nWantedBy=default.target\n'''.format(root=str(root).replace('%','%%'),python=quote(sys.executable),entry=quote(root/'camera_app/host.py'))
    (units/'camera-studio.service').write_text(service)
    apps=Path.home()/'.local/share/applications';apps.mkdir(parents=True,exist_ok=True)
    (apps/'camera-studio.desktop').write_text('[Desktop Entry]\nType=Application\nName=Camera Studio\nComment=Local camera control, simulator and replay\nExec=xdg-open http://127.0.0.1:8765/\nTerminal=false\nCategories=Video;Development;\n')
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','camera-studio.service'],check=True)
print('Open http://127.0.0.1:8765/ (new installations start in Simulator mode).')
