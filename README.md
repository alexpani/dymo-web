# DYMO Label Web App

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** collegata
via USB al Mac. Server Flask locale, frontend HTML/JS vanilla, stampa via CUPS (`lp`).

Pensata per uso casalingo / piccolo ufficio: aprila dal Mac o dall'iPhone sulla
stessa rete Wi-Fi e stampa.

## Funzionalità

- **Editor rich text** (contenteditable nativo): seleziona una parte del testo e
  applica grassetto / corsivo solo a quella.
- **4 preset etichette adesive** (89×36, 89×28, 57×32, 32×57 mm) e
  **4 preset nastro D1** (9, 12, 19, 24 mm).
- **Auto-selezione stampante** in base al tipo di preset (slot Label vs slot Tape).
- **Auto-fit del font** (binary search sulla dimensione massima che entra), con
  override manuale tramite slider e pulsante "Auto" per tornare indietro.
- **Auto-fit della lunghezza** sui nastri (come fa la app DYMO ufficiale).
- **Allineamento** sinistra / centro / destra.
- **QR code opzionale** a sinistra del testo.
- **Anteprima live** con debounce 300 ms.

## Setup

```bash
cd ~/Claude\ Code/dymo-web
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # opzionale, default PORT=5050
```

## Avvio

```bash
source .venv/bin/activate
python app.py
```

Apri **http://localhost:5050** sul Mac, oppure `http://<ip-del-mac>:5050` da iPhone
sulla stessa rete.

## Preset etichette

| Preset                       | Codice | Media CUPS              | Stampante  |
| ---------------------------- | ------ | ----------------------- | ---------- |
| 89 × 36 mm Address           | 99012  | `w101h252`              | `_Label`   |
| 89 × 28 mm Address Small     | 99010  | `w81h252`               | `_Label`   |
| 57 × 32 mm Multipurpose      | 11354  | `w162h90`               | `_Label`   |
| 32 × 57 mm Multipurpose vert | 11354  | `w162h90`               | `_Label`   |
| Nastro 9 mm  (auto-fit)      | D1-9   | `Custom.9xLENGTHmm`     | `_Tape`    |
| Nastro 12 mm (auto-fit)      | D1-12  | `Custom.12xLENGTHmm`    | `_Tape`    |
| Nastro 19 mm (auto-fit)      | D1-19  | `Custom.19xLENGTHmm`    | `_Tape`    |
| Nastro 24 mm (auto-fit)      | D1-24  | `Custom.24xLENGTHmm`    | `_Tape`    |

I preset Tape (`kind: 'tape'`) hanno **lunghezza variabile**: il PNG viene ruotato
in portrait e la lunghezza è calcolata dal contenuto.

Per aggiungere un preset: edita `FORMATS` in `label_render.py`. Per i preset Label,
`cups_media` deve essere uno dei nomi nel PPD:

```bash
lpoptions -p DYMO_LabelWriter_DUO_Label -l   # cerca "PageSize"
```

Se non c'è, lascia `cups_media: None` e il backend userà `Custom.WxHmm`.

## Stack

- **Backend**: Python 3.12 + Flask + waitress
- **Rendering**: Pillow (300 DPI), `qrcode[pil]`
- **Stampa**: subprocess su `lp` di CUPS
- **Frontend**: HTML + CSS + JS vanilla in `static/index.html`, no framework, no build
- **Persistenza**: nessuna

## Dipendenza dai driver DYMO

Questa app delega tutta la comunicazione USB a CUPS, che a sua volta usa i driver
DYMO ufficiali (`/Library/Printers/DYMO/`). Quei driver sono **x86_64-only** e
DYMO ne sconsiglia l'uso sulle prossime versioni di macOS Apple Silicon.

Su macOS funziona finché Rosetta è disponibile. Per uso "permanente" si consiglia
di spostare il server su un Raspberry Pi (vedi sezione sotto): su Linux ARM64 i
driver DYMO sono open source e mantenuti.

## Setup su Raspberry Pi (deploy permanente)

Il setup consigliato è far girare l'app su un **Raspberry Pi 4** sempre acceso,
con la DYMO collegata via USB al Pi. Mac e iPhone restano client che aprono il
browser.

### Preparazione SD (Mac)
1. **Raspberry Pi Imager** → Raspberry Pi OS Lite (64-bit)
2. Edit settings: hostname `dymo`, SSH abilitato (incolla la public key),
   user/password, Wi-Fi se serve, locale `Europe/Rome`
3. Flash, inserisci nel Pi, alimenta

### Setup sistema (sul Pi via SSH `pani@dymo.local`)
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip cups printer-driver-dymo \
                    fonts-dejavu git
sudo usermod -aG lpadmin $USER

# Blacklist usblp (interferisce con DYMO)
echo 'blacklist usblp' | sudo tee /etc/modprobe.d/blacklist-usblp.conf
sudo modprobe -r usblp || true

# CUPS accessibile in rete (per amministrare via http://dymo.local:631)
sudo cupsctl --remote-admin --remote-any --share-printers
sudo systemctl enable --now cups
```

### Aggiunta DYMO
Collega la DYMO via USB al Pi, poi dal Mac apri `http://dymo.local:631` →
*Administration → Add Printer* e aggiungi entrambe le code (Label e Tape).
Annota i nomi con `lpstat -p`. Per ognuna:
```bash
lpadmin -p <nome> -o printer-error-policy=retry-current-job
```

### Bare repo Git + push dal Mac
Sul Pi:
```bash
sudo mkdir -p /opt/git && sudo chown $USER:$USER /opt/git
git init --bare /opt/git/dymo-web.git
```
Sul Mac:
```bash
cd ~/Claude\ Code/dymo-web
git remote add pi pani@dymo.local:/opt/git/dymo-web.git
git push pi main
```
Sul Pi:
```bash
git clone /opt/git/dymo-web.git ~/dymo-web
cd ~/dymo-web && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Auto-start (systemd)
Crea `/etc/systemd/system/dymo-web.service`:
```ini
[Unit]
Description=DYMO Label Web App
After=network-online.target cups.service
Requires=cups.service

[Service]
Type=simple
User=pani
WorkingDirectory=/home/pani/dymo-web
Environment=PORT=5050
ExecStart=/home/pani/dymo-web/.venv/bin/python app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now dymo-web
journalctl -u dymo-web -f   # log in tempo reale
```

### Deploy automatico (opzionale)
Sul Pi, in `/opt/git/dymo-web.git/hooks/post-receive`:
```bash
#!/bin/bash
cd /home/pani/dymo-web && git pull --ff-only && sudo systemctl restart dymo-web
```
+ snippet sudoers `/etc/sudoers.d/dymo-web`:
```
pani ALL=(root) NOPASSWD: /usr/bin/systemctl restart dymo-web
```
Da quel momento in poi: `git push pi main` dal Mac fa deploy automatico in <5s.

### Note sul rendering Linux
- Il font usato su Linux è **DejaVu Sans** (4 file separati per le facce). Il
  codice rileva la piattaforma in `label_render.py:FONT_FACES` e cambia path da
  solo. Per cambiare font, modifica quella mappa.
- I `cups_media` dei preset sono validati per i PPD macOS DYMO. Su Linux i nomi
  potrebbero differire — verifica con `lpoptions -p <nome> -l` e aggiorna
  `FORMATS` se serve.

## Troubleshooting

### La stampante non appare in `lpstat -p`

- Verifica che la DYMO sia collegata: `system_profiler SPUSBDataType | grep -i dymo`
- Aggiungila in *Impostazioni di Sistema → Stampanti e Scanner → +*
- La LabelWriter Duo appare come **due** code distinte: `..._Label` (adesive) e
  `..._Tape` (nastro D1). Aggiungile entrambe se vuoi usare entrambi gli slot.

### CUPS error: `UsbPrinterClassDriver.bundle non disponibile`

Il filtro USB del driver DYMO è stato rimosso (capita su update di macOS).
Reinstalla **DYMO Label v8** o **DYMO Connect for Desktop**, poi verifica che
esista `/Library/Printers/DYMO/Filters/UsbPrinterClassDriver.bundle`.

### Stampa esce a cavallo di due etichette / avanza troppo

Il driver non riconosce il media size richiesto e usa il default. Trova il nome
esatto nel PPD:

```bash
grep "11354\|99012\|99010" /etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd | head
```

Aggiorna `cups_media` nel relativo preset.

### La stampante Tape si disabilita dopo un errore

Dopo un job fallito CUPS può disabilitare la stampante e bloccare la coda.
Riabilitala una volta sola:

```bash
cupsenable DYMO_LabelWriter_DUO_Tape_128
lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -o printer-error-policy=retry-current-job
```

Il secondo comando configura CUPS a riprovare invece di disabilitare la stampante
al primo errore (persistente in `/etc/cups/printers.conf`).

### Pagina vuota / contenuto strano nel browser

Se hai mai installato un'altra app web su `localhost:5050` (tipo "Labelle Web"),
il suo Service Worker potrebbe intercettare le richieste e servire la versione
cached. In DevTools → Application → Service Workers → Unregister, e svuota la
cache.
