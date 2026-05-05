#!/bin/bash
# One-shot setup to enable direct USB printing on the Pi (bypass CUPS backend).
# Run as a normal user; you'll be asked for your sudo password once.
set -e

echo "=== 1. Re-enable usblp (was blacklisted in CUPS-only mode) ==="
sudo rm -f /etc/modprobe.d/blacklist-usblp.conf
sudo modprobe usblp || true

echo ""
echo "=== 2. udev rule: /dev/usb/lp* writable without root ==="
sudo tee /etc/udev/rules.d/91-dymo-direct.rules > /dev/null <<'EOF'
# DYMO direct USB access — bypass CUPS backend, write to /dev/usb/lpN directly
KERNEL=="lp[0-9]*", SUBSYSTEM=="usb", ATTRS{idVendor}=="0922", MODE="0666", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger

echo ""
echo "=== 3. Disable CUPS queues for DYMO (frees the device but keeps PPDs) ==="
# Don't delete the queues — we still need the PPD files for cupsfilter.
# Just disable so CUPS won't try to dispatch jobs to them.
for q in DYMO_LabelWriter_DUO_Label DYMO_LabelWriter_DUO_Tape_128; do
    if lpstat -p "$q" >/dev/null 2>&1; then
        sudo cupsdisable "$q" 2>/dev/null || true
        sudo cupsreject  "$q" 2>/dev/null || true
        echo "   disabled queue: $q"
    fi
done

echo ""
echo "=== 4. Verify device nodes ==="
sleep 1
ls -la /dev/usb/lp* 2>/dev/null || { echo "ERROR: no /dev/usb/lp* — DYMO not detected by usblp"; exit 1; }

echo ""
echo "=== 5. Permission check ==="
for dev in /dev/usb/lp*; do
    if [ -w "$dev" ]; then
        echo "   OK: $dev writable as $USER"
    else
        echo "   FAIL: $dev not writable as $USER (udev rule didn't take effect — replug DYMO USB)"
    fi
done

echo ""
echo "Setup done. PPDs still installed in /etc/cups/ppd/ for the filter chain to use."
