"""Commit and push data/ after a web write.

Writes are serialized with a lock so two players submitting at once
don't race each other's commits. push=False is for local dev/tests,
where there is no remote (or we don't want to push automatically).
"""

import subprocess
import threading
from pathlib import Path

_lock = threading.Lock()


class GitSyncError(Exception):
    """Raised when a git command fails."""


def _run(repo_dir: Path, cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=repo_dir, capture_output=True,
                            text=True)
    if result.returncode != 0:
        raise GitSyncError(f"{' '.join(cmd)}: {result.stderr.strip()}")
    return result


def commit_and_push(repo_dir: Path, message: str, push: bool = True) -> None:
    with _lock:
        _run(repo_dir, ["git", "add", "data"])
        status = _run(repo_dir, ["git", "status", "--porcelain", "data"])
        if not status.stdout.strip():
            return
        _run(repo_dir, ["git", "commit", "-m", message])
        if push:
            _run(repo_dir, ["git", "push"])
