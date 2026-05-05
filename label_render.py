import platform
import re
from PIL import Image, ImageDraw, ImageFont
import qrcode

# Cross-platform font face mapping. Key = (bold, italic), value = (path, ttc_index).
# macOS uses Helvetica.ttc (one file, multiple faces via index).
# Linux (Pi OS / Debian) uses DejaVu Sans (separate files per face).
if platform.system() == 'Darwin':
    _MAC_HELVETICA = '/System/Library/Fonts/Helvetica.ttc'
    FONT_FACES = {
        (False, False): (_MAC_HELVETICA, 0),
        (True,  False): (_MAC_HELVETICA, 1),
        (False, True):  (_MAC_HELVETICA, 2),
        (True,  True):  (_MAC_HELVETICA, 3),
    }
else:
    _DEJAVU = '/usr/share/fonts/truetype/dejavu/'
    FONT_FACES = {
        (False, False): (_DEJAVU + 'DejaVuSans.ttf', 0),
        (True,  False): (_DEJAVU + 'DejaVuSans-Bold.ttf', 0),
        (False, True):  (_DEJAVU + 'DejaVuSans-Oblique.ttf', 0),
        (True,  True):  (_DEJAVU + 'DejaVuSans-BoldOblique.ttf', 0),
    }

FORMATS = [
    # Pre-cut adhesive labels (DYMO_LabelWriter_DUO_Label).
    # cups_media can be a string (same on all platforms) or a dict keyed by
    # platform.system() for the few cases where the PPDs disagree on names.
    {'name': '89 × 36 mm (Address, 99012)',         'width_mm': 89, 'height_mm': 36, 'code': '99012', 'cups_media': {'Darwin': 'w101h252', 'Linux': 'w102h252.1'}, 'kind': 'label'},
    {'name': '57 × 32 mm (Multipurpose, 11354)',    'width_mm': 57, 'height_mm': 32, 'code': '11354', 'cups_media': 'w162h90', 'kind': 'label'},
    {'name': '32 × 57 mm (Multipurpose vertical)',  'width_mm': 32, 'height_mm': 57, 'code': '11354', 'cups_media': 'w162h90', 'kind': 'label'},
    {'name': '89 × 28 mm (Address Small, 99010)',   'width_mm': 89, 'height_mm': 28, 'code': '99010', 'cups_media': {'Darwin': 'w81h252',  'Linux': 'w79h252.2'}, 'kind': 'label'},
    {'name': '102 × 54 mm (Shipping, 99014)',       'width_mm': 102,'height_mm': 54, 'code': '99014', 'cups_media': 'w154h286.2', 'kind': 'label'},
    {'name': '51 × 19 mm (Multipurpose, 11355)',    'width_mm': 51, 'height_mm': 19, 'code': '11355', 'cups_media': 'w54h144',    'kind': 'label'},
    {'name': '25 × 25 mm (Multipurpose, 11353)',    'width_mm': 25, 'height_mm': 25, 'code': '11353', 'cups_media': 'w72h72',     'kind': 'label'},
    # Continuous D1 tape (DYMO_LabelWriter_DUO_Tape_*). width_mm = tape width,
    # height_mm = minimum length; actual length is auto-fit to content.
    {'name': 'Nastro 9 mm  (auto-fit)',             'width_mm': 9,  'height_mm': 25, 'code': 'D1-9',  'cups_media': 'w26h4000', 'kind': 'tape'},
    {'name': 'Nastro 12 mm (auto-fit)',             'width_mm': 12, 'height_mm': 25, 'code': 'D1-12', 'cups_media': 'w35h4000', 'kind': 'tape'},
    {'name': 'Nastro 19 mm (auto-fit)',             'width_mm': 19, 'height_mm': 25, 'code': 'D1-19', 'cups_media': 'w55h4000', 'kind': 'tape'},
    {'name': 'Nastro 24 mm (auto-fit)',             'width_mm': 24, 'height_mm': 25, 'code': 'D1-24', 'cups_media': 'w68h4000', 'kind': 'tape'},
]


def resolve_cups_media(fmt):
    """Return the CUPS media name appropriate for the current platform."""
    media = fmt.get('cups_media')
    if isinstance(media, dict):
        return media.get(platform.system())
    return media

DPI = 300


def mm_to_px(mm):
    return int((mm / 25.4) * DPI)


def _load_font(size, bold=False, italic=False):
    path, index = FONT_FACES.get((bool(bold), bool(italic)), FONT_FACES[(False, False)])
    try:
        return ImageFont.truetype(path, size, index=index)
    except OSError:
        regular_path, regular_index = FONT_FACES[(False, False)]
        return ImageFont.truetype(regular_path, size, index=regular_index)


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

    For 'label' kind: PNG dimensions are fixed by the preset.
    For 'tape' kind:  PNG height is the tape width; PNG length is auto-fit to
                       the longest rendered line (clamped to height_mm minimum).
    """
    fmt = FORMATS[format_index]
    if not runs:
        runs = [{'text': text, 'bold': bold, 'italic': italic}]

    if fmt.get('kind') == 'tape':
        return _render_tape(fmt, runs, align, font_size_pt)
    return _render_label(fmt, runs, qr_enabled, qr_content, align, font_size_pt)


def _render_label(fmt, runs, qr_enabled, qr_content, align, font_size_pt):
    width_px = mm_to_px(fmt['width_mm'])
    height_px = mm_to_px(fmt['height_mm'])

    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)

    qr_img = None
    if qr_enabled and qr_content:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=5, border=1)
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

    if not any(r.get('text') for r in runs):
        return img

    size, lines, line_h = _layout(runs, text_w, text_h, font_size_pt)
    _draw_lines(draw, lines, _font_cache(size), text_x, text_y, text_w, text_h, line_h, align)
    return img


def _render_tape(fmt, runs, align, font_size_pt):
    """
    Tape: width fixed (= tape width), length auto-fit. Computes the largest
    font that fits vertically, then sizes the canvas length to the longest line.
    """
    height_px = mm_to_px(fmt['width_mm'])         # PNG height = tape width
    min_length_px = mm_to_px(fmt['height_mm'])    # minimum PNG length
    max_length_px = mm_to_px(1400)                # cap (CUPS w*h4000 ~= 1411 mm)

    # On narrow tape (9mm) a 1mm pad leaves too little visual breathing room
    # and the auto-fit pushes the font to the absolute max. 1.5mm gives a
    # better-looking result without wasting much surface.
    pad_short = mm_to_px(1.5)
    pad_long = mm_to_px(2)
    text_h = height_px - 2 * pad_short

    if not any(r.get('text') for r in runs):
        return Image.new('RGB', (min_length_px, height_px), 'white')

    # No-wrap layout: each paragraph is its own line, width unconstrained.
    size, lines, line_h = _layout(runs, max_length_px, text_h, font_size_pt)

    tmp_img = Image.new('RGB', (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)
    get_font = _font_cache(size)
    widest = max(
        (sum(tmp_draw.textlength(fr['text'], font=get_font(fr['bold'], fr['italic'])) for fr in line)
         for line in lines if line),
        default=0,
    )
    width_px = max(min_length_px, int(widest) + 2 * pad_long)

    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)
    _draw_lines(draw, lines, get_font, pad_long, pad_short,
                width_px - 2 * pad_long, text_h, line_h, align)
    return img


def _draw_lines(draw, lines, get_font, text_x, text_y, text_w, text_h, line_h, align):
    """
    Draws each line and centers the whole block vertically based on the
    *visual* glyph height (not the font's full ascent+descent) so single-line
    text without descenders doesn't drift towards the bottom.

    Uses anchor='lt' so (x, y) is the exact top-left of the rendered glyph
    bounding box — independent of font internal padding.
    """
    spacing = 0.2  # 20% inter-line gap

    # Per-line visual height = max bbox height across the line's fragments
    line_visual_hs = []
    for line in lines:
        h = 0
        for fr in line:
            f = get_font(fr['bold'], fr['italic'])
            bbox = f.getbbox(fr['text'])
            h = max(h, bbox[3] - bbox[1])
        line_visual_hs.append(h or line_h)

    total_h = sum(line_visual_hs) + sum(h * spacing for h in line_visual_hs[:-1])
    y = text_y + max(0, (text_h - total_h) / 2)

    for line, lvh in zip(lines, line_visual_hs):
        line_w = sum(draw.textlength(fr['text'], font=get_font(fr['bold'], fr['italic'])) for fr in line)
        if align == 'right':
            x = text_x + text_w - line_w
        elif align == 'left':
            x = text_x
        else:
            x = text_x + (text_w - line_w) / 2
        for fr in line:
            font = get_font(fr['bold'], fr['italic'])
            draw.text((x, y), fr['text'], fill='black', font=font, anchor='lt')
            x += draw.textlength(fr['text'], font=font)
        y += lvh * (1 + spacing)
