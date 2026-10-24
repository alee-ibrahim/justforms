"""Jotform questions -> a JustForms form plus an import report (DESIGN 13.1, 13.2).

Deterministic: the same source always gives the same form. The result is validated by the
Pydantic schema (:class:`app.schemas.form.Form`) like any other draft.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.importers.jotform.model import (
    ConditionReport,
    ImportReport,
    JfCondition,
    JfQuestion,
    JfSource,
    ReportItem,
)
from app.importers.jotform.text import IdPool, ScriptCount, option_values, snake
from app.schemas.form import Form

# The "not imported" entry for the form's cover/header image; the import endpoints drop it
# again when the logo was downloaded and becomes the form's own logo.
COVER_IMAGE = "Cover image (add a logo in the form's theme)"

# Calling code -> ISO country, for the phone field's default country.
CALLING_CODES = {
    "1": "US",
    "20": "EG",
    "27": "ZA",
    "30": "GR",
    "31": "NL",
    "32": "BE",
    "33": "FR",
    "34": "ES",
    "39": "IT",
    "41": "CH",
    "44": "GB",
    "46": "SE",
    "47": "NO",
    "49": "DE",
    "60": "MY",
    "61": "AU",
    "62": "ID",
    "63": "PH",
    "64": "NZ",
    "65": "SG",
    "66": "TH",
    "81": "JP",
    "82": "KR",
    "86": "CN",
    "90": "TR",
    "91": "IN",
    "92": "PK",
    "94": "LK",
    "880": "BD",
    "960": "MV",
    "966": "SA",
    "971": "AE",
    "974": "QA",
    "977": "NP",
}

UNSUPPORTED = {
    "control_matrix": "Matrix (grid) questions are not supported. Rebuild them as separate "
    "questions.",
    "control_inline": "Fill-in-the-blank questions are not supported.",
    "control_widget": "Jotform widgets are not supported.",
    "control_appointment": "Appointment booking is not supported.",
    "control_image": "Images are not imported. Add the image again in the builder.",
    "control_mixed": "Mixed (multi-field) questions are not supported.",
    "control_products": "Payments and product lists are not supported.",
    "control_payment": "Payments and product lists are not supported.",
    "control_stripe": "Payments and product lists are not supported.",
    "control_square": "Payments and product lists are not supported.",
    "control_paypal": "Payments and product lists are not supported.",
    "control_paypalpro": "Payments and product lists are not supported.",
    "control_authnet": "Payments and product lists are not supported.",
    "control_braintree": "Payments and product lists are not supported.",
}

NAME_PARTS = {
    "prefix": "Prefix",
    "first": "First name",
    "middle": "Middle name",
    "last": "Last name",
    "suffix": "Suffix",
}
ADDRESS_PARTS = {
    "addr_line1": "Street address",
    "addr_line2": "Street address line 2",
    "city": "City",
    "state": "State / province",
    "postal": "Postal / zip code",
    "country": "Country",
}
YES = {"yes", "އާން"}
NO = {"no", "ނޫން"}
DEFAULT_SUBMIT = {"submit", "send", "ހުށަހަޅާ"}

OPS = {
    "equals": "eq",
    "notEquals": "neq",
    "isEmpty": "empty",
    "isFilled": "not_empty",
    "lessThan": "lt",
    "greaterThan": "gt",
    "contains": "contains",
    "notContains": "not_contains",
}


class ConversionError(ValueError):
    """The converted form did not validate (a bug in the importer, reported as such)."""


@dataclass
class Conversion:
    form: dict[str, Any]
    report: ImportReport
    language: str
    detected_language: str
    captcha: bool = False


@dataclass
class _Ctx:
    language: str
    max_upload_mb: int
    pool: IdPool = field(default_factory=IdPool)
    report: ImportReport = field(default_factory=ImportReport)
    pages: list[dict[str, Any]] = field(default_factory=list)
    section: dict[str, Any] | None = None
    title: str = ""
    description: str = ""
    submit_label: str | None = None
    captcha: bool = False
    # qid -> the element made for it (sections for name/address), and its page index.
    by_qid: dict[str, dict[str, Any]] = field(default_factory=dict)
    page_of: dict[str, int] = field(default_factory=dict)
    started: bool = False  # something visible was added

    @property
    def page(self) -> dict[str, Any]:
        return self.pages[-1]

    def add(self, el: dict[str, Any], qid: str | None = None) -> None:
        target = self.section["elements"] if self.section is not None else self.page["elements"]
        target.append(el)
        self.started = True
        if qid is not None:
            self.by_qid[qid] = el
            self.page_of[qid] = len(self.pages) - 1


def _label(q: JfQuestion) -> tuple[str, str | None]:
    """(label, description): an empty label borrows the sub-label (Jotform shows it under the
    box), otherwise the sub-label and hover text become the description."""
    sub = q.sublabels.get("main", "")
    parts = [p for p in (q.description,) if p]
    label = q.label
    if not label and sub:
        label = sub
    elif sub and sub != label:
        parts.insert(0, sub)
    return label, "\n\n".join(parts) or None


def _field(
    ctx: _Ctx, q: JfQuestion, type_: str, *, base: str | None = None, **extra: Any
) -> dict[str, Any]:
    label, description = _label(q)
    el: dict[str, Any] = {
        "kind": "field",
        "id": ctx.pool.take(base or q.name or label, type_),
        "type": type_,
        "label": label,
    }
    if description:
        el["description"] = description
    if q.placeholder and type_ in ("short_text", "long_text", "email", "number"):
        el["placeholder"] = q.placeholder
    if q.required:
        el["required"] = True
    if q.half:
        el["width"] = "half"
    el.update({k: v for k, v in extra.items() if v is not None})
    return el


def _item(
    q: JfQuestion, status: str, justforms: str | None, el: dict[str, Any] | None, *notes: str
) -> ReportItem:
    label = q.label or q.text or q.sublabels.get("main", "")
    return ReportItem(
        qid=q.qid,
        jotform_type=q.type,
        label=label[:200],
        status=status,  # type: ignore[arg-type]
        justforms_type=justforms,
        element_id=el["id"] if el else None,
        notes=list(notes),
    )


def _options(labels: list[str]) -> list[dict[str, str]]:
    return [
        {"value": v, "label": label} for v, label in zip(option_values(labels), labels, strict=True)
    ]


def _date_bound(value: Any) -> str | None:
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})[-/](\d{2})[-/](\d{2})$", text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _part_section(ctx: _Ctx, q: JfQuestion, defaults: dict[str, str]) -> dict[str, Any]:
    parts = [p for p in q.props.get("parts", []) if p in defaults] or (
        ["first", "last"] if defaults is NAME_PARTS else list(defaults)
    )
    base = snake(q.name or q.label) or ("name" if defaults is NAME_PARTS else "address")
    section_id = ctx.pool.take(base, "section")
    children = []
    for part in parts:
        label = q.sublabels.get(part) or defaults[part]
        options = q.props.get("part_options", {}).get(part)
        required = q.required and part not in ("prefix", "middle", "suffix", "addr_line2")
        child: dict[str, Any] = {
            "kind": "field",
            "id": ctx.pool.take(f"{section_id}_{part}", "short_text"),
            "label": label,
        }
        if options:
            child.update(
                {"type": "single_choice", "display": "dropdown", "options": _options(options)}
            )
        else:
            child["type"] = "short_text"
        if required:
            child["required"] = True
        if part in ("first", "last", "city", "state", "postal"):
            child["width"] = "half"
        children.append(child)
    section: dict[str, Any] = {"kind": "section", "id": section_id, "elements": children}
    if q.label:
        section["title"] = q.label
    if q.description:
        section["description"] = q.description
    return section


def _convert_question(ctx: _Ctx, q: JfQuestion) -> None:
    t = q.type
    props = q.props
    report = ctx.report.items
    notes: list[str] = []
    status = "imported"
    el: dict[str, Any]

    if t == "control_pagebreak":
        if ctx.page["elements"] or ctx.page.get("title"):
            ctx.pages.append({"id": f"page_{len(ctx.pages) + 1}", "elements": []})
        ctx.section = None
        report.append(_item(q, "imported", "page", None, "Starts a new page."))
        return

    if t == "control_head":
        is_first_page = len(ctx.pages) == 1
        if not ctx.started and is_first_page and not ctx.title and q.text:
            ctx.title, ctx.description = q.text, q.subtext
            report.append(_item(q, "imported", "form title", None, "Became the form title."))
            return
        if not is_first_page and not ctx.page["elements"] and "title" not in ctx.page and q.text:
            ctx.page["title"] = q.text
            if q.subtext:
                ctx.page["description"] = q.subtext
            report.append(_item(q, "imported", "page title", None, "Became the page title."))
            return
        el = {"kind": "content", "id": ctx.pool.numbered("heading"), "contentType": "heading"}
        el["text"] = q.text
        ctx.add(el, q.qid)
        if q.subtext:
            ctx.add(
                {
                    "kind": "content",
                    "id": ctx.pool.numbered("paragraph"),
                    "contentType": "paragraph",
                    "text": q.subtext,
                }
            )
            notes.append("The sub-heading became a text block under it.")
        report.append(_item(q, "imported", "heading", el, *notes))
        return

    if t == "control_collapse":
        section: dict[str, Any] = {"kind": "section", "id": ctx.pool.numbered("section")}
        if q.text:
            section["title"] = q.text
        section["elements"] = []
        ctx.section = None
        ctx.add(section, q.qid)
        ctx.section = section
        report.append(
            _item(
                q,
                "changed",
                "section",
                section,
                "Collapsible sections are shown open; the questions that follow sit inside it.",
            )
        )
        return

    if t == "control_text":
        if props.get("heading"):
            el = {
                "kind": "content",
                "id": ctx.pool.numbered("heading"),
                "contentType": "heading",
                "text": props["heading"],
            }
            ctx.add(el, q.qid)
            report.append(_item(q, "imported", "heading", el, "A one-line heading block."))
            return
        if not q.text:
            report.append(_item(q, "skipped", None, None, "The text block is empty."))
            return
        el = {
            "kind": "content",
            "id": ctx.pool.numbered("paragraph"),
            "contentType": "paragraph",
            "text": q.text,
        }
        ctx.add(el, q.qid)
        report.append(
            _item(
                q,
                "imported",
                "paragraph",
                el,
                "Formatting reduced to bold, italic, links and lists.",
            )
        )
        return

    if t == "control_divider":
        el = {"kind": "content", "id": ctx.pool.numbered("divider"), "contentType": "divider"}
        ctx.add(el, q.qid)
        report.append(_item(q, "imported", "divider", el))
        return

    if t == "control_button":
        text = q.text.strip()
        if text and text.lower() not in DEFAULT_SUBMIT:
            ctx.submit_label = text
            report.append(_item(q, "imported", "submit label", None, "Became the submit label."))
        else:
            report.append(_item(q, "imported", "submit button", None))
        return

    if t == "control_captcha":
        ctx.captcha = True
        report.append(
            _item(
                q,
                "changed",
                "CAPTCHA",
                None,
                "CAPTCHA is turned on (automatic) in the form's access settings.",
            )
        )
        return

    if t in UNSUPPORTED or not t.startswith("control_") or t not in _SUPPORTED:
        reason = UNSUPPORTED.get(t, "This Jotform question type is not supported.")
        ctx.started = True
        report.append(_item(q, "skipped", None, None, reason))
        return

    if t == "control_textbox":
        validations = set(props.get("validations", []))
        if "Email" in validations:
            el = _field(ctx, q, "email")
            notes.append("A text box with email validation became an email question.")
            status = "changed"
        elif "Numeric" in validations:
            el = _field(ctx, q, "number")
            notes.append("A text box with number validation became a number question.")
            status = "changed"
        else:
            el = _field(ctx, q, "short_text", maxLength=props.get("max_length"))
            dropped = sorted(validations - {"Email", "Numeric"})
            if dropped:
                notes.append(f"Validation not imported: {', '.join(dropped)}.")
                status = "changed"
        if props.get("mask"):
            notes.append("The input mask was not imported.")
            status = "changed"
    elif t == "control_textarea":
        rows = props.get("rows")
        el = _field(
            ctx,
            q,
            "long_text",
            maxLength=props.get("max_length"),
            rows=max(2, min(30, rows)) if rows else None,
        )
        if props.get("rich"):
            notes.append("Rich text answers become plain text.")
            status = "changed"
    elif t == "control_email":
        el = _field(ctx, q, "email")
        if props.get("confirm"):
            notes.append('The "confirm email" box was dropped.')
            status = "changed"
    elif t == "control_phone":
        code = props.get("country_code")
        country = CALLING_CODES.get(code) if code else None
        el = _field(ctx, q, "phone", defaultCountry=country)
        if code and not country:
            notes.append(f"Country code +{code} is not known; set the default country by hand.")
            status = "changed"
        if props.get("split"):
            notes.append("Separate area code and number boxes became one phone number.")
            status = "changed"
        if code:
            notes.append(f"The input mask was replaced by a phone number check (+{code}).")
    elif t in ("control_number", "control_spinner"):
        lo, hi, step = props.get("min"), props.get("max"), props.get("step")
        if lo is not None and hi is not None and lo > hi:
            lo, hi = None, None
            notes.append("The minimum was above the maximum; both were dropped.")
            status = "changed"
        integer = step is not None and float(step).is_integer() and step >= 1
        el = _field(
            ctx,
            q,
            "number",
            min=lo,
            max=hi,
            step=step if step and step > 0 else None,
            integer=True if integer else None,
        )
    elif t in ("control_datetime", "control_time") and (
        t == "control_datetime" or not props.get("time")
    ):
        cal = props.get("calendar") or {}
        min_date = max_date = None
        if cal.get("past") is False:
            min_date = "today"
        if cal.get("future") is False:
            max_date = "today"
        # "start"/"end" are the date range limits ("custom" is about single blocked days).
        min_date = _date_bound(cal.get("start")) or min_date
        max_date = _date_bound(cal.get("end")) or max_date
        if cal.get("custom") or cal.get("ranges"):
            notes.append("Blocked days and date ranges were not imported.")
            status = "changed"
        el = _field(ctx, q, "date", minDate=min_date, maxDate=max_date)
        if cal.get("days") and not all(cal["days"].values()):
            notes.append("Allowed weekdays were not imported.")
            status = "changed"
        if props.get("time"):
            label, _ = _label(q)
            time_label = f"{label} (time)" if ctx.language == "en" else label
            time_el: dict[str, Any] = {
                "kind": "field",
                "id": ctx.pool.take(f"{el['id']}_time", "time"),
                "type": "time",
                "label": time_label,
            }
            if q.required:
                time_el["required"] = True
            if q.half:
                time_el["width"] = "half"
            ctx.add(el, q.qid)
            ctx.add(time_el)
            notes.append(f"The time part became a separate time question ({time_el['id']}).")
            report.append(_item(q, "changed", "date", el, *notes))
            return
    elif t == "control_time":
        el = _field(ctx, q, "time")
    elif t in ("control_dropdown", "control_radio", "control_checkbox"):
        regular = [o.label for o in q.options if not o.other]
        has_other = any(o.other for o in q.options)
        if not regular:
            ctx.started = True
            report.append(_item(q, "skipped", None, None, "The question has no options."))
            return
        if len(set(regular)) != len(regular):
            regular = list(dict.fromkeys(regular))
            notes.append("Duplicate options were merged.")
            status = "changed"
        if len(regular) > 1000:
            regular = regular[:1000]
            notes.append("Only the first 1000 options were imported.")
            status = "changed"
        lowered = {o.lower() for o in regular}
        if (
            t == "control_radio"
            and not has_other
            and len(regular) == 2
            and lowered & YES
            and lowered & NO
        ):
            el = _field(ctx, q, "yes_no")
            notes.append("A Yes/No choice became a yes/no question.")
            status = "changed"
        elif t == "control_checkbox" or props.get("multiple"):
            lo, hi = props.get("min"), props.get("max")
            if lo is not None and hi is not None and lo > hi:
                lo = hi = None
            el = _field(
                ctx,
                q,
                "multi_choice",
                options=_options(regular),
                minSelected=lo,
                maxSelected=hi,
                allowOther=True if has_other else None,
            )
            if t == "control_dropdown":
                notes.append("A multiple-selection dropdown became checkboxes.")
                status = "changed"
        else:
            display = "dropdown" if t == "control_dropdown" else "radio"
            el = _field(
                ctx,
                q,
                "single_choice",
                options=_options(regular),
                display=display,
                allowOther=True if has_other else None,
            )
        if has_other:
            notes.append('The "Other" choice lets people type their own answer.')
            hint = str(props.get("other_hint") or "")
            if hint and hint.lower() != "other":
                el["description"] = "\n\n".join(p for p in (el.get("description"), hint) if p)
                notes.append('The text of the "Other" choice was added to the description.')
    elif t == "control_fileupload":
        accept = [f".{e}" for e in props.get("accept", []) if re.fullmatch(r"[a-z0-9]{1,10}", e)]
        max_mb = None
        if props.get("max_kb"):
            max_mb = max(1, math.ceil(props["max_kb"] / 1024))
            if max_mb > ctx.max_upload_mb:
                notes.append(
                    f"The {max_mb} MB size limit was lowered to this install's "
                    f"{ctx.max_upload_mb} MB."
                )
                status = "changed"
                max_mb = ctx.max_upload_mb
        limit = props.get("limit")
        max_files = max(1, min(50, limit)) if limit else (10 if props.get("multiple") else 1)
        if props.get("multiple") and not limit:
            notes.append("No file limit was set on Jotform; up to 10 files are allowed.")
            status = "changed"
        el = _field(ctx, q, "file", accept=accept or None, maxFiles=max_files, maxSizeMb=max_mb)
    elif t == "control_signature":
        el = _field(ctx, q, "signature")
        notes.append("Signatures are drawn on JustForms' pad and kept with an audit trail.")
    elif t in ("control_fullname", "control_address"):
        section = _part_section(ctx, q, NAME_PARTS if t == "control_fullname" else ADDRESS_PARTS)
        ctx.add(section, q.qid)
        notes.append("Became a section with one question per part.")
        report.append(_item(q, "changed", "section", section, *notes))
        return
    elif t in ("control_rating", "control_scale"):
        low, high = props.get("low", 1), props.get("high", 5)
        count = int(high - low + 1) if high >= low else 5
        if low != 1:
            notes.append(f"The scale started at {low:g}; JustForms ratings start at 1.")
            status = "changed"
        clamped = max(3, min(10, count))
        if clamped != count:
            notes.append(f"A {count}-point scale became {clamped} points.")
            status = "changed"
        el = _field(ctx, q, "rating", max=clamped)
    elif t in ("control_hidden", "control_autoincrement"):
        el = _field(ctx, q, "hidden")
        el.pop("required", None)
        if t == "control_autoincrement":
            notes.append("Auto-increment numbers are not generated.")
            status = "changed"
    else:  # pragma: no cover - _SUPPORTED lists only types handled above
        report.append(_item(q, "skipped", None, None, "Not supported."))
        return

    ctx.add(el, q.qid)
    report.append(_item(q, status, el["type"], el, *notes))


_SUPPORTED = frozenset(
    {
        "control_textbox",
        "control_textarea",
        "control_email",
        "control_phone",
        "control_number",
        "control_spinner",
        "control_datetime",
        "control_time",
        "control_dropdown",
        "control_radio",
        "control_checkbox",
        "control_fileupload",
        "control_signature",
        "control_fullname",
        "control_address",
        "control_rating",
        "control_scale",
        "control_hidden",
        "control_autoincrement",
    }
)


# -- conditions ----------------------------------------------------------------------------


def _iter_fields(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for el in elements:
        if el.get("kind") == "field":
            out.append(el)
        out.extend(_iter_fields(el.get("elements", [])))
    return out


def _find(doc: dict[str, Any], element_id: str) -> dict[str, Any] | None:
    stack: list[dict[str, Any]] = [e for p in doc["pages"] for e in p["elements"]]
    while stack:
        el = stack.pop()
        if el.get("id") == element_id:
            return el
        stack.extend(el.get("elements", []))
    return None


def _term(ctx: _Ctx, term: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
    """(condition, readable text, reason when not translatable)."""
    qid = str(term.get("field", ""))
    op = str(term.get("operator", ""))
    value = term.get("value")
    el = ctx.by_qid.get(qid)
    name = (el or {}).get("label") or (el or {}).get("title") or f"question {qid}"
    readable = f'"{name}" {op} "{value}"' if value not in (None, "") else f'"{name}" {op}'
    if el is None or el.get("kind") != "field":
        return None, readable, "It refers to a question that was not imported."
    if op not in OPS:
        return None, readable, f'The operator "{op}" is not supported.'
    dop = OPS[op]
    if dop in ("empty", "not_empty"):
        return {"field": el["id"], "op": dop}, readable, ""
    ftype = el["type"]
    text = str(value if value is not None else "")
    if ftype in ("single_choice", "multi_choice"):
        match = next((o["value"] for o in el["options"] if o["label"] == text), None)
        if match is None:
            match = next(
                (o["value"] for o in el["options"] if o["label"].lower() == text.lower()), None
            )
        if match is None:
            return None, readable, "It compares with an option the question does not have."
        if ftype == "multi_choice":
            if dop not in ("eq", "neq", "contains", "not_contains"):
                return None, readable, "That comparison does not apply to checkboxes."
            dop = "contains" if dop in ("eq", "contains") else "not_contains"
        elif dop not in ("eq", "neq"):
            return None, readable, "That comparison does not apply to a choice."
        return {"field": el["id"], "op": dop, "value": match}, readable, ""
    if ftype == "yes_no":
        if text.lower() not in YES | NO or dop not in ("eq", "neq"):
            return None, readable, "That comparison does not apply to a yes/no question."
        return {"field": el["id"], "op": dop, "value": text.lower() in YES}, readable, ""
    if ftype in ("number", "rating"):
        try:
            number = float(text)
        except ValueError:
            return None, readable, "It compares a number with text."
        return {"field": el["id"], "op": dop, "value": number}, readable, ""
    if ftype in ("date", "time", "file", "signature"):
        return None, readable, "Conditions on this question type are not supported."
    if dop in ("lt", "gt"):
        return None, readable, "Less/greater-than comparisons need a number question."
    return {"field": el["id"], "op": dop, "value": text}, readable, ""


def _condition(
    ctx: _Ctx, raw: dict[str, Any]
) -> tuple[dict[str, Any] | None, str, str, list[dict[str, Any]]]:
    """(JustForms condition, readable terms, reason, raw terms)."""
    terms = [t for t in raw.get("terms") or [] if isinstance(t, dict)]
    if not terms:
        return None, "", "It has no terms.", terms
    parts, texts = [], []
    for term in terms:
        cond, text, reason = _term(ctx, term)
        texts.append(text)
        if cond is None:
            return None, " and ".join(texts), reason, terms
        parts.append(cond)
    link = "any" if str(raw.get("link", "All")).lower() == "any" else "all"
    joined = f" {'or' if link == 'any' else 'and'} ".join(texts)
    if len(parts) == 1:
        return parts[0], joined, "", terms
    return {link: parts}, joined, "", terms


def _apply_condition(ctx: _Ctx, doc: dict[str, Any], raw: dict[str, Any]) -> ConditionReport:
    ctype = str(raw.get("type", ""))
    actions = [a for a in raw.get("action") or [] if isinstance(a, dict)]
    cond, when, reason, terms = _condition(ctx, raw)
    summary = f"{ctype or 'condition'} when {when}" if when else ctype or "condition"
    if ctype not in ("field", "require", "page"):
        kinds = {
            "calculation": "Calculations are not supported.",
            "email": "Email routing is not supported.",
            "url": "Redirects after submit are not supported.",
            "message": "Custom thank-you messages per condition are not supported.",
        }
        return ConditionReport(summary, "not_imported", kinds.get(ctype, "Not supported."))
    if cond is None:
        return ConditionReport(summary, "not_imported", reason)
    if not actions:
        return ConditionReport(summary, "not_imported", "It has no action.")

    changed: list[str] = []
    if ctype in ("field", "require"):
        for action in actions:
            visibility = str(action.get("visibility", ""))
            targets = action.get("fields") or [action.get("field")]
            for qid in [str(t) for t in targets if t]:
                el = ctx.by_qid.get(qid)
                el = _find(doc, el["id"]) if el else None
                if el is None:
                    return ConditionReport(
                        summary, "not_imported", "Its target question was not imported."
                    )
                if ctype == "field":
                    if visibility.startswith("Show"):
                        new = cond
                        old = el.get("visibleIf")
                        el["visibleIf"] = {"any": [old, new]} if old else new
                    elif visibility.startswith("Hide"):
                        new = {"not": cond}
                        old = el.get("visibleIf")
                        el["visibleIf"] = {"all": [old, new]} if old else new
                    else:
                        return ConditionReport(
                            summary, "not_imported", f'"{visibility}" is not supported.'
                        )
                else:
                    if not visibility.startswith("Require") or el.get("kind") != "field":
                        return ConditionReport(
                            summary, "not_imported", f'"{visibility}" is not supported.'
                        )
                    old = el.get("requiredIf")
                    el["requiredIf"] = {"any": [old, cond]} if old else cond
                changed.append(el.get("label") or el.get("title") or el["id"])
        verb = "Show/hide" if ctype == "field" else "Require"
        summary = f"{verb} {', '.join(changed)} when {when}"
    else:  # page skip
        skip = str(actions[0].get("skipTo", ""))
        m = re.match(r"^page-(\d+)$", skip)
        if skip in ("end", "page-end"):
            goto = "submit"
        elif m and 1 <= int(m.group(1)) <= len(doc["pages"]):
            goto = doc["pages"][int(m.group(1)) - 1]["id"]
        else:
            return ConditionReport(summary, "not_imported", "The page it skips to is unknown.")
        pages = [ctx.page_of.get(str(t.get("field")), 0) for t in terms]
        page = doc["pages"][max(pages)]
        page.setdefault("next", []).append({"if": cond, "goto": goto})
        summary = f"Skip to {goto} when {when}"
    return ConditionReport(summary, "imported")


def _validate(doc: dict[str, Any]) -> str | None:
    try:
        Form.model_validate(doc)
    except ValidationError as exc:
        return exc.errors()[0].get("msg", "invalid")
    return None


def _conditions(ctx: _Ctx, doc: dict[str, Any], conditions: list[JfCondition]) -> dict[str, Any]:
    for c in conditions:
        trial = copy.deepcopy(doc)
        result = _apply_condition(ctx, trial, c.raw)
        if result.status == "imported":
            problem = _validate(trial)
            if problem:
                result = ConditionReport(
                    result.description,
                    "not_imported",
                    "It would make the form invalid (for example a loop or a backwards jump).",
                )
            else:
                doc = trial
        ctx.report.conditions.append(result)
    return doc


# -- entry point ---------------------------------------------------------------------------


def detect_language(src: JfSource) -> str:
    count = ScriptCount()
    count.add(src.title)
    for q in src.questions:
        count.add(q.label)
        count.add(q.text)
        count.add(q.subtext)
        count.add(q.description)
        for o in q.options:
            count.add(o.label)
    return count.language


def convert(
    src: JfSource,
    *,
    language: str | None = None,
    max_upload_mb: int = 25,
    source_kind: str = "html",
) -> Conversion:
    detected = detect_language(src)
    lang = language or detected
    ctx = _Ctx(language=lang, max_upload_mb=max_upload_mb)
    ctx.pages.append({"id": "page_1", "elements": []})
    for q in src.questions:
        _convert_question(ctx, q)
    # A trailing page break leaves an empty last page.
    if len(ctx.pages) > 1 and not ctx.pages[-1]["elements"] and "title" not in ctx.pages[-1]:
        ctx.pages.pop()

    settings: dict[str, Any] = {
        "language": lang,
        "title": ctx.title or src.title or "Imported form",
    }
    if ctx.title and src.title and src.title != ctx.title and not ctx.description:
        settings["description"] = src.title
    if ctx.description:
        settings["description"] = ctx.description
    if ctx.submit_label:
        settings["submitLabel"] = ctx.submit_label
    doc: dict[str, Any] = {"schemaVersion": "1", "settings": settings, "pages": ctx.pages}
    problem = _validate(doc)
    if problem:
        raise ConversionError(problem)

    report = ctx.report
    if src.conditions:
        doc = _conditions(ctx, doc, src.conditions)
    elif source_kind == "html":
        report.conditions_note = (
            "The form's HTML has no conditions. If the form shows or hides questions on "
            "Jotform, add those rules in the builder, or import with an API key."
        )
    else:
        report.conditions_note = "The form has no conditions."

    report.dropped.append("Theme, colours, fonts and layout styling")
    if src.cover_image:
        report.dropped.append(COVER_IMAGE)
    report.dropped.append(
        "Notification emails, autoresponders, integrations and the thank-you page"
        + (" (not part of the form's HTML)" if source_kind == "html" else "")
    )
    report.dropped.extend(src.extras)
    if lang != detected:
        report.notes.append(
            f"The text looks {'Dhivehi' if detected == 'dv' else 'English'}, "
            f"but the form language was set to {'Dhivehi' if lang == 'dv' else 'English'}."
        )
    form = Form.model_validate(doc).dump()
    return Conversion(
        form=form, report=report, language=lang, detected_language=detected, captcha=ctx.captcha
    )


def field_count(doc: dict[str, Any]) -> int:
    return len([f for p in doc["pages"] for f in _iter_fields(p["elements"])])
