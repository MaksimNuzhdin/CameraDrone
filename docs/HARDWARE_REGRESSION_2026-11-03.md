# Raspberry Pi 5 regression - 2026-11-03

## Scope and equipment

The Raspberry Pi returned to the network and the current application was deployed over its previously verified SSH identity. The CSI stack identified **Sony IMX708, 4608 x 2592**, on **Raspberry Pi 5 Model B Rev 1.0**. The separate GigE Vision camera was not accessed or configured.

Environment: Debian 13.7 (trixie), kernel `6.18.50+rpt-rpi-2712`, Python 3.13.5, Picamera2 0.3.37, OpenCV 4.10.0. The long run initially exercised the published `a616f3f` Pi backend. Subsequent lifecycle changes, host control refresh and test-safety fixes accompany this report; their separate retests are identified below. A private pre-deployment source/configuration backup was retained on the Pi.

## Functional regression

All **18 hardware checks passed**. These exercised exposure/gain metadata, manual white balance, ISP appearance controls, zoom crop, three output sizes, FPS, rotation, processing HDR, autofocus commands, JPEG/JSON snapshots, a full-resolution photo, H.264 recording, simultaneous analysis modes, tracking and camera restart.

- Manual 5000 us exposure was reported as 4991 us; requested gain 2.0 was reported as 2.0.
- A full-sensor photo decoded at 4608 x 2592, followed by preview recovery.
- A five-second 720p recording decoded into 155 frames.
- All AI/CV modes ran together while capture remained at 30 FPS.
- Five known-input CV checks passed directly on the Pi: objects, face location, QR, background motion, and tracker translation/loss.

These verify working controls and algorithms, not calibrated optical HDR/focus quality or field detection accuracy.

## Continuous capture and recording

The primary run used object detection every 350 ms, a continuous MJPEG receiver, and approximately one minute of initial H.264 recording. Additional browser clients and a short independent known-input CV check were present during the run; it was not an isolated microbenchmark.

| Measurement | Result |
| --- | --- |
| Run duration | 603.1 seconds |
| Preview frames received | 7386 |
| Preview bytes received | 422,081,566 |
| Stream errors | None |
| Capture FPS across every sample | 22.3-30.1 |
| Capture FPS after the first 10 seconds | 30.0-30.1 |
| Highest sampled Pi temperature | 67.8 C |
| Highest sampled frame age | 37 ms |
| Nonzero current firmware limit flags | 0 samples |
| Minute recording decoded frames | 1811 |
| Minute recording reported FPS | 30.032 |

The original soak invocation **failed its strict minimum-FPS assertion** because its very first sample, at elapsed 0.0 s immediately after service recovery/encoder startup, reported 22.3 FPS. This was the only sample below 28 FPS; all 118 samples at elapsed 10 s and later measured 30.0-30.1 FPS. No stream error, stale-frame failure or AI error occurred. The raw startup observation is preserved, not discarded or relabeled as a successful strict all-sample test.

The script now explicitly reports both overall and steady-state minima, with a documented 10-second warmup for the steady-rate acceptance check. Fresh-frame, running-state and AI-error checks still apply throughout startup. `--duration` supports a shorter follow-up without changing the default ten-minute run. Warmup does not justify a later low-FPS interval.

## Short confirmation after test changes

The guarded functional script passed all 18 checks again, then the revised soak passed a separate **60.3-second** repeat. Overall capture range was 29.9-30.2 FPS; after the explicit 10-second warmup it was 29.9-30.1 FPS. It received 782 preview frames without a stream error. Highest sampled temperature was 68.8 C and frame age 34 ms. This short repeat confirms the revised test behavior; it does not replace the raw ten-minute observations above.

## Recovery and host controls

Switching Simulator to Pi and back passed. Forced termination of the Pi backend recovered in **5.04 seconds** with camera and AI settings preserved. Boot lingering was already enabled; this run did not physically remove power.

Browser regression exposed host controls retaining their old disabled state after a source change. The UI now refreshes controls and the selector when the source generation changes, including changes made in another client. The autofocus button is explicitly re-enabled for supported hardware. Browser checks confirmed exposure/focus enabled on Pi and disabled after returning to Simulator. Recording format locks remain applied after initial control synchronization.

Hardware scripts now refuse Simulator, unavailable hardware and an existing recording. The functional test restores the original analysis settings as well as camera settings.

## Recording integrity during an ordinary service restart

The initial ordinary service-restart check found a damaged MP4 tail: 76 frames remained readable, but the decoder reported invalid NAL units and a partial file. A readable first frame or a plausible frame count was therefore insufficient evidence of recording integrity.

The Pi entry point now handles SIGTERM and calls `CameraEngine.close()`. The capture owner finalizes its encoder and metadata, closes the camera, and finishes before process exit. Preview iterators wake during shutdown, and new commands are rejected while stopping. The generated/example Pi systemd unit uses `KillMode=mixed` and a 30-second stop timeout so FFmpeg is not terminated before the camera owner finishes.

A repeated 3.5-second recording/restart test decoded **111 frames with zero decoder errors** using `ffmpeg -v error -xerror -err_detect explode`. Camera recovery took **4.14 seconds**. The decode test uses a precise 1/90000 output time base with passthrough frame timing: this avoids null-output timestamp rounding warnings on valid variable-rate MP4 while retaining strict NAL/truncation failure checks. The original broken sample was still rejected with this configuration. This is a clean service-stop result, not evidence of power-loss safety. `tests/restart_recording_check.py` reproduces the test, requires an explicit SSH hostname matching the selected camera URL, checks that no recording is already active, and verifies persisted settings.

## Regression after the Pi shutdown fix

The reproducible restart test passed with **112 strictly decoded frames**, zero decoder errors, **4.83 seconds** recovery and persisted camera/AI settings. The complete hardware script then passed all 18 checks again.

A subsequent **60.5-second** soak on the updated backend passed: overall capture 30.0-30.4 FPS, **30.0-30.0 FPS** after its first 10 seconds, 746 preview frames, no stream errors, maximum temperature 67.8 C and maximum frame age 40 ms. The ten-minute run above preceded the lifecycle fix; this shorter run and restart test cover that subsequent change.

## Reproduction and limits

```bash
python3 tests/hardware_check.py
python3 tests/restart_recording_check.py --pi-target youruser@192.168.1.20
python3 tests/soak_check.py                  # 600 seconds
python3 tests/soak_check.py --duration 60    # shorter repeat
```

Select a running real Pi deliberately, stop existing recording, and choose at least 25 FPS for the soak. These commands change settings and create local media. Private logs, real images, recordings, runtime tokens and host keys are excluded from the public repository.

A 30-60 minute thermal run, physical cold boot, power-loss behavior, Pi 3 A+, actual camera-to-RTP integration, radio performance and optical end-to-end latency remain unverified. The current browser preview remains a LAN configuration stream.
