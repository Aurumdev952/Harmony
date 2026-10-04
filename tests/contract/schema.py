"""Shape-only JSON Schema for API contract recordings.

A recording keeps the JSON Schema of a body, never its values, so fixtures
cannot carry PII or secrets (SPEC INV-6). Two things would still leak through
a naive schema, and both are handled here:

* object keys that are data (user emails, ids, dates, dimension values) are
  collapsed into ``additionalProperties`` instead of being listed by name;
* string values are reduced to a coarse ``x-format`` tag (``date-time``,
  ``http-date``, ``email``, ``api-uri``...), which also catches serialisation
  drift such as Flask's RFC 1123 dates becoming ISO 8601 under FastAPI.

``infer`` builds a schema from a JSON value, ``merge`` joins two schemas (list
items, map values), and ``diff`` explains how two schemas differ.
"""

from __future__ import annotations

import re
from typing import Any

Schema = dict[str, Any]

TYPE_ORDER = ("null", "boolean", "integer", "number", "string", "array", "object")

# Order matters: the first matching pattern names the format.
STRING_FORMATS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("date-time", re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")),
    ("date-time-space", re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")),
    ("date", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("http-date", re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")),
    ("email", re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
    ("uuid", re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
    ("api-uri", re.compile(r"^/api2?/[^\s?#]+$")),
    ("jwt", re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]*$")),
)

# An object whose keys look like this is a map keyed by data, not a record.
_DATA_KEY = re.compile(
    r"^(-?\d+(\.\d+)?"  # numeric ids
    r"|[0-9a-fA-F-]{32,36}"  # uuids and hex digests
    r"|\d{4}-\d{2}-\d{2}.*"  # dates
    r"|.*@.*"  # anything with an @, emails included
    r"|/api2?/.*"  # resource URIs
    r")$"
)
# Records in this API have a few dozen keys at most; beyond this it is a map.
MAP_KEY_THRESHOLD = 64


def string_format(value: str) -> str | None:
    for name, pattern in STRING_FORMATS:
        if pattern.match(value):
            return name
    return None


def is_data_key(key: str) -> bool:
    return bool(_DATA_KEY.match(key)) or any(ch.isspace() for ch in key)


def is_map(value: dict[str, Any]) -> bool:
    return len(value) > MAP_KEY_THRESHOLD or any(is_data_key(k) for k in value)


def infer(value: Any) -> Schema:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        fmt = string_format(value)
        return {"type": "string", "x-format": fmt} if fmt else {"type": "string"}
    if isinstance(value, (list, tuple)):
        if not value:
            return {"type": "array", "maxItems": 0}
        items = infer(value[0])
        for item in value[1:]:
            items = merge(items, infer(item))
        return {"type": "array", "items": items}
    if isinstance(value, dict):
        if not value:
            return {"type": "object", "properties": {}, "required": []}
        if is_map(value):
            values = list(value.values())
            inner = infer(values[0])
            for item in values[1:]:
                inner = merge(inner, infer(item))
            return {"type": "object", "additionalProperties": inner}
        return {
            "type": "object",
            "properties": {k: infer(value[k]) for k in sorted(value)},
            "required": sorted(value),
        }
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def types_of(schema: Schema) -> set[str]:
    t = schema.get("type")
    if t is None:
        return set()
    return {t} if isinstance(t, str) else set(t)


def _with_types(types: set[str], parts: Schema) -> Schema:
    if "number" in types:
        types = types - {"integer"}
    ordered = [t for t in TYPE_ORDER if t in types]
    out: Schema = {"type": ordered[0] if len(ordered) == 1 else ordered}
    out.update(parts)
    return out


def merge(a: Schema, b: Schema) -> Schema:
    """The narrowest schema that accepts everything ``a`` or ``b`` accepts."""
    if a == b:
        return a
    ta, tb = types_of(a), types_of(b)
    parts: Schema = {}

    if "string" in ta and "string" in tb:
        if a.get("x-format") is not None and a.get("x-format") == b.get("x-format"):
            parts["x-format"] = a["x-format"]
    elif "string" in ta or "string" in tb:
        src = a if "string" in ta else b
        if "x-format" in src:
            parts["x-format"] = src["x-format"]

    if "array" in ta and "array" in tb:
        if "items" in a and "items" in b:
            parts["items"] = merge(a["items"], b["items"])
        elif "items" in a or "items" in b:
            parts["items"] = a.get("items") or b["items"]
        else:
            parts["maxItems"] = 0
    elif "array" in ta or "array" in tb:
        src = a if "array" in ta else b
        parts.update({k: src[k] for k in ("items", "maxItems") if k in src})

    if "object" in ta and "object" in tb:
        parts.update(_merge_objects(a, b))
    elif "object" in ta or "object" in tb:
        src = a if "object" in ta else b
        parts.update({k: src[k] for k in ("properties", "required", "additionalProperties") if k in src})

    return _with_types(ta | tb, parts)


def _object_values(schema: Schema) -> Schema | None:
    """Every value schema an object admits, joined; None for an empty record."""
    joined = schema.get("additionalProperties")
    for prop in schema.get("properties", {}).values():
        joined = prop if joined is None else merge(joined, prop)
    return joined


def _merge_objects(a: Schema, b: Schema) -> Schema:
    if "additionalProperties" in a or "additionalProperties" in b:
        va, vb = _object_values(a), _object_values(b)
        if va is None or vb is None:
            joined = va if vb is None else vb
        else:
            joined = merge(va, vb)
        return {"additionalProperties": joined} if joined is not None else {}
    pa, pb = a.get("properties", {}), b.get("properties", {})
    props = {}
    for key in sorted(set(pa) | set(pb)):
        if key in pa and key in pb:
            props[key] = merge(pa[key], pb[key])
        else:
            props[key] = pa.get(key) or pb[key]
    required = sorted(set(a.get("required", [])) & set(b.get("required", [])))
    return {"properties": props, "required": required}


def diff(expected: Schema, actual: Schema, path: str = "$") -> list[str]:
    """Human-readable differences; empty when the shapes match."""
    out: list[str] = []
    te, ta = types_of(expected), types_of(actual)
    if te != ta:
        out.append(f"{path}: type {sorted(te)} != {sorted(ta)}")
    common = te & ta

    if "string" in common and expected.get("x-format") != actual.get("x-format"):
        out.append(f"{path}: string format {expected.get('x-format')!r} != {actual.get('x-format')!r}")

    if "array" in common:
        e_empty, a_empty = "items" not in expected, "items" not in actual
        if e_empty != a_empty:
            out.append(
                f"{path}: array is {'empty' if e_empty else 'non-empty'} in recording, {'empty' if a_empty else 'non-empty'} now"
            )
        elif not e_empty:
            out.extend(diff(expected["items"], actual["items"], f"{path}[]"))

    if "object" in common:
        e_map, a_map = "additionalProperties" in expected, "additionalProperties" in actual
        if e_map != a_map:
            out.append(
                f"{path}: object is {'a map' if e_map else 'a record'} in recording, {'a map' if a_map else 'a record'} now"
            )
        elif e_map:
            out.extend(diff(expected["additionalProperties"], actual["additionalProperties"], f"{path}{{*}}"))
        else:
            pe, pa = expected.get("properties", {}), actual.get("properties", {})
            for key in sorted(set(pe) - set(pa)):
                out.append(f"{path}: missing key {key!r}")
            for key in sorted(set(pa) - set(pe)):
                out.append(f"{path}: unexpected key {key!r}")
            re_, ra = set(expected.get("required", [])), set(actual.get("required", []))
            for key in sorted((re_ ^ ra) & set(pe) & set(pa)):
                state = "always present" if key in re_ else "sometimes absent"
                out.append(f"{path}.{key}: {state} in recording, not now")
            for key in sorted(set(pe) & set(pa)):
                out.extend(diff(pe[key], pa[key], f"{path}.{key}"))
    return out
