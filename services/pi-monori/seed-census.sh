#!/usr/bin/env bash
# Independent mutation toolchain, no keys or agent artifacts in judge. Chunked, SHA verified.
set -euo pipefail
umask 077
cd "$HOME/pi-monori-509-v1"
s=(kubectl -n openhands exec openhands-0 -c mutation-pilot --)
d=(kubectl -n openhands exec -i deploy/pi-monori-judge -c sandbox --)
"${s[@]}" sh -ec 'cd /scratch/monori; UV_PROJECT_ENVIRONMENT=/scratch/census-venv UV_CACHE_DIR=/scratch/uv-cache HOME=/scratch uv sync --locked --group mutation; cd /scratch; tar czf census-env.tgz census-venv'
read -r sha _ < <("${s[@]}" sha256sum /scratch/census-env.tgz)
bytes=$("${s[@]}" stat -c %s /scratch/census-env.tgz)
"${d[@]}" sh -c ': >/scratch/census-seed.tmp' </dev/null
for ((i=0;i*2097152<bytes;i++));do "${s[@]}" dd if=/scratch/census-env.tgz bs=2097152 skip="$i" count=1 status=none | "${d[@]}" sh -c 'cat >>/scratch/census-seed.tmp';done
"${d[@]}" sh -ec 'cd /scratch;echo "$1  census-seed.tmp"|sha256sum -c -;tar xzf census-seed.tmp;rm census-seed.tmp; cd monori;PYTHONPATH=/scratch /scratch/census-venv/bin/python -m mutmut run --help' sh "$sha" </dev/null
