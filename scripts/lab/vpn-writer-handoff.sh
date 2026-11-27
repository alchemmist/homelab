#!/usr/bin/env bash
# Isolated Linux process/port handoff experiment; never contacts a cluster.
set -euo pipefail
id="vpn-handoff-$$-$RANDOM"
img=python:3.13-slim
vol="$id-state"
cleanup() {
  docker rm -f "$id-a" "$id-b" "$id-net" >/dev/null 2>&1 || true
  docker volume rm "$vol" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker volume create "$vol" >/dev/null
docker run -d --name "$id-net" --network none "$img" sleep 240 >/dev/null
# Both runtimes share a network namespace, a lock inode and a synthetic DB.
program='import fcntl, socket, sqlite3, sys, time
owner=sys.argv[1]
with open("/state/owner.lock","a") as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 with sqlite3.connect("/state/test.sqlite") as db:
  db.execute("create table if not exists starts(owner text)")
  db.execute("insert into starts values (?)", (owner,))
 with socket.socket() as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  s.bind(("127.0.0.1",8443)); s.listen()
  while True:
   c,_=s.accept()
   with c: c.sendall(owner.encode())'
start() { docker run -d --name "$id-$1" --network "container:$id-net" -v "$vol:/state" "$img" python -c "$program" "$1" >/dev/null; }
probe() { docker exec "$id-net" python -c 'import socket,sys,time
end=time.monotonic()+6
while time.monotonic()<end:
 try:
  with socket.create_connection(("127.0.0.1",8443),.3) as s:
   if s.recv(8).decode()==sys.argv[1]: break
 except OSError: pass
 time.sleep(.02)
else: sys.exit("wrong or missing owner")' "$1"; }
start a; probe a; start b; probe a
docker restart -t 0 "$id-b" >/dev/null; probe a
docker kill "$id-a" >/dev/null; probe b
docker start "$id-a" >/dev/null; probe b
docker kill "$id-b" >/dev/null; probe a
docker exec "$id-a" python -c 'import sqlite3
with sqlite3.connect("/state/test.sqlite") as db:
 assert db.execute("pragma integrity_check").fetchone()==("ok",)
 assert list(db.execute("select owner from starts order by rowid"))==[("a",),("b",),("a",)]'
echo 'PASS: waiting runtime restart, writer transfer, reverse transfer and SQLite integrity'
