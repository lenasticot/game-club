"""Load and save the club data kept as JSON files in data/.

club.json             players, sit-out rotations, country used for prices
games.json            game metadata, fetched once and cached
submissions.json      each player's current list: [{game_id, priority}]
rounds.json           drawn rounds, with the lists they were drawn from
player_secrets.json   discord_id/steam_id per player, gitignored (not
                      committed: players.name is a pseudonym, these aren't)
"""

import json
import os
from pathlib import Path
from typing import Any, Optional, TypedDict

from dataclasses import replace

from gameclub.draw import Game, Rotation


class PlayerRec(TypedDict):
    id: str
    name: str
    platforms: list[str]
    active: bool


class SecretRec(TypedDict):
    discord_id: Optional[str]
    steam_id: Optional[str]


class SubmissionEntry(TypedDict):
    game_id: str
    priority: bool


class PriceRec(TypedDict):
    amount: Optional[float]
    currency: Optional[str]
    formatted: str
    is_free: bool
    fetched_at: str


class GameRec(TypedDict):
    id: str
    title: str
    rawg_id: Optional[int]
    cover_url: Optional[str]
    genres: list[str]
    is_indie: bool
    is_coop: bool
    platforms: list[str]
    hours_main: Optional[float]
    rawg_playtime: Optional[int]
    steam_appid: Optional[int]
    price: Optional[PriceRec]
    metadata_fetched_at: Optional[str]


class PickRec(TypedDict):
    slot: str
    player: str
    game_id: str


class RoundRec(TypedDict):
    number: int
    seed: str
    drawn_at: str
    status: str
    meeting_date: Optional[str]
    sitting: list[str]
    lists: dict[str, list[str]]
    picks: list[PickRec]


class StoreError(Exception):
    """Raised for invalid changes to the club data."""


def new_game(game_id: str, title: str) -> GameRec:
    return GameRec(
        id=game_id, title=title, rawg_id=None, cover_url=None, genres=[],
        is_indie=False, is_coop=False, platforms=[], hours_main=None,
        rawg_playtime=None, steam_appid=None, price=None,
        metadata_fetched_at=None,
    )


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir
        club = _read(data_dir / "club.json", {})
        self.players: list[PlayerRec] = club.get("players", [])
        self.rotations_raw: list[dict[str, Any]] = club.get("rotations", [])
        self.price_country: str = club.get("price_country", "nl")
        # Players who flagged their list "done" for the next round. Cleared
        # when that round is drawn (gameclub.rounds.run_draw).
        self.finalized: list[str] = club.get("finalized", [])
        self.games: list[GameRec] = _read(data_dir / "games.json", [])
        self.submissions: dict[str, list[SubmissionEntry]] = _read(
            data_dir / "submissions.json", {})
        self.rounds: list[RoundRec] = _read(data_dir / "rounds.json", [])
        self.secrets: dict[str, SecretRec] = _read(
            data_dir / "player_secrets.json", {})

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        _write(self.dir / "club.json", {
            "players": self.players,
            "rotations": self.rotations_raw,
            "price_country": self.price_country,
            "finalized": self.finalized,
        })
        _write(self.dir / "games.json", self.games)
        _write(self.dir / "submissions.json", self.submissions)
        _write(self.dir / "rounds.json", self.rounds)
        _write(self.dir / "player_secrets.json", self.secrets)

    # Players

    def player(self, player_id: str) -> PlayerRec:
        for p in self.players:
            if p["id"] == player_id:
                return p
        raise StoreError(f"unknown player: {player_id}")

    def active_ids(self) -> list[str]:
        return [p["id"] for p in self.players if p["active"]]

    def is_finalized(self, player_id: str) -> bool:
        return player_id in self.finalized

    def set_finalized(self, player_id: str, value: bool) -> None:
        self.finalized = [p for p in self.finalized if p != player_id]
        if value:
            self.finalized.append(player_id)

    def clear_finalized(self) -> None:
        self.finalized = []

    def add_player(self, player_id: str, name: str,
                   platforms: list[str],
                   discord_id: Optional[str] = None,
                   steam_id: Optional[str] = None) -> None:
        if any(p["id"] == player_id for p in self.players):
            raise StoreError(f"player {player_id} already exists")
        self.players.append(PlayerRec(
            id=player_id, name=name, platforms=platforms, active=True))
        self.secrets[player_id] = SecretRec(
            discord_id=discord_id, steam_id=steam_id)
        if self.rotations_raw:
            order = list(self._current_order()) + [player_id]
            self._start_rotation(order)

    def deactivate_player(self, player_id: str) -> None:
        self.player(player_id)["active"] = False
        if self.rotations_raw:
            order = [p for p in self._current_order() if p != player_id]
            self._start_rotation(order)

    # Rotations

    def rotations(self) -> list[Rotation]:
        return [Rotation(r["start_round"], tuple(r["order"]))
                for r in self.rotations_raw]

    def _current_order(self) -> tuple[str, ...]:
        latest = max(self.rotations(), key=lambda r: r.start_round)
        return latest.order

    def _start_rotation(self, order: list[str]) -> None:
        """Start a new cycle at the next round (membership changed).

        Several changes before the same draw collapse into one rotation.
        """
        start = self.next_round_number()
        self.rotations_raw = [r for r in self.rotations_raw
                              if r["start_round"] != start]
        self.rotations_raw.append({"start_round": start, "order": order})

    def set_first_rotation(self, order: tuple[str, ...]) -> None:
        self.rotations_raw = [{"start_round": 1, "order": list(order)}]

    # Games

    def game(self, game_id: str) -> GameRec:
        for g in self.games:
            if g["id"] == game_id:
                return g
        raise StoreError(f"unknown game: {game_id}")

    def has_game(self, game_id: str) -> bool:
        return any(g["id"] == game_id for g in self.games)

    def add_game(self, game: GameRec) -> None:
        if self.has_game(game["id"]):
            raise StoreError(f"game {game['id']} already exists")
        self.games.append(game)

    def draw_game(self, game_id: str) -> Game:
        g = self.game(game_id)
        hours = g["hours_main"] or g["rawg_playtime"]
        return Game(g["id"], g["title"], is_indie=g["is_indie"],
                    is_coop=g["is_coop"], hours=hours)

    def list_games(self, player_id: str) -> list[Game]:
        return [replace(self.draw_game(e["game_id"]), priority=e["priority"])
                for e in self.submissions.get(player_id, [])]

    # Rounds

    def next_round_number(self) -> int:
        return len(self.rounds) + 1

    def played(self) -> frozenset[str]:
        return frozenset(p["game_id"] for r in self.rounds
                         for p in r["picks"])

    def round(self, number: int) -> RoundRec:
        for r in self.rounds:
            if r["number"] == number:
                return r
        raise StoreError(f"no round {number}")
