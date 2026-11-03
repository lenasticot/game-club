"""Flask app: identity picker, list editing, game search/add.

No passwords: picking a name sets a signed session cookie, like a
Tricount group link. Reads and writes go through web.club.Club, which
keeps data/ in sync with GitHub (the source of truth). The Discord
interactions endpoint (web/discord_bot.py) is mounted here too.
"""

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)
from flask.typing import ResponseReturnValue

from gameclub import prices, rawg
from gameclub.draw import MAX_LIST_SIZE, DrawError
from gameclub.rounds import SLOT_LABELS
from gameclub.store import GameRec, Store, StoreError
from web import club as actions
from web import discord_bot
from web.club import Club

REEL_FILLER_CAP = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_app(data_dir: Optional[Path] = None,
               repo_dir: Optional[Path] = None) -> Flask:
    app = Flask(__name__)
    app.config["DATA_DIR"] = data_dir or Path(
        os.environ.get("GAMECLUB_DATA", "data"))
    app.config["REPO_DIR"] = repo_dir or app.config["DATA_DIR"].parent
    club = Club(app.config["DATA_DIR"], app.config["REPO_DIR"],
                remote=os.environ.get("GAMECLUB_GIT_PUSH", "1") != "0")
    app.config["CLUB"] = club
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))

    def store() -> Store:
        return club.read()

    def current_player(s: Store) -> Optional[str]:
        pid = session.get("player_id")
        if isinstance(pid, str) and any(p["id"] == pid for p in s.players):
            return pid
        return None

    def me() -> str:
        pid = session.get("player_id")
        assert isinstance(pid, str)  # checked by _require_identity
        return pid

    @app.before_request
    def _require_identity() -> Optional[ResponseReturnValue]:
        if request.endpoint in ("whoami", "static", "healthz",
                                "discord_interactions"):
            return None
        s = store()
        if current_player(s) is None:
            return redirect(url_for("whoami"))
        return None

    @app.route("/whoami", methods=["GET", "POST"])
    def whoami() -> ResponseReturnValue:
        s = store()
        if request.method == "POST":
            pid = request.form["player_id"]
            s.player(pid)  # raises StoreError (-> 500) if unknown
            session["player_id"] = pid
            session.permanent = True
            return redirect(url_for("home"))
        players = [p for p in s.players if p["active"]]
        return render_template("whoami.html", players=players)

    @app.route("/logout", methods=["POST"])
    def logout() -> ResponseReturnValue:
        session.pop("player_id", None)
        return redirect(url_for("whoami"))

    @app.route("/")
    def home() -> ResponseReturnValue:
        s = store()
        pid = current_player(s)
        assert pid is not None
        entries = s.submissions.get(pid, [])
        games = [(e, s.game(e["game_id"])) for e in entries]
        played = s.played()
        has_coop = any(g["is_coop"] and g["id"] not in played
                       for _, g in games)
        q = request.args.get("q", "").strip()
        catalog_matches: list[GameRec] = []
        rawg_matches: list[dict[str, object]] = []
        if q:
            catalog_matches = [g for g in s.games
                               if q.lower() in g["title"].lower()]
            try:
                rawg_matches = rawg.search(q)
            except rawg.RawgError as e:
                rawg_matches = []
                session["search_error"] = str(e)
        return render_template(
            "home.html", player=s.player(pid), games=games, query=q,
            catalog_matches=catalog_matches, rawg_matches=rawg_matches,
            max_list_size=MAX_LIST_SIZE, has_coop=has_coop, played=played,
            finalized=s.is_finalized(pid),
            search_error=session.pop("search_error", None),
            finalize_error=session.pop("finalize_error", None))

    @app.route("/list/add", methods=["POST"])
    def list_add() -> ResponseReturnValue:
        pid, game_id = me(), request.form["game_id"]
        with club.write(f"{pid}: add {game_id} to list") as s:
            actions.add_to_list(s, pid, game_id)
        return redirect(url_for("home"))

    @app.route("/list/remove", methods=["POST"])
    def list_remove() -> ResponseReturnValue:
        pid, game_id = me(), request.form["game_id"]
        with club.write(f"{pid}: remove {game_id} from list") as s:
            actions.remove_from_list(s, pid, game_id)
        return redirect(url_for("home"))

    @app.route("/list/priority", methods=["POST"])
    def list_priority() -> ResponseReturnValue:
        pid, game_id = me(), request.form["game_id"]
        with club.write(f"{pid}: set priority to {game_id}") as s:
            actions.set_priority(s, pid, game_id)
        return redirect(url_for("home"))

    @app.route("/list/finalize", methods=["POST"])
    def list_finalize() -> ResponseReturnValue:
        pid = me()
        try:
            with club.write(f"{pid}: finalized list") as s:
                actions.finalize(s, pid)
        except DrawError as e:
            session["finalize_error"] = str(e)
        return redirect(url_for("home"))

    @app.route("/games/new")
    def games_new() -> ResponseReturnValue:
        s = store()
        slug = request.args["slug"]
        draft = rawg.fetch(slug, now_iso())
        steam_matches: list[prices.SteamMatch] = []
        if draft["steam_appid"] is None:
            try:
                steam_matches = prices.steam_search(
                    draft["title"], s.price_country)
            except OSError:
                steam_matches = []
        return render_template("new_game.html", draft=draft,
                               steam_matches=steam_matches)

    @app.route("/games/new", methods=["POST"])
    def games_add() -> ResponseReturnValue:
        pid, slug = me(), request.form["slug"]
        s = store()
        if s.has_game(slug):
            game = s.game(slug)
        else:
            # The form always carries RAWG's own appid (hidden field) or
            # the player's pick; empty means no Steam price.
            appid = request.form.get("steam_appid", "").strip()
            game = actions.fetch_game(slug, int(appid) if appid else None,
                                      s.price_country, now_iso())
        with club.write(f"{pid}: add new game {game['id']}") as s:
            actions.add_game_to_list(s, pid, game)
        return redirect(url_for("home"))

    @app.route("/players")
    def players_page() -> ResponseReturnValue:
        return render_template("players.html")

    @app.route("/api/players")
    def api_players() -> ResponseReturnValue:
        s = store()
        played = s.played()
        data = []
        for p in s.players:
            if not p["active"]:
                continue
            entries = s.submissions.get(p["id"], [])
            games = []
            for e in entries:
                g = s.game(e["game_id"])
                games.append({
                    "title": g["title"], "is_coop": g["is_coop"],
                    "is_indie": g["is_indie"], "priority": e["priority"],
                    "played": g["id"] in played,
                })
            data.append({
                "id": p["id"], "name": p["name"],
                "finalized": s.is_finalized(p["id"]), "games": games,
            })
        return jsonify(data)

    @app.route("/games")
    def games_page() -> ResponseReturnValue:
        s = store()
        return render_template("games.html", games=s.games,
                               played=s.played())

    @app.route("/round")
    def round_page() -> ResponseReturnValue:
        s = store()
        if not s.rounds:
            return render_template("round.html", slots=None)
        rec = s.rounds[-1]
        sitting = [s.player(pid)["name"] for pid in rec["sitting"]]
        slots = []
        for pick in rec["picks"]:
            other_ids = [gid for gid in rec["lists"].get(pick["player"], [])
                         if s.has_game(gid) and gid != pick["game_id"]]
            filler = [s.game(gid) for gid in other_ids]
            random.shuffle(filler)
            reel = (filler * 3)[:REEL_FILLER_CAP] + [s.game(pick["game_id"])]
            slots.append({
                "slot": pick["slot"], "label": SLOT_LABELS[pick["slot"]],
                "player": s.player(pick["player"])["name"],
                "game": s.game(pick["game_id"]), "reel": reel,
            })
        return render_template("round.html", round=rec, sitting=sitting,
                               slots=slots)

    @app.route("/healthz")
    def healthz() -> ResponseReturnValue:
        # For an external pinger keeping the free Render instance awake,
        # so Discord commands don't hit a ~1min cold start.
        return "ok"

    @app.errorhandler(StoreError)
    @app.errorhandler(DrawError)
    @app.errorhandler(rawg.RawgError)
    def _store_error(e: Exception) -> tuple[str, int]:
        return str(e), 400

    public_key = os.environ.get("DISCORD_PUBLIC_KEY")
    if public_key:
        discord_bot.mount(app, discord_bot.Bot(
            club,
            public_key=public_key,
            app_id=os.environ["DISCORD_APPLICATION_ID"],
            players=discord_players(club.store()),
            admins=set(os.environ.get("DISCORD_ADMINS", "").split(",")) - {""},
            site_url=os.environ.get("SITE_URL", "").rstrip("/"),
        ))

    return app


def discord_players(s: Store) -> dict[str, str]:
    """Discord user id -> player id.

    From the DISCORD_PLAYERS env var on the server (JSON object), since
    player_secrets.json is gitignored and so missing from the live clone;
    the local secrets file is used too, for dev.
    """
    mapping = {sec["discord_id"]: pid for pid, sec in s.secrets.items()
               if sec.get("discord_id")}
    raw = os.environ.get("DISCORD_PLAYERS")
    if raw:
        mapping.update(json.loads(raw))
    return {str(k): v for k, v in mapping.items() if k}


if __name__ == "__main__":
    create_app().run(debug=True)
