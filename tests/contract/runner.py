"""Runs contract cases against a live Harmony server.

Sessions are named by the cases. The prefix decides how they authenticate:
  admin*      logged in through POST /api2/authentication/login?set_cookie=true,
              the way the React app does;
  client*     X-Username / X-Password headers, the way web/python_client
              authenticates today;
  anonymous*  no credentials.
A case that would change its session (logging in or out) uses its own name.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from .cases import (
    CAPTURED_FILE,
    REPO_ROOT,
    Case,
    capture_value,
    observe,
    placeholders,
    substitute,
)

TIMEOUT_SECONDS = 300


@dataclass
class Credentials:
    username: str
    password: str = field(repr=False)

    @classmethod
    def from_env(cls) -> Credentials:
        username = os.environ.get("CONTRACT_USERNAME")
        password = os.environ.get("CONTRACT_PASSWORD")
        creds_file = os.environ.get("CONTRACT_CREDENTIALS_FILE")
        if not password and creds_file:
            info = Path(creds_file).stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
                raise PermissionError(
                    f"{creds_file} must be owned by you with mode 600"
                )
            for line in Path(creds_file).read_text().splitlines():
                key, _, value = line.partition("=")
                if key == "CONTRACT_PASSWORD":
                    password = value
        if not username or not password:
            raise LookupError(
                "set CONTRACT_USERNAME and CONTRACT_PASSWORD (or CONTRACT_CREDENTIALS_FILE)"
            )
        # Cases reference the credentials as {env:...}; make them resolvable.
        os.environ["CONTRACT_USERNAME"] = username
        os.environ["CONTRACT_PASSWORD"] = password
        return cls(username, password)


class SkipCase(Exception):
    """A case cannot run because an earlier case did not produce what it needs."""


@dataclass
class Runner:
    base_url: str
    credentials: Credentials
    captures: dict[str, Any] = field(default_factory=dict, repr=False)
    _sessions: dict[str, requests.Session] = field(default_factory=dict, repr=False)

    def session(self, name: str) -> requests.Session:
        if name not in self._sessions:
            s = requests.Session()
            if name.startswith("admin"):
                r = s.post(
                    f"{self.base_url}/api2/authentication/login",
                    params={"set_cookie": "true"},
                    json={
                        "email": self.credentials.username,
                        "password": self.credentials.password,
                    },
                    timeout=TIMEOUT_SECONDS,
                )
                r.raise_for_status()
            elif name.startswith("client"):
                s.headers.update(
                    {
                        "X-Username": self.credentials.username,
                        "X-Password": self.credentials.password,
                    }
                )
            elif not name.startswith("anonymous"):
                raise ValueError(f"unknown session {name!r}")
            self._sessions[name] = s
        return self._sessions[name]

    def _file_part(self, source: str) -> tuple[str, bytes]:
        if source.startswith(CAPTURED_FILE):
            name = source.removeprefix(CAPTURED_FILE)
            return f"{name}.zip", self.captures[name]
        return Path(source).name, (REPO_ROOT / source).read_bytes()

    def run(self, case: Case) -> dict[str, Any]:
        missing = [p for p in placeholders(case) if p not in self.captures]
        if missing:
            raise SkipCase(f"{case.id} needs {missing}, which no earlier case captured")
        path = substitute(case.path, self.captures)
        query = substitute(dict(case.query), self.captures)
        query = {
            k: json.dumps(v, separators=(",", ":"))
            if isinstance(v, (dict, list))
            else v
            for k, v in query.items()
        }
        body = substitute(case.body, self.captures)
        kwargs: dict[str, Any] = {
            "params": query,
            "timeout": TIMEOUT_SECONDS,
            "allow_redirects": False,
        }
        if case.files:
            kwargs["files"] = {
                name: self._file_part(source) for name, source in case.files.items()
            }
        elif body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["headers"] = {"Content-Type": "application/json"}
        response = self.session(case.session).request(
            case.method, self.base_url + path, **kwargs
        )
        set_cookies = (
            tuple(response.raw.headers.getlist("Set-Cookie"))
            if response.raw is not None
            else ()
        )
        observation = observe(
            case, response.status_code, response.headers, response.content, set_cookies
        )
        if case.capture_body:
            self.captures[case.capture_body] = response.content
        # A capture that fails is reported next to the shape diff, which
        # usually explains it, instead of raising before the diff is seen.
        errors = []
        for name, spec in case.capture.items():
            try:
                self.captures[name] = capture_value(response.json(), spec)
            except (LookupError, TypeError, ValueError) as exc:
                errors.append(f"{name} from {spec}: {type(exc).__name__}: {exc}")
        if errors:
            observation["capture_errors"] = errors
        return observation
