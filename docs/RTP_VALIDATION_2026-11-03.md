# Real camera transport validation — 3 November 2026

## Scope and platform

Release 0.3 adds one-encoder H.264 recording/RTP fanout to the real Picamera2 backend. Testing used Raspberry Pi 5 (8 GB), CSI IMX708, Ethernet and the Ubuntu host's standard GStreamer H.264 decoder. No GigE Vision camera, WiFi interface, radio driver, bootloader or EEPROM was modified. Private raw logs and camera media remain outside the public repository.

The Pi ran Debian 13.7, kernel 6.18.50+rpt-rpi-2712, Python 3.13.5, Picamera2 0.3.37 and OpenCV 4.10.0. The Ubuntu decoder used GStreamer 1.20.3. `tools/environment.py` exports nonsecret package/source hashes for local reproduction.

## Functional transport checks

| Check | Measured result |
| --- | --- |
| Initial real RTP decode | 115 decoded 1280x720 frames; 30.169 FPS; no loss |
| RTP plus recording | 594 decoded frames over approximately 20 seconds; 30.048 FPS; no decode errors or packet loss |
| Shared encoder | Encoder generation unchanged when attaching/stopping recording; stopping RTP preserved a concurrent recording |
| MP4 coexistence | Six-second recording decoded strictly with FFmpeg; complete file, no decode errors |
| Controlled interruption | Bounded UDP relay dropped packets during a two-second blackout; decoder recovered without restart |
| Blackout observation | 567 frames in 24.316 seconds, maximum decoded-frame gap 2621.387 ms; receiver reported 911 lost packets, matching relay drops |
| Service restart | Recording finalized (161 decoded frames, zero errors); service returned in 4.15 seconds |
| RTP after service restart | Sender stayed off until explicitly enabled; existing receiver accepted the new RTP session; maximum decode gap 4926.603 ms |
| Provisioning check | Read-only Pi OS/module/FFmpeg checks passed on the actual board |
| Software reboot | Boot identity changed; API returned in 32.23 seconds, before post-boot SSH; capture 30 FPS, settings/AI preserved, RTP off |
| Final functional regression | 18 camera checks and six transport lifecycle/guard checks passed |

The relay test changes only its own UDP forwarding. It is not an RF fading/FEC test. A successful recovered stream can still contain a visible freeze. Maximum decoded-frame gap is reported separately from average FPS and timestamp latency.

## Initial extended run: retained failure

The first long run was deliberately stopped after **1147.368 seconds** when a stability failure appeared. It decoded 32419 frames at 28.294 FPS, but reported **487 lost RTP packets** and a **17041.321 ms** maximum decode gap. Pi capture/encoding continued at approximately 30 FPS with no local sender drops. Linux reported 457 receive-buffer drops on this receiver socket; this is a host socket counter, not an RF measurement.

The original receive path used the default 212992-byte kernel buffer and ran decoder/measurement callbacks directly downstream of the network reader. The revised monitor and native receiver request a bounded socket buffer and add a bounded, leaky ingress queue (256 packets, 307200 bytes, 100 ms; whichever limit is reached first). This separates network reads from downstream stalls and discards stale backlog. No global sysctl, NIC, firewall or driver settings were changed. [GStreamer documents the socket buffer setting and OS limits](https://gstreamer.freedesktop.org/documentation/udp/udpsrc.html).

This observation motivates the receiver change; it does not prove that every missing packet had the same cause. The failed run remains separate from subsequent validation. Average FPS and median software latency alone did not establish stable delivery.

## Corrected long-run status

A fresh 30-minute run is performed separately after the receiver change; its final measurements must be evaluated independently of the failed initial run. No cold-boot or optical-latency claim follows from software reboot or decoder timestamps.

## Clock validity and candidate profile

Immediately after reboot, the 18.275-second Pi3 candidate-profile check on Pi5 decoded **235 frames at 15.017 FPS**, 640x360, with zero reported packet loss/errors and an 88.368 ms maximum gap. This validates profile behavior on Pi5 only. Its clocks changed offset by **227.056 ms** during the run, so its negative software latency estimates are invalid and must not be used.

The monitor now rejects latency summaries when before/after clock offset changes exceed combined calibration uncertainty, or when the median estimate is negative. It reports null latency quantiles, a reason and explicitly raw timestamp estimates. Two unit tests cover valid clocks and rejection of drift/negative/missing measurements. Decoder counts/gaps/loss remain independent of clock validity.

## Software latency method

The RTP sender stamps each encoded access unit after encoding using an eight-byte Unix timestamp in a private RTP extension. The host maps that timestamp through its jitter/depay/decode pipeline to the decoded RGB frame. Eight HTTP clock samples before/after the run select the smallest-roundtrip estimate and report half-roundtrip uncertainty and observed offset drift.

The coexistence run measured p50 **13.892 ms**, p95 **22.587 ms** from encoder output to host decoded frame. Initial clock uncertainty was several milliseconds (approximately 2.9–5.2 ms in the short first run). These numbers exclude exposure, sensor readout, ISP, H.264 encoding, display queues and monitor refresh. They are **not optical end-to-end latency** and should not be compared directly with glass-to-glass measurements.

`/latency-target` supplies a changing browser timer for a later physical test. It neither measures latency automatically nor overcomes refresh/scheduling limitations. No optical result is claimed.

## Reproduce

Run host unit tests without the board:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The suite has 18 tests, including wire-level FU-A reconstruction, sequence wrap/marker/timestamp validation, address boundaries, and the custom sender decoded by standard GStreamer. Synthetic test media are generated locally.

With the real Pi deliberately selected and no recording/RTP session active:

```bash
/usr/bin/python3 tests/transport_soak.py --seconds 1800 --record-seconds 60
python3 tests/hardware_check.py
```

These hardware scripts change settings and create private media. The transport soak enables four CPU AI/CV modes every 350 ms, previews JPEG, sends 720p30 H.264 over RTP and records the first minute. It verifies one encoder generation, steady capture/decoded rates above 24 FPS, zero reported packet loss/local drops, and a maximum decode gap below 1500 ms. It restores previous settings/analysis afterward. Receiver measurements and errors are retained even when assertions fail.

## Remaining physical acceptance

Actual radio adapters, driver/kernel matching, RF capacity/FEC, range, interference, optical latency, cold boot after power removal, Pi 3 A+ memory/hardware encoding, power quality and long-duration 1080p remain unverified. The approximate budget tool is not a PHY-rate or range predictor. Clean shutdown is not protection against abrupt power loss.
