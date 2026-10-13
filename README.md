# Game Club

A video game club run like a book club: each round, 3 games are drawn from
the members' lists, everyone plays them, then we meet to discuss.

## Rules

- Each player keeps a list of up to 10 games, which they can update between
  rounds. Each list needs at least one co-op (any multiplayer) game. Indie
  games are encouraged.
- Every round has 3 slots: co-op, indie, free. If nobody drawn has an indie
  game left, the indie slot becomes a second free slot.
- A fixed rotation order, drawn at round 1, decides who sits out. With 4
  players, one person sits out per round and everyone sits out exactly once
  every 4 rounds. A new member starts a new cycle.
- The remaining players get one slot each at random, then one game from
  their own list that fits that slot. Games already drawn never come back.
- The 3 games are a menu: play one, two or all three.
- Each draw uses a fresh random seed, is stored in `data/rounds.json` and is
  announced to everyone. There is no redraw.

## Usage

```
python3 -m gameclub player add alice Alice --platform PC
python3 -m gameclub game search "hades"          # needs RAWG_API_KEY
python3 -m gameclub game add hades               # RAWG slug; fetches price
python3 -m gameclub game add mygame --manual --title "My Game" --coop
python3 -m gameclub game set hades --no-indie    # fix flags, --hours, ...
python3 -m gameclub list set alice hades mygame  # replace Alice's list
python3 -m gameclub status                       # who sits out, list checks
python3 -m gameclub draw                         # draw + announce
python3 -m gameclub round close 1                # after the meeting
```

Set `DISCORD_WEBHOOK_URL` to post draws to Discord. Commit `data/` after
each change.

## Layout

```
gameclub/draw.py     draw logic (pure functions, no I/O)
gameclub/store.py    JSON data files
gameclub/rounds.py   running and announcing a round
gameclub/rawg.py     game metadata (RAWG)
gameclub/prices.py   prices (Steam store)
gameclub/cli.py      command line
tests/               unit tests
data/                club data as JSON
```

## Development

```
python3 -m unittest -v
python3 -m mypy --strict gameclub tests
python3 -m flake8 gameclub tests
```
