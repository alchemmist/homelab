import json
import re
import sys
from pathlib import Path

path, source_sha = sys.argv[1:]
if not re.fullmatch(r"local|[0-9a-f]{40}", source_sha):
    raise SystemExit("SOURCE_SHA must be local or a full commit SHA")
Path(path).write_text(json.dumps({"source_sha": source_sha}) + "\n")
