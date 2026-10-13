# Game Club

Personal project, unrelated to Codam. A video game club run like a book club:
every few months 3 games are drawn from the members' lists, everyone plays them,
then the group meets to discuss.

Repo: `git@github.com:lenasticot/game-club.git`, public, pushed from `main`.
The `gh` CLI is not installed; SSH auth to GitHub works.

## Decided

- **4 players** currently. Platforms don't play a big role: the selection is
  the same for everyone, so no platform filter. `platforms` is stored as plain
  data only.
- **Per-player lists, max 10 games**, editable between rounds. Each list needs
  at least 1 unplayed co-op game. Indie games are encouraged but not required.
- **3 slots per round**: co-op, indie, free. `indie` and `coop` are flags on a
  game, not exclusive categories; any game fits the free slot. "Co-op" means
  any multiplayer game (2+ players). Genres are real genres (horror,
  adventure...); "Indie" is a type, so it's moved out of RAWG genres into the
  flag. The draw backtracks over slot assignments and games, so a game on two
  lists never blocks a round. If no picker can fill indie, it becomes a second
  free slot.
- **3 games is a menu**: people may play just one of them. Show price
  (Steam, with the fetch date) so they can choose.
- **Fairness = fixed sit-out rotation.** A random order is drawn once at round 1;
  `order[(n - 1) % 4]` sits out round n, so everyone sits out exactly once per 4
  rounds. ("Whoever sat out last plays" alone was rejected: it doesn't guarantee
  a full cycle.) The other 3 get a random slot each, then a random fitting game
  from their own list. Generalizes: 3 players → nobody sits out, 5 → two sit out.
  New member → append to order, start a new rotation (`club.json` `rotations`,
  each with a `start_round`). Sitters don't need a list.
- **Draws are one-shot and public.** The seed is random (`secrets`) at draw
  time and stored with the round. No redraw command: `draw` refuses until the
  previous round is closed, and every draw is announced (Discord webhook if
  `DISCORD_WEBHOOK_URL` is set, else printed to paste). Any re-run would be
  announced again.
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
games        id (rawg slug), rawg_id, title, cover_url, genres[], is_indie,
             is_coop, platforms[], hours_main, rawg_playtime, steam_appid,
             price {amount, currency, formatted, is_free, fetched_at},
             metadata_fetched_at
submissions  player_id -> [game_id]          -- current lists (submissions.json)
rounds       number, seed, drawn_at, meeting_date, status (drawn|discussed),
             sitting[], lists (snapshot of lists used), picks[]
picks        slot (coop|indie|free), game_id, player_id -- inside rounds
ratings      round_id, game_id, player_id, score, finished (bool), comment
```

Derive fairness state from history; don't store counters.

## Caveats found so far

- HowLongToBeat has no official API; store `hours_main` manually or fetch once.
- Steam's old public wishlist endpoint was retired (~late 2024); an
  `IWishlistService/GetWishlist` Web API method reportedly replaces it. Unverified.
  Console wishlists have no API, so manual entry is the main path.
- RAWG needs a key (401 without). `rawg.py` parsing is tested on hand-written
  samples only, not live responses. Tag slugs for multiplayer are from memory.
- Steam `appdetails` is unofficial but works without a key (checked live
  2026-10-13); free games return an empty `data` with `filters=price_overview`,
  so a second `filters=basic` call checks `is_free`. Non-Steam games get no
  price unless added later.
- The round's `lists` snapshot stores ids only. If a game's flags are edited
  after the draw, re-running the seed may not reproduce it exactly.

## Status

Done: `gameclub/draw.py` (rotation cycles, backtracking draw, indie fallback),
`store.py` (JSON I/O), `rawg.py`, `prices.py` (Steam), `rounds.py` (draw,
announcement, Discord webhook), CLI (`python3 -m gameclub`). 22 tests passing,
`mypy --strict` and `flake8` clean. Repo is public on GitHub, `main` pushed.

Next: get a RAWG key and check `game add` against live data → enter real
players and lists → round 1 → static site → (maybe) Forms import, Discord bot.

Open: list size (5 or 10), max length filter, vote to remove a game from the
pool, Google Form vs CLI entry, privacy of player data in the public repo.
The Discord webhook post is untested against a real webhook.

## Working notes

- CLI: `python3 -m gameclub <command>` (see README). Env vars: `RAWG_API_KEY`,
  `DISCORD_WEBHOOK_URL`.
- Python 3.10 (`/usr/bin/python3.10`) has mypy and flake8; run
  `python3 -m unittest -v`, `mypy --strict gameclub tests`, `flake8 gameclub tests`.
- Prefers plain prose, no overclaiming: flag gaps and untested assumptions.
