# Game Club

Personal project, unrelated to Codam. A video game club run like a book club:
every few months 3 games are drawn from the members' lists, everyone plays them,
then the group meets to discuss.

Repo: `git@github.com:lenasticot/game-club.git` (remote set; check whether the
GitHub repo has been created and pushed). The `gh` CLI is not installed; SSH
auth to GitHub works.

## Decided

- **4 players** currently. Platforms differ between players. Either the rule is
  "only list games everyone can play" (checked by hand when submitting) or a
  platform filter gets added later. Store `platforms` per player anyway.
- **Per-player lists, max 10 games**, submitted before each round and editable
  between rounds. Each list needs at least 1 co-op and 1 indie game, which
  guarantees every slot can be filled (no backtracking needed).
- **3 slots per round**: co-op, indie, free. `indie` and `coop` are tags on a
  game, not exclusive categories; any game fits the free slot.
- **Fairness = fixed sit-out rotation.** A random order is drawn once at round 1;
  `order[(n - 1) % 4]` sits out round n, so everyone sits out exactly once per 4
  rounds. ("Whoever sat out last plays" alone was rejected: it doesn't guarantee
  a full cycle.) The other 3 get a random slot each, then a random fitting game
  from their own list. Generalizes: 3 players → nobody sits out, 5 → two sit out.
  New member → append to order, start a new cycle.
- **Seeded draws** (`seed:round_number`), so anyone can re-run and verify.
- Games already played by the club are never drawn again; the same game can't be
  picked twice in a round.

## Planned stack (MVP)

- Python, data as JSON files in the repo (git = history/audit trail).
- Draw logic as a pure function (`gameclub/draw.py`), reusable by a CLI now and
  maybe a Discord bot later.
- Lists and ratings entered via Google Forms → Sheet → a script pulls the CSV
  into JSON, so friends never touch git.
- Game metadata from RAWG (simpler key) or IGDB (needs Twitch OAuth, server-side
  only). Fetch once when a game is added and cache it; never call APIs at draw
  time or from the site.
- Static site on GitHub Pages (needs a public repo on a free account): a card
  per game (cover, genre, length, proposer), a reveal animation that plays an
  already-computed draw, a page per round with ratings.
- Discussion: a Discord thread per round, linked from the site. Don't build a
  discussion page.

## Data model

```
players      id, name, platforms[], discord_id?, steam_id?, active
             (+ rotation_order stored in data/club.json)
games        id (rawg id), title, cover_url, genres[], is_indie, is_coop,
             crossplay?, platforms[], hours_main, metadata_fetched_at
submissions  round_id, player_id, game_id     -- per-round lists, copied forward
rounds       id, seed, drawn_at, meeting_date, status (drawn|playing|discussed)
picks        round_id, slot (coop|indie|free), game_id, player_id
ratings      round_id, game_id, player_id, score, finished (bool), comment
```

Derive fairness state from history; don't store counters.

## Caveats found so far

- HowLongToBeat has no official API; store `hours_main` manually or fetch once.
- Steam's old public wishlist endpoint was retired (~late 2024); an
  `IWishlistService/GetWishlist` Web API method reportedly replaces it. Unverified.
  Console wishlists have no API, so manual entry is the main path.
- For co-op, "on everyone's platform" isn't enough: needs crossplay or a shared
  platform.

## Status

Done: `gameclub/draw.py` (rotation, list validation, `draw_round`), 8 unit tests
passing, `mypy --strict` and `flake8` clean, empty JSON files in `data/`.

Next: CLI that loads `data/*.json` and runs a round → RAWG metadata fetch →
static site → Forms/Sheet import → (maybe) Discord bot.

Open: list size (5 or 10), whether to have a max length filter, Google Form vs
editing JSON directly, the actual rotation order.

## Working notes

- Python 3.10 (`/usr/bin/python3.10`) has mypy and flake8; run
  `python3 -m unittest -v`, `mypy --strict gameclub tests`, `flake8 gameclub tests`.
- Prefers plain prose, no overclaiming: flag gaps and untested assumptions.
