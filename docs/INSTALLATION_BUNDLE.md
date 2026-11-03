# Installation bundle and boot strategy

## What is packaged

`tools/build_release.py` builds a deterministic gzip/tar **software archive** from the same allowlist as the public release. It includes the application, model, tests, tools, Markdown, PDF and SHA-256 source manifest. Tokens, SSH files, recordings, imported inputs, runtime state and temporary outputs are excluded.

```bash
python3 tools/build_release.py --output releases/CameraDrone-software.tar.gz
(cd releases && sha256sum -c CameraDrone-software.tar.gz.sha256)
```

The subshell verifies the checksum from the archive's directory. Given unchanged input files, two builds produce identical archive bytes. The PDF itself records its generation date; rebuild the archive after deliberately rebuilding the PDF.

This archive is **not a bootable Raspberry Pi OS image**. It contains no partition table, kernel/root filesystem, EEPROM update, account password or SSH host keys. A cloned working SD card would also clone private credentials and recordings; it is intentionally not the public installation artifact.

## Recommended existing-board route

Keep the validated bootable microSD and use the Ubuntu host deployment:

```bash
export PI_TARGET=youruser@192.168.1.20
bash deploy-studio.sh
```

Dependencies must already exist on the Pi. The helper verifies the model, pairs the private token, copies `camera_app/` to the Pi user's home and installs its generated user service. Stop recording and RTP before deploying. The service uses orderly SIGTERM shutdown and a mixed process-group stop policy for encoder finalization.

## Fresh Pi route

1. Write a supported Raspberry Pi OS Lite image using Raspberry Pi Imager. Set your own account, SSH and network configuration. This step needs a boot medium; Ethernet alone is not an installed OS.
2. Extract the software archive under the normal Pi user's home. In the extracted `CameraDrone` directory, run the check and explicitly install dependencies if needed:

```bash
/usr/bin/python3 tools/setup_pi.py --check
/usr/bin/python3 tools/setup_pi.py --install-packages
```

3. Start the Ubuntu host once to generate its private `camera_app/runtime.json`. Copy that file over verified SSH to the extracted Pi `CameraDrone/camera_app/` directory. Do not put it in a public archive or repository.
4. As the normal Pi user, install the service and boot startup:

```bash
/usr/bin/python3 tools/setup_pi.py --install-service
sudo loginctl enable-linger "$USER"
systemctl --user status camera-backend.service
```

The installer generates paths for the extracted checkout and its system interpreter. It refuses to provision a non-Pi or unsupported OS and refuses to install the camera user service as root. `--check` only reads board/OS/dependency information. Package installation uses OS repositories, not a downloaded radio-driver installer.

The archive route installs from `~/CameraDrone/camera_app`; the host deployment route uses `~/camera_app`. Choose one managed installation at a time so only one backend owns the CSI camera.

## microSD, USB and network boot

The validated deployment boots from microSD. The same software can be deployed onto an OS booted from USB, but USB boot order, storage, power and a physical cold boot must be verified on the actual board. No attached USB device is formatted by these tools. Do not overwrite a flash drive containing another project's image.

A board without microSD/USB requires correctly configured network boot plus DHCP/TFTP/root filesystem services. This release does not provision that boot infrastructure. The historical passive network diagnostic does not make a complete netboot server.

## Reproducibility metadata

`tools/environment.py` exports OS, kernel, architecture, selected package versions and source/model hashes. It intentionally omits usernames, hostnames, network addresses, board serials, camera pixels and runtime credentials.

```bash
python3 tools/environment.py --output artifacts/environment.json
```

The verified Pi 5 used Debian 13.7, kernel `6.18.50+rpt-rpi-2712`, Python 3.13.5, Picamera2 0.3.37 and OpenCV 4.10.0. This records the tested platform; it is not a promise that arbitrary future OS/kernel versions behave identically.

## Shutdown

Stop recording and RTP first, then use `sudo systemctl poweroff` on the Pi. A clean software halt is different from physically removing supply power. Never remove a mounted boot medium from a running system. The host simulator/replay can continue while the board is off.
