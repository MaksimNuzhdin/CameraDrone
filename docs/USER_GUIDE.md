# Using Camera Studio

## Sources

**Simulator** renders a moving test pattern with color bars, a grayscale ramp, a textured tracking target and a generated QR payload. Its visible SIMULATOR badge remains on the preview. Exposure, autofocus, denoise and HDR are disabled because they require physical hardware. Software transforms approximate appearance; they do not reproduce the Pi ISP.

**Replay file** uses a host-local input library. Click **+ Add file**, select MP4/AVI/MOV/MKV/WebM/JPEG/PNG, then **Apply source**. Files are copied to private UUID names. Video loops automatically; use Pause/Resume and the seek slider. The output FPS can differ from native file FPS; frames are repeated or skipped to match. Images have no timeline. Imports are limited to 512 MB per request and 16 megapixels per decoded frame. Codec availability depends on OpenCV's decoder build.

**Raspberry Pi** forwards requests to a configured local camera API. It never probes the other cameras on the LAN. A disconnected Pi stays unavailable until you choose another source; a simulator is never substituted for live camera imagery. Switching source while recording is rejected.

## Camera and analysis

The Camera tab controls capture format, preview quality/FPS, recording bitrate, zoom and image appearance. On hardware, it also exposes sensor/ISP exposure, white balance, focus and processing HDR. Actual sensor metadata is shown separately from requested settings. Format changes interrupt capture briefly. Some controls depend on sensor and Pi capabilities.

Open **Profiles & saved presets** for Pi 5 Balanced, Pi 3 A+ Candidate and Offline Development. The Pi 3 profile is a proposed low-load starting point, not a performance guarantee. Save a named preset on Ubuntu, export JSON for version control, or import version-1 Camera Studio preset JSON. Applying a full preset during recording is blocked. Physical settings are skipped when applying it to offline sources, and the UI reports that fact.

AI & CV modes:

- **Objects:** CPU FP32 MobileNet-SSD; 20 PASCAL VOC classes, confidence threshold adjustable. Not general open-vocabulary recognition.
- **Faces:** OpenCV Haar face locations, no identity recognition.
- **QR:** decoded text, never automatically navigated or executed. Includes a single-code fallback when the multi-code detector misses a small code.
- **Motion:** background subtraction with ten-cycle warmup; assumes a stationary camera.
- **Region tracking:** select a textured region by dragging. A local template matcher follows translations and declares loss below confidence 0.55; large rotation or scale changes are outside its design.

Analysis works on reduced 640 x 360 frames independently of capture. Increasing the interval reduces CPU use. Overlays are drawn in the browser; photos/video remain clean. Analysis age is shown and stale boxes are hidden. The histogram, clipped/dark percentages and detail score describe the reduced image. Detail score varies with noise and scene texture; it is not a calibrated focus measurement.

## Photos, video and lab

**Snapshot** saves a JPEG and JSON sidecar at the current output resolution. **12 MP photo** is hardware-only, pauses preview briefly and is blocked during recording. **Record video** writes H.264 MP4 and JSONL metadata. Stop it before downloading or changing capture geometry/bitrate. Media lets you preview finished MP4s and download files. Files belong to the selected source: Pi storage in Pi mode, Ubuntu storage in offline modes.

Keyboard shortcuts: **S** snapshot, **R** toggle recording, **Escape** cancel ROI selection. Shortcuts are suppressed while editing form fields.

The **Lab** tab analyzes a saved host input regardless of the active preview source. Enable the desired AI/CV modes, select an input, frame stride (1..120), and maximum analyzed frames (1..1000), then start. Only one job runs at a time. Reports contain per-frame output, p50/p95 processing time, class counts, QR payloads and image quality metrics. Download JSON for detail or CSV for tabular analysis. Report timing measures this Ubuntu host; it does not estimate Pi speed or labeled-dataset accuracy.

## Interpreting status

Capture FPS and preview FPS are independent. An idle source generates JPEGs at at most 2 FPS until a viewer connects. The Pi may cap preview/analysis at high temperature. Host frame age and HTTP round-trip time are not optical glass-to-glass latency. Offline sources show no fabricated sensor temperature, gain or focus metadata.

The browser UI, diagnostics and all project documentation are in English. No cloud service receives camera frames.
