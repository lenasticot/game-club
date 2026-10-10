# Game Club

A video game club run like a book club: each round, 3 games are drawn from
the members' lists, everyone plays them, then we meet to discuss.

## Rules

- Each player submits a list of up to 10 games before every round, which they
  can update between rounds. Each list needs at least one co-op and one indie
  game.
- Every round has 3 slots: co-op, indie, free.
- A fixed rotation order decides who sits out. With 4 players, one person sits
  out per round and everyone sits out exactly once every 4 rounds.
- The 3 remaining players get one slot each at random, then one game from
  their own list that fits that slot.
- Draws are seeded: re-running a draw with the same seed gives the same result.

## Layout

```
gameclub/draw.py   draw logic (pure functions, no I/O)
tests/             unit tests
data/              club data as JSON (players, games, rounds, submissions)
```

## Development

```
python3 -m unittest -v
python3 -m mypy --strict gameclub tests
python3 -m flake8 gameclub tests
```
