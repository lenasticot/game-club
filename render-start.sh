#!/usr/bin/env bash
# Render start command: re-clone data/ + its git history fresh on every
# boot (cold start after idle spin-down included), since Render's free
# tier has no persistent disk. Every web write already commits+pushes
# before responding, so GitHub is the real source of truth - a fresh
# clone is always current. Separate from whatever Render itself checked
# out to build the app code, on purpose: this path is the one the app
# writes to and pushes from.
set -euo pipefail

REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/lenasticot/game-club.git"
CLONE_DIR="/tmp/gameclub-data-repo"

rm -rf "$CLONE_DIR"
git clone "$REPO_URL" "$CLONE_DIR"
git -C "$CLONE_DIR" config user.email "gameclub-bot@render"
git -C "$CLONE_DIR" config user.name "Game Club bot"

export GAMECLUB_DATA="$CLONE_DIR/data"
export GAMECLUB_GIT_PUSH=1

# One worker: git_sync's write lock is in-process only, so concurrent
# workers could race on the same clone.
exec gunicorn -w 1 -b "0.0.0.0:${PORT}" "web.app:create_app()"
