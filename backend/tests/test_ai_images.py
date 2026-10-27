"""Paper form import: page images stay small whatever the document claims (a tiny PDF with a
huge page box, a small PNG with a huge canvas), and oversized images are a clean refusal."""

from __future__ import annotations

import io
import time

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.ai import images
from app.ai.images import MAX_SIDE, DocumentError, prepare, render_scale


def pdf_with_pages(width: float, height: float, pages: int = 1) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(width, height)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def bilevel_png(side: int) -> bytes:
    buf = io.BytesIO()
    Image.new("1", (side, side), 1).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def test_huge_pdf_page_box_renders_small_and_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a few hundred bytes of PDF with 14400 pt pages rendered at 150 dpi to
    30000 x 30000 px (900 M pixels, ~7 GB). The scale is now chosen so the bitmap's longer
    side is at most MAX_SIDE."""
    data = pdf_with_pages(14400, 14400, pages=10)
    assert len(data) < 5000
    scales: list[float] = []
    real = pdfium.PdfPage.render

    def spy(self: pdfium.PdfPage, *args: object, **kwargs: object) -> pdfium.PdfBitmap:
        scales.append(float(kwargs["scale"]))  # type: ignore[arg-type]
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pdfium.PdfPage, "render", spy)
    start = time.monotonic()
    doc = prepare(data)
    took = time.monotonic() - start
    assert len(doc.pages) == 10
    assert all(round(s * 14400) <= MAX_SIDE for s in scales)
    for page in doc.pages:
        img = Image.open(io.BytesIO(page.data))
        assert max(img.size) <= MAX_SIDE
    assert took < 10


def test_page_scale() -> None:
    # A4 keeps 150 dpi; a poster is scaled down; absurd boxes are refused.
    assert render_scale(595, 842) == pytest.approx(150 / 72)
    assert render_scale(2384, 3370) * 3370 == pytest.approx(MAX_SIDE)
    for w, h in ((0, 100), (-5, 100), (100, float("inf")), (20_000, 100)):
        with pytest.raises(DocumentError) as err:
            render_scale(w, h)
        assert err.value.code == "unreadable_file"


def test_decompression_bomb_png_is_refused() -> None:
    """Regression: a 20000 x 20000 PNG (76 KB) raised an uncaught DecompressionBombError (a
    500), and 13000 x 13000 used over 1 GB. Both are now refused before decoding."""
    for side in (13_000, 20_000):
        with pytest.raises(DocumentError) as err:
            prepare(bilevel_png(side))
        assert err.value.code == "image_too_large"


def test_big_jpeg_photo_is_read_with_draft_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """A large phone photo is decoded at a reduced scale, so it fits under the pixel cap."""
    buf = io.BytesIO()
    Image.new("L", (9000, 6000), 200).save(buf, "JPEG", quality=50)
    doc = prepare(buf.getvalue())
    img = Image.open(io.BytesIO(doc.pages[0].data))
    assert max(img.size) == MAX_SIDE
    # Without draft decoding (a PNG of the same size) it is refused.
    monkeypatch.setattr(images, "MAX_PIXELS", 30_000_000)
    png = io.BytesIO()
    Image.new("L", (9000, 6000), 200).save(png, "PNG")
    with pytest.raises(DocumentError):
        prepare(png.getvalue())
