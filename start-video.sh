#!/usr/bin/env bash
# Legacy MPEG-TS proof of concept. Separate from the RTP air-link tools.
set -euo pipefail
: "${PI_TARGET:?Set PI_TARGET=user@private-ip}"
: "${GROUND_IP:?Set GROUND_IP to the ground station private IPv4 address}"
[[ "$GROUND_IP" =~ ^[0-9.]+$ ]] || exit 1
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$PI_TARGET" bash -s -- "$GROUND_IP" <<'REMOTE'
set -euo pipefail
if systemctl --user is-active --quiet camera-backend.service; then
  echo 'Stop camera-backend.service before using the legacy camera owner.' >&2
  exit 1
fi
systemd-run --user --unit=cameradrone-video --collect /usr/bin/rpicam-vid --camera 0 --nopreview --timeout 0 --width 1280 --height 720 --framerate 30 --bitrate 4000000 --intra 30 --inline --codec libav --libav-video-codec libx264 --low-latency --libav-format mpegts -o "udp://$1:5600?pkt_size=1316"
REMOTE
