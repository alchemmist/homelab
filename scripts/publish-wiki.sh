#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_SHA:?}"
: "${GITHUB_OUTPUT:?}"
: "${RUNNER_TEMP:?}"
: "${WIKI_IMAGE_DIGEST:?}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$WIKI_IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]

target=${1:-wiki}
case "$target" in
  wiki) source_dir=wiki; workflow=.github/workflows/wiki.yml ;;
  wiki-editor) source_dir=wiki-editor; workflow=.github/workflows/wiki-editor.yml ;;
  *) exit 2 ;;
esac
source_paths=("$source_dir")
if [[ "$target" == wiki-editor ]]; then source_paths+=(wiki ':!wiki/content'); fi
publish_branch="$target-publish"
chart_dir="charts/$target"
git fetch origin main
if ! git diff --quiet "$GITHUB_SHA" origin/main -- "${source_paths[@]}" "$chart_dir" scripts/publish-wiki.sh "$workflow"; then
  echo 'A newer wiki change exists on main; skipping stale publication.'
  echo 'promoted=false' >> "$GITHUB_OUTPUT"
  exit 0
fi

bundle_dir=$(mktemp -d "$RUNNER_TEMP/wiki-bundle.XXXXXX")
helm template "$target" "$chart_dir" --namespace wiki --set-string "image.digest=$WIKI_IMAGE_DIGEST" > "$bundle_dir/manifests.yaml"
cat > "$bundle_dir/fleet.yaml" <<FLEET
namespace: wiki
createNamespace: false
helm:
  releaseName: $target
  timeoutSeconds: 300
  atomic: true
FLEET

publish_dir=$(mktemp -d "$RUNNER_TEMP/wiki-publish.XXXXXX")
if git ls-remote --exit-code --heads origin "$publish_branch" > /dev/null; then
  git fetch origin "$publish_branch"
  git worktree add --detach "$publish_dir" FETCH_HEAD
else
  git worktree add --detach "$publish_dir" "$GITHUB_SHA"
  git -C "$publish_dir" checkout --orphan "$publish_branch"
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
if ! git diff --quiet "$GITHUB_SHA" origin/main -- "${source_paths[@]}" "$chart_dir" scripts/publish-wiki.sh "$workflow"; then
  echo 'A newer wiki change arrived during bundle preparation; skipping stale publication.'
  echo 'promoted=false' >> "$GITHUB_OUTPUT"
  exit 0
fi
git -C "$publish_dir" push origin "HEAD:refs/heads/$publish_branch"
echo 'promoted=true' >> "$GITHUB_OUTPUT"
