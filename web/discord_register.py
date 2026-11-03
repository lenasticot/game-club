"""Register the slash commands on the club's Discord server.

Run once, and again whenever COMMANDS in web/discord_bot.py changes:

    DISCORD_APPLICATION_ID=... DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \\
        python3 -m web.discord_register

Server ("guild") commands show up instantly, unlike global ones. The PUT
replaces the whole set, so removed commands disappear too.
"""

import json
import os
import sys
import urllib.error
import urllib.request

from web.discord_bot import API, COMMANDS, USER_AGENT


def main() -> None:
    try:
        app_id = os.environ["DISCORD_APPLICATION_ID"]
        token = os.environ["DISCORD_BOT_TOKEN"]
        guild = os.environ["DISCORD_GUILD_ID"]
    except KeyError as e:
        sys.exit(f"set {e.args[0]}")
    req = urllib.request.Request(
        f"{API}/applications/{app_id}/guilds/{guild}/commands",
        data=json.dumps(COMMANDS).encode(), method="PUT",
        headers={"Authorization": f"Bot {token}",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            names = [c["name"] for c in json.load(resp)]
    except urllib.error.HTTPError as e:
        sys.exit(f"Discord said {e.code}: {e.read().decode()}")
    print("registered: " + ", ".join(f"/{n}" for n in names))


if __name__ == "__main__":
    main()
