"""Turn an uploaded blank paper form (PDF or photo) into page images for a vision model.

PDF pages are rendered at 150 dpi with pypdfium2 (at most ``MAX_PAGES``), scaled down so the
bitmap is never more than ``MAX_SIDE`` pixels on its longer side whatever the page box says;
photos are turned upright from their EXIF orientation. Every page becomes a JPEG at most
``MAX_SIDE`` pixels on its longer side. Everything happens in memory: the document is never
stored.

Memory stays bounded: a page box larger than ``MAX_PAGE_POINTS`` is refused, a PDF page is
rendered straight at the small size, and an image larger than ``MAX_PIXELS`` (after JPEG's
draft decoding, which reads big photos at 1/2, 1/4 or 1/8 of their size) is refused before
its pixels are decoded. Pillow's process-wide ``MAX_IMAGE_PIXELS`` is left alone.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.ai.types import ImagePart
from app.uploads.sniff import JPEG, PDF, PNG, WEBP, detect

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 10
MAX_SIDE = 2048
DPI = 150
# The largest page box accepted (200 inches, the PDF format's own limit without UserUnit).
MAX_PAGE_POINTS = 14_400.0
# The most pixels decoded for one image (a 40-megapixel photo).
MAX_PIXELS = 40_000_000
ACCEPTED = {PDF.mime, JPEG.mime, PNG.mime, WEBP.mime}


class DocumentError(Exception):
    """``code``: unsupported_file, too_many_pages, unreadable_file or image_too_large."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class PreparedDocument:
    mime: str
    pages: list[ImagePart]


def _jpeg(image: Image.Image) -> ImagePart:
    # Shrink first, then convert: a converted full-size copy is what costs memory.
    if image.mode == "1":
        image = image.convert("L")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85, optimize=True)
    return ImagePart(out.getvalue(), "image/jpeg")


def render_scale(width: float, height: float) -> float:
    """The pdfium scale for a page of ``width`` x ``height`` points: 150 dpi, or less so the
    longer side is at most ``MAX_SIDE`` pixels. Refuses absurd page boxes."""
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        raise DocumentError("unreadable_file")
    if max(width, height) > MAX_PAGE_POINTS:
        raise DocumentError("unreadable_file")
    return min(DPI / 72, MAX_SIDE / max(width, height))


def _pdf(data: bytes) -> list[ImagePart]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise DocumentError("unreadable_file") from exc
    try:
        if len(pdf) == 0:
            raise DocumentError("unreadable_file")
        if len(pdf) > MAX_PAGES:
            raise DocumentError("too_many_pages")
        pages: list[ImagePart] = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                width, height = page.get_size()
                bitmap = page.render(scale=render_scale(width, height))
                try:
                    pages.append(_jpeg(bitmap.to_pil()))
                finally:
                    bitmap.close()
            except pdfium.PdfiumError as exc:
                raise DocumentError("unreadable_file") from exc
            finally:
                page.close()
        return pages
    finally:
        pdf.close()


def _image(data: bytes) -> ImagePart:
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format == "JPEG":
                # Decode at 1/2, 1/4 or 1/8 scale when that is still at least MAX_SIDE.
                img.draft("RGB", (MAX_SIDE, MAX_SIDE))
            width, height = img.size
            if width <= 0 or height <= 0:
                raise DocumentError("unreadable_file")
            if width * height > MAX_PIXELS:
                raise DocumentError("image_too_large")
            upright = ImageOps.exif_transpose(img)
            return _jpeg(upright or img)
    except Image.DecompressionBombError as exc:
        raise DocumentError("image_too_large") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise DocumentError("unreadable_file") from exc


def prepare(data: bytes) -> PreparedDocument:
    kind = detect(data[:4096])
    if kind is None or kind.mime not in ACCEPTED:
        raise DocumentError("unsupported_file")
    if kind.mime == PDF.mime:
        return PreparedDocument(kind.mime, _pdf(data))
    return PreparedDocument(kind.mime, [_image(data)])
