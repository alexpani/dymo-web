# DYMO Label Web App

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** (USB).
In produzione gira su un **Raspberry Pi 4** sempre acceso, accessibile da
qualsiasi browser sulla LAN (Mac, iPhone, ecc.). Frontend HTML + JS vanilla,
backend Flask, stampa via pipeline diretta a `/dev/usb/lpN` che bypassa il
backend USB di CUPS (~30 s → istantaneo).

Repo: [github.com/alexpani/dymo-web](https://github.com/alexpani/dymo-web)

---

## Funzionalità

### Editor
- **Rich text** in `contenteditable`: seleziona una parte e applica
  grassetto / corsivo solo a quella.
- **Allineamento** sx / centro / dx (icone stile word-processor).
- **Slider Dim. font**: auto-fit di default; sposta lo slider per forzare
  un valore, click "Auto" per tornare al fit automatico.
- **Slider Interlinea** 0–100% (default 20%).
- **Reset** azzera l'editor; **Salva bozza** mette l'etichetta in cronologia
  senza stamparla.
- **Persistenza in localStorage**: ricarichi la pagina e ritrovi l'ultima
  cosa che stavi scrivendo (testo, formato, decoro, slider).

### Decoro (mutuamente esclusivo: QR o icona)
- **QR code** (testo o URL) o
- **Icona da [Iconify](https://iconify.design/)**: search box, dropdown set,
  ~150k icone disponibili. Filtri server-side: solo set curati (lucide,
  tabler, mdi, material-symbols, phosphor, heroicons, solar, ic, ri,
  carbon, fluent, bx, octicon, feather, akar-icons), niente
  duotone/two-tone/broken, niente animate, niente colorate. Search molto
  più pulita rispetto al sito Iconify.
- Il decoro si posiziona a sx/dx/sopra/sotto rispetto al testo, oppure
  centrato sull'etichetta se non c'è testo.

### Preset
11 preset built-in (vedi sotto). Default: **57 × 32 mm (99019)**.

| Preset                       | Codice | Media CUPS              | Stampante  |
| ---------------------------- | ------ | ----------------------- | ---------- |
| 89 × 36 mm Address           | 99012  | `w101h252`              | `_Label`   |
| 57 × 32 mm Multipurpose      | 99019  | `w162h90`               | `_Label`   |
| 32 × 57 mm Multipurpose vert | 99019  | `w162h90`               | `_Label`   |
| 89 × 28 mm Address Small     | 99010  | `w81h252`               | `_Label`   |
| 102 × 54 mm Shipping         | 99014  | `w154h286.2`            | `_Label`   |
| 51 × 19 mm Multipurpose      | 11355  | `w54h144`               | `_Label`   |
| 25 × 25 mm Multipurpose      | 11353  | `w72h72`                | `_Label`   |
| Nastro 9 mm  (auto-fit)      | D1-9   | `Custom.9xLENGTHmm`     | `_Tape`    |
| Nastro 12 mm (auto-fit)      | D1-12  | `Custom.12xLENGTHmm`    | `_Tape`    |
| Nastro 19 mm (auto-fit)      | D1-19  | `Custom.19xLENGTHmm`    | `_Tape`    |
| Nastro 24 mm (auto-fit)      | D1-24  | `Custom.24xLENGTHmm`    | `_Tape`    |

I preset Tape hanno **lunghezza variabile**: il PNG viene ruotato in
portrait e la lunghezza è calcolata dal contenuto. Cambiare/aggiungere
preset: edita `FORMATS` in `label_render.py`.

### Cronologia
- **Sidebar in home** con le 8 stampe più recenti come miniature.
- **Pagina `/history`** paginata 10/pagina, filtro per tipo (label/tape).
- **Click** su una miniatura ricarica testo, formato, decoro, slider —
  pronta da modificare/ristampare.
- **Hover → ×** rimuove l'entry dalla cronologia.
- **De-duplicazione**: stampare/salvare lo stesso payload due volte non
  crea doppioni — la vecchia entry viene rimossa e la nuova va in cima.
- Capacità: 200 entries max (FIFO) in `~/.config/dymo-web/history.json`.
- **Color-coding**: bordo sinistro arancio = nastro, grigio = etichetta.

### Gestore preset (`/presets`)
Per ogni preset puoi regolare:
- **Offset stampa X / Y in mm** — compensa disallineamenti meccanici della
  stampante. **Applicato solo alla stampa**, l'anteprima resta nominale.
- **Margine auto-fit** (0–50%) — riduzione del font massimo per più aria.
- **Padding interno** (mm) — spazio bianco intorno a testo/decoro.

Override salvati in `~/.config/dymo-web/preset_overrides.json`.
Sono **server-side authoritative**: cambi una volta, valgono per tutti i
client (Mac + iPhone) senza dover passare nulla nel payload.

### Indicatori
- **Pallino in alto a destra**: verde = DYMO online, rosso = nessuna DYMO.
  Refresh ogni 30 s.
- **Bottone "Stampa"** mostra ✓ al successo, niente messaggi tecnici.
- **Anteprima live** con debounce 300 ms.
- **Selettore stampante** nascosto quando c'è una sola scelta sensata.

---

## Workflow di sviluppo

```
edit su Mac  →  git push origin main
                       │
        ┌──────────────┼──────────────┐
        ▼                             ▼
   GitHub (backup)            Pi bare repo /opt/git/dymo-web.git
                                       │
                                       ▼
                            post-receive hook:
                              git pull working-copy
                              systemctl restart dymo-web
                              (skip restart se cambia solo data/)
```

Un singolo `git push origin main` da Mac:
- aggiorna GitHub
- triggera l'auto-deploy sul Pi (~2 s)

---

## Architettura "Direct USB" (Pi)

```
PIL render (PNG, ~30 ms)
    ↓
imagetoraster (CUPS filter binary, subprocess)  → cups-raster (~30 ms)
    ↓
raster2dymolw / raster2dymolm (CUPS filter binary, subprocess)
                                                → DYMO native bytes (~30 ms)
    ↓
write to /dev/usb/lp0 (label) o /dev/usb/lp1 (tape) (~10 ms)
```

Niente `lp`, niente `cupsd` in mezzo. Le code CUPS DYMO sono `cupsdisable`d
ma installate, perché ci serve ancora il loro PPD per i filter binari.

Su macOS (dev/staging) c'è un fallback automatico: se `/dev/usb/lp*` non
esiste o non è scrivibile, `printing.py` usa il classico `lp`.

---

## Stack

- **Backend**: Python 3.13 + Flask + waitress
- **Rendering**: Pillow (300 DPI), `qrcode[pil]`
- **Icone**: Iconify SVG → PNG via `svglib` + `reportlab` (cache in `/tmp`)
- **Font**: DejaVu Sans (Pi) / Helvetica.ttc (Mac), selezione per piattaforma
- **Stampa**: subprocess CUPS filter binaries → `/dev/usb/lpN`
- **Frontend**: HTML + CSS + JS vanilla in `static/index.html`, no build, no framework
- **Persistenza**: `~/.config/dymo-web/{preset_overrides,history}.json`
  + `localStorage` lato browser per il draft dell'editor
- **Backup**: cron 03:00 → commit `data:` + push GitHub

---

## Setup nuovo Raspberry Pi (da zero)

> Tempo: ~10 min totali. Requisiti: una microSD (≥ 8 GB) e accesso fisico/SSH al Pi.

### 1. Flash della SD
- **Raspberry Pi Imager** → "Raspberry Pi OS Lite (64-bit)"
- Edit settings: hostname `dymo`, username `alexpani`, SSH abilitato (incolla
  la public key del Mac), Wi-Fi se serve, locale `Europe/Rome`.
- Flash, inserisci nel Pi, alimenta. Aspetta 90 s al primo boot.

### 2. Recovery one-shot
```bash
ssh alexpani@dymo.local
sudo apt-get install -y git
git clone https://github.com/alexpani/dymo-web.git ~/dymo-web
~/dymo-web/scripts/full-recovery.sh
```

Lo script `full-recovery.sh` ricostruisce TUTTO:
- pacchetti apt (Python, CUPS, `printer-driver-dymo`, font, libcairo)
- venv + `pip install -r requirements.txt`
- code CUPS DYMO (auto-rileva il serial USB della Duo collegata)
- direct-USB (`usblp` + udev rule + gruppo `lp` + `cupsdisable` delle code)
- systemd unit (da `etc/dymo-web.service`)
- bare repo `/opt/git/dymo-web.git` + post-receive hook + sudoers NOPASSWD
- cron nightly per il backup
- ripristino di `data/preset_overrides.json` + `data/history.json`

### 3. Aggiungi il Pi come remote sul Mac
```bash
cd ~/Claude\ Code/dymo-web
git remote add pi alexpani@dymo.local:/opt/git/dymo-web.git
# oppure dual-push via origin (consigliato):
git remote set-url --add --push origin alexpani@dymo.local:/opt/git/dymo-web.git
```

### 4. (Opzionale) Backup notturno verso GitHub
Sul Pi:
```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub   # copia su https://github.com/settings/keys
cd ~/dymo-web && git remote add github git@github.com:alexpani/dymo-web.git
~/dymo-web/scripts/backup-data.sh   # test manuale
```

Da qui in avanti il cron alle 03:00 (installato dal recovery script)
copia i due JSON in `data/`, fa commit, e pusha.

---

## Setup dev su Mac

```bash
cd ~/Claude\ Code/dymo-web
brew install cairo pkg-config        # per svglib (Iconify SVG → PNG)
python3.12 -m venv .venv
source .venv/bin/activate
PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig pip install -r requirements.txt
cp .env.example .env                  # opzionale, default PORT=5050
python app.py
```

Apri **http://localhost:5050**. Su Mac con DYMO collegata via USB il
fallback CUPS `lp` viene usato automaticamente — niente direct-USB.

---

## Tarare l'offset di stampa

Se la stampa esce sistematicamente spostata:

1. Stampa una etichetta di test con un contenuto centrato (es. solo
   `Centro`).
2. Misura lo scostamento col righello (in che direzione, quanti mm).
3. Apri `http://dymo.local:5050/presets`, click sul preset.
4. **Offset X**: positivo sposta a destra, negativo a sinistra.
   **Offset Y**: positivo giù, negativo su. Step 0.1 mm.
5. Salva e ristampa.

L'**anteprima resta nominale** durante la taratura (l'offset è una
compensazione meccanica della stampante, non una modifica del layout).

---

## Backup automatico + Disaster recovery

Stato salvato sul Pi:
- `~/.config/dymo-web/preset_overrides.json` — taratura per preset
- `~/.config/dymo-web/history.json` — cronologia con miniature

**Ogni notte alle 03:00** (cron utente alexpani):
1. I due JSON vengono copiati in `~/dymo-web/data/`
2. Se cambiati: commit `data: nightly backup YYYY-MM-DD HH:MM`
3. `git push github main`

Il post-receive hook **non riavvia il service** quando il commit tocca
solo `data/` — i backup sono no-op funzionali per l'app.

**Se la SD muore**: reflash + i 4 comandi della sezione "Setup nuovo
Raspberry Pi" sopra. Il `full-recovery.sh` riapplica anche i
`data/*.json` salvati nel repo, recuperando calibrazione e cronologia.

---

## Troubleshooting

### La DYMO non appare in `lpstat -p`
- Verifica che sia collegata: `lsusb | grep -i dymo`
- Sul Pi: il device dovrebbe esporre `/dev/usb/lp0` e `/dev/usb/lp1`
  (servono `usblp` caricato + udev rule, fatti dal recovery script)
- Se fai add manuale via web CUPS (`http://dymo.local:631`): la Duo
  appare come **due** code distinte (`..._Label` per adesive,
  `..._Tape_128` per nastro D1).

### Stampa esce a cavallo di due etichette / avanza troppo
Il driver non riconosce il media size richiesto e usa il default. Trova
il nome esatto nel PPD e aggiorna `cups_media` nel preset:
```bash
grep '^\*PageSize' /etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd
```

### CUPS disabilita la stampante dopo un errore
Job in coda forever, "Impossibile inviare i dati". Una volta:
```bash
cupsenable DYMO_LabelWriter_DUO_Tape_128
lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -o printer-error-policy=retry-current-job
```

### Pagina vuota / contenuto strano nel browser
Service Worker stale di un'altra app installata in passato sullo stesso
host:port. DevTools → Application → Service Workers → Unregister, e
clear cache.

### macOS: `UsbPrinterClassDriver.bundle non disponibile`
Il filtro USB del driver DYMO è stato rimosso (capita su update di macOS).
Reinstalla **DYMO Label v8** o **DYMO Connect for Desktop**, poi verifica
che esista `/Library/Printers/DYMO/Filters/UsbPrinterClassDriver.bundle`.
Per uso permanente, vai sul Pi.

### Il backup notturno non gira
- `tail -f ~/.dymo-web-backup.log` sul Pi (cron loga lì)
- Verifica `git remote -v` sul working copy: serve un `github` remote
- Verifica che la chiave SSH del Pi sia su https://github.com/settings/keys

---

## Layout repo

```
app.py                 Flask routes + waitress runner
label_render.py        FORMATS (preset) + render() (label vs tape) + Iconify fetch
printing.py            Direct USB (Linux) o lp (Mac fallback)
presets_store.py       JSON store delle override per-preset
history.py             Ring buffer della cronologia stampe (cap 200)
requirements.txt       Flask, waitress, Pillow, qrcode, svglib, reportlab, dotenv

static/
  index.html           Tutto il frontend home (HTML+CSS+JS vanilla)
  presets.html         Pagina /presets per gli override
  history.html         Pagina /history paginata

etc/
  dymo-web.service     Unit systemd (installata in /etc/systemd/system/ dal recovery)

scripts/
  full-recovery.sh         One-shot setup completo per un Pi nuovo
  setup-pi-direct-usb.sh   Direct-USB setup (usblp + udev + gruppo lp)
  setup-pi-autodeploy.sh   Bare repo + post-receive hook + sudoers
  setup-cron-backup.sh     Cron nightly 03:00
  backup-data.sh           Copia JSON in data/ + commit + push GitHub
  update-deps.sh           apt + pip dopo cambio requirements
  bench-direct.py          Profilatura della pipeline (no stampa fisica)

data/                  Snapshot dei JSON di stato (commitati dal cron)
```
