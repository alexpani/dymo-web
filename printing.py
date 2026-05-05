import subprocess
import tempfile
import os
from label_render import FORMATS, DPI, resolve_cups_media

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


def _px_to_mm(px):
    return round(px / DPI * 25.4, 1)


def _print_args(fmt, image):
    """
    Returns (image_to_save, media_arg, extra_opts) for the given preset+image.

    For label kind: use the PPD-defined cups_media (or Custom.WxHmm fallback)
    and let CUPS fit the PNG to the media.

    For tape kind: rotate the landscape PNG to portrait so it matches the
    CUPS portrait media orientation, then specify Custom.WIDTHxLENGTHmm with
    the exact rendered length. Skip fit-to-page (no scaling).
    """
    if fmt.get('kind') == 'tape':
        rotated = image.rotate(90, expand=True)
        length_mm = _px_to_mm(rotated.size[1])  # portrait height after rotation
        media = f"Custom.{fmt['width_mm']}x{length_mm}mm"
        return rotated, media, []

    media = resolve_cups_media(fmt) or f"Custom.{fmt['width_mm']}x{fmt['height_mm']}mm"
    return image, media, ['-o', 'fit-to-page']


def print_label(printer_name, image, format_index):
    """
    Print a PIL.Image to the given printer.
    Returns (ok: bool, message: str).
    """
    fmt = FORMATS[format_index]
    img_to_send, media, extra = _print_args(fmt, image)

    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    try:
        img_to_send.save(tmp.name, format='PNG')
        tmp.close()

        cmd = ['lp', '-d', printer_name, '-o', f'media={media}', *extra, tmp.name]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def build_print_command(printer_name, format_index, png_path='<png_temp>'):
    """Return the lp command that would be executed (for dry-run inspection)."""
    fmt = FORMATS[format_index]
    if fmt.get('kind') == 'tape':
        # length placeholder; real length depends on rendered image
        media = f"Custom.{fmt['width_mm']}xL_mm"
        return ['lp', '-d', printer_name, '-o', f'media={media}', png_path]
    media = resolve_cups_media(fmt) or f"Custom.{fmt['width_mm']}x{fmt['height_mm']}mm"
    return ['lp', '-d', printer_name, '-o', f'media={media}', '-o', 'fit-to-page', png_path]
