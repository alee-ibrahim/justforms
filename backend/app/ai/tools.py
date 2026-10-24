"""Schema tools the model calls (DESIGN 12.2).

Each tool is a deterministic operation on an in-memory working copy of the draft. Arguments
are parsed with a Pydantic model (whose JSON Schema is what the provider sees), the change
is made on a copy, and the result must pass the full form schema, including the logic
reference and cycle checks. A failing call leaves the working copy as it was and returns the
error to the model, which can correct itself.
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from app.ai.providers.http import clean_schema
from app.ai.types import ToolSpec
from app.schemas.form import ID_PATTERN, Form

ID_RE = re.compile(ID_PATTERN)
CONTAINER_KINDS = ("section", "repeater")
# Keys the model may never set: ids are fixed once made, children move with move_field, and
# images/logos point at uploaded files the model has no business choosing.
LOCKED_KEYS = frozenset({"id", "kind", "elements", "imageFileId"})
MAX_ERRORS_SHOWN = 6


class ToolFailure(Exception):
    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class Args(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, validate_by_name=True, validate_by_alias=True
    )


Text = Annotated[str, Field(max_length=10_000)]
ConditionArg = Annotated[
    dict[str, Any],
    Field(
        description=(
            'A condition: {"field": "<question id>", "op": "<op>", "value": ...} or '
            '{"all": [...]}, {"any": [...]}, {"not": {...}}. Ops: eq, neq, gt, gte, lt, lte, '
            "in, not_in (value is an array), contains, not_contains, empty, not_empty (no "
            "value), count_eq, count_gte, count_lte (non-negative integer). Compare choice "
            "questions with option values and yes/no questions with true/false."
        )
    ),
]


class GetForm(Args):
    """Return the current form (as changed so far) as JSON."""


class UpdateSettings(Args):
    """Change the form title, description, submit button label or success message. Pass null
    to clear an optional text."""

    title: Text | None = None
    description: Text | None = None
    submit_label: Text | None = None
    success_message: Text | None = None


class AddPage(Args):
    """Add a page. Returns the new page id."""

    title: Text | None = None
    description: Text | None = None
    after_page_id: str | None = Field(
        default=None, description="Insert after this page; default: at the end."
    )


class UpdatePage(Args):
    """Change a page's title or description (null clears it)."""

    page_id: str
    title: Text | None = None
    description: Text | None = None


class RemovePage(Args):
    """Remove a page. A page with questions needs moveElementsTo (another page id)."""

    page_id: str
    move_elements_to: str | None = None


class AddField(Args):
    """Add a question, text block, section or repeater to a page, section or repeater.
    Returns the new element's id (made from the label when not given)."""

    parent_id: str = Field(description="Page, section or repeater id.")
    index: int | None = Field(default=None, ge=0, description="Position; default: at the end.")
    field: dict[str, Any] = Field(
        description=(
            "The element in the JustForms schema shape, e.g. "
            '{"kind": "field", "type": "short_text", "label": "Full name", "required": true}, '
            '{"kind": "content", "contentType": "heading", "text": "About you"}, '
            '{"kind": "section", "title": "Address", "elements": [...]}. '
            "Ids are optional snake_case."
        )
    )


class UpdateField(Args):
    """Change properties of a question or other element. Only the given keys change; null
    removes a property. The id, kind and child elements cannot be changed here."""

    id: str
    changes: dict[str, Any]


class RemoveField(Args):
    """Remove an element. Fails while other questions' or pages' logic refers to it."""

    id: str


class MoveField(Args):
    """Move an element to another position, page, section or repeater."""

    id: str
    parent_id: str = Field(description="Page, section or repeater id.")
    index: int | None = Field(default=None, ge=0, description="Position; default: at the end.")


class SetOptions(Args):
    """Replace the options of a single or multiple choice question. Options are labels, or
    {"value", "label"} objects; values are made from labels when missing."""

    id: str
    options: list[str | dict[str, Any]] = Field(min_length=1, max_length=1000)


class SetLogic(Args):
    """Show an element or page only when a condition holds (visibleIf), or make a question
    required when it holds (requiredIf). condition null removes the rule."""

    target_id: str
    kind: Literal["visibleIf", "requiredIf"]
    condition: ConditionArg | None = None


class NavigationRuleArg(Args):
    if_: ConditionArg = Field(alias="if")
    goto: str = Field(description='A later page id, or "submit".')


class SetPageNavigation(Args):
    """Set where respondents go after a page: the first matching rule wins; otherwise the next
    page. An empty list removes the rules. Rules may only jump forward."""

    page_id: str
    rules: list[NavigationRuleArg]


class FlagUncertain(Args):
    """Mark an element you are unsure about (for example a hard-to-read box on a paper form)
    so the person checks it."""

    target_id: str
    note: Annotated[str, Field(max_length=300)]


class ReportFilledIn(Args):
    """Call this instead of anything else when the document has been filled in (it shows
    someone's answers, names or signatures). Nothing is added."""

    note: Annotated[str, Field(max_length=300)]


TOOLS: dict[str, type[Args]] = {
    "get_form": GetForm,
    "update_settings": UpdateSettings,
    "add_page": AddPage,
    "update_page": UpdatePage,
    "remove_page": RemovePage,
    "add_field": AddField,
    "update_field": UpdateField,
    "remove_field": RemoveField,
    "move_field": MoveField,
    "set_options": SetOptions,
    "set_logic": SetLogic,
    "set_page_navigation": SetPageNavigation,
    "flag_uncertain": FlagUncertain,
    "report_filled_in": ReportFilledIn,
}
IMPORT_ONLY = frozenset({"report_filled_in"})


def tool_specs(*, importing: bool = False) -> list[ToolSpec]:
    specs = []
    for name, model in TOOLS.items():
        if name in IMPORT_ONLY and not importing:
            continue
        schema = clean_schema(model.model_json_schema(by_alias=True))
        specs.append(ToolSpec(name, (model.__doc__ or name).strip(), schema))
    return specs


# --------------------------------------------------------------------------------------
# Helpers on the JSON document
# --------------------------------------------------------------------------------------


@dataclass
class Located:
    element: dict[str, Any]
    siblings: list[dict[str, Any]]
    index: int
    page_index: int
    parent_id: str  # page id, or the section/repeater id that holds it


def iter_elements(
    elements: list[dict[str, Any]], page_index: int, parent_id: str
) -> Iterator[Located]:
    for i, el in enumerate(elements):
        yield Located(el, elements, i, page_index, parent_id)
        if el.get("kind") in CONTAINER_KINDS:
            yield from iter_elements(el.setdefault("elements", []), page_index, el["id"])


def all_located(schema: dict[str, Any]) -> Iterator[Located]:
    for p, page in enumerate(schema["pages"]):
        yield from iter_elements(page.setdefault("elements", []), p, page["id"])


def element_label(el: dict[str, Any]) -> str:
    text = el.get("label") or el.get("title") or el.get("text") or ""
    if not text and el.get("kind") == "content":
        text = str(el.get("contentType", "")).capitalize()
    text = " ".join(str(text).split())
    return text[:80] + ("…" if len(text) > 80 else "")


def page_label(schema: dict[str, Any], page_id: str) -> str:
    for i, page in enumerate(schema["pages"]):
        if page["id"] == page_id:
            return str(page.get("title") or f"Page {i + 1}")[:80]
    return page_id


def slug_id(text: str, fallback: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:40].strip("_")
    if not slug or not slug[0].isalpha():
        slug = fallback
    return slug


def unique_id(base: str, taken: set[str]) -> str:
    candidate, n = base, 1
    while candidate in taken or candidate == "submit":
        n += 1
        candidate = f"{base}_{n}"
    taken.add(candidate)
    return candidate


def _camel_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {(to_camel(k) if "_" in k else k): v for k, v in data.items()}


def condition_fields(cond: Any) -> Iterator[str]:
    if isinstance(cond, dict):
        if isinstance(cond.get("field"), str):
            yield cond["field"]
        for key in ("all", "any"):
            for sub in cond.get(key) or []:
                yield from condition_fields(sub)
        if "not" in cond:
            yield from condition_fields(cond["not"])


def format_validation(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False, include_input=False)[:MAX_ERRORS_SHOWN]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        lines.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    more = len(exc.errors()) - MAX_ERRORS_SHOWN
    if more > 0:
        lines.append(f"(and {more} more)")
    return "; ".join(lines)


# --------------------------------------------------------------------------------------
# The working copy
# --------------------------------------------------------------------------------------


@dataclass
class StepResult:
    """What one tool call did, for the transcript (``action`` + ``label``) and the model."""

    ok: bool
    result: dict[str, Any]
    action: str = ""
    label: str = ""
    target_id: str | None = None
    error: str | None = None
    changed: bool = False


@dataclass
class WorkingCopy:
    schema: dict[str, Any]
    importing: bool = False
    flags: list[dict[str, Any]] = field(default_factory=list)
    filled_in: str | None = None

    # -- lookups -----------------------------------------------------------------------

    def _ids(self) -> set[str]:
        ids = {p["id"] for p in self.schema["pages"]}
        ids.update(loc.element["id"] for loc in all_located(self.schema))
        return ids

    def _locate(self, schema: dict[str, Any], element_id: str) -> Located:
        for loc in all_located(schema):
            if loc.element.get("id") == element_id:
                return loc
        raise ToolFailure(f"There is no element with id '{element_id}'.")

    def _page_index(self, schema: dict[str, Any], page_id: str) -> int:
        for i, page in enumerate(schema["pages"]):
            if page["id"] == page_id:
                return i
        raise ToolFailure(f"There is no page with id '{page_id}'.")

    def _container(self, schema: dict[str, Any], parent_id: str) -> list[dict[str, Any]]:
        for page in schema["pages"]:
            if page["id"] == parent_id:
                elements: list[dict[str, Any]] = page.setdefault("elements", [])
                return elements
        for loc in all_located(schema):
            if loc.element.get("id") == parent_id:
                if loc.element.get("kind") not in CONTAINER_KINDS:
                    raise ToolFailure(
                        f"'{parent_id}' is a {loc.element.get('kind')}; elements can only go "
                        "into a page, section or repeater."
                    )
                children: list[dict[str, Any]] = loc.element.setdefault("elements", [])
                return children
        raise ToolFailure(f"There is no page, section or repeater with id '{parent_id}'.")

    def references_to(self, schema: dict[str, Any], target_id: str) -> list[str]:
        """Ids of elements and pages whose logic reads ``target_id`` (outside it)."""
        inside = {target_id}
        try:
            loc = self._locate(schema, target_id)
            if loc.element.get("kind") in CONTAINER_KINDS:
                inside.update(
                    sub.element["id"]
                    for sub in iter_elements(loc.element.get("elements", []), 0, target_id)
                )
        except ToolFailure:
            pass
        refs: list[str] = []
        for page in schema["pages"]:
            conds = [page.get("visibleIf"), *[r.get("if") for r in page.get("next") or []]]
            if any(target_id in condition_fields(c) for c in conds):
                refs.append(page["id"])
        for loc in all_located(schema):
            el = loc.element
            if el["id"] in inside:
                continue
            if any(target_id in condition_fields(el.get(k)) for k in ("visibleIf", "requiredIf")):
                refs.append(el["id"])
        return refs

    # -- element preparation -----------------------------------------------------------

    def _options(self, options: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        taken: set[str] = set()
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                label, value = opt, None
            elif isinstance(opt, dict):
                label = str(opt.get("label", opt.get("value", "")))
                value = opt.get("value")
            else:
                raise ToolFailure("Each option must be a label or a {value, label} object.")
            if value is None or str(value).strip() == "":
                value = unique_id(slug_id(label, f"option_{i + 1}"), taken)
            else:
                value = str(value)
                taken.add(value)
            out.append({"value": value, "label": label})
        return out

    def _prepare(self, raw: dict[str, Any], taken: set[str]) -> dict[str, Any]:
        el = _camel_keys(copy.deepcopy(raw))
        if "imageFileId" in el:
            raise ToolFailure("Images can't be added by the assistant; leave imageFileId out.")
        if "kind" not in el:
            if "type" in el:
                el["kind"] = "field"
            elif "contentType" in el:
                el["kind"] = "content"
            else:
                raise ToolFailure('Give the element a "kind": field, content, section or repeater.')
        kind = el["kind"]
        given = el.get("id")
        if isinstance(given, str) and ID_RE.match(given) and given not in taken:
            taken.add(given)
        else:
            label = str(el.get("label") or el.get("title") or el.get("text") or "")
            fallback = str(el.get("type") or el.get("contentType") or kind)
            el["id"] = unique_id(slug_id(label, fallback), taken)
        if isinstance(el.get("options"), list):
            el["options"] = self._options(el["options"])
        if kind in CONTAINER_KINDS:
            el["elements"] = [self._prepare(child, taken) for child in el.get("elements") or []]
        return el

    # -- running a tool ----------------------------------------------------------------

    def _commit(self, candidate: dict[str, Any]) -> None:
        try:
            self.schema = Form.model_validate(candidate).dump()
        except ValidationError as exc:
            raise ToolFailure(f"The form would not be valid: {format_validation(exc)}") from exc

    def run(self, name: str, arguments: dict[str, Any]) -> StepResult:
        model = TOOLS.get(name)
        if model is None or (name in IMPORT_ONLY and not self.importing):
            return StepResult(False, {"error": f"Unknown tool '{name}'."}, error="unknown tool")
        try:
            args = model.model_validate(arguments)
        except ValidationError as exc:
            message = f"Invalid arguments: {format_validation(exc)}"
            return StepResult(False, {"error": message}, action=name, error=message)
        handler = getattr(self, f"_tool_{name}")
        try:
            out: StepResult = handler(args)
        except ToolFailure as exc:
            return StepResult(
                False, {"error": exc.message, **exc.extra}, action=name, error=exc.message
            )
        return out

    # -- tools ---------------------------------------------------------------------------

    def _tool_get_form(self, args: GetForm) -> StepResult:
        return StepResult(True, {"form": self.schema}, action="Read the form")

    def _tool_update_settings(self, args: UpdateSettings) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        settings = candidate["settings"]
        for key in args.model_fields_set:
            camel = to_camel(key)
            value = getattr(args, key)
            if value is None:
                if camel == "title":
                    raise ToolFailure("The form needs a title.")
                settings.pop(camel, None)
            else:
                settings[camel] = value
        self._commit(candidate)
        return StepResult(
            True, {"ok": True}, action="Changed", label="Form title and settings", changed=True
        )

    def _tool_add_page(self, args: AddPage) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        pages = candidate["pages"]
        position = len(pages)
        if args.after_page_id is not None:
            position = self._page_index(candidate, args.after_page_id) + 1
        page_id = unique_id(f"page_{len(pages) + 1}", self._ids())
        page: dict[str, Any] = {"id": page_id, "elements": []}
        if args.title:
            page["title"] = args.title
        if args.description:
            page["description"] = args.description
        pages.insert(position, page)
        self._commit(candidate)
        return StepResult(
            True,
            {"pageId": page_id},
            action="Added page",
            label=args.title or f"Page {position + 1}",
            target_id=page_id,
            changed=True,
        )

    def _tool_update_page(self, args: UpdatePage) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        page = candidate["pages"][self._page_index(candidate, args.page_id)]
        for key in args.model_fields_set - {"page_id"}:
            value = getattr(args, key)
            if value is None:
                page.pop(key, None)
            else:
                page[key] = value
        self._commit(candidate)
        return StepResult(
            True,
            {"ok": True},
            action="Changed page",
            label=page_label(self.schema, args.page_id),
            target_id=args.page_id,
            changed=True,
        )

    def _tool_remove_page(self, args: RemovePage) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        index = self._page_index(candidate, args.page_id)
        if len(candidate["pages"]) == 1:
            raise ToolFailure("A form needs at least one page.")
        label = page_label(candidate, args.page_id)
        page = candidate["pages"][index]
        elements = page.get("elements") or []
        if elements:
            if not args.move_elements_to:
                raise ToolFailure(
                    f"Page '{args.page_id}' has {len(elements)} element(s). Pass "
                    "moveElementsTo with another page id, or remove them first."
                )
            target = candidate["pages"][self._page_index(candidate, args.move_elements_to)]
            if target is page:
                raise ToolFailure("moveElementsTo must be a different page.")
            target.setdefault("elements", []).extend(elements)
        candidate["pages"].pop(index)
        self._commit(candidate)
        return StepResult(True, {"ok": True}, action="Removed page", label=label, changed=True)

    def _tool_add_field(self, args: AddField) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        container = self._container(candidate, args.parent_id)
        element = self._prepare(args.field, self._ids())
        index = len(container) if args.index is None else min(args.index, len(container))
        container.insert(index, element)
        self._commit(candidate)
        return StepResult(
            True,
            {"id": element["id"]},
            action="Added",
            label=element_label(element),
            target_id=element["id"],
            changed=True,
        )

    def _tool_update_field(self, args: UpdateField) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        loc = self._locate(candidate, args.id)
        changes = _camel_keys(args.changes)
        locked = sorted(LOCKED_KEYS & changes.keys())
        if locked:
            raise ToolFailure(
                f"These can't be changed with update_field: {', '.join(locked)}. "
                "Use move_field to move elements, or remove and add them again."
            )
        if not changes:
            raise ToolFailure("Pass at least one change.")
        for key, value in changes.items():
            if value is None:
                loc.element.pop(key, None)
            elif key == "options" and isinstance(value, list):
                loc.element[key] = self._options(value)
            else:
                loc.element[key] = value
        self._commit(candidate)
        return StepResult(
            True,
            {"ok": True},
            action="Changed",
            label=element_label(loc.element),
            target_id=args.id,
            changed=True,
        )

    def _tool_remove_field(self, args: RemoveField) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        loc = self._locate(candidate, args.id)
        refs = self.references_to(candidate, args.id)
        if refs:
            raise ToolFailure(
                f"Other logic refers to '{args.id}'. Change or remove those rules first.",
                referencedBy=refs,
            )
        label = element_label(loc.element)
        loc.siblings.pop(loc.index)
        self._commit(candidate)
        return StepResult(True, {"ok": True}, action="Removed", label=label, changed=True)

    def _tool_move_field(self, args: MoveField) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        loc = self._locate(candidate, args.id)
        if loc.element.get("kind") in CONTAINER_KINDS:
            inner = {
                sub.element["id"]
                for sub in iter_elements(loc.element.get("elements", []), 0, args.id)
            }
            if args.parent_id == args.id or args.parent_id in inner:
                raise ToolFailure("An element can't be moved inside itself.")
        element = loc.siblings.pop(loc.index)
        container = self._container(candidate, args.parent_id)
        index = len(container) if args.index is None else min(args.index, len(container))
        container.insert(index, element)
        self._commit(candidate)
        return StepResult(
            True,
            {"ok": True},
            action="Moved",
            label=element_label(element),
            target_id=args.id,
            changed=True,
        )

    def _tool_set_options(self, args: SetOptions) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        loc = self._locate(candidate, args.id)
        if loc.element.get("type") not in ("single_choice", "multi_choice"):
            raise ToolFailure(f"'{args.id}' is not a choice question.")
        loc.element["options"] = self._options(list(args.options))
        self._commit(candidate)
        return StepResult(
            True,
            {"ok": True, "options": loc.element["options"]},
            action="Changed options of",
            label=element_label(loc.element),
            target_id=args.id,
            changed=True,
        )

    def _tool_set_logic(self, args: SetLogic) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        page = next((p for p in candidate["pages"] if p["id"] == args.target_id), None)
        target: dict[str, Any]
        if page is not None:
            if args.kind == "requiredIf":
                raise ToolFailure("Pages can only have visibleIf.")
            target, label = page, page_label(candidate, args.target_id)
        else:
            target = self._locate(candidate, args.target_id).element
            if args.kind == "requiredIf" and target.get("kind") != "field":
                raise ToolFailure("Only questions can have requiredIf.")
            label = element_label(target)
        if args.condition is None:
            target.pop(args.kind, None)
        else:
            target[args.kind] = args.condition
        self._commit(candidate)
        action = "Changed when it shows:" if args.kind == "visibleIf" else "Changed when required:"
        return StepResult(
            True, {"ok": True}, action=action, label=label, target_id=args.target_id, changed=True
        )

    def _tool_set_page_navigation(self, args: SetPageNavigation) -> StepResult:
        candidate = copy.deepcopy(self.schema)
        page = candidate["pages"][self._page_index(candidate, args.page_id)]
        if args.rules:
            page["next"] = [{"if": r.if_, "goto": r.goto} for r in args.rules]
        else:
            page.pop("next", None)
        self._commit(candidate)
        return StepResult(
            True,
            {"ok": True},
            action="Changed where respondents go after",
            label=page_label(candidate, args.page_id),
            target_id=args.page_id,
            changed=True,
        )

    def _tool_flag_uncertain(self, args: FlagUncertain) -> StepResult:
        if args.target_id not in self._ids():
            raise ToolFailure(f"There is no element or page with id '{args.target_id}'.")
        self.flags = [f for f in self.flags if f["targetId"] != args.target_id]
        self.flags.append({"targetId": args.target_id, "note": args.note})
        try:
            label = element_label(self._locate(self.schema, args.target_id).element)
        except ToolFailure:
            label = page_label(self.schema, args.target_id)
        return StepResult(
            True, {"ok": True}, action="Flagged", label=label, target_id=args.target_id
        )

    def _tool_report_filled_in(self, args: ReportFilledIn) -> StepResult:
        self.filled_in = args.note
        return StepResult(True, {"ok": True, "stop": True}, action="Stopped: filled-in form")


def compact(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
