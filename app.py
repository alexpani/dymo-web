import os
import io
from flask import Flask, jsonify, request, send_from_directory
from waitress import serve
from dotenv import load_dotenv
from label_render import FORMATS, render
from printing import list_printers, print_label

load_dotenv()

app = Flask(__name__, static_folder='static')
port = int(os.getenv('PORT', 5050))

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/formats')
def get_formats():
    """Return available label formats."""
    return jsonify([
        {'index': i, **fmt} for i, fmt in enumerate(FORMATS)
    ])

@app.route('/api/preview', methods=['POST'])
def preview():
    """Generate and return a preview PNG."""
    data = request.get_json()
    format_index = data.get('format', 0)
    text = data.get('text', '')
    qr_enabled = data.get('qr_enabled', False)
    qr_content = data.get('qr_content', '')

    try:
        img = render(format_index, text, qr_enabled, qr_content)
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
    format_index = data.get('format', 0)
    text = data.get('text', '')
    qr_enabled = data.get('qr_enabled', False)
    qr_content = data.get('qr_content', '')
    printer_name = data.get('printer_name')

    if not printer_name:
        return jsonify({'ok': False, 'message': 'printer_name is required'}), 400

    try:
        img = render(format_index, text, qr_enabled, qr_content)
        ok, message = print_label(printer_name, img, format_index)
        return jsonify({'ok': ok, 'message': message})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

if __name__ == '__main__':
    print(f'Starting server on port {port}...')
    serve(app, host='0.0.0.0', port=port)
