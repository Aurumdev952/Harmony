"""Contract cases: load them, run them, and turn a response into an observation.

Cases live in ``cases/*.json`` and run in file-name order, then list order, so
a case can use what an earlier one created. Keys of a case:

  id, route        unique id; ``"METHOD /path/template"`` from INVENTORY.md
  path, query      the concrete request (path defaults to the route's)
  body | files     a JSON body, or multipart parts (repo path or ``capture:<name>``)
  session          ``admin*``, ``client*`` or ``anonymous*`` (see runner.py)
  capture          ``{name: "/json/pointer"}``; ``#id`` takes a URI's trailing id
  capture_body     name under which to keep the raw response body
  pin              pointers whose deterministic values are compared too;
                   ``[]``/``{*}`` tokens pin the set of values (enums)
  maps             response paths that are maps keyed by data (see schema.infer)
  cookies          true to record which cookies the response sets or clears
  note             why the case looks the way it does

``{name}`` in a path, query, body or key is replaced with a capture, and
``{env:NAME}`` with an environment variable (the login password, which
therefore never appears in a case or a recording).

An observation is what a recording stores and a replay compares:
``{status, content_type, headers, response_schema, pinned}``, plus ``cookies``
for cases that ask for it. Request bodies live in the case files, not the
recordings.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import schema

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[1]
CASES_DIR = HERE / "cases"
RECORDINGS_DIR = HERE / "recordings"
INVENTORY = HERE / "INVENTORY.md"

# Response headers whose presence is part of the contract (Potion pagination,
# downloads, redirects). Only names are recorded, never values.
CONTRACT_HEADERS = ("content-disposition", "link", "location", "x-total-count")

# Pinned values must be deterministic and harmless; these never qualify.
_SECRET_NAME = re.compile(
    r"pass(word)?|secret|token|api[_-]?key|hash|salt|session|cookie|authori[sz]ation|email|phone",
    re.IGNORECASE,
)

# A multipart part whose source starts with this is the raw body an earlier
# case captured with ``capture_body``, not a file in the repository.
CAPTURED_FILE = "capture:"

_PLACEHOLDER = re.compile(r"\{(env:)?([A-Za-z_][\w.]*)\}")


CASE_KEYS = {
    "id",
    "route",
    "path",
    "query",
    "body",
    "files",
    "session",
    "capture",
    "capture_body",
    "pin",
    "maps",
    "cookies",
    "note",
}


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
    capture_body: str | None = None
    pin: tuple[str, ...] = ()
    maps: frozenset[str] = frozenset()
    cookies: bool = False
    note: str = ""

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Case:
        unknown = set(raw) - CASE_KEYS
        if unknown:
            raise ValueError(f"{raw.get('id')}: unknown case keys {sorted(unknown)}")
        method, _, template = raw["route"].partition(" ")
        for pointer in raw.get("pin", []):
            if _SECRET_NAME.search(pointer):
                raise ValueError(
                    f"{raw['id']}: refusing to pin {pointer!r}; it names a secret or PII"
                )
        return cls(
            id=raw["id"],
            route=raw["route"],
            method=method,
            path=raw.get("path", template),
            query=raw.get("query", {}),
            body=raw.get("body"),
            files=raw.get("files", {}),
            session=raw.get("session", "admin"),
            capture=raw.get("capture", {}),
            capture_body=raw.get("capture_body"),
            pin=tuple(raw.get("pin", [])),
            maps=frozenset(raw.get("maps", [])),
            cookies=bool(raw.get("cookies", False)),
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


# A string "relay:<path to __generated__/X.graphql.js>" stands for that
# operation's query text, so GraphQL cases follow the client's real queries.
RELAY_PREFIX = "relay:"
_RELAY_TEXT = re.compile(r'"text":\s*("(?:[^"\\]|\\.)*")')


def relay_text(artifact: str) -> str:
    match = _RELAY_TEXT.search((REPO_ROOT / artifact).read_text())
    if not match:
        raise ValueError(f"no operation text in {artifact}")
    return json.loads(match.group(1))


def substitute(value: Any, captures: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith(RELAY_PREFIX):
        return relay_text(value.removeprefix(RELAY_PREFIX))
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value)
        if whole:
            return _lookup(whole, captures)
        return _PLACEHOLDER.sub(lambda m: str(_lookup(m, captures)), value)
    if isinstance(value, list):
        return [substitute(v, captures) for v in value]
    if isinstance(value, dict):
        return {
            substitute(k, captures): substitute(v, captures) for k, v in value.items()
        }
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


EACH = ("[]", "{*}")


def pin_value(document: Any, pointer: str) -> Any:
    """A JSON pointer, where a ``[]`` token means every item of an array and
    ``{*}`` every value of an object. Such a pointer pins the sorted set of
    values found, which is how an enum-like field is pinned."""
    tokens = [] if pointer in ("", "/") else pointer.lstrip("/").split("/")
    if not any(t in EACH for t in tokens):
        return resolve_pointer(document, pointer)
    found = {json.dumps(v, sort_keys=True) for v in _walk(document, tokens)}
    return [json.loads(v) for v in sorted(found)]


def _walk(node: Any, tokens: list[str]) -> Iterator[Any]:
    if not tokens:
        yield node
        return
    token, rest = tokens[0], tokens[1:]
    if token == "[]":
        for item in node:
            yield from _walk(item, rest)
    elif token == "{*}":
        for item in node.values():
            yield from _walk(item, rest)
    else:
        yield from _walk(resolve_pointer(node, "/" + token), rest)


def capture_value(document: Any, spec: str) -> Any:
    """``/pointer`` takes the value; ``/pointer#id`` takes the integer id at the
    end of a resource URI such as ``/api2/dashboard/7``; ``/pointer#relay``
    takes the database id inside a Hasura Relay node id (base64 of
    ``[1, "public", "<table>", <id>]``)."""
    pointer, _, transform = spec.partition("#")
    value = resolve_pointer(document, pointer)
    if transform == "id":
        return int(str(value).rstrip("/").rsplit("/", 1)[1])
    if transform == "relay":
        return json.loads(base64.b64decode(str(value)))[-1]
    if transform:
        raise ValueError(f"unknown capture transform {transform!r}")
    return value


def placeholders(case: Case) -> Iterator[str]:
    """Capture names a case needs before it can run."""
    text = json.dumps([case.path, case.query, case.body])
    for m in _PLACEHOLDER.finditer(text):
        if not m.group(1):
            yield m.group(2)
    for source in case.files.values():
        if source.startswith(CAPTURED_FILE):
            yield source.removeprefix(CAPTURED_FILE)


def captures_of(case: Case) -> set[str]:
    return set(case.capture) | ({case.capture_body} if case.capture_body else set())


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def describe_set_cookie(header: str) -> str:
    """One Set-Cookie header without its value: the name, then ``cleared``
    (empty value, Max-Age=0 or an expiry in 1970), ``persistent`` (Max-Age or
    Expires) or ``session``, then the attributes that matter for SEC-5."""
    first, *attrs = [part.strip() for part in header.split(";") if part.strip()]
    name, _, value = first.partition("=")
    pairs = {
        k.strip().lower(): v.strip() for k, _, v in (a.partition("=") for a in attrs)
    }
    if (
        not value.strip('"')
        or pairs.get("max-age") == "0"
        or "1970" in pairs.get("expires", "")
    ):
        lifetime = "cleared"
    elif "max-age" in pairs or "expires" in pairs:
        lifetime = "persistent"
    else:
        lifetime = "session"
    flags = [f for f in ("httponly", "secure") if f in pairs]
    if "samesite" in pairs:
        flags.append(f"samesite={pairs['samesite'].lower()}")
    for key in ("path", "domain"):
        if key in pairs:
            flags.append(f"{key}={pairs[key]}")
    return "; ".join([name, lifetime, *flags])


def _unsafe_pin(values: list[Any]) -> str | None:
    for v in values:
        if isinstance(v, (dict, list)):
            return "not a scalar"
        fmt = schema.string_format(v) if isinstance(v, str) else None
        if fmt in ("email", "jwt"):
            return f"a value looks like {fmt}"
    return None


def observe(
    case: Case,
    status: int,
    headers: Mapping[str, str],
    body: bytes,
    set_cookies: tuple[str, ...] = (),
    *,
    recording: bool = False,
) -> dict[str, Any]:
    """``recording`` refuses pins that would store an unsafe value. A replay
    never raises over a pin: an unsafe value is replaced by a marker, so the
    mismatch is a diff line that does not echo the new value."""
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
        "response_schema": schema.infer(parsed, case.maps)
        if is_json and body
        else None,
        "pinned": {},
    }
    if not is_json:
        observation["non_empty"] = bool(body)
    if case.cookies:
        observation["cookies"] = sorted(describe_set_cookie(h) for h in set_cookies)
    missing = []
    for pointer in case.pin:
        try:
            value = pin_value(parsed, pointer)
        except (LookupError, TypeError, ValueError, AttributeError):
            missing.append(pointer)
            continue
        values = (
            value
            if isinstance(value, list) and any(t in pointer for t in EACH)
            else [value]
        )
        unsafe = _unsafe_pin(values)
        if unsafe and recording:
            raise ValueError(f"{case.id}: refusing to pin {pointer}; {unsafe}")
        observation["pinned"][pointer] = f"<not shown: {unsafe}>" if unsafe else value
    if missing:
        observation["missing_pins"] = missing
    return observation


def compare(recorded: Mapping[str, Any], observed: Mapping[str, Any]) -> list[str]:
    """Every difference between a recording and a replay, as readable lines."""
    problems: list[str] = []
    if recorded["status"] != observed["status"]:
        problems.append(f"status {recorded['status']} != {observed['status']}")
    if recorded["content_type"] != observed["content_type"]:
        problems.append(
            f"content type {recorded['content_type']!r} != {observed['content_type']!r}"
        )
    if recorded["headers"] != observed["headers"]:
        problems.append(
            f"contract headers {recorded['headers']} != {observed['headers']}"
        )
    if recorded.get("non_empty") != observed.get("non_empty"):
        problems.append(
            f"non-JSON body present {recorded.get('non_empty')} != {observed.get('non_empty')}"
        )
    if recorded.get("cookies") != observed.get("cookies"):
        problems.append(
            f"cookies {recorded.get('cookies')} != {observed.get('cookies')}"
        )
    rs, os_ = recorded["response_schema"], observed["response_schema"]
    if (rs is None) != (os_ is None):
        problems.append(f"JSON body present {rs is not None} != {os_ is not None}")
    elif rs is not None:
        problems.extend(schema.diff(rs, os_))
    for pointer, value in recorded["pinned"].items():
        if pointer in observed.get("missing_pins", []):
            problems.append(f"pinned {pointer}: {value!r} recorded, missing now")
        elif observed["pinned"].get(pointer) != value:
            problems.append(
                f"pinned {pointer}: {value!r} != {observed['pinned'].get(pointer)!r}"
            )
    problems.extend(f"capture {error}" for error in observed.get("capture_errors", []))
    return problems
