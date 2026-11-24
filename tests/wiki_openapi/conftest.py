"""Make the wiki_openapi suite import its scripts as a package.

Test collection runs this nested suite from the repository root without
putting the repository root on sys.path. Insert it so scripts.wiki_openapi
resolves as a package under one canonical module name, and purge the old
flat names that earlier revisions cached so a stale module can never
shadow the package implementation.
"""

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
for _leaked in ("engine", "stages", "github", "client", "workflow"):
    sys.modules.pop(_leaked, None)
