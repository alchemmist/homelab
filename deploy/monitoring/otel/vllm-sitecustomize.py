"""Early, fail-closed application SDK privacy bootstrap for pinned vLLM.

Python loads this before vLLM imports, including spawned worker interpreters.
No network client, exporter or provider instance is created here.
"""

import os

# Concrete bootstrap failure modes (import and resolution errors); caught broadly
# on purpose so startup always fails closed without a traceback.
BOOTSTRAP_ERRORS = (
    ImportError,
    AttributeError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    MemoryError,
    RecursionError,
)

try:
    from source_privacy import activate

    activate()
except BOOTSTRAP_ERRORS:
    # Python normally continues after sitecustomize errors: explicitly refuse
    # startup instead. Never print exception messages, stacks or environment.
    os.write(2, b"OTel source privacy bootstrap failed; refusing application startup\n")
    os._exit(78)
