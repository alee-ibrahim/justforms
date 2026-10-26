"""The generated link-preview image: 1200x630 PNG (docs/ux/SHARING-PREVIEW-SCREENS.md 2).

Drawn as a one-page PDF with fpdf2 and HarfBuzz text shaping (uharfbuzz, the same approach as
the signed PDFs in :mod:`app.pdf.render`), then rasterised with pdfium. Thaana is shaped and
laid out right to left without system libraries (Pillow's own complex text layout needs
libraqm and FriBiDi, which slim containers don't have).

Layout, mirrored for Dhivehi forms: the logo and organisation name at the top start, the form
title (up to three lines, the largest size that fits), an optional description (up to two
lines), the form's address at the bottom start, and a band in the primary colour along the
bottom edge. Colours are the form theme's light values; Latin text uses the bundled Inter
(``app.pdf.faces.LATIN_REGULAR``) and Thaana the install's server Thaana face
(``app.pdf.faces``: the operator's ``JUSTFORMS_THAANA_FONT_FILE``, else the bundled Noto Sans
Thaana).
"""

from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass

from fpdf import FPDF
from fpdf.enums import Align
from PIL import Image

from app.pdf.faces import BUNDLED, LATIN_BOLD, LATIN_REGULAR, ThaanaFace
from app.pdf.render import add_thaana

WIDTH, HEIGHT = 1200, 630
PAD = 72
BAND = 14
LOGO_H = 72
LOGO_MAX_W = 320
TITLE_SIZES = (76, 68, 60, 54, 48, 44)
TITLE_LINES = 3
DESC_SIZE = 30
DESC_LINES = 2
# Thaana reads small next to Latin at the same size (DESIGN 16): one step larger, airier lines.
THAANA_SCALE = 1.12
THAANA = re.compile(r"[ހ-޿]")
ELLIPSIS = "…"
# Bumped when the drawing changes, so cached images are made again.
RENDER_VERSION = "1"

# pdfium is not thread-safe; rendering runs in worker threads.
_pdfium_lock = threading.Lock()


@dataclass(frozen=True)
class Colors:
    background: str = "#FFFFFF"
    text: str = "#18203A"
    muted: str = "#5A6380"
    primary: str = "#3B3FC1"
    border: str = "#DCE0EA"


@dataclass(frozen=True)
class Card:
    title: str
    description: str | None
    org_name: str
    address: str  # host/slug, shown at the bottom
    rtl: bool
    colors: Colors
    logo: bytes | None = None  # PNG or sanitised SVG
    logo_size: tuple[int, int] | None = None
    thaana: ThaanaFace = BUNDLED  # ``app.pdf.faces.thaana_face(settings, "image")``


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def is_thaana(text: str) -> bool:
    return bool(THAANA.search(text))


class _Canvas(FPDF):
    def __init__(self, thaana: ThaanaFace = BUNDLED) -> None:
        # 1 pt = 1 px: rasterised at scale 1 the page is exactly 1200x630.
        super().__init__(orientation="P", unit="pt", format=(WIDTH, HEIGHT))
        self.set_auto_page_break(False)
        self.set_margins(0, 0, 0)
        self.c_margin = 0
        self.add_font("latin", "", str(LATIN_REGULAR))
        self.add_font("latin", "B", str(LATIN_BOLD))
        add_thaana(self, thaana)
        self.add_page()

    def use(self, text: str, size: float, *, bold: bool = False) -> float:
        """Pick the font for ``text`` (Thaana: right to left, a step larger); returns the size
        used."""
        if is_thaana(text):
            size *= THAANA_SCALE
            self.set_font("thaana", "B" if bold else "", size)
            self.set_fallback_fonts(["latin"], exact_match=False)
            self.set_text_shaping(True, direction="rtl", script="thaa", language="div")
        else:
            self.set_font("latin", "B" if bold else "", size)
            self.set_fallback_fonts(["thaana"], exact_match=False)
            self.set_text_shaping(True, direction="ltr")
        return size

    def lines(self, text: str, width: float) -> list[str]:
        out = self.multi_cell(width, 10, text, dry_run=True, output="LINES")
        assert isinstance(out, list)
        return [str(line) for line in out]


def _fit(canvas: _Canvas, text: str, width: float, max_lines: int) -> list[str]:
    """``text`` broken into at most ``max_lines`` lines of ``width``, the last one cut with an
    ellipsis when it doesn't fit (with the current font)."""
    lines = canvas.lines(text, width)
    if len(lines) <= max_lines:
        return lines
    kept = lines[: max_lines - 1]
    rest = " ".join(lines[max_lines - 1 :]).split()
    while rest:
        candidate = " ".join(rest) + ELLIPSIS
        if canvas.get_string_width(candidate) <= width:
            return [*kept, candidate]
        rest.pop()
    return [*kept, ELLIPSIS]


def _text_lines(
    canvas: _Canvas,
    lines: list[str],
    *,
    y: float,
    line_h: float,
    rtl: bool,
    color: str,
) -> float:
    canvas.set_text_color(*_rgb(color))
    width = WIDTH - 2 * PAD
    for line in lines:
        canvas.set_xy(PAD, y)
        canvas.cell(width, line_h, line, align=Align.R if rtl else Align.L)
        y += line_h
    return y


def _logo_box(card: Card) -> tuple[float, float] | None:
    if card.logo is None:
        return None
    w, h = card.logo_size or (0, 0)
    if w <= 0 or h <= 0:
        return None
    height = float(LOGO_H)
    width = height * w / h
    if width > LOGO_MAX_W:
        width = float(LOGO_MAX_W)
        height = width * h / w
    return width, height


def _draw(card: Card) -> bytes:
    c = _Canvas(card.thaana)
    c.set_fill_color(*_rgb(card.colors.background))
    c.rect(0, 0, WIDTH, HEIGHT, style="F")
    c.set_fill_color(*_rgb(card.colors.primary))
    c.rect(0, HEIGHT - BAND, WIDTH, BAND, style="F")
    rtl = card.rtl
    inner = WIDTH - 2 * PAD

    # Header: logo, then the organisation name beside it (on its own when there is no logo).
    y = float(PAD)
    head_h = float(LOGO_H)
    box = _logo_box(card)
    name_start = float(PAD)
    if box is not None and card.logo is not None:
        lw, lh = box
        x = WIDTH - PAD - lw if rtl else PAD
        try:
            c.image(io.BytesIO(card.logo), x=x, y=y + (head_h - lh) / 2, w=lw, h=lh)
            name_start = PAD + lw + 24
        except Exception:  # a logo the PDF library can't draw: the name alone
            name_start = float(PAD)
    if card.org_name:
        c.use(card.org_name, 28, bold=True)
        name_w = WIDTH - PAD - name_start
        name = _fit(c, card.org_name, name_w, 1)[0]
        c.set_text_color(*_rgb(card.colors.muted))
        c.set_xy(PAD if rtl else name_start, y)
        c.cell(name_w, head_h, name, align=Align.R if rtl else Align.L)

    # Title and description, centred between the header and the address: the title at the
    # largest size where it fits in three lines with the description (up to two lines) below.
    top = y + head_h + 32
    bottom = HEIGHT - BAND - PAD - 56  # the address line sits below
    title = card.title.strip() or "Untitled form"
    desc = (card.description or "").strip()
    title_rtl = is_thaana(title)
    d_lines: list[str] = []
    d_line = 0.0
    if desc:
        d_size = c.use(desc, DESC_SIZE)
        d_line = d_size * (1.6 if is_thaana(desc) else 1.3)
        d_lines = _fit(c, desc, inner, DESC_LINES)
    gap = 20.0

    def block(lines: list[str], line_h: float, desc_n: int) -> float:
        return line_h * len(lines) + ((gap + d_line * desc_n) if desc_n else 0)

    chosen: tuple[int, list[str], int] | None = None
    for desc_n in sorted({len(d_lines), min(len(d_lines), 1), 0}, reverse=True):
        for base in TITLE_SIZES:
            size = c.use(title, base, bold=True)
            lines = c.lines(title, inner)
            line_h = size * (1.45 if title_rtl else 1.16)
            if len(lines) <= TITLE_LINES and block(lines, line_h, desc_n) <= bottom - top:
                chosen = (base, lines, desc_n)
                break
        if chosen is not None:
            break
    if chosen is None:
        c.use(title, TITLE_SIZES[-1], bold=True)
        chosen = (TITLE_SIZES[-1], _fit(c, title, inner, TITLE_LINES), 0)
    base, lines, desc_n = chosen
    t_size = c.use(title, base, bold=True)
    line_h = t_size * (1.45 if title_rtl else 1.16)
    y = top + max(0.0, (bottom - top - block(lines, line_h, desc_n)) / 2)
    y = _text_lines(c, lines, y=y, line_h=line_h, rtl=rtl, color=card.colors.text)
    if desc_n:
        c.use(desc, DESC_SIZE)
        shown = d_lines if desc_n == len(d_lines) else _fit(c, desc, inner, desc_n)
        _text_lines(c, shown, y=y + gap, line_h=d_line, rtl=rtl, color=card.colors.muted)

    # Address at the bottom start, always left to right.
    if card.address:
        c.set_font("latin", "", 26)
        c.set_fallback_fonts([], exact_match=False)
        c.set_text_shaping(True, direction="ltr")
        address = _fit(c, card.address, inner, 1)[0]
        c.set_text_color(*_rgb(card.colors.muted))
        c.set_xy(PAD, HEIGHT - BAND - PAD - 20)
        c.cell(inner, 30, address, align=Align.R if rtl else Align.L)
    return bytes(c.output())


def _rasterise(pdf: bytes) -> bytes:
    import pypdfium2 as pdfium

    with _pdfium_lock:
        doc = pdfium.PdfDocument(pdf)
        try:
            page = doc[0]
            bitmap = page.render(scale=1)
            img: Image.Image = bitmap.to_pil().convert("RGB")
        finally:
            doc.close()
    if img.size != (WIDTH, HEIGHT):
        img = img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render(card: Card) -> bytes:
    """The 1200x630 PNG for ``card`` (CPU-bound: call from a worker thread)."""
    return _rasterise(_draw(card))
