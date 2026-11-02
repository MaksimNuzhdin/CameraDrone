"""Download the pinned CPU object detector and verify its SHA-256 digests."""
import hashlib
import urllib.request
from pathlib import Path

BASE = 'https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/bb17b6c3eef36d80be441ae8e5339be66e8e3b7a/'
FILES = {
    'deploy.prototxt':'2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608',
    'mobilenet_iter_73000.caffemodel':'52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7',
}
folder = Path(__file__).resolve().parent/'models'
folder.mkdir(exist_ok=True)
for name, digest in FILES.items():
    path=folder/name
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
        print(name, 'verified')
        continue
    with urllib.request.urlopen(BASE+name, timeout=60) as response:
        data=response.read()
    if hashlib.sha256(data).hexdigest()!=digest:
        raise RuntimeError('Checksum mismatch: '+name)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)
    print(name, 'downloaded and verified')
