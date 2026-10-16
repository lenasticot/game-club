import unittest

from gameclub.draw import (
    DrawError,
    Game,
    Rotation,
    Slot,
    draw_rotation,
    draw_round,
    sitters_for_round,
)

ORDER = ("alice", "bob", "chloe", "dan")
ROTATIONS = [Rotation(1, ORDER)]


def make_list(player: str) -> list[Game]:
    return [
        Game(f"{player}-coop", "Co-op game", is_coop=True),
        Game(f"{player}-indie", "Indie game", is_indie=True),
        Game(f"{player}-other", "Other game"),
    ]


SUBMISSIONS = {p: make_list(p) for p in ORDER}


class TestRotation(unittest.TestCase):
    def test_four_players_each_sit_out_once_per_cycle(self) -> None:
        sat_out = [sitters_for_round(ROTATIONS, n)[0] for n in range(1, 5)]
        self.assertEqual(sat_out, list(ORDER))
        self.assertEqual(sitters_for_round(ROTATIONS, 5), ["alice"])

    def test_three_players_nobody_sits_out(self) -> None:
        self.assertEqual(sitters_for_round([Rotation(1, ORDER[:3])], 1), [])

    def test_five_players_two_sit_out(self) -> None:
        rotations = [Rotation(1, ORDER + ("eve",))]
        counts = {p: 0 for p in rotations[0].order}
        for n in range(1, 6):
            for p in sitters_for_round(rotations, n):
                counts[p] += 1
        self.assertEqual(set(counts.values()), {2})

    def test_new_rotation_starts_a_fresh_cycle(self) -> None:
        # eve joins before round 3: the new cycle starts with alice again.
        rotations = ROTATIONS + [Rotation(3, ORDER + ("eve",))]
        self.assertEqual(sitters_for_round(rotations, 2), ["bob"])
        self.assertEqual(sitters_for_round(rotations, 3), ["alice", "bob"])
        self.assertEqual(sitters_for_round(rotations, 4), ["chloe", "dan"])

    def test_draw_rotation_is_seeded(self) -> None:
        a = draw_rotation(list(ORDER), "x")
        self.assertEqual(a, draw_rotation(list(reversed(ORDER)), "x"))
        self.assertEqual(sorted(a), sorted(ORDER))


class TestDraw(unittest.TestCase):
    def test_sitter_gets_no_pick_and_slots_are_filled(self) -> None:
        picks = draw_round(2, "seed", ROTATIONS, SUBMISSIONS)
        players = {p.player for p in picks}
        self.assertEqual(len(picks), 3)
        self.assertNotIn("bob", players)
        self.assertEqual(len(players), 3)
        self.assertEqual({p.slot for p in picks}, set(Slot))
        for pick in picks:
            self.assertTrue(pick.game.fits(pick.slot))
            self.assertIn(pick.game, SUBMISSIONS[pick.player])

    def test_same_seed_same_result(self) -> None:
        a = draw_round(1, "round-01", ROTATIONS, SUBMISSIONS)
        b = draw_round(1, "round-01", ROTATIONS, SUBMISSIONS)
        self.assertEqual(a, b)

    def test_played_games_are_excluded(self) -> None:
        played = frozenset(g.id for p in ORDER for g in SUBMISSIONS[p]
                           if g.id.endswith("-other"))
        for n in range(1, 9):
            for pick in draw_round(n, "s", ROTATIONS, SUBMISSIONS, played):
                self.assertNotIn(pick.game.id, played)

    def test_list_without_coop_is_rejected(self) -> None:
        bad = dict(SUBMISSIONS)
        bad["dan"] = [g for g in make_list("dan") if not g.is_coop]
        with self.assertRaises(DrawError):
            draw_round(1, "s", ROTATIONS, bad)

    def test_list_whose_coop_games_were_played_is_rejected(self) -> None:
        with self.assertRaisesRegex(DrawError, "dan.*co-op"):
            draw_round(1, "s", ROTATIONS, SUBMISSIONS,
                       frozenset({"dan-coop"}))

    def test_missing_submission_is_rejected(self) -> None:
        partial = {p: SUBMISSIONS[p] for p in ORDER[1:]}
        with self.assertRaises(DrawError):
            draw_round(2, "s", ROTATIONS, partial)

    def test_sitter_needs_no_list(self) -> None:
        partial = {p: SUBMISSIONS[p] for p in ORDER if p != "bob"}
        self.assertEqual(len(draw_round(2, "s", ROTATIONS, partial)), 3)

    def test_shared_game_never_blocks_the_draw(self) -> None:
        # x is alice's only co-op game and bob's only indie game.
        x = Game("x", "Shared", is_coop=True, is_indie=True)
        subs = dict(SUBMISSIONS)
        subs["alice"] = [x, Game("a-indie", "", is_indie=True)]
        subs["bob"] = [x, Game("b-coop", "", is_coop=True)]
        for seed in range(300):
            picks = draw_round(4, str(seed), ROTATIONS, subs)
            self.assertEqual({p.slot for p in picks}, set(Slot))
            self.assertEqual(len({p.game.id for p in picks}), 3)

    def test_no_indie_anywhere_gives_two_free_slots(self) -> None:
        subs = {p: [g for g in make_list(p) if not g.is_indie]
                for p in ORDER}
        picks = draw_round(1, "s", ROTATIONS, subs)
        self.assertEqual(sorted(p.slot.value for p in picks),
                         ["coop", "free", "free"])

    def test_impossible_round_is_reported(self) -> None:
        # Every picker listed the same single co-op game.
        x = Game("x", "Shared", is_coop=True)
        subs = {p: [x] for p in ORDER}
        with self.assertRaises(DrawError):
            draw_round(1, "s", ROTATIONS, subs)

    def test_two_long_games_are_never_picked_together(self) -> None:
        # Round 3 sits out chloe: alice and bob both pick.
        subs = dict(SUBMISSIONS)
        subs["alice"] = [Game("alice-coop", "", is_coop=True, hours=40),
                         Game("alice-indie", "", is_indie=True),
                         Game("alice-other", "")]
        subs["bob"] = [Game("bob-coop", "", is_coop=True),
                       Game("bob-indie", "", is_indie=True),
                       Game("bob-other", "", hours=50)]
        for seed in range(200):
            picks = draw_round(3, str(seed), ROTATIONS, subs)
            self.assertLessEqual(sum(p.game.is_long for p in picks), 1)

    def test_priority_game_is_picked_more_often_but_not_always(self) -> None:
        subs = dict(SUBMISSIONS)
        a = Game("dan-a", "A", is_coop=True, priority=True)
        b = Game("dan-b", "B", is_coop=True)
        subs["dan"] = [a, b, Game("dan-indie", "", is_indie=True)]
        picked = {"dan-a": 0, "dan-b": 0}
        for seed in range(400):
            for pick in draw_round(1, str(seed), ROTATIONS, subs):
                if pick.game.id in picked:
                    picked[pick.game.id] += 1
        self.assertGreater(picked["dan-a"], picked["dan-b"])
        self.assertGreater(picked["dan-b"], 0)


if __name__ == "__main__":
    unittest.main()
