from PIL import Image, ImageDraw, ImageFont
import qrcode

# macOS system font (TrueType Collection: 0=Regular 1=Bold 2=Oblique 3=BoldOblique)
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
    return int((mm / 25.4) * DPI)


def _load_font(size, bold=False, italic=False):
    """Load Helvetica face. Falls back to Regular if requested face missing."""
    index = (1 if bold else 0) + (2 if italic else 0)
    try:
        return ImageFont.truetype(FONT_PATH, size, index=index)
    except OSError:
        return ImageFont.truetype(FONT_PATH, size, index=0)


def render(format_index, text, qr_enabled, qr_content,
           bold=False, italic=False, align='center', font_size_pt=None):
    """
    Render a label as PIL.Image.

    align: 'left' | 'center' | 'right'
    font_size_pt: int forced size in points (treated as pixels at our DPI),
                  or None for auto-fit.
    """
    fmt = FORMATS[format_index]
    width_px = mm_to_px(fmt['width_mm'])
    height_px = mm_to_px(fmt['height_mm'])

    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)

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
        qr_size = min(height_px - 10, width_px // 3)
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)

    qr_width = 0
    if qr_img:
        x = 5
        y = (height_px - qr_img.size[1]) // 2
        img.paste(qr_img, (x, y))
        qr_width = qr_img.size[0] + 10

    pad = mm_to_px(2)
    text_x = qr_width + pad
    text_y = pad
    text_w = width_px - text_x - pad
    text_h = height_px - 2 * pad

    if not text:
        return img

    if font_size_pt:
        font = _load_font(int(font_size_pt), bold, italic)
        lines = _wrap_text(text, font, text_w, draw)
    else:
        font, lines = _fit_text(text, text_w, text_h, bold, italic)

    line_h = font.getbbox('Ay')[3] - font.getbbox('Ay')[1]
    total_h = line_h * len(lines) + (len(lines) - 1) * (line_h * 0.2)
    y = text_y + max(0, (text_h - total_h) / 2)

    for line in lines:
        line_w = draw.textlength(line, font=font)
        if align == 'right':
            x = text_x + text_w - line_w
        elif align == 'left':
            x = text_x
        else:  # center (default)
            x = text_x + (text_w - line_w) / 2
        draw.text((x, y), line, fill='black', font=font)
        y += line_h * 1.2

    return img


def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit max_width pixels at given font. Honors explicit \\n."""
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


def _fit_text(text, max_width, max_height, bold=False, italic=False):
    """Largest font size where wrapped text fits in (max_width, max_height)."""
    tmp_img = Image.new('RGB', (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)

    lo, hi = 8, 400
    best = (_load_font(lo, bold, italic), [text])
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _load_font(mid, bold, italic)
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
