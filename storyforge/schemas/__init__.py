"""JSON Schemas for every LLM-produced document, plus validation helpers.

The schemas are defined in Python (so enums stay in sync with
:mod:`storyforge.models.constants`) and exported to ``storyforge/schemas/*.schema.json``
with ``python -m storyforge schemas export`` (a test checks the files are current).
Validation = JSON Schema (structure) + semantic checks (cross references), and both
kinds of errors are fed back to the LLM on retry.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from storyforge.schemas.definitions import ALL_SCHEMAS

SCHEMA_DIR = Path(__file__).resolve().parent


def get_schema(name: str) -> dict:
    return ALL_SCHEMAS[name]


def schema_errors(name: str, doc) -> list[str]:
    validator = Draft202012Validator(get_schema(name))
    errors = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: {err.message}")
    return errors


def export_schemas(target: Path = SCHEMA_DIR) -> list[Path]:
    written = []
    for name, schema in ALL_SCHEMAS.items():
        p = target / f"{name}.schema.json"
        p.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(p)
    return written


class ValidationFailed(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:12]))
        self.errors = errors
