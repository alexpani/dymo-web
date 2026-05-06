"""
Printing layer.

Three execution paths, picked in this order:

  - GATEWAY HTTP (LXC / any host where DYMO_GATEWAY_URL is set): POSTs the
    PNG + media + kind to a thin Flask service running on the Pi that owns
    the USB cable. The Pi runs the actual filter chain and writes to
    /dev/usb/lpN. Used when env var DYMO_GATEWAY_URL is non-empty.

  - DIRECT USB (Linux/Pi, ~1s end-to-end): pipes the PNG through CUPS'
    own `imagetoraster` and `raster2dymo*` filter binaries (subprocess) and
    writes the resulting DYMO-native bytes directly to /dev/usb/lpN.
    Skips the slow CUPS USB backend entirely. Used when /dev/usb/lp0
    (and lp1 for tape) are accessible to the running user.

  - CUPS lp (macOS dev/staging): falls back to the standard `lp` command
    when neither of the above is available.

The frontend doesn't need to know which path is used; list_printers()
returns the same shape ([{name, is_default}]) in all cases.
"""

import os
import platform
import subprocess
import tempfile
import urllib.request
import urllib.error
import json
import io
from label_render import FORMATS, DPI, resolve_cups_media


# ── Direct USB configuration (Linux only) ─────────────────────────────────────
# Maps preset kind to: device node, PPD file, and CUPS filter binary.
DIRECT_LABEL = {
    'kind': 'label',
    'name': 'DYMO_LabelWriter_DUO_Label',
    'device': '/dev/usb/lp0',
    'ppd':    '/etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd',
    'filter': '/usr/lib/cups/filter/raster2dymolw',
}
DIRECT_TAPE = {
    'kind': 'tape',
    'name': 'DYMO_LabelWriter_DUO_Tape_128',
    'device': '/dev/usb/lp1',
    'ppd':    '/etc/cups/ppd/DYMO_LabelWriter_DUO_Tape_128.ppd',
    'filter': '/usr/lib/cups/filter/raster2dymolm',
}
DIRECT_BY_KIND = {DIRECT_LABEL['kind']: DIRECT_LABEL, DIRECT_TAPE['kind']: DIRECT_TAPE}
IMAGETORASTER  = '/usr/lib/cups/filter/imagetoraster'


def _direct_available_for(kind):
    """True if direct-USB pipeline can be used for this kind on this host."""
    if platform.system() != 'Linux':
        return False
    cfg = DIRECT_BY_KIND.get(kind)
    if not cfg:
        return False
    return (os.access(cfg['device'], os.W_OK)
            and os.path.exists(cfg['ppd'])
            and os.access(cfg['filter'], os.X_OK)
            and os.access(IMAGETORASTER, os.X_OK))


# ── Common helpers ────────────────────────────────────────────────────────────
def _px_to_mm(px):
    return round(px / DPI * 25.4, 1)


def _print_args(fmt, image):
    """
    Returns (image_to_send, media_arg) for the given preset+image.

    For label kind: PPD-defined cups_media (or Custom.WxHmm fallback).
    For tape kind:  rotate the landscape PNG to portrait and use exact length.
    """
    if fmt.get('kind') == 'tape':
        rotated = image.rotate(90, expand=True)
        length_mm = _px_to_mm(rotated.size[1])
        return rotated, f"Custom.{fmt['width_mm']}x{length_mm}mm"
    media = resolve_cups_media(fmt) or f"Custom.{fmt['width_mm']}x{fmt['height_mm']}mm"
    return image, media


# ── Direct USB pipeline ───────────────────────────────────────────────────────
_FILTER_ENV_BASE = {
    'CHARSET': 'utf-8',
    'LANG': 'en_US.UTF-8',
    'CUPS_DATADIR': '/usr/share/cups',
    'CUPS_SERVERROOT': '/etc/cups',
    'CUPS_FONTPATH': '/usr/share/cups/fonts',
    'TMPDIR': '/tmp',
}


def _filter_env(ppd, content_type):
    env = os.environ.copy()
    env.update(_FILTER_ENV_BASE)
    env['PPD'] = ppd
    env['CONTENT_TYPE'] = content_type
    env['DEVICE_URI'] = 'file:///dev/null'
    return env


def _run_filter(argv, env, stdin_data=None, input_file=None):
    """Run a CUPS filter subprocess. Returns stdout bytes; raises on failure."""
    if input_file:
        argv = argv + [input_file]
    p = subprocess.run(argv, input=stdin_data, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed (exit {p.returncode}): "
                           f"{p.stderr.decode(errors='ignore')[:300]}")
    return p.stdout


def _print_direct(cfg, image, media):
    """
    PNG → cups-raster (imagetoraster) → dymo-native (raster2dymo*) → /dev/usb/lpN.
    Returns the number of bytes written.
    """
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as png_tmp:
        image.save(png_tmp.name, format='PNG')
        png_path = png_tmp.name

    try:
        # fit-to-page tells imagetoraster to scale the bitmap to the media size
        # (otherwise a 1-2 px mismatch can spill onto a second label).
        opts = f"media={media} PageSize={media} fit-to-page"
        cups_raster = _run_filter(
            [IMAGETORASTER, '1', os.environ.get('USER', 'web'), 'dymo-web', '1', opts],
            _filter_env(cfg['ppd'], 'image/png'),
            input_file=png_path,
        )
        dymo_bytes = _run_filter(
            [cfg['filter'], '1', os.environ.get('USER', 'web'), 'dymo-web', '1', opts],
            _filter_env(cfg['ppd'], 'application/vnd.cups-raster'),
            stdin_data=cups_raster,
        )
    finally:
        try:
            os.unlink(png_path)
        except OSError:
            pass

    with open(cfg['device'], 'wb') as dev:
        dev.write(dymo_bytes)
    return len(dymo_bytes)


# ── Gateway HTTP (Pi as thin USB gateway, app on LXC) ────────────────────────
def _gateway_url():
    return (os.environ.get('DYMO_GATEWAY_URL') or '').rstrip('/')


def _gateway_healthy():
    """Quick HEAD-level check of the gateway. 1.5 s timeout — keeps
    /api/printers responsive even when the Pi is offline."""
    base = _gateway_url()
    if not base:
        return False
    try:
        with urllib.request.urlopen(f'{base}/health', timeout=1.5) as r:
            data = json.loads(r.read().decode())
        return bool(data.get('ok'))
    except Exception:
        return False


def _print_via_gateway(image, kind, media):
    """
    POST the PNG + kind + media to the Pi gateway. The Pi runs the filter
    chain and writes to /dev/usb/lpN.
    Returns the number of bytes the gateway reported sending.
    """
    base = _gateway_url()
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    png = buf.getvalue()

    boundary = 'dymowebbnd' + os.urandom(8).hex()
    body = io.BytesIO()
    def field(name, val):
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    field('kind', kind)
    field('media', media)
    body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="label.png"\r\n'
               f'Content-Type: image/png\r\n\r\n'.encode())
    body.write(png)
    body.write(f'\r\n--{boundary}--\r\n'.encode())

    req = urllib.request.Request(
        f'{base}/print',
        data=body.getvalue(),
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    if not data.get('ok'):
        raise RuntimeError(data.get('error', 'gateway returned ok=false'))
    return int(data.get('bytes', 0))


# ── CUPS lp fallback ──────────────────────────────────────────────────────────
def _print_via_lp(printer_name, image, fmt, media):
    extra = [] if fmt.get('kind') == 'tape' else ['-o', 'fit-to-page']
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        image.save(tmp.name, format='PNG')
        path = tmp.name
    try:
        cmd = ['lp', '-d', printer_name, '-o', f'media={media}', *extra, path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ── Public API ────────────────────────────────────────────────────────────────
def list_printers():
    """
    Order of preference: gateway (env DYMO_GATEWAY_URL) > direct USB > lpstat.
    The two queues advertised in gateway/direct mode are virtual labels for
    the slot kind — the actual routing happens server-side.

    In gateway mode, the gateway is health-checked first: if the Pi is
    offline, returns an empty list so the frontend's status dot turns red.
    """
    if _gateway_url():
        if not _gateway_healthy():
            return []
        return [
            {'name': DIRECT_LABEL['name'], 'is_default': True},
            {'name': DIRECT_TAPE['name'],  'is_default': False},
        ]
    direct = []
    for cfg in (DIRECT_LABEL, DIRECT_TAPE):
        if _direct_available_for(cfg['kind']):
            direct.append({'name': cfg['name'], 'is_default': cfg['kind'] == 'label'})
    if direct:
        return direct
    return _list_printers_cups()


def _list_printers_cups():
    printers = []
    try:
        result = subprocess.run(['lpstat', '-p'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                if parts[0] == 'printer':
                    printers.append(parts[1])
                elif parts[0] == 'la' and len(parts) >= 3 and parts[1] == 'stampante':
                    printers.append(parts[2])
    except subprocess.CalledProcessError:
        return []

    default = None
    try:
        result = subprocess.run(['lpstat', '-d'], capture_output=True, text=True, check=True)
        line = result.stdout.strip()
        if ':' in line:
            default = line.split(':', 1)[1].strip()
    except subprocess.CalledProcessError:
        pass

    return [{'name': p, 'is_default': p == default} for p in printers]


def print_label(printer_name, image, format_index):
    """
    Render a label and send it to the printer.
    Returns (ok: bool, message: str).
    """
    fmt = FORMATS[format_index]
    img_to_send, media = _print_args(fmt, image)
    kind = fmt.get('kind') or 'label'

    if _gateway_url():
        try:
            n = _print_via_gateway(img_to_send, kind, media)
            return True, f"sent {n} bytes via gateway"
        except Exception as e:
            return False, f"gateway failed: {e}"

    cfg = DIRECT_BY_KIND.get(kind)
    if cfg and _direct_available_for(cfg['kind']):
        try:
            n = _print_direct(cfg, img_to_send, media)
            return True, f"sent {n} bytes to {cfg['device']} (direct USB)"
        except Exception as e:
            return False, f"direct USB failed: {e}"

    return _print_via_lp(printer_name, img_to_send, fmt, media)
