# Game Club

A video game club that works like a book club. Every few months, three
games are drawn from the members' wishlists, everyone plays them, and the
group meets to talk about them.

This repo holds everything that runs the club: the draw rules, a small
website where members manage their lists and watch the draw, and a
Discord integration so most of it can be done without leaving the chat.
It is built for a group of friends (4 to 5 people), runs on free hosting,
and keeps all its data as JSON files in this repo, so git is the history.

## How a round works

1. **Everyone keeps a list** of up to 10 games they'd like the club to
   play. Lists can change any time between rounds. Indie games are
   encouraged.
2. **Players mark their list as ready** when they're done editing it.
   Changing the list afterwards un-marks it.
3. **The draw** picks 3 games from 3 different people's lists.
4. **The 3 games are a menu.** Nobody has to play all of them; prices
   (from Steam, with the date they were fetched) help people choose.
5. **The group meets**, discusses, and the admin closes the round. Lists
   open for the next one.

### Draw rules: a fair lottery

The draw has to be random (otherwise it's no fun) and fair (otherwise
someone's taste never comes up). It works in two steps:

1. **Who**: 3 different people are drawn at random, never 2 games from
   the same person. Each person's weight is **1 + the number of rounds
   they've waited since they were last picked**, so being left out raises
   your odds next time. With 4 people, someone left out has a 90% chance
   to be picked the next round instead of 75%; being left out twice in a
   row drops from 25% (pure chance) to 10%. Over time everyone gets
   picked about equally, but nobody knows in advance who will be.
2. **What**: a random game from each picked person's list. **List size
   doesn't matter**: the person is drawn first, so a 2-game list has the
   same odds as a 10-game list.

More rules:
- **Priority star**: each player can star one game on their list. It gets
  3x the weight in the pick from their list, not a guarantee.
- **No two long games** (over 30 hours) in the same round.
- A game is never drawn twice, ever. If two picked people listed the same
  game, the draw works around it.
- **Any group size**: it's always "3 people among everyone with a list".
  A new member starts with the highest weight in the group, so they're
  likely in their first round. Everyone's current odds are shown in
  Discord's `/status` and the CLI's `status`.
- **Draws are one-shot and public.** Each uses a fresh random seed, stored
  with the round, and is announced right away. There is no redraw, and a
  new draw is refused until the previous round is closed.

## How members use it

Players never touch git or a terminal. They use either:

**The website** (Flask):
- pick their name (no passwords: the site's URL is the shared secret, like
  a Tricount link)
- search for a game (club catalog first, then [RAWG](https://rawg.io)),
  confirm its Steam page for the price, add it to their list
- star a game, remove one, mark their list ready
- `/players`: everyone's lists, refreshed live
- `/games`: the whole club catalog
- `/round`: the draw reveal, a slot-machine reel of cover art per slot
  that lands on the drawn game

**Discord slash commands**:

| Command | What it does |
|---|---|
| `/add game:` | add a game (suggestions as you type, from the catalog and RAWG) |
| `/remove game:` | remove a game from your list |
| `/star game:` | make a game your priority |
| `/ready` | mark your list as done |
| `/list [player]` | show a list (yours by default) |
| `/status` | who's ready, everyone's odds, the current round |
| `/draw` | admin: draw the next round |
| `/close` | admin: close the current round |

Adds and "ready" are announced in the channel. The draw announcement hides
the picks behind spoiler tags and links to the site's reveal.

## Architecture

```
gameclub/          core, no web dependencies
  draw.py          draw logic: pure functions, same seed = same result
  store.py         reading/writing the JSON files in data/
  rounds.py        running, recording and announcing a draw
  rawg.py          game metadata from RAWG (fetched once, cached)
  prices.py        Steam prices and Steam store search
  cli.py           admin command line
web/
  app.py           website (Flask)
  club.py          shared data access and list actions (site + Discord)
  discord_bot.py   Discord slash commands
  discord_register.py  registers the commands on a Discord server
  git_sync.py      pull / commit / push of data/
  templates/, static/
data/              the club's data (see below)
tests/
```

**Data lives in git.** Every change made on the site or in Discord is
written to `data/`, committed, and pushed to GitHub by the app itself,
so the commit log is a full audit trail. The admin's command line edits
the same files, and the app pulls before every write (and every 30s on
reads), so both stay in sync.

**Discord without a bot process.** Discord's "interactions endpoint" mode
sends each command as an HTTP request to the same Flask app
(`/discord/interactions`), so there is one thing to host. Anything slow
(RAWG, Steam, git) answers "thinking..." right away and finishes in the
background, to stay within Discord's 3 second limit.

**External APIs are called only when a game is added**, never at draw
time: RAWG for metadata, Steam's (unofficial, keyless) store endpoints for
price and search.

### Data files

| File | Content |
|---|---|
| `club.json` | players, ready flags, price country |
| `games.json` | game metadata cache (title, cover, genres, co-op/indie, length, Steam price) |
| `submissions.json` | each player's current list |
| `rounds.json` | every draw: seed, who wasn't picked, the lists it used, the picks |

**Privacy**: the repo is public, so players appear under a nickname only.
Discord user ids live in an environment variable on the server
(`DISCORD_PLAYERS`) and, for local use, in `data/player_secrets.json`,
which is gitignored.

## Running your own

### Requirements

- Python 3.10+
- A free [RAWG API key](https://rawg.io/apidocs) for game search
- For hosting: a GitHub repo you control, a [Render](https://render.com)
  account (free tier is enough), optionally a Discord server

### Local setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-web.txt
```

Add players and games with the CLI (the admin side):

```
python3 -m gameclub player add alice Alice
python3 -m gameclub game search "hades"            # needs RAWG_API_KEY
python3 -m gameclub game add hades                 # RAWG slug; fetches price
python3 -m gameclub game add mygame --manual --title "My Game" --coop
python3 -m gameclub game set hades --no-indie      # fix flags, --hours, ...
python3 -m gameclub list set alice hades mygame    # replace a list
python3 -m gameclub status                         # everyone's odds, list checks
python3 -m gameclub draw                           # draw + announce
python3 -m gameclub round close 1                  # after the meeting
```

`draw` posts to Discord if `DISCORD_WEBHOOK_URL` is set, otherwise it
prints the announcement. After CLI changes, commit and push `data/` so
the live site picks them up.

Run the site locally:

```
GAMECLUB_GIT_PUSH=0 FLASK_SECRET_KEY=dev .venv/bin/python -m web.app
```

### Environment variables

| Variable | Used for |
|---|---|
| `RAWG_API_KEY` | game search and metadata |
| `FLASK_SECRET_KEY` | signing the name-picker cookie; any random string |
| `GAMECLUB_DATA` | data directory (default `data`) |
| `GAMECLUB_GIT_PUSH` | `0` to only commit locally (no pull/push) |
| `GITHUB_TOKEN` | Render only: lets the app clone and push the repo |
| `SITE_URL` | public URL of the site, for links in Discord messages |
| `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY` | Discord integration |
| `DISCORD_PLAYERS` | JSON `{"<discord user id>": "<player id>"}` |
| `DISCORD_ADMINS` | comma-separated Discord user ids allowed to draw/close |
| `DISCORD_WEBHOOK_URL` | CLI only: where `draw` posts its announcement |

### Deploying on Render (free tier)

Render's free tier has no persistent disk: the file system is wiped on
every restart, and the service sleeps after 15 minutes idle (about a
minute to wake up). So `render-start.sh` clones the repo fresh at every
boot, using a GitHub token, and the app pushes every change straight back.
GitHub is the real storage; the server's copy is disposable.

1. Fork or push this repo to your own GitHub account.
2. On Render: **New → Blueprint**, select the repo. `render.yaml` creates
   the web service.
3. In the service's **Environment** tab, set `GITHUB_TOKEN` (a
   fine-grained token for this repo only, with *Contents: read and write*),
   `FLASK_SECRET_KEY` and `RAWG_API_KEY`. Update `REPO_URL` in
   `render-start.sh` to point at your repo.
4. **Turn Auto-Deploy off.** The app pushes to the repo on every player
   action; with auto-deploy on, each one would redeploy the live service.
   Deploy manually (**Manual Deploy → Deploy latest commit**) when the
   code changes.

### Adding Discord

1. Create a Discord server, and an application on the
   [developer portal](https://discord.com/developers/applications).
   From **General Information**, note the **Application ID** and
   **Public Key**. From **Bot**, reset and copy the **bot token** (needed
   once, to register commands; never commit it).
2. Invite the app to your server by opening this URL while logged in, then
   choosing the server:
   ```
   https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&scope=bot+applications.commands&permissions=0
   ```
3. In Discord, turn on **User Settings → Advanced → Developer Mode**. Then
   right-click the server icon → **Copy Server ID**, and right-click each
   member → **Copy User ID**. (Members who aren't linked yet get their
   own id in the bot's reply, so they can send it to you.)
4. On Render, set `DISCORD_APPLICATION_ID`, `DISCORD_PUBLIC_KEY`,
   `DISCORD_PLAYERS` (e.g. `{"123456789012345678": "alice"}`, player ids
   as in `data/club.json`), `DISCORD_ADMINS` and `SITE_URL`, then deploy.
5. In the developer portal, set **Interactions Endpoint URL** to
   `<SITE_URL>/discord/interactions` and save. Discord sends a signed test
   request; saving only works if the site is up and answers it, so open
   `<SITE_URL>/healthz` first to wake it.
6. Register the commands from your machine (again whenever they change):
   ```
   DISCORD_APPLICATION_ID=... DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
       .venv/bin/python -m web.discord_register
   ```
7. Keep the service awake: a sleeping service takes about a minute to
   answer, past Discord's 3 second limit. Point a free uptime monitor
   (UptimeRobot, cron-job.org) at `<SITE_URL>/healthz` every 10 minutes.
   A single always-on service fits within Render's 750 free hours a month.

## Development

```
.venv/bin/python -m unittest -v
.venv/bin/mypy --strict gameclub web tests
.venv/bin/flake8 gameclub web tests
```

Tests run without network access: RAWG, Steam and Discord are mocked, and
git sync is tested against throwaway local repositories.

## Ideas to improve

- **Co-op special draw.** Rounds used to have a co-op slot (and every list
  needed a co-op game); it was dropped for a simpler, fairer lottery.
  Playing together could come back as an optional extra: a separate
  co-op draw, or a co-op bonus round now and then. Games already carry a
  co-op flag (from RAWG), so the data is ready.
- **Admin reset command.** An admin-only way to wipe the lists (or start
  the club over from round 1). Everything stays recoverable from git
  history.
- **More than 3 games per round** once the group grows past ~6 people,
  so each person still gets picked regularly.
- **Ratings and meeting dates** per round (in the data model, not built
  yet).
- **Steam-only game add** as a fallback when RAWG is down.

### Known limits

- RAWG's flags (co-op, indie) and playtime are trusted as-is when a game
  is added; the admin can fix them with `game set`. Playtime matters for
  the "no two long games" rule.
- Round 1 was drawn with the earlier system (fixed sit-out rotation and
  co-op/indie/free slots); its record keeps the slot labels.
- Steam prices use unofficial store endpoints; games not on Steam have no
  price.
- The Discord integration is tested against hand-written payloads, and
  only lightly in real use so far.
- A round stores the list contents as game ids. If a game's flags are
  edited after a draw, re-running that draw's seed may not reproduce it.
