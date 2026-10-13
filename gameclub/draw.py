"""Round draw: who sits out, which slot each player fills, which game.

Pure logic, no I/O. The same inputs (including the seed) always give the
same picks, so a stored draw can be checked against its seed.
"""

import itertools
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

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
    # Any multiplayer game, 2 players or more.
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


@dataclass(frozen=True)
class Rotation:
    """A sit-out order that applies from start_round until the next one."""
    start_round: int
    order: tuple[str, ...]


class DrawError(Exception):
    """Raised when the inputs cannot produce a valid round."""


def draw_rotation(players: list[str], seed: str) -> tuple[str, ...]:
    """Random sit-out order, drawn once when a cycle starts."""
    order = sorted(players)
    random.Random(f"{seed}:rotation").shuffle(order)
    return tuple(order)


def rotation_for_round(
    rotations: list[Rotation], round_number: int,
) -> Rotation:
    """The rotation in force for a round: the last one started by then."""
    started = [r for r in rotations if r.start_round <= round_number]
    if not started:
        raise DrawError(f"no rotation covers round {round_number}")
    return max(started, key=lambda r: r.start_round)


def sitters_for_round(
    rotations: list[Rotation], round_number: int,
) -> list[str]:
    """Players sitting out this round.

    Counted from the start of the rotation in force, so a membership
    change (which starts a new rotation) begins a fresh cycle. With 4
    players everyone sits out exactly once every 4 rounds; with 3 or
    fewer nobody sits out.
    """
    if round_number < 1:
        raise DrawError(f"round_number must be >= 1, got {round_number}")
    rotation = rotation_for_round(rotations, round_number)
    order = rotation.order
    if len(set(order)) != len(order):
        raise DrawError("rotation order contains duplicate players")
    n_sitters = max(0, len(order) - SLOTS_PER_ROUND)
    start = (round_number - rotation.start_round) * n_sitters
    return [order[(start + i) % len(order)] for i in range(n_sitters)]


def validate_submission(
    player: str,
    games: list[Game],
    played: frozenset[str] = frozenset(),
) -> None:
    """Check one player's list against the club rules.

    The co-op requirement counts only games the club has not played yet,
    since played games are never drawn again.
    """
    if not games:
        raise DrawError(f"{player} submitted an empty list")
    if len(games) > MAX_LIST_SIZE:
        raise DrawError(
            f"{player} submitted {len(games)} games (max {MAX_LIST_SIZE})")
    if len({g.id for g in games}) != len(games):
        raise DrawError(f"{player} submitted the same game twice")
    if not any(g.is_coop and g.id not in played for g in games):
        raise DrawError(f"{player}'s list has no unplayed co-op game")


def _fill(
    rng: random.Random,
    assignment: list[tuple[Slot, str]],
    lists: dict[str, list[Game]],
    taken: set[str],
) -> Optional[list[Pick]]:
    """Pick a game for each (slot, player), backtracking on collisions."""
    if not assignment:
        return []
    (slot, player), rest = assignment[0], assignment[1:]
    candidates = [g for g in lists[player]
                  if g.fits(slot) and g.id not in taken]
    rng.shuffle(candidates)
    for game in candidates:
        taken.add(game.id)
        tail = _fill(rng, rest, lists, taken)
        taken.discard(game.id)
        if tail is not None:
            return [Pick(slot=slot, player=player, game=game)] + tail
    return None


def draw_round(
    round_number: int,
    seed: str,
    rotations: list[Rotation],
    submissions: dict[str, list[Game]],
    played: frozenset[str] = frozenset(),
) -> list[Pick]:
    """Draw the picks for one round.

    rotations: sit-out orders over the club's history.
    submissions: each player's current list. Only the players who are
      not sitting out need one.
    played: ids of games the club has already drawn, never drawn again.

    Slots are assigned to players at random, then each player gets a
    random fitting game from their own list. If an assignment can't be
    completed (say two players listed the same game), other assignments
    are tried. If no player can fill the indie slot, it becomes a second
    free slot. The co-op slot is always filled.
    """
    sitting = set(sitters_for_round(rotations, round_number))
    order = rotation_for_round(rotations, round_number).order
    pickers = [p for p in order if p not in sitting]

    missing = [p for p in pickers if p not in submissions]
    if missing:
        raise DrawError(f"no list submitted by: {', '.join(missing)}")
    for player in pickers:
        validate_submission(player, submissions[player], played)

    rng = random.Random(f"{seed}:{round_number}")
    lists = {p: sorted(submissions[p], key=lambda g: g.id) for p in pickers}

    slot_options = [
        [Slot.COOP, Slot.INDIE, Slot.FREE],
        [Slot.COOP, Slot.FREE, Slot.FREE],
    ]
    for slots in slot_options:
        slots = slots[:len(pickers)]
        player_orders = list(itertools.permutations(pickers))
        rng.shuffle(player_orders)
        for players in player_orders:
            # Most constrained slots first: co-op, then indie, then free.
            assignment = list(zip(slots, players))
            picks = _fill(rng, assignment, lists, set(played))
            if picks is not None:
                return picks
    raise DrawError(
        "no way to fill every slot with distinct unplayed games "
        f"from the lists of: {', '.join(pickers)}")
