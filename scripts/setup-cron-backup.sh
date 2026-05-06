#!/bin/bash
# Install (or update) the nightly cron entry that backs up the per-preset
# overrides and the print history into data/ in the repo, and pushes to
# GitHub. Idempotent: re-running rewrites the entry instead of duplicating.
#
# Prerequisite: a 'github' remote pointing at git@github.com:.../dymo-web.git
# (or HTTPS with a token), reachable from alexpani's SSH key. If the remote
# is missing or unreachable the backup script silently exits — cron should
# not spam the inbox.
set -e

USER_NAME=${USER:-alexpani}
WORK=/home/$USER_NAME/dymo-web
ENTRY="0 3 * * * $WORK/scripts/backup-data.sh >> /home/$USER_NAME/.dymo-web-backup.log 2>&1"
TAG="# dymo-web nightly backup"

echo "=== Installing nightly cron for $USER_NAME ==="
# Drop any existing dymo-web entry, then append the new one
crontab -l 2>/dev/null | grep -v "$TAG" > /tmp/cron.tmp || true
echo "$TAG" >> /tmp/cron.tmp
echo "$ENTRY" >> /tmp/cron.tmp
crontab /tmp/cron.tmp
rm /tmp/cron.tmp

echo ""
echo "=== Current crontab ==="
crontab -l

echo ""
echo "Cron job scheduled at 03:00 every night."
echo "Log: ~/.dymo-web-backup.log"
echo ""
echo "If you haven't set up the 'github' remote on the working copy yet:"
echo "  cd ~/dymo-web && git remote add github git@github.com:alexpani/dymo-web.git"
echo "and ensure your SSH public key is added to your GitHub account."
