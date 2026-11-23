"""Test helpers: build small PDFs (reportlab) and inspect results (gotoquill.pdfdoc / pypdf / pypdfium2).
Coordinates are PDF points with a top-left origin, like the rest of gotoquill."""
from __future__ import annotations

import io

from PIL import Image
from pypdf import PdfReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from gotoquill import pdfdoc


class Page:
    def __init__(self, w, h):
        self.w, self.h, self.ops = w, h, []

    def insert_text(self, pt, text, fontsize=11, fontfile=None, fontname="Helvetica"):
        self.ops.append(("t", pt, text, fontsize, fontfile, fontname))

    def draw_line(self, a, b, width=1.0):
        self.ops.append(("l", a, b, width))

    def box(self, r, width=0.8):  # a box as 4 separate lines (like many real forms do)
        x0, y0, x1, y1 = r
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            self.draw_line(a, b, width)

    def text_field(self, name, r):
        self.ops.append(("f", name, r))


class Doc:
    def __init__(self):
        self.pages = []

    def new_page(self, width=595, height=842):
        self.pages.append(Page(width, height)); return self.pages[-1]

    def close(self):
        return None

    def tobytes(self) -> bytes:
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        for p in self.pages or [Page(595, 842)]:
            c.setPageSize((p.w, p.h))
            for op in p.ops:
                if op[0] == "t":
                    _, (x, y), text, fs, ff, fn = op
                    if ff:
                        fn = "F" + str(abs(hash(ff)))
                        if fn not in pdfmetrics.getRegisteredFontNames():
                            pdfmetrics.registerFont(TTFont(fn, ff))
                    c.setFont(fn, fs); c.drawString(x, p.h - y, text)
                elif op[0] == "l":
                    _, (ax, ay), (bx, by), w = op
                    c.setLineWidth(w); c.line(ax, p.h - ay, bx, p.h - by)
                else:
                    _, name, (x0, y0, x1, y1) = op
                    c.acroForm.textfield(name=name, x=x0, y=p.h - y1, width=x1 - x0, height=y1 - y0, borderWidth=0,
                                         fillColor=None, borderColor=None, value="")
            c.showPage()
        c.save()
        return buf.getvalue()


def sig_png(w=300, h=100) -> bytes:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for x in range(20, w - 20):  # a diagonal-ish stroke
        y = h // 2 + int(30 * ((x % 60) / 60 - 0.5))
        for dy in range(-2, 3):
            im.putpixel((x, y + dy), (10, 26, 74, 255))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def blank_png(w=60, h=20) -> bytes:
    b = io.BytesIO(); Image.new("RGB", (w, h), (0, 0, 0)).save(b, "PNG"); return b.getvalue()


def _data(src) -> bytes:
    if isinstance(src, (bytes, bytearray)):
        return bytes(src)
    with open(src, "rb") as f:
        return f.read()


def image_count(src, page=0) -> int:
    return len(PdfReader(io.BytesIO(_data(src))).pages[page].images)


def text(src, page=0) -> str:
    with pdfdoc.Document.open(_data(src)) as d:
        return d[page].get_text()


def widgets(src, page=0) -> list:
    with pdfdoc.Document.open(_data(src)) as d:
        return d[page].widgets()


def search_for(src, phrase, page=0) -> list:
    """Rects of the words covering each occurrence of `phrase` on a line (substring match, like a viewer's find)."""
    with pdfdoc.Document.open(_data(src)) as d:
        words = sorted(d[page].get_text("words"), key=lambda w: (round(w[1]), w[0]))
    rows: list[list] = []
    for w in words:
        if rows and abs(rows[-1][0][1] - w[1]) < 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    hits = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        line, spans = "", []
        for w in row:
            if line:
                line += " "
            spans.append((len(line), len(line) + len(w[4]), w)); line += w[4]
        start = line.find(phrase)
        while start >= 0:
            end = start + len(phrase)
            cov = [w for a, b, w in spans if a < end and b > start]
            r = pdfdoc.Rect(cov[0][:4])
            for w in cov:
                r |= pdfdoc.Rect(w[:4])
            hits.append(r)
            start = line.find(phrase, end)
    return hits


def min_pixel(src, clip, page=0, zoom=1.0) -> int:
    """Darkest grayscale value inside `clip` (display coords) - < 255 means something was drawn there."""
    img = pdfdoc.render_image(_data(src), page, zoom).convert("L")
    x0, y0, x1, y1 = clip
    c = img.crop((int(x0 * zoom), int(y0 * zoom), int(x1 * zoom), int(y1 * zoom)))
    return min(c.get_flattened_data() if hasattr(c, "get_flattened_data") else c.getdata())


class PageView:
    def __init__(self, data, i):
        self.data, self.i = data, i

    def get_text(self):
        return text(self.data, self.i)

    def search_for(self, s):
        return search_for(self.data, s, self.i)

    def widgets(self):
        return widgets(self.data, self.i)

    def get_images(self):
        return [None] * image_count(self.data, self.i)

    def min_pixel(self, clip):
        return min_pixel(self.data, clip, self.i)


class Opened:
    """`with Opened(pdf_bytes_or_path) as d: d[0].get_text()` - read-only views for assertions."""

    def __init__(self, src):
        self.data = _data(src)
        self.page_count = len(PdfReader(io.BytesIO(self.data)).pages)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def __getitem__(self, i):
        return PageView(self.data, i % self.page_count)
