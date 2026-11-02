# Model assets

Object detection uses the CPU MobileNet-SSD model by chuanqi305.

- Source: https://github.com/chuanqi305/MobileNet-SSD
- Pinned commit: `bb17b6c3eef36d80be441ae8e5339be66e8e3b7a`
- License: MIT; see `LICENSE.MobileNet-SSD`.
- Input: 300 x 300 BGR, scale `0.007843`, mean `127.5`.
- Output: the 20 PASCAL VOC object classes, excluding background.
- This is an FP32 Caffe model, not an INT8 model.
- Run `python3 camera_app/fetch_models.py` from the project root to fetch or verify assets.

Face detection uses the Haar cascade shipped in Debian's `opencv-data` package.
QR decoding, motion detection and template tracking use OpenCV. They do not
require this neural network. No images are uploaded to a cloud inference service.
