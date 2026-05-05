import os
import io
import json
import urllib.request
import urllib.parse
from flask import Flask, jsonify, request, send_from_directory
from waitress import serve
from dotenv import load_dotenv
from label_render import FORMATS, render, resolve_cups_media
from printing import list_printers, print_label
import presets_store
import history

load_dotenv()

app = Flask(__name__, static_folder='static')
port = int(os.getenv('PORT', 5050))

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/formats')
def get_formats():
    """Return available label formats. cups_media is resolved to the string
    appropriate for the current platform (PPDs differ between macOS and Linux)."""
    return jsonify([
        {'index': i, **fmt, 'cups_media': resolve_cups_media(fmt)}
        for i, fmt in enumerate(FORMATS)
    ])

def _render_kwargs(data, for_print=False):
    """
    Build render() kwargs from the API payload + per-preset overrides.

    The mechanical print offset (offset_x/y_mm) compensates a printer-side
    misalignment, so it must be applied to the bytes sent to the printer
    but NOT to the on-screen preview — otherwise the preview shows the
    shifted layout, which is misleading. We force offsets to 0 for previews.
    """
    fmt_index = data.get('format', 0)
    fmt = FORMATS[fmt_index] if 0 <= fmt_index < len(FORMATS) else FORMATS[0]
    overrides = presets_store.get(fmt['name'])
    return {
        'format_index': fmt_index,
        'runs': data.get('runs'),
        'text': data.get('text', ''),
        'decor': data.get('decor', 'none'),
        'qr_content': data.get('qr_content', ''),
        'icon_id': data.get('icon_id', ''),
        'decor_position': data.get('decor_position', 'left'),
        # legacy (older clients)
        'qr_enabled': data.get('qr_enabled', False),
        'qr_position': data.get('qr_position'),
        'bold': data.get('bold', False),
        'italic': data.get('italic', False),
        'align': data.get('align', 'center'),
        'font_size_pt': data.get('font_size_pt') or None,
        # per-preset overrides (server-side authoritative)
        'auto_fit_safety': overrides['auto_fit_safety'],
        'padding_mm':      overrides['padding_mm'],
        'offset_x_mm':     overrides['offset_x_mm'] if for_print else 0.0,
        'offset_y_mm':     overrides['offset_y_mm'] if for_print else 0.0,
    }

@app.route('/api/preview', methods=['POST'])
def preview():
    """Generate and return a preview PNG."""
    try:
        img = render(**_render_kwargs(request.get_json(), for_print=False))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return buf.getvalue(), 200, {'Content-Type': 'image/png'}
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/printers')
def get_printers():
    """Return CUPS printer list."""
    return jsonify(list_printers())

@app.route('/api/print', methods=['POST'])
def print_endpoint():
    """Render a label and send it to a CUPS printer."""
    data = request.get_json()
    printer_name = data.get('printer_name')
    if not printer_name:
        return jsonify({'ok': False, 'message': 'printer_name is required'}), 400

    try:
        kwargs = _render_kwargs(data, for_print=True)
        img = render(**kwargs)
        ok, message = print_label(printer_name, img, kwargs['format_index'])
        if ok:
            try:
                fmt = FORMATS[kwargs['format_index']]
                meta = {'index': kwargs['format_index'], **fmt}
                # Don't store the printer_name in the history (it changes per host)
                payload = {k: v for k, v in data.items() if k != 'printer_name'}
                history.add(payload, meta, img)
            except Exception:
                pass  # history failure shouldn't fail the print
        return jsonify({'ok': ok, 'message': message})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/presets')
def presets_page():
    return send_from_directory('static', 'presets.html')


@app.route('/api/preset_overrides', methods=['GET'])
def api_overrides_get():
    """Return both DEFAULTS and the current per-preset overrides."""
    return jsonify({
        'defaults': presets_store.DEFAULTS,
        'overrides': presets_store.load_all(),
    })


@app.route('/api/preset_overrides/<path:name>', methods=['PUT'])
def api_overrides_put(name):
    try:
        data = request.get_json() or {}
        return jsonify(presets_store.save(name, data))
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/preset_overrides/<path:name>', methods=['DELETE'])
def api_overrides_delete(name):
    try:
        return jsonify(presets_store.reset(name))
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/history')
def history_page():
    return send_from_directory('static', 'history.html')


@app.route('/api/history')
def api_history_list():
    limit  = min(int(request.args.get('limit', 5)), 50)
    offset = max(int(request.args.get('offset', 0)), 0)
    kind   = request.args.get('kind') or None
    if kind not in (None, 'label', 'tape'):
        kind = None
    return jsonify({
        'items': history.list_(limit=limit, offset=offset, kind=kind),
        'total': history.total(),
    })


@app.route('/api/history/<entry_id>', methods=['GET'])
def api_history_get(entry_id):
    item = history.get(entry_id)
    if not item:
        return jsonify({'error': 'not found'}), 404
    return jsonify(item)


@app.route('/api/history/<entry_id>', methods=['DELETE'])
def api_history_delete(entry_id):
    return jsonify({'deleted': history.delete(entry_id)})


@app.route('/api/icons/search')
def icons_search():
    """Proxy to https://api.iconify.design/search — keeps icon discovery
    server-side (consistent retries, easier to swap library later)."""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'icons': []})
    limit = min(int(request.args.get('limit', 24)), 96)
    url = f'https://api.iconify.design/search?query={urllib.parse.quote(q)}&limit={limit}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'dymo-web/1.0'})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        return jsonify({'icons': data.get('icons', [])})
    except Exception as e:
        return jsonify({'icons': [], 'error': str(e)}), 502


if __name__ == '__main__':
    print(f'Starting server on port {port}...')
    serve(app, host='0.0.0.0', port=port)
