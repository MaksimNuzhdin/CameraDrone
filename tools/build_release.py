"""Create a deterministic, sanitized SOFTWARE archive. This is not a bootable OS image."""
import argparse
import gzip
import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'releases/CameraDrone-software.tar.gz')
args=parser.parse_args();output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='cameradrone-release-') as tmp:
    folder=Path(tmp)/'CameraDrone'
    subprocess.run([sys.executable,str(ROOT/'tools/prepare_public_release.py'),str(folder)],check=True)
    with output.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w|') as archive:
        for path in sorted(folder.rglob('*')):
            if not path.is_file():continue
            data=path.read_bytes();info=tarfile.TarInfo(str(Path('CameraDrone')/path.relative_to(folder)))
            info.size=len(data);info.mtime=0;info.mode=0o644;info.uid=info.gid=0
            archive.addfile(info,io.BytesIO(data))
digest=hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n')
print('Software archive:',output)
print('SHA256:',digest)
print('No OS image, partition, bootloader or runtime secret is included.')
