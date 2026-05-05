# CLAUDE.md

Context per Claude Code in sessioni future. Leggi questo file per orientarti
prima di toccare il codice.

## Cos'è

Web app personale per stampare su una **DYMO LabelWriter Duo** (USB, Mac).
Server Flask locale + frontend HTML/JS vanilla. Vedi `README.md` per le
istruzioni utente.

## Vincoli di scope (non violarli senza consenso)

- **Niente framework frontend**, niente build step, niente npm. Tutto vanilla
  in `static/index.html`.
- **Niente SDK DYMO, niente pyusb, niente labelle.** La stampa va via `lp`
  CUPS — vedi sezione "Dipendenza driver" sotto.
- **Niente persistenza**: no DB, no file di stato, no localStorage per dati
  utente. Ogni sessione è stateless.
- **Backend**: Python 3.12 + Flask + waitress. Niente FastAPI, niente async.
- **File pochi e leggibili.** Non aggiungere astrazioni "per il futuro".
  L'utente è tecnico ma non sviluppatore esperto: privilegia chiarezza.

## Architettura

```
app.py              Flask routes (/, /api/formats, /api/printers,
                    /api/preview, /api/print) + waitress runner.
                    _render_kwargs() centralizza il parsing del payload.
label_render.py     FORMATS (preset), render() che dispatch tra
                    _render_label() (dimensioni fisse) e _render_tape()
                    (lunghezza auto-fit), helpers per font, layout multi-run,
                    word-wrap.
printing.py         Due path stampa con auto-select:
                    - DIRECT USB (Linux/Pi): pipe imagetoraster + raster2dymo[lw|lm]
                      (CUPS filter binaries via subprocess) e write a /dev/usb/lpN.
                      Salta il backend USB di CUPS. ~istantaneo.
                    - CUPS lp (macOS dev/staging): subprocess `lp` come fallback.
                    list_printers() advertise i 2 device direct in modalità Linux
                    o parsa lpstat (Mac).
presets_store.py    JSON store ~/.config/dymo-web/preset_overrides.json (writable
                    by the running user — was the bug of the old settings.py
                    that wrote to /etc/dymo-web). Per-preset overrides keyed by
                    preset 'name': offset_x/y_mm, auto_fit_safety, padding_mm.
                    DEFAULTS define the values used when no override exists.
                    Server-side authoritative: app._render_kwargs() applies
                    overrides automatically; clients never pass them.
history.py          Print history ring buffer (~/.config/dymo-web/history.json).
                    Cap HISTORY_MAX=200, FIFO. Each entry stores the full
                    request payload + a base64 PNG thumbnail (long side
                    scaled to THUMB_LONG_SIDE=200 px). Hooked from /api/print
                    on success only; failure to add() is swallowed (history
                    must never block a print).
static/presets.html Pagina /presets: lista preset, click per espandere form
                    di override (offset, safety, padding) con Salva/Reset.
static/history.html Pagina /history: griglia paginata 10/pagina, filtro
                    tipo (label/tape), click su una card → sessionStorage
                    'replay_id' + redirect a / per ricaricare il payload.
scripts/update-deps.sh  Aggiorna pacchetti Pi quando cambiano le dependencies
                        (apt install libcairo2 + pip install -r requirements.txt
                        + restart). Da lanciare a mano dopo che le deps cambiano.
static/index.html   Tutto il frontend in un solo file (HTML+CSS+JS).
                    contenteditable per il rich text, B/I via execCommand.
.claude/launch.json Config per il preview server di Claude Code.
```

## Lessons learned (gotchas reali, non ipotesi)

### Backend CUPS USB della DYMO Duo è LENTISSIMO (risolto via direct USB)
Il backend USB di CUPS impiega ~25-27 secondi a consegnare 5KB alla DYMO Duo
(stampante anziana, polling bidirezionale lento). I filter `imagetoraster` e
`raster2dymolw` standalone sono velocissimi (~30ms ciascuno), e una write
diretta a `/dev/usb/lp0` è sub-secondo.

Fix adottato in `printing.py._print_direct()`:
- pipe PNG → imagetoraster (subprocess) → raster2dymo[lw|lm] (subprocess)
- write bytes risultanti direttamente a `/dev/usb/lp0` (label) o `/dev/usb/lp1` (tape)
- CUPS code stampa restano installate ma `cupsdisable`d (servono i loro PPD)
- Alexpani in gruppo `lp` per scrivere su `/dev/usb/lpN`
- Setup tutto in `scripts/setup-pi-direct-usb.sh`

Risultato: 33s → istantaneo. Ricontrollare se la pipeline standalone si
rompe dopo update di `printer-driver-dymo` o `cups-filters`.

### `usblp` kernel module DEVE essere caricato (non blacklistato)
Storia: nella prima versione della guida l'avevo blacklistato per evitare
"conflitti col driver DYMO". Era sbagliato — serve proprio `usblp` per
esporre `/dev/usb/lpN`. La via direct USB richiede `usblp` attivo.

### Driver DYMO è x86_64-only su macOS (problema risolto via Pi)
- `/Library/Printers/DYMO/Filters/UsbPrinterClassDriver.bundle` può sparire
  dopo update macOS. Reinstall DYMO Label v8 lo ripristina.
- DYMO Connect for Desktop NON supporta la LabelWriter Duo dell'utente. Solo
  DYMO Label v8 (Sep 2020, x86_64).
- **Soluzione adottata**: deploy permanente su **Raspberry Pi 4** (ARM64,
  Raspberry Pi OS Lite). Driver DYMO open source via `printer-driver-dymo`,
  niente più dipendenze Intel. Mac diventa solo client. Vedi sezione "Setup
  su Raspberry Pi" in README.md.
- Su Mac il setup originale rimane valido come dev/staging; il codice è
  cross-platform via `FONT_FACES` in `label_render.py`.

### CUPS auto-disable
Quando un job fallisce, CUPS **disabilita la stampante** e blocca la coda.
Sintomo: job in coda forever, "Impossibile inviare i dati". Fix:

```bash
cupsenable DYMO_LabelWriter_DUO_Tape_128
lpadmin -p DYMO_LabelWriter_DUO_Tape_128 -o printer-error-policy=retry-current-job
```

Il secondo comando è già stato applicato sul Mac dell'utente (persistente).

### Anteprima vs stampa: due percorsi distinti per l'offset meccanico
`presets_store` espone `offset_x_mm` / `offset_y_mm` per compensare
disallineamenti fisici della stampante (es. la 11354 esce 1mm a sinistra).
**Va applicato solo alla stampa**, NON all'anteprima: se applicato anche
all'anteprima, l'utente vede il contenuto traslato e crede sia un bug
del rendering. `app._render_kwargs(data, for_print=False)` azzera gli
offset; `for_print=True` li lascia. `/api/preview` usa False, `/api/print`
usa True.

Padding e auto-fit safety invece sono applicati a entrambi (sono scelte
di layout, non compensazioni hardware).

### Duo = due stampanti CUPS distinte
La LabelWriter Duo si presenta a CUPS come **due code separate**:
- `DYMO_LabelWriter_DUO_Label` → slot etichette adesive
- `DYMO_LabelWriter_DUO_Tape_128` → slot nastro D1

Non confonderle mai. Il frontend autoseleziona quella giusta in base al
`kind` del preset (regex `/tape/i` vs `/label/i` sul nome).

### Media custom per Tape: portrait + dimensioni esatte
Per il nastro NON usare `w*h4000` (continuous max ~1411mm) con `fit-to-page`:
il driver scala il PNG su tutta la lunghezza max e il nastro esce all'infinito.

Strategia che funziona (vedi `_print_args` in `printing.py`):
1. Ruota il PNG di 90° (landscape → portrait)
2. Calcola `media=Custom.WIDTHxLENGTHmm` con la lunghezza esatta del PNG
3. Niente `-o fit-to-page`

### Media name 11354 non in lpoptions ma sì nel PPD
`lpoptions -p ... -l` non espone tutti i PageSize. Per i nomi reali:

```bash
grep '^\*PageSize ' /etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd
```

Es. la 11354 ha `w162h90` nel PPD ma non in lpoptions.

### parser lpstat in italiano
Su macOS italiano `lpstat -p` ritorna "la stampante NAME è in attesa..." invece
di "printer NAME is...". `printing.list_printers()` gestisce entrambi i casi.

### Service Worker stale su localhost:5050
Se l'utente ha mai installato altre app su `localhost:5050` (l'utente aveva
"Labelle Web"), il SW intercetta tutto e mostra contenuto vecchio. Sintomo:
"pagina vuota" o app sbagliata anche se il server Flask risponde corretto a
curl. Fix: unregister SW + clear cache da DevTools.

### Iconify free API: solo SVG (no PNG endpoint pubblico)
- `https://api.iconify.design/<set>:<name>.png` ritorna 404 (PNG è premium)
- `https://api.iconify.design/<set>:<name>.svg?color=%23000` funziona
- Iconify rifiuta richieste senza User-Agent (HTTP 403). Sempre includere
  `User-Agent: dymo-web/1.0` nelle Request urllib
- Conversione SVG → PNG via svglib + reportlab (pure Python, ma trascina
  pycairo che richiede cairo system lib: `brew install cairo` su Mac,
  `apt install libcairo2` su Pi)
- Cache PNG renderizzato a 600px in /tmp/dymo-web-icons/, PIL ridimensiona
  on-demand. Cache miss = ~200ms, cache hit = ~10ms

### Font: cross-platform via FONT_FACES
- macOS: `Helvetica.ttc` (1 file, 4 facce per index — Regular/Bold/Oblique/BoldOblique)
- Linux (Pi): `DejaVuSans*.ttf` (4 file separati)
- Mappa `FONT_FACES[(bold, italic)] = (path, index)` in `label_render.py`
  inizializzata in base a `platform.system()`. `_load_font()` legge da lì
  con fallback a Regular se la chiave manca.
- Per cambiare font su una piattaforma, modifica solo quella sezione.

## Convenzioni di codice

- Commenti solo dove il **perché** non è ovvio. Niente commenti che spiegano
  cosa fa una riga.
- Identificatori parlanti, niente abbreviazioni criptiche.
- Niente "preparato per l'estensione futura". Tre righe simili sono meglio di
  un'astrazione prematura.
- Backward compat solo dove serve davvero (es. `_render_kwargs` accetta sia
  `runs` che il legacy `text+bold+italic` per script curl).

## Workflow tipico

```bash
# Avvio server (in background per testing)
kill $(cat /tmp/dymo_server.pid 2>/dev/null) 2>/dev/null
cd "$HOME/Claude Code/dymo-web" && source .venv/bin/activate && \
  python app.py > /tmp/dymo_server.log 2>&1 &
echo $! > /tmp/dymo_server.pid

# Smoke test API senza stampare
curl -s -X POST http://localhost:5050/api/preview \
  -H "Content-Type: application/json" \
  -d '{"format":0,"runs":[{"text":"Test","bold":true,"italic":false}]}' \
  -o /tmp/preview.png

# Verifica anteprima nel browser
# (preview tab già configurato in .claude/launch.json)
```

**Mai** mandare un job fisico (`/api/print` o `lp`) senza autorizzazione
esplicita dell'utente — consuma materiale.

## Decisioni out of scope (per ora)

- Salvataggio template / storico
- Stampa multipla / batch
- Immagini caricate dall'utente
- Barcode (solo QR)
- Auth / utenti
- Service launchd per avvio automatico
- Migrazione USB diretta (vedi sezione driver sopra)

Quando una di queste serve, l'utente la chiederà esplicitamente.
