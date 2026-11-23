"""Small PDF document model on permissively licensed libraries.

- pdfplumber / pdfminer.six (MIT): words with positions, and vector drawings (rects, lines, curves)
- pypdf (BSD): form widgets (read, fill, remove), merging overlay pages, metadata, saving
- reportlab (BSD): draws the signature image, text and preview highlights onto an overlay page
- pypdfium2 (Apache-2.0 / BSD): renders pages to PNG

Coordinates used throughout gotoquill: PDF points, origin at the top-left of the page's CropBox, in the
*unrotated* page (y grows downwards). That is what placements, spots and widget rects are expressed in.
``page.rect`` is the unrotated CropBox (0, 0, width, height); ``page.display_size`` is the rotated size.
"""
from __future__ import annotations

import io
import threading
import logging
import re
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, NumberObject, TextStringObject, BooleanObject

logging.getLogger("pypdf").setLevel(logging.ERROR)  # repaired-xref chatter on real-world PDFs

WIDGET_TEXT = 7
WIDGET_SIGNATURE = 6
WIDGET_OTHER = 0
FONT = "Helvetica"


class Point:
    __slots__ = ("x", "y")

    def __init__(self, x, y=None):
        if y is None:
            x, y = x
        self.x, self.y = float(x), float(y)


class Rect:
    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, *a):
        if len(a) == 1:
            a = tuple(a[0])
        self.x0, self.y0, self.x1, self.y1 = (float(v) for v in a[:4])

    width = property(lambda s: s.x1 - s.x0)
    height = property(lambda s: s.y1 - s.y0)
    is_empty = property(lambda s: s.x0 >= s.x1 or s.y0 >= s.y1)
    tl = property(lambda s: Point(s.x0, s.y0))
    tr = property(lambda s: Point(s.x1, s.y0))
    bl = property(lambda s: Point(s.x0, s.y1))
    br = property(lambda s: Point(s.x1, s.y1))

    def __iter__(self):
        return iter((self.x0, self.y0, self.x1, self.y1))

    def __getitem__(self, i):
        return (self.x0, self.y0, self.x1, self.y1)[i]

    def __len__(self):
        return 4

    def __eq__(self, o):
        try:
            return tuple(self) == tuple(o)
        except TypeError:
            return False

    __hash__ = None

    def __repr__(self):
        return f"Rect({self.x0:.2f}, {self.y0:.2f}, {self.x1:.2f}, {self.y1:.2f})"

    def intersects(self, o) -> bool:
        o = o if isinstance(o, Rect) else Rect(o)
        if self.is_empty or o.is_empty:
            return False
        return self.x0 < o.x1 and o.x0 < self.x1 and self.y0 < o.y1 and o.y0 < self.y1

    def contains(self, o) -> bool:
        if isinstance(o, Point):
            return o in self
        o = o if isinstance(o, Rect) else Rect(o)
        return self.x0 <= o.x0 and o.x1 <= self.x1 and self.y0 <= o.y0 and o.y1 <= self.y1

    def __contains__(self, p):
        p = p if isinstance(p, Point) else Point(p)
        return self.x0 <= p.x < self.x1 and self.y0 <= p.y < self.y1

    def __or__(self, o):
        o = o if isinstance(o, Rect) else Rect(o)
        if self.is_empty:
            return Rect(o)
        if o.is_empty:
            return Rect(self)
        return Rect(min(self.x0, o.x0), min(self.y0, o.y0), max(self.x1, o.x1), max(self.y1, o.y1))

    def __and__(self, o):
        o = o if isinstance(o, Rect) else Rect(o)
        return Rect(max(self.x0, o.x0), max(self.y0, o.y0), min(self.x1, o.x1), min(self.y1, o.y1))


def text_length(text: str, fontsize: float) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    return stringWidth(text, FONT, fontsize)


def _rgb(c) -> tuple | None:
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c,)
    try:
        c = tuple(float(v) for v in c)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)  # pattern / named colour: treat as dark
    if len(c) == 1:
        return (c[0],) * 3
    if len(c) == 3:
        return c
    if len(c) == 4:
        k = c[3]
        return tuple((1 - v) * (1 - k) for v in c[:3])
    return (0.0, 0.0, 0.0)


_RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")


def _logical(text: str) -> str:
    """pdfplumber orders a word's characters left to right by position; Hebrew/Arabic reads right to left."""
    return text[::-1] if _RTL.search(text) else text


@dataclass
class Widget:
    field_name: str
    field_type: int
    field_value: str
    field_label: str | None
    rect: Rect
    _ref: object  # indirect reference of the widget annotation


def _inherited(obj, key):
    seen = 0
    while obj is not None and seen < 50:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return None


def _full_name(obj) -> str:
    parts, seen = [], 0
    while obj is not None and seen < 50:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
        seen += 1
    return ".".join(reversed(parts))


class Page:
    def __init__(self, doc: "Document", number: int):
        self.doc, self.number = doc, number
        self._wp = doc.writer.pages[number]
        cb = self._wp.cropbox
        mb = self._wp.mediabox
        self._cb = tuple(float(v) for v in (cb.left, cb.bottom, cb.right, cb.top))
        self._mb = tuple(float(v) for v in (mb.left, mb.bottom, mb.right, mb.top))
        self.rotation = int(self._wp.get("/Rotate", 0) or 0) % 360
        w, h = self._cb[2] - self._cb[0], self._cb[3] - self._cb[1]
        self.rect = Rect(0, 0, w, h)
        self.display_size = (h, w) if self.rotation in (90, 270) else (w, h)
        self._words = None
        self._drawings = None
        self._extra_words: list = []
        self._ops: list = []

    # ---------------------------------------------------------------- coordinates
    def to_user(self, x: float, y: float) -> tuple[float, float]:
        """gotoquill coords (unrotated, CropBox top-left) -> PDF user space (bottom-left origin)."""
        return self._cb[0] + x, self._cb[3] - y

    def from_user(self, X: float, Y: float) -> tuple[float, float]:
        return X - self._cb[0], self._cb[3] - Y

    def to_display(self, x: float, y: float) -> tuple[float, float]:
        """gotoquill coords -> coords on the page as displayed (rotation applied), top-left origin."""
        w, h = self.rect.width, self.rect.height
        return {0: (x, y), 90: (h - y, x), 180: (w - x, h - y), 270: (y, w - x)}[self.rotation]

    def from_display(self, x: float, y: float) -> tuple[float, float]:
        w, h = self.rect.width, self.rect.height
        return {0: (x, y), 90: (y, h - x), 180: (w - x, h - y), 270: (w - y, x)}[self.rotation]

    def rect_to_display(self, r: Rect) -> Rect:
        a, b = self.to_display(r.x0, r.y0), self.to_display(r.x1, r.y1)
        return Rect(min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    def _from_plumber(self, x0, top, x1, bottom) -> Rect:
        # pdfplumber (on the un-rotated copy): MediaBox top-left origin
        dx, dy = self._mb[0] - self._cb[0], self._cb[3] - self._mb[3]
        return Rect(x0 + dx, top + dy, x1 + dx, bottom + dy)

    # ---------------------------------------------------------------- reading
    def _plumber(self):
        return self.doc._plumber().pages[self.number]

    def _load(self):
        if self._words is not None:
            return
        pp = self._plumber()
        raw = []
        for w in pp.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=3):
            r = self._from_plumber(w["x0"], w["top"], w["x1"], w["bottom"])
            raw.append([r.x0, r.y0, r.x1, r.y1, _logical(w["text"])])
        # (block, line, word) numbers: a row of words, split where there is a wide gap
        raw.sort(key=lambda w: (round(w[1]), w[0]))
        rows: list[list] = []
        for w in raw:
            for row in rows:
                r0 = row[0]
                if abs(r0[1] - w[1]) <= 2.5 and abs(r0[3] - w[3]) <= 2.5:
                    row.append(w)
                    break
            else:
                rows.append([w])
        out, line_no = [], 0
        for row in rows:
            row.sort(key=lambda w: w[0])
            prev, wn = None, 0
            for w in row:
                gap_limit = max(10.0, 1.2 * (w[3] - w[1]))
                if prev is not None and w[0] - prev[2] > gap_limit:
                    line_no += 1; wn = 0
                out.append((w[0], w[1], w[2], w[3], w[4], 0, line_no, wn))
                prev, wn = w, wn + 1
            line_no += 1
        self._words = out
        self._drawings = self._read_drawings(pp)

    def _read_drawings(self, pp) -> list[dict]:
        out = []
        for o in pp.rects:
            r = self._from_plumber(o["x0"], o["top"], o["x1"], o["bottom"])
            fill = _rgb(o.get("non_stroking_color")) if o.get("fill") else None
            if o.get("fill") and fill is None:
                fill = (0.0, 0.0, 0.0)
            out.append({"items": [("re", r)], "fill": fill, "rect": r})
        for o in pp.lines:
            pts = o.get("pts") or [(o["x0"], o["top"]), (o["x1"], o["bottom"])]
            out.append(self._path(pts, None))
        for o in pp.curves:
            fill = _rgb(o.get("non_stroking_color")) if o.get("fill") else None
            out.append(self._path(o.get("pts") or [], fill))
        return [d for d in out if d]

    def _path(self, pts, fill) -> dict | None:
        P = [Point(*self._from_plumber(x, y, x, y)[:2]) for x, y in pts]
        if not P:
            return None
        xs, ys = [p.x for p in P], [p.y for p in P]
        bb = Rect(min(xs), min(ys), max(xs), max(ys))
        # an axis-aligned closed 4-corner path is a rectangle
        corners = {(round(p.x, 1), round(p.y, 1)) for p in P}
        if len(P) in (4, 5) and len(corners) == 4 and all(
                (round(bb.x0, 1) in (cx,) or round(bb.x1, 1) in (cx,)) and (round(bb.y0, 1) in (cy,) or round(bb.y1, 1) in (cy,))
                for cx, cy in corners):
            return {"items": [("re", bb)], "fill": fill, "rect": bb}
        items = [("l", a, b) for a, b in zip(P, P[1:])]
        return {"items": items, "fill": fill, "rect": bb}

    def get_text(self, kind: str = "text"):
        self._load()
        words = self._words + self._extra_words
        if kind == "words":
            return list(words)
        return " ".join(w[4] for w in words)

    def get_drawings(self) -> list[dict]:
        self._load()
        return list(self._drawings)

    def widgets(self) -> list[Widget]:
        out = []
        for ref in self._wp.get("/Annots") or []:
            a = ref.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            ft = _inherited(a, "/FT")
            t = WIDGET_TEXT if ft == "/Tx" else WIDGET_SIGNATURE if ft == "/Sig" else WIDGET_OTHER
            v = _inherited(a, "/V")
            tu = _inherited(a, "/TU")
            X0, Y0, X1, Y1 = (float(v_) for v_ in a.get("/Rect", [0, 0, 0, 0]))
            (x0, y0), (x1, y1) = self.from_user(min(X0, X1), max(Y0, Y1)), self.from_user(max(X0, X1), min(Y0, Y1))
            out.append(Widget(_full_name(a), t, "" if v is None or t != WIDGET_TEXT else str(v),
                              str(tu) if tu is not None else None, Rect(x0, y0, x1, y1), ref))
        return out

    # ---------------------------------------------------------------- writing
    def delete_widget(self, w: Widget) -> None:
        annots = self._wp.get("/Annots")
        if annots is not None:
            annots = annots.get_object()
            for i, ref in enumerate(list(annots)):
                if ref.get_object() is w._ref.get_object():
                    del annots[i]
                    break
        self.doc._remove_field(w._ref.get_object())

    def set_widget_value(self, w: Widget, text: str) -> None:
        a = w._ref.get_object()
        field = a if "/T" in a or "/Parent" not in a else a["/Parent"].get_object()
        field[NameObject("/V")] = TextStringObject(text)
        self.doc._need_appearances = True
        try:
            self.doc.writer.update_page_form_field_values(self._wp, {w.field_name: text}, auto_regenerate=False)
        except Exception:  # noqa: BLE001 - /V is set; viewers regenerate with NeedAppearances
            pass
        w.field_value = text

    def insert_text(self, point, text: str, fontsize: float = 11, color=(0, 0, 0)) -> None:
        x, y = point
        self._ops.append(("text", (float(x), float(y)), text, float(fontsize), color))
        tw = text_length(text, fontsize)
        self._extra_words.append((x, y - fontsize * 0.93, x + tw, y + fontsize * 0.22, text, 1, 10 ** 6 + len(self._ops), 0))

    def insert_image(self, rect: Rect, png: bytes) -> None:
        self._ops.append(("image", Rect(rect), png))

    def draw_rect(self, rect: Rect, color=None, fill=None, width: float = 1, fill_opacity: float = 1,
                  dashes: tuple | None = None) -> None:
        self._ops.append(("rect", Rect(rect), color, fill, float(width), float(fill_opacity), dashes))

    def _overlay(self) -> bytes | None:
        if not self._ops:
            return None
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(max(1.0, self._mb[2]), max(1.0, self._mb[3])))
        # gotoquill coords (unrotated, CropBox top-left, y down) -> PDF user space. Like the page's own content,
        # what we draw is turned with the page's /Rotate when displayed.
        M = (1, 0, 0, -1, self._cb[0], self._cb[3])
        for op in self._ops:
            c.saveState()
            c.transform(*M)
            if op[0] == "text":
                _, (x, y), text, fs, color = op
                c.translate(x, y); c.scale(1, -1)
                c.setFillColorRGB(*color); c.setFont(FONT, fs)
                c.drawString(0, 0, text)
            elif op[0] == "image":
                r = op[1]
                img = ImageReader(io.BytesIO(op[2]))
                iw, ih = img.getSize()
                s = min(r.width / iw, r.height / ih)
                w, h = iw * s, ih * s
                x0, y0 = r.x0 + (r.width - w) / 2, r.y0 + (r.height - h) / 2
                c.translate(x0, y0 + h); c.scale(1, -1)
                c.drawImage(img, 0, 0, w, h, mask="auto")
            else:
                _, r, color, fill, width, fop, dashes = op
                if fill is not None:
                    c.setFillColorRGB(*fill); c.setFillAlpha(fop)
                if color is not None and width > 0:
                    c.setStrokeColorRGB(*color); c.setLineWidth(width)
                    if dashes:
                        c.setDash(*dashes)
                c.rect(r.x0, r.y0, r.width, r.height, stroke=int(color is not None and width > 0),
                       fill=int(fill is not None))
            c.restoreState()
        c.showPage(); c.save()
        return buf.getvalue()


class Document:
    def __init__(self, data: bytes):
        self._data = data
        reader = PdfReader(io.BytesIO(data))
        self.needs_pass = False
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001
                ok = 0
            if not ok:
                self.needs_pass = True
        self.reader = reader
        self.writer = PdfWriter(clone_from=reader) if not self.needs_pass else PdfWriter()
        self._pages: dict[int, Page] = {}
        self._pl = None
        self._need_appearances = False

    @classmethod
    def open(cls, data_or_path) -> "Document":
        if not isinstance(data_or_path, (bytes, bytearray)):
            with open(data_or_path, "rb") as f:
                data_or_path = f.read()
        return cls(bytes(data_or_path))

    @property
    def page_count(self) -> int:
        return len(self.writer.pages) if not self.needs_pass else len(self.reader.pages)

    def __len__(self):
        return self.page_count

    def __getitem__(self, i: int) -> Page:
        n = self.page_count
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError("page out of range")
        if i not in self._pages:
            self._pages[i] = Page(self, i)
        return self._pages[i]

    def __iter__(self):
        for i in range(self.page_count):
            yield self[i]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def close(self):
        if self._pl is not None:
            self._pl.close(); self._pl = None

    @property
    def metadata(self) -> dict:
        return dict(self.reader.metadata or {})

    def _plumber(self):
        if self._pl is None:
            import pdfplumber
            data = self._data
            if any(int(p.get("/Rotate", 0) or 0) % 360 for p in self.reader.pages) or self.reader.is_encrypted:
                w = PdfWriter(clone_from=self.reader)
                for p in w.pages:
                    p[NameObject("/Rotate")] = NumberObject(0)
                b = io.BytesIO(); w.write(b); data = b.getvalue()
            self._pl = pdfplumber.open(io.BytesIO(data))
        return self._pl

    def _remove_field(self, annot) -> None:
        root = self.writer._root_object
        af = root.get("/AcroForm")
        if af is None:
            return
        af = af.get_object()
        node = annot
        while node is not None:
            parent = node.get("/Parent")
            container = parent.get_object().get("/Kids") if parent is not None else af.get("/Fields")
            if container is None:
                return
            container = container.get_object()
            for i, ref in enumerate(list(container)):
                if ref.get_object() is node:
                    del container[i]
                    break
            if parent is None or len(container):
                return
            node = parent.get_object()

    def tobytes(self, metadata: dict | None = None) -> bytes:
        for page in self._pages.values():
            ov = page._overlay()
            if ov:
                page._wp.merge_page(PdfReader(io.BytesIO(ov)).pages[0])
                page._ops = []
        if self._need_appearances and "/AcroForm" in self.writer._root_object:
            self.writer._root_object["/AcroForm"].get_object()[NameObject("/NeedAppearances")] = BooleanObject(True)
        if metadata is not None:
            self.writer.add_metadata(metadata)
        for p in self.writer.pages:
            try:
                p.compress_content_streams()
            except Exception:  # noqa: BLE001
                pass
        buf = io.BytesIO()
        self.writer.write(buf)
        return buf.getvalue()


def render_png(data: bytes, index: int, zoom: float, crop: Rect | None = None, page: Page | None = None) -> bytes:
    """Render page `index` (0-based) as displayed (rotation applied). `crop` is in display coords (points)."""
    img = render_image(data, index, zoom)
    if crop is not None:
        img = img.crop((int(crop.x0 * zoom), int(crop.y0 * zoom), int(round(crop.x1 * zoom)), int(round(crop.y1 * zoom))))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


_PDFIUM_LOCK = threading.Lock()  # PDFium is not thread-safe; the local server renders from worker threads


def render_image(data: bytes, index: int, zoom: float):
    import pypdfium2 as pdfium
    with _PDFIUM_LOCK:
        return _render_image(pdfium, data, index, zoom)


def _render_image(pdfium, data: bytes, index: int, zoom: float):
    doc = pdfium.PdfDocument(data)
    try:
        doc.init_forms()
        p = doc[index]
        bmp = p.render(scale=zoom, may_draw_forms=True)
        img = bmp.to_pil().convert("RGB")
        p.close()
        return img
    finally:
        doc.close()
