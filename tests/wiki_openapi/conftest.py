"""Make the wiki_openapi suite bind its own generic module names.

Test collection imports ``tests/blog_updates`` suites first; those cache
``engine``, ``stages`` and ``github`` from ``scripts/blog_updates`` in
``sys.modules``. Purge the leaked names and put this suite's script
directory on the path so ``tests/wiki_openapi/test_flow.py`` always
imports the wiki_openapi implementations regardless of collection order.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/wiki_openapi"))
for _leaked in ("engine", "stages", "github"):
    sys.modules.pop(_leaked, None)
