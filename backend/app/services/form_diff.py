"""What changed between a form's live version and its draft ("Review changes").

Only the form document is versioned: its pages, sections, repeaters, questions, logic and
``settings`` (title, description, language, button texts, success message, legacy theme
accent). Everything stored on the form record instead (access, sharing, notifications,
approvals, embed origins, form theme and logo, retention, card fields...) applies at once
without publishing, so it is never part of the diff.

Both documents are parsed and dumped with their defaults filled in, so a key that is missing
and a key that holds its default compare equal. Elements are matched by id (ids are stable
across edits); a question whose parent or order among its siblings changed is "moved".

Texts in the result are lists of pieces: ``{"text": ..., "content": bool}`` where ``content``
marks form-language text (labels, options, titles) that the studio shows with the form's
direction, and plain pieces are English UI words.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from app.schemas.form import Form

Status = Literal["added", "removed", "changed", "moved"]
Piece = dict[str, Any]

TYPE_NAMES: dict[str, str] = {
    "short_text": "Short answer",
    "long_text": "Long answer",
    "email": "Email",
    "phone": "Phone",
    "number": "Number",
    "date": "Date",
    "time": "Time",
    "single_choice": "Single choice",
    "multi_choice": "Multi choice",
    "yes_no": "Yes / no",
    "rating": "Rating",
    "file": "File upload",
    "signature": "Signature",
    "hidden": "Hidden value",
    "section": "Section",
    "repeater": "Repeater",
    "heading": "Heading",
    "paragraph": "Text block",
    "divider": "Divider",
    "image": "Image",
}

# property -> (name, kind). kind: text (form content), value (English), logic, options, list.
PROPS: dict[str, tuple[str, str]] = {
    "type": ("Question type", "type"),
    "contentType": ("Block type", "type"),
    "label": ("Label", "text"),
    "title": ("Title", "text"),
    "text": ("Text", "text"),
    "description": ("Help text", "text"),
    "placeholder": ("Placeholder", "text"),
    "required": ("Required", "bool"),
    "requiredIf": ("Required when", "logic"),
    "visibleIf": ("Shown when", "logic"),
    "width": ("Width", "width"),
    "options": ("Options", "options"),
    "display": ("Show as", "display"),
    "allowOther": ("Allow 'Other'", "bool"),
    "minSelected": ("At least selected", "value"),
    "maxSelected": ("At most selected", "value"),
    "maxLength": ("Max length", "value"),
    "pattern": ("Pattern", "code"),
    "patternMessage": ("Message when it doesn't match", "text"),
    "rows": ("Rows", "value"),
    "inputScript": ("Typing", "script"),
    "min": ("Min", "value"),
    "max": ("Max", "value"),
    "step": ("Step", "value"),
    "integer": ("Whole numbers only", "bool"),
    "minDate": ("Earliest", "value"),
    "maxDate": ("Latest", "value"),
    "defaultCountry": ("Default country", "value"),
    "accept": ("Accepted files", "list"),
    "maxFiles": ("Max files", "value"),
    "maxSizeMb": ("Max size (MB)", "value"),
    "attestation": ("Statement above the pad", "text"),
    "prefillParam": ("Fill from link parameter", "code"),
    "sensitive": ("Sensitive", "bool"),
    "imageFileId": ("Image", "image"),
    "minRows": ("Minimum rows", "value"),
    "maxRows": ("Maximum rows", "value"),
    "addLabel": ("Add button text", "text"),
    "next": ("Go to after this page", "nav"),
}
# Description is "Help text" on questions, "Description" on pages, sections and repeaters.
CONTAINER_NAMES = {"description": "Description"}

SETTINGS_PROPS: dict[str, tuple[str, str]] = {
    "title": ("Form title", "text"),
    "description": ("Form description", "text"),
    "language": ("Form language", "language"),
    "submitLabel": ("Submit button text", "text"),
    "nextLabel": ("Next button text", "text"),
    "backLabel": ("Back button text", "text"),
    "successMessage": ("Message after submitting", "text"),
    "theme.accent": ("Accent colour", "value"),
    "theme.logoFileId": ("Logo in the form", "image"),
}

OP_WORDS: dict[str, str] = {
    "eq": "is",
    "neq": "is not",
    "in": "is one of",
    "not_in": "is not one of",
    "gt": "is more than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "contains": "contains",
    "not_contains": "doesn't contain",
    "empty": "is empty",
    "not_empty": "is not empty",
    "count_eq": "has exactly",
    "count_gte": "has at least",
    "count_lte": "has at most",
}
DATE_OP_WORDS = {
    "gt": "is after",
    "gte": "is on or after",
    "lt": "is before",
    "lte": "is on or before",
}


def word(text: str) -> Piece:
    return {"text": text, "content": False}


def content(text: str) -> Piece:
    return {"text": text, "content": True}


def plain(pieces: list[Piece]) -> str:
    return "".join(p["text"] for p in pieces)


# -- the documents ---------------------------------------------------------------------------


def full(schema: dict[str, Any]) -> dict[str, Any]:
    """The document with every default filled in (``None`` for unset optionals)."""
    return Form.model_validate(schema).model_dump(mode="json", by_alias=True)


@dataclass
class Node:
    id: str
    data: dict[str, Any]  # without "elements"
    parent: str  # "page:<id>" or "el:<id>"
    page: str
    # Labels of the sections/repeaters it sits in, outermost first.
    within: list[str]


@dataclass
class Doc:
    raw: dict[str, Any]
    pages: dict[str, dict[str, Any]]  # id -> page without elements
    page_order: list[str]
    nodes: dict[str, Node]
    children: dict[str, list[str]]  # parent key -> ids in order
    preorder: dict[str, list[str]]  # page id -> element ids, depth first

    def page_number(self, page_id: str) -> int:
        return self.page_order.index(page_id) + 1

    def page_name(self, page_id: str) -> str:
        title = (self.pages[page_id].get("title") or "").strip()
        return title or f"Page {self.page_number(page_id)}"


def element_label(el: dict[str, Any]) -> str:
    kind = el.get("kind")
    if kind in ("field", "repeater"):
        return str(el.get("label") or "").strip()
    if kind == "section":
        return str(el.get("title") or "").strip()
    if kind == "content":
        return str(el.get("text") or "").strip()
    return ""


def element_type(el: dict[str, Any]) -> str:
    if el.get("kind") == "field":
        return str(el.get("type"))
    if el.get("kind") == "content":
        return str(el.get("contentType"))
    return str(el.get("kind"))


def thing(el: dict[str, Any]) -> str:
    kind = el.get("kind")
    if kind == "field":
        return "question"
    if kind == "section":
        return "section"
    if kind == "repeater":
        return "repeater"
    return "content block"


def build(schema: dict[str, Any]) -> Doc:
    raw = full(schema)
    doc = Doc(raw=raw, pages={}, page_order=[], nodes={}, children={}, preorder={})

    def walk(elements: list[dict[str, Any]], parent: str, page: str, within: list[str]) -> None:
        ids = doc.children.setdefault(parent, [])
        for el in elements:
            data = {k: v for k, v in el.items() if k != "elements"}
            doc.nodes[el["id"]] = Node(el["id"], data, parent, page, within)
            ids.append(el["id"])
            doc.preorder[page].append(el["id"])
            if el.get("kind") in ("section", "repeater"):
                name = element_label(el) or TYPE_NAMES[el["kind"]]
                walk(el.get("elements") or [], f"el:{el['id']}", page, [*within, name])

    for page in raw["pages"]:
        pid = page["id"]
        doc.pages[pid] = {k: v for k, v in page.items() if k != "elements"}
        doc.page_order.append(pid)
        doc.preorder[pid] = []
        walk(page.get("elements") or [], f"page:{pid}", pid, [])
    return doc


# -- display values ---------------------------------------------------------------------------


def _labels(doc: Doc) -> dict[str, dict[str, Any]]:
    return {nid: n.data for nid, n in doc.nodes.items()}


def value_text(el: dict[str, Any] | None, op: str, value: Any) -> list[Piece]:
    if op in ("empty", "not_empty"):
        return []
    if op.startswith("count_"):
        unit = "rows" if el and el.get("kind") == "repeater" else "files"
        if el and el.get("type") == "multi_choice":
            unit = "selected"
        return [word(f" {value} {unit}")]

    def one(v: Any) -> Piece:
        if el and el.get("type") == "yes_no" and isinstance(v, bool):
            return word("Yes" if v else "No")
        if el and el.get("type") in ("single_choice", "multi_choice"):
            for o in el.get("options") or []:
                if o.get("value") == v:
                    return content(str(o.get("label") or v))
        return content("" if v is None else str(v))

    values = value if isinstance(value, list) else [value]
    out: list[Piece] = []
    for i, v in enumerate(values):
        out.append(word(" " if i == 0 else (" or " if i == len(values) - 1 else ", ")))
        out.append(one(v))
    return out


def condition_text(cond: Any, doc: Doc, nested: bool = False) -> list[Piece]:
    if not isinstance(cond, dict):
        return []
    if "field" in cond:
        node = doc.nodes.get(cond["field"])
        el = node.data if node else None
        label = (element_label(el) or "Untitled question") if el else "(deleted question)"
        op = str(cond.get("op"))
        words = OP_WORDS.get(op, op)
        if el and el.get("type") in ("date", "time"):
            words = DATE_OP_WORDS.get(op, words)
        return [
            content(label) if el else word(label),
            word(f" {words}"),
            *value_text(el, op, cond.get("value")),
        ]
    if "not" in cond:
        return [word("not ("), *condition_text(cond["not"], doc), word(")")]
    items = cond.get("all") if "all" in cond else cond.get("any")
    joiner = " and " if "all" in cond else " or "
    out: list[Piece] = []
    for i, c in enumerate(items or []):
        if i:
            out.append(word(joiner))
        out.extend(condition_text(c, doc, nested=True))
    if not items:
        out.append(word("always" if "all" in cond else "never"))
    if nested and items and len(items) > 1:
        return [word("("), *out, word(")")]
    return out


def nav_text(rules: list[dict[str, Any]], doc: Doc) -> list[Piece]:
    out: list[Piece] = []
    for i, rule in enumerate(rules):
        if i:
            out.append(word("; "))
        goto = rule.get("goto")
        target = (
            [word("Submit")]
            if goto == "submit" or goto not in doc.pages
            else [content(doc.page_name(goto))]
            if (doc.pages[goto].get("title") or "").strip()
            else [word(doc.page_name(goto))]
        )
        out += [word("If "), *condition_text(rule.get("if"), doc), word(", go to "), *target]
    return out


def display(kind: str, value: Any, doc: Doc) -> list[Piece] | None:
    """A property value as pieces; None when it is unset/empty."""
    if value is None or value == "" or value == [] or (kind == "bool" and value is False):
        if kind == "bool":
            return [word("Off")]
        return None
    if kind == "text":
        return [content(str(value))]
    if kind == "bool":
        return [word("On")]
    if kind == "width":
        return [word("Half width" if value == "half" else "Full width")]
    if kind == "type":
        return [word(TYPE_NAMES.get(str(value), str(value)))]
    if kind == "display":
        return [word("Dropdown" if value == "dropdown" else "Radio buttons")]
    if kind == "script":
        return [word({"latin": "Latin", "thaana": "Thaana"}.get(str(value), "Automatic"))]
    if kind == "language":
        return [word("Dhivehi" if value == "dv" else "English")]
    if kind == "logic":
        return condition_text(value, doc)
    if kind == "nav":
        return nav_text(value, doc)
    if kind == "list":
        return [word(", ".join(str(v) for v in value))]
    if kind == "image":
        return [word("An image")]
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return [word(str(value))]


# -- property changes -------------------------------------------------------------------------


def _options_change(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    old = {o["value"]: o["label"] for o in before}
    new = {o["value"]: o["label"] for o in after}
    added = [{"value": v, "label": label} for v, label in new.items() if v not in old]
    removed = [{"value": v, "label": label} for v, label in old.items() if v not in new]
    renamed = [
        {"value": v, "before": old[v], "after": label}
        for v, label in new.items()
        if v in old and old[v] != label
    ]
    common_old = [v for v in old if v in new]
    common_new = [v for v in new if v in old]
    return {
        "added": added,
        "removed": removed,
        "renamed": renamed,
        "reordered": common_old != common_new,
    }


def _options_summary(o: dict[str, Any]) -> str:
    parts = []
    for key, verb in (("added", "added"), ("removed", "removed"), ("renamed", "renamed")):
        n = len(o[key])
        if n:
            parts.append(f"{n} {'option' if n == 1 else 'options'} {verb}")
    if o["reordered"]:
        parts.append("options reordered")
    text = ", ".join(parts) or "Options changed"
    return text[0].upper() + text[1:]


def _text_summary(name: str, before: Any, after: Any) -> str:
    if before in (None, ""):
        return f"{name} added"
    if after in (None, ""):
        return f"{name} removed"
    return f"{name} changed"


def prop_change(
    prop: str,
    name: str,
    kind: str,
    before: Any,
    after: Any,
    old: Doc,
    new: Doc,
) -> dict[str, Any] | None:
    if before == after:
        return None
    change: dict[str, Any] = {
        "property": prop,
        "name": name,
        "kind": kind,
        "before": display(kind, before, old),
        "after": display(kind, after, new),
    }
    if kind == "options":
        opts = _options_change(before or [], after or [])
        change["options"] = opts
        change["before"] = change["after"] = None
        change["summary"] = _options_summary(opts)
    elif kind == "bool":
        if prop == "required":
            change["summary"] = "Now required" if after else "No longer required"
        else:
            change["summary"] = f"{name} turned {'on' if after else 'off'}"
    elif kind in ("text", "logic", "nav", "image", "code") or before is None or after is None:
        if kind == "logic":
            label = {"visibleIf": "Show rule", "requiredIf": "Required rule"}.get(prop, name)
            change["summary"] = _text_summary(label, before, after)
        elif kind == "nav":
            change["summary"] = _text_summary("Page navigation", before or None, after or None)
        else:
            change["summary"] = _text_summary(name, before, after)
    else:
        change["summary"] = f"{name} changed"
    return change


def element_changes(
    a: dict[str, Any], b: dict[str, Any], old: Doc, new: Doc
) -> list[dict[str, Any]]:
    container = a.get("kind") != "field" or b.get("kind") != "field"
    out = []
    keys = [k for k in PROPS if k in a or k in b]
    keys += sorted(k for k in set(a) | set(b) if k not in PROPS and k not in ("id", "kind"))
    for key in keys:
        name, kind = PROPS.get(key, (key, "value"))
        if container and key in CONTAINER_NAMES:
            name = CONTAINER_NAMES[key]
        change = prop_change(key, name, kind, a.get(key), b.get(key), old, new)
        if change:
            out.append(change)
    if a.get("kind") != b.get("kind"):
        out.insert(
            0,
            {
                "property": "kind",
                "name": "Block type",
                "kind": "type",
                "before": [word(TYPE_NAMES.get(element_type(a), element_type(a)))],
                "after": [word(TYPE_NAMES.get(element_type(b), element_type(b)))],
                "summary": "Block type changed",
            },
        )
    return out


# -- order ------------------------------------------------------------------------------------


def lcs(a: list[str], b: list[str]) -> set[str]:
    """Items of the longest common subsequence (the ones that kept their relative order)."""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
            )
    keep: set[str] = set()
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            keep.add(a[i])
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return keep


def reordered(old_ids: list[str], new_ids: list[str]) -> set[str]:
    common = set(old_ids) & set(new_ids)
    a = [x for x in old_ids if x in common]
    b = [x for x in new_ids if x in common]
    return common - lcs(a, b)


def interleave(new_ids: list[str], old_ids: list[str], gone: Iterable[str]) -> list[str]:
    """``new_ids`` with the ``gone`` ids put back after the item that preceded them before."""
    gone = set(gone)
    out = list(new_ids)
    anchor: str | None = None
    for x in old_ids:
        if x in gone:
            out.insert(out.index(anchor) + 1 if anchor is not None else 0, x)
            anchor = x
        elif x in out:
            anchor = x
    return out


# -- the diff ---------------------------------------------------------------------------------


@dataclass
class Counts:
    added: int = 0
    removed: int = 0
    changed: int = 0
    moved: int = 0
    by_thing: dict[tuple[str, str], int] = field(default_factory=dict)

    def add(self, status: str, what: str) -> None:
        setattr(self, status, getattr(self, status) + 1)
        self.by_thing[(what, status)] = self.by_thing.get((what, status), 0) + 1


PLURAL = {
    "page": "pages",
    "question": "questions",
    "section": "sections",
    "repeater": "repeaters",
    "content block": "content blocks",
}


def summary_text(counts: Counts, settings_changed: int) -> str:
    parts = []
    for what in ("page", "question", "section", "repeater", "content block"):
        for status in ("added", "removed", "changed", "moved"):
            n = counts.by_thing.get((what, status), 0)
            if n:
                parts.append(f"{n} {what if n == 1 else PLURAL[what]} {status}")
    if settings_changed:
        parts.append(
            "1 form setting changed"
            if settings_changed == 1
            else f"{settings_changed} form settings changed"
        )
    if not parts:
        return "No changes"
    text = ", ".join(parts)
    return text[0].upper() + text[1:]


def _where(doc: Doc, node: Node) -> list[Piece]:
    """Page name and containers, e.g. "Page 2, Contacts"."""
    title = (doc.pages[node.page].get("title") or "").strip()
    out: list[Piece] = [content(title) if title else word(doc.page_name(node.page))]
    for name in node.within:
        out += [word(", "), content(name)]
    return out


def _settings(a: dict[str, Any], b: dict[str, Any], old: Doc, new: Doc) -> list[dict[str, Any]]:
    out = []
    for key, (name, kind) in SETTINGS_PROPS.items():
        if "." in key:
            outer, inner = key.split(".")
            before, after = (a.get(outer) or {}).get(inner), (b.get(outer) or {}).get(inner)
        else:
            before, after = a.get(key), b.get(key)
        change = prop_change(key, name, kind, before, after, old, new)
        if change:
            out.append(change)
    return out


def diff(published: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Structured changes from ``published`` to ``draft`` (both valid form documents)."""
    old, new = build(published), build(draft)
    counts = Counts()

    settings = _settings(old.raw["settings"], new.raw["settings"], old, new)

    # Pages.
    added_pages = [p for p in new.page_order if p not in old.pages]
    removed_pages = [p for p in old.page_order if p not in new.pages]
    moved_pages = reordered(old.page_order, new.page_order)

    # Elements: where each one is reported (its page now, or its old page when removed).
    elements: dict[str, list[dict[str, Any]]] = {}
    old_ids, new_ids = set(old.nodes), set(new.nodes)

    # Reordered among siblings that kept the same parent.
    moved_in_place: set[str] = set()
    for parent, ids in new.children.items():
        before_ids = [x for x in old.children.get(parent, []) if old.nodes[x].parent == parent]
        after_ids = [x for x in ids if x in old_ids and old.nodes[x].parent == parent]
        moved_in_place |= reordered(before_ids, after_ids)

    def entry(nid: str, status: Status, doc: Doc, **extra: Any) -> dict[str, Any]:
        node = doc.nodes[nid]
        el = node.data
        return {
            "id": nid,
            "kind": el.get("kind"),
            "type": element_type(el),
            "typeName": TYPE_NAMES.get(element_type(el), element_type(el)),
            "label": element_label(el),
            "within": node.within,
            "status": status,
            "changes": [],
            "movedFrom": None,
            **extra,
        }

    reported: dict[str, dict[str, Any]] = {}
    for nid in new_ids - old_ids:
        item = entry(nid, "added", new)
        item["summary"] = f"{TYPE_NAMES.get(item['type'], 'Block')} added"
        reported[nid] = item
        counts.add("added", thing(new.nodes[nid].data))
    for nid in old_ids - new_ids:
        item = entry(nid, "removed", old)
        item["summary"] = f"{TYPE_NAMES.get(item['type'], 'Block')} removed"
        reported[nid] = item
        counts.add("removed", thing(old.nodes[nid].data))
    for nid in old_ids & new_ids:
        a, b = old.nodes[nid], new.nodes[nid]
        changes = element_changes(a.data, b.data, old, new)
        parent_moved = a.parent != b.parent
        moved = parent_moved or nid in moved_in_place
        if not changes and not moved:
            continue
        item = entry(nid, "changed" if changes else "moved", new, changes=changes)
        if moved:
            if parent_moved:
                item["movedFrom"] = _where(old, a)
                item["moveSummary"] = f"Moved from {plain(_where(old, a))}"
            else:
                item["moveSummary"] = "Moved to a new position"
        summaries = [c["summary"] for c in changes]
        if moved:
            summaries.append(item["moveSummary"])
        item["summary"] = "; ".join(summaries)
        reported[nid] = item
        what = thing(b.data)
        if changes:
            counts.add("changed", what)
        if moved:
            counts.add("moved", what)

    for nid, item in reported.items():
        doc = old if item["status"] == "removed" else new
        elements.setdefault(doc.nodes[nid].page, []).append(item)

    # Page groups, in the draft's order with removed pages back where they were.
    groups = []
    for pid in interleave(new.page_order, old.page_order, removed_pages):
        if pid in removed_pages:
            status: str | None = "removed"
            doc = old
        elif pid in added_pages:
            status, doc = "added", new
        else:
            doc = new
            status = None
        page_changes: list[dict[str, Any]] = []
        if status is None:
            pa, pb = old.pages[pid], new.pages[pid]
            for key in ("title", "description", "visibleIf", "next"):
                name, kind = PROPS.get(key, (key, "value"))
                name = {"title": "Page title", "description": "Page description"}.get(key, name)
                change = prop_change(key, name, kind, pa.get(key), pb.get(key), old, new)
                if change:
                    page_changes.append(change)
            if page_changes:
                status = "changed"
            elif pid in moved_pages:
                status = "moved"
        items = elements.get(pid, [])
        if status is None and not items:
            continue
        # Elements in the page's order now, removed ones back where they were.
        new_order = new.preorder.get(pid, [])
        old_order = old.preorder.get(pid, [])
        gone = [x for x in old_order if x in reported and reported[x]["status"] == "removed"]
        order = interleave(new_order if pid in new.pages else [], old_order, gone)
        rank = {x: i for i, x in enumerate(order)}
        items.sort(key=lambda it: rank.get(it["id"], len(rank)))
        if status in ("added", "removed", "changed", "moved"):
            counts.add(status, "page")
        number = doc.page_number(pid)
        page_summaries = {
            "added": "Page added",
            "removed": "Page removed",
            "moved": f"Page moved (was page {old.page_number(pid)})" if pid in old.pages else "",
        }
        summary = page_summaries.get(status or "", "")
        if status == "changed":
            summary = "; ".join(c["summary"] for c in page_changes)
            if pid in moved_pages:
                summary += f"; moved (was page {old.page_number(pid)})"
        groups.append(
            {
                "pageId": pid,
                "number": number,
                "title": (doc.pages[pid].get("title") or "").strip(),
                "status": status,
                "summary": summary,
                "movedFrom": old.page_number(pid) if pid in moved_pages else None,
                "changes": page_changes,
                "elements": items,
            }
        )

    total = counts.added + counts.removed + counts.changed + counts.moved + len(settings)
    return {
        "hasChanges": total > 0,
        "summary": summary_text(counts, len(settings)),
        "counts": {
            "added": counts.added,
            "removed": counts.removed,
            "changed": counts.changed + len(settings),
            "moved": counts.moved,
        },
        "language": new.raw["settings"].get("language", "en"),
        "settings": settings,
        "pages": groups,
    }


def iter_changes(result: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every element entry of a diff (tests and summaries)."""
    for page in result["pages"]:
        yield from page["elements"]
