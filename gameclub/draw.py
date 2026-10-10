"""Round draw: who sits out, which slot each player fills, which game.

Pure logic, no I/O. The same inputs (including the seed) always give the
same picks, so anyone can re-run a draw to check it.
"""

import random
from dataclasses import dataclass
from enum import Enum

SLOTS_PER_ROUND = 3
MAX_LIST_SIZE = 10


class Slot(Enum):
    COOP = "coop"
    INDIE = "indie"
    FREE = "free"


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    is_indie: bool = False
    is_coop: bool = False

    def fits(self, slot: Slot) -> bool:
        if slot is Slot.COOP:
            return self.is_coop
        if slot is Slot.INDIE:
            return self.is_indie
        return True


@dataclass(frozen=True)
class Pick:
    slot: Slot
    player: str
    game: Game


class DrawError(Exception):
    """Raised when the inputs cannot produce a valid round."""


def sitters_for_round(order: list[str], round_number: int) -> list[str]:
    """Players sitting out this round, following the fixed rotation order.

    With 4 players one person sits out per round and everyone sits out
    exactly once every 4 rounds. With 3 players or fewer nobody sits out.
    """
    if round_number < 1:
        raise DrawError(f"round_number must be >= 1, got {round_number}")
    if len(set(order)) != len(order):
        raise DrawError("rotation order contains duplicate players")
    n_sitters = max(0, len(order) - SLOTS_PER_ROUND)
    start = (round_number - 1) * n_sitters
    return [order[(start + i) % len(order)] for i in range(n_sitters)]


def validate_submission(player: str, games: list[Game]) -> None:
    """Check one player's list against the club rules."""
    if not games:
        raise DrawError(f"{player} submitted an empty list")
    if len(games) > MAX_LIST_SIZE:
        raise DrawError(
            f"{player} submitted {len(games)} games (max {MAX_LIST_SIZE})")
    if len({g.id for g in games}) != len(games):
        raise DrawError(f"{player} submitted the same game twice")
    if not any(g.is_coop for g in games):
        raise DrawError(f"{player}'s list has no co-op game")
    if not any(g.is_indie for g in games):
        raise DrawError(f"{player}'s list has no indie game")


def draw_round(
    round_number: int,
    seed: str,
    order: list[str],
    submissions: dict[str, list[Game]],
    played: frozenset[str] = frozenset(),
) -> list[Pick]:
    """Draw the picks for one round.

    order: fixed rotation order of all active players.
    submissions: each player's list for this round.
    played: ids of games the club has already played, never drawn again.
    """
    missing = [p for p in order if p not in submissions]
    if missing:
        raise DrawError(f"no list submitted by: {', '.join(missing)}")
    for player in order:
        validate_submission(player, submissions[player])

    rng = random.Random(f"{seed}:{round_number}")
    sitting = set(sitters_for_round(order, round_number))
    pickers = [p for p in order if p not in sitting]

    slots = list(Slot)[:len(pickers)]
    rng.shuffle(slots)

    picks: list[Pick] = []
    taken: set[str] = set(played)
    # Fill the most constrained slots first so a game listed by two
    # players is less likely to leave a slot empty.
    for slot in (Slot.COOP, Slot.INDIE, Slot.FREE):
        if slot not in slots:
            continue
        player = pickers[slots.index(slot)]
        eligible = sorted(
            (g for g in submissions[player]
             if g.fits(slot) and g.id not in taken),
            key=lambda g: g.id,
        )
        if not eligible:
            raise DrawError(
                f"{player} has no eligible game for the {slot.value} slot")
        game = rng.choice(eligible)
        taken.add(game.id)
        picks.append(Pick(slot=slot, player=player, game=game))
    return picks
