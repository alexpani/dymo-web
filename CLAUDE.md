# CLAUDE.md

Context per Claude Code in sessioni future. Leggi questo file prima di
toccare il codice.

## Cos'è

Web app personale per stampare etichette su una **DYMO LabelWriter Duo** (USB).

**Architettura distribuita** in produzione:
- **LXC Debian su Proxmox** (`dymo.local`, IP 192.168.68.159) — l'app
  Flask completa: render, history, presets, frontend, Iconify.
- **Raspberry Pi 4** (`dymopi.local`, IP 192.168.100.112) — thin USB
  gateway: solo `gateway.py` su porta 5051. La DYMO è collegata qui.

Le due macchine stanno su **subnet diverse**: la LXC sulla rete principale
(192.168.68.0/24), il Pi sulla VLAN IoT (192.168.100.0/24, gateway
192.168.100.1). Il router instrada tra le due in entrambe le direzioni, e
la porta 5051 passa. L'IP del Pi è fissato da una DHCP reservation sul
router per il MAC di `wlan0` (`E4:5F:01:B3:17:FC` — attenzione, `eth0` è
`...FB`, differiscono per l'ultima cifra).

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
                    /api/preview usa False, /api/print usa True, e torna
                    in X-Font-Size-Pt il corpo che il render ha usato.
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
                    pt_to_px() converte i punti del cursore in pixel PIL
                    e px_to_pt() torna indietro; render(report={}) riempie
                    il dict col corpo usato, per l'editor in auto-fit;
                    printable_height_mm() dà l'altezza su cui si può
                    scrivere (nastro meno il registro, o lato corto
                    dell'imageable area); max_font_pt() ne ricava il corpo
                    massimo (esposto da /api/formats).
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
                    rinomina un preset dal catalogo. Il padding NON sta
                    più qui: è un cursore dell'editor, memorizzato per
                    formato in localStorage.

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

### I "pt" del cursore non sono pixel: PIL misura il font in pixel
`ImageFont.truetype(path, size)` vuole `size` in **pixel**, e il canvas gira a
300 DPI. Il valore del cursore ci finiva dentro tale e quale, quindi un "20 pt"
veniva disegnato a 20 px = 1,69 mm di corpo invece di 7,06 mm: 300/72 = 4,17×
più piccolo di quello che fa una LabelManager 160 con lo stesso numero.
Verificato col righello su quattro nastri, due per macchina, a 8 e 20.

Fix: `pt_to_px()` in label_render.py, usata nel ramo a dimensione forzata di
`_layout`. L'auto-fit NON la usa — la sua binary search lavora già in pixel
(8..400 px) ed è rimasta identica byte per byte (verificato su 33 combinazioni
preset × opzioni).

Corollario: il cursore non può più arrivare dove gli pare, o il testo uscirebbe
dall'area stampabile senza dirlo. `max_font_pt(fmt)` calcola il massimo sul
`LINE_INK_EM = 0.96`, cioè maiuscola + discendente, non sulla sola altezza
delle maiuscole: così non è una `g` a farsi tagliare. Il padding NON viene
sottratto — è una preferenza di layout, e un blocco troppo alto ci sborda
dentro, mentre l'area stampabile è fisica. /api/formats lo espone per ogni
preset e `syncFontSizeUI()` ci limita lo slider: nastro 9 mm → 23 pt,
11354 57×32 → 85 pt.

Verificato preset per preset: al massimo il testo con discendenti sta dentro,
a massimo+1 viene tagliato. Sulla LabelManager 160 il "20" su nastro da 9 mm
dà maiuscole da 4,26 mm contro i 5,21 mm nostri, ma non è un errore di scala:
il rapporto 20/8 da noi è 2,45 (atteso 2,50), da lei 2,10. Cioè la
LabelManager a 20 tronca alla misura massima che il nastro regge, in silenzio.
A 8 pt, dove nessuna delle due è al limite, le due macchine coincidono entro
il 5% — ed è il DejaVu della LXC che disegna le maiuscole l'1,8% più alte di
Arial, più l'allargamento dell'inchiostro termico.

### Sui media custom la testina copre tutto il nastro (ma il registro balla)
La PPD del nastro dichiara una ImageableArea più stretta per i media **a
nome** — `*ImageableArea w26h4000: "2.80 30.00 22.80 3970.00"` su una pagina
da 25.60 pt, cioè 7,06 mm su un nastro da 9 — e per i `Custom.WxLmm` dichiara
`*HWMargins: 0 0 0 0`. Lungo la **lunghezza** quella dichiarazione è falsa, ed
è la zona morta. Attraverso la **larghezza** è vera: stampato il pattern di
calibrazione, la cornice disegnata sul bordo esatto della tela è uscita a
0,33 mm dal bordo del nastro. Non generalizzare la bugia da un asse all'altro:
l'ho fatto, e il commit che ne è uscito restringeva il testo a 7,06 mm per
niente (060c177, corretto subito dopo).

Quello che balla è il **registro**: la stessa stampa è finita 0,29 mm oltre il
bordo opposto, cioè il bitmap sta ~0,3 mm fuori centro attraverso il nastro.
`TAPE_REGISTRATION_MM = 0.5` tiene mezzo millimetro per lato, che lo assorbe;
un preset che ha bisogno di più ha `offset_y_mm` (19 e 24 mm stanno a −2,5
e −3).

Per misurarlo: stampa la calibrazione del preset nastro. La cornice sta sul
bordo esatto della tela, quindi un lato lungo che esce monco è il bitmap che
scappa da quella parte, e quanto manca va in `offset_y_mm`.

Il metodo di misura buono, su foto, non tocca mai il bordo del nastro — che è
bianco su bianco e si stima male. Due riferimenti stanno già dentro la stampa:
le **due verticali della cornice distano 60 mm esatti** (danno la scala in
px/mm) e la **crocetta sta al centro esatto della tela** (dà come si spartisce
la perdita fra i due lati). Da lì: quanto è alto l'inchiostro stampato contro
l'altezza della tela = quanto si è perso; distanza crocetta-inchiostro sopra
contro sotto = da che parte. Misurato così su due cassette:

| nastro | tela | stampato | perso | sopra | sotto |
|--------|------|----------|-------|-------|-------|
|  9 mm  | 9,00 |   8,84   | 0,16  | 0,29  | ~0    |
| 12 mm  | 12,00|  11,54   | 0,46  | 0,30  | 0,16  |

Circa **0,3 mm in alto su entrambe**, cioè uno scarto di registro costante e
non proporzionale alla larghezza: è la stampante, non la cassetta. Il mezzo
millimetro di `TAPE_REGISTRATION_MM` lo copre su tutt'e due, e il 12 mm non ha
bisogno di nessun `offset_y_mm`. Conferma anche, con un metodo che non dipende
da stime a occhio, che la testina copre tutta la larghezza.

### Misurare la stampa su sé stessa non dice dove sta sul nastro
Errore mio, da non rifare. Sul 24 mm, che ha `offset_y_mm: -3`, avevo concluso
che quell'offset fosse inutile: avevo misurato l'inchiostro stampato contro le
**verticali della cornice** e contro il PNG spedito, trovandoli coerenti entro
0,3 mm, e ne avevo dedotto "la stampante riproduce fedelmente, quindi l'offset
sposta fuori centro una stampa già centrata". L'utente ha guardato il nastro e
ha detto il contrario: con −3 era centrato, azzerandolo è finito in basso.

Il ragionamento era sbagliato alla radice. Misurare la stampa contro i propri
riferimenti interni dimostra solo che **non c'è scalatura né ritaglio**: dice
che il bitmap è riprodotto fedele, non *dove* finisce sul nastro. La posizione
si giudica solo contro i **bordi del nastro** — che è la misura che avevo
scartato perché bianco-su-bianco in foto si stima male. Scartata la misura
difficile, avevo risposto a una domanda più facile facendo finta che fosse la
stessa.

Quindi: i 2,96 mm di bianco che il PNG ha in fondo **servono**, perché il
meccanismo del 24 mm spinge il contenuto verso il basso di quei 3 mm. Gli
offset di 19 e 24 mm sono tarature vere e vanno lasciate stare.

Per giudicare il centraggio servono i bordi del nastro: a occhio sul nastro
vero funziona benissimo, in foto bisogna avere il nastro piatto, ben
illuminato e su uno sfondo che contrasti — oppure chiedere a chi ce l'ha in
mano.

Resta valido dal tentativo sbagliato, e vale la pena tenerlo:
- `max_font_pt()` misura su `LINE_INK_EM = 0.96` (maiuscola + discendente) e
  sulla sola area stampabile, padding escluso.
- `_draw_lines` sborda **simmetrico** quando il blocco non ci sta: prima
  `max(0, ...)` lo faceva colare tutto in basso, cioè tutto da un lato solo.

### Il cursore in Auto è un display, non un valore
Richiesta dell'utente: in auto-fit il cursore deve mostrare la misura scelta.
Il tranello è che spostarci il cursore e basta spegnerebbe l'auto-fit al
primo carattere digitato. Quindi `state.autoFont` separa le due cose: il
cursore sta sulla misura che il server ha scelto, ma `getPayload()` continua
a mandare `font_size_pt: null` finché quel flag è vero. Si prende il comando
muovendo il cursore (parte da lì, non da zero), si torna in Auto col tasto o
portandolo a 0. L'etichetta dice "Auto · 23 pt" contro "23 pt".

Il valore arriva dall'header `X-Font-Size-Pt` di `/api/preview`: il body è un
PNG, quindi non c'era un JSON dove metterlo. `render(report={})` riempie il
dict in `_render_label` / `_render_tape` subito dopo `_layout` — niente
secondo giro di layout, e nessun duplicato della geometria della scatola di
testo, che nei due rami è diversa.

Due dettagli: il flag si rilegge **dopo** l'await della fetch, così
un'anteprima già in volo non sovrascrive un cursore che l'utente ha appena
mosso; e il draft in localStorage salva 0, non la misura parcheggiata, o al
reload l'auto-fit si ritroverebbe spento. L'andata e ritorno auto → pt →
forzato costa al massimo 0,17 mm di arrotondamento al punto intero.

### Il padding è una scelta di composizione, non una taratura
Stava fra gli override di preset accanto a `offset_x/y_mm`, ma quei due
compensano un disallineamento meccanico della stampante — appartengono al
pezzo di hardware — mentre il padding è come l'allineamento o l'interlinea:
cambia da stampa a stampa. Ora il cursore "Margine" sta nell'editor, il
payload porta `padding_mm` e `_render_kwargs` lo prende da lì, con
`label_render.DEFAULT_PADDING_MM` come fallback per i client vecchi e i
curl. Gli offset restano invece server-authoritative: un client non deve
poterci dissuadere.

Perché non un default globale e basta: su un nastro da 9 mm il valore giusto
è 0 e sulla 57×32 è 2, quindi un unico default costringerebbe a riazzerarlo a
ogni cambio formato. L'editor ricorda **l'ultimo margine per nome di preset**
in `localStorage['dymo-web:padding']`. Il nome, non l'indice, che cambia se
riordini il catalogo.

`max_padding_mm(fmt)` limita la corsa del cursore a un terzo dell'altezza
stampabile (9 mm → 2,5; 57×32 → 9,5): oltre, l'aria è più del testo e i tre
quarti della corsa sarebbero inutili.

Una chiave `padding_mm` rimasta in un `preset_overrides.json` vecchio è
inerte — `presets_store.get()` filtra su `DEFAULTS` — ma resta scritta nel
file finché quel preset non viene risalvato. Non è un problema, è solo
rumore: non rimetterla in DEFAULTS pensando che serva.

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

### Cambiare la WiFi del Pi = `nmcli`, non il seed
Corollario del punto sopra: dato che cloud-init non propaga mai
`/boot/firmware/network-config`, quel file è **inerte** e modificarlo non
cambia la rete. La WiFi vive solo nei profili NetworkManager. Per cambiarla:

```bash
ssh -t alexpani@dymopi.local 'sudo nmcli device wifi rescan && sleep 5 && \
  sudo nmcli device wifi connect "SSID" password "PSK"'
```

Il seed va comunque tenuto in pari con le credenziali vere: non serve al
boot, ma `setup-pi-gateway.sh` lo legge e su un Pi riflashato ricreerebbe
il profilo della rete vecchia.

Tre trappole, tutte incontrate davvero:
- `ssh` senza `-t` fallisce con "a terminal is required to read the
  password": `sudo` non ha TTY. Il sudoers del Pi ha NOPASSWD **solo** per
  `systemctl restart dymo-gateway` (lo mette `setup-pi-autodeploy.sh`).
- `Connection to dymopi.local closed.` è la riga che `ssh -t` stampa a ogni
  uscita normale. Non è un errore e non significa che il comando è
  fallito — verifica con `nmcli connection show`, non con quella riga.
- Se il Pi non ha ethernet attaccata la WiFi è l'unica via d'accesso.
  Aggiungi il profilo con `connection.autoconnect no`, attivalo a mano,
  verifica, e solo dopo metti `autoconnect yes`: se qualcosa va storto un
  power-cycle riporta il Pi sul profilo precedente. Con il cavo attaccato,
  invece, `dymopi.local` risolve a **entrambi** gli IP e un test positivo
  può passare dall'ethernet: per un test onesto usa l'IP di `wlan0`, o
  stacca il cavo.

### La cache di scansione NM fa sembrare inesistente una rete che c'è
`nmcli device wifi list` restituisce la **lista in cache**, e mentre è già
connesso il `brcmfmac` del Pi non rifà scansioni aggressive. Sintomo:
`Error: No network with SSID 'X' found.` per una rete perfettamente
visibile a ogni altro dispositivo nella stessa stanza. Sempre rescansionare
prima di concludere che una rete non c'è:

```bash
sudo nmcli device wifi rescan && sleep 6 && nmcli -f SSID,CHAN,SIGNAL device wifi list
```

Nota: la rescan richiede sudo (senza, polkit risponde `not authorized`) ma
la `list` no — quindi una `list` non privilegiata "funziona" restituendo
dati vecchi, che è il modo peggiore di fallire. Il regdomain del Pi è
correttamente `IT` (`cat /sys/module/cfg80211/parameters/ieee80211_regdom`),
quindi i canali 12–13 non sono la spiegazione. `iw` e `rfkill` **non** sono
installati: per diagnosi WiFi serie, `sudo apt install iw` prima.

### `dymopi.local` sulla LXC lo risolve `/etc/hosts`, non mDNS
Il `nsswitch.conf` della LXC è `hosts: files mdns4_minimal
[NOTFOUND=return] dns`, e in `/etc/hosts` c'è una riga statica:

```
192.168.100.112 dymopi.local dymopi
```

`files` viene prima, quindi quella riga vince su tutto. **Se l'IP del Pi
cambia va aggiornata a mano**, altrimenti il `DYMO_GATEWAY_URL` della LXC
(`http://dymopi.local:5051`) punta nel vuoto e `/api/printers` torna `[]`
con la stampa silenziosamente morta. Nessun restart del servizio: glibc
rilegge `/etc/hosts` a ogni risoluzione.

Non tentare di risolverlo con un record sul DNS locale (192.168.68.53, che
è il resolver servito anche alla VLAN IoT): `[NOTFOUND=return]` dopo
`mdns4_minimal` interrompe la catena, quindi una query per un nome `.local`
non arriva **mai** al DNS server.

L'mDNS invece attraversa le due subnet (il router fa reflection: verificato
dal Mac, che risolve `dymopi.local` → 192.168.100.112), ma sulla LXC non
entra mai in gioco perché `files` viene prima di `mdns4_minimal`. Se un
giorno volessi togliere la riga statica, prima verifica che avahi sulla LXC
risolva davvero il nome — `avahi-utils` non è installato lì e la cosa non è
testata.

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
