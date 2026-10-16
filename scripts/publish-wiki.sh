#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_SHA:?}"
: "${GITHUB_OUTPUT:?}"
: "${RUNNER_TEMP:?}"
: "${WIKI_IMAGE_DIGEST:?}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$WIKI_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]

git fetch origin main
if ! git diff --quiet "$GITHUB_SHA" origin/main -- wiki charts/wiki scripts/publish-wiki.sh .github/workflows/wiki.yml; then
  echo 'A newer wiki change exists on main; skipping stale publication.'
  echo 'promoted=false' >> "$GITHUB_OUTPUT"
  exit 0
fi

bundle_dir=$(mktemp -d "$RUNNER_TEMP/wiki-bundle.XXXXXX")
helm template wiki charts/wiki --namespace wiki --set-string "image.digest=$WIKI_IMAGE_DIGEST" > "$bundle_dir/manifests.yaml"
cat > "$bundle_dir/fleet.yaml" <<'FLEET'
namespace: wiki
createNamespace: false
helm:
  releaseName: wiki
  timeoutSeconds: 300
  atomic: true
FLEET

publish_dir=$(mktemp -d "$RUNNER_TEMP/wiki-publish.XXXXXX")
if git ls-remote --exit-code --heads origin wiki-publish > /dev/null; then
  git fetch origin wiki-publish
  git worktree add --detach "$publish_dir" FETCH_HEAD
else
  git worktree add --detach "$publish_dir" "$GITHUB_SHA"
  git -C "$publish_dir" checkout --orphan wiki-publish
  git -C "$publish_dir" rm -rf .
fi
trap 'git worktree remove --force "$publish_dir"; rm -rf "$bundle_dir"' EXIT
mkdir -p "$publish_dir/bundle"
cp "$bundle_dir/"*.yaml "$publish_dir/bundle/"
git -C "$publish_dir" config user.name 'github-actions[bot]'
git -C "$publish_dir" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$publish_dir" add bundle
if ! git -C "$publish_dir" diff --cached --quiet; then
  git -C "$publish_dir" commit -m "publish wiki ${GITHUB_SHA:0:12}"
fi

git fetch origin main
if ! git diff --quiet "$GITHUB_SHA" origin/main -- wiki charts/wiki scripts/publish-wiki.sh .github/workflows/wiki.yml; then
  echo 'A newer wiki change arrived during bundle preparation; skipping stale publication.'
  echo 'promoted=false' >> "$GITHUB_OUTPUT"
  exit 0
fi
git -C "$publish_dir" push origin HEAD:refs/heads/wiki-publish
echo 'promoted=true' >> "$GITHUB_OUTPUT"
