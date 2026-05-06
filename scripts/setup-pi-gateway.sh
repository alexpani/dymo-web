#!/bin/bash
# One-shot setup for a Raspberry Pi to run as the dymo-gateway USB
# microservice. Works from a fresh Pi OS Lite (64-bit) flash AND on an
# existing install — idempotent, safe to re-run.
#
# Prereqs: SSH access as the user below, DYMO LabelWriter DUO plugged in
# and powered on (so step 3 can generate the PPDs).
#
# What it does, end-to-end:
#   1. apt update + system packages (Python venv, CUPS filter chain,
#      DYMO driver) — no Pillow / svglib / libcairo: rendering lives on
#      the LXC.
#   2. Python venv + Flask + waitress.
#   3. Generate the two CUPS DYMO queues — purely to populate
#      /etc/cups/ppd/ with the .ppd files the filter chain needs.
#   4. Run setup-pi-direct-usb.sh (usblp + udev rule + lp group +
#      cupsdisable on the queues).
#   5. Drop-in cloud-init "preserve_hostname: true" so the rename to
#      dymopi survives reboots (Pi Imager's cloud-init otherwise resets
#      hostname from /boot/firmware/user-data on every boot).
#   6. Install + enable dymo-gateway.service on port 5051.
#   7. Health check.
#
# After this script: run scripts/setup-pi-autodeploy.sh dymo-gateway to
# enable 'git push' auto-deploy on the bare repo.
set -e

USER_NAME=${USER:-alexpani}
REPO=/home/$USER_NAME/dymo-web

step() { echo ""; echo "=== $* ==="; }

cd "$REPO"

step "1. System packages"
sudo apt-get update -qq
sudo apt-get install -y python3-venv cups cups-filters printer-driver-dymo

step "2. Python venv + Flask + waitress"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip Flask waitress

step "3. CUPS DYMO queues (to populate /etc/cups/ppd/)"
URI_LABEL=$(sudo lpinfo -v 2>/dev/null | awk '/usb:.*LabelWriter.*DUO%20Label\?/ {print $2; exit}')
URI_TAPE=$(sudo lpinfo  -v 2>/dev/null | awk '/usb:.*LabelWriter.*DUO%20Tape/  {print $2; exit}')
if [ -n "$URI_LABEL" ]; then
    sudo lpadmin -p DYMO_LabelWriter_DUO_Label    -E -v "$URI_LABEL" -m dymo:0/cups/model/lwduol.ppd  || true
    echo "  queue DYMO_LabelWriter_DUO_Label ready"
else
    echo "  WARN: slot Label not found via lpinfo — plug in DYMO and re-run"
fi
if [ -n "$URI_TAPE" ]; then
    sudo lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -E -v "$URI_TAPE"  -m dymo:0/cups/model/lwduot2.ppd || true
    echo "  queue DYMO_LabelWriter_DUO_Tape_128 ready"
else
    echo "  WARN: slot Tape not found via lpinfo — plug in DYMO and re-run"
fi

step "4. Direct-USB (usblp + udev + lp group + cupsdisable)"
"$REPO/scripts/setup-pi-direct-usb.sh"

step "5. cloud-init preserve_hostname drop-in"
sudo tee /etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg > /dev/null <<EOF
preserve_hostname: true
EOF
echo "  /etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg installed"

step "6. systemd unit"
sudo install -m 644 etc/dymo-gateway.service /etc/systemd/system/dymo-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now dymo-gateway

sleep 1
step "7. Health check"
curl -s http://localhost:5051/health | python3 -m json.tool || echo "FAILED"

echo ""
echo "===================================================================="
echo "Gateway up on port 5051."
echo ""
echo "Test from the LXC or Mac:"
echo "  curl http://$(hostname).local:5051/health"
echo ""
echo "Next: enable 'git push' auto-deploy with"
echo "  $REPO/scripts/setup-pi-autodeploy.sh dymo-gateway"
echo "===================================================================="
