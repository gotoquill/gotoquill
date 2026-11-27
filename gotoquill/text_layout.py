"""Visible Standard 14 glyph bounds used by all boxed text stamp engines."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def glyph_metrics():
    return json.loads(Path(__file__).with_name("text-metrics.json").read_text())


def text_bounds(text, font="Helvetica"):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    metrics = glyph_metrics()[font]
    boxes, advance = [], 0.0
    for char in text:
        if char in metrics:
            left, bottom, right, top = metrics[char]
            boxes.append((advance + left, bottom, advance + right, top))
        advance += stringWidth(char, font, 1)
    if not boxes:
        return (0, -0.207, max(advance, 0.001), 0.718)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def write_box_text(page, rect, text, cap=11, font="Helvetica", color=(0, 0, 0)):
    pad = min(2.0, rect.width / 8, rect.height / 8)
    left, bottom, right, top = text_bounds(text, font)
    size = min(cap, (rect.width - 2 * pad) / max(right - left, 0.001),
               (rect.height - 2 * pad) / max(top - bottom, 0.001))
    point = (rect.x0 + rect.width / 2 - (left + right) * size / 2,
             rect.y0 + rect.height / 2 + (top + bottom) * size / 2)
    kwargs = {"fontname": font} if font != "Helvetica" else {}
    page.insert_text(point, text, fontsize=size, color=color, **kwargs)
