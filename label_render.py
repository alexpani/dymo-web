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
    {'name': '59 × 190 mm (LeverArch, 99019)',      'width_mm': 59, 'height_mm': 190,'code': '99019', 'cups_media': 'w167h539', 'kind': 'label'},
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


# ── PPD imageable area (in mm) ────────────────────────────────────────────────
# Values read from /etc/cups/ppd/DYMO_LabelWriter_DUO_Label.ppd on the Pi.
# Tuple is (left, top, right, bottom). For pre-cut labels DYMO leaves a sizeable
# top margin (~5-6 mm) to account for the leading-edge sensor; bottom is ~1.5 mm.
# Used to: (a) render the PNG at exact imageable size so the printer doesn't
# scale it (no fit-to-page), and (b) compute an automatic offset that puts the
# logical centre of the content at the *physical* centre of the label.
PPD_IMAGEABLE_MARGINS_MM = {
    'w162h90':    (1.016, 1.524, 1.016, 1.524),  # 11354 Multi-Purpose 57×32 (symmetric)
    'w154h286.2': (1.524, 5.42,  1.016, 1.524),  # 99014 Shipping 102×54
    'w102h252.1': (1.524, 5.67,  1.016, 1.524),  # 99012 Large Address 89×36
    'w101h252':   (1.524, 5.67,  1.016, 1.524),  # 99012 macOS PPD name
    'w79h252.2':  (1.524, 5.84,  1.016, 1.524),  # 99010 Standard Address 89×28
    'w81h252':    (1.524, 5.84,  1.016, 1.524),  # 99010 macOS PPD name
    'w54h144':    (1.439, 5.76,  1.016, 1.524),  # 11355 Multi-Purpose 51×19
    'w72h72':     (1.439, 2.37,  1.016, 1.524),  # 11353 Multi-Purpose 25×25
    'w167h539':   (1.439, 5.59,  1.016, 1.524),  # 99019 Large Lever Arch 59×190
}
DEFAULT_IMAGEABLE_MARGINS_MM = (1.0, 1.5, 1.0, 1.5)  # safe DYMO label default


def get_imageable_margins_mm(fmt):
    """Return (left, top, right, bottom) in mm for this preset's media."""
    if fmt.get('imageable_margins_mm'):
        m = fmt['imageable_margins_mm']
        if isinstance(m, (list, tuple)) and len(m) == 4:
            return tuple(float(x) for x in m)
    media = resolve_cups_media(fmt) or ''
    return PPD_IMAGEABLE_MARGINS_MM.get(media, DEFAULT_IMAGEABLE_MARGINS_MM)


def imageable_size_mm(fmt):
    """Return (w_mm, h_mm) = paper minus the printer's hardware margins."""
    L, T, R, B = get_imageable_margins_mm(fmt)
    return (max(1.0, fmt['width_mm'] - L - R),
            max(1.0, fmt['height_mm'] - T - B))


def centring_offset_mm(fmt):
    """Return (dx_mm, dy_mm) needed to push the logical centre of an
    imageable-sized canvas onto the *physical* centre of the paper.
    For symmetric margins this is (0, 0)."""
    L, T, R, B = get_imageable_margins_mm(fmt)
    return ((L - R) / 2.0, (T - B) / 2.0)


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
        # Per-line visual height = how tall the actual glyphs are. We must
        # match what _draw_lines does (otherwise the bin search reserves
        # space for descenders that aren't there and the result drifts off
        # centre). We use the same _line_visual_geometry helper for both.
        f_default = get_font(False, False)
        default_h = f_default.getbbox('Ay')[3] - f_default.getbbox('Ay')[1]
        line_visual_hs = []
        for line in lines:
            if not line:
                line_visual_hs.append(default_h)
                continue
            asc, desc = _line_visual_geometry(line, get_font)
            line_visual_hs.append((asc + desc) or default_h)
        total_h = sum(line_visual_hs) + sum(h * line_spacing for h in line_visual_hs[:-1])
        line_h = max(line_visual_hs) if line_visual_hs else default_h
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

    # Backward-compat: map old qr_enabled/qr_position to new decor params
    if decor == 'none' and qr_enabled and qr_content:
        decor = 'qr'
    if qr_position and decor_position == 'left':
        decor_position = qr_position

    is_vertical = orientation == 'vertical' and fmt.get('kind') != 'tape'

    if fmt.get('kind') == 'tape':
        img = _render_tape(fmt, runs, align, font_size_pt,
                           auto_fit_safety, padding_mm, line_spacing)
    else:
        # Render at the imageable size (paper minus PPD hardware margins),
        # so the print pipeline can ship the PNG as-is — no fit-to-page,
        # no asymmetric scaling. The driver places the bitmap inside the
        # imageable area and the PPD's hardware margins do the rest.
        i_w, i_h = imageable_size_mm(fmt)
        if is_vertical:
            i_w, i_h = i_h, i_w
        fmt_eff = {**fmt, 'width_mm': i_w, 'height_mm': i_h}
        img = _render_label(fmt_eff, runs, decor, qr_content, icon_id, decor_position,
                            align, font_size_pt, auto_fit_safety, padding_mm, line_spacing)

    if is_vertical:
        img = img.rotate(-90, expand=True)
    return _apply_offset(img, offset_x_mm, offset_y_mm)


def render_calibration(fmt, offset_x_mm=0.0, offset_y_mm=0.0):
    """Render a calibration pattern for a preset: frame around the imageable
    area, centred crosshair (so it lands on the *paper* centre after
    auto-compensation), and 1 mm / 5 mm rulers on all four sides.

    Stamp it, measure how far the cross is from the physical centre of the
    label, and put that delta into the preset's offset_x/y_mm — repeat until
    centred. The on-screen crosshair sits at the PNG centre and the apply-
    offset step shifts the bitmap by (centring + user) mm, exactly like a
    normal print, so what you measure on paper is exactly what the formula
    is doing.

    Tapes are continuous, so for kind='tape' we draw a 60 mm long sample.
    """
    if fmt.get('kind') == 'tape':
        canvas_w_mm = 60.0
        canvas_h_mm = float(fmt['width_mm'])
    else:
        canvas_w_mm, canvas_h_mm = imageable_size_mm(fmt)

    w = mm_to_px(canvas_w_mm)
    h = mm_to_px(canvas_h_mm)
    img = Image.new('RGB', (w, h), 'white')
    draw = ImageDraw.Draw(img)

    # Frame at the imageable border
    draw.rectangle([(0, 0), (w - 1, h - 1)], outline='black', width=2)

    # Crosshair at canvas centre (= imageable centre, becomes paper centre
    # after auto-compensation in apply_offset).
    cx, cy = w // 2, h // 2
    arm = mm_to_px(min(canvas_w_mm, canvas_h_mm) * 0.18)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill='black', width=2)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill='black', width=2)
    r = max(2, mm_to_px(0.6))
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline='black', width=2)

    # mm rulers along all four edges
    long_tick = mm_to_px(2.0)
    short_tick = mm_to_px(1.0)
    for mm in range(int(canvas_w_mm) + 1):
        x = mm_to_px(mm)
        if x >= w:
            continue
        t = long_tick if mm % 5 == 0 else short_tick
        draw.line([(x, 0), (x, t)], fill='black', width=1)
        draw.line([(x, h - 1 - t), (x, h - 1)], fill='black', width=1)
    for mm in range(int(canvas_h_mm) + 1):
        y = mm_to_px(mm)
        if y >= h:
            continue
        t = long_tick if mm % 5 == 0 else short_tick
        draw.line([(0, y), (t, y)], fill='black', width=1)
        draw.line([(w - 1 - t, y), (w - 1, y)], fill='black', width=1)

    # Caption: imageable size and applied offsets
    label_size = max(8, mm_to_px(2.2))
    try:
        font = _load_font(label_size)
    except Exception:
        font = None
    caption = f'{canvas_w_mm:.1f}×{canvas_h_mm:.1f}mm  ox={offset_x_mm:+.2f} oy={offset_y_mm:+.2f}'
    if font is not None:
        bb = draw.textbbox((0, 0), caption, font=font, anchor='lt')
        tw = bb[2] - bb[0]
        th = bb[3] - bb[1]
        draw.text((cx - tw / 2, cy + arm + mm_to_px(1.5)), caption,
                  fill='black', font=font, anchor='lt')

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


def _line_visual_geometry(line, get_font):
    """For one line, return (ascent_above_baseline, descent_below_baseline)
    measured on the actual glyphs (not the font's full ascent/descent metric).

    PIL's font.getbbox(text) returns coords relative to the *ascender top*
    (anchor 'la'). To convert to baseline-relative we subtract the font's
    ascent metric:
        top_above_baseline    = ascent_metric - bbox[1]
        bottom_below_baseline = bbox[3]       - ascent_metric
    Either may go negative for unusual glyphs; we take per-fragment max so
    the line's tallest glyph defines the line height.
    """
    asc = desc = 0
    for fr in line:
        font = get_font(fr['bold'], fr['italic'])
        ascent_metric = font.getmetrics()[0]
        bb = font.getbbox(fr['text'])
        asc  = max(asc,  ascent_metric - bb[1])
        desc = max(desc, bb[3] - ascent_metric)
    return asc, desc


def _draw_lines(draw, lines, get_font, text_x, text_y, text_w, text_h, line_h, align, spacing=0.2):
    """
    Centre the text block vertically using the *real* glyph extents (not the
    font's ascender/descender metric), so single-line all-caps text doesn't
    drift downward and lines with only ascender-less glyphs don't float up.

    Each line's space is (visual_ascent + visual_descent), measured fragment
    by fragment in _line_visual_geometry. The baseline of each line is then
    placed so the line's visual top lands exactly at the running y cursor.
    """
    # Per-line visual geometry, matching _layout's bin search.
    geos = []
    for line in lines:
        if not line:
            geos.append((line_h, 0))  # placeholder for blank paragraph
        else:
            geos.append(_line_visual_geometry(line, get_font))
    line_visual_hs = [a + d for a, d in geos]

    total_h = sum(line_visual_hs) + sum(h * spacing for h in line_visual_hs[:-1])
    y = text_y + max(0, (text_h - total_h) / 2)

    for line, (asc, desc) in zip(lines, geos):
        lvh = asc + desc
        line_w = sum(draw.textlength(fr['text'], font=get_font(fr['bold'], fr['italic'])) for fr in line)
        if align == 'right':
            x = text_x + text_w - line_w
        elif align == 'left':
            x = text_x
        else:
            x = text_x + (text_w - line_w) / 2
        baseline_y = y + asc  # visual top of glyphs = y; baseline = y + ascent
        for fr in line:
            font = get_font(fr['bold'], fr['italic'])
            draw.text((x, baseline_y), fr['text'], fill='black', font=font, anchor='ls')
            x += draw.textlength(fr['text'], font=font)
        y += lvh * (1 + spacing)
