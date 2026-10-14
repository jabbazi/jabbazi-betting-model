"""Branded research graphic renderer. Requires the exact approved JABBAZI logo."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

BLACK = (9, 9, 9)
PANEL = (26, 26, 31)
PINK = (255, 10, 138)
WHITE = (255, 255, 255)
MUTED = (217, 217, 217)


def approved_logo_path():
    import os
    return os.getenv("JABBAZI_APPROVED_LOGO_PATH") or str(
        Path(__file__).resolve().parents[1] / "static" / "jabbazi-approved.png")


def render_research_card(title, lines, logo_file, *, notice="RESEARCH ONLY • NOT AN OFFICIAL BET"):
    """Render supplied canonical facts, never synthesize picks or probabilities."""
    with Image.open(logo_file) as raw:
        logo = ImageOps.contain(raw.convert("RGBA"), (190, 190))
    image = Image.new("RGB", (1200, 1200), BLACK)
    image.paste(logo, (30, 20), logo)
    draw = ImageDraw.Draw(image)
    text_fit(draw, (250, 85), title, max_width=900, size=38, bold=True, fill=PINK)
    draw.line((45, 225, 1155, 225), fill=PINK, width=3)
    for i, line in enumerate(lines[:10]):
        y = 250+i*78
        draw.rounded_rectangle((45, y, 1155, y+66), radius=12, fill=PANEL)
        text_fit(draw, (65, y+18), line, max_width=1060, size=25)
    text_fit(draw, (45, 1100), notice, max_width=1110, size=20, fill=PINK)
    draw.text((45, 1140), "JABBAZI • Timestamped evidence. Keep losses in the record.", font=font(18), fill=MUTED)
    out = BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def text_fit(draw, position, text, *, max_width, size, fill=WHITE, bold=False):
    value = str(text or "Unavailable")
    size = max(12, size)
    f = font(size, bold)
    while size > 14 and draw.textbbox((0, 0), value, font=f)[2] > max_width:
        size -= 2
        f = font(size, bold)
    while value and draw.textbbox((0, 0), value, font=f)[2] > max_width:
        value = value[:-2].rstrip('…') + '…'
    draw.text(position, value, font=f, fill=fill)


def render_matchup(detail, logo_file):
    path = Path(logo_file)
    if not path.is_file():
        raise FileNotFoundError("The approved JABBAZI logo asset is not configured.")
    with Image.open(path) as raw:
        logo = raw.convert("RGB")
    image = Image.new("RGB", (1200, 675), BLACK)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 1182, 657), radius=22, outline=PINK, width=3)
    logo = ImageOps.contain(logo, (360, 185), method=Image.Resampling.LANCZOS)
    image.paste(logo, (42, 24))
    draw.text((430, 54), "JABBAZI MATCHUP RESEARCH", font=font(30, True), fill=PINK)
    draw.text((432, 110), str(detail.get("sport") or "SPORT"), font=font(18, True), fill=MUTED)
    text_fit(draw, (432, 145), 'Start: '+str(detail.get('starts_at') or 'Unavailable'), max_width=710, size=18, fill=MUTED)
    text_fit(draw, (432, 175), 'Model: '+str(detail.get('projection', {}).get('model_stage') or 'UNAVAILABLE'), max_width=710, size=16, fill=MUTED)
    draw.line((45, 207, 1155, 207), fill=PINK, width=3)
    text_fit(draw, (52, 245), detail.get("event"), max_width=1080, size=52, bold=True)
    draw.rounded_rectangle((46, 350, 1154, 555), radius=16, fill=PANEL)
    projection = detail.get("projection") or {}
    draw.text((78, 374), "PROJECTED WINNER", font=font(19, True), fill=PINK)
    text_fit(draw, (78, 416), projection.get("selection"), max_width=490, size=34, bold=True)
    draw.text((630, 374), "EVIDENCE", font=font(19, True), fill=PINK)
    text_fit(draw, (630, 415), projection.get("source"), max_width=460, size=23, bold=True)
    probability = projection.get("model_probability")
    value = f"Independent model: {probability*100:.1f}%" if probability is not None else "Independent model: unavailable"
    text_fit(draw, (630, 464), value, max_width=475, size=19, fill=MUTED)
    draw.text((53, 586), "RESEARCH ONLY  •  NOT AN OFFICIAL BET", font=font(19, True), fill=PINK)
    text_fit(draw, (53, 621), 'Snapshot: '+str(detail.get('snapshot_at') or 'Unavailable')+' • Recheck prices and availability.', max_width=1090, size=14, fill=MUTED)
    out = BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()
