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

Per il momento funziona; quando si romperà bisognerà passare alla comunicazione
USB diretta (libusb / pyusb / `labelle`). Vedi `CLAUDE.md` per le opzioni.

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
