# DYMO Label Web App

Minimal web app to print labels on a DYMO LabelWriter Duo via USB on macOS.

## Setup

1. Install dependencies:
   ```
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Create `.env` from `.env.example`:
   ```
   cp .env.example .env
   ```

3. Run:
   ```
   python app.py
   ```

Access at `http://localhost:5050`

## Troubleshooting

### CUPS / lpstat
Check printer list:
```
lpstat -p
lpstat -d
```

Check available media sizes for a printer:
```
lpoptions -p <printer-name> -l
```
