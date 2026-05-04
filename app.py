import os
from flask import Flask
from waitress import serve
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
port = int(os.getenv('PORT', 5050))

@app.route('/')
def hello():
    return 'Hello from DYMO Label Web App'

if __name__ == '__main__':
    print(f'Starting server on port {port}...')
    serve(app, host='0.0.0.0', port=port)
