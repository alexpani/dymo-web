#!/usr/bin/env python3
"""
Benchmark direct-USB pipeline vs CUPS backend, on the Pi.
Run on the Pi after setup-pi-direct-usb.sh:

    cd ~/dymo-web && .venv/bin/python scripts/bench-direct.py

DOES NOT print anything physical: writes the dymo-native bytes to a tmp file.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.expanduser('~/dymo-web'))
from label_render import render
from printing import _print_args, FORMATS

PPD = '/etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd'
FORMAT_INDEX = 1   # 11354
TEXT = 'Bench'


def main():
    fmt = FORMATS[FORMAT_INDEX]
    img = render(FORMAT_INDEX, runs=[{'text': TEXT, 'bold': False, 'italic': False}], align='center')
    img2, media, _ = _print_args(fmt, img)
    img2.save('/tmp/bench.png', format='PNG')

    print(f"Format: {fmt['name']}, media={media}, PNG={img2.size}")

    # Variant A: cupsfilter to dymo-native, NO write to device (just measure render+filter)
    t0 = time.perf_counter()
    r = subprocess.run(
        ['/usr/sbin/cupsfilter', '-p', PPD, '-o', f'media={media}',
         '-i', 'image/png', '-m', 'application/vnd.cups-dymo', '/tmp/bench.png'],
        capture_output=True, check=False,
    )
    t_filter = time.perf_counter() - t0
    print(f"\nA. cupsfilter PNG -> dymo-native: {t_filter*1000:.0f} ms "
          f"(stdout {len(r.stdout)} bytes, exit {r.returncode})")
    if r.returncode != 0:
        print(f"   stderr: {r.stderr.decode()[:300]}")
        return

    # Save the dymo-native bytes
    open('/tmp/bench.dymo', 'wb').write(r.stdout)
    print(f"   wrote /tmp/bench.dymo ({len(r.stdout)} bytes)")

    # Variant B: explicit MIME chain image/png -> application/vnd.cups-raster -> dymo (no Ghostscript)
    t0 = time.perf_counter()
    r2 = subprocess.run(
        ['/usr/sbin/cupsfilter', '-p', PPD, '-o', f'media={media}',
         '-i', 'image/png', '-m', 'application/vnd.cups-raster', '/tmp/bench.png'],
        capture_output=True, check=False,
    )
    t_raster = time.perf_counter() - t0
    print(f"\nB. cupsfilter PNG -> cups-raster only: {t_raster*1000:.0f} ms "
          f"({len(r2.stdout)} bytes)")

    # Variant C: time write to /dev/usb/lp0 (uses already-built dymo bytes from A)
    if os.path.exists('/dev/usb/lp0') and os.access('/dev/usb/lp0', os.W_OK):
        # Comment-out the next 4 lines to skip the actual physical print
        print("\nC. write to /dev/usb/lp0 — SKIPPED (would print physically). Uncomment to measure.")
        # t0 = time.perf_counter()
        # with open('/dev/usb/lp0', 'wb') as dev:
        #     dev.write(open('/tmp/bench.dymo', 'rb').read())
        # t_write = time.perf_counter() - t0
        # print(f"   write to /dev/usb/lp0: {t_write*1000:.0f} ms")
    else:
        print("\nC. /dev/usb/lp0 not writable — skip setup or replug DYMO USB")


if __name__ == '__main__':
    main()
