"""Export the canonical form schema to ``spec/form-schema.v1.json``.

    uv run python -m app.schemas.export           # write the file
    uv run python -m app.schemas.export --check   # exit 1 if the file is stale (CI)

The frontend generates its TS types and zod schemas from that file (``pnpm gen:schema``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.schemas.form import Form

SPEC_PATH = Path(__file__).resolve().parents[3] / "spec" / "form-schema.v1.json"
SCHEMA_ID = "https://github.com/alee-ibrahim/justforms/blob/main/spec/form-schema.v1.json"


def build_json_schema() -> dict[str, Any]:
    schema = Form.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
        "description": (
            "JustForms form document, schemaVersion 1. GENERATED from backend/app/schemas/form.py; "
            "do not edit by hand. Cross-element rules (unique ids, logic references, cycles) "
            "are enforced by the backend and are not expressible here."
        ),
    }


def render() -> str:
    return json.dumps(build_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args(argv)
    content = render()
    if args.check:
        current = SPEC_PATH.read_text(encoding="utf-8") if SPEC_PATH.exists() else ""
        if current != content:
            print(
                f"{SPEC_PATH} is stale; run: uv run python -m app.schemas.export", file=sys.stderr
            )
            return 1
        return 0
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {SPEC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
