#!/bin/sh
# Existing private asset directory is an input, never tracked or placed in a chart.
set -eu
src=${1:?usage: build-local.sh /private/assets}
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
context=$(mktemp -d)
trap 'rm -rf "$context"' EXIT
mkdir "$context/assets" "$context/app"
cp "$here/Dockerfile" "$here/library_manifest.py" "$context/"
cp "$here/../../charts/spi-triage/files/"*.py "$context/app/"
for name in tokenizer.json tokenizer_config.json chat_template.jinja README.md tokenizers-0.22.2-cp39-abi3-musllinux_1_2_x86_64.whl; do
  cp "$src/$name" "$context/assets/"
done
cp "$here/LICENSE-2.0.txt" "$context/assets/"
cp -R "$here/legal" "$context/assets/legal"
echo 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30  '"$context/assets/LICENSE-2.0.txt" | shasum -a 256 -c -
DOCKER_BUILDKIT=0 docker build --platform linux/amd64 -t spi-local-tokenizer-counter:source-only "$context"
