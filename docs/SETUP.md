# Setup, deployment and recovery

## Ubuntu host

Use the installation commands in the root README. The host needs Flask, Requests, NumPy, OpenCV and GStreamer. Picamera2 is **not** imported by the host. `opencv-python-headless` supplies its own face cascade; Debian `opencv-data` is also supported. GStreamer `x264enc`, `mp4mux`, `h264parse`, RTP plugins and `avdec_h264` are required for recording and the transport bench.

Start in foreground with `.venv/bin/python camera_app/host.py`. It binds to 127.0.0.1:8765. `CAMERA_HOST_PORT` can override the port, and `CAMERA_HOST_DATA` can select another private data directory. Use one host instance per data directory.

Optional user-session startup:

```bash
.venv/bin/python tools/setup_host.py --install-service
systemctl --user status camera-studio.service
journalctl --user -u camera-studio.service -n 80
bash start-studio.sh
bash stop-studio.sh
```

The setup script generates the user service and application-menu shortcut using the current paths. It does not contact the Pi. The service is tied to the host user's session by default. `start-studio.sh` starts an installed service or runs Python in the foreground; for a virtualenv foreground launch, use its Python explicitly.

A first run generates `camera_app/runtime.json`, mode 0600, with a random API token and default `http://camera.local:8081`. The UI lets you enter a private Pi address. Simulator and Replay never silently fall back to a Pi. The selected source is remembered, so an installation last used in Pi mode can show unavailable until Simulator is selected.

## Raspberry Pi OS and camera

The reference system used Raspberry Pi OS with Picamera2 and an IMX708 camera on Pi 5. Ubuntu 22.04 is the **host** OS, not the recommended replacement for the Pi camera stack. Install Raspberry Pi OS to microSD using Raspberry Pi Imager, configure your own username, SSH and network, then boot the Pi. Keep storage connected for the entire operating session.

On the Pi, install camera-stack dependencies from the OS repositories:

```bash
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-flask python3-requests python3-opencv opencv-data ffmpeg
rpicam-hello --list-cameras
```

Confirm the model and camera index before deployment. Older OS releases may expose `libcamera-*` names instead of `rpicam-*`; use a supported Raspberry Pi OS camera stack. Only one process can own the CSI camera. Stop an old `rpicam-vid`, OpenHD camera service or another capture application before starting this backend.

On Ubuntu, establish and verify the Pi SSH host key by a normal SSH login. Use your own username/private address; do not disable host-key checks. The helper uses normal SSH known_hosts, or `pi_known_hosts` in this checkout when that private file exists.

```bash
export PI_TARGET=youruser@192.168.1.20
bash deploy-studio.sh
```

The script verifies model checksums, transfers source/models/private shared token, generates a Pi user service, and starts it. It preserves `camera_app/data/` and never copies host input videos. Dependencies must already be installed. Review local source before redeployment and repeat the hardware regression after camera/backend changes. The current Pi 5 regression is documented separately.

On the Pi, enable boot startup without an SSH login:

```bash
sudo loginctl enable-linger "$USER"
systemctl --user status camera-backend.service
journalctl --user -u camera-backend.service -n 80
```

On Ubuntu, choose **Raspberry Pi**, enter `http://192.168.1.20:8081`, then **Apply source**. The token is shared automatically by the deployment script. If you regenerate the host token, redeploy the matching runtime file to the Pi. Avoid publishing that file.

## Storage and boot

This release uses a normal bootable microSD on the Pi. Network boot and a USB boot image are future packaging work, not prerequisites for the host simulator. A bare board with only Ethernet and camera cannot serve video unless its EEPROM boot configuration and a working network-boot server provide the OS. The passive `diagnose-netboot.sh` helper is historical troubleshooting, not a complete network-boot installer.

Do not remove storage while the Pi is running. Use a clean shutdown before physically switching it off. Neither a host service nor this repository magically supplies a Pi OS image.

## Recovery

- **Source unavailable:** select Simulator to continue locally; for Pi mode check its power, address, token and service log.
- **No model:** run `camera_app/fetch_models.py`; the UI exposes unavailable detector capabilities. Hash mismatches abort downloads.
- **Recording fails:** inspect `.encoder.log` under private offline media, verify `gst-inspect-1.0 x264enc`, stop recording before changing format.
- **App not starting:** verify Python dependencies and port availability; run in foreground to see errors. Do not run a second instance on the same port/data.
- **Low storage:** new writes are refused below 256 MB; recording stops near that threshold. Inputs require at least 1 GB free before import. No automatic media deletion is implemented.
- **Pi temperature:** ensure active cooling and adequate power. Preview/AI workload caps help but do not replace cooling.

Host MP4 requires a clean stop to finalize. The Pi backend also handles SIGTERM and finalizes its encoder through the capture owner before exit; deploy the generated Pi unit with `KillMode=mixed` so its FFmpeg child is not killed prematurely. SIGTERM and Ctrl-C trigger host cleanup. The generated host service uses `KillMode=mixed` and `TimeoutStopSec=30` so Python can finalize its encoder before systemd terminates remaining children. Abrupt power loss can damage an unfinished recording. The Pi baseline uses a different fragmented-MP4 output path; its existing resilience does not prove SD-card or power-loss safety.
