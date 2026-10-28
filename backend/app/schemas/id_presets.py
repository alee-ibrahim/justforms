"""Identity-number presets for the "ID number" question (``short_text`` with ``idPreset``).

The presets are data (``id_presets.json``), not code: a country is added by adding an entry
there. The file is exported to ``spec/id-presets.v1.json`` and copied into the frontend, so the
renderer and the server apply the same pattern and normalising (``app.validation.answers`` and
``frontend/src/renderer/id-presets.ts``).

``idPreset: "custom"`` keeps the question's own pattern, placeholder and message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

PRESETS_PATH = Path(__file__).with_name("id_presets.json")
CUSTOM = "custom"
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class IdPreset:
    id: str
    label: str
    example: str
    pattern: str
    placeholder: str
    message: str
    max_length: int
    uppercase: bool
    strip_spaces: bool
    sensitive: bool


def presets_document() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    return data


@cache
def presets() -> dict[str, IdPreset]:
    out: dict[str, IdPreset] = {}
    for p in presets_document()["presets"]:
        out[p["id"]] = IdPreset(
            id=p["id"],
            label=p["label"],
            example=p["example"],
            pattern=p["pattern"],
            placeholder=p["placeholder"],
            message=p["message"],
            max_length=int(p["maxLength"]),
            uppercase=bool(p.get("uppercase", False)),
            strip_spaces=bool(p.get("stripSpaces", False)),
            sensitive=bool(p.get("sensitive", False)),
        )
    return out


def get_preset(preset_id: str | None) -> IdPreset | None:
    """The preset, or ``None`` for no preset, ``custom`` and unknown ids."""
    if not preset_id or preset_id == CUSTOM:
        return None
    return presets().get(preset_id)


def known(preset_id: str) -> bool:
    return preset_id == CUSTOM or preset_id in presets()


def normalize(preset: IdPreset | None, value: Any) -> Any:
    """Strip spaces and upper-case as the preset says; other values are returned unchanged."""
    if preset is None or not isinstance(value, str):
        return value
    if preset.strip_spaces:
        value = _SPACES.sub("", value)
    if preset.uppercase:
        value = value.upper()
    return value
