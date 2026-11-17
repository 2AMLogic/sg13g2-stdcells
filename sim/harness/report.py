"""Record-id minting and git provenance for append-only evidence records.

Record id shape: ``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``. sim/ results are
append-only evidence; :func:`allocate_record_id` never returns an id whose
record already exists, advancing the timestamp on collision instead.
"""

from __future__ import annotations

import datetime as _dt
import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
        )
        return out.stdout.strip()
    except OSError:  # pragma: no cover - git always present in a scaffolded repo
        return ""


def git_provenance(repo_root: Path) -> dict:
    commit = _git("rev-parse", "HEAD", cwd=repo_root)
    dirty = bool(_git("status", "--porcelain", cwd=repo_root))
    return {
        "commit": commit or "unknown",
        "short": (commit[:7] if commit else "unknown"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root) or "unknown",
        "dirty": dirty,
    }


# The one dirty marker in the repo: `commit_stamp` appends it, `is_dirty_stamp`
# recognises it, and nothing else hand-types the literal (issue #134).
_DIRTY_SUFFIX = " (dirty)"


def commit_stamp(git: dict) -> str:
    """``<commit>[ (dirty)]`` -- the stamp format writer and checker share.

    Takes a :func:`git_provenance` snapshot so a stamp always names the tree
    state the snapshot captured.
    """
    return git["commit"] + (_DIRTY_SUFFIX if git["dirty"] else "")


def is_dirty_stamp(stamp: str) -> bool:
    """Whether ``stamp`` is a :func:`commit_stamp` output that marked a dirty tree.

    Anchored on the exact `` (dirty)`` suffix (trailing whitespace tolerated),
    so a commit string that merely contains ``dirty`` elsewhere does not match.
    """
    return stamp.rstrip().endswith(_DIRTY_SUFFIX)


def format_record_id(short_sha: str, when: _dt.datetime) -> str:
    """``<YYYYMMDD>-<HHMMSS>-<short-git-sha>``."""
    return f"{when.strftime('%Y%m%d-%H%M%S')}-{short_sha}"


def allocate_record_id(
    repo_root: Path,
    records_dir: Path,
    when: _dt.datetime | None = None,
    git: dict | None = None,
) -> str:
    """Mint a fresh, unused ``<record-id>``.

    Append-only: if a record with this id already exists (same second, same
    commit) the timestamp advances until the id is free, rather than
    overwriting anything.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    short_sha = (git or git_provenance(repo_root))["short"]
    while True:
        record_id = format_record_id(short_sha, when)
        if not (records_dir / f"{record_id}.md").exists():
            return record_id
        when += _dt.timedelta(seconds=1)
