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

## Entry site

A small Flask app lets players pick their name (no password, like a
Tricount group link — add players via the CLI first), edit their own list,
and add games (search the catalog, else RAWG, confirm flags/hours/Steam
match). Every write commits+pushes `data/` itself.

```
pip install -r requirements-web.txt
FLASK_SECRET_KEY=<random> python3 -m web.app   # dev server, localhost:5000
```

Env vars: `GAMECLUB_DATA` (default `data`), `GAMECLUB_GIT_PUSH=0` to disable
the push (commits still happen), `FLASK_SECRET_KEY` (required to keep
sessions valid across restarts).

### Deploying (Render, free tier)

Render's free web services have no persistent disk (wiped on every restart
or spin-down after 15min idle), so `render-start.sh` re-clones `data/` and
its git history fresh on every boot over HTTPS with a token, instead of
relying on whatever Render itself checked out to build the app. Every
write already commits+pushes before responding, so GitHub stays the real
source of truth and a fresh clone is always current. One-time setup:

1. Push this repo to GitHub (already done, `main`).
2. On [render.com](https://render.com): New → Blueprint, point it at this
   repo. It reads `render.yaml` and creates the web service.
3. In the Render dashboard, set these env vars (they stay secret, never go
   in the repo):
   - `GITHUB_TOKEN` — a GitHub **fine-grained personal access token**,
     scoped to only this repo, with Contents: Read and write permission.
   - `FLASK_SECRET_KEY` — any random string (e.g. `openssl rand -hex 32`).
   - `RAWG_API_KEY` — your RAWG key, for the "find online" game search.
4. Deploy. First load after idle takes about a minute (cold start +
   re-clone); fine for occasional use by a few friends.

I can't create the Render account, GitHub token, or set secrets for you —
those need your own logins.

## Layout

```
gameclub/draw.py     draw logic (pure functions, no I/O)
gameclub/store.py    JSON data files
gameclub/rounds.py   running and announcing a round
gameclub/rawg.py     game metadata (RAWG)
gameclub/prices.py   prices + search (Steam store)
gameclub/cli.py      command line
web/app.py           entry site (Flask)
web/git_sync.py      commit+push data/ after a web write
tests/               unit tests
data/                club data as JSON
```

## Development

```
python3 -m unittest -v
python3 -m mypy --strict gameclub web tests
python3 -m flake8 gameclub web tests
```

`web` needs Flask (`pip install -r requirements-web.txt`) for the tests and
type checks to pass.
