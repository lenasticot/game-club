"""Flask app tests: identity, list editing, game search/add.

rawg.search/fetch and prices.steam_search/steam_price are mocked (no
network, no RAWG_API_KEY needed). git_sync runs for real against a
throwaway local repo, with push disabled, so a commit actually
happening is checked, not just assumed.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gameclub.store import GameRec, Store, new_game
from web.app import create_app


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True)


class TestWeb(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.data = self.repo / "data"
        self.data.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "test")

        s = Store(self.data)
        s.add_player("alice", "Alice", [])
        s.add_player("bob", "Bob", [])
        coop = new_game("existing-coop", "Existing Coop")
        coop["is_coop"] = True
        s.add_game(coop)
        s.save()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")

        app = create_app(data_dir=self.data, repo_dir=self.repo)
        app.config["GIT_PUSH"] = False
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def log(self) -> str:
        return subprocess.run(
            ["git", "log", "--oneline"], cwd=self.repo,
            capture_output=True, text=True, check=True).stdout

    def pick(self, player_id: str) -> None:
        r = self.client.post("/whoami", data={"player_id": player_id})
        self.assertEqual(r.status_code, 302)

    def test_no_identity_redirects_to_whoami(self) -> None:
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/whoami", r.headers["Location"])

    def test_pick_identity_then_see_home(self) -> None:
        self.pick("alice")
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Alice", r.data)
        self.assertIn(b"needs at least one unplayed co-op", r.data)

    def test_add_remove_priority_existing_game(self) -> None:
        self.pick("alice")
        r = self.client.post("/list/add", data={"game_id": "existing-coop"})
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertEqual(store.submissions["alice"],
                         [{"game_id": "existing-coop", "priority": False}])
        self.assertIn("add existing-coop", self.log())

        r = self.client.post("/list/priority",
                             data={"game_id": "existing-coop"})
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertTrue(store.submissions["alice"][0]["priority"])

        r = self.client.post("/list/remove",
                             data={"game_id": "existing-coop"})
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertEqual(store.submissions["alice"], [])
        self.assertIn("remove existing-coop", self.log())

    def test_adding_same_game_twice_is_a_noop(self) -> None:
        self.pick("alice")
        self.client.post("/list/add", data={"game_id": "existing-coop"})
        self.client.post("/list/add", data={"game_id": "existing-coop"})
        store = Store(self.data)
        self.assertEqual(len(store.submissions["alice"]), 1)

    def test_list_full_rejects_another_add(self) -> None:
        self.pick("alice")
        store = Store(self.data)
        for i in range(10):
            g = new_game(f"g{i}", f"Game {i}")
            store.add_game(g)
        store.submissions["alice"] = [
            {"game_id": f"g{i}", "priority": False} for i in range(10)]
        store.save()
        r = self.client.post("/list/add", data={"game_id": "existing-coop"})
        self.assertEqual(r.status_code, 400)

    def test_catalog_search_finds_existing_game(self) -> None:
        self.pick("alice")
        with patch("gameclub.rawg.search", return_value=[]):
            r = self.client.get("/?q=Existing")
        self.assertIn(b"Already in the club", r.data)
        self.assertIn(b"Existing Coop", r.data)

    def test_add_new_game_from_rawg_with_steam_fallback(self) -> None:
        self.pick("bob")
        draft: GameRec = new_game("new-slug", "New Game")
        draft["is_coop"] = True
        draft["genres"] = ["Action"]
        steam_results = [{"appid": 42, "name": "New Game"}]
        fetch_patch = patch("gameclub.rawg.fetch", return_value=draft)
        search_patch = patch("gameclub.prices.steam_search",
                             return_value=steam_results)
        with fetch_patch, search_patch:
            r = self.client.get("/games/new?slug=new-slug")
            self.assertEqual(r.status_code, 200)
            self.assertIn(b"New Game", r.data)

            with patch("gameclub.prices.steam_price", return_value=None):
                r = self.client.post("/games/new", data={
                    "slug": "new-slug", "steam_appid": "42",
                })
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertTrue(store.has_game("new-slug"))
        game = store.game("new-slug")
        self.assertTrue(game["is_coop"])  # RAWG's own guess, no form override
        self.assertIsNone(game["hours_main"])  # never set from the form
        self.assertEqual(game["steam_appid"], 42)
        self.assertIn({"game_id": "new-slug", "priority": False},
                      store.submissions["bob"])
        self.assertIn("add new game new-slug", self.log())

    def test_adding_existing_catalog_game_via_rawg_flow_reuses_it(
            self) -> None:
        self.pick("alice")
        r = self.client.post("/games/new", data={"slug": "existing-coop"})
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertEqual(len(store.games), 1)
        self.assertIn({"game_id": "existing-coop", "priority": False},
                      store.submissions["alice"])

    def test_finalize_succeeds_and_shows_in_players_api(self) -> None:
        self.pick("alice")
        self.client.post("/list/add", data={"game_id": "existing-coop"})
        r = self.client.post("/list/finalize")
        self.assertEqual(r.status_code, 302)
        store = Store(self.data)
        self.assertTrue(store.is_finalized("alice"))
        self.assertIn("finalized list", self.log())

        api = self.client.get("/api/players")
        alice = next(p for p in api.get_json() if p["id"] == "alice")
        self.assertTrue(alice["finalized"])
        self.assertEqual(alice["games"][0]["title"], "Existing Coop")

    def test_finalize_fails_without_coop_game(self) -> None:
        self.pick("bob")
        r = self.client.post("/list/finalize", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"co-op", r.data)
        store = Store(self.data)
        self.assertFalse(store.is_finalized("bob"))

    def test_editing_after_finalize_unfinalizes(self) -> None:
        self.pick("alice")
        self.client.post("/list/add", data={"game_id": "existing-coop"})
        self.client.post("/list/finalize")
        self.client.post("/list/remove", data={"game_id": "existing-coop"})
        store = Store(self.data)
        self.assertFalse(store.is_finalized("alice"))

    def test_games_page_lists_catalog(self) -> None:
        self.pick("alice")
        r = self.client.get("/games")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Existing Coop", r.data)

    def test_players_page_loads(self) -> None:
        self.pick("alice")
        r = self.client.get("/players")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"api/players", r.data)


if __name__ == "__main__":
    unittest.main()
