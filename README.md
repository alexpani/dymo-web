# DYMO Label Web App

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** (USB).

In produzione gira **distribuita su due host** sulla LAN:
- **LXC Debian su Proxmox** (hostname `dymo.local`) — l'app vera e propria
  (Flask, render, history, presets, frontend, Iconify).
- **Raspberry Pi 4** (hostname `dymopi.local`) — thin gateway USB con la
  DYMO collegata. Solo `gateway.py` (~80 righe Flask) sulla porta 5051.

Quando l'utente preme "Stampa" sul browser, la LXC produce il PNG e fa
`POST http://dymopi.local:5051/print`; il Pi esegue il filter chain CUPS
e scrive il bytestream a `/dev/usb/lpN` — pipeline istantanea, nessun
backend CUPS in mezzo.

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

## Architettura distribuita

```
[Mac/iPhone browser]                   [Mac dev]
        │                                  │
        ▼                       git push origin main
[ http://dymo.local:5050 ]              │
        │                  ┌─────────────┼──────────────┬───────────────┐
        ▼                  ▼             ▼              ▼               ▼
[ LXC: dymo (Debian)   GitHub        Pi bare         LXC bare
  app principale ]    backup     /opt/git/...      /opt/git/...
        │              public      hook → restart    hook → restart
        │                          dymo-gateway      dymo-web
        │
   POST /print  PNG + media + kind
        │
        ▼
[ Pi: dymopi (Raspberry Pi 4)
  http://dymopi.local:5051
  gateway.py ]
        │
        ▼
imagetoraster | raster2dymo[lw|lm]  →  /dev/usb/lpN  →  📃
```

**LXC (`dymo.local`)** — l'app principale. Container Debian 13 unprivileged
su Proxmox. Niente CUPS, niente driver DYMO: la stampa è delegata via HTTP.
Risorse modeste (CPU < 1% in idle, ~60 MB RAM).

**Pi (`dymopi.local`)** — thin gateway USB. Solo `gateway.py` su porta 5051,
più i pacchetti `cups-filters` + `printer-driver-dymo` per il filter chain.
Quando arriva il POST /print: PNG → `imagetoraster` → `raster2dymo[lw|lm]`
→ write a `/dev/usb/lpN`. Pipeline ~150 ms end-to-end.

**Mac (dev)** — `origin` ha tre push URL: GitHub, Pi bare, LXC bare. Un
singolo `git push origin main` triggera tre auto-deploy in parallelo
(GitHub backup, Pi gateway restart se cambia gateway code, LXC dymo-web
restart se cambia app code; commit `data:` saltano il restart).

Su macOS (dev/staging) `printing.py` ha fallback automatico al classico
`lp` se né `DYMO_GATEWAY_URL` né `/dev/usb/lp*` sono disponibili.

---

## Stack

- **Backend (LXC)**: Python 3.13 + Flask + waitress
- **Rendering (LXC)**: Pillow (300 DPI), `qrcode[pil]`
- **Icone (LXC)**: Iconify SVG → PNG via `svglib` + `reportlab` (cache `/tmp`)
- **Font**: DejaVu Sans (LXC/Pi) / Helvetica.ttc (Mac dev), per piattaforma
- **Stampa (Pi)**: `gateway.py` (Flask) → CUPS filter binaries → `/dev/usb/lpN`
- **Frontend**: HTML + CSS + JS vanilla in `static/*.html`, no build, no framework
- **Persistenza**: `~/.config/dymo-web/{preset_overrides,history}.json` sulla LXC
  + `localStorage` lato browser per il draft dell'editor
- **Backup**: snapshot/replication della LXC gestiti da Proxmox (out of band)

---

## Setup da zero

### A) LXC su Proxmox (l'app)

Prerequisiti: container Debian 12+ unprivileged, IP fisso, hostname `dymo`,
utente `alexpani` con sudo, SSH abilitato.

```bash
# Dal Mac, copia la pubkey e clona il repo
ssh-copy-id alexpani@<lxc-ip>
ssh alexpani@<lxc-ip> 'git clone https://github.com/alexpani/dymo-web.git ~/dymo-web'

# Dal Mac, lancia il setup (chiede sudo password una volta sulla LXC)
ssh -t alexpani@<lxc-ip> '~/dymo-web/scripts/setup-lxc.sh dymopi.local'
```

`setup-lxc.sh <pi-host>` installa: Python+venv, font DejaVu, libcairo dev,
requirements pip, e crea il systemd unit `dymo-web.service` con
`Environment=DYMO_GATEWAY_URL=http://<pi-host>:5051`. Niente CUPS, niente
driver DYMO sulla LXC.

### B) Pi gateway

Prerequisiti: Pi 4 con Pi OS Lite 64-bit, hostname `dymopi`, utente
`alexpani`, DYMO Duo collegata via USB.

```bash
# Sul Pi, da zero (recovery script completo)
ssh alexpani@dymopi.local
sudo apt-get install -y git
git clone https://github.com/alexpani/dymo-web.git ~/dymo-web
~/dymo-web/scripts/full-recovery.sh

# Quindi attiva il gateway (microservice porta 5051)
~/dymo-web/scripts/setup-pi-gateway.sh

# Stop l'app monolitica (ridondante con la LXC ora)
sudo systemctl disable --now dymo-web
```

Il `full-recovery.sh` continua a fare anche il setup full-app (storica,
utile per scenari senza LXC). Sul gateway-only basta `setup-pi-gateway.sh`.

### C) Auto-deploy dal Mac (triple-push)

Bare repo su Pi e LXC, hook che restartano i rispettivi service:

```bash
# Una volta, sul Pi (dymo-gateway)
ssh -t alexpani@dymopi.local '~/dymo-web/scripts/setup-pi-autodeploy.sh dymo-gateway'

# Una volta, sulla LXC (dymo-web)
ssh -t alexpani@dymo.local '~/dymo-web/scripts/setup-pi-autodeploy.sh dymo-web'
```

Sul Mac, configura `origin` con tre push URL:
```bash
cd ~/Claude\ Code/dymo-web
git remote set-url --add --push origin alexpani@dymopi.local:/opt/git/dymo-web.git
git remote set-url --add --push origin alexpani@dymo.local:/opt/git/dymo-web.git
```

Da quel momento `git push origin main` aggiorna GitHub + entrambi i
bare-repo, e i due hook restartano i rispettivi service in parallelo.

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

## Backup + Disaster recovery

Stato vivo sulla LXC: `~/.config/dymo-web/preset_overrides.json` (taratura)
e `history.json` (cronologia con miniature).

**Backup**: gestiti da Proxmox a livello di container (snapshot e
replication, configurati nella console PVE — niente cron applicativo).

**Recovery scenari**:

| Cosa muore | Cosa fare | Tempo | Dati persi |
|---|---|---|---|
| LXC | Rollback all'ultimo snapshot da Proxmox | ~10 s | ≤ frequenza snapshot |
| SD del Pi | Reflash + `~/dymo-web/scripts/setup-pi-gateway.sh` | ~5 min | **zero** (sono sulla LXC) |
| Code corrotto sul Pi | `git push origin main` dal Mac riallinea | <2 s | nessuno |
| Tutto contemporaneamente | Restore snapshot LXC + reflash + setup Pi | ~10 min | ≤ frequenza snapshot |

Il Pi è completamente stateless: cambia SD, rigenera la chiave SSH,
relancia gli script di setup, e in pochi minuti torna gateway operativo.
La LXC ha tutti i dati e Proxmox la backuppa nativamente — non serve nessun
backup applicativo dentro l'app.

`scripts/backup-data.sh` e `scripts/setup-cron-backup.sh` esistono ancora
nel repo per chi avesse setup il Pi monolitico storico. Non sono usati
nell'architettura LXC + Pi gateway.

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
app.py                  Flask app principale (sulla LXC)
gateway.py              Microservice USB sul Pi (porta 5051, ~80 righe Flask)
label_render.py         FORMATS + render() + Iconify fetch
printing.py             Tre path: gateway HTTP > direct-USB > lp (Mac)
presets_store.py        JSON store delle override per-preset
history.py              Ring buffer della cronologia stampe (cap 200)
requirements.txt        Flask, waitress, Pillow, qrcode, svglib, reportlab,
                        python-dotenv (gateway.py usa solo Flask+waitress)

static/
  index.html            Frontend home
  presets.html          Gestore preset (/presets)
  history.html          Cronologia paginata (/history)

etc/
  dymo-web.service      Unit dell'app principale (LXC; pure il Pi storico)
  dymo-gateway.service  Unit del gateway (Pi)

scripts/
  setup-lxc.sh             Setup app sulla LXC (deps + venv + systemd)
  setup-pi-gateway.sh      Attiva il gateway sul Pi (porta 5051)
  setup-pi-direct-usb.sh   usblp + udev + gruppo lp + cupsdisable
  setup-pi-autodeploy.sh   Bare repo + post-receive hook + sudoers (parametrico)
  full-recovery.sh         One-shot completo per un Pi vergine (legacy ma utile)
  setup-cron-backup.sh     Legacy (cron+GitHub backup); non usato in LXC mode
  backup-data.sh           Legacy (per setup-cron-backup); non usato in LXC mode
  update-deps.sh           apt + pip dopo cambio requirements
  bench-direct.py          Profilatura della pipeline (no stampa fisica)

data/                   Snapshot legacy dei JSON (commitati dal cron, in modalità
                        Pi-monolitica). In modalità LXC il backup lo fa Proxmox.
```
