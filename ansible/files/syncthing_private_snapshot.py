import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


root = Path(sys.argv[1])
config = ET.parse(root / 'config.xml').getroot()
snapshot = {
    'certificate': hashlib.sha256((root / 'cert.pem').read_bytes()).hexdigest(),
    'devices': sorted(device.get('id') for device in config.findall('device')),
    'folders': sorted(
        (
            folder.get('id'),
            folder.get('path'),
            folder.get('paused') or folder.findtext('paused', 'false'),
        )
        for folder in config.findall('folder')
    ),
}
print(json.dumps(snapshot, sort_keys=True))
