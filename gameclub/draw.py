"""Round draw: a fair lottery over players, then a game from each list.

Pure logic, no I/O. The same inputs (including the seed) always give the
same picks, so a stored draw can be checked against its seed.

Who: up to 3 different players, drawn at random. Each player's weight is
1 + the rounds they've waited since they were last picked, so being left
out raises your odds next time; everyone evens out over time. List size
doesn't matter: a 2-game list and a 10-game list weigh the same.
What: a random game from each picked player's own list (a starred game
gets extra weight), never one the club already played, never two long
games in the same round.
"""

import itertools
import random
from dataclasses import dataclass
from typing import Optional

GAMES_PER_ROUND = 3
MAX_LIST_SIZE = 10
LONG_GAME_HOURS = 30
PRIORITY_WEIGHT = 3


@dataclass(frozen=True)
class Game:
    id: str
    title: str
    is_indie: bool = False
    # Any multiplayer game, 2 players or more. Shown as info only; the
    # draw doesn't use it (co-op slot dropped 2026-11-03).
    is_coop: bool = False
    hours: Optional[float] = None
    # Set per submission: this player flagged this game for extra draw
    # weight, not a guarantee.
    priority: bool = False

    @property
    def is_long(self) -> bool:
        return self.hours is not None and self.hours > LONG_GAME_HOURS


@dataclass(frozen=True)
class Pick:
    player: str
    game: Game


@dataclass(frozen=True)
class PastRound:
    """Who took part in a round (picked or not) and who was picked."""
    took_part: frozenset[str]
    picked: frozenset[str]


class DrawError(Exception):
    """Raised when the inputs cannot produce a valid round."""


def waits(players: list[str], history: list[PastRound]) -> dict[str, int]:
    """Rounds each player has waited since they were last picked.

    Only rounds a player took part in count. Someone who never took part
    in any round (a new member) starts at the highest wait in the group,
    so they're likely picked soon after joining.
    """
    result: dict[str, int] = {}
    newcomers = []
    for p in players:
        if not any(p in r.took_part for r in history):
            newcomers.append(p)
            continue
        n = 0
        for r in reversed(history):
            if p in r.picked:
                break
            if p in r.took_part:
                n += 1
        result[p] = n
    top = max(result.values(), default=0)
    for p in newcomers:
        result[p] = top
    return result


def weight(wait: int) -> int:
    return 1 + wait


def pick_chances(player_waits: dict[str, int],
                 n: int = GAMES_PER_ROUND) -> dict[str, float]:
    """Each player's chance of being among the n drawn, from weights.

    Exact for the lottery itself; the real draw can still skip someone
    whose games all collide with others' (rare), so it's an indication.
    """
    players = sorted(player_waits)
    n = min(n, len(players))
    chances = {p: 0.0 for p in players}

    def walk(left: list[str], prob: float, depth: int) -> None:
        if depth == n:
            return
        total = sum(weight(player_waits[p]) for p in left)
        for p in left:
            q = prob * weight(player_waits[p]) / total
            chances[p] += q
            walk([o for o in left if o != p], q, depth + 1)

    walk(players, 1.0, 0)
    return chances


def validate_submission(
    player: str,
    games: list[Game],
    played: frozenset[str] = frozenset(),
) -> None:
    """Check one player's list against the club rules.

    It needs at least one game the club hasn't played yet, since played
    games are never drawn again.
    """
    if len(games) > MAX_LIST_SIZE:
        raise DrawError(
            f"{player} submitted {len(games)} games (max {MAX_LIST_SIZE})")
    if len({g.id for g in games}) != len(games):
        raise DrawError(f"{player} submitted the same game twice")
    if not any(g.id not in played for g in games):
        raise DrawError(f"{player}'s list has no unplayed game")


def _weighted_order(rng: random.Random,
                    player_waits: dict[str, int]) -> list[str]:
    """Players in a random order where heavier ones tend to come first.

    Drawing one by one without replacement, each time in proportion to
    weight; the first n of this order are the lottery's winners.
    """
    left = sorted(player_waits)
    order = []
    while left:
        weights = [weight(player_waits[p]) for p in left]
        p = rng.choices(left, weights=weights)[0]
        order.append(p)
        left.remove(p)
    return order


def _fill(
    rng: random.Random,
    players: tuple[str, ...],
    lists: dict[str, list[Game]],
    taken: set[str],
    has_long: bool,
) -> Optional[list[Pick]]:
    """Pick a game for each player, backtracking on collisions.

    Skips a second >30h game once one is already chosen this round.
    A priority-flagged game is repeated in the shuffle pool, giving it
    extra (not guaranteed) odds of being the one picked.
    """
    if not players:
        return []
    player, rest = players[0], players[1:]
    candidates = [g for g in lists[player]
                  if g.id not in taken and not (has_long and g.is_long)]
    weighted = []
    for g in candidates:
        weighted.append(g)
        if g.priority:
            weighted.extend([g] * (PRIORITY_WEIGHT - 1))
    rng.shuffle(weighted)
    seen: set[str] = set()
    for game in weighted:
        if game.id in seen:
            continue
        seen.add(game.id)
        taken.add(game.id)
        tail = _fill(rng, rest, lists, taken, has_long or game.is_long)
        taken.discard(game.id)
        if tail is not None:
            return [Pick(player=player, game=game)] + tail
    return None


def draw_round(
    round_number: int,
    seed: str,
    player_waits: dict[str, int],
    submissions: dict[str, list[Game]],
    played: frozenset[str] = frozenset(),
) -> list[Pick]:
    """Draw the picks for one round.

    player_waits: the players in the lottery (see waits()); each needs a
      list in submissions.
    played: ids of games the club has already drawn, never drawn again.

    Players with nothing left to draw are skipped. If the lottery's
    winners can't all get a distinct game (say two of them listed only
    the same one), the next players in the lottery's order are tried.
    """
    for p in player_waits:
        if p not in submissions:
            raise DrawError(f"no list submitted by {p}")
    lists = {p: sorted((g for g in submissions[p] if g.id not in played),
                       key=lambda g: g.id)
             for p in player_waits}
    eligible = {p: w for p, w in player_waits.items() if lists[p]}
    if not eligible:
        raise DrawError("nobody has an unplayed game on their list")
    n = min(GAMES_PER_ROUND, len(eligible))

    rng = random.Random(f"{seed}:{round_number}")
    order = _weighted_order(rng, eligible)
    # combinations() keeps the order, so the lottery's own winners come
    # first and later players only step in when they can't be filled.
    for players in itertools.combinations(order, n):
        picks = _fill(rng, players, lists, set(played), False)
        if picks is not None:
            return picks
    raise DrawError("no way to give each drawn player a distinct unplayed "
                    f"game (lists of: {', '.join(sorted(eligible))})")
