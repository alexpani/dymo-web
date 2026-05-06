#!/bin/bash
# Full disaster-recovery for the dymo-web Pi.
# Run on a freshly flashed Raspberry Pi OS (Lite, 64-bit) right after
# the first SSH login as the same user used in the original install
# (the script assumes 'alexpani' below — adjust if you use a different
# username on the imager).
#
# Idempotent: safe to re-run.
#
# What it does, end-to-end:
#   1. apt update + system packages (Python, CUPS, DYMO driver, fonts,
#      libcairo headers for svglib)
#   2. clone the repo from GitHub (read-only HTTPS) into ~/dymo-web
#   3. Python venv + pip install
#   4. add the user to lpadmin, enable CUPS in network mode
#   5. add the two CUPS DYMO queues if a DYMO is plugged in
#   6. run setup-pi-direct-usb.sh (load usblp, udev rule, lp group,
#      cupsdisable the queues — keeps PPDs but bypasses CUPS USB)
#   7. install/refresh the systemd unit and enable it
#   8. run setup-pi-autodeploy.sh (sudoers + post-receive hook)
#   9. run setup-cron-backup.sh (nightly backup at 03:00)
#  10. restore preset_overrides.json + history.json from data/ in repo
#
# Resulting state should match the previous Pi 1:1, modulo the SSH key
# you'll need to re-add to GitHub for backup pushes.
set -e

USER_NAME=${USER:-alexpani}
REPO_HTTPS=https://github.com/alexpani/dymo-web.git
REPO_SSH=git@github.com:alexpani/dymo-web.git
WORK=/home/$USER_NAME/dymo-web
CONFIG=/home/$USER_NAME/.config/dymo-web

step()  { echo ""; echo "=== $* ==="; }

step "1. System packages"
sudo apt-get update -qq
sudo apt-get install -y \
    python3-venv python3-pip git \
    cups printer-driver-dymo \
    fonts-dejavu \
    libcairo2 libcairo2-dev pkg-config

step "2. Clone repo (if not already there)"
if [ ! -d "$WORK/.git" ]; then
    git clone "$REPO_HTTPS" "$WORK"
else
    cd "$WORK" && git pull --ff-only
fi

step "3. Python venv + dependencies"
cd "$WORK"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

step "4. CUPS user + network access"
sudo usermod -aG lpadmin "$USER_NAME"
sudo cupsctl --remote-admin --remote-any --share-printers
sudo systemctl enable --now cups

step "5. Re-add the two CUPS DYMO queues"
URI_LABEL=$(lpinfo -v 2>/dev/null | awk '/usb:.*LabelWriter.*DUO%20Label/ {print $2; exit}')
URI_TAPE=$(lpinfo  -v 2>/dev/null | awk '/usb:.*LabelWriter.*DUO%20Tape/  {print $2; exit}')
if [ -n "$URI_LABEL" ]; then
    sudo lpadmin -p DYMO_LabelWriter_DUO_Label -E -v "$URI_LABEL" -m dymo:0/cups/model/lwduol.ppd  || true
    sudo lpadmin -p DYMO_LabelWriter_DUO_Label -o printer-error-policy=retry-current-job             || true
    echo "  added DYMO_LabelWriter_DUO_Label"
else
    echo "  (slot Label not found — plug in the DYMO and re-run, or add manually)"
fi
if [ -n "$URI_TAPE" ]; then
    sudo lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -E -v "$URI_TAPE" -m dymo:0/cups/model/lwduot2.ppd || true
    sudo lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -o printer-error-policy=retry-current-job          || true
    echo "  added DYMO_LabelWriter_DUO_Tape_128"
else
    echo "  (slot Tape not found — plug in the DYMO and re-run, or add manually)"
fi

step "6. Direct-USB setup (usblp, udev, lp group)"
"$WORK/scripts/setup-pi-direct-usb.sh"

step "7. systemd unit"
sudo install -m 644 "$WORK/etc/dymo-web.service" /etc/systemd/system/dymo-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now dymo-web

step "8. Auto-deploy hook (bare repo + post-receive + sudoers)"
"$WORK/scripts/setup-pi-autodeploy.sh"

step "9. Nightly backup cron"
"$WORK/scripts/setup-cron-backup.sh"

step "10. Restore preset overrides + history"
mkdir -p "$CONFIG"
[ -f "$WORK/data/preset_overrides.json" ] && cp "$WORK/data/preset_overrides.json" "$CONFIG/preset_overrides.json"
[ -f "$WORK/data/history.json" ]          && cp "$WORK/data/history.json"          "$CONFIG/history.json"
ls -la "$CONFIG" 2>/dev/null
sudo systemctl restart dymo-web

echo ""
echo "===================================================================="
echo "Recovery complete."
echo ""
echo "  http://dymo.local:5050      → the app"
echo "  http://dymo.local:631       → CUPS web admin"
echo ""
echo "Optional finishing touches:"
echo "  1. add your SSH key to GitHub so the nightly cron can push backups:"
echo "     ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519   (if not already)"
echo "     cat ~/.ssh/id_ed25519.pub                          # add to GitHub"
echo "     cd ~/dymo-web && git remote add github $REPO_SSH"
echo ""
echo "  2. if you push from your Mac via 'git push pi main', re-add the Pi"
echo "     remote on the Mac:  git remote add pi $USER_NAME@dymo.local:/opt/git/dymo-web.git"
echo "===================================================================="
