import re
from PIL import Image, ImageDraw, ImageFont
import qrcode

# macOS Helvetica TTC: 0=Regular 1=Bold 2=Oblique 3=BoldOblique
FONT_PATH = '/System/Library/Fonts/Helvetica.ttc'

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
    index = (1 if bold else 0) + (2 if italic else 0)
    try:
        return ImageFont.truetype(FONT_PATH, size, index=index)
    except OSError:
        return ImageFont.truetype(FONT_PATH, size, index=0)


def _font_cache(size):
    """Memoized font getter for a single render pass."""
    cache = {}
    def get(bold, italic):
        key = (bold, italic)
        if key not in cache:
            cache[key] = _load_font(size, bold, italic)
        return cache[key]
    return get


def _split_paragraphs(runs):
    """Split runs on '\\n' into a list of paragraphs (each = list of fragments)."""
    paragraphs = [[]]
    for run in runs:
        text = run.get('text', '')
        bold = bool(run.get('bold'))
        italic = bool(run.get('italic'))
        if not text:
            continue
        parts = text.split('\n')
        for i, part in enumerate(parts):
            if i > 0:
                paragraphs.append([])
            if part:
                paragraphs[-1].append({'text': part, 'bold': bold, 'italic': italic})
    return paragraphs


def _wrap_paragraph(fragments, max_width, draw, get_font):
    """Greedy word-wrap. Returns list of lines (each = list of fragments)."""
    atoms = []
    current_word = []
    for frag in fragments:
        for tok in re.findall(r'\s+|\S+', frag['text']):
            f = {'text': tok, 'bold': frag['bold'], 'italic': frag['italic']}
            if tok.isspace():
                if current_word:
                    atoms.append(current_word)
                    current_word = []
                atoms.append([f])
            else:
                current_word.append(f)
    if current_word:
        atoms.append(current_word)

    def atom_width(atom):
        return sum(draw.textlength(f['text'], font=get_font(f['bold'], f['italic'])) for f in atom)

    lines = [[]]
    current_w = 0
    for atom in atoms:
        is_space = all(f['text'].isspace() for f in atom)
        w = atom_width(atom)
        if not lines[-1] or current_w + w <= max_width:
            lines[-1].extend(atom)
            current_w += w
        else:
            lines.append([])
            current_w = 0
            if not is_space:
                lines[-1].extend(atom)
                current_w = w

    for line in lines:
        while line and line[-1]['text'].isspace():
            line.pop()
    return [l for l in lines if l] or [[]]


def _layout(runs, max_width, max_height, font_size_pt=None):
    """
    Returns (size, lines, line_height). Each line is a list of fragments.
    If font_size_pt is given, uses it; otherwise binary-searches the largest
    size that fits.
    """
    tmp_img = Image.new('RGB', (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)
    paragraphs = _split_paragraphs(runs)

    def lines_for_size(size):
        get_font = _font_cache(size)
        lines = []
        for para in paragraphs:
            if not para:
                lines.append([])
            else:
                lines.extend(_wrap_paragraph(para, max_width, tmp_draw, get_font))
        f = get_font(False, False)
        line_h = f.getbbox('Ay')[3] - f.getbbox('Ay')[1]
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * (line_h * 0.2)
        max_w = max(
            (sum(tmp_draw.textlength(fr['text'], font=get_font(fr['bold'], fr['italic'])) for fr in line)
             for line in lines if line),
            default=0,
        )
        return lines, line_h, total_h, max_w

    if font_size_pt:
        size = int(font_size_pt)
        lines, line_h, _, _ = lines_for_size(size)
        return size, lines, line_h

    lo, hi = 8, 400
    best = (lo, [], 0)
    while lo <= hi:
        mid = (lo + hi) // 2
        lines, line_h, total_h, max_w = lines_for_size(mid)
        if total_h <= max_height and max_w <= max_width:
            best = (mid, lines, line_h)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def render(format_index, runs=None, qr_enabled=False, qr_content='',
           align='center', font_size_pt=None,
           text='', bold=False, italic=False):
    """
    Render a label as PIL.Image.

    runs:    list of {text, bold, italic}. Newlines '\\n' inside text split paragraphs.
    text/bold/italic: legacy single-run shortcut, used only if runs is None/empty.
    align:   'left' | 'center' | 'right'
    font_size_pt: int forced size, or None for auto-fit.
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

    if not runs:
        runs = [{'text': text, 'bold': bold, 'italic': italic}]
    if not any(r.get('text') for r in runs):
        return img

    size, lines, line_h = _layout(runs, text_w, text_h, font_size_pt)
    get_font = _font_cache(size)

    total_h = len(lines) * line_h + max(0, len(lines) - 1) * (line_h * 0.2)
    y = text_y + max(0, (text_h - total_h) / 2)

    for line in lines:
        line_w = sum(draw.textlength(fr['text'], font=get_font(fr['bold'], fr['italic'])) for fr in line)
        if align == 'right':
            x = text_x + text_w - line_w
        elif align == 'left':
            x = text_x
        else:
            x = text_x + (text_w - line_w) / 2
        for fr in line:
            font = get_font(fr['bold'], fr['italic'])
            draw.text((x, y), fr['text'], fill='black', font=font)
            x += draw.textlength(fr['text'], font=font)
        y += line_h * 1.2

    return img
