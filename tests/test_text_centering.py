"""Measure visible stamped glyph bounds, not just the requested text origin."""
from datetime import datetime, timezone

import pypdfium2
import pytest

from gotoquill import pdf, pdfdoc
from pdfmake import Doc, sig_png


def assert_text_center(data, text, box):
    with pypdfium2.PdfDocument(data) as doc:
        page = doc[0]
        tp = page.get_textpage()
        try:
            content = tp.get_text_range()
            start = content.index(text)
            bounds = [tp.get_charbox(i) for i in range(start, start + len(text)) if not content[i].isspace()]
            left, bottom = min(b[0] for b in bounds), min(b[1] for b in bounds)
            right, top = max(b[2] for b in bounds), max(b[3] for b in bounds)
            x, y, w, h = box
            assert (left + right) / 2 == pytest.approx(x + w / 2, abs=1)
            assert page.get_height() - (bottom + top) / 2 == pytest.approx(y + h / 2, abs=1)
            pad = min(2, w / 8, h / 8)
            assert left >= x + pad - .1 and right <= x + w - pad + .1
            assert bottom >= page.get_height() - y - h + pad - .1
            assert top <= page.get_height() - y - pad + .1
        finally:
            tp.close()
            page.close()


@pytest.mark.parametrize('rtl', [False, True])
@pytest.mark.parametrize('size', [(150, 24), (45, 10), (20, 6)])
def test_date_glyphs_centered_on_ltr_and_hebrew_pages(rtl, size):
    doc = Doc(); page = doc.new_page()
    page.insert_text((60, 50), 'חתימת הנישום'[::-1] if rtl else 'Dana Cohen',
                     fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf' if rtl else None)
    box = (100, 100, *size)
    stamped = pdf.stamp(doc.tobytes(), [dict(kind='date', page=1, x=box[0], y=box[1], width=size[0], height=size[1], date_format='DD/MM/YYYY')],
                        sig_png(), datetime(2026, 11, 27, tzinfo=timezone.utc), 'Dana Cohen', 'synthetic', {'locale':'he-IL' if rtl else 'en-GB'})
    assert_text_center(stamped, '27/11/2026', box)


@pytest.mark.parametrize('text,font,cap', [('Dana Cohen','Helvetica',28), ('Gregory Young','Helvetica-Oblique',28), ('D.C.','Helvetica-Oblique',22)])
def test_boxed_text_accounts_for_visible_ascenders_descenders_and_bearings(text,font,cap):
    from gotoquill.text_layout import write_box_text
    doc=Doc();doc.new_page()
    with pdfdoc.Document.open(doc.tobytes()) as output:
        # Public only stamps typed signatures as centered, cropped PNGs.
        import inspect
        if font != 'Helvetica' and 'fontname' not in inspect.signature(output[0].insert_text).parameters:
            font='Helvetica'
        write_box_text(output[0],pdfdoc.Rect(100,100,300,150),text,cap,font)
        assert_text_center(output.tobytes(),text,(100,100,200,50))
