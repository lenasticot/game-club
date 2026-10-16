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
- **Max length rule**: no two long games (>30h, `hours_main`/`rawg_playtime`) in
  the same round. If a >30h game is already picked, skip other >30h games for
  remaining slots (don't block the round, just avoid the pair).
- **Priority star**: a player may flag one game per list as priority, giving it
  extra weight (not a guarantee) in the random pick from their list. No vote to
  remove a game from the pool — lists are player-edited anytime, that's enough.
- **Privacy**: repo stays public (needed for free GitHub Pages). Pseudonymize
  instead: `players.name` is a nickname/first name, not full name;
  `discord_id`/`steam_id` move out of the committed JSON into a local
  gitignored file, loaded at runtime, never pushed.
- **List entry**: a website, not Forms/CSV, not CLI — friends won't touch git
  or a terminal. Replaces the Forms→Sheet plan.
- **Entry-site identity**: Tricount-style, no passwords. Admin adds players
  via the CLI (unchanged); the site shows a name picker, stores the choice
  in a signed session cookie. The site URL itself is the "closed" gate.
- **Entry-site game add**: players add games themselves, not admin-only.
  Flow: search the local catalog first (with cover thumbnails), else search
  RAWG (thumbnails too) → pick a result → confirm a Steam price match
  (RAWG's own guess, or a fallback search against Steam's unofficial
  `storesearch` endpoint, checked live 2026-10-16) or skip price. No
  co-op/indie confirm step and no manual hours entry on add — RAWG's own
  guess is trusted as-is, hours shown as a RAWG-fetched indication only
  (rejected as unnecessary friction; player feedback 2026-10-16). Flags
  stay editable later via CLI `game set` (admin only) if wrong — whoever
  last edits a game's flags changes them for everyone (trust-based, fine
  for a 4-5 friend group).
- **Finalize button**: a player marks their list "done" for the next round
  (`club.json` `finalized: [player_id]`, cleared on `rounds.run_draw`). Any
  further list edit (add/remove/priority) clears their own finalized flag
  again. Requires the list to already pass `validate_submission` (≥1
  unplayed co-op, ≤10) — finalizing with fewer than 10 is fine, there's no
  minimum count.
- **Everyone's lists page** (`/players`): read-only, auto-refreshes via a
  small vanilla-JS poll against `/api/players` every 6s — no WebSocket/SSE,
  "live enough" for a few friends checking a casual list.
- **All games page** (`/games`): browse the full shared catalog (title,
  cover, flags, hours indication, played tag), separate from the per-list
  search results.
- **Render auto-deploy must stay off** for the entry-site service. The
  app's own writes push to GitHub (`git_sync`); with auto-deploy on, every
  single player action re-triggers a redeploy of the live service, which
  can crash mid-request (found live 2026-10-16, after ~3 game-adds).
  Deploys happen manually (dashboard → "Deploy latest commit") when *code*
  changes.
- **Entry-site writes**: Flask app wraps `gameclub.store.Store` directly
  (same code the CLI uses), then `git commit`+`push`es `data/` itself
  (`web/git_sync.py`), serialized with a lock. Keeps git as the audit trail
  without the admin manually committing every list change.
- **Hosting: Render free tier**, checked live 2026-10-16 (other free tiers
  ruled out: Fly.io has none since 2024, PythonAnywhere free has no SSH and
  an outbound whitelist, Railway free's $1/mo credit is too thin). Render
  free has no persistent disk (wiped on every spin-down/restart, sleeps
  after 15min idle, ~1min cold wake) but unrestricted outbound HTTPS. Design
  around it: clone `data/`+repo via **HTTPS + a GitHub token** (not SSH)
  into the ephemeral disk at boot; every write already commits+pushes
  within the same request, so GitHub is the real persistence layer and a
  fresh clone at each cold start is always current. `git_sync.py` needed no
  change (`repo_dir` is already a parameter) — this is a boot-script/deploy
  concern, not app code.
- **Static display site** stack: Astro (mostly-static game cards, round
  pages) with a Svelte island for the reveal animation — ships ~zero JS for
  the static 95%, Svelte's built-in transitions handle the animated reveal.
  Not started yet.

## Planned stack (MVP)

- Python, data as JSON files in the repo (git = history/audit trail).
- Draw logic as a pure function (`gameclub/draw.py`), reusable by a CLI now and
  maybe a Discord bot later.
- Lists and ratings entered via a small website (backend first, UI/design
  later), writing to the same JSON files so friends never touch git.
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
players      id, name (pseudonym), platforms[], active
             (+ rotation_order stored in data/club.json)
             discord_id?/steam_id? live in a local gitignored file, not committed
games        id (rawg slug), rawg_id, title, cover_url, genres[], is_indie,
             is_coop, platforms[], hours_main, rawg_playtime, steam_appid,
             price {amount, currency, formatted, is_free, fetched_at},
             metadata_fetched_at
submissions  player_id -> [{game_id, priority?}]  -- current lists (submissions.json)
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

Done: `gameclub/draw.py` (rotation cycles, backtracking draw, indie fallback,
max-length rule, priority-star weighting), `store.py` (JSON I/O,
`player_secrets.json` split out for discord_id/steam_id), `rawg.py`,
`prices.py` (Steam price + unofficial `storesearch`), `rounds.py` (draw,
announcement, Discord webhook), CLI (`python3 -m gameclub`, with
`--priority` on `list set` and `--discord-id`/`--steam-id` on `player add`).
Entry-site backend: `web/app.py` (Flask: whoami picker, list add/remove/
priority, game search+add from RAWG with Steam-match confirm) and
`web/git_sync.py` (commit+push `data/` after each write), with templates in
`web/templates/`. 33 tests passing (`tests/test_web.py` runs real git
commits against a throwaway repo, mocks RAWG/Steam), `mypy --strict` and
`flake8` clean (`gameclub`, `web`, `tests`). Manually smoke-tested the live
dev server end to end (whoami → add/remove/priority → catalog search → git
commit each step) in a scratch dir. Repo is public on GitHub, `main` pushed.

Next: write the Render boot script (clone via HTTPS+GitHub token, no SSH)
and `render.yaml`/service config → deploy → get a RAWG key for live
metadata → enter real players (pseudonyms) and lists through the site →
round 1 → static display site (Astro + Svelte island, not started).

Open: none blocking on the backend/hosting side. The Discord webhook post
is untested against a real webhook.

## Working notes

- CLI: `python3 -m gameclub <command>` (see README). Env vars: `RAWG_API_KEY`,
  `DISCORD_WEBHOOK_URL`.
- Python 3.10 (`/usr/bin/python3.10`) has mypy and flake8; run
  `python3 -m unittest -v`, `mypy --strict gameclub tests`, `flake8 gameclub tests`.
- Prefers plain prose, no overclaiming: flag gaps and untested assumptions.
