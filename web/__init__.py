"""Entry site: a Flask app friends use to pick who they are, manage their
game list, and add new games. No passwords: pick your name from the ones
the admin added via the CLI, like Tricount's group-link model.

Every write goes through gameclub.store.Store, same as the CLI, then
git_sync commits and pushes data/ so the repo stays the source of truth.
"""
