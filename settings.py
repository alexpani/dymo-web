"""
App-wide settings persisted as JSON.

Server-side authoritative: each render() reads the current value, so changes
made from the /settings page apply immediately to all clients.
"""

import json
import os
import platform
import tempfile

DEFAULTS = {
    # Fraction (0..0.5) by which the auto-fit font max height is reduced.
    # 0 = use the full available height; 0.1 = reserve 10% air; 0.5 = use half.
    'auto_fit_safety': 0.0,
}


def _path():
    if platform.system() == 'Darwin':
        d = os.path.expanduser('~/.config/dymo-web')
    else:
        d = '/etc/dymo-web'
    return os.path.join(d, 'settings.json')


def load():
    """Return the merged dict (defaults + on-disk overrides)."""
    out = dict(DEFAULTS)
    try:
        with open(_path(), 'r') as f:
            out.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return out


def save(updates):
    """Merge updates into the current settings and persist atomically."""
    current = load()
    current.update({k: v for k, v in updates.items() if k in DEFAULTS})
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='settings.', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(current, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return current
