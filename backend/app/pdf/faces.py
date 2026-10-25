"""The Thaana face for server-side rendering (signed PDFs and link-preview images).

The bundled face is Noto Sans Thaana (SIL OFL). An operator can supply another Thaana TrueType
or OpenType font (``JUSTFORMS_THAANA_FONT_FILE``, optionally ``JUSTFORMS_THAANA_FONT_BOLD_FILE``)
whose licence allows it; JustForms never ships one. A supplied font is checked once per process:
it must open, have outlines and cover the Thaana letters. For PDFs its embedding permissions
(OS/2 ``fsType``) must also allow embedding a subset; link-preview images are rasterised and
never contain the font. When a check fails the bundled face is used and a warning is logged
once.

The supplied face is only used for the characters the bundled face covers (the Thaana block,
Arabic-script punctuation, digits and common punctuation), so Latin words in Dhivehi text keep
the Latin face, as on the web (DESIGN-SYSTEM 4.1).
"""

from __future__ import annotations

import hashlib
import io
import logging
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.config import Settings

log = logging.getLogger(__name__)

FONTS = Path(__file__).parent / "fonts"
BUNDLED_REGULAR = FONTS / "NotoSansThaana-Regular.ttf"
BUNDLED_BOLD = FONTS / "NotoSansThaana-Bold.ttf"
# Larger files are refused (a Thaana face is tens to hundreds of kilobytes).
MAX_FONT_BYTES = 20 * 1024 * 1024
# Letters and vowel signs a usable Thaana face must have: U+0780..U+07B0.
THAANA_REQUIRED = range(0x0780, 0x07B1)
# fsType bits (OpenType OS/2): restricted licence, no subsetting, bitmap embedding only.
FS_RESTRICTED = 0x0002
FS_NO_SUBSETTING = 0x0100
FS_BITMAP_ONLY = 0x0200

Purpose = Literal["pdf", "image"]


@dataclass(frozen=True)
class ThaanaFace:
    name: str
    regular: Path
    bold: Path
    # Codepoints the face is used for (None: all it has).
    unicode_range: tuple[int, ...] | None
    # Changes when the face changes (part of the link-preview image version).
    version: str
    bundled: bool


BUNDLED = ThaanaFace(
    "Noto Sans Thaana", BUNDLED_REGULAR, BUNDLED_BOLD, None, "noto-sans-thaana", True
)


class FontRejected(ValueError):
    pass


@lru_cache(maxsize=1)
def _bundled_coverage() -> tuple[int, ...]:
    from fontTools.ttLib import TTFont

    with TTFont(str(BUNDLED_REGULAR), lazy=True) as font:
        return tuple(sorted(font.getBestCmap()))


def _check(path: Path, purpose: Purpose) -> tuple[str, set[int], bytes]:
    """(family name, codepoints, file bytes) of a usable font file, else FontRejected."""
    from fontTools.ttLib import TTFont, TTLibError

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FontRejected(f"cannot read {path}: {exc.strerror or exc}") from exc
    if len(data) > MAX_FONT_BYTES:
        raise FontRejected(f"{path} is larger than {MAX_FONT_BYTES // (1024 * 1024)} MB")
    try:
        with TTFont(io.BytesIO(data), lazy=True) as font:
            if "glyf" not in font and "CFF " not in font and "CFF2" not in font:
                raise FontRejected(f"{path} has no glyph outlines")
            cmap = font.getBestCmap() or {}
            fs_type = int(font["OS/2"].fsType) if "OS/2" in font else 0
            name = font["name"].getBestFamilyName() if "name" in font else None
    except FontRejected:
        raise
    except (TTLibError, KeyError, AssertionError, struct.error, ValueError) as exc:
        raise FontRejected(f"{path} is not a TrueType/OpenType font: {exc}") from exc
    missing = [c for c in THAANA_REQUIRED if c not in cmap]
    if missing:
        first = f"U+{missing[0]:04X}"
        raise FontRejected(f"{path} lacks {len(missing)} Thaana characters (e.g. {first})")
    if purpose == "pdf":
        if fs_type & FS_RESTRICTED:
            raise FontRejected(f"{path} does not allow embedding (fsType {fs_type:#06x})")
        if fs_type & (FS_NO_SUBSETTING | FS_BITMAP_ONLY):
            raise FontRejected(
                f"{path} allows only whole-font or bitmap embedding (fsType {fs_type:#06x})"
            )
    return name or path.stem, set(cmap), data


@lru_cache(maxsize=8)
def _load(regular: str, bold: str, purpose: Purpose) -> ThaanaFace:
    try:
        name, cmap, data = _check(Path(regular), purpose)
        bold_path = Path(bold) if bold else Path(regular)
        bold_data = b""
        if bold:
            _, bold_cmap, bold_data = _check(bold_path, purpose)
            cmap &= bold_cmap
    except FontRejected as exc:
        log.warning(
            "Thaana font for %s rendering not used, falling back to %s: %s",
            purpose,
            BUNDLED.name,
            exc,
        )
        return BUNDLED
    used = tuple(c for c in _bundled_coverage() if c in cmap)
    version = hashlib.sha256(data + b"\x1f" + bold_data).hexdigest()[:12]
    log.info("Thaana font for %s rendering: %s (%s)", purpose, name, regular)
    return ThaanaFace(name, Path(regular), bold_path, used, version, False)


def thaana_face(settings: Settings, purpose: Purpose) -> ThaanaFace:
    """The Thaana face for ``purpose``: the operator's font when set and usable, else the
    bundled Noto Sans Thaana."""
    regular = settings.thaana_font_file.strip()
    if not regular:
        return BUNDLED
    return _load(regular, settings.thaana_font_bold_file.strip(), purpose)
