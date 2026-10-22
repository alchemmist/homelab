#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
android_dir="$root/android"
cache_dir="${ANDROID_TOOL_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/homelab-android-tools}"
release_dir="$android_dir/releases"
debug_certificate_sha256="1e08a903aef9c3a721510b64ec764d01d3d094eb954161b62544ea8f187b5953"

mkdir -p "$cache_dir" "$release_dir"

fetch_tool() {
    local path="$1"
    local url="$2"
    local expected_sha256="$3"
    local actual_sha256

    if [ ! -f "$path" ]; then
        curl -fsSL "$url" -o "$path"
    fi

    actual_sha256="$(shasum -a 256 "$path" | awk '{print $1}')"
    if [ "$actual_sha256" != "$expected_sha256" ]; then
        printf 'Unexpected SHA-256 for %s: %s\n' "$path" "$actual_sha256" >&2
        exit 1
    fi
}

apktool="${APKTOOL_JAR:-$cache_dir/apktool_2.11.1.jar}"
signer="${UBER_APK_SIGNER_JAR:-$cache_dir/uber-apk-signer-1.3.0.jar}"

fetch_tool "$apktool" "https://github.com/iBotPeaches/Apktool/releases/download/v2.11.1/apktool_2.11.1.jar" "56d59c524fc764263ba8d345754d8daf55b1887818b15cd3b594f555d249e2db"
fetch_tool "$signer" "https://github.com/patrickfav/uber-apk-signer/releases/download/v1.3.0/uber-apk-signer-1.3.0.jar" "e1299fd6fcf4da527dd53735b56127e8ea922a321128123b9c32d619bba1d835"

source_sha256="$(python3 - "$android_dir" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = [root / "build.sh"]
for app in ("tv-mode", "tv-grafana"):
    paths.extend(path for path in (root / app).rglob("*") if path.is_file() and "build" not in path.parts)

digest = hashlib.sha256()
for path in sorted(paths):
    digest.update(path.relative_to(root).as_posix().encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
)"
state_file="$release_dir/.build-state"

release_sha256="$(for app in tv-mode tv-grafana; do
    if [ -f "$release_dir/$app.apk" ]; then
        shasum -a 256 "$release_dir/$app.apk" | awk '{print $1}'
    fi
done)"

if [ -f "$state_file" ] && [ -f "$release_dir/tv-mode.apk" ] && [ -f "$release_dir/tv-grafana.apk" ] && [ "$(cat "$state_file")" = "$(printf '%s\n%s' "$source_sha256" "$release_sha256")" ]; then
    for app in tv-mode tv-grafana; do
        java -jar "$signer" -a "$release_dir/$app.apk" -y --verifySha256 "$debug_certificate_sha256" >/dev/null
    done
    printf 'Sources and helper APKs are unchanged in %s\n' "$release_dir"
    exit 0
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

for app in tv-mode tv-grafana; do
    java -jar "$apktool" b "$android_dir/$app" -o "$temporary_dir/$app.apk"
    java -jar "$signer" -a "$temporary_dir/$app.apk" -o "$temporary_dir/signed" >/dev/null
    signed_apk="$temporary_dir/signed/$app-aligned-debugSigned.apk"
    java -jar "$signer" -a "$signed_apk" -y --verifySha256 "$debug_certificate_sha256" >/dev/null
    cp "$signed_apk" "$release_dir/$app.apk"
done

release_sha256="$(for app in tv-mode tv-grafana; do shasum -a 256 "$release_dir/$app.apk" | awk '{print $1}'; done)"
printf '%s\n%s' "$source_sha256" "$release_sha256" > "$state_file"

printf 'Built helper APKs in %s\n' "$release_dir"
