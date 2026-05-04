import subprocess
import tempfile
import os
from label_render import FORMATS

def list_printers():
    """Return list of CUPS printers as [{name, is_default}]."""
    printers = []

    # Get all printers
    try:
        result = subprocess.run(
            ['lpstat', '-p'],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            # Format: "printer NAME is ..." or italian "la stampante NAME è ..."
            parts = line.split()
            if len(parts) >= 2:
                # English: "printer X is" / Italian: "la stampante X è"
                if parts[0] == 'printer':
                    printers.append(parts[1])
                elif parts[0] == 'la' and len(parts) >= 3 and parts[1] == 'stampante':
                    printers.append(parts[2])
    except subprocess.CalledProcessError:
        return []

    # Get default
    default = None
    try:
        result = subprocess.run(
            ['lpstat', '-d'],
            capture_output=True, text=True, check=True
        )
        # "system default destination: NAME" or "destinazione predefinita di sistema: NAME"
        line = result.stdout.strip()
        if ':' in line:
            default = line.split(':', 1)[1].strip()
    except subprocess.CalledProcessError:
        pass

    return [{'name': p, 'is_default': p == default} for p in printers]


def get_media_options(printer_name):
    """Return list of media size names supported by a printer (from lpoptions)."""
    try:
        result = subprocess.run(
            ['lpoptions', '-p', printer_name, '-l'],
            capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            # Format: "PageSize/Media Size: option1 option2 *current ..."
            if line.startswith('PageSize') or line.startswith('media'):
                _, _, options = line.partition(':')
                return [o.lstrip('*').strip() for o in options.split() if o.strip()]
    except subprocess.CalledProcessError:
        return []
    return []


def print_label(printer_name, image, format_index):
    """
    Print a PIL.Image to the given printer.
    Returns (ok: bool, message: str).
    """
    name, width_mm, height_mm, code = FORMATS[format_index]

    # Save image to temp PNG
    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    try:
        image.save(tmp.name, format='PNG')
        tmp.close()

        # Build lp command. Use Custom media size in millimeters.
        media = f'Custom.{width_mm}x{height_mm}mm'

        cmd = [
            'lp',
            '-d', printer_name,
            '-o', f'media={media}',
            '-o', 'fit-to-page',
            tmp.name,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip() or result.stdout.strip()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def build_print_command(printer_name, format_index, png_path='<png_temp>'):
    """Return the lp command that would be executed (for dry-run inspection)."""
    name, width_mm, height_mm, code = FORMATS[format_index]
    media = f'Custom.{width_mm}x{height_mm}mm'
    return ['lp', '-d', printer_name, '-o', f'media={media}', '-o', 'fit-to-page', png_path]
