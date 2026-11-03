"""Discord interactions, with hand-written payloads.

Discord calls (reply edits, followups) are captured instead of sent and
background work runs inline. RAWG and Steam are mocked. Payload shapes
follow Discord's docs; not checked against live Discord.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

from nacl.signing import SigningKey

from gameclub.store import GameRec, Store, new_game
from web import discord_bot as d
from web.app import create_app
from web.club import Club

ALICE, BOB, ADMIN = "111", "222", "999"


class TestDiscord(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.data = self.repo / "data"
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            subprocess.run(["git", "config", k, v], cwd=self.repo,
                           check=True)
        s = Store(self.data)
        s.add_player("alice", "Alice", [])
        s.add_player("bob", "Bob", [])
        coop = new_game("coop-game", "Coop Game")
        coop["is_coop"] = True
        indie = new_game("indie-game", "Indie Game")
        indie["is_indie"] = True
        s.add_game(coop)
        s.add_game(indie)
        s.save()

        self.key = SigningKey.generate()
        self.sent: list[tuple[str, str, Optional[d.Json]]] = []
        self.bot = d.Bot(
            Club(self.data, self.repo, remote=False),
            public_key=self.key.verify_key.encode().hex(),
            app_id="app", players={ALICE: "alice", BOB: "bob",
                                   ADMIN: "alice"},
            admins={ADMIN}, site_url="https://club.example",
            send=lambda m, u, b: self.sent.append((m, u, b)),
            spawn=lambda work: work())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def command(self, user: str, name: str, **opts: str) -> d.Json:
        return self.bot.handle({
            "type": d.COMMAND, "token": "tok",
            "member": {"user": {"id": user}},
            "data": {"name": name, "options": [
                {"name": k, "type": d.STRING, "value": v}
                for k, v in opts.items()]}})

    def click(self, user: str, custom_id: str,
              values: Optional[list[str]] = None) -> d.Json:
        data: d.Json = {"custom_id": custom_id}
        if values is not None:
            data["values"] = values
        return self.bot.handle({"type": d.COMPONENT, "token": "tok",
                                "member": {"user": {"id": user}},
                                "data": data})

    def reply(self) -> d.Json:
        """The last edit of the deferred reply."""
        edits = [b for m, u, b in self.sent if m == "PATCH"]
        assert edits[-1] is not None
        return edits[-1]

    def followups(self) -> list[str]:
        return [b["content"] for m, u, b in self.sent
                if m == "POST" and b is not None]

    def store(self) -> Store:
        return Store(self.data)

    def test_signature_checked_by_route(self) -> None:
        env = {"DISCORD_PUBLIC_KEY": self.key.verify_key.encode().hex(),
               "DISCORD_APPLICATION_ID": "app", "GAMECLUB_GIT_PUSH": "0"}
        with patch.dict("os.environ", env):
            client = create_app(self.data, self.repo).test_client()
        body = json.dumps({"type": d.PING}).encode()
        ts = "1700000000"
        sig = self.key.sign(ts.encode() + body).signature.hex()
        r = client.post("/discord/interactions", data=body, headers={
            "X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts})
        self.assertEqual(r.get_json(), {"type": d.PONG})
        r = client.post("/discord/interactions", data=body, headers={
            "X-Signature-Ed25519": "00" * 64,
            "X-Signature-Timestamp": ts})
        self.assertEqual(r.status_code, 401)

    def test_unknown_user_is_told_to_get_linked(self) -> None:
        r = self.command("333", "ready")
        self.assertIn("not linked", r["data"]["content"])

    def test_add_catalog_game_announces_publicly(self) -> None:
        r = self.command(ALICE, "add", game="coop-game")
        self.assertEqual(r["type"], d.DEFERRED_MESSAGE)
        self.assertEqual(r["data"]["flags"], d.EPHEMERAL)
        self.assertIn("Added **Coop Game**", self.reply()["content"])
        self.assertIn("**Alice** added **Coop Game** (1/10)",
                      self.followups()[0])
        self.assertEqual(self.store().submissions["alice"],
                         [{"game_id": "coop-game", "priority": False}])

    def test_add_new_game_with_steam_select(self) -> None:
        draft: GameRec = new_game("new-game", "New Game")
        draft["rawg_id"] = 77
        with patch("gameclub.rawg.fetch", return_value=draft), \
                patch("gameclub.prices.steam_search",
                      return_value=[{"appid": 5, "name": "New Game"}]):
            self.command(BOB, "add", game="new-game")
        select = self.reply()["components"][0]["components"][0]
        self.assertEqual(select["custom_id"], "addsel|77")
        self.assertEqual([o["value"] for o in select["options"]],
                         ["5", "none"])

        with patch("gameclub.rawg.fetch", return_value=draft) as fetch, \
                patch("gameclub.prices.steam_price",
                      return_value=None) as price:
            r = self.click(BOB, "addsel|77", ["5"])
        self.assertEqual(r["type"], d.DEFERRED_UPDATE)
        fetch.assert_called_with("77", unittest.mock.ANY)
        price.assert_called_once()
        self.assertEqual(self.store().game("new-game")["steam_appid"], 5)
        self.assertIn("**Bob** added **New Game**", self.followups()[-1])

    def test_add_button_without_price(self) -> None:
        draft: GameRec = new_game("new-game", "New Game")
        draft["steam_appid"] = 9
        with patch("gameclub.rawg.fetch", return_value=draft), \
                patch("gameclub.prices.steam_price") as price:
            self.click(BOB, "add|77|")
        price.assert_not_called()
        self.assertIsNone(self.store().game("new-game")["steam_appid"])

    def test_ready_needs_coop_then_announces(self) -> None:
        self.command(ALICE, "ready")
        self.assertIn("⚠️", self.reply()["content"])
        self.assertFalse(self.store().is_finalized("alice"))
        self.command(ALICE, "add", game="coop-game")
        self.click(ALICE, "ready")
        self.assertTrue(self.store().is_finalized("alice"))
        self.assertIn("**Alice** is ready (1/2)", self.followups()[-1])

    def test_star_and_remove_unready(self) -> None:
        self.command(ALICE, "add", game="coop-game")
        self.command(ALICE, "add", game="indie-game")
        self.command(ALICE, "ready")
        self.command(ALICE, "star", game="indie-game")
        s = self.store()
        self.assertFalse(s.is_finalized("alice"))
        self.assertTrue(s.submissions["alice"][1]["priority"])
        self.command(ALICE, "remove", game="indie-game")
        self.assertEqual(len(self.store().submissions["alice"]), 1)
        self.command(ALICE, "star", game="indie-game")
        self.assertIn("isn't on your list", self.reply()["content"])

    def test_draw_admin_only_with_spoilered_picks(self) -> None:
        for user in (ALICE, BOB):
            self.command(user, "add", game="coop-game")
        self.command(BOB, "add", game="indie-game")
        r = self.command(BOB, "draw")
        self.assertEqual(r["data"]["content"], "Admin only.")
        r = self.command(ADMIN, "draw")
        self.assertEqual(r["data"], {})  # public reply
        content = self.reply()["content"]
        self.assertIn("round 1** is drawn!", content)
        self.assertIn("https://club.example/round", content)
        self.assertIn("||", content)
        self.assertEqual(len(self.store().rounds), 1)

        self.command(ADMIN, "close")
        self.assertEqual(self.store().rounds[0]["status"], "discussed")
        self.command(ADMIN, "close")
        self.assertIn("no open round", self.reply()["content"])

    def test_status_and_list(self) -> None:
        self.command(ALICE, "add", game="coop-game")
        self.command(BOB, "status")
        content = self.reply()["content"]
        self.assertIn("⏳ Alice (1 games)", content)
        self.command(BOB, "list", player="alice")
        self.assertIn("**Coop Game** (co-op)", self.reply()["content"])

    def test_autocomplete_add_mixes_catalog_and_rawg(self) -> None:
        results: list[dict[str, Any]] = [
            {"slug": "coop-game", "name": "Coop Game", "released": None},
            {"slug": "game-two", "name": "Game Two",
             "released": "2020-01-01"}]
        with patch("gameclub.rawg.search", return_value=results):
            r = self.bot.handle({
                "type": d.AUTOCOMPLETE, "member": {"user": {"id": ALICE}},
                "data": {"name": "add", "options": [
                    {"name": "game", "value": "game", "focused": True}]}})
        choices = r["data"]["choices"]
        self.assertEqual([c["value"] for c in choices],
                         ["coop-game", "indie-game", "game-two"])
        self.assertEqual(choices[2]["name"], "Game Two (2020)")


if __name__ == "__main__":
    unittest.main()
