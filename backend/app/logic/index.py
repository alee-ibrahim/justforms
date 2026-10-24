"""A flat index over a form's pages and elements, shared by the rule checks and the engine."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.schemas.form import (
    Condition,
    ContentElement,
    FieldCondition,
    Form,
    Page,
    RepeaterElement,
    SectionElement,
)

type AnyElement = BaseModel  # field / content / section / repeater model


def page_node(page_id: str) -> str:
    """Graph node name for "page is on the navigation path" (ids never contain ':')."""
    return f"page:{page_id}"


@dataclass
class ElementInfo:
    id: str
    element: AnyElement
    kind: str  # field | content | section | repeater
    type: str | None  # field type for kind == field
    page_index: int
    parent_id: str | None  # enclosing section/repeater id, None when directly on the page
    repeater_id: str | None  # enclosing repeater id (scope for conditions)
    section_depth: int  # number of enclosing sections
    children: list[str] = field(default_factory=list)

    @property
    def produces_value(self) -> bool:
        return self.kind in ("field", "repeater")


@dataclass
class FormIndex:
    form: Form
    pages: list[Page]
    page_index: dict[str, int]
    elements: dict[str, ElementInfo]  # in document order
    duplicates: list[str]
    top_level: list[str]  # ids of elements outside repeaters, document order

    @classmethod
    def build(cls, form: Form) -> FormIndex:
        elements: dict[str, ElementInfo] = {}
        duplicates: list[str] = []
        page_index: dict[str, int] = {}
        seen: set[str] = set()

        for i, page in enumerate(form.pages):
            if page.id in seen:
                duplicates.append(page.id)
            seen.add(page.id)
            page_index.setdefault(page.id, i)

        def walk(
            items: Sequence[AnyElement],
            page_i: int,
            parent: str | None,
            repeater: str | None,
            depth: int,
        ) -> None:
            for el in items:
                el_id: str = el.id  # type: ignore[attr-defined]
                if el_id in seen:
                    duplicates.append(el_id)
                    continue
                seen.add(el_id)
                kind: str = el.kind  # type: ignore[attr-defined]
                info = ElementInfo(
                    id=el_id,
                    element=el,
                    kind=kind,
                    type=getattr(el, "type", None) if kind == "field" else None,
                    page_index=page_i,
                    parent_id=parent,
                    repeater_id=repeater,
                    section_depth=depth,
                )
                elements[el_id] = info
                if parent is not None:
                    elements[parent].children.append(el_id)
                if isinstance(el, SectionElement):
                    walk(el.elements, page_i, el_id, repeater, depth + 1)
                elif isinstance(el, RepeaterElement):
                    walk(el.elements, page_i, el_id, el_id, depth)

        for i, page in enumerate(form.pages):
            walk(page.elements, i, None, None, 0)

        top_level = [e.id for e in elements.values() if e.repeater_id is None]
        return cls(
            form=form,
            pages=form.pages,
            page_index=page_index,
            elements=elements,
            duplicates=duplicates,
            top_level=top_level,
        )

    def page_children(self, page_i: int) -> list[str]:
        return [
            e.id for e in self.elements.values() if e.page_index == page_i and e.parent_id is None
        ]


def iter_leaves(cond: Condition | None) -> Iterator[FieldCondition]:
    """All leaf conditions in a condition tree."""
    if cond is None:
        return
    stack = [cond.root]
    while stack:
        node = stack.pop()
        if isinstance(node, FieldCondition):
            yield node
        elif hasattr(node, "all_"):
            stack.extend(c.root for c in node.all_)
        elif hasattr(node, "any_"):
            stack.extend(c.root for c in node.any_)
        else:
            stack.append(node.not_.root)


def element_conditions(el: AnyElement) -> tuple[Condition | None, Condition | None]:
    """(visibleIf, requiredIf) of an element; requiredIf is None for non-fields."""
    visible_if = getattr(el, "visible_if", None)
    required_if = getattr(el, "required_if", None)
    if isinstance(el, ContentElement | SectionElement | RepeaterElement):
        required_if = None
    return visible_if, required_if
