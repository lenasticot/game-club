"""Parsing of RAWG and Steam responses, using hand-written samples.

The samples follow the documented response shapes; they are not copies
of live responses (RAWG needs a key that this repo doesn't have yet).
"""

import unittest

from gameclub.prices import parse_price, parse_search
from gameclub.rawg import parse_game

NOW = "2026-10-13T12:00:00+00:00"

DETAIL = {
    "id": 274755,
    "slug": "hades-2",
    "name": "Hades",
    "background_image": "https://media.rawg.io/x.jpg",
    "genres": [{"name": "Action"}, {"name": "Indie"}, {"name": "RPG"}],
    "tags": [{"slug": "singleplayer"}, {"slug": "roguelike"}],
    "platforms": [{"platform": {"name": "PC"}},
                  {"platform": {"name": "Nintendo Switch"}}],
    "playtime": 22,
}
STORES = {"results": [
    {"store_id": 6, "url": "https://www.nintendo.com/x"},
    {"store_id": 1, "url": "https://store.steampowered.com/app/1145360/"},
]}


class TestRawg(unittest.TestCase):
    def test_parse_game(self) -> None:
        g = parse_game(DETAIL, STORES, NOW)
        self.assertEqual(g["id"], "hades-2")
        self.assertEqual(g["genres"], ["Action", "RPG"])
        self.assertTrue(g["is_indie"])
        self.assertFalse(g["is_coop"])
        self.assertEqual(g["steam_appid"], 1145360)
        self.assertEqual(g["rawg_playtime"], 22)
        self.assertEqual(g["platforms"], ["PC", "Nintendo Switch"])

    def test_multiplayer_tag_sets_coop(self) -> None:
        detail = dict(DETAIL, tags=[{"slug": "online-co-op"}])
        self.assertTrue(parse_game(detail, {"results": []}, NOW)["is_coop"])


class TestSteamPrice(unittest.TestCase):
    def test_paid(self) -> None:
        payload = {"1145360": {"success": True, "data": {"price_overview": {
            "currency": "EUR", "initial": 2450, "final": 2450,
            "discount_percent": 0, "final_formatted": "24,50€"}}}}
        price = parse_price(1145360, payload, NOW)
        assert price is not None
        self.assertEqual(price["amount"], 24.5)
        self.assertEqual(price["formatted"], "24,50€")

    def test_free_needs_second_call(self) -> None:
        # With filters=price_overview Steam returns an empty list.
        self.assertIsNone(
            parse_price(570, {"570": {"success": True, "data": []}}, NOW))
        basic = {"570": {"success": True, "data": {"is_free": True}}}
        price = parse_price(570, basic, NOW)
        assert price is not None
        self.assertTrue(price["is_free"])


class TestSteamSearch(unittest.TestCase):
    def test_parse_search_keeps_only_apps(self) -> None:
        # Live sample from storesearch?term=portal+2, trimmed (checked
        # live 2026-10-16).
        payload = {"total": 10, "items": [
            {"type": "app", "name": "Portal 2", "id": 620},
            {"type": "app", "name": "Portal 2 Soundtrack", "id": 323180},
            {"type": "bundle", "name": "Portal Bundle", "id": 999},
        ]}
        matches = parse_search(payload)
        self.assertEqual(matches, [
            {"appid": 620, "name": "Portal 2"},
            {"appid": 323180, "name": "Portal 2 Soundtrack"},
        ])


if __name__ == "__main__":
    unittest.main()
