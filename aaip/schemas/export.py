"""
aaip/schemas/export.py — True JSON Schema Export  v1.0.0

Generates proper JSON Schema (Draft 2020-12) from AEP dataclass models.

Features:
  - Full $defs references (no inline repetition)
  - Python type → JSON Schema type mapping
  - required fields correctly identified
  - Enum values inlined as "enum": [...]
  - Versioned schema with $id URL
  - Stable across releases (no runtime-dependent fields)

Run:
    python -m aaip.schemas.export               # export all
    python -m aaip.schemas.export --model PaymentRequest
    python -m aaip.schemas.export --out ./schemas/json/
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import sys
import types
from enum import Enum
from pathlib import Path
from typing import Any, get_type_hints, get_args, get_origin, Union

VERSION     = "1.0.0"
SCHEMA_BASE = "https://aep.protocol/schemas/v{version}/"

# ── Python type → JSON Schema type ────────────────────────────────────────────

def _py_type_to_schema(annotation: Any, defs: dict) -> dict:
    """
    Recursively convert a Python type annotation to a JSON Schema fragment.

    Handles: str, int, float, bool, None, list, dict, Optional,
             Union, Enum subclasses, and AEP dataclass types.
    """
    origin = get_origin(annotation)
    args   = get_args(annotation)

    # Optional[X] → {"oneOf": [schema(X), {"type": "null"}]}
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        has_none = type(None) in args
        if len(non_none) == 1:
            inner = _py_type_to_schema(non_none[0], defs)
            if has_none:
                return {"oneOf": [inner, {"type": "null"}]}
            return inner
        return {"oneOf": [_py_type_to_schema(a, defs) for a in args]}

    # list[X]
    if origin is list:
        items = _py_type_to_schema(args[0], defs) if args else {}
        return {"type": "array", "items": items}

    # dict[K, V]
    if origin is dict:
        return {"type": "object"}

    # Primitive scalars
    _PRIMITIVES = {str: "string", int: "integer", float: "number",
                   bool: "boolean", type(None): "null"}
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}

    # Enum → {"type": "string", "enum": [...]}
    if inspect.isclass(annotation) and issubclass(annotation, Enum):
        return {"type": "string", "enum": [e.value for e in annotation]}

    # AEP dataclass → $ref into $defs
    if inspect.isclass(annotation) and dataclasses.is_dataclass(annotation):
        name = annotation.__name__
        if name not in defs:
            defs[name] = {}           # placeholder to break recursion
            defs[name] = _dataclass_to_schema(annotation, defs)
        return {"$ref": f"#/$defs/{name}"}

    # String forward references
    if isinstance(annotation, str):
        return {"type": "string", "description": f"ref:{annotation}"}

    # Fallback
    return {}


def _dataclass_to_schema(cls: type, defs: dict) -> dict:
    """Build a JSON Schema object for a single dataclass."""
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = {f.name: f.type for f in dataclasses.fields(cls)}

    properties: dict[str, Any] = {}
    required:   list[str]      = []

    for field in dataclasses.fields(cls):
        annotation = hints.get(field.name, field.type)
        prop       = _py_type_to_schema(annotation, defs)

        # Add description from field metadata if present
        if field.metadata.get("description"):
            prop["description"] = field.metadata["description"]

        # Mark as required if no default and no default_factory
        no_default = field.default is dataclasses.MISSING
        no_factory = field.default_factory is dataclasses.MISSING  # type: ignore[misc]
        if no_default and no_factory:
            required.append(field.name)
        elif field.default is not dataclasses.MISSING:
            # Inline simple defaults
            try:
                prop["default"] = field.default
            except Exception:
                pass

        properties[field.name] = prop

    schema = {
        "type":       "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


# ── Top-level schema builder ──────────────────────────────────────────────────

def build_schema(cls: type, version: str = VERSION) -> dict[str, Any]:
    """
    Build a complete, self-contained JSON Schema for an AEP dataclass.

    The schema uses $defs for nested types so it is fully resolvable
    without external references.
    """
    defs: dict[str, Any] = {}
    root = _dataclass_to_schema(cls, defs)

    schema: dict[str, Any] = {
        "$schema":  "https://json-schema.org/draft/2020-12/schema",
        "$id":      f"{SCHEMA_BASE.format(version=version)}{cls.__name__.lower()}.json",
        "title":    cls.__name__,
        "version":  version,
        "description": (inspect.getdoc(cls) or "").split("\n")[0],
        **root,
    }
    if defs:
        schema["$defs"] = defs

    return schema


# ── All-model catalogue ───────────────────────────────────────────────────────

from aaip.schemas.models import (
    PaymentRequest, ExecutionReceipt, AgentWallet,
    AgentTask, UsageRecord, PoEReference, ValidationResult,
)

MODELS = {
    "payment_request":   PaymentRequest,
    "execution_receipt": ExecutionReceipt,
    "agent_wallet":      AgentWallet,
    "agent_task":        AgentTask,
    "usage_record":      UsageRecord,
    "poe_reference":     PoEReference,
    "validation_result": ValidationResult,
}


def export_all(out_dir: Path | str | None = None, version: str = VERSION) -> dict[str, Path]:
    """Export all AEP model schemas to JSON files."""
    out = Path(out_dir or Path(__file__).parent / "json")
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, cls in MODELS.items():
        schema = build_schema(cls, version=version)
        path   = out / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2))
        written[name] = path
    return written


def get_schema(model_name: str) -> dict[str, Any] | None:
    """Return built schema dict for a model name (case-insensitive)."""
    cls = MODELS.get(model_name.lower())
    return build_schema(cls) if cls else None


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export AEP JSON Schemas")
    parser.add_argument("--model", default=None, help="Export a single model")
    parser.add_argument("--out",   default="./schemas", help="Output directory")
    parser.add_argument("--list",  action="store_true", help="List available models")
    args = parser.parse_args()

    if args.list:
        for name in MODELS:
            print(f"  {name}")
        sys.exit(0)

    if args.model:
        schema = get_schema(args.model)
        if not schema:
            print(f"Unknown model: {args.model}. Use --list.", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(schema, indent=2))
        sys.exit(0)

    result = export_all(args.out)
    for name, path in result.items():
        print(f"  ✔  {name:<22} → {path}")
