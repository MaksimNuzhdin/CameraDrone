"""Read-only radio/software inventory. No monitor mode, driver install or network changes."""
import json
import platform
import shutil
import subprocess
from pathlib import Path

def run(command):
    if not shutil.which(command[0]):return {'available':False}
    result=subprocess.run(command,capture_output=True,text=True,timeout=10)
    return {'available':True,'exit_code':result.returncode,'output':(result.stdout+result.stderr)[:16000]}
interfaces=[]
for path in sorted(Path('/sys/class/net').iterdir()):
    driver=path/'device/driver'
    interfaces.append(dict(name=path.name,wireless=(path/'wireless').exists(),driver=driver.resolve().name if driver.exists() else None))
plugins=['x264enc','rtph264pay','rtph264depay','rtpjitterbuffer','avdec_h264','h264parse']
print(json.dumps(dict(kernel=platform.release(),architecture=platform.machine(),interfaces=interfaces,
    usb=run(['lsusb']),iw=run(['iw','list']),dkms=run(['dkms','status']),
    gstreamer={p:run(['gst-inspect-1.0',p]).get('exit_code')==0 for p in plugins},
    note='Inventory only. A detected adapter/driver is not proof of WFB-ng injection or reception support.'),indent=2))
