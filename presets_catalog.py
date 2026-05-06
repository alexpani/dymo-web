"""
Mutable catalog of label presets. Seeded once from label_render.FORMATS;
from then on the JSON file is the source of truth. Users can add, edit and
delete entries through /api/presets.

Storage: ~/.config/dymo-web/presets.json (writable by the running user).

Each entry is a plain dict with the same shape used elsewhere in the app:

    name        str   shown in the picker
    width_mm    float
    height_mm   float
    kind        'label' | 'tape'
    cups_media  str | dict (per-platform mapping for built-ins; user-added
                presets always store a single string)
    code        str   optional, free-form (e.g. "99012", "D1-12")
    is_default  bool  optional
"""

import json
import os
import tempfile

from label_render import FORMATS as _SEED


REQUIRED = ('name', 'width_mm', 'height_mm', 'kind', 'cups_media')
ALLOWED_KINDS = ('label', 'tape')


def _path():
    return os.path.expanduser('~/.config/dymo-web/presets.json')


def load():
    """Return the current catalog. Falls back to the built-in seed on
    missing/corrupt file."""
    try:
        with open(_path(), 'r') as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except (FileNotFoundError, ValueError, OSError):
        pass
    return [dict(p) for p in _SEED]


def save_all(presets):
    """Atomically replace the whole catalog."""
    if not isinstance(presets, list) or not presets:
        raise ValueError('catalog must be a non-empty list')
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='presets.', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(presets, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def validate(p):
    """Coerce/validate a preset dict. Raises ValueError on bad input.
    Returns the cleaned dict."""
    if not isinstance(p, dict):
        raise ValueError('preset must be an object')
    out = {}
    for k in REQUIRED:
        if k not in p or p[k] in (None, ''):
            raise ValueError(f'missing required field: {k}')
    out['name'] = str(p['name']).strip()
    if not out['name']:
        raise ValueError('name cannot be empty')
    try:
        out['width_mm']  = float(p['width_mm'])
        out['height_mm'] = float(p['height_mm'])
    except (TypeError, ValueError):
        raise ValueError('width_mm and height_mm must be numbers')
    if out['width_mm'] <= 0 or out['height_mm'] <= 0:
        raise ValueError('width_mm and height_mm must be positive')
    if p['kind'] not in ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {ALLOWED_KINDS}")
    out['kind'] = p['kind']
    media = p['cups_media']
    if isinstance(media, dict):
        out['cups_media'] = {str(k): str(v) for k, v in media.items()}
    else:
        out['cups_media'] = str(media).strip()
        if not out['cups_media']:
            raise ValueError('cups_media cannot be empty')
    if p.get('code'):
        out['code'] = str(p['code']).strip()
    if p.get('is_default'):
        out['is_default'] = True
    return out


def add(preset):
    """Append a validated preset. Returns the new index."""
    catalog = load()
    catalog.append(validate(preset))
    save_all(catalog)
    return len(catalog) - 1


def update(index, preset):
    """Replace the preset at index with the validated payload. Returns the
    (old_name, new_name) pair so callers can migrate per-preset overrides."""
    catalog = load()
    if not (0 <= index < len(catalog)):
        raise IndexError('preset index out of range')
    old_name = catalog[index].get('name')
    catalog[index] = validate(preset)
    save_all(catalog)
    return old_name, catalog[index]['name']


def delete(index):
    """Remove the preset at index. Refuses to empty the catalog. Returns the
    name of the deleted preset (so the caller can drop its overrides)."""
    catalog = load()
    if not (0 <= index < len(catalog)):
        raise IndexError('preset index out of range')
    if len(catalog) <= 1:
        raise ValueError('cannot delete the last remaining preset')
    removed = catalog.pop(index)
    save_all(catalog)
    return removed.get('name')
