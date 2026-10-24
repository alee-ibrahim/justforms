"""A small, read-only HTML tree built with the standard library parser.

Imported HTML is untrusted: it is only tokenised here, never rendered or executed, and
``<script>`` content is kept as plain text (the Jotform importer reads a few calls out of it).
The builder tolerates sloppy markup: void elements never take children, and an end tag closes
the nearest matching open element or is ignored when none is open.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
# Elements whose text is never visible content.
HIDDEN_TEXT = frozenset({"script", "style", "template", "noscript", "title"})
MAX_DEPTH = 512


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = None

    # -- attributes ------------------------------------------------------------------------

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def has_class(self, name: str) -> bool:
        return name in self.classes

    # -- traversal -------------------------------------------------------------------------

    def elements(self) -> Iterator[Node]:
        """Descendant elements in document order (not including this node)."""
        stack: list[Node] = [c for c in reversed(self.children) if isinstance(c, Node)]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(c for c in reversed(node.children) if isinstance(c, Node))

    def find_all(self, pred: Callable[[Node], bool]) -> list[Node]:
        return [n for n in self.elements() if pred(n)]

    def find(self, pred: Callable[[Node], bool]) -> Node | None:
        return next((n for n in self.elements() if pred(n)), None)

    def by_tag(self, *tags: str) -> list[Node]:
        return self.find_all(lambda n: n.tag in tags)

    def ancestors(self) -> Iterator[Node]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    # -- text ------------------------------------------------------------------------------

    def raw_text(self) -> str:
        """All text below this node, including script content, unnormalised."""
        out: list[str] = []
        stack: list[Node | str] = list(reversed(self.children))
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                out.append(item)
            else:
                stack.extend(reversed(item.children))
        return "".join(out)

    def text(self, *, skip: Callable[[Node], bool] | None = None) -> str:
        """Visible text with whitespace collapsed. ``skip`` drops matching subtrees."""
        out: list[str] = []
        stack: list[Node | str] = list(reversed(self.children))
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                out.append(item)
            elif item.tag in HIDDEN_TEXT or (skip is not None and skip(item)):
                continue
            else:
                if item.tag == "br":
                    out.append(" ")
                stack.extend(reversed(item.children))
        return clean_space("".join(out))


_SPACE = re.compile(r"\s+")


def clean_space(text: str) -> str:
    """Collapse whitespace; no-break spaces and replacement characters count as spaces (a
    page saved with the wrong code page turns no-break spaces into U+FFFD)."""
    text = text.replace("\u00a0", " ").replace("\ufffd", " ").replace("\u200b", "")
    return _SPACE.sub(" ", text).strip()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parent = self.stack[-1]
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs}, parent=parent)
        parent.children.append(node)
        if tag not in VOID and len(self.stack) < MAX_DEPTH:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parent = self.stack[-1]
        parent.children.append(Node(tag, {k.lower(): (v or "") for k, v in attrs}, parent=parent))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(source: str) -> Node:
    builder = _Builder()
    builder.feed(source)
    builder.close()
    return builder.root
