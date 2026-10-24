"""Cross-element rules for a :class:`~app.schemas.form.Form` (DESIGN sections 4.2 and 5.3).

Pydantic handles the shape of each object; this module checks everything that needs the
whole document: id uniqueness, nesting limits, logic references and scope,
forward-only navigation and dependency cycles.

:func:`collect_issues` returns structured issues; :func:`check_form` raises them as one
Pydantic error (it runs as the ``Form`` model validator).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydantic_core import PydanticCustomError

from app.logic.graph import build_graph, find_cycle
from app.logic.index import FormIndex, element_conditions, iter_leaves
from app.schemas.form import (
    COUNT_OPS,
    REPEATER_OPS,
    ContentElement,
    Option,
    RepeaterElement,
    Settings,
)

if TYPE_CHECKING:
    from app.schemas.form import Condition, Form

MAX_SECTION_DEPTH = 2
COUNTABLE_FIELD_TYPES = frozenset({"multi_choice", "file"})
RESERVED_IDS = frozenset({"submit"})


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    target: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Texts that must not be blank when a form is published, per model: (model, attribute).
REQUIRED_TEXTS: tuple[tuple[type[BaseModel], str], ...] = (
    (Settings, "title"),
    (RepeaterElement, "label"),
    (Option, "label"),
)


def _blank_required_texts(obj: Any, path: str) -> list[str]:
    """Dotted paths of required texts inside ``obj`` that are blank (whitespace only)."""
    found: list[str] = []
    if isinstance(obj, BaseModel):
        required = {attr for model, attr in REQUIRED_TEXTS if isinstance(obj, model)}
        if getattr(obj, "kind", None) == "field":
            required.add("label")
        if isinstance(obj, ContentElement) and obj.content_type in ("heading", "paragraph"):
            required.add("text")
        for name in type(obj).model_fields:
            value = getattr(obj, name)
            if name in required and isinstance(value, str) and not value.strip():
                found.append(f"{path}.{name}")
            else:
                found.extend(_blank_required_texts(value, f"{path}.{name}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(_blank_required_texts(item, f"{path}[{i}]"))
    return found


def collect_issues(form: Form) -> list[Issue]:
    issues: list[Issue] = []
    index = FormIndex.build(form)

    # -- ids and structure -----------------------------------------------------------
    for dup in sorted(set(index.duplicates)):
        issues.append(Issue("duplicate_id", f"id '{dup}' is used more than once", dup))
    for page in form.pages:
        if page.id in RESERVED_IDS:
            issues.append(Issue("reserved_id", f"'{page.id}' is reserved", page.id))

    for info in index.elements.values():
        if info.id in RESERVED_IDS:
            issues.append(Issue("reserved_id", f"'{info.id}' is reserved", info.id))
        if info.kind == "repeater" and info.repeater_id is not None:
            issues.append(
                Issue("repeater_nested", f"repeater '{info.id}' cannot sit in a repeater", info.id)
            )
        if info.kind == "section" and info.section_depth >= MAX_SECTION_DEPTH:
            issues.append(
                Issue(
                    "section_too_deep",
                    f"section '{info.id}' is nested more than {MAX_SECTION_DEPTH} levels",
                    info.id,
                )
            )
        if info.type == "signature" and info.repeater_id is not None:
            issues.append(
                Issue(
                    "signature_in_repeater",
                    f"signature field '{info.id}' cannot sit in a repeater",
                    info.id,
                )
            )

    # -- logic references ------------------------------------------------------------
    def check_condition(
        cond: Condition | None,
        owner: str,
        scope: str | None,
        max_page: int | None = None,
    ) -> None:
        """``scope`` is the repeater the condition is evaluated in; ``max_page`` (exclusive)
        limits page-level conditions to fields on earlier pages."""
        for leaf in iter_leaves(cond):
            ref = index.elements.get(leaf.field)
            if ref is None:
                if leaf.field in index.page_index:
                    issues.append(
                        Issue("not_value_field", f"{owner}: '{leaf.field}' is a page", owner)
                    )
                else:
                    issues.append(
                        Issue("unknown_reference", f"{owner}: unknown field '{leaf.field}'", owner)
                    )
                continue
            if not ref.produces_value:
                issues.append(
                    Issue(
                        "not_value_field",
                        f"{owner}: '{leaf.field}' is a {ref.kind} and has no value",
                        owner,
                    )
                )
                continue
            if ref.repeater_id is not None and ref.repeater_id != scope:
                issues.append(
                    Issue(
                        "repeater_scope",
                        f"{owner}: '{leaf.field}' is inside repeater '{ref.repeater_id}' and "
                        "can only be referenced from that repeater",
                        owner,
                    )
                )
            if ref.kind == "repeater" and leaf.op not in REPEATER_OPS:
                issues.append(
                    Issue(
                        "repeater_op",
                        f"{owner}: repeater '{leaf.field}' only supports empty, not_empty and "
                        "count_* operators",
                        owner,
                    )
                )
            if (
                leaf.op in COUNT_OPS
                and ref.kind != "repeater"
                and ref.type not in COUNTABLE_FIELD_TYPES
            ):
                issues.append(
                    Issue(
                        "count_op_type",
                        f"{owner}: '{leaf.op}' needs a multi_choice, file or repeater field",
                        owner,
                    )
                )
            if max_page is not None and ref.page_index >= max_page:
                issues.append(
                    Issue(
                        "page_reference_not_earlier",
                        f"{owner}: page logic can only read fields on earlier pages "
                        f"('{leaf.field}' is not)",
                        owner,
                    )
                )

    for info in index.elements.values():
        visible_if, required_if = element_conditions(info.element)
        check_condition(visible_if, info.id, info.repeater_id)
        check_condition(required_if, info.id, info.repeater_id)

    for i, page in enumerate(form.pages):
        check_condition(page.visible_if, page.id, None, max_page=i)
        for rule in page.next:
            check_condition(rule.if_, page.id, None, max_page=i + 1)
            if rule.goto == "submit":
                continue
            target = index.page_index.get(rule.goto)
            if target is None:
                issues.append(
                    Issue("goto_unknown", f"{page.id}: goto '{rule.goto}' is not a page", page.id)
                )
            elif target <= i:
                issues.append(
                    Issue(
                        "goto_not_forward",
                        f"{page.id}: goto '{rule.goto}' must jump to a later page",
                        page.id,
                    )
                )

    # -- cycles (only meaningful once references resolve) -----------------------------
    if not issues:
        cycle = find_cycle(build_graph(index))
        if cycle:
            issues.append(Issue("cycle", "logic dependency cycle: " + " -> ".join(cycle), cycle[0]))
    return issues


def check_form(form: Form) -> None:
    issues = collect_issues(form)
    if issues:
        raise PydanticCustomError(
            "form_rules",
            "{summary}",
            {
                "summary": "; ".join(i.message for i in issues),
                "issues": [i.as_dict() for i in issues],
            },
        )


def collect_publish_issues(form: Form) -> list[Issue]:
    """Extra checks before publishing: titles, labels and heading/paragraph text must not be
    blank (drafts may hold empty strings while they are being written)."""
    return [
        Issue("blank_text", f"{path} is blank", path)
        for path in _blank_required_texts(form, "form")
    ]
