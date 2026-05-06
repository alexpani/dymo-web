#!/bin/bash
# Nightly backup: copies preset_overrides.json + history.json into the repo's
# data/ directory and pushes to the 'github' remote (read-only-friendly path
# -> survives a full SD wipe).
#
# Usage: scripts/backup-data.sh
# Triggered automatically by the cron job installed by setup-cron-backup.sh.
set -e

REPO=/home/alexpani/dymo-web
SRC=/home/alexpani/.config/dymo-web
DEST=$REPO/data

cd "$REPO"

mkdir -p "$DEST"
[ -f "$SRC/preset_overrides.json" ] && cp "$SRC/preset_overrides.json" "$DEST/preset_overrides.json"
[ -f "$SRC/history.json" ]          && cp "$SRC/history.json"          "$DEST/history.json"

# Anything to commit?
if git diff --quiet -- data/; then
    exit 0
fi

git add data/
TS=$(date +'%Y-%m-%d %H:%M')
git -c user.email='dymo-web@dymo.local' \
    -c user.name='dymo-web backup' \
    commit -m "data: nightly backup $TS" >/dev/null

# Push to GitHub if configured (skip silently otherwise — cron should not yell)
if git remote get-url github >/dev/null 2>&1; then
    git push github main 2>&1
fi
