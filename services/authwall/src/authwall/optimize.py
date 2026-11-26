"""Build a full-size WebP and a tiny blurred stand-in from an upload."""

import io

from PIL import Image, ImageFilter, ImageOps


def _open(raw: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(raw))
    image = ImageOps.exif_transpose(image)
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("animated images are not allowed")
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGB")
    return image


def _webp(image: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def full_webp(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as original:
        if getattr(original, "n_frames", 1) != 1:
            raise ValueError("animated images are not allowed")
        if original.format == "WEBP":
            return raw
        image = ImageOps.exif_transpose(original)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info or "A" in image.getbands() else "RGB")
        output = io.BytesIO()
        image.save(output, format="WEBP", lossless=True, method=6, exact=True,
                   icc_profile=image.info.get("icc_profile", b""))
        return output.getvalue()


def derivatives(raw: bytes) -> tuple[bytes, bytes, int, int]:
    """Return optimized WebP, blurred preview WebP, and source pixel size."""
    image = _open(raw)
    width, height = image.size
    thumb = image.copy().convert("RGB")
    thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
    thumb = thumb.filter(ImageFilter.GaussianBlur(radius=0.4))
    return full_webp(raw), _webp(thumb, 62), width, height
