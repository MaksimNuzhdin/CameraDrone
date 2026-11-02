#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if systemctl --user cat camera-studio.service >/dev/null 2>&1; then
  systemctl --user start camera-studio.service
  printf '%s\n' 'Camera Studio: http://127.0.0.1:8765/'
else
  exec python3 "$project_dir/camera_app/host.py"
fi
