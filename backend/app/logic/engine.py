"""The JustForms rule engine (DESIGN section 5). Python twin of ``frontend/src/logic/engine.ts``.

Both implementations must agree exactly; ``spec/logic/vectors/*.json`` is the shared
conformance suite. Any behaviour change here needs the same change in TypeScript plus a
new vector.

``evaluate(form, answers)`` returns which elements are visible, which fields are
required, the page path, per-row results for repeaters, and the answers with every key
the respondent could not see stripped out.

Algorithm: visibility is memoised recursion over the (acyclic, see ``graph.py``)
dependency graph. An element is visible when its container is visible (its page being on
the navigation path, for top-level elements) and its own ``visibleIf`` holds against the
*effective* answers, where any hidden field reads as missing. The navigation path is
built lazily, page by page, as visibility needs it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.logic.index import FormIndex, element_conditions
from app.schemas.form import (
    AllCondition,
    AnyCondition,
    Condition,
    FieldCondition,
    Form,
    NotCondition,
    Op,
)

# ASCII digits only and full-string matches, exactly like the TypeScript engine's regexes
# (Python's \d would accept other scripts' digits and $ would accept a trailing newline).
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TIME_RE = re.compile(r"[0-9]{2}:[0-9]{2}")


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


class LogicCycleError(RuntimeError):
    """Raised if evaluation hits a dependency cycle (validated forms never do)."""


# --------------------------------------------------------------------------------------
# Operators (section 5.2)
# --------------------------------------------------------------------------------------


def is_missing(value: Any) -> bool:
    return (
        value is MISSING
        or value is None
        or (isinstance(value, str) and value == "")
        or (isinstance(value, list) and len(value) == 0)
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def json_equal(a: Any, b: Any) -> bool:
    """Deep JSON equality without coercion; strings compared after NFC normalisation."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return bool(a == b)
    if isinstance(a, str) and isinstance(b, str):
        return _nfc(a) == _nfc(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return a is None and b is None


def _compare(a: Any, b: Any) -> int | None:
    """-1/0/1 for comparable pairs (numbers, two dates, two times), else None."""
    if _is_number(a) and _is_number(b):
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        a, b = _nfc(a), _nfc(b)
        if (DATE_RE.fullmatch(a) and DATE_RE.fullmatch(b)) or (
            TIME_RE.fullmatch(a) and TIME_RE.fullmatch(b)
        ):
            return (a > b) - (a < b)
    return None


_NEGATIONS = {Op.NEQ: Op.EQ, Op.NOT_IN: Op.IN, Op.NOT_CONTAINS: Op.CONTAINS}


def apply_op(op: Op, value: Any, target: Any) -> bool:
    """Apply ``op`` to a field's effective ``value`` and the condition's ``target``."""
    if op is Op.EMPTY:
        return is_missing(value)
    if op is Op.NOT_EMPTY:
        return not is_missing(value)
    if op in _NEGATIONS:
        return not apply_op(_NEGATIONS[op], value, target)
    if is_missing(value):
        return False
    match op:
        case Op.EQ:
            return json_equal(value, target)
        case Op.GT | Op.GTE | Op.LT | Op.LTE:
            c = _compare(value, target)
            if c is None:
                return False
            return {Op.GT: c > 0, Op.GTE: c >= 0, Op.LT: c < 0, Op.LTE: c <= 0}[op]
        case Op.IN:
            if not isinstance(target, list) or isinstance(value, list | dict):
                return False
            return any(json_equal(value, t) for t in target)
        case Op.CONTAINS:
            if isinstance(value, list):
                return any(json_equal(v, target) for v in value)
            if isinstance(value, str) and isinstance(target, str):
                return _nfc(target) in _nfc(value)
            return False
        case Op.COUNT_EQ | Op.COUNT_GTE | Op.COUNT_LTE:
            if not isinstance(value, list) or not _is_number(target):
                return False
            n = len(value)
            return {Op.COUNT_EQ: n == target, Op.COUNT_GTE: n >= target, Op.COUNT_LTE: n <= target}[
                op
            ]
    return False  # pragma: no cover - every op is handled above


# --------------------------------------------------------------------------------------
# Evaluation (section 5.4)
# --------------------------------------------------------------------------------------


@dataclass
class RowResult:
    visible: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    visible: list[str]
    hidden: list[str]
    required: list[str]
    path: list[str]
    rows: dict[str, list[RowResult]]
    stripped_answers: dict[str, Any]


type RowRef = tuple[str, int] | None  # (repeater id, row index)


class _Evaluator:
    def __init__(self, form: Form, answers: dict[str, Any]) -> None:
        self.index = FormIndex.build(form)
        self.answers = answers if isinstance(answers, dict) else {}
        self.vis: dict[str, bool] = {}
        self.row_vis: dict[tuple[str, int], bool] = {}
        self.in_progress: set[Any] = set()
        # Navigation state: pages on the path, and the highest page index whose
        # membership is decided.
        self.path: list[int] = []
        self.on_path_set: set[int] = set()
        self.frontier = -1
        self.started = False
        self.done = False
        self.stepping = False

    # -- answers -----------------------------------------------------------------------

    def rows_of(self, repeater_id: str) -> list[dict[str, Any]]:
        raw = self.answers.get(repeater_id)
        if not isinstance(raw, list):
            return []
        return [r if isinstance(r, dict) else {} for r in raw]

    def value(self, field_id: str, row: RowRef) -> Any:
        info = self.index.elements[field_id]
        if info.repeater_id is not None:
            if row is None or row[0] != info.repeater_id:
                return MISSING  # out of scope; rejected by validation
            rep, i = row
            if not self.visible_in_row(field_id, rep, i):
                return MISSING
            return self.rows_of(rep)[i].get(field_id, MISSING)
        if not self.visible(field_id):
            return MISSING
        return self.answers.get(field_id, MISSING)

    def cond(self, cond: Condition | None, row: RowRef) -> bool:
        if cond is None:
            return True
        node = cond.root
        if isinstance(node, FieldCondition):
            return apply_op(node.op, self.value(node.field, row), node.value)
        if isinstance(node, AllCondition):
            return all(self.cond(c, row) for c in node.all_)
        if isinstance(node, AnyCondition):
            return any(self.cond(c, row) for c in node.any_)
        if isinstance(node, NotCondition):
            return not self.cond(node.not_, row)
        raise TypeError(node)  # pragma: no cover

    # -- navigation --------------------------------------------------------------------

    def on_path(self, page_i: int) -> bool:
        while page_i > self.frontier and not self.done:
            if self.stepping:
                raise LogicCycleError(f"page {self.index.pages[page_i].id} depends on itself")
            self.step()
        return page_i in self.on_path_set

    def _first_visible_from(self, start: int) -> int | None:
        for k in range(start, len(self.index.pages)):
            self.frontier = k - 1
            if self.cond(self.index.pages[k].visible_if, None):
                return k
        return None

    def step(self) -> None:
        self.stepping = True
        try:
            if not self.started:
                self.started = True
                nxt = self._first_visible_from(0)
            else:
                j = self.path[-1]
                goto: str | None = None
                for rule in self.index.pages[j].next:
                    if self.cond(rule.if_, None):
                        goto = rule.goto
                        break
                if goto == "submit":
                    nxt = None
                else:
                    start = self.index.page_index[goto] if goto is not None else j + 1
                    nxt = self._first_visible_from(start)
            if nxt is None:
                self.done = True
                self.frontier = len(self.index.pages) - 1
            else:
                self.path.append(nxt)
                self.on_path_set.add(nxt)
                self.frontier = nxt
        finally:
            self.stepping = False

    # -- visibility --------------------------------------------------------------------

    def visible(self, element_id: str) -> bool:
        if element_id in self.vis:
            return self.vis[element_id]
        if element_id in self.in_progress:
            raise LogicCycleError(f"'{element_id}' depends on itself")
        self.in_progress.add(element_id)
        info = self.index.elements[element_id]
        if info.parent_id is not None:
            ok = self.visible(info.parent_id)
        else:
            ok = self.on_path(info.page_index)
        if ok:
            ok = self.cond(element_conditions(info.element)[0], None)
        self.in_progress.discard(element_id)
        self.vis[element_id] = ok
        return ok

    def visible_in_row(self, element_id: str, repeater_id: str, i: int) -> bool:
        key = (element_id, i)
        if key in self.row_vis:
            return self.row_vis[key]
        if key in self.in_progress:
            raise LogicCycleError(f"'{element_id}' (row {i}) depends on itself")
        self.in_progress.add(key)
        info = self.index.elements[element_id]
        parent = info.parent_id
        assert parent is not None
        if parent == repeater_id:
            ok = self.visible(repeater_id) and i < len(self.rows_of(repeater_id))
        else:
            ok = self.visible_in_row(parent, repeater_id, i)
        if ok:
            ok = self.cond(element_conditions(info.element)[0], (repeater_id, i))
        self.in_progress.discard(key)
        self.row_vis[key] = ok
        return ok

    def required(self, element_id: str, row: RowRef) -> bool:
        info = self.index.elements[element_id]
        if info.kind != "field":
            return False
        el: Any = info.element
        return bool(el.required) or (el.required_if is not None and self.cond(el.required_if, row))

    # -- result ------------------------------------------------------------------------

    def descendants_in_repeater(self, repeater_id: str) -> list[str]:
        return [e.id for e in self.index.elements.values() if e.repeater_id == repeater_id]

    def run(self) -> Evaluation:
        visible: list[str] = []
        hidden: list[str] = []
        required: list[str] = []
        rows: dict[str, list[RowResult]] = {}
        stripped: dict[str, Any] = {}

        for el_id in self.index.top_level:
            if self.visible(el_id):
                visible.append(el_id)
                if self.required(el_id, None):
                    required.append(el_id)
            else:
                hidden.append(el_id)

        # Finish navigation so the path is complete even if nothing on later pages
        # was asked about.
        while not self.done:
            self.step()

        for el_id in visible:
            info = self.index.elements[el_id]
            if info.kind == "field":
                if el_id in self.answers:
                    stripped[el_id] = self.answers[el_id]
            elif info.kind == "repeater":
                children = self.descendants_in_repeater(el_id)
                results: list[RowResult] = []
                stripped_rows: list[dict[str, Any]] = []
                for i, row_data in enumerate(self.rows_of(el_id)):
                    res = RowResult()
                    kept: dict[str, Any] = {}
                    for child in children:
                        if self.visible_in_row(child, el_id, i):
                            res.visible.append(child)
                            if self.required(child, (el_id, i)):
                                res.required.append(child)
                            child_info = self.index.elements[child]
                            if child_info.kind == "field" and child in row_data:
                                kept[child] = row_data[child]
                        else:
                            res.hidden.append(child)
                    results.append(res)
                    stripped_rows.append(kept)
                rows[el_id] = results
                if el_id in self.answers:
                    raw = self.answers[el_id]
                    stripped[el_id] = stripped_rows if isinstance(raw, list) else raw

        return Evaluation(
            visible=visible,
            hidden=hidden,
            required=required,
            path=[self.index.pages[i].id for i in self.path],
            rows=rows,
            stripped_answers=stripped,
        )


def evaluate(form: Form, answers: dict[str, Any]) -> Evaluation:
    return _Evaluator(form, answers).run()
