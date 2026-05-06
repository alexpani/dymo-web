#!/bin/bash
# One-shot: configure 'git push pi main' to auto-pull + restart dymo-web service.
# Idempotent. Run on the Pi (sudo password required once).
set -e

REPO=/opt/git/dymo-web.git
WORK=/home/alexpani/dymo-web
USER_NAME=alexpani

if [ ! -d "$REPO" ]; then
    echo "ERROR: bare repo not found at $REPO. Run the README's Pi setup first."
    exit 1
fi

echo "=== 1. sudoers: allow $USER_NAME to restart dymo-web without password ==="
sudo tee /etc/sudoers.d/dymo-web > /dev/null <<EOF
# Allow $USER_NAME to restart the dymo-web service without a password
# (used by the post-receive Git hook for automatic deploy).
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart dymo-web
EOF
sudo chmod 440 /etc/sudoers.d/dymo-web
sudo visudo -cf /etc/sudoers.d/dymo-web > /dev/null
echo "  /etc/sudoers.d/dymo-web installed (syntax OK)"

echo ""
echo "=== 2. post-receive hook in $REPO ==="
sudo tee $REPO/hooks/post-receive > /dev/null <<'HOOK'
#!/bin/bash
# Auto-deploy: pull the working copy and restart the systemd service
# whenever someone pushes to the bare repo.
# Skips the restart when the only files changed live under data/ — those
# are the nightly backup commits and don't affect the running code.
set -e

WORK=/home/alexpani/dymo-web
BRANCH=main

while read oldrev newrev refname; do
    branch=$(echo "$refname" | sed 's,refs/heads/,,')
    if [ "$branch" = "$BRANCH" ]; then
        echo "[post-receive] deploying $branch ($newrev)"
        unset GIT_DIR GIT_WORK_TREE
        cd "$WORK"
        git pull --ff-only origin "$BRANCH"
        # Restart only if something outside data/ changed
        if git diff --name-only "$oldrev..$newrev" 2>/dev/null | grep -qv '^data/'; then
            sudo /usr/bin/systemctl restart dymo-web
            echo "[post-receive] deploy done (service restarted)."
        else
            echo "[post-receive] data-only change; service not restarted."
        fi
    fi
done
HOOK
sudo chown $USER_NAME:$USER_NAME $REPO/hooks/post-receive
sudo chmod +x $REPO/hooks/post-receive
echo "  hook installed and made executable"

echo ""
echo "=== Verify ==="
echo "sudoers:"
sudo cat /etc/sudoers.d/dymo-web
echo ""
echo "hook:"
ls -la $REPO/hooks/post-receive
echo ""
echo "From now on:  'git push pi main'  ⇒  pull + systemctl restart automatic."
