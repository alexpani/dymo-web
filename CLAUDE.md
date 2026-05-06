# CLAUDE.md

Context per Claude Code in sessioni future. Leggi questo file prima di
toccare il codice.

## Cos'è

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** (USB).
Deploy permanente su Raspberry Pi 4. Frontend HTML/JS vanilla, backend Flask.
Vedi `README.md` per setup, feature complete e troubleshooting.

Repo pubblico: github.com/alexpani/dymo-web.
Pi hostname: `dymo.local` (utente `alexpani`).
URL produzione: `http://dymo.local:5050`.

## Vincoli di scope (non violarli senza consenso esplicito)

- **Niente framework frontend**, niente build step, niente npm. Tutto vanilla
  in `static/*.html`.
- **Backend**: Python 3.13 + Flask + waitress. Niente FastAPI, niente async.
- **File pochi e leggibili.** Niente astrazioni "per il futuro". Tre righe
  simili sono meglio di un'astrazione prematura.
- **Backward compat solo dove serve davvero** (es. `_render_kwargs` accetta
  sia `runs` che il legacy `text+bold+italic` per script curl).
- **Persistenza**: solo i due JSON `~/.config/dymo-web/*.json` (server-side)
  più `localStorage` (lato browser, per il draft dell'editor). Niente DB.
- **Mai mandare un job fisico** (`/api/print` o `lp`) senza autorizzazione
  esplicita dell'utente — consuma materiale.

## Layout

```
app.py              Flask routes + waitress runner.
                    _render_kwargs(data, for_print=False) centralizza il
                    parsing del payload e applica gli override del preset
                    corrente leggendoli da presets_store.
                    for_print=True applica anche l'offset meccanico;
                    /api/preview usa False, /api/print usa True.

label_render.py     FORMATS (lista preset). render() dispatch tra
                    _render_label() (dimensioni fisse) e _render_tape()
                    (lunghezza auto-fit). _layout() = binary search del
                    font massimo che entra. _draw_lines() centra
                    verticalmente sull'altezza visiva con anchor='lt'.
                    _fetch_icon() scarica SVG da Iconify e lo converte
                    in PNG via svglib (cache /tmp/dymo-web-icons/).

printing.py         Due path stampa con auto-select:
                    - DIRECT USB (Linux/Pi): pipe imagetoraster +
                      raster2dymo[lw|lm] (CUPS filter binaries via
                      subprocess) e write a /dev/usb/lpN.
                      Bypassa il backend USB di CUPS. ~istantaneo.
                    - CUPS lp (macOS dev/staging): subprocess `lp` come
                      fallback. Auto-detect: se /dev/usb/lp* è scrivibile
                      → direct, altrimenti lp.

presets_store.py    JSON store ~/.config/dymo-web/preset_overrides.json
                    (writable by user — non /etc/dymo-web come la vecchia
                    settings.py). Per-preset overrides keyed by preset
                    'name': offset_x/y_mm, auto_fit_safety, padding_mm.
                    DEFAULTS definiscono i valori usati senza override.

history.py          Print history ring buffer
                    ~/.config/dymo-web/history.json. Cap HISTORY_MAX=200,
                    FIFO. Ogni entry: full request payload + base64 PNG
                    thumbnail (long side 200 px). De-dup via _fingerprint
                    (json.dumps con sort_keys): stesso payload non
                    accumula doppioni. Hookato da /api/print e
                    /api/history (POST). Failure to add() è swallowed
                    (history non deve bloccare una stampa).

static/index.html   Frontend home (HTML+CSS+JS vanilla, single file).
                    contenteditable per il rich text. Persistenza in
                    localStorage (key 'dymo-web:draft') per ricaricare
                    l'ultima cosa che l'utente stava editando.
                    Sidebar history a destra (8 thumbnails); replay via
                    sessionStorage 'replay_id'. Pallino stato stampante
                    e ingranaggio /presets nell'header pagina (sopra le
                    due colonne).

static/presets.html Pagina /presets: lista preset, click per espandere
                    form di override (offset, safety, padding) con
                    Salva / Ripristina default.

static/history.html Pagina /history: griglia paginata 10/pagina, filtro
                    tipo (label/tape), click su una card → sessionStorage
                    'replay_id' + redirect a / per ricaricare il payload.

etc/dymo-web.service Unit systemd (committata nel repo, full-recovery.sh
                     la copia in /etc/systemd/system/).

scripts/
  full-recovery.sh         One-shot per Pi vergine.
  setup-pi-direct-usb.sh   usblp + udev + gruppo lp + cupsdisable.
  setup-pi-autodeploy.sh   bare repo + post-receive hook + sudoers
                           NOPASSWD per restart. Hook salta il restart
                           quando il commit tocca solo data/.
  setup-cron-backup.sh     Cron user nightly 03:00 → backup-data.sh.
  backup-data.sh           Copia ~/.config/dymo-web/*.json in data/,
                           commit "data: nightly backup …", push github.
  update-deps.sh           apt install + pip install + restart, dopo
                           un cambio in requirements.txt.
  bench-direct.py          Profilazione filter chain (no stampa fisica).

data/                Snapshot di preset_overrides.json + history.json
                     committati dal cron backup. Vive su GitHub →
                     sopravvive a un wipe SD. Ricaricato da
                     full-recovery.sh in ~/.config/dymo-web/.
```

## Lessons learned (gotchas reali)

### Backend USB CUPS è LENTISSIMO sulla DYMO Duo (risolto via direct USB)
Il backend USB di CUPS impiega ~25–27 s a consegnare 5 KB alla DYMO Duo
(stampante anziana, polling bidirezionale lento). I filter `imagetoraster`
e `raster2dymolw` standalone sono velocissimi (~30 ms ciascuno), e una
write diretta a `/dev/usb/lp0` è sub-secondo.

Fix in `printing.py._print_direct()`:
- pipe PNG → imagetoraster → raster2dymo[lw|lm] (subprocess)
- write bytes a /dev/usb/lpN
- code CUPS restano installate ma `cupsdisable`d (servono i loro PPD)
- alexpani in gruppo `lp` per scrivere su /dev/usb/lpN

Risultato: 33 s → istantaneo. Ricontrollare se la pipeline standalone si
rompe dopo update di `printer-driver-dymo` o `cups-filters`.

### `usblp` kernel module DEVE essere caricato (non blacklistato)
Nella prima guida l'avevo blacklistato per evitare "conflitti col driver
DYMO". Era sbagliato: serve proprio `usblp` per esporre `/dev/usb/lpN`.

### Anteprima vs stampa: due percorsi distinti per l'offset meccanico
`offset_x_mm` / `offset_y_mm` compensano disallineamenti fisici.
**Va applicato solo alla stampa**, NON all'anteprima: se applicato anche
all'anteprima, l'utente vede il contenuto traslato e crede sia un bug del
rendering. `app._render_kwargs(data, for_print=False)` azzera gli offset;
`for_print=True` li lascia. Padding e safety invece sono applicati a
entrambi (sono scelte di layout, non compensazioni hardware).

### Duo = due stampanti CUPS distinte
- `DYMO_LabelWriter_DUO_Label` → slot adesive
- `DYMO_LabelWriter_DUO_Tape_128` → slot nastro D1

Il frontend autoseleziona quella giusta in base al `kind` del preset
(regex `/tape/i` vs `/label/i` sul nome). Il dropdown stampante è
nascosto se il sistema rileva 1–2 sole code (caso normale Pi).

### Media custom per Tape: portrait + dimensioni esatte
NON usare `w*h4000` (continuous max ~1411 mm) con `fit-to-page`: il
driver scala il PNG su tutta la lunghezza max e il nastro esce
all'infinito. In `_print_args` (printing.py):
1. Ruota il PNG di 90° (landscape → portrait)
2. `media=Custom.WIDTHxLENGTHmm` con la lunghezza esatta del PNG
3. Niente `-o fit-to-page`

### Media name nel PPD ≠ lpoptions
`lpoptions -p ... -l` non espone tutti i PageSize. Per i nomi reali:
```bash
grep '^\*PageSize ' /etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd
```
La 11354 ha `w162h90`, la 99019 condivide lo stesso media.

### Iconify free API: solo SVG (no PNG endpoint pubblico)
- `https://api.iconify.design/<set>:<name>.png` → 404 (PNG è premium)
- `https://api.iconify.design/<set>:<name>.svg?color=%23000` funziona
- Iconify rifiuta richieste senza User-Agent (HTTP 403). Sempre includere
  `User-Agent: dymo-web/1.0` nelle Request urllib.
- Conversione SVG → PNG via svglib + reportlab (pure Python, ma trascina
  pycairo che richiede cairo system lib: `brew install cairo` su Mac,
  `apt install libcairo2-dev` su Pi — `libcairo2` solo non basta, servono
  gli headers).
- Cache PNG renderizzato a 600 px in `/tmp/dymo-web-icons/`, PIL
  ridimensiona on-demand. Cache miss ~200 ms, hit ~10 ms.

### Filtri Iconify search
Il proxy `/api/icons/search` applica:
- whitelist: solo set in `POPULAR_SETS` (~16 set curati)
- skip se `palette=true` (emoji, flag, color icons)
- skip set animati (blacklist `ANIMATED_SETS`: `line-md`, `svg-spinners`)
- skip se nome contiene `duotone` / `two-tone` / `twotone` / `broken`
- ordine: prima i set in ordine `POPULAR_SETS`, poi gli altri
Limite: 999 (max free Iconify), default frontend 200.

### Font: cross-platform via FONT_FACES
- macOS: `Helvetica.ttc` (1 file, 4 facce per index — Regular/Bold/Oblique/BoldOblique)
- Linux (Pi): `DejaVuSans*.ttf` (4 file separati)
- Mappa `FONT_FACES[(bold, italic)] = (path, index)` in `label_render.py`
  inizializzata in base a `platform.system()`.

### Centering verticale del testo
`_draw_lines` usa `anchor='lt'` (top-left esatto del bbox) e centra
sull'altezza visiva (max bbox per linea), non sull'altezza nominale del
font. Senza questo, il testo senza descender (es. "Cavo HDMI") sembrava
shiftato in basso perché il font lasciava sempre spazio per la 'y'.

### Il post-receive hook salta i commit data:
Il backup notturno commit-pusha solo `data/*.json`, e il service non
viene riavviato perché il diff `oldrev..newrev` è interamente sotto
`data/`. Se modifichi quel filtro e regredisci, ogni notte il service
si riavvia inutilmente.

### Cron user, non root
`scripts/setup-cron-backup.sh` installa nel crontab dell'utente
(`crontab -e`), non in `/etc/cron.d/`. Logfile: `~/.dymo-web-backup.log`.
Se cambi a system cron, ricorda di runnare come `alexpani` (PATH, HOME,
SSH key, git remote).

### CUPS auto-disable dopo un errore
Quando un job fallisce, CUPS può disabilitare la stampante e bloccare
la coda. Sintomo: job "Impossibile inviare i dati". Una volta:
```
cupsenable DYMO_LabelWriter_DUO_Tape_128
lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -o printer-error-policy=retry-current-job
```

### Service Worker stale su localhost:5050
Se l'utente ha mai installato altre app sullo stesso host:port, il SW
intercetta tutto e mostra contenuto vecchio. Sintomo: pagina vuota anche
se curl mostra il PNG corretto. DevTools → Application → SW → Unregister.

### Driver DYMO macOS è x86_64-only
DYMO Connect non supporta la Duo dell'utente; serve DYMO Label v8 (Sept
2020). Su Apple Silicon con Rosetta in dismissione, la pipeline si
romperà. Su Pi (ARM64) usiamo `printer-driver-dymo` open source: nessun
rischio.

## Convenzioni di codice

- Commenti solo dove il **perché** non è ovvio. Niente commenti che
  ripetono cosa fa una riga.
- Identificatori parlanti.
- `requirements.txt` con `>=` minimi (non pinning rigido), eccetto se
  serve un fix specifico.

## Workflow di test

```bash
# Avvio server local (background)
kill $(cat /tmp/dymo_server.pid 2>/dev/null) 2>/dev/null
cd "$HOME/Claude Code/dymo-web" && source .venv/bin/activate && \
  python app.py > /tmp/dymo_server.log 2>&1 &
echo $! > /tmp/dymo_server.pid

# Smoke test API senza stampare fisicamente
curl -s -X POST http://localhost:5050/api/preview \
  -H 'Content-Type: application/json' \
  -d '{"format":1,"runs":[{"text":"Test","bold":true,"italic":false}]}' \
  -o /tmp/preview.png
file /tmp/preview.png

# Stop
kill $(cat /tmp/dymo_server.pid)
```

Per test sul Pi via SSH (read-only):
```bash
ssh alexpani@dymo.local 'systemctl status dymo-web | head -10'
ssh alexpani@dymo.local 'tail -20 ~/.dymo-web-backup.log'
```

## Workflow git

```
edit Mac  →  git push origin main
                      │
       ┌──────────────┴──────────────┐
       ▼                             ▼
   GitHub                  Pi /opt/git/dymo-web.git
                                    │
                          post-receive hook:
                            git pull working-copy
                            systemctl restart (skip se solo data/)
```

`origin` ha 2 push URL: HTTPS GitHub + SSH Pi. Single command pusha a
entrambi. Per un push solo a uno specifico: `git push pi main` o
`git push github main` esistono come remote separati.

## Decisioni out of scope (oggi)

- Stampa multipla / batch
- Immagini caricate dall'utente (oltre alle icone Iconify)
- Barcode (oltre al QR)
- Auth / multi-utente
- LXC/Proxmox + ESP32 (discusse ma scartate)
- Migrazione USB diretta tipo libusb/labelle (non serve, direct USB via
  CUPS filter binaries è già istantaneo)

Quando una di queste serve, l'utente la chiederà esplicitamente.
