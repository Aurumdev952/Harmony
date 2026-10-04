"""Contract cases: load them, run them, and turn a response into an observation.

Cases live in ``cases/*.json`` and run in file-name order, then list order, so
a case can use what an earlier one created. ``capture`` stores a value from a
response under a name; ``{name}`` in a later path, query or body is replaced
with it, and ``{env:NAME}`` with an environment variable (used for the login
password, which therefore never appears in a case or a recording).

An observation is what a recording stores and a replay compares:
``{status, content_type, headers, request_schema, response_schema, pinned}``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import schema

HERE = Path(__file__).parent
CASES_DIR = HERE / "cases"
RECORDINGS_DIR = HERE / "recordings"
INVENTORY = HERE / "INVENTORY.md"

# Response headers whose presence is part of the contract (Potion pagination,
# downloads, redirects). Only names are recorded, never values.
CONTRACT_HEADERS = ("content-disposition", "link", "location", "x-total-count")

# Pinned values must be deterministic and harmless; these never qualify.
_SECRET_NAME = re.compile(
    r"pass(word)?|secret|token|api[_-]?key|hash|salt|session|cookie|authori[sz]ation|email|phone", re.IGNORECASE
)

_PLACEHOLDER = re.compile(r"\{(env:)?([A-Za-z_][\w.]*)\}")


@dataclass(frozen=True)
class Case:
    id: str
    route: str
    method: str
    path: str
    query: Mapping[str, Any] = field(default_factory=dict)
    body: Any = None
    files: Mapping[str, str] = field(default_factory=dict)
    session: str = "admin"
    capture: Mapping[str, str] = field(default_factory=dict)
    pin: tuple[str, ...] = ()
    compare: str = "shape"
    note: str = ""

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Case:
        method, _, template = raw["route"].partition(" ")
        if raw.get("compare", "shape") not in ("shape", "status"):
            raise ValueError(f"{raw['id']}: compare must be 'shape' or 'status'")
        if raw.get("compare") == "status" and not raw.get("note"):
            raise ValueError(f"{raw['id']}: a status-only case must say why in 'note'")
        for pointer in raw.get("pin", []):
            if _SECRET_NAME.search(pointer):
                raise ValueError(f"{raw['id']}: refusing to pin {pointer!r}; it names a secret or PII")
        return cls(
            id=raw["id"],
            route=raw["route"],
            method=raw.get("method", method),
            path=raw.get("path", template),
            query=raw.get("query", {}),
            body=raw.get("body"),
            files=raw.get("files", {}),
            session=raw.get("session", "admin"),
            capture=raw.get("capture", {}),
            pin=tuple(raw.get("pin", [])),
            compare=raw.get("compare", "shape"),
            note=raw.get("note", ""),
        )


def load_cases(cases_dir: Path = CASES_DIR) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(cases_dir.glob("*.json")):
        for raw in json.loads(path.read_text())["cases"]:
            cases.append(Case.from_json(raw))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    return cases


def recording_path(case_id: str, recordings_dir: Path = RECORDINGS_DIR) -> Path:
    return recordings_dir / f"{case_id}.json"


def substitute(value: Any, captures: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole:
            return _lookup(whole, captures)
        return _PLACEHOLDER.sub(lambda m: str(_lookup(m, captures)), value)
    if isinstance(value, list):
        return [substitute(v, captures) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, captures) for k, v in value.items()}
    return value


def _lookup(match: re.Match[str], captures: Mapping[str, Any]) -> Any:
    is_env, name = match.group(1), match.group(2)
    if is_env:
        if name not in os.environ:
            raise LookupError(f"environment variable {name} is not set")
        return os.environ[name]
    if name not in captures:
        raise LookupError(f"capture {name!r} is not set; did an earlier case fail?")
    return captures[name]


def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON pointer lookup."""
    if pointer in ("", "/"):
        return document
    current = document
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        else:
            current = current[token]
    return current


def capture_value(document: Any, spec: str) -> Any:
    """``/pointer`` takes the value; ``/pointer#id`` takes the integer id at the
    end of a resource URI such as ``/api2/dashboard/7``."""
    pointer, _, transform = spec.partition("#")
    value = resolve_pointer(document, pointer)
    if transform == "id":
        return int(str(value).rstrip("/").rsplit("/", 1)[1])
    if transform:
        raise ValueError(f"unknown capture transform {transform!r}")
    return value


def placeholders(case: Case) -> Iterator[str]:
    """Capture names a case needs before it can run."""
    text = json.dumps([case.path, case.query, case.body])
    for m in _PLACEHOLDER.finditer(text):
        if not m.group(1):
            yield m.group(2)


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _request_schema(case: Case, sent_body: Any) -> schema.Schema | None:
    if case.files:
        parts = sorted(case.files)
        return {
            "type": "object",
            "x-format": "multipart",
            "properties": {name: {"type": "string", "x-format": "binary"} for name in parts},
            "required": parts,
        }
    return schema.infer(sent_body) if sent_body is not None else None


def observe(case: Case, sent_body: Any, status: int, headers: Mapping[str, str], body: bytes) -> dict[str, Any]:
    lowered = {k.lower(): v for k, v in headers.items()}
    content_type = media_type(lowered.get("content-type"))
    parsed: Any = None
    is_json = content_type.endswith("json")
    if is_json and body:
        parsed = json.loads(body)
    elif body.lstrip()[:1] in (b"{", b"["):
        # The streamed table endpoints send JSON labelled text/html; the client
        # parses it as JSON regardless, so its shape is still the contract.
        try:
            parsed = json.loads(body)
            is_json = True
        except ValueError:
            pass
    observation: dict[str, Any] = {
        "status": status,
        "content_type": content_type,
        "headers": sorted(h for h in CONTRACT_HEADERS if h in lowered),
        "request_schema": _request_schema(case, sent_body),
        "response_schema": schema.infer(parsed) if is_json and body else None,
        "pinned": {},
    }
    if not is_json:
        observation["non_empty"] = bool(body)
    for pointer in case.pin:
        value = resolve_pointer(parsed, pointer)
        if isinstance(value, (dict, list)):
            raise TypeError(f"{case.id}: pin {pointer} must point at a scalar")
        fmt = schema.string_format(value) if isinstance(value, str) else None
        if fmt in ("email", "jwt"):
            raise ValueError(f"{case.id}: refusing to pin {pointer}; the value looks like {fmt}")
        observation["pinned"][pointer] = value
    return observation


def compare(case: Case, recorded: Mapping[str, Any], observed: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    if recorded["status"] != observed["status"]:
        problems.append(f"status {recorded['status']} != {observed['status']}")
    if recorded["content_type"] != observed["content_type"]:
        problems.append(f"content type {recorded['content_type']!r} != {observed['content_type']!r}")
    if case.compare == "status":
        return problems
    if recorded["headers"] != observed["headers"]:
        problems.append(f"contract headers {recorded['headers']} != {observed['headers']}")
    if recorded.get("non_empty") != observed.get("non_empty"):
        problems.append(f"non-JSON body present {recorded.get('non_empty')} != {observed.get('non_empty')}")
    rs, os_ = recorded["response_schema"], observed["response_schema"]
    if (rs is None) != (os_ is None):
        problems.append(f"JSON body present {rs is not None} != {os_ is not None}")
    elif rs is not None:
        problems.extend(schema.diff(rs, os_))
    for pointer, value in recorded["pinned"].items():
        if observed["pinned"].get(pointer) != value:
            problems.append(f"pinned {pointer}: {value!r} != {observed['pinned'].get(pointer)!r}")
    return problems
