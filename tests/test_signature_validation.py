"""Reject PNGs without visible ink in the shared browser guard and Python boundary."""
import base64
import io
import struct
import zlib
from pathlib import Path

import pytest
from PIL import Image
from gotoquill.core import SignError, _decode_png


def png(color):
    out = io.BytesIO()
    Image.new('RGBA', (8, 8), color).save(out, 'PNG')
    return out.getvalue()


def invalid_pngs():
    zero = bytearray(png('black'))
    zero[16:20] = struct.pack('>I', 0)
    zero[29:33] = struct.pack('>I', zlib.crc32(zero[12:29]))
    return [png((0, 0, 0, 0)), png('white'), bytes(zero), png('black')[:40], b'\x89PNG\r\n\x1a\ninvalid']


@pytest.mark.parametrize('raw', invalid_pngs(), ids=['transparent','white','zero','truncated','corrupt'])
def test_python_rejects_empty_or_corrupt(raw):
    with pytest.raises(SignError):
        _decode_png(base64.b64encode(raw).decode(), 1_000_000)


def test_python_accepts_visible_ink_and_checks_limit():
    raw = png('black')
    assert _decode_png(base64.b64encode(raw).decode(), len(raw)) == raw
    with pytest.raises(SignError):
        _decode_png(base64.b64encode(raw).decode(), len(raw)-1)


def capture_block(path):
    text = Path(path).read_text()
    return text[text.index('// signature-capture:start'):text.index('// signature-capture:end')]


def test_capture_guards_are_shared():
    assert capture_block('gotoquill/static/offline.html') == capture_block('gotoquill/static/sign.html') == capture_block('web/sign.js')


def test_browser_validation_and_invalid_stroke_geometry():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
        pg = browser.new_page()
        pg.add_script_tag(content=capture_block('gotoquill/static/offline.html'))
        for raw in invalid_pngs():
            assert not pg.evaluate('validSignature', 'data:image/png;base64,'+base64.b64encode(raw).decode())
        for bad in ['data:,', '', 'data:image/png;base64,NaN']:
            assert not pg.evaluate('validSignature', bad)
        assert pg.evaluate('validSignature', 'data:image/png;base64,'+base64.b64encode(png('black')).decode())
        pg.add_script_tag(content="""
            var mode='draw', pad=document.createElement('canvas'), strokes=[], lastD=1;
            pad.width=300;pad.height=150;
            pad.getContext('2d').fillRect(0,0,300,150);
        """)
        for bad in ['NaN', 'Infinity']:
            pg.evaluate(f'strokes=[[{{x:{bad},y:0.5,p:0.5}}]]')
            assert pg.evaluate('sigPng()') == 'data:,'
        pg.evaluate('strokes=[[{x:0.5,y:0.5,p:0.5}]];pad.width=0')
        assert not pg.evaluate('async()=>validSignature(sigPng())')
        # A hidden layout still exports the real backing pixels.
        pg.evaluate('pad.width=300;pad.getContext("2d").fillRect(0,0,300,150)')
        assert pg.evaluate('async()=>validSignature(sigPng())')
        browser.close()


@pytest.mark.parametrize('raw', invalid_pngs(), ids=['transparent','white','zero','truncated','corrupt'])
def test_invalid_receipt_leaves_request_pending(env, pdf_file, raw):
    from gotoquill import offline
    from tests.test_file_mode import page_data, make_response
    req = offline.create_file_request(pdf_path=str(pdf_file))
    data = page_data(Path(req['html_path']).read_text())
    resp = make_response(data, signature_png=base64.b64encode(raw).decode())
    with pytest.raises(SignError):
        offline.apply_signature_response(req['request_id'], response_obj=resp)
    assert offline.status(req['request_id'])['status'] == 'pending'
    assert not Path(req['output_path']).exists()
    assert not Path(req['audit_path']).exists()


def test_browser_standard_date_formats_match_python():
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from playwright.sync_api import sync_playwright
    text = Path('gotoquill/static/offline.html').read_text()
    block = text[text.index('const SB_TOK'):text.index('// sbdate:end')]
    fmt = '%Y %y %C %m %d %e %H %I %M %S %f %p %a %A %b %B %j %w %u %U %W %G %g %V %z %Z %c %x %X %D %F %R %T %r %%'
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--no-sandbox'])
        for zone in ['America/New_York', 'Asia/Tokyo']:
            pg = browser.new_page(timezone_id=zone)
            pg.add_script_tag(content=block)
            for timestamp in ['2026-01-01T00:00:00Z','2026-12-31T18:23:45Z','2027-01-03T12:00:00Z','2026-07-12T15:30:00Z']:
                date = datetime.fromisoformat(timestamp.replace('Z','+00:00')).astimezone(ZoneInfo(zone))
                actual = pg.evaluate('([ts,fmt,tz])=>sbDate(new Date(ts),fmt,tz)',[timestamp,fmt,date.tzname()])
                assert actual == date.strftime(fmt)
            pg.close()
        browser.close()
