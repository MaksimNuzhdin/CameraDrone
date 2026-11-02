#!/usr/bin/env bash
# Explicit hardware-only deployment. Existing media is not copied or deleted.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
: "${PI_TARGET:?Set PI_TARGET=user@private-ip; see docs/SETUP.md}"
[[ "$PI_TARGET" =~ ^[a-zA-Z0-9_-]+@[a-zA-Z0-9.:-]+$ ]] || { echo 'Invalid PI_TARGET' >&2; exit 1; }
ssh_opts=(-o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=yes)
if [[ -f "$project_dir/pi_known_hosts" ]]; then ssh_opts+=(-o UserKnownHostsFile="$project_dir/pi_known_hosts"); fi
python3 "$project_dir/camera_app/fetch_models.py"
test -f "$project_dir/camera_app/runtime.json" || { echo 'Start the host once to create private runtime.json.' >&2; exit 1; }
bundle="$(mktemp)"
trap 'rm -f "$bundle"' EXIT
tar -C "$project_dir" --exclude='camera_app/data' --exclude='camera_app/__pycache__' -cf "$bundle" camera_app
ssh "${ssh_opts[@]}" "$PI_TARGET" 'systemctl --user stop camera-backend.service 2>/dev/null || true'
ssh "${ssh_opts[@]}" "$PI_TARGET" 'tar -xf - -C "$HOME"; chmod 600 "$HOME/camera_app/runtime.json"' < "$bundle"
ssh "${ssh_opts[@]}" "$PI_TARGET" python3 - <<'PY'
import subprocess
from pathlib import Path
home=Path.home();units=home/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
def q(v):return '"'+str(v).replace('%','%%').replace('"','\\"')+'"'
(units/'camera-backend.service').write_text('[Unit]\nDescription=Camera Studio Pi backend\nAfter=network.target\n[Service]\nExecStart=/usr/bin/python3 '+q(home/'camera_app/backend.py')+'\nRestart=on-failure\nRestartSec=3\nEnvironment=PYTHONUNBUFFERED=1\n[Install]\nWantedBy=default.target\n')
subprocess.run(['systemctl','--user','daemon-reload'],check=True)
subprocess.run(['systemctl','--user','enable','--now','camera-backend.service'],check=True)
PY
printf '%s\n' 'Pi deployed. Select Raspberry Pi in the host UI; enable user lingering on the Pi for boot startup.'
