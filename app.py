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

def _render_kwargs(data):
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
        'offset_x_mm':     overrides['offset_x_mm'],
        'offset_y_mm':     overrides['offset_y_mm'],
    }

@app.route('/api/preview', methods=['POST'])
def preview():
    """Generate and return a preview PNG."""
    try:
        img = render(**_render_kwargs(request.get_json()))
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
        kwargs = _render_kwargs(data)
        img = render(**kwargs)
        ok, message = print_label(printer_name, img, kwargs['format_index'])
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
