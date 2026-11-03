# Hardware return and Pi 3 A+ migration

## Regression after future Pi 5 changes

The current version has completed functional and ten-minute Pi 5 regression; see [the measured report](HARDWARE_REGRESSION_2026-11-03.md). Real-camera RTP is integrated; see [the transport report](RTP_VALIDATION_2026-11-03.md). Physical cold boot and radio trials remain separate milestones. Repeat these checks after future changes.

1. Preserve its existing bootable card and deployed baseline. Back up private settings/media separately; they are not in the public repository.
2. Verify the detected sensor (`rpicam-hello --list-cameras`) and confirm no second capture process.
3. Deploy the shared API refactor, select the explicit Pi endpoint and repeat `tests/hardware_check.py`.
4. Verify resolution, exposure/gain/AWB, AF states, zoom, Pi5 processing HDR, full photo, recording and overlays. Compare MP4 decode counts and sidecar data.
5. Repeat the ten-minute soak, watchdog/process recovery and source reconnect tests. Check the new host presets and switching back from Simulator to hardware.
6. Test a clean shutdown and physical cold boot. Previous software reboot success does not cover power removal.
7. Repeat the single-encoder RTP/recording tests on Ethernet before any RF deployment.

## Pi 3 Model A+ constraints

The Pi 3 A+ has **512 MB RAM**, one USB 2.0 port and no onboard Ethernet connector. A USB radio, optional Ethernet adapter and power must fit that topology; a powered hub may be needed for development. The CSI ribbon/connector differs from Pi 5's connector, so select the correct cable. Hardware details: [official Pi 3 A+ product page](https://www.raspberrypi.com/products/raspberry-pi-3-model-a-plus/) and [product brief](https://datasheets.raspberrypi.com/rpi3/raspberry-pi-3-a-plus-product-brief.pdf).

The supplied `pi3a-light` profile requests 640x360 at 15 FPS, 5 FPS JPEG preview, 1.5 Mbit/s recording, HDR off and motion-only analysis every 1200 ms. These are candidate settings, **not a validated port**. Background motion itself is unsuitable for a moving drone until camera-motion compensation is designed.

Use Raspberry Pi OS Lite and verify camera support on that OS. Keep the host UI and batch analysis on Ubuntu. Avoid loading the neural network on the Pi if the selected profile does not need it; the current Vision constructor still loads it eagerly, so profile reduction alone does not fully reduce memory. A lazy model loader is a later board-measured optimization. Set explicit memory budgets before enabling object detection.

Pi 5 H.264 encoding is software-based; Pi 3 has a different hardware encoder path. The present engine needs platform-specific encoder selection and testing on Pi 3, not just profile changes. The [official camera software guide](https://www.raspberrypi.com/documentation/computers/camera_software.html) describes platform-dependent encoding, and [Pi 5 encoding performance](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-010033-WP-1-H.264%20encoding%20performance%20on%20Raspberry%20Pi%205_series%20computers.pdf) explains its software encoder.

## Definition of a validated port

- Sensor detected and correct controls/capabilities shown; Pi5-only HDR hidden/rejected as appropriate.
- Sustained capture/encoding at the candidate resolution without OOM or excessive swap.
- Actual memory, CPU, temperature, dropped frames and bitrate reported for capture + radio + chosen AI.
- Correct hardware encoder selected; one camera owner; bounded stream/record queues.
- At least 30-minute soak, interruption/recovery, clean shutdown and cold boot.
- Exact OS/kernel/driver/cable/power/adapters documented with measured results.

## Later product work

A repeatable boot image, network boot packaging, labeled field datasets, camera calibration, exposure/AF/HDR optical comparisons, adaptive stream settings and flight integration remain separate milestones. A USB boot image should be created from a validated system; this offline work does not claim an installable Pi OS image.
