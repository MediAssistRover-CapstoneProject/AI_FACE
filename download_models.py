"""Download only the pinned, checksum-verified OpenCV models."""
import hashlib
import json
import urllib.request
from pathlib import Path

root = Path(__file__).parent / 'models'
for item in json.loads((root / 'manifest.json').read_text()).values():
    target = root / item['file']
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256']:
        continue
    data = urllib.request.urlopen(item['url'], timeout=120).read()
    if hashlib.sha256(data).hexdigest() != item['sha256']:
        raise RuntimeError('MODEL_CHECKSUM_MISMATCH')
    target.write_bytes(data)
    print('Verified', target.name)
