---
name: worktree-guard-bash
description: The worktree-isolation guard rejects Bash it cannot parse; how to phrase commands so they run
metadata:
  type: feedback
---

In an isolated worktree, the guard refuses Bash commands it cannot verify:
- `uv run ... --delimiter ';'` (a quoted `;` argument);
- heredocs that create files outside the worktree;
- compound `cd /tmp && ...` chains;
- a variable used as the command name (`C=/x; $C/run.sh`);
- any text with the substring `git` inside another word or argument (`github.com`, `.github/`, a python heredoc mentioning it) chained with other commands, and `curl -w '%{...}'`; run them alone or reword;
- `uv run python - <<EOF` fed scripts containing f-string braces, when chained with other commands;
- `git` with `A..B` plus pipes in loops;
- any computed value fed to `uv` or `git` (`uv run ... $(cat list)`, `xargs -a list uv run ...`, `git diff $(git merge-base ...)`), and long `cd && sed && cat <<EOF && git -C` chains. Pass paths and SHAs literally.

A refused command runs nothing. Any follow-up command that depends on it then runs against missing files and can look green. Always check that the setup step actually ran.

**Why:** the guard must prove that no git command escapes the worktree, so it refuses any construct it cannot parse.

**How to apply:**
- Write edit scripts to `/tmp/*.py` with the Write tool, then run `uv run --no-project python /tmp/x.py` on its own.
- Use literal absolute paths, not variables, for commands.
- For a clean checkout, use `git archive --format=tar -o /tmp/x.tar <sha>` alone, then extract it in a separate call.
- Run one plain git command per call.
- `python3 x.py` is blocked; use `uv run python x.py`.
- To split a commit without `rebase -i`: `git switch -c tmp <parent>`, then for each new commit `git checkout <old-sha> -- <paths>` and commit. Check `git diff --cached --quiet <old-sha>`, run `git cherry-pick <old-sha>..<tip>`, check `git diff --quiet <old-tip>`, then `git branch -f <wp-branch> tmp`. Only on unpushed branches.
