"""Generate read-only overlay files for the pinned Canvas SDK, not mutable history."""
from hashlib import sha256
from pathlib import Path

ROOT = Path("/usr/local/lib/python3.13/site-packages/openhands/sdk/conversation")
PATCHES = (
    ("impl/local_conversation.py", "1a272a4c714652a554bbd602cfe825a5044c412b1da7101e5e02403b4c413854", "if iteration >= self.max_iteration_per_run:", 6),
    ("goal/controller.py", "eb6922cd87a46fb78c28a47906fe0e01010bad9bea00d048eadbacaa3f82af43", "if self.iteration >= self.max_iterations:", 1),
)
def prepare(root, out):
    for name, digest, condition, count in PATCHES:
        original=(root/name).read_bytes()
        if sha256(original).hexdigest()!=digest or original.count(condition.encode())!=count:
            raise ValueError("Unexpected SDK revision: "+name)
        result=original.replace(condition.encode(),b"if False:  # Owner policy: no iteration-count stop")
        compile(result,name,"exec");(out/Path(name).name).write_bytes(result)
if __name__=="__main__":prepare(ROOT,Path("/overlay"))
