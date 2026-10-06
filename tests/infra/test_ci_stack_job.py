"""Tests marked `stack` run in a CI job of their own, on a runner with Docker.

The unit job deselects them. The Postgres clock test (WP-0k) starts its own
throwaway Postgres with `docker run`, so it needs Docker but not the compose
stack; the contract replay skips itself without CONTRACT_BASE_URL.
"""

import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "integration.yml"


def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def runs(job: dict) -> list[str]:
    return [step["run"].strip() for step in job["steps"] if "run" in step]


def test_a_job_on_a_docker_runner_runs_the_stack_marked_tests():
    stack_jobs = [
        job for job in jobs().values() if "ci/pytest_suites.sh -m stack" in runs(job)
    ]
    assert len(stack_jobs) == 1
    (job,) = stack_jobs
    # GitHub's Ubuntu runners have a Docker daemon; containers or self-hosted
    # runners may not.
    assert job["runs-on"] == "ubuntu-24.04"
    assert "container" not in job
    assert job["permissions"] == {"contents": "read"}


def test_the_unit_job_still_deselects_them():
    assert "ci/pytest_suites.sh" in runs(jobs()["python"])
    script = (REPO / "ci" / "pytest_suites.sh").read_text()
    assert "pytest -m 'not stack' \"$@\"" in script


def test_a_later_marker_option_replaces_the_default(tmp_path):
    # pytest_suites.sh passes its arguments after `-m 'not stack'`; the job relies
    # on the last -m winning.
    (tmp_path / "test_markers.py").write_text(
        "import pytest\n\n"
        "def test_unit():\n    pass\n\n"
        "@pytest.mark.stack\n"
        "def test_needs_docker():\n    pass\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-o", "markers=stack: test", "-m", "not stack", "-m", "stack", str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )  # fmt: skip
    collected = [line for line in result.stdout.splitlines() if "::" in line]
    assert [line.rsplit("/", 1)[-1] for line in collected] == [
        "test_markers.py::test_needs_docker"
    ]


def test_the_contract_replay_skips_without_the_compose_stack():
    env = {k: v for k, v in os.environ.items() if k != "CONTRACT_BASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-m", "stack", "tests/contract/test_replay.py"],
        capture_output=True, text=True, cwd=REPO, env=env, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    assert " skipped" in result.stdout
    assert " failed" not in result.stdout
