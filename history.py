"""
Print history: a small JSON-backed ring buffer of the last N labels printed.

Each entry stores:
  - id           short random id (used in URLs and DELETE)
  - ts           epoch seconds (printed-at timestamp)
  - format_index, format_name, format_code, kind  — for filtering & display
  - payload      the original /api/print payload (minus printer_name) so the
                 client can re-load it as-is into the editor
  - thumb_b64    a small PNG (max ~200 px on the long side) base64-encoded,
                 for previews in the sidebar / history page

Storage: ~/.config/dymo-web/history.json
Capacity: HISTORY_MAX (default 200), FIFO eviction.
"""

import base64
import io
import json
import os
import secrets
import tempfile
import time

HISTORY_MAX = 200
THUMB_LONG_SIDE = 200


def _path():
    return os.path.expanduser('~/.config/dymo-web/history.json')


def _load_raw():
    try:
        with open(_path(), 'r') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def _write_raw(items):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='history.', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(items, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _make_thumb(pil_image):
    """Down-scale to THUMB_LONG_SIDE preserving aspect ratio, return base64 PNG."""
    img = pil_image.copy()
    w, h = img.size
    scale = THUMB_LONG_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def add(payload, format_meta, pil_image):
    """
    Append a new entry and evict oldest if over capacity. Returns the entry.
    `payload` is the request body (printer_name stripped); `format_meta` is the
    relevant chunk from FORMATS; `pil_image` is the rendered (printed) PNG.
    """
    items = _load_raw()
    entry = {
        'id': secrets.token_urlsafe(8),
        'ts': int(time.time()),
        'format_index': format_meta.get('index'),
        'format_name':  format_meta.get('name'),
        'format_code':  format_meta.get('code'),
        'kind':         format_meta.get('kind', 'label'),
        'payload':      payload,
        'thumb_b64':    _make_thumb(pil_image),
    }
    items.insert(0, entry)
    if len(items) > HISTORY_MAX:
        items = items[:HISTORY_MAX]
    _write_raw(items)
    return entry


def list_(limit=None, offset=0, kind=None):
    items = _load_raw()
    if kind:
        items = [it for it in items if it.get('kind') == kind]
    if offset:
        items = items[offset:]
    if limit:
        items = items[:limit]
    return items


def get(entry_id):
    for it in _load_raw():
        if it.get('id') == entry_id:
            return it
    return None


def delete(entry_id):
    items = _load_raw()
    new = [it for it in items if it.get('id') != entry_id]
    if len(new) != len(items):
        _write_raw(new)
        return True
    return False


def total():
    return len(_load_raw())
