import unittest

from gameclub.draw import (
    DrawError,
    Game,
    Slot,
    draw_round,
    sitters_for_round,
)

ORDER = ["alice", "bob", "chloe", "dan"]


def make_list(player: str) -> list[Game]:
    return [
        Game(f"{player}-coop", "Co-op game", is_coop=True),
        Game(f"{player}-indie", "Indie game", is_indie=True),
        Game(f"{player}-other", "Other game"),
    ]


SUBMISSIONS = {p: make_list(p) for p in ORDER}


class TestRotation(unittest.TestCase):
    def test_four_players_each_sit_out_once_per_cycle(self) -> None:
        sat_out = [sitters_for_round(ORDER, n)[0] for n in range(1, 5)]
        self.assertEqual(sat_out, ORDER)
        self.assertEqual(sitters_for_round(ORDER, 5), ["alice"])

    def test_three_players_nobody_sits_out(self) -> None:
        self.assertEqual(sitters_for_round(ORDER[:3], 1), [])

    def test_five_players_two_sit_out(self) -> None:
        order = ORDER + ["eve"]
        counts = {p: 0 for p in order}
        for n in range(1, 6):
            for p in sitters_for_round(order, n):
                counts[p] += 1
        self.assertEqual(set(counts.values()), {2})


class TestDraw(unittest.TestCase):
    def test_sitter_gets_no_pick_and_slots_are_filled(self) -> None:
        picks = draw_round(2, "seed", ORDER, SUBMISSIONS)
        players = {p.player for p in picks}
        self.assertEqual(len(picks), 3)
        self.assertNotIn("bob", players)
        self.assertEqual(len(players), 3)
        self.assertEqual({p.slot for p in picks}, set(Slot))
        for pick in picks:
            self.assertTrue(pick.game.fits(pick.slot))
            self.assertIn(pick.game, SUBMISSIONS[pick.player])

    def test_same_seed_same_result(self) -> None:
        a = draw_round(1, "round-01", ORDER, SUBMISSIONS)
        b = draw_round(1, "round-01", ORDER, SUBMISSIONS)
        self.assertEqual(a, b)

    def test_played_games_are_excluded(self) -> None:
        played = frozenset(g.id for p in ORDER for g in SUBMISSIONS[p]
                           if g.id.endswith("-other"))
        for n in range(1, 9):
            for pick in draw_round(n, "s", ORDER, SUBMISSIONS, played):
                self.assertNotIn(pick.game.id, played)

    def test_list_without_coop_is_rejected(self) -> None:
        bad = dict(SUBMISSIONS)
        bad["dan"] = [g for g in make_list("dan") if not g.is_coop]
        with self.assertRaises(DrawError):
            draw_round(1, "s", ORDER, bad)

    def test_missing_submission_is_rejected(self) -> None:
        partial = {p: SUBMISSIONS[p] for p in ORDER[:3]}
        with self.assertRaises(DrawError):
            draw_round(1, "s", ORDER, partial)


if __name__ == "__main__":
    unittest.main()
