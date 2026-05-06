#!/bin/bash
# One-shot: configure 'git push <remote> main' to auto-pull + restart a
# systemd service. Idempotent. Run on the host that owns the bare repo
# (Pi for the gateway, LXC for the main app).
#
# Usage: setup-pi-autodeploy.sh [service-name]
#   service-name defaults to 'dymo-web' (the LXC main app).
#   on the Pi gateway, pass 'dymo-gateway'.
set -e

SERVICE=${1:-dymo-web}
REPO=/opt/git/dymo-web.git
WORK=/home/alexpani/dymo-web
USER_NAME=alexpani

if [ ! -d "$REPO" ]; then
    echo "Bare repo missing at $REPO — creating it."
    sudo mkdir -p /opt/git
    sudo chown $USER_NAME:$USER_NAME /opt/git
    git init --bare $REPO
    git -C $REPO symbolic-ref HEAD refs/heads/main
fi

echo "=== Service to be restarted by the hook: $SERVICE ==="

echo ""
echo "=== 1. sudoers: allow $USER_NAME to restart $SERVICE without password ==="
sudo tee /etc/sudoers.d/dymo-web > /dev/null <<EOF
# Allow $USER_NAME to restart the $SERVICE service without a password
# (used by the post-receive Git hook for automatic deploy).
$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart $SERVICE
EOF
sudo chmod 440 /etc/sudoers.d/dymo-web
sudo visudo -cf /etc/sudoers.d/dymo-web > /dev/null
echo "  /etc/sudoers.d/dymo-web installed (syntax OK)"

echo ""
echo "=== 2. post-receive hook in $REPO ==="
sudo tee $REPO/hooks/post-receive > /dev/null <<HOOK
#!/bin/bash
# Auto-deploy: pull the working copy and restart the $SERVICE systemd unit
# whenever someone pushes to the bare repo. Skips the restart when the
# only files changed live under data/ — those are nightly backup commits
# and don't affect the running code.
set -e

WORK=/home/alexpani/dymo-web
BRANCH=main
SERVICE=$SERVICE

while read oldrev newrev refname; do
    branch=\$(echo "\$refname" | sed 's,refs/heads/,,')
    if [ "\$branch" = "\$BRANCH" ]; then
        echo "[post-receive] deploying \$branch (\$newrev) -> \$SERVICE"
        unset GIT_DIR GIT_WORK_TREE
        cd "\$WORK"
        git pull --ff-only origin "\$BRANCH"
        if git diff --name-only "\$oldrev..\$newrev" 2>/dev/null | grep -qv '^data/'; then
            sudo /usr/bin/systemctl restart "\$SERVICE"
            echo "[post-receive] deploy done (\$SERVICE restarted)."
        else
            echo "[post-receive] data-only change; \$SERVICE not restarted."
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
