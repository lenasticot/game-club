"""Flask app: identity picker, list editing, game search/add.

No passwords: picking a name sets a signed session cookie, like a
Tricount group link. Every write loads a fresh Store, changes it,
saves, and commits+pushes via git_sync (in a background thread, so the
request doesn't wait on the network) so data/ (the source of truth)
stays in sync with the live site.
"""

import os
import random
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, session, url_for)
from flask.typing import ResponseReturnValue

from gameclub import prices, rawg
from gameclub.draw import MAX_LIST_SIZE, DrawError, validate_submission
from gameclub.rounds import SLOT_LABELS
from gameclub.store import GameRec, Store, StoreError
from web import git_sync

REEL_FILLER_CAP = 10


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_app(data_dir: Optional[Path] = None,
               repo_dir: Optional[Path] = None) -> Flask:
    app = Flask(__name__)
    app.config["DATA_DIR"] = data_dir or Path(
        os.environ.get("GAMECLUB_DATA", "data"))
    app.config["REPO_DIR"] = repo_dir or app.config["DATA_DIR"].parent
    app.config["GIT_PUSH"] = os.environ.get("GAMECLUB_GIT_PUSH", "1") != "0"
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32))
    # Threads doing the actual commit+push, so tests can join() them instead
    # of racing a background thread.
    pending_syncs: list[threading.Thread] = []
    app.config["PENDING_SYNCS"] = pending_syncs

    def store() -> Store:
        return Store(app.config["DATA_DIR"])

    def sync(message: str) -> None:
        # git push is a slow network round-trip; don't make the player
        # wait on it. The commit itself (inside commit_and_push) is fast
        # and local, so data isn't lost even if the thread is slow - only
        # a crash before it runs would lose this one push.
        t = threading.Thread(
            target=git_sync.commit_and_push,
            args=(app.config["REPO_DIR"], message),
            kwargs={"push": app.config["GIT_PUSH"]},
            daemon=True)
        t.start()
        pending_syncs.append(t)

    def current_player(s: Store) -> Optional[str]:
        pid = session.get("player_id")
        if isinstance(pid, str) and any(p["id"] == pid for p in s.players):
            return pid
        return None

    def unfinalize(s: Store, pid: str) -> None:
        # Any list edit invalidates a previous "I'm done".
        s.set_finalized(pid, False)

    @app.before_request
    def _require_identity() -> Optional[ResponseReturnValue]:
        if request.endpoint in ("whoami", "static"):
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
        s = store()
        pid = current_player(s)
        assert pid is not None
        game_id = request.form["game_id"]
        s.game(game_id)  # 404-ish StoreError if unknown
        entries = s.submissions.get(pid, [])
        if any(e["game_id"] == game_id for e in entries):
            return redirect(url_for("home"))
        if len(entries) >= MAX_LIST_SIZE:
            abort(400, f"list already has {MAX_LIST_SIZE} games")
        entries.append({"game_id": game_id, "priority": False})
        s.submissions[pid] = entries
        unfinalize(s, pid)
        s.save()
        sync(f"{pid}: add {game_id} to list")
        return redirect(url_for("home"))

    @app.route("/list/remove", methods=["POST"])
    def list_remove() -> ResponseReturnValue:
        s = store()
        pid = current_player(s)
        assert pid is not None
        game_id = request.form["game_id"]
        s.submissions[pid] = [e for e in s.submissions.get(pid, [])
                              if e["game_id"] != game_id]
        unfinalize(s, pid)
        s.save()
        sync(f"{pid}: remove {game_id} from list")
        return redirect(url_for("home"))

    @app.route("/list/priority", methods=["POST"])
    def list_priority() -> ResponseReturnValue:
        s = store()
        pid = current_player(s)
        assert pid is not None
        game_id = request.form["game_id"]
        s.submissions[pid] = [
            {"game_id": e["game_id"], "priority": e["game_id"] == game_id}
            for e in s.submissions.get(pid, [])
        ]
        unfinalize(s, pid)
        s.save()
        sync(f"{pid}: set priority to {game_id}")
        return redirect(url_for("home"))

    @app.route("/list/finalize", methods=["POST"])
    def list_finalize() -> ResponseReturnValue:
        s = store()
        pid = current_player(s)
        assert pid is not None
        try:
            validate_submission(pid, s.list_games(pid), s.played())
        except DrawError as e:
            session["finalize_error"] = str(e)
            return redirect(url_for("home"))
        s.set_finalized(pid, True)
        s.save()
        sync(f"{pid}: finalized list")
        return redirect(url_for("home"))

    @app.route("/games/new")
    def games_new() -> ResponseReturnValue:
        s = store()
        slug = request.args["slug"]
        try:
            draft = rawg.fetch(slug, now_iso())
        except rawg.RawgError as e:
            abort(400, str(e))
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
        s = store()
        pid = current_player(s)
        assert pid is not None
        slug = request.form["slug"]
        if s.has_game(slug):
            game = s.game(slug)
        else:
            try:
                game = rawg.fetch(slug, now_iso())
            except rawg.RawgError as e:
                abort(400, str(e))
            appid = request.form.get("steam_appid", "").strip()
            if appid:
                game["steam_appid"] = int(appid)
            if game["steam_appid"] is not None:
                try:
                    game["price"] = prices.steam_price(
                        game["steam_appid"], s.price_country, now_iso())
                except OSError:
                    game["price"] = None
            s.add_game(game)
        entries = s.submissions.get(pid, [])
        if not any(e["game_id"] == game["id"] for e in entries):
            if len(entries) >= MAX_LIST_SIZE:
                abort(400, f"list already has {MAX_LIST_SIZE} games")
            entries.append({"game_id": game["id"], "priority": False})
            s.submissions[pid] = entries
            unfinalize(s, pid)
        s.save()
        sync(f"{pid}: add new game {game['id']}")
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

    @app.errorhandler(StoreError)
    @app.errorhandler(DrawError)
    def _store_error(e: Exception) -> tuple[str, int]:
        return str(e), 400

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
