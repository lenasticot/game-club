"""Command line: python3 -m gameclub <command>.

Every command reads data/*.json, changes it, and writes it back. Commit
the data/ changes afterwards so git keeps the history.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gameclub import prices, rawg, rounds
from gameclub.draw import DrawError, draw_round, sitters_for_round
from gameclub.draw import validate_submission
from gameclub.store import GameRec, Store, StoreError, new_game


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Players

def cmd_player_add(store: Store, args: argparse.Namespace) -> None:
    store.add_player(args.id, args.name, args.platform or [])
    print(f"added {args.id}")


def cmd_player_remove(store: Store, args: argparse.Namespace) -> None:
    store.deactivate_player(args.id)
    print(f"{args.id} is now inactive")


def cmd_player_list(store: Store, args: argparse.Namespace) -> None:
    for p in store.players:
        state = "" if p["active"] else " (inactive)"
        plats = ", ".join(p["platforms"]) or "-"
        print(f"{p['id']:12} {p['name']:16} {plats}{state}")


# Games

def _apply_flags(game: GameRec, args: argparse.Namespace) -> None:
    if args.coop is not None:
        game["is_coop"] = args.coop
    if args.indie is not None:
        game["is_indie"] = args.indie
    if args.hours is not None:
        game["hours_main"] = args.hours
    if args.steam_appid is not None:
        game["steam_appid"] = args.steam_appid


def _fetch_price(store: Store, game: GameRec) -> None:
    if game["steam_appid"] is None:
        return
    try:
        game["price"] = prices.steam_price(
            game["steam_appid"], store.price_country, now_iso())
    except OSError as e:
        print(f"warning: no price for {game['id']}: {e}", file=sys.stderr)


def _describe(game: GameRec) -> str:
    flags = [f for f, on in (("co-op", game["is_coop"]),
                             ("indie", game["is_indie"])) if on]
    price = game["price"]["formatted"] if game["price"] else "no price"
    return (f"{game['id']:28} {game['title'][:32]:32} "
            f"{'/'.join(flags) or '-':12} {price}")


def cmd_game_search(store: Store, args: argparse.Namespace) -> None:
    for r in rawg.search(args.query):
        print(f"{r['slug']:36} {r['name']} ({r['released'] or '?'})")


def cmd_game_add(store: Store, args: argparse.Namespace) -> None:
    if args.manual:
        if not args.title:
            raise StoreError("--manual needs --title")
        game = new_game(args.id, args.title)
    else:
        game = rawg.fetch(args.id, now_iso())
    _apply_flags(game, args)
    _fetch_price(store, game)
    store.add_game(game)
    print(_describe(game))
    print("check the co-op and indie flags; fix them with `game set`")


def cmd_game_set(store: Store, args: argparse.Namespace) -> None:
    game = store.game(args.id)
    _apply_flags(game, args)
    if args.title:
        game["title"] = args.title
    print(_describe(game))


def cmd_game_price(store: Store, args: argparse.Namespace) -> None:
    ids = args.ids or [g["id"] for g in store.games]
    for game_id in ids:
        game = store.game(game_id)
        _fetch_price(store, game)
        print(_describe(game))


def cmd_game_list(store: Store, args: argparse.Namespace) -> None:
    played = store.played()
    for g in store.games:
        mark = " (played)" if g["id"] in played else ""
        print(_describe(g) + mark)


# Lists

def cmd_list_set(store: Store, args: argparse.Namespace) -> None:
    store.player(args.player)
    games = [store.draw_game(i) for i in args.games]
    validate_submission(args.player, games, store.played())
    store.submissions[args.player] = list(args.games)
    print(f"{args.player}: {len(games)} games")


def cmd_list_show(store: Store, args: argparse.Namespace) -> None:
    played = store.played()
    players = [args.player] if args.player else store.active_ids()
    for pid in players:
        print(f"{store.player(pid)['name']}:")
        for game_id in store.submissions.get(pid, []):
            mark = " (played)" if game_id in played else ""
            print("  " + _describe(store.game(game_id)) + mark)


# Rounds

def cmd_status(store: Store, args: argparse.Namespace) -> None:
    number = store.next_round_number()
    if store.rounds:
        last = store.rounds[-1]
        print(f"last round: {last['number']} ({last['status']})")
    rotations = rounds.preview_rotations(store)
    sitting: list[str] = []
    if not store.rotations_raw:
        print("sit-out order: drawn at round 1, so every list must be valid")
    else:
        sitting = sitters_for_round(rotations, number)
        names = ", ".join(store.player(p)["name"] for p in sitting)
        print(f"round {number} sits out: {names or 'nobody'}")
    pickers = [p for p in store.active_ids() if p not in sitting]
    ok = True
    for pid in pickers:
        try:
            validate_submission(pid, store.list_games(pid), store.played())
        except DrawError as e:
            ok = False
            print(f"  problem: {e}")
    if not ok:
        return
    # The search behind draw_round is exhaustive, so whether a round can
    # be drawn does not depend on the seed. Any seed works for this check.
    lists = {p: store.list_games(p) for p in pickers}
    try:
        draw_round(number, "check", rotations, lists, store.played())
        print(f"round {number} can be drawn")
    except DrawError as e:
        print(f"  problem: {e}")


def _announce(store: Store, number: int) -> None:
    text = rounds.announcement(store, store.round(number))
    print(text)
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("\n(DISCORD_WEBHOOK_URL not set: paste this in Discord)")
        return
    try:
        rounds.post_to_discord(webhook, text)
        print("\nposted to Discord")
    except OSError as e:
        print(f"\nwarning: Discord post failed ({e}); "
              f"retry with `round announce {number}`", file=sys.stderr)


def cmd_draw(store: Store, args: argparse.Namespace) -> None:
    rec = rounds.run_draw(store, rounds.new_seed(), now_iso())
    # Save before announcing, so a failed post never loses the draw.
    store.save()
    _announce(store, rec["number"])


def cmd_round_announce(store: Store, args: argparse.Namespace) -> None:
    _announce(store, args.number)


def cmd_round_close(store: Store, args: argparse.Namespace) -> None:
    store.round(args.number)["status"] = "discussed"
    print(f"round {args.number} closed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gameclub")
    parser.add_argument("--data", type=Path, default=Path("data"),
                        help="data directory (default: data)")
    sub = parser.add_subparsers(dest="command", required=True)

    def flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--coop", action=argparse.BooleanOptionalAction,
                       help="multiplayer (2+ players)")
        p.add_argument("--indie", action=argparse.BooleanOptionalAction)
        p.add_argument("--hours", type=float, help="main story length")
        p.add_argument("--steam-appid", type=int, help="for prices")

    player = sub.add_parser("player").add_subparsers(required=True)
    p = player.add_parser("add")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--platform", action="append")
    p.set_defaults(func=cmd_player_add, writes=True)
    p = player.add_parser("remove", help="mark inactive")
    p.add_argument("id")
    p.set_defaults(func=cmd_player_remove, writes=True)
    p = player.add_parser("list")
    p.set_defaults(func=cmd_player_list, writes=False)

    game = sub.add_parser("game").add_subparsers(required=True)
    p = game.add_parser("search", help="search RAWG")
    p.add_argument("query")
    p.set_defaults(func=cmd_game_search, writes=False)
    p = game.add_parser("add", help="add from RAWG (slug) or --manual")
    p.add_argument("id", help="RAWG slug, or your own id with --manual")
    p.add_argument("--manual", action="store_true")
    p.add_argument("--title")
    flags(p)
    p.set_defaults(func=cmd_game_add, writes=True)
    p = game.add_parser("set", help="fix flags, title or length")
    p.add_argument("id")
    p.add_argument("--title")
    flags(p)
    p.set_defaults(func=cmd_game_set, writes=True)
    p = game.add_parser("price", help="refresh Steam prices")
    p.add_argument("ids", nargs="*")
    p.set_defaults(func=cmd_game_price, writes=True)
    p = game.add_parser("list")
    p.set_defaults(func=cmd_game_list, writes=False)

    lst = sub.add_parser("list").add_subparsers(required=True)
    p = lst.add_parser("set", help="replace a player's list")
    p.add_argument("player")
    p.add_argument("games", nargs="+")
    p.set_defaults(func=cmd_list_set, writes=True)
    p = lst.add_parser("show")
    p.add_argument("player", nargs="?")
    p.set_defaults(func=cmd_list_show, writes=False)

    p = sub.add_parser("status", help="next round and list checks")
    p.set_defaults(func=cmd_status, writes=False)
    p = sub.add_parser("draw", help="draw the next round and announce it")
    p.set_defaults(func=cmd_draw, writes=False)  # saves itself

    rnd = sub.add_parser("round").add_subparsers(required=True)
    p = rnd.add_parser("announce", help="post a drawn round again")
    p.add_argument("number", type=int)
    p.set_defaults(func=cmd_round_announce, writes=False)
    p = rnd.add_parser("close", help="mark a round as discussed")
    p.add_argument("number", type=int)
    p.set_defaults(func=cmd_round_close, writes=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.data)
    try:
        args.func(store, args)
    except (DrawError, StoreError, rawg.RawgError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.writes:
        store.save()
    return 0
