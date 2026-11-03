"""Running a round: draw it, record it, announce it."""

import json
import secrets
import urllib.request

from gameclub.draw import draw_round, pick_chances, waits
from gameclub.store import GameRec, PickRec, RoundRec, Store, StoreError

# Only rounds drawn with the old slot system (round 1) have slots.
SLOT_LABELS = {"coop": "Co-op", "indie": "Indie", "free": "Free pick"}


def new_seed() -> str:
    return secrets.token_hex(8)


def check_can_draw(store: Store) -> None:
    if store.rounds and store.rounds[-1]["status"] != "discussed":
        last = store.rounds[-1]["number"]
        raise StoreError(
            f"round {last} is not closed yet (run `round close {last}`)")
    if not store.active_ids():
        raise StoreError("no active players")


def next_waits(store: Store) -> dict[str, int]:
    """Rounds waited by each player in the next draw's lottery."""
    return waits(store.lottery_players(), store.history())


def chances(store: Store) -> dict[str, float]:
    """Each player's chance of being picked in the next draw."""
    return pick_chances(next_waits(store))


def run_draw(store: Store, seed: str, now: str) -> RoundRec:
    """Draw the next round and add it to the store (caller saves)."""
    check_can_draw(store)
    number = store.next_round_number()
    player_waits = next_waits(store)
    lists = {p: store.list_games(p) for p in player_waits}
    picks = draw_round(number, seed, player_waits, lists, store.played())
    picked = {p.player for p in picks}
    rec = RoundRec(
        number=number,
        seed=seed,
        drawn_at=now,
        status="drawn",
        meeting_date=None,
        sitting=sorted(p for p in player_waits if p not in picked),
        lists={p: [e["game_id"] for e in store.submissions[p]]
               for p in lists},
        picks=[PickRec(player=p.player, game_id=p.game.id) for p in picks],
    )
    store.rounds.append(rec)
    store.clear_finalized()
    return rec


def game_line(game: GameRec) -> str:
    bits = []
    if game["genres"]:
        bits.append(", ".join(game["genres"][:3]))
    hours = game["hours_main"] or game["rawg_playtime"]
    if hours:
        bits.append(f"~{hours:g}h")
    if game["price"]:
        bits.append(f"{game['price']['formatted']} on Steam "
                    f"({game['price']['fetched_at'][:10]})")
    return " · ".join(bits)


def announcement(store: Store, rec: RoundRec) -> str:
    def name(pid: str) -> str:
        return store.player(pid)["name"]

    lines = [f"**Game Club, round {rec['number']}**"]
    if rec["sitting"]:
        lines.append("Not picked this time: "
                     + ", ".join(map(name, rec["sitting"])))
    lines.append("")
    for pick in rec["picks"]:
        game = store.game(pick["game_id"])
        label = SLOT_LABELS.get(pick.get("slot", ""), "")
        prefix = f"{label}: " if label else "• "
        lines.append(f"{prefix}**{game['title']}** "
                     f"(from {name(pick['player'])})")
        detail = game_line(game)
        if detail:
            lines.append(f"  {detail}")
    lines.append("")
    lines.append(f"Seed `{rec['seed']}`, drawn {rec['drawn_at']}")
    return "\n".join(lines)


def post_to_discord(webhook_url: str, text: str) -> None:
    body = json.dumps({"content": text[:2000]}).encode()
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "game-club"})
    with urllib.request.urlopen(req, timeout=15):
        pass
