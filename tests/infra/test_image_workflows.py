"""The image workflows tag images with a valid Docker tag, whatever the branch name."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
IMAGE_WORKFLOWS = ["web.yml", "pipeline.yml"]


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def image_tag_step(workflow: dict) -> dict:
    (step,) = [
        s for s in workflow["jobs"]["prepare"]["steps"] if s.get("id") == "image_tag"
    ]
    return step


def run_step(step: dict, tmp_path: Path, **env: str) -> str:
    output = tmp_path / "output"
    output.write_text("")
    # The Actions default for a run step without `shell:`.
    subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        env={"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output), **env},
        check=True,
    )
    return dict(line.split("=", 1) for line in output.read_text().splitlines())[
        "image_tag"
    ]


@pytest.mark.parametrize("name", IMAGE_WORKFLOWS)
@pytest.mark.parametrize(
    ("ref", "tag"),
    [
        ("main", "main"),
        ("mig/WP-3b-cpython-313", "mig-WP-3b-cpython-313"),
        ("feature/a b:c@d", "feature-a-b-c-d"),
        ("x" * 200, "x" * 128),
    ],
)
def test_branch_name_becomes_a_valid_image_tag(name, ref, tag, tmp_path):
    step = image_tag_step(load(name))
    assert set(step["env"]) == {"REF"}
    assert run_step(step, tmp_path, REF=ref) == tag


@pytest.mark.parametrize("name", IMAGE_WORKFLOWS)
def test_every_build_job_uses_the_prepared_tag(name):
    jobs = load(name)["jobs"]
    builds = {job_name: job for job_name, job in jobs.items() if job_name != "prepare"}
    assert builds
    for job in builds.values():
        assert job["env"]["TAG"] == "${{ needs.prepare.outputs.image_tag }}"
