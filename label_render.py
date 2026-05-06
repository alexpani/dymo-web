import os
import platform
import re
import urllib.request
import urllib.parse
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
    {'name': '57 × 32 mm (Multipurpose, 11354)',    'width_mm': 57, 'height_mm': 32, 'code': '11354', 'cups_media': 'w162h90', 'kind': 'label', 'is_default': True},
    {'name': '89 × 28 mm (Address Small, 99010)',   'width_mm': 89, 'height_mm': 28, 'code': '99010', 'cups_media': {'Darwin': 'w81h252',  'Linux': 'w79h252.2'}, 'kind': 'label'},
    {'name': '102 × 54 mm (Shipping, 99014)',       'width_mm': 102,'height_mm': 54, 'code': '99014', 'cups_media': 'w154h286.2', 'kind': 'label'},
    {'name': '59 × 190 mm (LeverArch, 99019)',      'width_mm': 59, 'height_mm': 190,'code': '99019', 'cups_media': 'Custom.59x190mm', 'kind': 'label'},
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


def _layout(runs, max_width, max_height, font_size_pt=None,
            auto_fit_safety=0.0, line_spacing=0.2):
    """
    Returns (size, lines, line_height). Each line is a list of fragments.
    If font_size_pt is given, uses it; otherwise binary-searches the largest
    size that fits, optionally reducing the available height by auto_fit_safety
    (0..0.5) to leave breathing room.

    line_spacing: extra gap between lines as a fraction of line height
                  (0 = lines touching, 0.2 = default, 1.0 = double spacing).
    """
    if not font_size_pt and auto_fit_safety:
        max_height = int(max_height * max(0.0, 1.0 - min(0.5, auto_fit_safety)))
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
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * (line_h * line_spacing)
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


def render(fmt, runs=None,
           decor='none', qr_content='', icon_id='', decor_position='left',
           align='center', font_size_pt=None,
           auto_fit_safety=0.0, padding_mm=2.0, line_spacing=0.2,
           offset_x_mm=0.0, offset_y_mm=0.0,
           text='', bold=False, italic=False, orientation='horizontal',
           # legacy aliases (older clients / curl scripts):
           qr_enabled=False, qr_position=None):
    """
    Render a label as PIL.Image.

    fmt:             preset dict (name, width_mm, height_mm, kind, cups_media)
    decor:           'none' | 'qr' | 'icon'  (mutually exclusive)
    qr_content:      text/URL for the QR (used only when decor='qr')
    icon_id:         Iconify '<set>:<name>' (used only when decor='icon')
    decor_position:  'left' | 'right' | 'top' | 'bottom' — placement relative
                     to the text area. Ignored when there's no text (decor
                     centered on the label).
    runs:            list of {text, bold, italic}; '\\n' splits paragraphs
    align:           text alignment within its area
    font_size_pt:    int forced size, or None for auto-fit
    orientation:     'horizontal' (default) or 'vertical' — when vertical the
                     content is laid out on a swapped canvas (height × width)
                     and rotated 90° before output, so the printed paper
                     stays the same physical size but the text reads sideways.
    """
    if not runs:
        runs = [{'text': text, 'bold': bold, 'italic': italic}]
    if orientation == 'vertical' and fmt.get('kind') != 'tape':
        fmt = {**fmt, 'width_mm': fmt['height_mm'], 'height_mm': fmt['width_mm']}

    # Backward-compat: map old qr_enabled/qr_position to new decor params
    if decor == 'none' and qr_enabled and qr_content:
        decor = 'qr'
    if qr_position and decor_position == 'left':
        decor_position = qr_position

    if fmt.get('kind') == 'tape':
        img = _render_tape(fmt, runs, align, font_size_pt,
                           auto_fit_safety, padding_mm, line_spacing)
    else:
        img = _render_label(fmt, runs, decor, qr_content, icon_id, decor_position,
                            align, font_size_pt, auto_fit_safety, padding_mm, line_spacing)
    if orientation == 'vertical' and fmt.get('kind') != 'tape':
        # Rotate so the swapped canvas matches the physical paper size again.
        img = img.rotate(-90, expand=True)
    return _apply_offset(img, offset_x_mm, offset_y_mm)


def _apply_offset(img, offset_x_mm, offset_y_mm):
    """Translate the rendered content by (ox, oy) mm to compensate mechanical
    printer misalignment. Pixels shifted out of frame are cropped; the freed
    edge becomes white."""
    if not offset_x_mm and not offset_y_mm:
        return img
    ox = mm_to_px(offset_x_mm)
    oy = mm_to_px(offset_y_mm)
    if ox == 0 and oy == 0:
        return img
    out = Image.new(img.mode, img.size, 'white')
    out.paste(img, (ox, oy))
    return out


def _make_qr(qr_content, max_size_px):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=5, border=1)
    qr.add_data(qr_content)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    return img.resize((max_size_px, max_size_px), Image.Resampling.LANCZOS)


# ── Iconify integration ──────────────────────────────────────────────────────
ICON_CACHE_DIR = '/tmp/dymo-web-icons'
ICONIFY_BASE = 'https://api.iconify.design'


def _fetch_icon(icon_id, size_px):
    """
    Fetch an Iconify icon (or read from cache) and return a black PIL.Image
    resized to (size_px, size_px). Returns None on any network/parse error.

    Iconify's free API serves SVG only; we render to PNG locally with svglib
    + reportlab, then cache the rendered PNG.
    """
    if not icon_id or ':' not in icon_id:
        return None
    set_name, name = icon_id.split(':', 1)
    safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', f'{set_name}__{name}')
    os.makedirs(ICON_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(ICON_CACHE_DIR, f'{safe}.png')

    if not os.path.exists(cache_path):
        url = f'{ICONIFY_BASE}/{urllib.parse.quote(set_name)}:{urllib.parse.quote(name)}.svg?color=%23000'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'dymo-web/1.0'})
            with urllib.request.urlopen(req, timeout=5) as r:
                svg_bytes = r.read()
            # Convert SVG -> PNG @ 600px (cache once, resize on demand)
            import io as _io
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
            drawing = svg2rlg(_io.BytesIO(svg_bytes))
            target = 600
            scale = target / max(drawing.width or target, drawing.height or target)
            drawing.width = drawing.minWidth() * scale
            drawing.height = drawing.height * scale
            drawing.scale(scale, scale)
            renderPM.drawToFile(drawing, cache_path, fmt='PNG')
        except Exception:
            return None

    try:
        icon = Image.open(cache_path).convert('RGBA')
    except Exception:
        return None
    return icon.resize((size_px, size_px), Image.Resampling.LANCZOS)


def _paste_icon(canvas, icon_rgba, position):
    """Paste an RGBA icon onto a white canvas, preserving transparency."""
    x, y = position
    canvas.paste(icon_rgba, (x, y), icon_rgba)


def _build_decor(decor, qr_content, icon_id, size_px):
    """Return RGB or RGBA PIL.Image for the chosen decor (QR or icon), or None."""
    if decor == 'qr' and qr_content:
        return _make_qr(qr_content, size_px)
    if decor == 'icon' and icon_id:
        return _fetch_icon(icon_id, size_px)
    return None


def _render_label(fmt, runs, decor, qr_content, icon_id, decor_position, align,
                  font_size_pt, auto_fit_safety=0.0, padding_mm=2.0,
                  line_spacing=0.2):
    width_px = mm_to_px(fmt['width_mm'])
    height_px = mm_to_px(fmt['height_mm'])
    pad = mm_to_px(padding_mm)

    img = Image.new('RGB', (width_px, height_px), 'white')
    draw = ImageDraw.Draw(img)

    # Strip whitespace: contenteditable often leaves a stray '\n' from a <br>
    # after the user clears the field — that would falsely keep has_text true
    # and prevent the decor from centering.
    has_text = any((r.get('text') or '').strip() for r in runs)
    has_decor = decor in ('qr', 'icon') and (
        (decor == 'qr' and qr_content) or (decor == 'icon' and icon_id)
    )

    if has_decor and not has_text:
        # Centered: as big as the shorter side allows, leaving padding
        size = max(20, min(width_px, height_px) - 2 * pad)
        d_img = _build_decor(decor, qr_content, icon_id, size)
        if d_img is not None:
            dx = (width_px - d_img.size[0]) // 2
            dy = (height_px - d_img.size[1]) // 2
            if d_img.mode == 'RGBA':
                _paste_icon(img, d_img, (dx, dy))
            else:
                img.paste(d_img, (dx, dy))
        return img

    text_x, text_y = pad, pad
    text_w = width_px - 2 * pad
    text_h = height_px - 2 * pad

    if has_decor:
        if decor_position in ('left', 'right'):
            d_size = max(20, min(height_px - 2 * pad, width_px // 3))
        else:  # top, bottom
            d_size = max(20, min(width_px - 2 * pad, height_px // 3))
        d_img = _build_decor(decor, qr_content, icon_id, d_size)

        if d_img is not None:
            dw, dh = d_img.size
            if decor_position == 'left':
                dx, dy = pad, (height_px - dh) // 2
                text_x = dx + dw + pad
                text_w = width_px - text_x - pad
            elif decor_position == 'right':
                dx, dy = width_px - dw - pad, (height_px - dh) // 2
                text_w = dx - 2 * pad
            elif decor_position == 'top':
                dx, dy = (width_px - dw) // 2, pad
                text_y = dy + dh + pad
                text_h = height_px - text_y - pad
            else:  # bottom
                dx, dy = (width_px - dw) // 2, height_px - dh - pad
                text_h = dy - 2 * pad
            if d_img.mode == 'RGBA':
                _paste_icon(img, d_img, (dx, dy))
            else:
                img.paste(d_img, (dx, dy))

    if has_text and text_w > 10 and text_h > 10:
        size, lines, line_h = _layout(runs, text_w, text_h, font_size_pt,
                                      auto_fit_safety, line_spacing)
        _draw_lines(draw, lines, _font_cache(size), text_x, text_y, text_w, text_h,
                    line_h, align, line_spacing)
    return img


def _render_tape(fmt, runs, align, font_size_pt, auto_fit_safety=0.0,
                 padding_mm=2.0, line_spacing=0.2):
    """
    Tape: width fixed (= tape width), length auto-fit. Computes the largest
    font that fits vertically, then sizes the canvas length to the longest line.

    padding_mm is split: ~75% horizontally (along the tape) and 50% vertically
    (across the narrow tape width — even less air would crowd the glyphs).
    """
    height_px = mm_to_px(fmt['width_mm'])         # PNG height = tape width
    min_length_px = mm_to_px(fmt['height_mm'])    # minimum PNG length
    max_length_px = mm_to_px(1400)                # cap (CUPS w*h4000 ~= 1411 mm)

    pad_short = mm_to_px(max(0.5, padding_mm * 0.75))
    pad_long = mm_to_px(padding_mm)
    text_h = height_px - 2 * pad_short

    if not any((r.get('text') or '').strip() for r in runs):
        return Image.new('RGB', (min_length_px, height_px), 'white')

    # No-wrap layout: each paragraph is its own line, width unconstrained.
    size, lines, line_h = _layout(runs, max_length_px, text_h, font_size_pt,
                                  auto_fit_safety, line_spacing)

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
                width_px - 2 * pad_long, text_h, line_h, align, line_spacing)
    return img


def _draw_lines(draw, lines, get_font, text_x, text_y, text_w, text_h, line_h, align, spacing=0.2):
    """
    Draws each line and centers the whole block vertically based on the
    *visual* glyph height (not the font's full ascent+descent) so single-line
    text without descenders doesn't drift towards the bottom.

    Uses anchor='lt' so (x, y) is the exact top-left of the rendered glyph
    bounding box — independent of font internal padding.

    `spacing` is the extra gap between lines as a fraction of line height
    (default 0.2 = 20%).
    """
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
        # Baseline-anchor every fragment so glyphs of different heights line up
        # (anchor='lt' would top-align each fragment to its own bbox, lifting
        # short letters like 'e' relative to taller ones like 'T'). The baseline
        # sits at y + max_ascent across the line's fragments.
        max_ascent = max(get_font(fr['bold'], fr['italic']).getmetrics()[0] for fr in line)
        baseline_y = y + max_ascent
        for fr in line:
            font = get_font(fr['bold'], fr['italic'])
            draw.text((x, baseline_y), fr['text'], fill='black', font=font, anchor='ls')
            x += draw.textlength(fr['text'], font=font)
        y += lvh * (1 + spacing)
