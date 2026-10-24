"""Header and background images for form themes (docs/ux/FORM-THEME-SCREENS.md section 3.1).

PNG, JPEG or WebP, up to 2 MB and 4096 px a side. Each upload is decoded with Pillow and
re-encoded as WebP, which drops metadata (location, camera) and anything that isn't pixels.
Stored through the storage abstraction under ``theme/{org_id}/{sha16}.webp`` and referenced
from a theme by that file name.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 2 * 1024 * 1024
MAX_SIDE = 4096
FORMATS = {"PNG", "JPEG", "WEBP"}
REF = re.compile(r"^[0-9a-f]{16}\.webp$")


class ThemeImageError(ValueError):
    """``code`` is the API error detail (the studio maps it to copy)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ThemeImage:
    data: bytes
    width: int
    height: int

    @property
    def ref(self) -> str:
        return f"{hashlib.sha256(self.data).hexdigest()[:16]}.webp"


def storage_key(org_id: uuid.UUID, ref: str) -> str:
    if not REF.match(ref):
        raise ThemeImageError("bad_ref")
    return f"theme/{org_id}/{ref}"


def clean_image(raw: bytes) -> ThemeImage:
    if len(raw) > MAX_BYTES:
        raise ThemeImageError("too_large")
    if not raw:
        raise ThemeImageError("bad_type")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            width, height = probe.size
            if fmt not in FORMATS:
                raise ThemeImageError("bad_type")
            if width > MAX_SIDE or height > MAX_SIDE or width < 1 or height < 1:
                raise ThemeImageError("too_large_pixels")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            img: Image.Image = ImageOps.exif_transpose(opened)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert(
                    "RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB"
                )
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=85, method=4)
            width, height = img.size
    except ThemeImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ThemeImageError("bad_type") from exc
    return ThemeImage(out.getvalue(), width, height)
