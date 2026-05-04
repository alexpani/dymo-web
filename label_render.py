from PIL import Image, ImageDraw, ImageFont
import qrcode

# macOS system font (always present)
FONT_PATH = '/System/Library/Fonts/Helvetica.ttc'

# Label formats. cups_media = exact CUPS media name from `lpoptions -p <printer> -l`.
# If cups_media is None, we fall back to Custom.WxHmm.
FORMATS = [
    {'name': '89 × 36 mm (Address, 99012)',         'width_mm': 89, 'height_mm': 36, 'code': '99012', 'cups_media': 'w101h252'},
    {'name': '57 × 32 mm (Multipurpose, 11354)',    'width_mm': 57, 'height_mm': 32, 'code': '11354', 'cups_media': 'w162h90'},
    {'name': '32 × 57 mm (Multipurpose vertical)',  'width_mm': 32, 'height_mm': 57, 'code': '11354', 'cups_media': 'w162h90'},
    {'name': '89 × 28 mm (Address Small, 99010)',   'width_mm': 89, 'height_mm': 28, 'code': '99010', 'cups_media': 'w81h252'},
]

DPI = 300

def mm_to_px(mm):
    """Convert millimeters to pixels at DPI."""
    return int((mm / 25.4) * DPI)

def render(format_index, text, qr_enabled, qr_content):
    """
    Render a label as PIL.Image.

    Args:
        format_index: Index into FORMATS
        text: Label text (multiline)
        qr_enabled: bool
        qr_content: QR content string (if qr_enabled)

    Returns:
        PIL.Image (RGB)
    """
    fmt = FORMATS[format_index]
    width_px = mm_to_px(fmt['width_mm'])
    height_px = mm_to_px(fmt['height_mm'])

    # Create white background
    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)

    # If QR enabled, generate it
    qr_img = None
    if qr_enabled and qr_content:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=5,
            border=1,
        )
        qr.add_data(qr_content)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='black', back_color='white')

        # Scale QR to fit (max half width)
        qr_size = min(height_px - 10, width_px // 3)
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)

    # Draw QR on left if present
    qr_width = 0
    if qr_img:
        x = 5
        y = (height_px - qr_img.size[1]) // 2
        img.paste(qr_img, (x, y))
        qr_width = qr_img.size[0] + 10

    # Text area (with small inner padding)
    pad = mm_to_px(2)
    text_x = qr_width + pad
    text_y = pad
    text_w = width_px - text_x - pad
    text_h = height_px - 2 * pad

    if text:
        font, lines = _fit_text(text, text_w, text_h)
        # Center vertically
        line_h = font.getbbox('Ay')[3] - font.getbbox('Ay')[1]
        total_h = line_h * len(lines) + (len(lines) - 1) * (line_h * 0.2)
        y = text_y + max(0, (text_h - total_h) / 2)
        for line in lines:
            draw.text((text_x, y), line, fill='black', font=font)
            y += line_h * 1.2

    return img


def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit max_width pixels at given font size. Honors explicit \\n."""
    out = []
    for paragraph in text.splitlines() or ['']:
        words = paragraph.split()
        if not words:
            out.append('')
            continue
        line = words[0]
        for w in words[1:]:
            test = line + ' ' + w
            if draw.textlength(test, font=font) <= max_width:
                line = test
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def _fit_text(text, max_width, max_height):
    """
    Find the largest font size where wrapped text fits in (max_width, max_height).
    Returns (font, wrapped_lines).
    """
    # Use a throwaway image just for textlength measurement
    tmp_img = Image.new('RGB', (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)

    lo, hi = 8, 400
    best = (ImageFont.truetype(FONT_PATH, lo), [text])
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(FONT_PATH, mid)
        lines = _wrap_text(text, font, max_width, tmp_draw)
        line_h = font.getbbox('Ay')[3] - font.getbbox('Ay')[1]
        total_h = line_h * len(lines) + (len(lines) - 1) * (line_h * 0.2)
        widest = max((tmp_draw.textlength(l, font=font) for l in lines), default=0)

        if total_h <= max_height and widest <= max_width:
            best = (font, lines)
            lo = mid + 1
        else:
            hi = mid - 1
    return best
