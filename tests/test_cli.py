import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from gameclub.cli import main


def run(data: Path, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(out):
        code = main(["--data", str(data), *argv])
    return code, out.getvalue()


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        for pid in ("alice", "bob", "chloe", "dan"):
            run(self.data, "player", "add", pid, pid.title())
            ids = []
            for kind in ("coop", "indie", "other"):
                gid = f"{pid}-{kind}"
                flag = {"coop": ["--coop"], "indie": ["--indie"]}.get(kind, [])
                run(self.data, "game", "add", gid, "--manual",
                    "--title", gid, *flag)
                ids.append(gid)
            run(self.data, "list", "set", pid, *ids)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_round(self) -> None:
        code, out = run(self.data, "status")
        self.assertEqual(code, 0, out)
        self.assertIn("round 1 can be drawn", out)

        code, out = run(self.data, "draw")
        self.assertEqual(code, 0, out)
        self.assertIn("round 1", out)

        rounds = json.loads((self.data / "rounds.json").read_text())
        self.assertEqual(len(rounds), 1)
        self.assertEqual(len(rounds[0]["picks"]), 3)
        self.assertEqual(len(rounds[0]["sitting"]), 1)
        left_out = rounds[0]["sitting"][0]

        # No second draw until the round is closed.
        code, out = run(self.data, "draw")
        self.assertEqual(code, 1)
        self.assertIn("not closed", out)

        run(self.data, "round", "close", "1")
        code, out = run(self.data, "status")
        # Left out once: weight 2 vs 1, so a 90% chance next round.
        self.assertIn(f"{left_out.title()}: 90% (waited 1)", out)

    def test_list_set_rejects_unknown_game(self) -> None:
        code, out = run(self.data, "list", "set", "alice", "nope")
        self.assertEqual(code, 1)
        self.assertIn("unknown game", out)

    def test_player_joining_later_starts_at_highest_wait(self) -> None:
        run(self.data, "draw")
        run(self.data, "round", "close", "1")
        run(self.data, "player", "add", "eve", "Eve")
        run(self.data, "game", "add", "eve-1", "--manual", "--title", "E")
        run(self.data, "list", "set", "eve", "eve-1")
        code, out = run(self.data, "status")
        self.assertIn("Eve: ", out)
        self.assertIn("(waited 1)", out.split("Eve: ")[1].split("\n")[0])


if __name__ == "__main__":
    unittest.main()
