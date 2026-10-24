"""Text helpers: rich text to JustForms' Markdown subset, ids, option values, Thaana detection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.importers.dom import HIDDEN_TEXT, Node, clean_space, parse_html

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_BLOCK = frozenset(
    {"p", "div", "ul", "ol", "li", "table", "tr", "blockquote", "section", *HEADINGS}
)
_SAFE_HREF = re.compile(r"^(https?:|mailto:|tel:)", re.I)


def _inline(node: Node | str) -> str:
    if isinstance(node, str):
        return node
    if node.tag in HIDDEN_TEXT:
        return ""
    if node.tag == "br":
        return "\n"
    inner = "".join(_inline(c) for c in node.children)
    if node.tag in ("b", "strong") and inner.strip():
        return f"**{inner.strip()}** "
    if node.tag in ("i", "em") and inner.strip():
        return f"_{inner.strip()}_ "
    if node.tag == "a":
        href = node.get("href").strip()
        label = clean_space(inner)
        if label and _SAFE_HREF.match(href) and " " not in href:
            return f"[{label}]({href})"
        return inner
    return inner


def _blocks(node: Node, out: list[str]) -> None:
    """Append Markdown blocks for ``node``'s children; inline runs become paragraphs."""
    run: list[Node | str] = []

    def flush() -> None:
        text = "".join(_inline(c) for c in run)
        lines = [clean_space(line) for line in text.split("\n")]
        joined = "\n".join(line for line in lines if line)
        if joined:
            out.append(joined)
        run.clear()

    for child in node.children:
        if isinstance(child, Node) and child.tag in ("ul", "ol"):
            flush()
            items = [
                "- " + clean_space("".join(_inline(c) for c in li.children))
                for li in child.children
                if isinstance(li, Node) and li.tag == "li"
            ]
            items = [i for i in items if i.strip() != "-"]
            if items:
                out.append("\n".join(items))
        elif isinstance(child, Node) and child.tag in _BLOCK:
            flush()
            _blocks(child, out)
        else:
            run.append(child)
    flush()


def to_markdown(node: Node) -> str:
    """Rich text reduced to the renderer's Markdown: bold, italic, links, "- " lists and
    paragraphs. Colours, fonts, sizes and images are dropped."""
    out: list[str] = []
    _blocks(node, out)
    text = "\n\n".join(out)
    text = re.sub(r"\*\*\s*\*\*", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r" {2,}", " ", text).strip()


def html_to_markdown(html: str) -> str:
    return to_markdown(parse_html(html))


def single_heading(node: Node) -> str | None:
    """The text when a rich-text block is just one short heading (shown as a heading)."""
    elements = [c for c in node.children if isinstance(c, Node)]
    stray = "".join(c for c in node.children if isinstance(c, str)).strip()
    if len(elements) != 1 or stray or elements[0].tag not in HEADINGS:
        return None
    text = elements[0].text()
    return text if 0 < len(text) <= 150 else None


# -- ids and values ------------------------------------------------------------------------

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake(text: str, *, limit: int = 40) -> str:
    """``csoName`` / ``CSO Name`` -> ``cso_name``; Latin letters and digits only."""
    text = unicodedata.normalize("NFKD", text)
    text = _CAMEL.sub("_", text)
    text = "".join(ch for ch in text if ord(ch) < 128)
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    slug = slug[:limit].rstrip("_")
    if slug and not slug[0].isalpha():
        slug = f"q_{slug}"[:limit].rstrip("_")
    return slug


class IdPool:
    """Unique element ids for one form (``^[a-z][a-z0-9_]{0,62}$``)."""

    def __init__(self) -> None:
        self.used: set[str] = set()
        self.counters: dict[str, int] = {}

    def take(self, base: str, fallback_prefix: str) -> str:
        """``base`` in snake case (``_2``, ``_3`` on clashes), or ``{prefix}_N`` when the base
        has no Latin letters (Thaana labels)."""
        base = snake(base)
        if not base:
            return self.numbered(fallback_prefix)
        if base not in self.used:
            self.used.add(base)
            return base
        n = 2
        while f"{base}_{n}" in self.used:
            n += 1
        self.used.add(f"{base}_{n}")
        return f"{base}_{n}"

    def numbered(self, prefix: str) -> str:
        n = self.counters.get(prefix, 0)
        while True:
            n += 1
            candidate = f"{prefix}_{n}"
            if candidate not in self.used:
                self.counters[prefix] = n
                self.used.add(candidate)
                return candidate


def option_values(labels: list[str]) -> list[str]:
    """Stable, unique option values from labels (snake case, or ``option_N`` for Thaana)."""
    out: list[str] = []
    seen: set[str] = set()
    for i, label in enumerate(labels, start=1):
        value = snake(label, limit=60) or f"option_{i}"
        base, n = value, 2
        while value in seen:
            value = f"{base}_{n}"
            n += 1
        seen.add(value)
        out.append(value)
    return out


# -- language ------------------------------------------------------------------------------

THAANA = re.compile(r"[\u0780-\u07bf]")
LATIN = re.compile(r"[A-Za-z]")


@dataclass
class ScriptCount:
    thaana: int = 0
    latin: int = 0

    def add(self, text: str) -> None:
        self.thaana += len(THAANA.findall(text))
        self.latin += len(LATIN.findall(text))

    @property
    def language(self) -> str:
        """``dv`` when most letters are Thaana."""
        return "dv" if self.thaana > self.latin else "en"
