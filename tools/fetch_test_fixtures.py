"""Optional external sample download for historical known-image CV checks.

Images retain upstream rights and are not included in CameraDrone releases.
Offline unit tests use generated images and do not need these downloads.
"""
import hashlib
import urllib.request
from pathlib import Path
files={
 'object-sample.jpg':('https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/bb17b6c3eef36d80be441ae8e5339be66e8e3b7a/images/000001.jpg','3f0bdad67d01aa452929683b74a124a2926b6bce534c85f3ee0f00e20eeacab0'),
 'face-sample.jpg':('https://raw.githubusercontent.com/opencv/opencv/4.10.0/samples/data/lena.jpg','7de7ed51a1594fff247f4cae2301eceacf5313d6011e37b4a4c8733f7bb72c07')
}
folder=Path(__file__).resolve().parents[1]/'tests'
for name,(url,digest) in files.items():
    with urllib.request.urlopen(url,timeout=30) as response:data=response.read()
    if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Checksum mismatch: '+name)
    (folder/name).write_bytes(data);print(name,'verified')
