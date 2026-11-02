#!/usr/bin/env bash
set -euo pipefail
systemctl --user stop camera-studio.service
printf '%s\n' 'Host application stopped. The Raspberry Pi is managed separately.'
