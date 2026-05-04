from PIL import Image, ImageDraw, ImageFont
import qrcode
import textwrap

# Label formats. cups_media = exact CUPS media name from `lpoptions -p <printer> -l`.
# If cups_media is None, we fall back to Custom.WxHmm.
FORMATS = [
    {'name': '89 × 36 mm (Address, 99012)',         'width_mm': 89, 'height_mm': 36, 'code': '99012', 'cups_media': 'w101h252'},
    {'name': '57 × 32 mm (Multipurpose, 11354)',    'width_mm': 57, 'height_mm': 32, 'code': '11354', 'cups_media': None},
    {'name': '32 × 57 mm (Multipurpose vertical)',  'width_mm': 32, 'height_mm': 57, 'code': '11354', 'cups_media': None},
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

    # Text area
    text_x = qr_width + 5
    text_y = 5
    text_width = width_px - text_x - 5
    text_height = height_px - 10

    # Auto-scale font size
    font_size = 30
    while font_size > 8:
        try:
            font = ImageFont.load_default()
            # Estimate lines needed
            lines = textwrap.wrap(text, width=max(1, text_width // (font_size // 2)))
            line_height = font_size + 4
            total_height = len(lines) * line_height
            if total_height <= text_height:
                break
        except:
            pass
        font_size -= 2

    # Use default font (fixed width)
    font = ImageFont.load_default()

    # Wrap and draw text
    lines = textwrap.wrap(text, width=max(1, text_width // 8))
    y = text_y
    for line in lines:
        if y + 12 > text_y + text_height:
            break
        draw.text((text_x, y), line, fill='black', font=font)
        y += 14

    return img
