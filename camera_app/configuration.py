"""Camera settings shared by the Pi backend, host simulator and tests."""
import math

DEFAULTS = dict(width=1280, height=720, fps=30, preview_fps=15, jpeg_quality=80, record_bitrate=4000000,
                rotation=0, zoom=1.0, AeEnable=True, ExposureTime=10000,
                AnalogueGain=1.0, ExposureValue=0.0, AwbEnable=True,
                AwbMode=0, ColourGains=[1.5, 1.5], Brightness=0.0, Contrast=1.0,
                Saturation=1.0, Sharpness=1.0, NoiseReductionMode=1,
                AeMeteringMode=0, AeExposureMode=0, AfMode=0, LensPosition=0.0,
                HdrMode=0)
RECONFIGURE = {'width', 'height', 'fps', 'rotation', 'HdrMode'}
RANGES = dict(fps=(5, 30), preview_fps=(1, 30), jpeg_quality=(35, 95), record_bitrate=(1000000, 16000000), zoom=(1, 4),
              ExposureTime=(100, 200000), AnalogueGain=(1, 16), ExposureValue=(-4, 4),
              AwbMode=(0, 7), Brightness=(-1, 1), Contrast=(0, 4), Saturation=(0, 4),
              Sharpness=(0, 4), NoiseReductionMode=(0, 4), AeMeteringMode=(0, 2),
              AeExposureMode=(0, 2), AfMode=(0, 2), LensPosition=(0, 32))


def validate_settings(values):
    if not isinstance(values, dict) or not values or set(values) - set(DEFAULTS):
        raise ValueError('Unknown or empty camera settings')
    for key, value in values.items():
        if key in ('AeEnable', 'AwbEnable'):
            if not isinstance(value, bool):
                raise ValueError(key + ' must be boolean')
        elif key == 'ColourGains':
            if not isinstance(value, list) or len(value) != 2 or any(isinstance(x,bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or not 0.1 <= x <= 16 for x in value):
                raise ValueError('ColourGains must contain two gains from 0.1 to 16')
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key + ' must be a finite number')
            if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
                raise ValueError(key + ' is out of range')
            if key in ('width', 'height', 'fps', 'preview_fps', 'jpeg_quality', 'record_bitrate', 'ExposureTime', 'rotation', 'AwbMode', 'NoiseReductionMode', 'AeMeteringMode', 'AeExposureMode', 'AfMode', 'HdrMode') and not isinstance(value,int):
                raise ValueError(key + ' must be an integer')
    if 'width' in values and values['width'] not in (640, 1280, 1920):
        raise ValueError('Unsupported width')
    if 'height' in values and values['height'] not in (360, 720, 1080):
        raise ValueError('Unsupported height')
    if 'rotation' in values and values['rotation'] not in (0, 180):
        raise ValueError('Rotation must be 0 or 180')
    if 'HdrMode' in values and values['HdrMode'] not in (0, 3):
        raise ValueError('Only off and Pi 5 single-exposure HDR are offered')

