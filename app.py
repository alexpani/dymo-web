import os
import io
from flask import Flask, jsonify, request, send_from_directory
from waitress import serve
from dotenv import load_dotenv
from label_render import FORMATS, render, resolve_cups_media
from printing import list_printers, print_label

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
    return {
        'format_index': data.get('format', 0),
        'runs': data.get('runs'),
        'text': data.get('text', ''),
        'qr_enabled': data.get('qr_enabled', False),
        'qr_content': data.get('qr_content', ''),
        'bold': data.get('bold', False),
        'italic': data.get('italic', False),
        'align': data.get('align', 'center'),
        'font_size_pt': data.get('font_size_pt') or None,
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

if __name__ == '__main__':
    print(f'Starting server on port {port}...')
    serve(app, host='0.0.0.0', port=port)
