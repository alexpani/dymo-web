"""
USB printer gateway — runs on the Raspberry Pi when the main app lives
elsewhere (e.g. an LXC on Proxmox).

Single endpoint, intentionally tiny:

    POST /print
        multipart/form-data fields:
            kind    'label' | 'tape'
            media   CUPS media name (e.g. 'w162h90' or 'Custom.12x60mm')
            file    the PNG bytes (already rotated/offset by the caller)
        returns:
            {"ok": true, "bytes": <int>}     on success
            {"ok": false, "error": "..."}    on any failure

Pipeline mirrors the original direct-USB path: imagetoraster (CUPS filter)
+ raster2dymolw|raster2dymolm (DYMO driver) + write to /dev/usb/lpN.

Dependencies are minimal: Flask + waitress + the system 'cups-filters' and
'printer-driver-dymo' packages. No Pillow, no svglib — the rendering lives
on the LXC. Keeps the Pi as a thin gateway.
"""
import os
import subprocess
import tempfile
from flask import Flask, jsonify, request
from waitress import serve

app = Flask(__name__)

DEVICES = {
    'label': {
        'device': '/dev/usb/lp0',
        'ppd':    '/etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd',
        'filter': '/usr/lib/cups/filter/raster2dymolw',
    },
    'tape': {
        'device': '/dev/usb/lp1',
        'ppd':    '/etc/cups/ppd/DYMO_LabelWriter_DUO_Tape_128.ppd',
        'filter': '/usr/lib/cups/filter/raster2dymolm',
    },
}
IMAGETORASTER = '/usr/lib/cups/filter/imagetoraster'

FILTER_ENV_BASE = {
    'CHARSET': 'utf-8',
    'LANG': 'en_US.UTF-8',
    'CUPS_DATADIR': '/usr/share/cups',
    'CUPS_SERVERROOT': '/etc/cups',
    'CUPS_FONTPATH': '/usr/share/cups/fonts',
    'TMPDIR': '/tmp',
}


def _filter_env(ppd, content_type):
    env = os.environ.copy()
    env.update(FILTER_ENV_BASE)
    env['PPD'] = ppd
    env['CONTENT_TYPE'] = content_type
    env['DEVICE_URI'] = 'file:///dev/null'
    return env


def _run_filter(argv, env, stdin=None, input_file=None):
    if input_file:
        argv = argv + [input_file]
    p = subprocess.run(argv, input=stdin, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed (exit {p.returncode}): "
                           f"{p.stderr.decode(errors='ignore')[:300]}")
    return p.stdout


@app.get('/health')
def health():
    info = {'ok': True, 'devices': {}}
    for kind, cfg in DEVICES.items():
        info['devices'][kind] = {
            'device': cfg['device'],
            'present': os.path.exists(cfg['device']),
            'writable': os.access(cfg['device'], os.W_OK),
        }
    return jsonify(info)


@app.post('/print')
def print_label():
    kind = (request.form.get('kind') or '').strip()
    media = (request.form.get('media') or '').strip()
    f = request.files.get('file')
    if kind not in DEVICES or not media or not f:
        return jsonify({'ok': False, 'error': 'kind, media, file are required'}), 400

    cfg = DEVICES[kind]
    if not os.access(cfg['device'], os.W_OK):
        return jsonify({'ok': False, 'error': f"{cfg['device']} not writable"}), 503

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        f.save(tmp.name)
        png_path = tmp.name

    try:
        # No fit-to-page: the PNG arrives already sized to the imageable area
        # by the app (label_render.imageable_size_mm). Any scaling here would
        # just distort and decentre the bitmap.
        opts = f"media={media} PageSize={media}"
        cups_raster = _run_filter(
            [IMAGETORASTER, '1', os.environ.get('USER', 'gateway'), 'dymo', '1', opts],
            _filter_env(cfg['ppd'], 'image/png'),
            input_file=png_path,
        )
        dymo_bytes = _run_filter(
            [cfg['filter'], '1', os.environ.get('USER', 'gateway'), 'dymo', '1', opts],
            _filter_env(cfg['ppd'], 'application/vnd.cups-raster'),
            stdin=cups_raster,
        )
        with open(cfg['device'], 'wb') as dev:
            dev.write(dymo_bytes)
        return jsonify({'ok': True, 'bytes': len(dymo_bytes)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            os.unlink(png_path)
        except OSError:
            pass


if __name__ == '__main__':
    port = int(os.getenv('GATEWAY_PORT', '5051'))
    print(f'dymo-gateway listening on 0.0.0.0:{port}')
    serve(app, host='0.0.0.0', port=port)
