#!/usr/bin/env bash
# Operator-only, on socrat-0. Transfer immutable public source + independent venv.
set -euo pipefail
umask 077
cd "$HOME/pi-monori-509-v1"
sourcepod=(kubectl -n openhands exec openhands-0 -c mutation-pilot --)
"${sourcepod[@]}" sh -ec 'test -s /scratch/pi-pilot-deps.tgz || (cd /scratch/monori; tar czf /scratch/pi-pilot-deps.tmp .venv; mv /scratch/pi-pilot-deps.tmp /scratch/pi-pilot-deps.tgz)'
read -r expected _ < <("${sourcepod[@]}" sha256sum /scratch/pi-pilot-deps.tgz)
bytes=$("${sourcepod[@]}" stat -c %s /scratch/pi-pilot-deps.tgz)
if ! echo "$expected  deps.tar.gz" | sha256sum -c - >/dev/null 2>&1;then
 : >deps.tmp
 for ((i=0;i*2097152<bytes;i++));do "${sourcepod[@]}" dd if=/scratch/pi-pilot-deps.tgz bs=2097152 skip="$i" count=1 status=none >>deps.tmp;done
 echo "$expected  deps.tmp" | sha256sum -c -;mv deps.tmp deps.tar.gz
fi
for role in judge author;do
 dest=(kubectl -n openhands exec -i deploy/pi-monori-"$role" -c sandbox --)
 "${dest[@]}" sh -ec 'mkdir -p /scratch/monori /scratch/home; : >/scratch/incoming.tmp' </dev/null
 for ((i=0;i*2097152<bytes;i++));do dd if=deps.tar.gz bs=2097152 skip="$i" count=1 status=none | "${dest[@]}" sh -c 'cat >>/scratch/incoming.tmp';done
 "${dest[@]}" sh -ec "echo \"\$1  /scratch/incoming.tmp\" | sha256sum -c -; tar xzf /scratch/incoming.tmp -C /scratch/monori; rm /scratch/incoming.tmp" sh "$expected" </dev/null
done
tar czf - base.git | kubectl -n openhands exec -i deploy/pi-monori-author -c sandbox -- sh -ec 'tar xzf - -C /scratch;mkdir -p /scratch/home/.pi/agent; cp /code/models.json /scratch/home/.pi/agent/models.json; /opt/pi/node_modules/.bin/pi --version'
git --git-dir=base.git archive HEAD | kubectl -n openhands exec -i deploy/pi-monori-judge -c sandbox -- sh -ec 'tar xf - -C /scratch/monori'
kubectl -n openhands exec deploy/pi-monori-judge -c sandbox -- sh -ec 'cd /scratch/monori; PYTHONPATH=/scratch .venv/bin/python -m pytest -q server/tests/unit/test_db_records.py'
touch seed.ok
