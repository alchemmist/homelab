#!/usr/bin/env python3
"""Build reviewed, metadata-free WebP derivatives from the owner's dotfiles Nature set.

Local source changes only; never modifies dotfiles or deploys anything.
Requires Pillow with WebP support. Re-run with the same Pillow/libwebp versions for byte parity.
"""

import argparse
import base64
import hashlib
import io
import json
import subprocess
from pathlib import Path
from typing import NamedTuple, Protocol

from PIL import Image, ImageOps, features
from PIL import __version__ as pillow_version


class PILImage(Protocol):
    """Structural subset of PIL.Image.Image operations used by the builders."""

    size: tuple[int, int]

    def save(self, *args: object, **kwargs: object) -> None:
        """Encode the image into the provided buffer at the requested quality."""

    def copy(self) -> "PILImage":
        """Duplicate the image for lossless derivative transformations."""

    def thumbnail(self, size: tuple[int, int], resample: int) -> None:
        """Resize in place so the derivative fits the reviewed bounding box."""


class SceneContext(NamedTuple):
    """Shared facts about the source photo being processed for the scene."""

    record: dict[str, object]
    manifest: dict[str, dict[str, str]]
    dest: Path
    image: PILImage
    path: Path
    ident: str


def _collect_files(source: Path) -> list[Path]:
    """List the Nature wallpapers to derive, ordered deterministically."""
    folder = source / "wallpapers/nature/images"
    files = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not files:
        message = "No Nature images found"
        raise ValueError(message)
    return files


def _ensure_single_frame(image: PILImage) -> None:
    """Reject animated sources so scenes cannot become scripted or multi-state."""
    if getattr(image, "n_frames", 1) != 1:
        message = "Animated images are not allowed"
        raise ValueError(message)


def _encode_webp(derivative: PILImage, cap: int, name: str) -> tuple[bytes, int]:
    """Encode the largest WebP derivative that fits the review byte budget."""
    for quality in [80, 76, 72, 68]:
        buf = io.BytesIO()
        derivative.save(buf, format="WEBP", quality=quality, method=6)
        content = buf.getvalue()
        if len(content) <= cap:
            return content, quality
    message = "Derivative too large: " + name
    raise ValueError(message)


def _encode_avif(derivative: PILImage, label: str) -> tuple[bytes, int]:
    """Encode the AVIF transfer copy under its per-format byte budget."""
    cap = 220000 if label == "desktop" else 100000
    for avif_quality in [45, 42, 38, 34]:
        buf = io.BytesIO()
        derivative.save(buf, format="AVIF", quality=avif_quality, speed=6)
        avif_content = buf.getvalue()
        if len(avif_content) <= cap:
            return avif_content, avif_quality
    message = "AVIF derivative exceeds transfer budget"
    raise ValueError(message)


def _reject_metadata(avif_content: bytes) -> None:
    """Ensure the AVIF encoder did not inherit EXIF/XMP/ICC from the source."""
    with Image.open(io.BytesIO(avif_content)) as decoded:
        if any(decoded.info.get(k) for k in ["exif", "xmp", "icc_profile"]):
            message = "AVIF output must not inherit source metadata"
            raise ValueError(message)


def _add_derivative(
    scene: SceneContext,
    label: str,
    width: int,
    cap: int,
) -> None:
    """Write one responsive size plus its AVIF transfer copy and manifest keys."""
    record, manifest, dest, image, path, ident = (
        scene.record,
        scene.manifest,
        scene.dest,
        scene.image,
        scene.path,
        scene.ident,
    )
    derivative = image.copy()
    derivative.thumbnail((width, width), Image.Resampling.LANCZOS)
    content, quality = _encode_webp(derivative, cap, path.name)
    name = f"nature-{ident}-{width}.webp"
    (dest / name).write_bytes(content)
    key = "NATURE_" + ident.upper() + "_" + label.upper()
    manifest[key] = {
        "path": "nature/" + name,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    record[label] = key
    record[label + "Dimensions"] = list(derivative.size)
    record[label + "Bytes"] = len(content)
    record[label + "Quality"] = quality
    # AVIF is the preferred transfer; keep the reviewed WebP fallback.
    avif_content, avif_quality = _encode_avif(derivative, label)
    _reject_metadata(avif_content)
    avif_name = f"nature-{ident}-{width}.avif"
    (dest / avif_name).write_bytes(avif_content)
    avif_key = key + "_AVIF"
    manifest[avif_key] = {
        "path": "nature/" + avif_name,
        "sha256": hashlib.sha256(avif_content).hexdigest(),
    }
    record[label + "Avif"] = avif_key
    record[label + "AvifBytes"] = len(avif_content)
    record[label + "AvifQuality"] = avif_quality


def build(source, output):
    files = _collect_files(source)
    manifest = json.loads((output / "assets.json").read_text())
    manifest = {k: v for k, v in manifest.items() if not k.startswith("NATURE_")}
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    collection = {
        "repository": "https://github.com/alchemmist/dotfiles",
        "revision": revision,
        "sourceDirectory": "wallpapers/nature/images",
        "pillowVersion": pillow_version,
        "libwebpVersion": features.version("webp"),
        "libavifVersion": features.version("avif"),
        "rights": (
            "Owner-requested existing wallpaper collection; upstream photo rights are not "
            "reassigned."
        ),
        "photos": [],
    }
    dest = output / "nature"
    dest.mkdir(parents=True, exist_ok=True)
    seen = set()
    for path in files:
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        if source_hash in seen:
            message = "Duplicate source image: review selection weights"
            raise ValueError(message)
        seen.add(source_hash)
        ident = source_hash[:12]
        with Image.open(io.BytesIO(raw)) as image:
            _ensure_single_frame(image)
            image = ImageOps.exif_transpose(image).convert("RGB")
            # AVIF inherits ICC from im.info by default; WebP does not. Strip all
            # metadata explicitly so both formats/preview share the same RGB data.
            image.info.clear()
            record: dict[str, object] = {
                "id": ident,
                "source": str(path.relative_to(source)),
                "sourceSha256": source_hash,
                "sourceDimensions": list(image.size),
            }
            for label, width, cap in [("desktop", 1920, 600000), ("mobile", 960, 220000)]:
                _add_derivative(
                    SceneContext(record, manifest, dest, image, path, ident), label, width, cap
                )
            preview = image.copy()
            preview.thumbnail((48, 48), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            preview.save(buf, format="WEBP", quality=25, method=6)
            tiny = base64.b64encode(buf.getvalue()).decode()

            def url(key):
                item = manifest[key]
                return "/-/quiet-mono/v1/" + item["sha256"][:12] + "-" + Path(item["path"]).name

            def layer(label, record=record, tiny=tiny) -> str:
                return (
                    "background-image:url('"
                    + url(record[label])
                    + "'),url('data:image/webp;base64,"
                    + tiny
                    + "')!important;"
                    + "background-image:image-set(url('"
                    + url(record[label + "Avif"])
                    + "') type('image/avif'),url('"
                    + url(record[label])
                    + "') type('image/webp')),url('data:image/webp;base64,"
                    + tiny
                    + "')!important;"
                )

            css = (
                "/* Reviewed scene "
                + ident
                + "; same-photo inline preview, no script. */\nbody::before{--qm-scene:"
                + ident
                + ";"
                + layer("desktop")
                + "}\n@media(max-width:700px){body::before{"
                + layer("mobile")
                + "}}\n"
            )
            css_name = "nature-" + ident + ".css"
            (dest / css_name).write_text(css)
            css_key = "NATURE_" + ident.upper() + "_CSS"
            manifest[css_key] = {
                "path": "nature/" + css_name,
                "sha256": hashlib.sha256(css.encode()).hexdigest(),
            }
            record["sceneCss"] = css_key
            record["previewBytes"] = len(buf.getvalue())
            record["sceneCssBytes"] = len(css.encode())
            collection["photos"].append(record)
    (output / "assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "nature.json").write_text(json.dumps(collection, indent=2) + "\n")
    print(
        json.dumps(
            {
                "photos": len(collection["photos"]),
                "derivativeBytes": sum(
                    p["desktopBytes"]
                    + p["mobileBytes"]
                    + p["desktopAvifBytes"]
                    + p["mobileAvifBytes"]
                    for p in collection["photos"]
                ),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "deploy/authentik/quiet-mono",
    )
    args = parser.parse_args()
    build(args.source, args.output)
