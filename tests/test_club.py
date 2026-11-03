"""Club sync against a real (local, bare) git remote.

Two clones stand in for the live app and the admin's laptop, to check
that the app picks up a CLI draw and that a rejected push recovers.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from gameclub.store import Store, new_game
from web import club as actions
from web import git_sync
from web.club import Club


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _clone(remote: Path, dest: Path) -> None:
    subprocess.run(["git", "clone", "-q", str(remote), str(dest)],
                   check=True, capture_output=True)
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "test")


class TestClubSync(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote = root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)],
                       check=True)
        self.admin = root / "admin"
        _clone(self.remote, self.admin)
        s = Store(self.admin / "data")
        s.add_player("alice", "Alice", [])
        coop = new_game("coop", "Coop")
        coop["is_coop"] = True
        s.add_game(coop)
        s.save()
        _git(self.admin, "add", "-A")
        _git(self.admin, "commit", "-q", "-m", "seed")
        _git(self.admin, "push", "-q", "origin", "HEAD")
        self.app_repo = root / "app"
        _clone(self.remote, self.app_repo)
        self.club = Club(self.app_repo / "data", self.app_repo, remote=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def admin_change(self, game_id: str) -> None:
        _git(self.admin, "pull", "-q", "--rebase")
        s = Store(self.admin / "data")
        s.add_game(new_game(game_id, game_id))
        s.save()
        _git(self.admin, "commit", "-q", "-am", f"admin: {game_id}")
        _git(self.admin, "push", "-q")

    def wait_pushes(self) -> None:
        for t in self.club.pending:
            t.join(timeout=10)

    def test_write_pulls_admin_change_first_and_pushes(self) -> None:
        self.admin_change("from-admin")
        with self.club.write("alice: add coop") as s:
            self.assertTrue(s.has_game("from-admin"))
            actions.add_to_list(s, "alice", "coop")
        self.wait_pushes()
        log = _git(self.remote, "log", "--oneline")
        self.assertIn("admin: from-admin", log)
        self.assertIn("alice: add coop", log)

    def test_rejected_push_rebases_and_retries(self) -> None:
        s = Store(self.app_repo / "data")
        actions.add_to_list(s, "alice", "coop")
        s.save()
        git_sync.commit(self.app_repo, "alice: add coop")
        self.admin_change("meanwhile")  # remote moves before our push
        with self.assertLogs("gameclub.sync", "WARNING"):
            git_sync.push(self.app_repo)
        log = _git(self.remote, "log", "--oneline")
        self.assertIn("admin: meanwhile", log)
        self.assertIn("alice: add coop", log)

    def test_failed_body_saves_nothing(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.club.write("nope") as s:
                actions.add_to_list(s, "alice", "coop")
                raise RuntimeError
        self.assertEqual(Store(self.app_repo / "data").submissions, {})


if __name__ == "__main__":
    unittest.main()
