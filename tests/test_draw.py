import unittest
from collections import Counter

from gameclub.draw import (
    DrawError,
    Game,
    PastRound,
    draw_round,
    pick_chances,
    validate_submission,
    waits,
)

PLAYERS = ["alice", "bob", "chloe", "dan"]


def make_list(player: str, n: int = 3) -> list[Game]:
    return [Game(f"{player}-{i}", f"{player} {i}") for i in range(n)]


def subs() -> dict[str, list[Game]]:
    return {p: make_list(p) for p in PLAYERS}


def zero_waits() -> dict[str, int]:
    return {p: 0 for p in PLAYERS}


def past(took_part: list[str], picked: list[str]) -> PastRound:
    return PastRound(frozenset(took_part), frozenset(picked))


class TestWaits(unittest.TestCase):
    def test_counts_rounds_since_last_picked(self) -> None:
        history = [past(PLAYERS, ["alice", "bob", "chloe"]),
                   past(PLAYERS, ["alice", "bob", "dan"])]
        self.assertEqual(waits(PLAYERS, history),
                         {"alice": 0, "bob": 0, "chloe": 1, "dan": 0})

    def test_never_picked_keeps_counting(self) -> None:
        history = [past(PLAYERS, ["alice", "bob", "chloe"])] * 3
        self.assertEqual(waits(PLAYERS, history)["dan"], 3)

    def test_newcomer_starts_at_highest_wait(self) -> None:
        history = [past(PLAYERS, ["alice", "bob", "chloe"])] * 2
        w = waits(PLAYERS + ["eve"], history)
        self.assertEqual(w["eve"], 2)

    def test_rounds_skipped_dont_count(self) -> None:
        # dan wasn't in round 2 (no list): only round 1 counts.
        history = [past(PLAYERS, ["alice", "bob", "chloe"]),
                   past(PLAYERS[:3], ["alice", "bob", "chloe"])]
        self.assertEqual(waits(PLAYERS, history)["dan"], 1)


class TestChances(unittest.TestCase):
    def test_equal_weights_give_equal_chances(self) -> None:
        c = pick_chances(zero_waits())
        for p in PLAYERS:
            self.assertAlmostEqual(c[p], 0.75)

    def test_waiting_raises_your_chance(self) -> None:
        # Left out once (weight 2 vs 1): left out again only 10%.
        c = pick_chances({**zero_waits(), "dan": 1})
        self.assertAlmostEqual(c["dan"], 0.9)
        self.assertAlmostEqual(sum(c.values()), 3)

    def test_three_or_fewer_players_are_always_picked(self) -> None:
        c = pick_chances({"alice": 0, "bob": 5})
        self.assertEqual(c, {"alice": 1.0, "bob": 1.0})


class TestDraw(unittest.TestCase):
    def test_three_different_players_one_game_each(self) -> None:
        picks = draw_round(1, "seed", zero_waits(), subs())
        self.assertEqual(len(picks), 3)
        self.assertEqual(len({p.player for p in picks}), 3)
        for pick in picks:
            self.assertTrue(pick.game.id.startswith(pick.player))

    def test_same_seed_same_picks(self) -> None:
        a = draw_round(1, "seed", zero_waits(), subs())
        b = draw_round(1, "seed", zero_waits(), subs())
        self.assertEqual(a, b)

    def test_list_size_doesnt_change_odds(self) -> None:
        lists = subs()
        lists["alice"] = make_list("alice", 10)
        lists["bob"] = make_list("bob", 1)
        counts: Counter[str] = Counter()
        for i in range(2000):
            for pick in draw_round(1, f"s{i}", zero_waits(), lists):
                counts[pick.player] += 1
        for p in PLAYERS:
            self.assertAlmostEqual(counts[p] / 2000, 0.75, delta=0.05)

    def test_long_wait_is_picked_more(self) -> None:
        w = {**zero_waits(), "dan": 1}
        left_out = 0
        for i in range(2000):
            picks = draw_round(1, f"s{i}", w, subs())
            left_out += "dan" not in {p.player for p in picks}
        self.assertAlmostEqual(left_out / 2000, 0.10, delta=0.03)

    def test_played_games_are_never_drawn(self) -> None:
        played = frozenset(g.id for games in subs().values()
                           for g in games[:2])
        for i in range(50):
            for pick in draw_round(1, f"s{i}", zero_waits(), subs(),
                                   played):
                self.assertNotIn(pick.game.id, played)

    def test_player_with_only_played_games_is_skipped(self) -> None:
        played = frozenset(g.id for g in make_list("dan"))
        for i in range(50):
            picks = draw_round(1, f"s{i}", zero_waits(), subs(), played)
            self.assertNotIn("dan", {p.player for p in picks})

    def test_shared_game_never_blocks_a_round(self) -> None:
        x = Game("x", "Shared")
        lists = {"alice": [x], "bob": [x], "chloe": make_list("chloe"),
                 "dan": make_list("dan")}
        for i in range(50):
            picks = draw_round(1, f"s{i}", zero_waits(), lists)
            ids = [p.game.id for p in picks]
            self.assertEqual(len(ids), len(set(ids)))

    def test_no_two_long_games(self) -> None:
        lists = {p: [Game(f"{p}-long", "", hours=40),
                     Game(f"{p}-short", "", hours=5)] for p in PLAYERS}
        for i in range(50):
            picks = draw_round(1, f"s{i}", zero_waits(), lists)
            self.assertLessEqual(sum(p.game.is_long for p in picks), 1)

    def test_priority_star_gets_extra_weight(self) -> None:
        lists = {p: [Game(f"{p}-a", "A", priority=True),
                     Game(f"{p}-b", "B")] for p in PLAYERS}
        starred = sum(p.game.id.endswith("-a")
                      for i in range(500)
                      for p in draw_round(1, f"s{i}", zero_waits(), lists))
        # 3:1 weight, so ~75% of picks.
        self.assertGreater(starred / 1500, 0.65)

    def test_fewer_than_three_players_draws_fewer_games(self) -> None:
        w = {"alice": 0, "bob": 0}
        picks = draw_round(1, "seed", w, subs())
        self.assertEqual({p.player for p in picks}, {"alice", "bob"})

    def test_nothing_to_draw_is_an_error(self) -> None:
        with self.assertRaises(DrawError):
            draw_round(1, "seed", {"alice": 0}, {"alice": []})


class TestValidate(unittest.TestCase):
    def test_too_many_games(self) -> None:
        with self.assertRaises(DrawError):
            validate_submission("a", make_list("a", 11))

    def test_duplicates(self) -> None:
        g = Game("x", "X")
        with self.assertRaises(DrawError):
            validate_submission("a", [g, g])

    def test_needs_an_unplayed_game(self) -> None:
        games = make_list("a", 2)
        with self.assertRaises(DrawError):
            validate_submission("a", games,
                                frozenset(g.id for g in games))
        with self.assertRaises(DrawError):
            validate_submission("a", [])
        validate_submission("a", games, frozenset({games[0].id}))


if __name__ == "__main__":
    unittest.main()
