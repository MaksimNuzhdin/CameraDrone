"""Create an allowlisted, secret-checked public checkout without touching local runtime.

Usage: python3 tools/prepare_public_release.py /tmp/cameradrone-public
The destination must be absent or empty. This script does not publish anything.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
args=parser.parse_args();destination=args.destination.resolve()
if destination==ROOT or ROOT in destination.parents:parser.error('Use a separate directory outside the project')
if destination.exists() and any(destination.iterdir()):parser.error('Destination must be absent or empty')
files=[]
for name in ['README.md','VALIDATION.md','THIRD_PARTY.md','LICENSE','.gitignore','.gitattributes','requirements-host.txt',
             'start-studio.sh','stop-studio.sh','deploy-studio.sh','start-video.sh','stop-video.sh','view-video.sh','diagnose-netboot.sh']:
    files.append(ROOT/name)
for directory in ['camera_app','airlink','tests','tools','docs','.github','output/pdf']:
    for path in (ROOT/directory).rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:continue
        rel=path.relative_to(ROOT)
        if rel.parts[:2] in [('camera_app','data')]:continue
        if path.name=='runtime.json':continue
        if path.suffix in {'.py','.sh','.md','.json','.css','.js','.html','.service','.desktop','.yml','.pdf','.prototxt','.caffemodel'} or path.name.startswith('LICENSE.') or (rel.parts[:2]==('docs','images') and path.suffix=='.png'):
            files.append(path)
secret=None
runtime=ROOT/'camera_app/runtime.json'
if runtime.exists():secret=json.loads(runtime.read_text()).get('token','').encode()
patterns=[rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----',rb'ghp_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{30,}']
manifest=[]
for path in sorted(set(files)):
    data=path.read_bytes();rel=path.relative_to(ROOT)
    if secret and secret in data:raise RuntimeError('Private runtime token found in '+str(rel))
    if any(re.search(pattern,data) for pattern in patterns):raise RuntimeError('Possible secret in '+str(rel))
    target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    manifest.append(dict(path=str(rel),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
(destination/'release-manifest.json').write_text(json.dumps(dict(format='cameradrone-public-manifest',files=manifest),indent=2)+'\n')
print(f'Prepared {len(manifest)} public files ({sum(f["bytes"] for f in manifest):,} bytes), plus checksum manifest.')
print('Excluded runtime token, host-data, recordings, upstream test photos, known_hosts, artifacts, logs, caches and archives.')
