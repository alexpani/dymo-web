#!/bin/bash
# Setup the dymo-web app on a Debian 13 LXC. The LXC runs the full
# Flask app (rendering, history, presets, frontend, Iconify) and offloads
# only the actual printing to a thin gateway on the Pi via HTTP
# (DYMO_GATEWAY_URL).
#
# Usage:
#   1) inside the LXC, after first SSH: clone the repo to ~/dymo-web
#   2) ./scripts/setup-lxc.sh <pi-host>
#      e.g. ./scripts/setup-lxc.sh 192.168.68.141
#         or ./scripts/setup-lxc.sh dymopi.local
#
# Idempotent: safe to re-run.
set -e

if [ -z "$1" ]; then
    echo "usage: $0 <pi-host>"
    echo "  e.g.  $0 192.168.68.141"
    echo "        $0 dymopi.local"
    exit 1
fi
PI_HOST=$1
GATEWAY_URL="http://$PI_HOST:5051"
USER_NAME=${USER:-alexpani}
WORK=/home/$USER_NAME/dymo-web

echo "=== 1. apt packages ==="
sudo apt-get update -qq
sudo apt-get install -y \
    python3-venv python3-pip git \
    fonts-dejavu \
    libcairo2 libcairo2-dev pkg-config

# NOTE: deliberately *not* installing cups / printer-driver-dymo here.
# The LXC doesn't print: it sends rendered PNGs to the Pi gateway,
# which owns the USB cable and the DYMO drivers.

echo ""
echo "=== 2. Python venv + dependencies ==="
cd "$WORK"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo ""
echo "=== 3. systemd unit (with DYMO_GATEWAY_URL=$GATEWAY_URL) ==="
sudo tee /etc/systemd/system/dymo-web.service > /dev/null <<EOF
[Unit]
Description=DYMO Label Web App (LXC; prints via gateway on $PI_HOST)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$WORK
Environment=PORT=5050
Environment=DYMO_GATEWAY_URL=$GATEWAY_URL
ExecStart=$WORK/.venv/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now dymo-web

sleep 2
echo ""
echo "=== 4. Health check ==="
systemctl is-active dymo-web
curl -s -o /dev/null -w "GET / -> HTTP %{http_code}\n"            http://localhost:5050/
curl -s -o /dev/null -w "GET /api/printers -> HTTP %{http_code}\n" http://localhost:5050/api/printers
echo ""
echo "Gateway target: $GATEWAY_URL"
echo "App listening:  http://0.0.0.0:5050  (and via mDNS on this LXC's hostname)"
