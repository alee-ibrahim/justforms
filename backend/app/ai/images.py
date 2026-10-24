"""Turn an uploaded blank paper form (PDF or photo) into page images for a vision model.

PDF pages are rendered at 150 dpi with pypdfium2 (at most ``MAX_PAGES``); photos are turned
upright from their EXIF orientation. Every page becomes a JPEG at most ``MAX_SIDE`` pixels on
its longer side. Everything happens in memory: the document is never stored.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.ai.types import ImagePart
from app.uploads.sniff import JPEG, PDF, PNG, WEBP, detect

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 10
MAX_SIDE = 2048
DPI = 150
ACCEPTED = {PDF.mime, JPEG.mime, PNG.mime, WEBP.mime}


class DocumentError(Exception):
    """``code``: unsupported_file, too_many_pages or unreadable_file."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class PreparedDocument:
    mime: str
    pages: list[ImagePart]


def _jpeg(image: Image.Image) -> ImagePart:
    image = image.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85, optimize=True)
    return ImagePart(out.getvalue(), "image/jpeg")


def prepare(data: bytes) -> PreparedDocument:
    kind = detect(data[:4096])
    if kind is None or kind.mime not in ACCEPTED:
        raise DocumentError("unsupported_file")
    if kind.mime == PDF.mime:
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
            pages = [_jpeg(pdf[i].render(scale=DPI / 72).to_pil()) for i in range(len(pdf))]
        finally:
            pdf.close()
        return PreparedDocument(kind.mime, pages)
    try:
        with Image.open(io.BytesIO(data)) as img:
            upright = ImageOps.exif_transpose(img)
            return PreparedDocument(kind.mime, [_jpeg(upright or img)])
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentError("unreadable_file") from exc
