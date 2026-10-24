"""Dependency graph of a form's visibility logic, and cycle detection (DESIGN section 5.3).

Nodes are element ids plus one ``page:<id>`` node per page ("page is on the path").
An edge ``a -> b`` means "evaluating a's visibility needs b first":

* element -> every field its ``visibleIf`` reads;
* element -> its enclosing section/repeater, or its page node when directly on a page;
* ``page:P`` -> fields read by the ``visibleIf`` of P and of every earlier page, and by the
  ``next`` rules of every earlier page (they decide whether navigation reaches P).

``requiredIf`` is not part of the graph: requiredness never feeds back into visibility.
A form is only valid when this graph is acyclic; the engine relies on that.
"""

from __future__ import annotations

from app.logic.index import FormIndex, element_conditions, iter_leaves, page_node


def build_graph(index: FormIndex) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}

    for info in index.elements.values():
        deps: list[str] = []
        if info.parent_id is not None:
            deps.append(info.parent_id)
        else:
            deps.append(page_node(index.pages[info.page_index].id))
        visible_if, _ = element_conditions(info.element)
        deps.extend(leaf.field for leaf in iter_leaves(visible_if))
        graph[info.id] = deps

    reads_before: list[str] = []  # fields read by navigation of pages before the current one
    for page in index.pages:
        own = [leaf.field for leaf in iter_leaves(page.visible_if)]
        graph[page_node(page.id)] = [*reads_before, *own]
        reads_before = [
            *reads_before,
            *own,
            *(leaf.field for rule in page.next for leaf in iter_leaves(rule.if_)),
        ]
    return graph


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as ``[a, b, ..., a]`` or ``None``. Unknown nodes are ignored."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(graph, white)

    for start in graph:
        if color[start] != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        color[start] = grey
        while stack:
            node, i = stack[-1]
            deps = graph[node]
            if i < len(deps):
                stack[-1] = (node, i + 1)
                nxt = deps[i]
                if nxt not in color:
                    continue
                if color[nxt] == grey:
                    return [*path[path.index(nxt) :], nxt]
                if color[nxt] == white:
                    color[nxt] = grey
                    stack.append((nxt, 0))
                    path.append(nxt)
            else:
                color[node] = black
                stack.pop()
                path.pop()
    return None
