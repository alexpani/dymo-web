import os
import io
from flask import Flask, jsonify, request
from waitress import serve
from dotenv import load_dotenv
from label_render import FORMATS, render

load_dotenv()

app = Flask(__name__)
port = int(os.getenv('PORT', 5050))

@app.route('/')
def hello():
    return 'Hello from DYMO Label Web App'

@app.route('/api/formats')
def get_formats():
    """Return available label formats."""
    return jsonify([
        {'index': i, 'name': name, 'width_mm': width, 'height_mm': height, 'code': code}
        for i, (name, width, height, code) in enumerate(FORMATS)
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

if __name__ == '__main__':
    print(f'Starting server on port {port}...')
    serve(app, host='0.0.0.0', port=port)
