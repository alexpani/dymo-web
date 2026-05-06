"""
Per-preset overrides: a small JSON store keyed by preset name.

Each preset can override a subset of these knobs (others fall back to defaults
hard-coded in label_render):

    offset_x_mm     float, -5..5    horizontal print offset (compensates
                                    mechanical printer misalignment)
    offset_y_mm     float, -5..5    vertical print offset
    auto_fit_safety float, 0..0.5   fraction of available height reserved as
                                    breathing room when auto-fitting the font
    padding_mm      float, 0..10    inner whitespace around text/decor

Storage: ~/.config/dymo-web/preset_overrides.json (writable by the running user).
"""

import json
import os
import tempfile

DEFAULTS = {
    'offset_x_mm':     0.0,
    'offset_y_mm':     0.0,
    'auto_fit_safety': 0.0,
    'padding_mm':      2.0,
}


def _path():
    return os.path.expanduser('~/.config/dymo-web/preset_overrides.json')


def load_all():
    """Return the full dict {preset_name: {key: value, ...}}."""
    try:
        with open(_path(), 'r') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def get(preset_name):
    """Return the merged effective settings for a preset (defaults + override)."""
    out = dict(DEFAULTS)
    overrides = load_all().get(preset_name, {})
    for k, v in overrides.items():
        if k in DEFAULTS:
            out[k] = v
    return out


def save(preset_name, override):
    """Merge override into the named preset and persist atomically."""
    all_data = load_all()
    current = all_data.get(preset_name, {})
    current.update({k: v for k, v in override.items() if k in DEFAULTS})
    all_data[preset_name] = current

    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='preset_overrides.', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(all_data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return current


def reset(preset_name):
    """Remove the override for preset_name (revert to defaults)."""
    all_data = load_all()
    if preset_name in all_data:
        del all_data[preset_name]
        _write(all_data)
    return DEFAULTS.copy()


def rename(old_name, new_name):
    """Move overrides from old_name to new_name (keeps the user's offset
    tweaks across a preset rename). No-op if old_name has no overrides or
    the names match."""
    if old_name == new_name:
        return
    all_data = load_all()
    if old_name not in all_data:
        return
    all_data[new_name] = all_data.pop(old_name)
    _write(all_data)


def _write(all_data):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(all_data, f, indent=2)
