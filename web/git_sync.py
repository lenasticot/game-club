"""Keep the data/ clone in sync with GitHub.

Two writers share the repo: the live app (site + Discord) and the admin
CLI on a laptop (draws, `game set`). So the app pulls before every write
and now and then before reads, commits right after a write, and pushes
in the background, retrying once after a rebase if the push is rejected.

All git commands go through one lock so a background push never runs in
the middle of a pull or commit.
"""

import logging
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("gameclub.sync")
_lock = threading.Lock()


class GitSyncError(Exception):
    """Raised when a git command fails."""


def _run(repo_dir: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=repo_dir, capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise GitSyncError(f"{' '.join(cmd)}: {result.stderr.strip()}")
    return result


def _pull(repo_dir: Path) -> None:
    try:
        _run(repo_dir, ["git", "pull", "--rebase", "-q"])
    except GitSyncError:
        # A conflicting rebase would leave the clone stuck mid-rebase and
        # block every later write; back out and let the caller report it.
        subprocess.run(["git", "rebase", "--abort"], cwd=repo_dir,
                       capture_output=True)
        raise


def pull(repo_dir: Path) -> None:
    with _lock:
        _pull(repo_dir)


def commit(repo_dir: Path, message: str) -> bool:
    """Commit data/; False if there was nothing to commit."""
    with _lock:
        _run(repo_dir, ["git", "add", "data"])
        status = _run(repo_dir, ["git", "status", "--porcelain", "data"])
        if not status.stdout.strip():
            return False
        _run(repo_dir, ["git", "commit", "-q", "-m", message])
        return True


def push(repo_dir: Path) -> None:
    """Push, rebasing once on top of the remote if it moved meanwhile."""
    with _lock:
        try:
            _run(repo_dir, ["git", "push", "-q"])
        except GitSyncError as first:
            log.warning("push rejected, rebasing and retrying: %s", first)
            _pull(repo_dir)
            _run(repo_dir, ["git", "push", "-q"])
