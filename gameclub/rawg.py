"""Game metadata from RAWG (https://rawg.io/apidocs).

Called once when a game is added, never at draw time. Needs an API key in
the RAWG_API_KEY environment variable.

The response fields used here (genres, tags, platforms, playtime, stores)
follow RAWG's documented schema but have not been checked against a live
response yet.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

from gameclub.store import GameRec, new_game

API = "https://api.rawg.io/api"
STEAM_STORE_ID = 1

# RAWG tag slugs that mean the game can be played with others.
MULTIPLAYER_TAGS = frozenset({
    "multiplayer", "co-op", "cooperative", "online-co-op", "local-co-op",
    "online-multiplayer", "local-multiplayer", "split-screen", "pvp",
    "online-pvp", "massively-multiplayer",
})


class RawgError(Exception):
    pass


def _get(path: str, params: Optional[dict[str, str]] = None) -> Any:
    key = os.environ.get("RAWG_API_KEY")
    if not key:
        raise RawgError("set RAWG_API_KEY (free key from rawg.io/apidocs)")
    query = urllib.parse.urlencode({**(params or {}), "key": key})
    req = urllib.request.Request(f"{API}{path}?{query}",
                                 headers={"User-Agent": "game-club"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def search(query: str) -> list[dict[str, Any]]:
    data = _get("/games", {"search": query, "page_size": "8"})
    return [{"id": r["id"], "slug": r["slug"], "name": r["name"],
             "released": r.get("released"),
             "background_image": r.get("background_image")}
            for r in data.get("results", [])]


def fetch(id_or_slug: str, now: str) -> GameRec:
    detail = _get(f"/games/{urllib.parse.quote(id_or_slug)}")
    stores = _get(f"/games/{detail['id']}/stores")
    return parse_game(detail, stores, now)


def steam_appid(stores: Any) -> Optional[int]:
    for s in stores.get("results", []):
        if s.get("store_id") != STEAM_STORE_ID:
            continue
        m = re.search(r"store\.steampowered\.com/app/(\d+)", s.get("url", ""))
        if m:
            return int(m.group(1))
    return None


def parse_game(detail: Any, stores: Any, now: str) -> GameRec:
    """Turn RAWG responses into a game record.

    "Indie" is a genre on RAWG but a flag here, so it is moved out of
    genres. The indie and co-op flags are only defaults; check them and
    fix with `game set`.
    """
    genre_names = [g["name"] for g in detail.get("genres", [])]
    tags = {t["slug"] for t in detail.get("tags", [])}
    game = new_game(detail["slug"], detail["name"])
    game["rawg_id"] = detail["id"]
    game["cover_url"] = detail.get("background_image")
    game["genres"] = [g for g in genre_names if g != "Indie"]
    game["is_indie"] = "Indie" in genre_names
    game["is_coop"] = bool(tags & MULTIPLAYER_TAGS)
    game["platforms"] = [p["platform"]["name"]
                         for p in detail.get("platforms") or []]
    game["rawg_playtime"] = detail.get("playtime") or None
    game["steam_appid"] = steam_appid(stores)
    game["metadata_fetched_at"] = now
    return game
