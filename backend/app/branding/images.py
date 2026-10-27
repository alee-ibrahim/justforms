"""Validate and clean branding images (logo, dark logo, icon).

Only PNG and SVG are accepted. PNGs are decoded with Pillow (a real image, sane size); SVGs
are parsed with defusedxml (no DTDs or entities) and rebuilt from an allow-list of shape,
text, gradient and clip elements and presentation attributes. Scripts, event handlers,
``<style>``, ``<foreignObject>``, ``<image>``, external references and ``url()`` values other
than local ``#id`` fragments are refused rather than silently dropped, so what the
administrator sees in the preview is exactly what every page serves.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from PIL import Image, UnidentifiedImageError

Kind = Literal["logo", "logo_dark", "icon"]
KINDS: tuple[Kind, ...] = ("logo", "logo_dark", "icon")

MAX_BYTES = 512 * 1024
MAX_SIDE = 4096
ICON_MIN = 64
ICON_MAX = 1024

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"


class BrandImageError(ValueError):
    """``code`` is the API error detail (the studio maps it to copy)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CleanImage:
    data: bytes
    mime: Literal["image/png", "image/svg+xml"]
    width: int
    height: int

    @property
    def ext(self) -> str:
        return "png" if self.mime == "image/png" else "svg"


# Logos are shallow; deeper nesting is refused (and would exhaust recursion when rebuilt).
MAX_SVG_DEPTH = 64

ELEMENTS = {
    "svg", "g", "defs", "title", "desc", "symbol", "use",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask",
}  # fmt: skip

ATTRIBUTES = {
    "id", "class", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "d", "points", "transform", "preserveAspectRatio",
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
    "stroke-dashoffset", "opacity", "clip-path", "clip-rule", "mask", "color",
    "offset", "stop-color", "stop-opacity", "gradientUnits", "gradientTransform",
    "spreadMethod", "fx", "fy", "fr", "clipPathUnits", "maskUnits", "maskContentUnits",
    "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "letter-spacing", "dx", "dy", "style", "role", "aria-label",
    "aria-hidden", "focusable", "version", "visibility", "display", "vector-effect",
    "shape-rendering", "href",
}  # fmt: skip

# Allowed inside style="" and presentation attributes: no url() except url(#id), no
# expressions, imports, escapes or javascript.
_BAD_VALUE = re.compile(
    r"(javascript:|expression\s*\(|@import|\\|data:|url\s*\(\s*(?!['\"]?#))", re.I
)


def _local(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return None, tag


def _clean_svg(raw: bytes) -> CleanImage:
    text = raw.decode("utf-8", errors="strict") if raw else ""
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        raise BrandImageError("svg_unsafe")
    try:
        root = SafeET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError):
        raise BrandImageError("svg_unsafe") from None
    if _local(root.tag) != (SVG_NS, "svg"):
        raise BrandImageError("bad_type")

    def rebuild(el: ET.Element, depth: int = 0) -> ET.Element:
        if depth > MAX_SVG_DEPTH:
            raise BrandImageError("svg_unsafe")
        ns, name = _local(el.tag)
        if ns != SVG_NS or name not in ELEMENTS:
            raise BrandImageError("svg_unsafe")
        out = ET.Element(name)
        for key, value in el.attrib.items():
            ans, aname = _local(key)
            if ans == XLINK_NS and aname == "href":
                aname = "href"
            elif ans is not None:
                raise BrandImageError("svg_unsafe")
            if aname.lower().startswith("on") or aname not in ATTRIBUTES:
                raise BrandImageError("svg_unsafe")
            if aname == "href" and not value.startswith("#"):
                raise BrandImageError("svg_unsafe")
            if _BAD_VALUE.search(value):
                raise BrandImageError("svg_unsafe")
            out.set(aname, value)
        out.text = el.text
        out.tail = el.tail
        for child in el:
            out.append(rebuild(child, depth + 1))
        return out

    clean = rebuild(root)
    clean.set("xmlns", SVG_NS)
    width, height = _svg_size(clean)
    data = ET.tostring(clean, encoding="unicode").encode()
    return CleanImage(data, "image/svg+xml", width, height)


def _svg_size(el: ET.Element) -> tuple[int, int]:
    box = el.get("viewBox")
    if box:
        parts = re.split(r"[\s,]+", box.strip())
        if len(parts) == 4:
            try:
                w, h = float(parts[2]), float(parts[3])
                if w > 0 and h > 0:
                    return round(w), round(h)
            except ValueError:
                pass
    try:
        w = float(re.sub(r"px$", "", el.get("width", "")))
        h = float(re.sub(r"px$", "", el.get("height", "")))
        if w > 0 and h > 0:
            return round(w), round(h)
    except ValueError:
        pass
    raise BrandImageError("svg_no_size")


def _clean_png(raw: bytes) -> CleanImage:
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.verify()
        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "PNG":
                raise BrandImageError("bad_type")
            width, height = img.size
            if width > MAX_SIDE or height > MAX_SIDE:
                raise BrandImageError("too_large_pixels")
            img.load()
            # Re-encode: drops text chunks and anything trailing the image data.
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise BrandImageError("bad_type") from None
    return CleanImage(out.getvalue(), "image/png", width, height)


def clean_image(kind: Kind, raw: bytes) -> CleanImage:
    """Validate and clean an upload for ``kind``; raises :class:`BrandImageError`."""
    if len(raw) > MAX_BYTES:
        raise BrandImageError("too_large")
    if not raw:
        raise BrandImageError("bad_type")
    if raw.startswith(PNG_MAGIC):
        img = _clean_png(raw)
    elif b"<svg" in raw[:4096]:
        img = _clean_svg(raw)
    else:
        raise BrandImageError("bad_type")
    if kind == "icon":
        if abs(img.width - img.height) > max(1, img.width // 100):
            raise BrandImageError("not_square")
        if img.mime == "image/png" and not ICON_MIN <= img.width <= ICON_MAX:
            raise BrandImageError("icon_size")
    return img
