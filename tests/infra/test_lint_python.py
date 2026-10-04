import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "ci" / "lint_python.sh"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def one_commit_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Like a depth-1 CI checkout: the base the script is asked about does not exist.
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "t")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "t@example.invalid")
    git(tmp_path, "init", "-q")
    (tmp_path / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", "a.py")
    git(tmp_path, "commit", "-q", "-m", "only")
    return tmp_path


@pytest.mark.parametrize("base", ["HEAD~1", "no-such-ref"])
def test_unresolvable_base_fails_instead_of_passing(one_commit_repo, base):
    result = subprocess.run(
        ["bash", str(SCRIPT), base],
        cwd=one_commit_repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "no Python files changed" not in result.stdout
