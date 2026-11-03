# Validation report

## Scope of evidence

This document separates the **historical Pi 5 baseline** from the **current offline extension**, validated on Ubuntu on 2026-11-03. The Pi was unplugged during the initial offline extension. It subsequently returned and the current version was redeployed and exercised on the real Pi 5. See the [2026-11-03 hardware regression](docs/HARDWARE_REGRESSION_2026-11-03.md), including the retained startup-rate assertion failure and separate steady-state measurements. Historical results below remain evidence for their original baseline. Private raw artifacts and real camera images are intentionally excluded from the public repository.


Validation used the real Raspberry Pi 5 (8 GB) and its CSI IMX708 camera.
The Ubuntu application at `http://127.0.0.1:8765/` was the control endpoint.
No GigE Vision camera was accessed or configured.

## Real camera checks

All **18 hardware checks passed** in the final functional run:

- Reject unknown settings, unsupported sizes and invalid confidence thresholds.
- Manual exposure of 5000 us produced 4991 us in sensor metadata; gain 2.0 was reported as 2.0.
- Manual white balance gains 1.6 / 1.2 appeared in ISP metadata.
- Brightness, contrast, saturation, sharpening, exposure compensation and denoise controls were accepted.
- Zoom 2 changed the capture crop from `[768,432,3072,1728]` to `[1536,864,1536,864]`.
- 640 x 360 at 15 FPS, 1920 x 1080 at 30 FPS and 1280 x 720 at 30 FPS captured correctly sized JPEGs.
- 180-degree rotation and Pi 5 single-exposure HDR reconfiguration resumed capture.
- Autofocus was exercised; a separate metadata check observed scanning followed by focused state, with lens position moving from 0 to 12 diopters.
- Standard snapshots and JSON metadata downloaded successfully.
- A full-resolution photo decoded as **4608 x 2592**; the 720p preview recovered afterward.
- A five-second MP4 decoded successfully into **155 frames** at 1280 x 720.
- Resolution/bitrate/full-photo changes and duplicate recording starts were rejected while recording.
- All four analysis modes ran together on the live image without stopping 30 FPS capture.
- Live-region tracking reported approximately 0.997 match confidence on a stationary region.
- The camera restart operation resumed capture.

Details: `artifacts/hardware-results.json`. JPEGs and a decoded test recording
are also saved in `artifacts/`.

## Known-input AI/CV checks

All **5 known-input tests passed on the Pi CPU**:

1. MobileNet-SSD detected a person in the model author's sample image.
2. OpenCV's face cascade found a face in the OpenCV Lena sample.
3. QR decoding recovered the generated payload `CameraStudio-QR-test`.
4. Background subtraction found a newly introduced moving region after warmup.
5. Template tracking followed a known translation and declared loss when the target disappeared.

These checks establish working model execution and algorithm behavior, not field
accuracy across arbitrary lighting, object sizes or viewpoints.

Details: `artifacts/vision-results.json`.
Sample sources: the MobileNet-SSD repository's `images/000001.jpg` and OpenCV's
`samples/data/lena.jpg`. These are test fixtures, not camera media.

## Ten-minute live soak

A continuous MJPEG client ran with CPU object detection every 350 ms.
The first minute also recorded H.264 MP4 on the Pi.

| Observation | Result |
| --- | --- |
| Duration | 602.5 seconds |
| Preview JPEG frames received | 7310 |
| Stream errors | None |
| Capture FPS range | 28.9–30.1 |
| Highest sampled temperature | 73.2 C |
| Highest sampled frame age on Pi | 46 ms |
| Preview data received | 534,434,043 bytes |

Frame age measures freshness inside the Pi service. It does not include network,
browser buffering or display latency. Preview target was 15 FPS; actual delivery
was approximately 12 FPS under this workload. Preview and capture rates are
reported independently in the application.

The initial implementation reached roughly 83 C and a firmware temperature limit
under recording load. After reducing redundant frame copies/conversions, the
continuous soak above remained below 74 C. Thermal workload caps and firmware
flags are exposed in the application. Historical firmware limit flags can remain
set even after the current condition clears.

The soak preceded the final additions for 12 MP photos, recording bitrate selection
and stricter input validation. The unchanged capture/analysis pipeline was soaked;
those additions were subsequently covered by the final hardware checks.

Details: `artifacts/soak-results.json`.

## Recovery, persistence and access

- Forced termination of the Pi backend process: camera recovered in **4.77 seconds**.
- Camera and analysis settings survived that recovery.
- Software reboot: the camera API returned automatically after approximately 29 seconds,
  before any SSH login. Capture returned to 30 FPS and AI settings were preserved.
- Host writes without the application header were rejected with HTTP 403.
- Pi API calls without the shared token were rejected with HTTP 401.
- Ten invalid-input cases were rejected with HTTP 400, including NaN, wrong types,
  out-of-range settings and malformed tracking regions.
- The Pi user service is enabled with `Linger=yes`; the host service is enabled
  for the Ubuntu user session.
- Browser checks exercised settings, snapshots, the Media gallery, downloading a
  photo to Ubuntu, and selecting a tracking region by dragging on the live view.
- Application source strings were checked for remaining Cyrillic text.

Details: `artifacts/recovery-results.json`, `artifacts/invalid-input-results.json`
and `artifacts/reboot-results.json`.

## Verification limits

- Optical end-to-end latency has not been measured.
- Physical power removal, power quality and SD-card failure have not been tested.
- Low-disk protection is implemented but the real card was not filled to test it.
- No long-duration 1080p recording or field-accuracy benchmark was performed.
- Pi 3 A+ portability and performance remain future work.
- HDR and focus commands were functionally exercised; controlled optical comparisons
  and sensor HDR tuning remain future work.

## Current Ubuntu offline extension (2026-11-03)

The complete standard-library unittest suite passes **12 tests**:

| Check | Observed result |
| --- | --- |
| Synthetic capture / JPEG / multipart preview | Running; valid JPEG frames |
| API authentication / host write header | Missing token 401, missing application header 403 |
| Hardware-only controls offline | Exposure and full-sensor photo rejected, 400 |
| Resolution validation and QR fallback | Invalid size pair rejected; generated testcard payload decoded at 640x360 |
| Preset save/export/apply and Pi3 candidate profile | Passed with explicit unsupported-setting filtering |
| Local recording | H.264 MP4 stopped cleanly; every submitted/encoded frame decoded |
| Recording guards and HTTP Range media view | Source change/download blocked during recording; 206 partial response afterward |
| Input upload, replay, pause/seek and bounded batch report | Synthetic PNG and generated MP4; JSON/CSV downloads passed |
| Offline source isolation | Requests stayed on localhost despite an unreachable configured Pi address |
| Numeric / type / URL boundary validation | Invalid values rejected, including nonfinite values and nonlocal endpoints |
| Motion and tracking known synthetic transforms | Motion detected; translation followed and target loss declared |
| Real H.264/RTP localhost transport | 29 decoded 640x360 frames; encode, UDP and decode pipeline all executed |

Five additional known-input checks passed on the Ubuntu CPU: object detection, face detection, QR decoding, background motion and tracking/loss. These use the historical optional upstream sample photographs and generated patterns; the photographs are not redistributed. This does not establish general detection accuracy.

The recording test exposed malformed fragmented-MP4 output from this Ubuntu GStreamer stack: a weak first-frame-only check could pass even though subsequent NAL reads failed. The host recorder now uses finalized fast-start MP4 with I420 input, and the regression check decodes **all** encoded frames. This change is host-only; the Pi's FFmpeg output path remains separate. Host recordings require a clean stop and do not claim power-loss resilience.

Browser review verified Simulator labeling, generated QR overlay/text, unavailable hardware controls and the English source/AI interface. The public screenshot is synthetic. Python compilation, JavaScript syntax and shell syntax checks passed. GitHub Actions is configured but remote execution is not claimed until its actual result is observed.

Read-only radio inventory: Ubuntu x86_64, Ethernet `e1000e` and loopback only; no wireless network interface. Required GStreamer encoder/RTP/decode elements are present. No WiFi driver/module, monitor mode, channel, power or other camera configuration was changed.

### Offline soak and service shutdown

A separate **60.69-second** synthetic-source soak ran all four AI/CV modes, preview JPEG generation and an initial recording on Ubuntu. Minimum sampled capture rate after warmup was **30.0 FPS**, maximum sampled frame age **26 ms**, and **867 preview frames** were generated. The recording contained **451 decoded frames**, with **zero encoder queue drops**. These figures describe this host, not Raspberry Pi or RF behavior.

A real `systemctl --user restart camera-studio.service` during a synthetic recording initially exposed process-group termination interrupting MP4 finalization. The installed/generated host unit now uses `KillMode=mixed` and a 30-second stop timeout, while Python handles SIGTERM cleanup. The repeated restart test produced a finalized MP4 with **53 decoded frames**, and the source returned running at 30 FPS with no active recording. Abrupt power loss remains untested.

### Reproduce

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tools/fetch_test_fixtures.py  # optional external samples
python3 tests/vision_check.py       # optional known-image suite
python3 airlink/diagnose.py
python3 tools/offline_soak.py --seconds 60 --output artifacts/offline-soak.json
```

Hardware scripts `tests/hardware_check.py` and `tests/soak_check.py` change settings and create media. Select the real Pi deliberately before running them. They are not part of offline unittest discovery.

### Remaining unverified behavior

Physical cold boot and power loss, Pi3 encoder/driver/RAM suitability, actual RF adapter support, RF packet loss/FEC/recovery, optical latency, range, field accuracy, storage-exhaustion behavior and long-term 1080p operation still need physical tests. A localhost transport test does not establish any of those results.
