"""Read a Jotform form's HTML (the published page or "Source Code" export) into questions.

Every question is an ``li`` with ``data-type="control_*"``; inputs live under it with ids and
names keyed by the question id (``input_{qid}``, ``q{qid}_{name}``). Scripts are read as text
only, for ``JotForm.setConditions``, ``setCalendar`` and phone masks.
"""

from __future__ import annotations

import codecs
import json
import re
from typing import Any

from app.importers.dom import Node, clean_space, parse_html
from app.importers.jotform.logo import find_logo_url
from app.importers.jotform.model import JfCondition, JfOption, JfQuestion, JfSource
from app.importers.jotform.text import single_heading, to_markdown

QID = re.compile(r"^(?:id|cid)_(\d+)$")
NAME = re.compile(r"^q(\d+)_([^\[\]]*)")
FORM_ID = re.compile(
    r"(?:form\.jotform\.com/|JotFormIFrame-|jotform\.com/form/|formID\W+value=\W?)(\d{10,20})"
)

GENERIC_NAMES = frozenset({"input", "type", "typea", "text", "question", "field"})

# Validation classes Jotform puts on text inputs (``validate[required, Email]``).
_VALIDATE = re.compile(r"validate\[([^\]]*)\]")


class NotAJotform(ValueError):
    """The HTML holds no Jotform questions. ``form_url`` is set when it embeds one."""

    def __init__(self, form_url: str | None = None) -> None:
        super().__init__("no_questions")
        self.form_url = form_url


def _validations(node: Node) -> set[str]:
    out: set[str] = set()
    for el in [node, *node.elements()]:
        for match in _VALIDATE.finditer(el.get("class")):
            out.update(t.strip() for t in match.group(1).split(",") if t.strip())
    return out


def _decode_js_string(text: str) -> str:
    try:
        return codecs.decode(text, "unicode_escape")
    except (UnicodeDecodeError, ValueError):
        return text


def _json_after(script: str, start: int) -> Any:
    """Decode the JSON value that starts at or after ``start``; None when there is none."""
    i = start
    while i < len(script) and script[i] in " \t\r\n":
        i += 1
    try:
        value, _end = json.JSONDecoder().raw_decode(script, i)
    except ValueError:
        return None
    return value


def _scripts(root: Node) -> str:
    return "\n".join(n.raw_text() for n in root.by_tag("script"))


def _calendars(script: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in re.finditer(r"JotForm\.setCalendar\(\s*[\"'](\d+)[\"']\s*,\s*\w+\s*,\s*", script):
        value = _json_after(script, m.end())
        if isinstance(value, dict):
            out[m.group(1)] = value
    return out


def _phone_masks(script: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pattern = r"setPhoneMaskingValidator\(\s*['\"]input_(\d+)_full['\"]\s*,\s*['\"]([^'\"]*)['\"]"
    for m in re.finditer(pattern, script):
        out[m.group(1)] = _decode_js_string(m.group(2))
    return out


def _conditions(script: str) -> list[JfCondition]:
    out: list[JfCondition] = []
    for m in re.finditer(r"JotForm\.setConditions\(", script):
        value = _json_after(script, m.end())
        if isinstance(value, list):
            out.extend(JfCondition(raw=c) for c in value if isinstance(c, dict))
    return out


def _label(li: Node, qid: str) -> tuple[str, str]:
    """(label, description) of a question."""
    label_node = li.find(lambda n: n.id == f"label_{qid}")

    def skip(n: Node) -> bool:
        return bool(n.classes & {"form-required", "form-description", "jf-required-asterisk"})

    label = label_node.text(skip=skip) if label_node else ""
    desc_node = li.find(
        lambda n: n.has_class("form-description-content") or n.id == f"description_{qid}"
    ) or li.find(lambda n: n.has_class("form-description"))
    description = desc_node.text() if desc_node else ""
    return label, description


def _sublabels(li: Node) -> dict[str, str]:
    """Sub-labels keyed by the part they label (``first``, ``addr_line1``, ``main``...)."""
    out: dict[str, str] = {}
    for lab in li.find_all(lambda n: n.has_class("form-sub-label")):
        text = lab.text()
        if not text or lab.has_class("is-empty"):
            continue
        target = lab.get("for")
        part = "main"
        m = re.match(r"^(?:input_\d+_|)(\w+?)_\d+$", target)
        if m and m.group(1) not in ("input", "signature_pad", "lite_mode"):
            part = m.group(1)
        else:
            m2 = re.match(r"^input_\d+_(\w+)$", target)
            if m2 and m2.group(1) not in ("full",):
                part = m2.group(1)
        out.setdefault(part, text)
    return out


def _inputs(li: Node) -> list[Node]:
    return li.find_all(lambda n: n.tag in ("input", "select", "textarea"))


def _name(li: Node, qid: str) -> str:
    """``q131_policyAreas131[]`` -> ``policyAreas`` (Jotform repeats the id on duplicates)."""
    for el in _inputs(li):
        m = NAME.match(el.get("name"))
        if m and m.group(1) == qid:
            name = m.group(2)
            if name.endswith(qid) and len(name) > len(qid):
                name = name[: -len(qid)]
            # Names Jotform makes up when the label has no Latin letters carry no meaning.
            return "" if name.lower() in GENERIC_NAMES else name
    return ""


def _required(li: Node, label: Node | None) -> bool:
    if li.classes & {"jf-required", "form-required"}:
        return True
    if label is not None and label.find(lambda n: n.has_class("form-required")):
        return True
    for el in _inputs(li):
        wants = "required" in _validations(el) or "required" in el.attrs
        if wants and el.get("type") != "hidden":
            return True
    return False


def _choices(li: Node, kind: str) -> list[JfOption]:
    out: list[JfOption] = []
    for inp in li.find_all(lambda n: n.tag == "input" and n.get("type") == kind):
        is_other = any("other" in c for c in inp.classes) or inp.id.startswith("other_")
        target = inp.id

        def labels_it(n: Node, target: str = target) -> bool:
            return (
                n.tag == "label"
                and bool(target)
                and n.get("for") == target
                and not n.has_class("form-label")
            )

        label_node = li.find(labels_it)
        text = label_node.text() if label_node else ""
        if not text:
            text = clean_space(inp.get("value"))
        if is_other and not text:
            text = "Other"
        if text:
            out.append(JfOption(label=text, other=is_other))
    return out


def _main_input(li: Node, qid: str) -> Node | None:
    return li.find(lambda n: n.id == f"input_{qid}") or li.find(
        lambda n: n.tag in ("input", "textarea", "select") and n.get("type") != "hidden"
    )


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _read_question(
    li: Node, qid: str, type_: str, calendars: dict[str, Any], masks: dict[str, str]
) -> JfQuestion:
    q = JfQuestion(qid=qid, type=type_)
    label_node = li.find(lambda n: n.id == f"label_{qid}")
    q.label, q.description = _label(li, qid)
    q.name = _name(li, qid)
    q.required = _required(li, label_node)
    q.half = li.has_class("form-line-column")
    q.sublabels = _sublabels(li)
    main = _main_input(li, qid)
    props = q.props
    if main is not None:
        q.placeholder = clean_space(main.get("placeholder"))
        for attr in ("maxlength", "data-maxlength"):
            if main.get(attr).isdigit() and type_ in ("control_textbox", "control_textarea"):
                props["max_length"] = int(main.get(attr))
                break

    if type_ == "control_head":
        header = li.find(lambda n: n.has_class("form-header"))
        sub = li.find(lambda n: n.has_class("form-subHeader"))
        q.text = header.text() if header else ""
        q.subtext = sub.text() if sub else ""
        props["level"] = header.tag if header else "h2"
    elif type_ == "control_collapse":
        mid = li.find(lambda n: n.has_class("form-collapse-mid"))
        q.text = mid.text() if mid else li.text()
    elif type_ == "control_text":
        block = li.find(lambda n: n.has_class("form-html")) or li
        q.text = to_markdown(block)
        heading = single_heading(block)
        if heading:
            props["heading"] = heading
    elif type_ == "control_textbox":
        props["validations"] = sorted(_validations(li) - {"required"})
        if main is not None and (main.get("data-masked") == "true" or main.get("maskvalue")):
            props["mask"] = True
    elif type_ == "control_textarea":
        if li.find(lambda n: n.get("data-richtext") == "Yes" or "nicEdit" in n.get("class")):
            props["rich"] = True
        if main is not None and main.get("rows").isdigit():
            props["rows"] = int(main.get("rows"))
    elif type_ == "control_email":
        props["confirm"] = bool(
            li.find(lambda n: "[confirm]" in n.get("name") or n.id.endswith("_confirm"))
        )
    elif type_ == "control_phone":
        mask = masks.get(qid) or (main.get("placeholder") if main is not None else "")
        m = re.search(r"\+\s*(\d{1,4})", mask or "")
        if m:
            props["country_code"] = m.group(1)
        props["split"] = bool(
            li.find(lambda n: n.id in (f"input_{qid}_area", f"input_{qid}_country"))
        )
        q.placeholder = ""
    elif type_ in ("control_number", "control_spinner"):
        if main is not None:
            for key, attrs in (
                ("min", ("min", "data-spinnermin", "data-numbermin")),
                ("max", ("max", "data-spinnermax", "data-numbermax")),
                ("step", ("step", "data-spinnerstep")),
            ):
                for attr in attrs:
                    value = _number(main.get(attr))
                    if value is not None:
                        props[key] = value
                        break
    elif type_ in ("control_datetime", "control_time"):
        has_time = bool(
            li.find(lambda n: n.get("data-allow-time") == "Yes")
            or li.find(lambda n: n.id in (f"input_{qid}_hourSelect", f"hour_{qid}"))
        )
        props["time"] = has_time
        props["calendar"] = calendars.get(qid, {})
        fmt = li.find(lambda n: bool(n.get("data-format")))
        if fmt is not None:
            props["format"] = fmt.get("data-format")
        q.placeholder = ""
    elif type_ in ("control_dropdown",):
        select = li.find(lambda n: n.tag == "select")
        if select is not None:
            props["multiple"] = "multiple" in select.attrs
            for opt in select.by_tag("option"):
                text = opt.text()
                if opt.get("value") == "" or not text:
                    continue
                q.options.append(JfOption(label=text))
    elif type_ in ("control_radio", "control_checkbox"):
        kind = "radio" if type_ == "control_radio" else "checkbox"
        q.options = _choices(li, kind)
        hint = li.find(lambda n: bool(n.get("data-otherhint")))
        if hint is not None:
            props["other_hint"] = clean_space(hint.get("data-otherhint"))
        for attr, key in (("data-minselection", "min"), ("data-maxselection", "max")):
            holder = next((n for n in li.elements() if n.get(attr).isdigit()), None)
            if holder is not None and int(holder.get(attr)) > 0:
                props[key] = int(holder.get(attr))
    elif type_ in ("control_rating", "control_scale"):
        radios = li.find_all(lambda n: n.tag == "input" and n.get("type") == "radio")
        values = [v for v in (_number(r.get("value")) for r in radios) if v is not None]
        holder = li.find(lambda n: bool(n.get("data-stars") or n.get("data-scaleamount")))
        if values:
            props["low"], props["high"] = min(values), max(values)
        elif holder is not None:
            amount = _number(holder.get("data-stars") or holder.get("data-scaleamount"))
            if amount:
                props["low"], props["high"] = 1, amount
    elif type_ == "control_fileupload":
        up = li.find(lambda n: n.tag == "input" and n.get("type") == "file")
        if up is not None:
            props["accept"] = [
                e.strip().lstrip(".").lower()
                for e in re.split(r"[,\s]+", up.get("data-file-accept"))
                if e.strip() and e.strip() != "*"
            ]
            maxsize = _number(up.get("data-file-maxsize"))
            if maxsize and up.get("data-limit-file-size", "Yes") != "No":
                props["max_kb"] = maxsize
            limit = _number(up.get("data-file-limit"))
            props["multiple"] = "multiple" in up.attrs
            if limit:
                props["limit"] = int(limit)
    elif type_ in ("control_fullname", "control_address"):
        parts: list[str] = []
        for el in _inputs(li):
            m = re.search(r"\[(\w+)\]$", el.get("name"))
            if m and m.group(1) not in parts:
                parts.append(m.group(1))
                if el.tag == "select":
                    props.setdefault("part_options", {})[m.group(1)] = [
                        o.text() for o in el.by_tag("option") if o.get("value") and o.text()
                    ]
        props["parts"] = parts
    elif type_ == "control_button":
        button = li.find(lambda n: n.tag == "button" and n.get("type") == "submit") or li.find(
            lambda n: n.tag == "button"
        )
        q.text = button.text() if button else ""
    return q


def read_html(source: str) -> JfSource:
    """Parse the HTML into a :class:`JfSource`; raises :class:`NotAJotform`."""
    root = parse_html(source)
    script = _scripts(root)
    calendars = _calendars(script)
    masks = _phone_masks(script)
    out = JfSource()
    title = root.find(lambda n: n.tag == "title")
    out.title = title.text() if title else ""
    if not out.title:
        out.title = clean_space(title.raw_text()) if title else ""
    m = FORM_ID.search(source)
    out.form_id = m.group(1) if m else None

    for li in root.find_all(lambda n: n.tag == "li" and n.get("data-type").startswith("control_")):
        qm = QID.match(li.id)
        if not qm:
            continue
        out.questions.append(_read_question(li, qm.group(1), li.get("data-type"), calendars, masks))
    if not out.questions:
        raise NotAJotform(f"https://form.jotform.com/{out.form_id}" if out.form_id else None)

    out.conditions = _conditions(script)
    out.logo_url = find_logo_url(root)
    out.cover_image = out.logo_url is not None or bool(
        root.find(lambda n: n.id == "formCoverLogo" or n.has_class("form-page-cover-image"))
    )
    return out
