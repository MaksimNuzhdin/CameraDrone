# Third-party components

CameraDrone's own source and documentation are MIT licensed. Third-party software and model assets retain their own licenses.

| Component | Role | Upstream / license |
| --- | --- | --- |
| MobileNet-SSD model and Caffe graph | CPU object detection | [chuanqi305/MobileNet-SSD](https://github.com/chuanqi305/MobileNet-SSD), MIT; full notice in `camera_app/models/LICENSE.MobileNet-SSD` |
| OpenCV | DNN, Haar faces, QR, motion, tracking, file decoding | [OpenCV](https://opencv.org/license/); installed separately, version dependent |
| Haar face cascade | Face locations without identification | Distributed with installed OpenCV/opencv-data; retain upstream cascade notice |
| Picamera2 / libcamera | Pi camera and ISP | [Picamera2](https://github.com/raspberrypi/picamera2), BSD-2-Clause; [libcamera](https://libcamera.org/), component-specific licenses |
| Flask / Werkzeug | Local HTTP services | [Pallets](https://palletsprojects.com/), BSD-3-Clause |
| Requests | Host-to-camera HTTP client | [Requests](https://github.com/psf/requests), Apache-2.0 |
| NumPy | Image arrays and numeric summaries | [NumPy](https://numpy.org/), BSD-3-Clause |
| GStreamer / x264 / FFmpeg | Video encoding, transport, decoding | [GStreamer licensing](https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/licensing.html); plugins/codecs have separate licenses, including GPL components |
| WFB-ng / OpenHD | Future optional radio transport | External projects, not bundled or installed by CameraDrone; consult their licenses |
| ReportLab / DejaVu fonts | PDF build tools | Installed separately; PDF build script uses system DejaVu fonts |

Model inputs and SHA-256 checksums are recorded in `camera_app/models/README.md` and `camera_app/fetch_models.py`. The included weights are about 23 MB. No cloud model or API key is needed.

`tools/fetch_test_fixtures.py` optionally fetches upstream sample images for the historical known-image tests. CameraDrone does not redistribute these photographs or claim their rights. Generated unit-test images and the documentation screenshot contain no real camera imagery.
