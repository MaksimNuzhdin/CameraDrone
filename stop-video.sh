#!/usr/bin/env bash
set -euo pipefail
: "${PI_TARGET:?Set PI_TARGET=user@private-ip}"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$PI_TARGET" 'systemctl --user stop cameradrone-video.service'
