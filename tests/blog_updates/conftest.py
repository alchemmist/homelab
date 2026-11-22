"""Make the blog_updates suite bind its own generic module names.

Test collection order decides whether ``engine``, ``stages`` or ``github``
already cached a different script tree's module (``tests/wiki_openapi``
uses the same names). Purge the leaked names so this directory's test
modules always import the blog_updates implementations.
"""

import sys

for _leaked in ("engine", "stages", "github"):
    sys.modules.pop(_leaked, None)
