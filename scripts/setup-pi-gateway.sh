#!/bin/bash
# Turn the existing Pi (running the full dymo-web app) into a thin USB
# printer gateway: keeps the direct-USB plumbing, adds a tiny Flask
# microservice on port 5051, and stops the full app once everything is
# verified by the user.
#
# Idempotent: safe to re-run.
set -e

REPO=/home/alexpani/dymo-web
cd "$REPO"

echo "=== 1. Pull latest code ==="
git pull --ff-only

echo ""
echo "=== 2. Make sure the venv has Flask + waitress (no Pillow needed) ==="
.venv/bin/pip install -q --upgrade Flask waitress

echo ""
echo "=== 3. Install systemd unit for the gateway ==="
sudo install -m 644 etc/dymo-gateway.service /etc/systemd/system/dymo-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now dymo-gateway

sleep 1
echo ""
echo "=== 4. Health check ==="
curl -s http://localhost:5051/health | python3 -m json.tool || echo "FAILED"
echo ""
echo "Gateway is up on port 5051."
echo "The full dymo-web service on port 5050 is still running — leave it"
echo "alone until the LXC takes over. Stop it later with:"
echo "  sudo systemctl disable --now dymo-web"
