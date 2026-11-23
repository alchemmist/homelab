"""Generate read-only overlay files for the pinned Canvas SDK, not mutable history."""

from hashlib import sha256
from pathlib import Path

ROOT = Path("/usr/local/lib/python3.13/site-packages/openhands/sdk/conversation")
PATCHES = (
    (
        "impl/local_conversation.py",
        "01a206776c6bc8902d59b7caf53379771d2cf7f5d5be79b7d8435c0eb1474871",
        "if iteration >= self.max_iteration_per_run:",
        6,
    ),
    (
        "goal/controller.py",
        "651761b919dc3cc5e4f58c5e9cfc2e1890cc096ea0478bf3ce5e2c3fa42df1a9",
        "if self.iteration >= self.max_iterations:",
        1,
    ),
)


def prepare(root, out) -> None:
    for name, digest, condition, count in PATCHES:
        original = (root / name).read_bytes()
        if sha256(original).hexdigest() != digest or original.count(condition.encode()) != count:
            raise ValueError("Unexpected SDK revision: " + name)
        result = original.replace(
            condition.encode(), b"if False:  # Owner policy: no iteration-count stop"
        )
        compile(result, name, "exec")
        (out / Path(name).name).write_bytes(result)


if __name__ == "__main__":
    prepare(ROOT, Path("/overlay"))
