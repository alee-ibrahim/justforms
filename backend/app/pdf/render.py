"""The respondent's PDF (DESIGN 9.5): the form title, the answers, signature images, the
reference number, the submission date, the approval record when there is one, and a footer
with a QR code to the public verify page. Rendered with fpdf2 and HarfBuzz text shaping
(uharfbuzz), so Thaana is shaped and laid out right to left, with no system libraries. The
result is then signed (``app.pdf.sign``).

Audit data (IP address, device, stroke and file hashes, the event chain) is never printed:
it stays in the studio, and the hashes that tie the file to its record travel in the signed
document metadata.

Fonts are bundled under ``fonts/`` (SIL OFL): Atkinson Hyperlegible Next for Latin and
Noto Sans Thaana for Thaana. Faruma is never bundled (licence unclear, DESIGN 16).

Fixed labels (reference, submitted, approval record, footer, "No answer", "Yes"/"No") are
English for every form. The page follows the form's direction: in a Dhivehi form every line
starts at the right edge, form content is shaped right to left, and each English label is one
left-to-right run placed against that edge, so its words and numbers keep their order.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import segno
from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos

from app.answers import WORDS, answer_text
from app.logic.engine import evaluate
from app.logic.index import FormIndex
from app.schemas.form import (
    ContentElement,
    DateField,
    EmailField,
    FieldElement,
    FileField,
    Form,
    HiddenField,
    NumberField,
    PhoneField,
    RepeaterElement,
    SectionElement,
    SignatureField,
    TimeField,
    YesNoField,
)

FONTS = Path(__file__).parent / "fonts"
INK = (24, 32, 58)
MUTED = (90, 99, 128)
# Question labels: a darker ink-muted than MUTED, so they never read as pale captions.
LABEL = (58, 66, 94)
# Thaana question labels are set this much larger again (on top of the 1.12 Thaana scale), so
# a label is never smaller than its answer (DESIGN-SYSTEM 4.2).
DV_LABEL_SCALE = 1.15
HAIRLINE = (220, 224, 234)
# Answers printed left to right: Latin data, and Yes / No (English system words).
LATIN_ONLY = (EmailField, PhoneField, NumberField, DateField, TimeField, YesNoField)
MARGIN = 18
# Space kept free at the bottom of each page for the footer (QR code and two lines).
FOOTER_HEIGHT = 22
QR_SIZE = 16

# Fixed words printed on the respondent's PDF: English for every form.
PDF_WORDS: dict[str, str] = {
    "reference": "Reference",
    "submitted": "Submitted",
    "signed_verify": "Digitally signed. Verify at",
    "page": "page",
    "of": "of",
    "approval": "Approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "stopped": "Stopped",
}


@dataclass
class SignatureInfo:
    field_id: str
    png: bytes
    attestation: str


@dataclass
class FileInfo:
    name: str
    size: int


@dataclass
class ApprovalLine:
    """One decided (or stopped) approval step for the printed record."""

    step: int
    name: str
    outcome: str  # approved | rejected | stopped
    approver_name: str | None
    approver_email: str | None
    decided_at: datetime | None


@dataclass
class PdfInput:
    org_name: str
    form_title: str
    form: Form
    version: int
    schema_hash: str
    submission_id: str
    seq: int
    submitted_at: datetime
    data: dict[str, Any]
    content_hash: str
    chain_head: str | None
    tz: ZoneInfo
    verify_url: str
    files: dict[str, FileInfo] = field(default_factory=dict)
    signatures: dict[str, SignatureInfo] = field(default_factory=dict)
    approvals: list[ApprovalLine] = field(default_factory=list)
    # The organisation's logo (PNG or sanitised SVG) for the header, or None (DESIGN 18.2).
    logo: bytes | None = None
    logo_size: tuple[int, int] | None = None  # pixels (PNG) or viewBox units (SVG)
    # The theme's logo size and placement (start/end follow the form's direction; "hidden"
    # leaves the name only, as without a logo).
    logo_scale: Literal["s", "m", "l"] = "m"
    logo_placement: Literal["start", "center", "end", "hidden"] = "start"
    # Print the organisation's name in the header (only when it is branded).
    show_brand: bool = False
    # The form theme's primary colour (title rule and page headings), None for ink.
    accent: tuple[int, int, int] | None = None


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def reference(seq: int) -> str:
    return f"#{seq:04d}"


class _Doc(FPDF):
    def __init__(self, src: PdfInput, total_pages: int | None) -> None:
        super().__init__(format="A4", unit="mm")
        self.src = src
        self.total_pages = total_pages
        self.rtl = src.form.settings.language == "dv"
        self.w_ = PDF_WORDS
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=MARGIN + FOOTER_HEIGHT)
        self.add_font("latin", "", str(FONTS / "AtkinsonHyperlegibleNext-Regular.ttf"))
        self.add_font("latin", "B", str(FONTS / "AtkinsonHyperlegibleNext-Bold.ttf"))
        self.add_font("thaana", "", str(FONTS / "NotoSansThaana-Regular.ttf"))
        self.add_font("thaana", "B", str(FONTS / "NotoSansThaana-Bold.ttf"))
        self.set_title(f"{src.form_title} {reference(src.seq)}")
        self.set_author(src.org_name or "JustForms")
        self.set_creator("JustForms")
        self.set_subject(f"Submission {reference(src.seq)}")
        # Read by `justforms verify-pdf` and the verify page to find and check the record.
        # Covered by the signature like every other byte, and never printed.
        self.set_keywords(
            f"justforms-submission:{src.submission_id} justforms-content-hash:{src.content_hash}"
            f" justforms-version-hash:{src.schema_hash} justforms-log-head:{src.chain_head or '-'}"
        )
        self.qr = segno.make(src.verify_url, error="m")

    # -- text helpers -------------------------------------------------------------------

    def _font(self, content: bool, size: float, bold: bool = False) -> None:
        thaana = content and self.rtl
        self.set_font("thaana" if thaana else "latin", "B" if bold else "", size)
        self.set_fallback_fonts(["latin" if thaana else "thaana"], exact_match=False)
        if thaana:
            self.set_text_shaping(True, direction="rtl", script="thaa", language="div")
        else:
            self.set_text_shaping(True, direction="ltr")

    def text_block(
        self,
        text: str,
        *,
        content: bool = True,
        latin: bool = False,
        size: float = 10.5,
        bold: bool = False,
        color: tuple[int, int, int] = INK,
        gap: float = 1.5,
        line: float | None = None,
        dry_run: bool = False,
    ) -> float:
        """A paragraph at the page's start edge (right in a Dhivehi form). ``content`` text is
        shaped in the form's language and direction; ``latin`` (Latin-only answers, English
        labels) is shaped left to right. Returns the height it takes, gap included;
        ``dry_run`` only measures."""
        if not text:
            return 0.0
        self._font(content and not latin, size * (1.12 if content and self.rtl else 1), bold)
        self.set_text_color(*color)
        align = Align.R if self.rtl else Align.L
        line_h = line or size * (0.62 if content and self.rtl else 0.5)
        if dry_run:
            height = self.multi_cell(0, line_h, text, align=align, dry_run=True, output="HEIGHT")
            assert isinstance(height, float | int)
            return float(height) + gap
        self.multi_cell(0, line_h, text, align=align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(gap)
        return 0.0

    def label(self, text: str, *, gap: float = 0.5, dry_run: bool = False) -> float:
        """A question label: ink-muted, and in a Dhivehi form as large as its answer."""
        size = 9 * (DV_LABEL_SCALE if self.rtl else 1)
        return self.text_block(text, size=size, color=LABEL, gap=gap, dry_run=dry_run)

    def runs(
        self,
        parts: list[tuple[str, bool]],
        *,
        size: float,
        color: tuple[int, int, int] = INK,
        height: float = 5,
        start: float | None = None,
    ) -> None:
        """One line of mixed text as separate runs: ``(text, latin)`` in reading order.

        Each run is shaped on its own (Thaana right to left, Latin left to right) and placed
        from the start edge (``start``, default the margin), so a reference like ``#0042`` or
        a URL keeps its order inside Dhivehi text instead of being reordered by the bidi
        algorithm. An empty run adds a wider gap."""
        # Runs are placed with absolute positions: break the page before the line, never
        # between its runs (the footer draws below the trigger and never breaks).
        if not self.in_footer and self.get_y() + height > self.page_break_trigger:
            self.add_page()
        y = self.get_y()
        x = start if start is not None else (self.w - self.r_margin if self.rtl else self.l_margin)
        self.set_text_color(*color)
        for text, latin in parts:
            self._font(not latin, size * (1.12 if self.rtl and not latin else 1))
            gap = self.get_string_width(" ")
            if not text:
                x += -2 * gap if self.rtl else 2 * gap
                continue
            width = self.get_string_width(text)
            if self.rtl:
                x -= width
                self.set_xy(x, y)
                self.cell(width, height, text)
                x -= gap
            else:
                self.set_xy(x, y)
                self.cell(width, height, text)
                x += width + gap
        self.set_xy(self.l_margin, y + height)

    def rule(self, color: tuple[int, int, int] | None = None) -> None:
        self.set_draw_color(*(color or HAIRLINE))
        if color:
            self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)

    def _qr(self, x: float, y: float) -> None:
        matrix = list(self.qr.matrix)
        n = len(matrix)
        quiet = 2
        cell = QR_SIZE / (n + 2 * quiet)
        self.set_fill_color(*INK)
        for r, row in enumerate(matrix):
            c = 0
            while c < n:
                if row[c]:
                    start = c
                    while c < n and row[c]:
                        c += 1
                    self.rect(
                        x + (quiet + start) * cell,
                        y + (quiet + r) * cell,
                        (c - start) * cell,
                        cell,
                        style="F",
                    )
                else:
                    c += 1

    def footer(self) -> None:
        w = self.w_
        top = self.h - MARGIN - QR_SIZE + 2
        qr_x = self.w - self.r_margin - QR_SIZE if self.rtl else self.l_margin
        self._qr(qr_x, top)
        text_edge = qr_x - 3 if self.rtl else qr_x + QR_SIZE + 3
        self.set_y(top + 2.5)
        self.runs([(w["signed_verify"], True)], size=8, color=INK, height=4.2, start=text_edge)
        self.runs([(self.src.verify_url, True)], size=8, color=INK, height=4.2, start=text_edge)
        total = self.total_pages or self.page_no()
        name = self.src.org_name
        brand = f"{name}, " if self.src.show_brand and name and not _has_thaana(name) else ""
        line = (
            f"{brand}{w['reference']} {reference(self.src.seq)}, "
            f"{w['page']} {self.page_no()} {w['of']} {total}"
        )
        self.runs([(line, True)], size=7.5, color=MUTED, height=4, start=text_edge)


def _local(dt: datetime | None, tz: ZoneInfo, seconds: bool = False) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(tz).strftime("%d %b %Y %H:%M:%S" if seconds else "%d %b %Y %H:%M")


def _answer(doc: _Doc, fld: FieldElement, value: Any, src: PdfInput) -> None:
    lang = src.form.settings.language
    no_answer = WORDS["no_answer"]
    if isinstance(fld, SignatureField) and fld.id in src.signatures:
        _signature(doc, fld.label, src.signatures[fld.id])
        return
    doc.label(fld.label)
    if isinstance(fld, FileField):
        refs = value if isinstance(value, list) else []
        shown = 0
        for ref in refs:
            info = src.files.get(str(ref.get("fileId"))) if isinstance(ref, dict) else None
            if info is None:
                continue
            doc.text_block(f"{info.name}  ({_size(info.size)})", latin=True, gap=0.5)
            shown += 1
        if not shown:
            doc.text_block(no_answer, latin=True, color=MUTED, gap=3)
        else:
            doc.ln(2.5)
        return
    if isinstance(fld, SignatureField):
        doc.text_block(no_answer, latin=True, color=MUTED, gap=3)
        return
    text = answer_text(fld, value, lang, display=True)
    if not text:
        doc.text_block(no_answer, latin=True, color=MUTED, gap=3)
    else:
        doc.text_block(text, latin=isinstance(fld, LATIN_ONLY), gap=3)


PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")


def _png_size(png: bytes) -> tuple[int, int] | None:
    """(width, height) in pixels from a PNG's IHDR chunk."""
    if png[:8] != PNG_MAGIC or len(png) < 24:
        return None
    w, h = struct.unpack(">II", png[16:24])
    return (w, h) if w and h else None


SIGNATURE_WIDTH = 70.0


def _signature(doc: _Doc, label: str, sig: SignatureInfo) -> None:
    """The label, the statement the signer saw, the server-rendered image and its baseline,
    kept together: when they don't fit, the page breaks before the label, so the image is
    never separated from its statement."""
    width = SIGNATURE_WIDTH
    px = _png_size(sig.png)
    image_h = width * px[1] / px[0] if px else 40.0
    needed = doc.label(label, dry_run=True) + image_h + 5
    if sig.attestation:
        needed += doc.text_block(sig.attestation, size=10, gap=1, dry_run=True)
    top_of_page = doc.get_y() <= doc.t_margin + 1
    if not top_of_page and doc.get_y() + needed > doc.page_break_trigger:
        doc.add_page()
    doc.label(label)
    if sig.attestation:
        doc.text_block(sig.attestation, size=10, gap=1)
    if doc.get_y() + image_h > doc.page_break_trigger:
        doc.add_page()  # a statement longer than a page: the image still follows it
    x = doc.w - doc.r_margin - width if doc.rtl else doc.l_margin
    top = doc.get_y()
    info = doc.image(io.BytesIO(sig.png), x=x, y=top, w=width)
    bottom = top + float(info.rendered_height)
    doc.set_draw_color(*HAIRLINE)
    doc.line(x, bottom, x + width, bottom)
    doc.set_y(bottom + 5)


def _elements(doc: _Doc, elements: list[Any], visible: set[str], src: PdfInput) -> None:
    for el in elements:
        if getattr(el, "id", None) not in visible:
            continue
        if isinstance(el, ContentElement):
            if el.content_type == "heading" and el.text:
                doc.text_block(el.text, size=12, bold=not doc.rtl, gap=2)
            continue
        if isinstance(el, SectionElement):
            if el.title:
                doc.text_block(el.title, size=11.5, bold=not doc.rtl, gap=2)
            _elements(doc, el.elements, visible, src)
            continue
        if isinstance(el, RepeaterElement):
            _repeater(doc, el, src)
            continue
        if isinstance(el, HiddenField):
            continue
        _answer(doc, el, src.data.get(el.id), src)


def leaf_fields(elements: list[Any]) -> list[FieldElement]:
    """Fields among ``elements``, looking inside sections, in document order."""
    out: list[FieldElement] = []
    for el in elements:
        if isinstance(el, SectionElement):
            out.extend(leaf_fields(el.elements))
        elif getattr(el, "kind", None) == "field":
            out.append(el)
    return out


def _repeater(doc: _Doc, rep: RepeaterElement, src: PdfInput) -> None:
    lang = src.form.settings.language
    doc.label(rep.label, gap=1)
    rows = src.data.get(rep.id)
    rows = rows if isinstance(rows, list) else []
    fields = [f for f in leaf_fields(rep.elements) if not isinstance(f, HiddenField)]
    if not rows or not fields:
        doc.text_block(WORDS["no_answer"], latin=True, color=MUTED, gap=3)
        return
    doc._font(True, 8.5 * (1.12 if doc.rtl else 1))
    doc.set_text_color(*INK)
    doc.set_draw_color(*HAIRLINE)
    headings = ["#", *(f.label for f in fields)]
    body = [
        [str(i + 1), *(answer_text(f, row.get(f.id), lang, display=True) for f in fields)]
        for i, row in enumerate(rows)
        if isinstance(row, dict)
    ]
    if doc.rtl:
        headings = list(reversed(headings))
        body = [list(reversed(r)) for r in body]
    widths = [8] + [40] * len(fields)
    if doc.rtl:
        widths = list(reversed(widths))
    with doc.table(
        col_widths=widths,
        text_align="RIGHT" if doc.rtl else "LEFT",
        line_height=6 if doc.rtl else 5,
        first_row_as_headings=True,
        borders_layout="HORIZONTAL_LINES",
        padding=1.2,
    ) as table:
        for cells in [headings, *body]:
            r = table.row()
            for c in cells:
                r.cell(c)
    doc.ln(4)


def _approvals(doc: _Doc, src: PdfInput) -> None:
    if not src.approvals:
        return
    w = doc.w_
    if doc.get_y() + 12 + 14 * len(src.approvals) > doc.h - doc.b_margin:
        doc.add_page()
    doc.ln(2)
    doc.rule()
    doc.text_block(w["approval"], latin=True, size=12, bold=True, gap=2)
    for line in src.approvals:
        if _has_thaana(line.name):
            step = [(str(line.step) if doc.rtl else f"{line.step}.", True), (line.name, False)]
        else:
            step = [(f"{line.step}. {line.name}", True)]  # a Latin step name reads as one run
        doc.runs(step, size=10.5, height=6.5 if doc.rtl else 5.5)
        outcome = w.get(line.outcome, line.outcome)
        when = _local(line.decided_at, src.tz) if line.decided_at else None
        name = line.approver_name or None
        if name and _has_thaana(name):
            # "Approved  {name}  email  date" with the Thaana name as its own run; in RTL the
            # English facts are one left-to-right run at the right edge, then the name.
            rest = "  ".join(x for x in (line.approver_email, when) if x)
            who: list[tuple[str, bool]] = (
                [("  ".join(x for x in (outcome, rest) if x), True), (name, False)]
                if doc.rtl
                else [(outcome, True), (name, False), *([(rest, True)] if rest else [])]
            )
        else:
            who = [("  ".join(x for x in (outcome, name, line.approver_email, when) if x), True)]
        doc.runs(who, size=8.5, color=MUTED, height=5.5 if doc.rtl else 4.5)
        doc.ln(2)


# Logo height and widest box (mm) per theme logo size; "m" is the long-standing look.
LOGO_HEIGHTS = {"s": 7.0, "m": 9.0, "l": 13.0}
LOGO_MAX_WIDTHS = {"s": 48.0, "m": 60.0, "l": 80.0}


def logo_box(
    src: PdfInput, page_w: float, l_margin: float, r_margin: float, rtl: bool
) -> tuple[float, float, float]:
    """(x, width, height) in mm of the header logo for the theme's size and placement."""
    w_px, h_px = src.logo_size or (1, 1)
    max_h, max_w = LOGO_HEIGHTS[src.logo_scale], LOGO_MAX_WIDTHS[src.logo_scale]
    width = min(max_w, max_h * w_px / max(1, h_px))
    height = width * h_px / max(1, w_px)
    left, right = l_margin, page_w - r_margin - width
    if src.logo_placement == "center":
        x = (page_w - width) / 2
    elif src.logo_placement == "end":
        x = left if rtl else right
    else:
        x = right if rtl else left
    return x, width, height


def _brand_header(doc: _Doc, src: PdfInput) -> None:
    """The logo (the form's own or the organisation's) above the title, placed and sized by
    the form theme; or the organisation's name at the start edge when it is branded."""
    if src.logo and src.logo_placement != "hidden":
        try:
            x, width, height = logo_box(src, doc.w, doc.l_margin, doc.r_margin, doc.rtl)
            doc.image(io.BytesIO(src.logo), x=x, y=doc.get_y(), w=width, h=height)
            doc.ln(height + 3)
            return
        except Exception:
            pass
    if not src.show_brand:
        return
    doc.runs([(src.org_name, not _has_thaana(src.org_name))], size=9, color=MUTED, height=5)
    doc.ln(2)


def _has_thaana(text: str) -> bool:
    return any("ހ" <= ch <= "޿" for ch in text)


def _render(src: PdfInput, total_pages: int | None) -> _Doc:
    form = src.form
    ev = evaluate(form, src.data)
    visible = set(ev.visible)
    index = FormIndex.build(form)
    doc = _Doc(src, total_pages)
    w = doc.w_
    doc.add_page()
    _brand_header(doc, src)
    doc.text_block(form.settings.title or src.form_title, size=17, bold=not doc.rtl, gap=2)
    doc.runs(
        [
            (
                f"{w['reference']} {reference(src.seq)}    "
                f"{w['submitted']} {_local(src.submitted_at, src.tz)}",
                True,
            )
        ],
        size=9,
        color=MUTED,
        height=6 if doc.rtl else 5,
    )
    doc.ln(2)
    doc.rule(src.accent)
    for i, page in enumerate(form.pages):
        if page.id not in ev.path:
            continue
        ids = {e for e in visible if index.elements[e].page_index == i}
        if not ids:
            continue
        if page.title:
            doc.text_block(page.title, size=13, bold=not doc.rtl, gap=3, color=src.accent or INK)
        _elements(doc, page.elements, visible, src)
        doc.ln(2)
    _approvals(doc, src)
    return doc


def render_pdf(src: PdfInput) -> bytes:
    # Two passes: the first counts the pages so the footer can say "page 1 of 3" without
    # fpdf2's {nb} alias (which the bidi algorithm would reorder in Dhivehi).
    pages = _render(src, None).pages_count
    return bytes(_render(src, pages).output())
