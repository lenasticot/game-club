"""Discord slash commands, served by the Flask app.

Uses Discord's HTTP "interactions endpoint" instead of a gateway bot:
Discord POSTs each command/button click to /discord/interactions, so no
extra always-on process is needed. Discord wants an answer within 3s,
so anything touching the network (git pull, RAWG, Steam) replies
"thinking..." right away and finishes in a background thread, editing
that reply through the interaction's webhook token.

Players are matched by Discord user id (DISCORD_PLAYERS). Admin-only
commands (draw, close) check DISCORD_ADMINS on top of being hidden from
non-admins in Discord's own UI.

Payload/endpoint shapes follow Discord's documented API v10; they are
tested here against hand-written payloads only, not live Discord.
"""

import json
import logging
import time
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from flask import Flask, jsonify, request
from flask.typing import ResponseReturnValue
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from gameclub import prices, rawg, rounds
from gameclub.draw import MAX_LIST_SIZE, DrawError
from gameclub.store import GameRec, Store, StoreError
from web import club as actions
from web.club import Club

log = logging.getLogger("gameclub.discord")

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/lenasticot/game-club, 1)"
EPHEMERAL = 64

# Interaction types
PING, COMMAND, COMPONENT, AUTOCOMPLETE = 1, 2, 3, 4
# Response types
PONG = 1
MESSAGE = 4
DEFERRED_MESSAGE = 5
DEFERRED_UPDATE = 6
AUTOCOMPLETE_RESULT = 8
# Component types / button styles
ROW, BUTTON, SELECT = 1, 2, 3
PRIMARY, SECONDARY, SUCCESS, LINK = 1, 2, 3, 5
# Option types
STRING = 3

AUTOCOMPLETE_RAWG_TIMEOUT = 2.0  # of Discord's 3s budget

Json = dict[str, Any]


def _option(name: str, description: str, autocomplete: bool = True,
            required: bool = True) -> Json:
    return {"type": STRING, "name": name, "description": description,
            "required": required, "autocomplete": autocomplete}


# Registered by web/discord_register.py.
COMMANDS: list[Json] = [
    {"name": "add", "description": "Add a game to your list",
     "options": [_option("game", "Start typing a title")]},
    {"name": "remove", "description": "Remove a game from your list",
     "options": [_option("game", "A game on your list")]},
    {"name": "star", "description": "Make a game your priority "
                                    "(extra draw weight)",
     "options": [_option("game", "A game on your list")]},
    {"name": "ready", "description": "Mark your list as done for the "
                                     "next draw"},
    {"name": "list", "description": "Show a list (yours by default)",
     "options": [_option("player", "Whose list", required=False)]},
    {"name": "status", "description": "Who's ready, and the current round"},
    # "0": hidden from everyone but server admins in Discord's UI.
    {"name": "draw", "description": "Admin: draw the next round",
     "default_member_permissions": "0"},
    {"name": "close", "description": "Admin: close the current round "
                                     "(after the meeting)",
     "default_member_permissions": "0"},
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _http(method: str, url: str, body: Optional[Json]) -> None:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15):
                return
        except urllib.error.HTTPError as e:
            # 404 right after a deferred reply: Discord may not have
            # registered our "thinking..." yet. Retry once.
            if e.code != 404 or attempt:
                raise
            time.sleep(1)


def _thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


def game_embed(game: GameRec) -> Json:
    flags = [f for f, on in (("Co-op", game["is_coop"]),
                             ("Indie", game["is_indie"])) if on]
    desc = " · ".join(filter(None, [" · ".join(flags),
                                    rounds.game_line(game)]))
    embed: Json = {"title": game["title"], "description": desc or "-"}
    if game["cover_url"]:
        embed["thumbnail"] = {"url": game["cover_url"]}
    return embed


def _msg(content: str, **extra: Any) -> Json:
    return {"content": content, "embeds": [], "components": [], **extra}


class Bot:
    def __init__(self, club: Club, public_key: str, app_id: str,
                 players: dict[str, str], admins: set[str], site_url: str,
                 send: Callable[[str, str, Optional[Json]], None] = _http,
                 spawn: Callable[[Callable[[], None]], None] = _thread
                 ) -> None:
        self.club = club
        self.verify_key = VerifyKey(bytes.fromhex(public_key))
        self.app_id = app_id
        self.players = players
        self.admins = admins
        self.site_url = site_url
        # Injected so tests can capture Discord calls and run "background"
        # work inline.
        self.send = send
        self.spawn = spawn

    def verify(self, signature: str, timestamp: str, body: bytes) -> bool:
        try:
            self.verify_key.verify(timestamp.encode() + body,
                                   bytes.fromhex(signature))
            return True
        except (BadSignatureError, ValueError):
            return False

    # Plumbing

    def _edit_original(self, token: str, message: Json) -> None:
        self.send("PATCH", f"{API}/webhooks/{self.app_id}/{token}"
                           "/messages/@original", message)

    def _followup(self, token: str, message: Json) -> None:
        # Public announcement after the data is saved; failing to post
        # it must not look like the change itself failed.
        try:
            self.send("POST", f"{API}/webhooks/{self.app_id}/{token}",
                      message)
        except OSError:
            log.exception("could not post Discord followup")

    def _deferred(self, payload: Json, work: Callable[[], Json],
                  ephemeral: bool = True, update: bool = False) -> Json:
        """Reply "thinking..." now; run work() later and show its result.

        update=True is for button/select clicks: the result replaces the
        message the component was on instead of a new reply.
        """
        token = payload["token"]

        def run() -> None:
            try:
                message = work()
            except (StoreError, DrawError, rawg.RawgError) as e:
                message = _msg(f"⚠️ {e}")
            except Exception:
                log.exception("Discord command failed")
                message = _msg("⚠️ Something broke, check the server logs.")
            try:
                self._edit_original(token, message)
            except OSError:
                log.exception("could not edit Discord reply")
        self.spawn(run)
        if update:
            return {"type": DEFERRED_UPDATE}
        return {"type": DEFERRED_MESSAGE,
                "data": {"flags": EPHEMERAL} if ephemeral else {}}

    def _link(self, label: str, path: str) -> list[Json]:
        if not self.site_url:
            return []
        return [{"type": BUTTON, "style": LINK, "label": label,
                 "url": f"{self.site_url}{path}"}]

    # Entry point

    def handle(self, payload: Json) -> Json:
        kind = payload.get("type")
        if kind == PING:
            return {"type": PONG}
        user = (payload.get("member") or {}).get("user") \
            or payload.get("user") or {}
        uid = str(user.get("id", ""))
        pid = self.players.get(uid)
        data = payload.get("data") or {}
        if kind == AUTOCOMPLETE:
            return {"type": AUTOCOMPLETE_RESULT,
                    "data": {"choices": self._autocomplete(pid, data)}}
        if pid is None:
            return {"type": MESSAGE, "data": {
                "content": "You're not linked to a Game Club player yet; "
                           "ask the admin to add your Discord id.",
                "flags": EPHEMERAL}}
        if kind == COMPONENT:
            return self._component(payload, pid, uid, data)
        if kind == COMMAND:
            return self._command(payload, pid, uid, data)
        return {"type": MESSAGE, "data": {"content": "Unknown interaction",
                                          "flags": EPHEMERAL}}

    # Autocomplete

    def _autocomplete(self, pid: Optional[str], data: Json) -> list[Json]:
        focused = next((o for o in data.get("options", [])
                        if o.get("focused")), None)
        if focused is None:
            return []
        q = str(focused.get("value", "")).strip().lower()
        s = self.club.store()  # no pull: must answer within 3s
        choices: list[Json] = []
        if data.get("name") == "add":
            for g in s.games:
                if q in g["title"].lower():
                    choices.append({"name": f"{g['title']} · in the club",
                                    "value": g["id"]})
            if len(q) >= 2:
                try:
                    results = rawg.search(q, AUTOCOMPLETE_RAWG_TIMEOUT)
                except (rawg.RawgError, OSError):
                    results = []
                for r in results:
                    if s.has_game(r["slug"]):
                        continue
                    year = f" ({r['released'][:4]})" if r["released"] else ""
                    choices.append({"name": f"{r['name']}{year}",
                                    "value": r["slug"]})
        elif data.get("name") in ("remove", "star") and pid:
            for e in s.submissions.get(pid, []):
                title = s.game(e["game_id"])["title"]
                if q in title.lower():
                    choices.append({"name": title, "value": e["game_id"]})
        elif data.get("name") == "list":
            for p in s.players:
                if p["active"] and q in p["name"].lower():
                    choices.append({"name": p["name"], "value": p["id"]})
        return [{"name": c["name"][:100], "value": c["value"][:100]}
                for c in choices[:25]]

    # Commands

    def _command(self, payload: Json, pid: str, uid: str,
                 data: Json) -> Json:
        name = data.get("name")
        opts = {o["name"]: str(o["value"]) for o in data.get("options", [])}
        token = payload["token"]
        if name == "add":
            return self._deferred(payload, lambda: self._add(
                token, pid, opts["game"]))
        if name == "remove":
            return self._deferred(payload, lambda: self._remove(
                pid, opts["game"]))
        if name == "star":
            return self._deferred(payload, lambda: self._star(
                pid, opts["game"]))
        if name == "ready":
            return self._deferred(payload, lambda: self._ready(token, pid))
        if name == "list":
            return self._deferred(payload, lambda: self._list(
                pid, opts.get("player", pid)))
        if name == "status":
            return self._deferred(payload, self._status, ephemeral=False)
        if name in ("draw", "close"):
            if uid not in self.admins:
                return {"type": MESSAGE, "data": {
                    "content": "Admin only.", "flags": EPHEMERAL}}
            work = self._draw if name == "draw" else self._close
            return self._deferred(payload, work, ephemeral=False)
        return {"type": MESSAGE, "data": {"content": "Unknown command",
                                          "flags": EPHEMERAL}}

    def _added(self, token: str, s: Store, pid: str, game: GameRec) -> Json:
        """Announce an add (call after the write is saved)."""
        count = len(s.submissions.get(pid, []))
        name = s.player(pid)["name"]
        self._followup(token, {
            "content": f"➕ **{name}** added **{game['title']}** "
                       f"({count}/{MAX_LIST_SIZE})",
            "embeds": [game_embed(game)]})
        return _msg(f"Added **{game['title']}** to your list. "
                    "Use `/ready` when your list is done.")

    def _add(self, token: str, pid: str, game_id: str) -> Json:
        if self.club.read().has_game(game_id):
            with self.club.write(f"{pid}: add {game_id} to list") as s:
                added = actions.add_to_list(s, pid, game_id)
            if not added:
                return _msg("Already on your list.")
            return self._added(token, s, pid, s.game(game_id))
        # New game: show RAWG's card and ask which Steam entry to price.
        draft = rawg.fetch(game_id, now_iso())
        rid = draft["rawg_id"]
        if draft["steam_appid"] is not None:
            components = [{"type": ROW, "components": [
                {"type": BUTTON, "style": SUCCESS, "label": "Add it",
                 "custom_id": f"add|{rid}|{draft['steam_appid']}"},
                {"type": BUTTON, "style": SECONDARY,
                 "label": "Add without price", "custom_id": f"add|{rid}|"},
            ]}]
            text = "Found it, with its Steam page for the price."
        else:
            try:
                matches = prices.steam_search(
                    draft["title"], self.club.store().price_country)
            except OSError:
                matches = []
            options = [{"label": m["name"][:100], "value": str(m["appid"])}
                       for m in matches[:24]]
            options.append({"label": "None of these / not on Steam",
                            "value": "none"})
            components = [{"type": ROW, "components": [
                {"type": SELECT, "custom_id": f"addsel|{rid}",
                 "placeholder": "Which Steam game is it? (for the price)",
                 "options": options}]}]
            text = "Pick its Steam page (for the price) to add it."
        return _msg(text, embeds=[game_embed(draft)],
                    components=components)

    def _add_new(self, token: str, pid: str, rawg_id: str,
                 appid: Optional[int]) -> Json:
        country = self.club.store().price_country
        game = actions.fetch_game(rawg_id, appid, country, now_iso())
        with self.club.write(f"{pid}: add new game {game['id']}") as s:
            game = actions.add_game_to_list(s, pid, game)
        return self._added(token, s, pid, game)

    def _remove(self, pid: str, game_id: str) -> Json:
        with self.club.write(f"{pid}: remove {game_id} from list") as s:
            actions.remove_from_list(s, pid, game_id)
            title = s.game(game_id)["title"] if s.has_game(game_id) \
                else game_id
        return _msg(f"Removed **{title}**. You're not marked ready anymore.")

    def _star(self, pid: str, game_id: str) -> Json:
        with self.club.write(f"{pid}: set priority to {game_id}") as s:
            if not any(e["game_id"] == game_id
                       for e in s.submissions.get(pid, [])):
                raise StoreError("that game isn't on your list")
            actions.set_priority(s, pid, game_id)
            title = s.game(game_id)["title"]
        return _msg(f"⭐ **{title}** is your priority now. "
                    "You're not marked ready anymore.")

    def _ready(self, token: str, pid: str) -> Json:
        with self.club.write(f"{pid}: finalized list") as s:
            was_ready = s.is_finalized(pid)
            actions.finalize(s, pid)
            active = s.active_ids()
            done = sum(s.is_finalized(p) for p in active)
            name = s.player(pid)["name"]
        if was_ready:
            return _msg("You were already ready.")
        self._followup(token, {
            "content": f"✅ **{name}** is ready ({done}/{len(active)})"})
        return _msg("You're ready. Editing your list un-readies you.")

    def _list(self, pid: str, whose: str) -> Json:
        s = self.club.read()
        p = s.player(whose)
        played = s.played()
        lines = []
        for e in s.submissions.get(whose, []):
            g = s.game(e["game_id"])
            tags = [t for t, on in (("co-op", g["is_coop"]),
                                    ("indie", g["is_indie"]),
                                    ("played", g["id"] in played)) if on]
            star = "⭐ " if e["priority"] else ""
            extra = f" ({', '.join(tags)})" if tags else ""
            lines.append(f"{star}**{g['title']}**{extra}")
        ready = "✅ ready" if s.is_finalized(whose) else "⏳ not ready"
        head = f"**{p['name']}'s list** · {len(lines)}/{MAX_LIST_SIZE} · " \
               f"{ready}"
        buttons = self._link("Edit on the site", "/")
        if whose == pid and not s.is_finalized(pid):
            buttons.insert(0, {"type": BUTTON, "style": SUCCESS,
                               "label": "I'm ready", "custom_id": "ready"})
        components = [{"type": ROW, "components": buttons}] if buttons \
            else []
        return _msg("\n".join([head, *lines]) if lines
                    else f"{head}\n(empty)", components=components)

    def _status(self) -> Json:
        s = self.club.read()
        lines = []
        if s.rounds:
            last = s.rounds[-1]
            state = "in progress" if last["status"] == "drawn" else "closed"
            titles = ", ".join(s.game(p["game_id"])["title"]
                               for p in last["picks"])
            lines.append(f"**Round {last['number']}** ({state}): {titles}")
        lines.append(f"**Lists for round {s.next_round_number()}:**")
        for p in s.players:
            if not p["active"]:
                continue
            mark = "✅" if s.is_finalized(p["id"]) else "⏳"
            count = len(s.submissions.get(p["id"], []))
            lines.append(f"{mark} {p['name']} ({count} games)")
        buttons = [{"type": BUTTON, "style": SUCCESS, "label": "I'm ready",
                    "custom_id": "ready"}]
        buttons += self._link("Players' lists", "/players")
        return _msg("\n".join(lines),
                    components=[{"type": ROW, "components": buttons}])

    def _draw(self) -> Json:
        number = self.club.read().next_round_number()
        with self.club.write(f"admin: draw round {number}") as s:
            rec = rounds.run_draw(s, rounds.new_seed(), now_iso())
            text = rounds.announcement(s, rec)
        # Picks behind a spoiler so the site's reveal still means
        # something; the header stays visible.
        head, _, rest = text.partition("\n")
        link = f"\n🎰 Watch the reveal: {self.site_url}/round" \
            if self.site_url else ""
        return _msg(f"{head} is drawn!{link}\n||{rest.strip()}||"[:2000])

    def _close(self) -> Json:
        with self.club.write("admin: close round") as s:
            if not s.rounds or s.rounds[-1]["status"] == "discussed":
                raise StoreError("no open round to close")
            s.rounds[-1]["status"] = "discussed"
            number = s.rounds[-1]["number"]
        return _msg(f"Round {number} closed. Lists are open for round "
                    f"{number + 1}: edit them and `/ready` up.")

    # Buttons / selects

    def _component(self, payload: Json, pid: str, uid: str,
                   data: Json) -> Json:
        cid = str(data.get("custom_id", ""))
        token = payload["token"]
        if cid == "ready":
            # A new reply, not an edit: the button sits on a shared
            # message (/status) that shouldn't change for everyone.
            return self._deferred(payload, lambda: self._ready(token, pid))
        kind, _, rest = cid.partition("|")
        if kind == "add":
            rid, _, appid = rest.partition("|")
            return self._deferred(payload, lambda: self._add_new(
                token, pid, rid, int(appid) if appid else None),
                update=True)
        if kind == "addsel":
            value = (data.get("values") or ["none"])[0]
            appid_opt = None if value == "none" else int(value)
            return self._deferred(payload, lambda: self._add_new(
                token, pid, rest, appid_opt), update=True)
        return {"type": MESSAGE, "data": {"content": "Unknown button",
                                          "flags": EPHEMERAL}}


def mount(app: Flask, bot: Bot) -> None:
    @app.route("/discord/interactions", methods=["POST"],
               endpoint="discord_interactions")
    def interactions() -> ResponseReturnValue:
        body = request.get_data()
        if not bot.verify(request.headers.get("X-Signature-Ed25519", ""),
                          request.headers.get("X-Signature-Timestamp", ""),
                          body):
            return "invalid request signature", 401
        return jsonify(bot.handle(json.loads(body)))
