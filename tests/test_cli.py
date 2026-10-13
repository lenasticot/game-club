import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from gameclub.cli import main
from gameclub.store import Store


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
        club = json.loads((self.data / "club.json").read_text())
        self.assertEqual(len(club["rotations"][0]["order"]), 4)
        self.assertEqual(rounds[0]["sitting"],
                         club["rotations"][0]["order"][:1])

        # No second draw until the round is closed.
        code, out = run(self.data, "draw")
        self.assertEqual(code, 1)
        self.assertIn("not closed", out)

        run(self.data, "round", "close", "1")
        code, out = run(self.data, "status")
        sitter = club["rotations"][0]["order"][1]
        self.assertIn(f"sits out: {sitter.title()}", out)

    def test_list_set_rejects_unknown_game_and_missing_coop(self) -> None:
        code, out = run(self.data, "list", "set", "alice", "nope")
        self.assertEqual(code, 1)
        self.assertIn("unknown game", out)
        code, out = run(self.data, "list", "set", "alice", "alice-indie")
        self.assertEqual(code, 1)
        self.assertIn("co-op", out)

    def test_player_joining_after_round_1_starts_new_rotation(self) -> None:
        run(self.data, "draw")
        run(self.data, "player", "add", "eve", "Eve")
        store = Store(self.data)
        rotations = store.rotations()
        self.assertEqual([r.start_round for r in rotations], [1, 2])
        self.assertEqual(rotations[1].order[-1], "eve")


if __name__ == "__main__":
    unittest.main()
