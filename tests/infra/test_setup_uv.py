"""Every setup-uv step pins uv's version and the checksum of its download (SEC-9).

setup-uv v10.2.0 has no built-in checksum for uv 0.12.23, so without `checksum`
it would run whatever the release URL serves (security finding F2, WP-3b).
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted(
    (Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml")
)
# sha256 of uv-x86_64-unknown-linux-gnu.tar.gz from the 0.12.23 release, which
# matches the release's own .sha256 file; GitHub runners are x86_64.
UV_CHECKSUMS = {
    "0.12.23": "9167d72b3319674b6303c4cbe071854bba13ebdf3d76b1a7cbdc175471fb66d6",
}


def setup_uv_steps():
    for path in WORKFLOWS:
        for job_name, job in yaml.safe_load(path.read_text())["jobs"].items():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    yield pytest.param(step, id=f"{path.name}:{job_name}")


@pytest.mark.parametrize("step", list(setup_uv_steps()))
def test_setup_uv_pins_version_and_checksum(step):
    version = step["with"]["version"]
    assert step["with"].get("checksum") == UV_CHECKSUMS[version]


def test_there_are_setup_uv_steps_to_check():
    assert list(setup_uv_steps())
