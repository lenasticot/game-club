"""Shared read/write access to the club data, and the list actions.

Both the site (web/app.py) and Discord (web/discord_bot.py) go through
here, so a rule like "editing your list un-readies you" lives in one
place.
"""

import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from gameclub import prices, rawg
from gameclub.draw import MAX_LIST_SIZE, validate_submission
from gameclub.store import GameRec, Store, StoreError
from web import git_sync

log = logging.getLogger("gameclub.club")

# Reads pull at most this often; writes always pull first.
READ_PULL_INTERVAL = 30.0


class Club:
    def __init__(self, data_dir: Path, repo_dir: Path, remote: bool) -> None:
        self.data_dir = data_dir
        self.repo_dir = repo_dir
        # False in local dev/tests: commit only, no pull/push.
        self.remote = remote
        # Serializes load-modify-save, so two writers can't overwrite each
        # other's change (Discord work runs in background threads).
        self._lock = threading.RLock()
        self._last_pull = 0.0
        self.pending: list[threading.Thread] = []

    def store(self) -> Store:
        """Current local data, no network (for fast paths)."""
        return Store(self.data_dir)

    def _pull(self) -> None:
        git_sync.pull(self.repo_dir)
        self._last_pull = time.monotonic()

    def read(self) -> Store:
        if self.remote and (time.monotonic() - self._last_pull
                            > READ_PULL_INTERVAL):
            with self._lock:
                try:
                    self._pull()
                except git_sync.GitSyncError as e:
                    # Stale data beats an error page; writes will retry.
                    log.warning("pull before read failed: %s", e)
        return self.store()

    @contextmanager
    def write(self, message: str) -> Iterator[Store]:
        """Load fresh data, let the caller change it, save and commit.

        Nothing is saved if the body raises.
        """
        with self._lock:
            if self.remote:
                self._pull()
            s = self.store()
            yield s
            s.save()
            if git_sync.commit(self.repo_dir, message) and self.remote:
                self._push_in_background()

    def _push_in_background(self) -> None:
        # The push is a slow network round-trip; the commit is already
        # done, so a crash before it runs only delays it to the next push.
        def run() -> None:
            try:
                git_sync.push(self.repo_dir)
            except git_sync.GitSyncError as e:
                log.error("push failed, data only local until next "
                          "write: %s", e)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.pending.append(t)


# List actions. All raise StoreError/DrawError on invalid changes; the
# caller is inside Club.write(), so nothing is saved then.

def add_to_list(s: Store, pid: str, game_id: str) -> bool:
    """False if the game was already on the list."""
    s.game(game_id)  # unknown game -> StoreError
    entries = s.submissions.get(pid, [])
    if any(e["game_id"] == game_id for e in entries):
        return False
    if len(entries) >= MAX_LIST_SIZE:
        raise StoreError(f"list already has {MAX_LIST_SIZE} games")
    entries.append({"game_id": game_id, "priority": False})
    s.submissions[pid] = entries
    s.set_finalized(pid, False)
    return True


def remove_from_list(s: Store, pid: str, game_id: str) -> None:
    s.submissions[pid] = [e for e in s.submissions.get(pid, [])
                          if e["game_id"] != game_id]
    s.set_finalized(pid, False)


def set_priority(s: Store, pid: str, game_id: str) -> None:
    s.submissions[pid] = [
        {"game_id": e["game_id"], "priority": e["game_id"] == game_id}
        for e in s.submissions.get(pid, [])
    ]
    s.set_finalized(pid, False)


def finalize(s: Store, pid: str) -> None:
    validate_submission(pid, s.list_games(pid), s.played())
    s.set_finalized(pid, True)


def fetch_game(rawg_id_or_slug: str, steam_appid: Optional[int],
               country: str, now: str) -> GameRec:
    """Game record from RAWG, priced on Steam if an appid is given.

    Network calls, so do it before Club.write(), not inside it.
    """
    game = rawg.fetch(rawg_id_or_slug, now)
    game["steam_appid"] = steam_appid
    if steam_appid is not None:
        try:
            game["price"] = prices.steam_price(steam_appid, country, now)
        except OSError:
            game["price"] = None
    return game


def add_game_to_list(s: Store, pid: str, game: GameRec) -> GameRec:
    """Add a game to the catalog if new, then to the player's list."""
    if s.has_game(game["id"]):
        game = s.game(game["id"])
    else:
        s.add_game(game)
    add_to_list(s, pid, game["id"])
    return game
