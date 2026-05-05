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
printing.py         list_printers() (parsa lpstat italiano e inglese),
                    print_label() (rotazione PNG per tape, media custom esatto,
                    no fit-to-page per tape).
static/index.html   Tutto il frontend in un solo file (HTML+CSS+JS).
                    contenteditable per il rich text, B/I via execCommand.
.claude/launch.json Config per il preview server di Claude Code.
```

## Lessons learned (gotchas reali, non ipotesi)

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
