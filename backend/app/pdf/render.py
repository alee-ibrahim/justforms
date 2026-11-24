"""The respondent's PDF (DESIGN 9.5): the form title, the answers, signature images, the
reference number, the submission date, the approval record when there is one, and a footer
with a QR code to the public verify page. Rendered with fpdf2 and HarfBuzz text shaping
(uharfbuzz), so Thaana is shaped and laid out right to left, with no system libraries. The
result is then signed (``app.pdf.sign``).

Audit data (IP address, device, stroke and file hashes, the event chain) is never printed:
it stays in the studio, and the hashes that tie the file to its record travel in the signed
document metadata.

Fonts are bundled under ``fonts/`` (SIL OFL): Inter for Latin (a subset, ``app.pdf.faces``) and
Noto Sans Thaana for Thaana. MV Faseyha and Faruma are never bundled (licences unclear, DESIGN
16); an operator can supply a Thaana font for server rendering (``JUSTFORMS_THAANA_FONT_FILE``,
``app.pdf.faces``).

Fixed labels (reference, submitted, approval record, footer, "No answer", "Yes"/"No") are
English for every form. A form has no language (schemaVersion 2): every piece of form content
takes its direction and face from its own text (Thaana: right to left in the Thaana face, a
step larger; Latin: left to right in Inter; a mixed text such as "Name / ނަން" is laid out by
the Unicode bidi algorithm with its first strong character as the paragraph direction). Each
question, heading and title is aligned by its ``align`` (else ``settings.align``, else its
label's direction). The sheet chrome (reference and date line, approval record, footer, logo
and QR placement) follows the **sheet direction**, the direction of the form title: in a
right-to-left sheet those lines start at the right edge and each English label is one
left-to-right run placed against that edge, so its words and numbers keep their order.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import segno
from fpdf import FPDF
from fpdf.enums import Align, XPos, YPos

from app.answers import WORDS, answer_text
from app.logic.engine import evaluate
from app.logic.index import FormIndex
from app.pdf.faces import BUNDLED, LATIN_BOLD, LATIN_REGULAR, ThaanaFace
from app.schemas.direction import (
    BilingualParts,
    Direction,
    bilingual_parts,
    explicit_align,
    has_thaana,
    isolate_runs,
    resolve_align,
    text_direction,
    text_lines,
)
from app.schemas.form import (
    ContentElement,
    DateField,
    EmailField,
    FieldElement,
    FileField,
    Form,
    HiddenField,
    MultiChoiceField,
    NumberField,
    PhoneField,
    RepeaterElement,
    SectionElement,
    SignatureField,
    SingleChoiceField,
    TimeField,
    YesNoField,
)

INK = (24, 32, 58)
MUTED = (90, 99, 128)
# Question labels: a darker ink-muted than MUTED, so they never read as pale captions.
LABEL = (58, 66, 94)
# Thaana question labels are set this much larger again (on top of the 1.12 Thaana scale), so
# a label is never smaller than its answer (DESIGN-SYSTEM 4.2).
DV_LABEL_SCALE = 1.15
# Thaana reads small next to Latin at the same size (DESIGN 16): one step larger.
THAANA_SCALE = 1.12
# Picks the Thaana face in ``_font`` for a block of mixed cells (a repeater table).
THAANA_SAMPLE = "\u0780"
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
    # The Thaana face (``app.pdf.faces.thaana_face(settings, "pdf")``).
    thaana: ThaanaFace = BUNDLED


def add_thaana(pdf: FPDF, face: ThaanaFace) -> None:
    """Register ``face`` as the "thaana" family (regular and bold)."""
    rng = list(face.unicode_range) if face.unicode_range else None
    pdf.add_font("thaana", "", str(face.regular), unicode_range=rng)
    pdf.add_font("thaana", "B", str(face.bold), unicode_range=rng)


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{round(n / 1024)} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def reference(seq: int) -> str:
    return f"#{seq:04d}"


def isolate_text(text: str, direction: Direction) -> str:
    """Mixed text for the shaper: runs of the other script wrapped in LRI/RLI ... PDI (the PDF
    equivalent of ``<bdi>``), so brackets and punctuation next to them stay on the side of the
    surrounding text ("(PPY)" inside Dhivehi)."""
    return "".join(
        f"{LRI if d == 'ltr' else RLI}{chunk}{PDI}" if d else chunk
        for chunk, d in isolate_runs(text, direction)
    )


LRI, RLI, PDI = "\u2066", "\u2067", "\u2069"
# Space (mm) kept between the English and the Dhivehi part of a bilingual text on one row.
BILINGUAL_GAP = 6.0


class _Doc(FPDF):
    def __init__(self, src: PdfInput, total_pages: int | None) -> None:
        super().__init__(format="A4", unit="mm")
        self.src = src
        self.total_pages = total_pages
        # The sheet direction: the form title's. Places the chrome (see the module docs).
        self.sheet_dir: Direction = text_direction(src.form.settings.title or src.form_title)
        self.rtl = self.sheet_dir == "rtl"
        self.w_ = PDF_WORDS
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=MARGIN + FOOTER_HEIGHT)
        self.add_font("latin", "", str(LATIN_REGULAR))
        self.add_font("latin", "B", str(LATIN_BOLD))
        add_thaana(self, src.thaana)
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

    # The last line of a justified paragraph: fpdf2 always sets it left; a right-to-left
    # paragraph ends at its start edge (the right) instead.
    _justify_last: Align | None = None

    def _render_styled_text_line(self, text_line: Any, *args: Any, **kwargs: Any) -> Any:
        if self._justify_last is not None and text_line.align == Align.L:
            text_line = text_line._replace(align=self._justify_last)
        return super()._render_styled_text_line(text_line, *args, **kwargs)

    def _font(
        self,
        text: str | None,
        size: float,
        bold: bool = False,
        tabular: bool = False,
        *,
        direction: Direction | None = None,
    ) -> float:
        """Face and shaping for ``text`` (``None``: English system text, Latin left to right).
        Text with Thaana uses the Thaana face a step larger (Latin falls back to Inter), shaped
        in its own direction; a mixed text is split into runs by the bidi algorithm. Returns the
        size used. ``tabular``: figures of equal width (references, dates, page numbers)."""
        d = direction or (text_direction(text) if text is not None else "ltr")
        if text is not None and has_thaana(text) and d == "ltr":
            # English-dominant mixed text: the Latin face leads so its punctuation (", ?") keeps
            # Latin shapes; the Thaana words come from the fallback face.
            self.set_font("latin", "B" if bold else "", size)
            self.set_fallback_fonts(["thaana"], exact_match=False)
            self.set_text_shaping(True, direction="ltr")
            return size
        if text is not None and has_thaana(text):
            size *= THAANA_SCALE
            self.set_font("thaana", "B" if bold else "", size)
            self.set_fallback_fonts(["latin"], exact_match=False)
            pure = not any(ch.isascii() and ch.isalpha() for ch in text)
            self.set_text_shaping(
                True,
                direction=direction or text_direction(text),
                script="thaa" if pure else None,
                language="div" if pure else None,
            )
            return size
        self.set_font("latin", "B" if bold else "", size)
        self.set_fallback_fonts(["thaana"], exact_match=False)
        self.set_text_shaping(
            True,
            direction=direction or ("ltr" if text is None else text_direction(text)),
            features={"tnum": True} if tabular else None,
        )
        return size

    def start_align(self) -> str:
        """The sheet's start edge, for English system lines."""
        return "right" if self.rtl else "left"

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
        align: str | None = None,
        per_line: bool = False,
        split: bool = False,
    ) -> float:
        """A paragraph. ``content`` text is shaped in its own direction and face (``_font``);
        ``latin`` (Latin-only answers, English labels) is shaped left to right. ``align`` is
        ``left``/``center``/``right``; by default content follows its own direction and
        English system text the sheet's start edge. Returns the height it takes, gap
        included; ``dry_run`` only measures.

        Multi-line ``content`` text is laid out line by line: each line break-separated
        paragraph is shaped in its own direction (an English paragraph, then Dhivehi ones),
        aligned by ``align`` when ``per_line`` is false, else each to its own direction.

        ``split`` (auto alignment): a bilingual one-line text ("Full name: ފުރިހަމަ ނަން",
        ``bilingual_parts``) is laid out as one row, the English part at the left and the
        Dhivehi part at the right; two lines (English left, Dhivehi right) when they don't fit."""
        if not text:
            return 0.0
        parts = bilingual_parts(text) if split and content and not latin else None
        if parts is not None:
            return self._bilingual(
                parts, size=size, bold=bold, color=color, gap=gap, line=line, dry_run=dry_run
            )
        if content and not latin and ("\n" in text or "\r" in text):
            total = 0.0
            lines = text_lines(text, text_direction(text, self.sheet_dir))
            for i, para in enumerate(lines):
                last = i == len(lines) - 1
                own = "right" if para["dir"] == "rtl" else "left"
                if not para["text"].strip():
                    blank = size * 0.5
                    if dry_run:
                        total += blank
                    else:
                        self.ln(blank)
                    continue
                total += self.text_block(
                    para["text"],
                    size=size,
                    bold=bold,
                    color=color,
                    gap=gap if last else 0.0,
                    line=line,
                    dry_run=dry_run,
                    align=own if per_line or align is None else align,
                    split=split,
                )
            if not lines[-1]["text"].strip():
                total += gap
                if not dry_run:
                    self.ln(gap)
            return total if dry_run else 0.0
        content = content and not latin
        direction: Direction = text_direction(text, self.sheet_dir) if content else "ltr"
        thaana = content and has_thaana(text)
        self._font(text if content else None, size, bold, direction=direction)
        if content and has_thaana(text) and any(ch.isascii() and ch.isalpha() for ch in text):
            text = isolate_text(text, direction)
        self.set_text_color(*color)
        if align is None:
            align = ("right" if direction == "rtl" else "left") if content else self.start_align()
        justify = align == "justify"
        if justify:
            # Justified in its own direction: wrapped lines stretched, the last line (and a
            # paragraph that fits on one line) at the start edge, never stretched.
            align = "right" if direction == "rtl" else "left"
        cell_align = {"left": Align.L, "center": Align.C, "right": Align.R}[align]
        line_h = line or size * (0.62 if thaana else 0.5)
        if dry_run:
            height = self.multi_cell(
                0, line_h, text, align=cell_align, dry_run=True, output="HEIGHT"
            )
            assert isinstance(height, float | int)
            return float(height) + gap
        if justify:
            self._justify_last = cell_align
            try:
                self.multi_cell(0, line_h, text, align=Align.J, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            finally:
                self._justify_last = None
            self.ln(gap)
            return 0.0
        self.multi_cell(0, line_h, text, align=cell_align, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(gap)
        return 0.0

    def _bilingual(
        self,
        parts: BilingualParts,
        *,
        size: float,
        bold: bool,
        color: tuple[int, int, int],
        gap: float,
        line: float | None,
        dry_run: bool,
    ) -> float:
        """The two parts of a bilingual text in one row: English left, Dhivehi right; stacked
        (the English line at the left, then the Dhivehi line at the right) when they don't
        fit side by side."""
        ltr, rtl = parts["ltr"], parts["rtl"]
        mixed = any(c.isascii() and c.isalpha() for c in rtl)
        shown_rtl = isolate_text(rtl, "rtl") if mixed else rtl
        self._font(rtl, size, bold, direction="rtl")
        rtl_w = self.get_string_width(shown_rtl)
        self._font(ltr, size, bold, direction="ltr")
        ltr_w = self.get_string_width(ltr)
        if ltr_w + rtl_w + BILINGUAL_GAP > self.w - self.l_margin - self.r_margin:
            first = self.text_block(
                ltr,
                size=size,
                bold=bold,
                color=color,
                gap=0.0,
                line=line,
                dry_run=dry_run,
                align="left",
            )
            second = self.text_block(
                rtl,
                size=size,
                bold=bold,
                color=color,
                gap=gap,
                line=line,
                dry_run=dry_run,
                align="right",
            )
            return first + second
        line_h = line or size * 0.62
        if dry_run:
            return line_h + gap
        if self.get_y() + line_h > self.page_break_trigger:
            self.add_page()
        y = self.get_y()
        self.set_text_color(*color)
        self.set_xy(self.l_margin, y)
        self.cell(ltr_w, line_h, ltr, align=Align.L)
        self._font(rtl, size, bold, direction="rtl")
        self.set_xy(self.w - self.r_margin - rtl_w, y)
        self.cell(rtl_w, line_h, shown_rtl, align=Align.R)
        self.set_xy(self.l_margin, y + line_h)
        self.ln(gap)
        return 0.0

    def label(
        self,
        text: str,
        *,
        gap: float = 0.5,
        dry_run: bool = False,
        align: str | None = None,
        split: bool = False,
    ) -> float:
        """A question label: ink-muted, and a Thaana label as large as its answer."""
        size = 9 * (DV_LABEL_SCALE if has_thaana(text) else 1)
        return self.text_block(
            text, size=size, color=LABEL, gap=gap, dry_run=dry_run, align=align, split=split
        )

    def split_for(self, el: Any) -> bool:
        """True when an element's text aligns ``auto`` (its own ``align``, then the form
        default), so a bilingual text is split into its English and Dhivehi parts."""
        return explicit_align(getattr(el, "align", None), self.src.form.settings.align) is None

    def field_align(self, el: Any, text: str | None) -> str:
        """Alignment of an element's lines: its ``align``, else the form's, else the
        direction of ``text`` (its label or title)."""
        return resolve_align(
            getattr(el, "align", None),
            self.src.form.settings.align,
            text_direction(text, self.sheet_dir),
        )

    def runs(
        self,
        parts: list[tuple[str, bool]],
        *,
        size: float,
        color: tuple[int, int, int] = INK,
        height: float = 5,
        start: float | None = None,
        tabular: bool = False,
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
            self._font(None if latin else text, size, tabular=tabular and latin)
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
        self.runs([(line, True)], size=7.5, color=MUTED, height=4, start=text_edge, tabular=True)


def _local(dt: datetime | None, tz: ZoneInfo, seconds: bool = False) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(tz).strftime("%d %b %Y %H:%M:%S" if seconds else "%d %b %Y %H:%M")


def _answer(doc: _Doc, fld: FieldElement, value: Any, src: PdfInput) -> None:
    no_answer = WORDS["no_answer"]
    align = doc.field_align(fld, fld.label)
    split = doc.split_for(fld)
    if isinstance(fld, SignatureField) and fld.id in src.signatures:
        _signature(doc, fld.label, src.signatures[fld.id], align, split)
        return
    doc.label(fld.label, align=align, split=split)
    if isinstance(fld, FileField):
        refs = value if isinstance(value, list) else []
        shown = 0
        for ref in refs:
            info = src.files.get(str(ref.get("fileId"))) if isinstance(ref, dict) else None
            if info is None:
                continue
            doc.text_block(f"{info.name}  ({_size(info.size)})", gap=0.5, align=align)
            shown += 1
        if not shown:
            doc.text_block(no_answer, latin=True, color=MUTED, gap=3, align=align)
        else:
            doc.ln(2.5)
        return
    if isinstance(fld, SignatureField):
        doc.text_block(no_answer, latin=True, color=MUTED, gap=3, align=align)
        return
    # Chosen options one per line, so a bilingual option is split like on the form.
    choice = isinstance(fld, SingleChoiceField | MultiChoiceField)
    if split and isinstance(fld, MultiChoiceField):
        text = answer_text(fld, value, display=True, list_sep=chr(10))
    else:
        text = answer_text(fld, value, display=True)
    if not text:
        doc.text_block(no_answer, latin=True, color=MUTED, gap=3, align=align)
    else:
        explicit = explicit_align(getattr(fld, "align", None), src.form.settings.align)
        doc.text_block(
            text,
            latin=isinstance(fld, LATIN_ONLY),
            gap=3,
            align="justify" if explicit == "justify" else align,
            per_line=explicit is None,
            split=split and choice,
        )


PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")


def _png_size(png: bytes) -> tuple[int, int] | None:
    """(width, height) in pixels from a PNG's IHDR chunk."""
    if png[:8] != PNG_MAGIC or len(png) < 24:
        return None
    w, h = struct.unpack(">II", png[16:24])
    return (w, h) if w and h else None


SIGNATURE_WIDTH = 70.0


def _signature(doc: _Doc, label: str, sig: SignatureInfo, align: str, split: bool = False) -> None:
    """The label, the statement the signer saw, the server-rendered image and its baseline,
    kept together: when they don't fit, the page breaks before the label, so the image is
    never separated from its statement."""
    width = SIGNATURE_WIDTH
    px = _png_size(sig.png)
    image_h = width * px[1] / px[0] if px else 40.0
    needed = doc.label(label, dry_run=True, align=align, split=split) + image_h + 5
    if sig.attestation:
        needed += doc.text_block(sig.attestation, size=10, gap=1, dry_run=True, align=align)
    top_of_page = doc.get_y() <= doc.t_margin + 1
    if not top_of_page and doc.get_y() + needed > doc.page_break_trigger:
        doc.add_page()
    doc.label(label, align=align, split=split)
    if sig.attestation:
        doc.text_block(sig.attestation, size=10, gap=1, align=align)
    if doc.get_y() + image_h > doc.page_break_trigger:
        doc.add_page()  # a statement longer than a page: the image still follows it
    if align == "right":
        x = doc.w - doc.r_margin - width
    elif align == "center":
        x = (doc.w - width) / 2
    else:
        x = doc.l_margin
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
                doc.text_block(
                    el.text,
                    size=12,
                    bold=not has_thaana(el.text),
                    gap=2,
                    align=doc.field_align(el, el.text),
                    split=doc.split_for(el),
                )
            continue
        if isinstance(el, SectionElement):
            if el.title:
                doc.text_block(
                    el.title,
                    size=11.5,
                    bold=not has_thaana(el.title),
                    gap=2,
                    align=doc.field_align(el, el.title),
                    split=doc.split_for(el),
                )
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
    align = doc.field_align(rep, rep.label)
    doc.label(rep.label, gap=1, align=align, split=doc.split_for(rep))
    rows = src.data.get(rep.id)
    rows = rows if isinstance(rows, list) else []
    fields = [f for f in leaf_fields(rep.elements) if not isinstance(f, HiddenField)]
    if not rows or not fields:
        doc.text_block(WORDS["no_answer"], latin=True, color=MUTED, gap=3, align=align)
        return
    headings = ["#", *(f.label for f in fields)]
    body = [
        [str(i + 1), *(answer_text(f, row.get(f.id), display=True) for f in fields)]
        for i, row in enumerate(rows)
        if isinstance(row, dict)
    ]
    # Columns run in the repeater label's direction; every cell's paragraph direction is
    # detected from its own text (shaping direction left unset).
    rtl = text_direction(rep.label, doc.sheet_dir) == "rtl"
    thaana = any(has_thaana(c) for c in [*headings, *(c for r in body for c in r)])
    doc._font(THAANA_SAMPLE if thaana else "", 8.5)
    doc.set_text_shaping(True, direction=None)
    doc.set_text_color(*INK)
    doc.set_draw_color(*HAIRLINE)
    if rtl:
        headings = list(reversed(headings))
        body = [list(reversed(r)) for r in body]
    widths = [8] + [40] * len(fields)
    if rtl:
        widths = list(reversed(widths))
    with doc.table(
        col_widths=widths,
        text_align=align.upper(),
        line_height=6 if thaana else 5,
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
    title = form.settings.title or src.form_title
    title_align = resolve_align(
        form.settings.title_align, form.settings.align, text_direction(title, doc.sheet_dir)
    )
    doc.text_block(
        title,
        size=17,
        bold=not has_thaana(title),
        gap=2,
        align=title_align,
        split=explicit_align(form.settings.title_align, form.settings.align) is None,
    )
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
        tabular=True,
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
            doc.text_block(
                page.title,
                size=13,
                bold=not has_thaana(page.title),
                gap=3,
                color=src.accent or INK,
                align=doc.field_align(page, page.title),
                split=doc.split_for(page),
            )
        _elements(doc, page.elements, visible, src)
        doc.ln(2)
    _approvals(doc, src)
    return doc


def render_pdf(src: PdfInput) -> bytes:
    # Two passes: the first counts the pages so the footer can say "page 1 of 3" without
    # fpdf2's {nb} alias (which the bidi algorithm would reorder in Dhivehi).
    pages = _render(src, None).pages_count
    return bytes(_render(src, pages).output())
