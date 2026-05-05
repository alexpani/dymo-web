#!/bin/bash
# Update system + Python deps and restart the service.
# Run on the Pi after pulling a commit that adds new dependencies.
set -e

echo "=== System packages (libcairo2 needed by svglib for icon rendering) ==="
sudo apt-get update -qq
sudo apt-get install -y libcairo2

echo ""
echo "=== Python dependencies ==="
cd /home/alexpani/dymo-web
.venv/bin/pip install -q -r requirements.txt

echo ""
echo "=== Restart service ==="
sudo systemctl restart dymo-web
sleep 1
systemctl is-active dymo-web && echo "OK: dymo-web active" || echo "FAIL"
