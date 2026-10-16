"""Game prices from the Steam store.

Uses store.steampowered.com/api/appdetails, which needs no key but is not
an officially documented API. Only covers games sold on Steam; others get
no price unless entered by hand.
"""

import json
import urllib.parse
import urllib.request
from typing import Any, Optional, TypedDict

from gameclub.store import PriceRec

APPDETAILS = "https://store.steampowered.com/api/appdetails"
STORESEARCH = "https://store.steampowered.com/api/storesearch/"


class SteamMatch(TypedDict):
    appid: int
    name: str


def _get(appid: int, country: str, filters: str) -> Any:
    query = urllib.parse.urlencode(
        {"appids": appid, "cc": country, "filters": filters})
    req = urllib.request.Request(f"{APPDETAILS}?{query}",
                                 headers={"User-Agent": "game-club"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def parse_price(appid: int, payload: Any, now: str) -> Optional[PriceRec]:
    """Price from an appdetails response, or None if there is none.

    Steam returns an empty data list for free games and games not on sale
    in the country; is_free tells them apart.
    """
    entry = payload.get(str(appid)) or {}
    if not entry.get("success"):
        return None
    data = entry.get("data")
    if not isinstance(data, dict):
        return None
    if data.get("is_free"):
        return PriceRec(amount=0.0, currency=None, formatted="free",
                        is_free=True, fetched_at=now)
    overview = data.get("price_overview")
    if not overview:
        return None
    return PriceRec(
        amount=overview["final"] / 100,
        currency=overview["currency"],
        formatted=overview.get("final_formatted") or
        f"{overview['final'] / 100:.2f} {overview['currency']}",
        is_free=False,
        fetched_at=now,
    )


def steam_price(appid: int, country: str, now: str) -> Optional[PriceRec]:
    price = parse_price(appid, _get(appid, country, "price_overview"), now)
    if price is None:
        price = parse_price(appid, _get(appid, country, "basic"), now)
    return price


def parse_search(payload: Any) -> list[SteamMatch]:
    """Candidate Steam store matches for a title.

    For the entry site to offer as a confirm-the-match step, not to
    auto-pick: title search is fuzzy and can return unrelated apps
    (soundtracks, DLC, community editions).
    """
    return [SteamMatch(appid=item["id"], name=item["name"])
            for item in payload.get("items", []) if item.get("type") == "app"]


def steam_search(title: str, country: str) -> list[SteamMatch]:
    query = urllib.parse.urlencode(
        {"term": title, "l": "english", "cc": country})
    req = urllib.request.Request(f"{STORESEARCH}?{query}",
                                 headers={"User-Agent": "game-club"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return parse_search(json.load(resp))
