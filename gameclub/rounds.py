"""Running a round: draw it, record it, announce it."""

import json
import secrets
import urllib.request

from gameclub.draw import (
    Rotation,
    draw_rotation,
    draw_round,
    rotation_for_round,
    sitters_for_round,
)
from gameclub.store import GameRec, PickRec, RoundRec, Store, StoreError

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


def preview_rotations(store: Store) -> list[Rotation]:
    """The rotations a draw would use, without saving a first one.

    Before round 1 there is no order yet; a provisional one (not the one
    the real draw will produce) is used only for checks.
    """
    if store.rotations_raw:
        return store.rotations()
    return [Rotation(1, tuple(sorted(store.active_ids())))]


def run_draw(store: Store, seed: str, now: str) -> RoundRec:
    """Draw the next round and add it to the store (caller saves).

    On round 1 the sit-out order is drawn from the same seed.
    """
    check_can_draw(store)
    number = store.next_round_number()
    if not store.rotations_raw:
        store.set_first_rotation(draw_rotation(store.active_ids(), seed))
    rotations = store.rotations()
    order = rotation_for_round(rotations, number).order
    lists = {p: store.list_games(p) for p in order if p in store.submissions}
    picks = draw_round(number, seed, rotations, lists, store.played())
    rec = RoundRec(
        number=number,
        seed=seed,
        drawn_at=now,
        status="drawn",
        meeting_date=None,
        sitting=sitters_for_round(rotations, number),
        lists={p: list(store.submissions[p]) for p in lists},
        picks=[PickRec(slot=p.slot.value, player=p.player,
                       game_id=p.game.id) for p in picks],
    )
    store.rounds.append(rec)
    return rec


def _game_line(game: GameRec) -> str:
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
        lines.append("Sitting out: " + ", ".join(map(name, rec["sitting"])))
    lines.append("")
    for pick in rec["picks"]:
        game = store.game(pick["game_id"])
        lines.append(f"{SLOT_LABELS[pick['slot']]}: **{game['title']}** "
                     f"(from {name(pick['player'])})")
        detail = _game_line(game)
        if detail:
            lines.append(f"  {detail}")
    if not any(p["slot"] == "indie" for p in rec["picks"]):
        lines.append("(No indie game available, so two free picks.)")
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
