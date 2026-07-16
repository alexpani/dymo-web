# CLAUDE.md

Context per Claude Code in sessioni future. Leggi questo file prima di
toccare il codice.

## Cos'è

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** (USB).

**Architettura distribuita** in produzione:
- **LXC Debian su Proxmox** (`dymo.local`, IP 192.168.68.159) — l'app
  Flask completa: render, history, presets, frontend, Iconify.
- **Raspberry Pi 4** (`dymopi.local`, IP 192.168.68.141) — thin USB
  gateway: solo `gateway.py` su porta 5051. La DYMO è collegata qui.

LXC → POST PNG/media/kind → Pi gateway → CUPS filter chain → /dev/usb/lpN.
Pipeline ~150 ms.

Frontend HTML/JS vanilla, backend Flask. Repo:
github.com/alexpani/dymo-web. Vedi `README.md` per dettagli utente.

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
                    _tape_length_mm() valida/clampa la lunghezza nastro
                    richiesta; /api/formats espone dead_zone_mm e i
                    min/max ai preset tape, così il frontend non
                    duplica la geometria.

label_render.py     FORMATS (seed dei preset built-in). render() dispatch
                    tra _render_label (size = imageable area) e
                    _render_tape (lunghezza auto-fit, oppure fissa se
                    length_mm: allora length_mm è il nastro TOTALE e si
                    disegna length_mm - TAPE_DEAD_ZONE_MM). orientation=
                    'vertical' lavora su canvas swappato e ruota 90°.
                    _layout() = binary search del font massimo che entra;
                    usa _line_visual_geometry come _draw_lines, così le
                    altezze del bin search e del rendering coincidono.
                    PPD_IMAGEABLE_MARGINS_MM mappa le imageable areas per
                    media DYMO; centring_offset_mm() restituisce lo shift
                    da applicare in stampa per portare il centro logico
                    sul centro fisico della carta. render_calibration()
                    produce il pattern di taratura.
                    _fetch_icon() scarica SVG da Iconify e lo converte
                    in PNG via svglib (cache /tmp/dymo-web-icons/).

presets_catalog.py  Catalogo MUTABILE dei preset, JSON in
                    ~/.config/dymo-web/presets.json. Seedato da
                    label_render.FORMATS al primo accesso. CRUD:
                    add/update/delete con validazione, refusa di
                    svuotare il catalogo. update() ritorna (old_name,
                    new_name) così il chiamante migra le override.

printing.py         Tre path stampa con auto-select (in ordine):
                    1. GATEWAY HTTP (LXC): se env DYMO_GATEWAY_URL è set,
                       POST multipart (kind, media, file=PNG) al Pi
                       microservice. Default in produzione.
                    2. DIRECT USB (Linux/Pi monolitico): pipe imagetoraster
                       + raster2dymo[lw|lm] e write a /dev/usb/lpN.
                       Bypassa il backend USB di CUPS.
                    3. CUPS lp (macOS dev): fallback con subprocess `lp`.

gateway.py          Microservice Flask SOLO sul Pi (porta 5051). Single
                    POST /print endpoint che riceve PNG+kind+media,
                    fa il filter chain CUPS e scrive a /dev/usb/lpN.
                    Dipendenze: Flask + waitress (no Pillow/svglib).

presets_store.py    JSON store ~/.config/dymo-web/preset_overrides.json
                    (writable by user — non /etc/dymo-web come la vecchia
                    settings.py). Per-preset overrides keyed by preset
                    'name': offset_x/y_mm, auto_fit_safety, padding_mm.
                    DEFAULTS definiscono i valori usati senza override.
                    rename(old, new) migra la chiave quando l'utente
                    rinomina un preset dal catalogo.

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

static/presets.html Pagina /presets: bottone "+ Nuovo preset" e, per
                    ciascuno, form a due sezioni: "Caratteristiche
                    preset" (nome/dimensioni/kind/cups_media/codice →
                    POST/PUT/DELETE su /api/presets) e "Aggiustamenti
                    di stampa" (i 4 valori override + bottone "Stampa
                    calibrazione").

static/history.html Pagina /history: griglia paginata 10/pagina, filtro
                    tipo (label/tape), click su una card → sessionStorage
                    'replay_id' + redirect a / per ricaricare il payload.

etc/dymo-web.service Unit systemd (committata nel repo, full-recovery.sh
                     la copia in /etc/systemd/system/).

scripts/
  setup-lxc.sh             Setup LXC: apt deps + venv + pip + systemd
                           unit con DYMO_GATEWAY_URL puntato al Pi.
  setup-pi-gateway.sh      Setup completo del Pi gateway da fresh Pi OS
                           Lite: apt (cups, cups-filters, printer-driver-
                           dymo, python3-venv), venv + Flask/waitress,
                           lpadmin per generare le PPD in /etc/cups/ppd/,
                           setup-pi-direct-usb, drop-in cloud-init
                           preserve_hostname, workaround WiFi NM (vedi
                           lessons), systemd unit, health check.
                           Idempotente, safe to re-run.
  setup-pi-autodeploy.sh   Bare repo + post-receive hook + sudoers
                           NOPASSWD. PARAMETRICO: $1 = nome servizio
                           da restartare (default 'dymo-web', Pi usa
                           'dymo-gateway'). Hook salta restart sui
                           commit che toccano solo data/.
  setup-pi-direct-usb.sh   usblp + udev + gruppo lp + cupsdisable.
                           Usato dal full-recovery.sh storico.
  full-recovery.sh         One-shot per un Pi vergine in modalità
                           monolitica (legacy ma ancora valido).
  setup-cron-backup.sh,
  backup-data.sh           Cron+commit+push, modalità monolitica
                           legacy. Sostituiti dagli snapshot Proxmox
                           nell'architettura distribuita.
  update-deps.sh           apt install + pip install + restart, dopo
                           un cambio in requirements.txt.
  bench-direct.py          Profilazione filter chain (no stampa fisica).

data/                Snapshot legacy dei JSON, riempito dal cron
                     monolitico. Non usato in modalità LXC: lo stato
                     vive in ~/.config/dymo-web/ sulla LXC e viene
                     backuppato tramite snapshot Proxmox.
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

### Anteprima vs stampa: gli offset valgono solo a print time
`offset_x_mm` / `offset_y_mm` (utente) + auto-compensation PPD vanno
applicati SOLO alla stampa, non all'anteprima — altrimenti l'utente vede
il contenuto traslato e crede sia un bug del rendering.
`app._render_kwargs(data, for_print=False)` azzera tutti gli offset;
`for_print=True` somma override utente + `centring_offset_mm(fmt)`.
Padding e safety invece sono applicati a entrambi (sono scelte di layout,
non compensazioni hardware).

### Centraggio fisico = render a imageable size + niente fit-to-page + auto-comp
Tre cose insieme rendono la stampa centrata sull'etichetta fisica:
1. `_render_label` lavora su un canvas dell'**imageable area** (paper
   meno i margini hardware della PPD), non paper-size. Il driver mette
   il bitmap nell'imageable area senza scalare.
2. La pipeline (`printing._print_direct`, `_print_via_lp`, `gateway.py`)
   NON passa `fit-to-page`: qualsiasi scaling re-introduce asimmetria.
3. `_render_kwargs` somma `centring_offset_mm(fmt) = ((L-R)/2, (T-B)/2)`
   agli offset utente quando `for_print=True`. Per la 11354 è (0,0)
   perché simmetrica; per 99012/99010/99014/99019/11355 il margine
   "top" della PPD è ~5–6 mm contro 1.5 mm sotto, e l'auto-comp spinge
   il contenuto giù di ~2 mm per centrarlo fisicamente.

I valori sono in `PPD_IMAGEABLE_MARGINS_MM` (label_render.py), letti
da `/etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd` sul Pi. Per preset
custom (cups_media `Custom.WxHmm`) il default è (1.0, 1.5, 1.0, 1.5).
Pattern di calibrazione stampabile da `/presets` per fine-tuning manuale
dell'override utente.

### Il nastro D1 si mangia 21.17 mm fissi, e la PPD lo nega sui custom
La testina di stampa sta ~10.6 mm a monte della taglierina: ogni etichetta
tagliata ha quindi un tratto bianco in testa (nastro già passato davanti
alla testina) e uno in coda (avanzamento per portare la fine dello stampato
sotto la lama). Sono **30 punti per lato = 21.17 mm totali**, simmetrici
(verificato col righello).

La PPD del nastro lo dichiara per i media a nome — `*ImageableArea w26h252:
"2.80 30.00 22.80 222.00"` su una `*PaperDimension` di 252 pt, cioè 30 pt
tagliati sotto e 30 sopra — ma per i formati custom dichiara
`*HWMargins: 0 0 0 0`, che **è falso**: il meccanismo consuma il nastro
comunque. Siccome `_print_args` costruisce `Custom.WxLmm`, la nostra
pipeline cadeva esattamente in quella bugia: chiedendo 40 mm ne uscivano 60.

Perciò `render(length_mm=...)` interpreta il valore come **nastro totale
misurato col righello** e `_render_tape` disegna `length_mm -
TAPE_DEAD_ZONE_MM`. Minimo accettato 31.2 mm (zona morta + 10 mm di
stampabile). Testato su 40/50/60/70 mm: precisi a ±1 mm.

Il bianco è simmetrico, quindi il centro dello stampato coincide col centro
dell'etichetta tagliata: **non serve nessun offset di compensazione**. Se un
giorno risultasse asimmetrico, quello sì andrebbe compensato.

Diagnostica utile (non stampa niente): far girare `imagetoraster` sul Pi con
`media=Custom.9x40mm` stampa `DEBUG: Page = 26x113; 0,0 to 26,113` — 113 pt
= 39.9 mm interamente "stampabile" secondo CUPS. Cioè: il PNG e il raster
sono giusti, l'errore sta a valle nel meccanismo.

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

### Centering verticale del testo: glyph extents reali, non i metric
`_layout` (bin search) e `_draw_lines` usano lo stesso helper
`_line_visual_geometry`, che misura ascent+descent **dei glifi
effettivamente presenti** nella line — non `font.getmetrics()` che è
l'ascent della font (riserva spazio per accenti/lettere alte assenti).
Senza questa coerenza, "TEST" tutto-maiuscolo finiva in basso (il bin
search prenotava spazio per i descender mai disegnati). Conversione
chiave: PIL `getbbox(text)` è anchor='la' (left, ascender top), per
portarlo in baseline-relative serve sottrarre `font.getmetrics()[0]`.

### Il post-receive hook salta i commit data:
Il backup notturno commit-pusha solo `data/*.json`, e il service non
viene riavviato perché il diff `oldrev..newrev` è interamente sotto
`data/`. Se modifichi quel filtro e regredisci, ogni notte il service
si riavvia inutilmente.

### Cron user, non root (modalità legacy)
`scripts/setup-cron-backup.sh` installa nel crontab utente, non in
`/etc/cron.d/`. Nell'architettura distribuita LXC+Pi questo NON è
attivo: i backup li fa Proxmox a livello container. Lo script resta
nel repo per chi avesse bisogno della modalità Pi monolitica.

### Pi OS Trixie: WiFi seed non arriva mai a NetworkManager
Su Pi OS Lite (Bookworm/Trixie) installato con Pi Imager, cloud-init
gira in stato `degraded done` con il warning "Could not find module
named cc_netplan_nm_patch": il modulo che dovrebbe propagare
`/boot/firmware/network-config` dentro NetworkManager **non esiste**
nella distribuzione. Risultato: WiFi funziona al primo boot, sparisce
ai successivi, `wlan0` resta DOWN, `/etc/NetworkManager/system-
connections/` non riceve mai il profilo. Workaround in
`setup-pi-gateway.sh`: legge SSID + PSK dal seed e crea direttamente
un profilo NM persistente. Niente fix di cloud-init — bypass.

### cloud-init di Pi Imager riapplica `hostname` ad ogni boot
`hostnamectl set-hostname dymopi` non sopravvive al reboot: cloud-init
rilegge `hostname: dymo` da `/boot/firmware/user-data` ogni boot. Fix:
drop-in `/etc/cloud/cloud.cfg.d/99-preserve-hostname.cfg` con
`preserve_hostname: true`. Non tocca la rete (testato: `wlan0` resta
attiva). Già incluso in `setup-pi-gateway.sh`.

### Gateway pattern
La LXC produce il PNG (con offset/safety/padding già applicati per la
stampa via `for_print=True`), poi `_print_via_gateway()` costruisce a
mano un payload multipart (no `requests` dep, solo urllib stdlib),
POST a `$DYMO_GATEWAY_URL/print`. Il Pi gateway fa il filter chain e
scrive a `/dev/usb/lpN`. Vedi `printing.py:_print_via_gateway` e
`gateway.py`.

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
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    GitHub      Pi bare       LXC bare
                 │                │
       hook restart        hook restart
       dymo-gateway         dymo-web
       (Pi 5051)            (LXC 5050)
```

`origin` ha 3 push URL: HTTPS GitHub + SSH Pi (`alexpani@dymopi.local:/opt/git/...`)
+ SSH LXC (`alexpani@dymo.local:/opt/git/...`). Un singolo `git push origin
main` aggiorna tutti e tre. I due hook sono identici (parametrici sul nome
del servizio) e saltano il restart sui commit `data:` (legacy).

## Decisioni out of scope (oggi)

- Stampa multipla / batch
- Immagini caricate dall'utente (oltre alle icone Iconify)
- Barcode (oltre al QR)
- Auth / multi-utente
- ESP32 (discusso e scartato — driver USB Printer Class custom troppo
  costoso per il guadagno; il Pi 4 fa già lo stesso lavoro con codice
  Python ben mantenuto)
- libusb/labelle/SDK DYMO (non serve, gateway pattern via CUPS filter
  binaries è già istantaneo)

Quando una di queste serve, l'utente la chiederà esplicitamente.
