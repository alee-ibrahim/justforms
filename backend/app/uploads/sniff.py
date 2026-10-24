"""Magic-byte sniffing for uploaded files (DESIGN section 10).

Pure Python and deliberately small: it recognises the formats people attach to forms
(PDF, common images, Office/OpenDocument containers, plain text) and answers two questions:
what is this file really, and is that consistent with the name/type it was uploaded as and
with the question's ``accept`` list. Anything it cannot identify is "unknown binary".
"""

from __future__ import annotations

from dataclasses import dataclass

SNIFF_BYTES = 4096


@dataclass(frozen=True)
class Kind:
    """A family of files that share a signature."""

    mime: str  # canonical type stored for the file
    mimes: frozenset[str]  # declared types consistent with this signature
    exts: frozenset[str]  # extensions consistent with this signature


def _k(mime: str, mimes: set[str], exts: set[str]) -> Kind:
    return Kind(mime, frozenset(mimes | {mime}), frozenset(exts))


PDF = _k("application/pdf", {"application/x-pdf"}, {".pdf"})
PNG = _k("image/png", set(), {".png"})
JPEG = _k("image/jpeg", {"image/pjpeg", "image/jpg"}, {".jpg", ".jpeg", ".jfif", ".jpe"})
GIF = _k("image/gif", set(), {".gif"})
WEBP = _k("image/webp", set(), {".webp"})
HEIC = _k(
    "image/heic", {"image/heif", "image/heic-sequence", "image/heif-sequence"}, {".heic", ".heif"}
)
TIFF = _k("image/tiff", set(), {".tif", ".tiff"})
BMP = _k("image/bmp", {"image/x-ms-bmp"}, {".bmp"})
MP4 = _k(
    "video/mp4", {"video/quicktime", "audio/mp4", "video/3gpp"}, {".mp4", ".mov", ".m4a", ".3gp"}
)
WEBM = _k("video/webm", {"audio/webm", "video/x-matroska"}, {".webm", ".mkv"})
MP3 = _k("audio/mpeg", {"audio/mp3"}, {".mp3"})
ZIP = _k(
    "application/zip",
    {
        "application/x-zip-compressed",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/epub+zip",
    },
    {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub"},
)
OLE = _k(
    "application/x-ole-storage",
    {
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-outlook",
    },
    {".doc", ".xls", ".ppt", ".msg"},
)
TEXT = _k(
    "text/plain",
    {
        "text/csv",
        "application/csv",
        "text/tab-separated-values",
        "text/markdown",
        "application/json",
    },
    {".txt", ".csv", ".tsv", ".md", ".json"},
)

# Office containers keep their specific type when the declared one is consistent.
_KEEP_DECLARED = {ZIP.mime, OLE.mime, TEXT.mime, MP4.mime, WEBM.mime}


def detect(head: bytes) -> Kind | None:
    """The file family from its first bytes, or ``None`` for unknown binary data."""
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return GIF
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return HEIC
        return MP4
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return TIFF
    if head[:2] == b"BM" and len(head) >= 14:
        return BMP
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return WEBM
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return MP3
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return ZIP
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return OLE
    if _is_text(head):
        return TEXT
    return None


def _is_text(head: bytes) -> bool:
    if not head or b"\x00" in head:
        return False
    sample = head.lstrip(b"\xef\xbb\xbf")
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character may be cut at the end of the sniffed window.
        if exc.start < len(sample) - 4:
            return False
    # Markup is not "plain text": SVG and HTML can carry script.
    lowered = sample[:512].lstrip().lower()
    return not lowered.startswith((b"<svg", b"<?xml", b"<!doctype", b"<html", b"<script"))


def extension(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def accepts(accept: list[str], name: str, mime: str) -> bool:
    """The question's ``accept`` list (``.pdf``, ``image/*``, ``application/pdf``) allows
    a file with this name and declared type. An empty list allows everything."""
    if not accept:
        return True
    ext = extension(name)
    mime = mime.lower()
    for entry in (a.strip().lower() for a in accept):
        if entry.startswith("."):
            if ext == entry:
                return True
        elif entry.endswith("/*"):
            if mime.startswith(entry[:-1]):
                return True
        elif mime == entry:
            return True
    return False


def consistent(kind: Kind, name: str, mime: str) -> bool:
    """The sniffed family agrees with the declared type or the file name."""
    return mime.lower() in kind.mimes or extension(name) in kind.exts


def checked_type(head: bytes, name: str, mime: str, accept: list[str]) -> str | None:
    """The type to store for an upload, or ``None`` when the bytes contradict its name/type
    or the question does not accept it."""
    kind = detect(head)
    if kind is None:
        # Unknown binary is only allowed when the question takes any file.
        return (mime or "application/octet-stream") if not accept else None
    if not consistent(kind, name, mime):
        return None
    stored = (
        mime.lower() if kind.mime in _KEEP_DECLARED and mime.lower() in kind.mimes else kind.mime
    )
    if not accept:
        return stored
    # The accept list is checked against what the file really is, not just its label.
    return stored if accepts(accept, name, stored) or accepts(accept, name, kind.mime) else None
