"""Finish the already approved one-shot cleanup after off-host archive readback."""

import json
import subprocess
import sys
import time

from retire import SPOOL, SSH, D, K, output

NAME = "raw-packed-copy-20261121"
original = "raw-cold-copy-20261121"
other = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "socrat-3"]


def main() -> None:
    if sys.flags.optimize:
        msg = "safety checks need standard Python"
        raise RuntimeError(msg)
    assert sys.argv[1:] == ["--after-release"]
    manifest = output([*SSH, "cat " + SPOOL + "/manifest.json"])
    released = json.loads(output([*SSH, "cat " + SPOOL + "/released.json"]))
    assert released["source_empty"]
    assert released["files"] >= 100
    write = """import pathlib,sys,json,hashlib,os
p=pathlib.Path(sys.argv[1]);os.umask(0o077);obj=json.load(sys.stdin);d=hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest();assert d==sys.argv[2];f=p/'manifest.json'
if f.exists(): assert json.loads(f.read_bytes())==obj
else:
 with f.open('x') as out:json.dump(obj,out,sort_keys=True);out.flush();os.fsync(out.fileno())
"""
    import shlex

    output(
        [*other, "python3 -c " + shlex.quote(write) + " " + SPOOL + " " + released["manifest"]],
        manifest,
    )
    deadline = time.monotonic() + 20 * 3600
    while time.monotonic() < deadline:
        try:
            j = json.loads(output([*K, "--request-timeout=20s", "get", "job", NAME, "-o", "json"]))
        except subprocess.CalledProcessError:
            # Status lookup is read-only. Never interpret a lost API connection as success.
            time.sleep(45)
            continue
        s = j["status"]
        assert not s.get("failed"), "offload failed; retain local backup"
        if s.get("succeeded") == 1:
            break
        time.sleep(45)
    else:
        msg = "retain local backup"
        raise TimeoutError(msg)
    prog = (
        (D / "tree.py").read_text()
        + """\nfrom pathlib import Path
import subprocess,tarfile,socket
assert socket.gethostname().split('.')[0]=='socrat-3';p=Path('/home/alchemmist/.local/state/socrat-backups/retired-thanos-raw-20261121');assert p.resolve()==p
m=json.loads((p/'manifest.json').read_bytes());proof=json.loads((p/'offload.json').read_bytes());assert digest(m)==proof['manifest'] and checksum(p/'raw.tar.zst')==proof['sha256']
seen={};dirs=set();proc=subprocess.Popen(['zstd','-qdc',str(p/'raw.tar.zst')],stdout=subprocess.PIPE)
with tarfile.open(fileobj=proc.stdout,mode='r|') as t:
 for x in t:
  k=x.name.removeprefix('./')
  if k in ('.',''):assert x.isdir();continue
  if x.isdir():assert DIR.fullmatch(k);dirs.add(k);continue
  assert FILE.fullmatch(k) and k not in seen and k in m['files']
  if x.islnk(): seen[k]=seen[x.linkname.removeprefix('./')]
  else:
   assert x.isfile();h=hashlib.sha256();n=0
   with t.extractfile(x) as f:
    while b:=f.read(2**20):n+=len(b);h.update(b)
   seen[k]=[n,h.hexdigest()]
assert proc.wait()==0 and seen==m['files'] and dirs==set(m['dirs']);(p/'restore-verified.json').write_text(json.dumps(proof));print(json.dumps(proof),flush=True)
"""
    )
    proof = json.loads(output([*other, "nice -n 12 ionice -c2 -n7 python3 -I -"], prog))
    assert proof["manifest"] == released["manifest"]
    assert proof["sha256"] == released["archive"]
    # The working archive on 0 is now only a byte-identical duplicate of the verified copy on 3.
    scrub = (
        (D / "tree.py").read_text()
        + f"""\nfrom pathlib import Path
p=Path({SPOOL!r});r=json.loads((p/'released.json').read_bytes());assert r['source_empty'] and r['archive']=={proof["sha256"]!r};f=p/'raw.tar.zst';assert f.is_file() and not f.is_symlink() and checksum(f)==r['archive'];f.unlink();(p/'offsite-complete.json').write_text({json.dumps(proof)!r});print('released compressed transit archive on 0')"""
    )
    print(output([*SSH, "python3 -I -"], scrub), flush=True)
    for resource in [
        "pod/" + NAME,
        "service/" + original,
        "networkpolicy/" + original,
        "secret/" + original,
        "configmap/" + NAME,
        "configmap/" + original,
    ]:
        output([*K, "delete", resource, "--ignore-not-found", "--wait=false"])
    print(
        "verified independent cold archive on socrat-3:",
        SPOOL,
        proof["sha256"],
        flush=True,
    )


if __name__ == "__main__":
    main()
