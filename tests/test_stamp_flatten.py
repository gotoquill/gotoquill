"""Poppler regression: used blue AcroForm appearances must not hide stamped ink."""
import io
import subprocess
from datetime import datetime, timezone

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas

from gotoquill.pdf import stamp


@pytest.mark.parametrize('mode', ['named', 'coordinates', 'automatic-date'])
def test_blue_widgets_removed_and_ink_fits(tmp_path, mode):
    buf = io.BytesIO()
    canvas = Canvas(buf, pagesize=(612, 792))
    boxes = [('Signature', 40, 80, 208, 22), ('Date', 280, 80, 65, 10)]
    for name, x, y, width, height in boxes + [('Other', 40, 250, 80, 22)]:
        canvas.acroForm.textfield(name=name, x=x, y=792-y-height, width=width, height=height,
                                  fillColor=Color(.8, .843, 1), borderWidth=0)
    canvas.showPage()
    canvas.save()
    image = Image.new('RGBA', (100, 30), (255, 255, 255, 0))
    ImageDraw.Draw(image).line([(2, 25), (20, 3), (35, 24), (65, 8), (97, 20)], fill=(10, 20, 40), width=3)
    png = io.BytesIO()
    image.save(png, format='PNG')
    placements = [dict(field_name=name, kind='date' if name == 'Date' else 'signature', date_format='%b %d, %Y')
                  for name, *_ in boxes]
    if mode == 'coordinates':
        placements = [dict(kind='date' if name == 'Date' else 'signature', page=1, x=x, y=y, width=w, height=h,
                           date_format='%b %d, %Y') for name, x, y, w, h in boxes]
    if mode == 'automatic-date':
        placements = [dict(placements[0], add_date=True, proof_line=False)]
    signed = stamp(buf.getvalue(), placements, png.getvalue(), datetime(2026, 11, 1, tzinfo=timezone.utc),
                   'Alex Morgan', 'visual-regression')
    reader = PdfReader(io.BytesIO(signed))
    assert set(reader.get_fields()) == {'Other'}
    assert len(reader.pages[0]['/Annots']) == 1
    path = tmp_path / 'signed.pdf'
    path.write_bytes(signed)
    subprocess.run(['pdftoppm', '-r', '72', '-singlefile', str(path), str(tmp_path / 'page')], check=True)
    with Image.open(tmp_path / 'page.ppm') as rendered:
        for name, x, y, w, h in boxes:
            pixels = list(rendered.crop((x, y, x+w, y+h)).convert('RGB').getdata())
            assert sum(max(pixel) < 180 for pixel in pixels) > 5, name
            assert not any(b > 230 and r > 180 and b-r > 20 for r, g, b in pixels), name
            # Ink must stay within the field, even in the short, narrow date box.
            for strip in [(x-2,y-2,x+w+2,y), (x-2,y+h,x+w+2,y+h+2),
                          (x-2,y,x,y+h), (x+w,y,x+w+2,y+h)]:
                assert not any(max(p) < 180 for p in rendered.crop(strip).convert('RGB').getdata()), name
