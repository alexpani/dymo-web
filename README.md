# DYMO Label Web App

Web app personale per stampare etichette su una **DYMO LabelWriter** collegata via USB
al Mac. Server Flask + frontend HTML/JS vanilla, stampa via CUPS (`lp`).

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

| Preset                       | Codice | Media CUPS              |
| ---------------------------- | ------ | ----------------------- |
| 89 × 36 mm Address           | 99012  | `w101h252`              |
| 89 × 28 mm Address Small     | 99010  | `w81h252`               |
| 57 × 32 mm Multipurpose      | 11354  | `w162h90`               |
| 32 × 57 mm Multipurpose vert | 11354  | `w162h90`               |
| Nastro 9 mm  (auto-fit)      | D1-9   | `Custom.9xLENGTHmm`     |
| Nastro 12 mm (auto-fit)      | D1-12  | `Custom.12xLENGTHmm`    |
| Nastro 19 mm (auto-fit)      | D1-19  | `Custom.19xLENGTHmm`    |
| Nastro 24 mm (auto-fit)      | D1-24  | `Custom.24xLENGTHmm`    |

I preset Tape (`kind: 'tape'`) hanno **lunghezza variabile**: il PNG viene
ruotato in portrait e la lunghezza è calcolata dal contenuto. La stampante
Tape viene autoselezionata quando scegli un preset Nastro.

Per aggiungere un preset: edita la lista `FORMATS` in `label_render.py`. Il campo
`cups_media` deve essere uno dei nomi esposti da:

```bash
lpoptions -p DYMO_LabelWriter_DUO_Label -l   # cerca "PageSize"
```

Se la dimensione non è nel listato, puoi mettere `cups_media: None` e il backend
userà `Custom.WxHmm` come fallback (può funzionare o no a seconda del driver).

## Troubleshooting

### La stampante non appare in `lpstat -p`

- Verifica che la DYMO sia collegata: `system_profiler SPUSBDataType | grep -i dymo`
- Aggiungila in *Impostazioni di Sistema → Stampanti e Scanner → +*
- La LabelWriter Duo appare come **due** code: `..._Label` (etichette adesive)
  e `..._Tape` (nastro D1). Servono entrambe se vuoi usare entrambi gli slot;
  questa app usa solo `_Label`.

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

Il secondo comando configura CUPS a riprovare invece di disabilitare la
stampante al primo errore (persistente in `/etc/cups/printers.conf`).

## Stack

- **Backend**: Python 3.12 + Flask + waitress
- **Stampa**: subprocess su `lp` di CUPS
- **Rendering**: Pillow (300 DPI), `qrcode[pil]`
- **Frontend**: HTML + CSS + JS vanilla in `static/index.html`, no framework, no build

Nessuna persistenza, nessun DB, nessuno stato.
