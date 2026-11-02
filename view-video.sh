#!/usr/bin/env bash
set -euo pipefail
exec gst-launch-1.0 -e \
  udpsrc address="${GROUND_IP:-127.0.0.1}" port=5600 buffer-size=212992 \
  caps="video/mpegts,systemstream=(boolean)true,packetsize=(int)188" \
  ! tsdemux latency=0 ! h264parse ! avdec_h264 \
  ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream \
  ! videoconvert \
  ! fpsdisplaysink text-overlay=false video-sink=autovideosink sync=false
