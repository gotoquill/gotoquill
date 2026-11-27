"""Drawn capture regression: actual Chrome pointer/touch events through heroClose."""
import base64
import functools
import hashlib
import io
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

from gotoquill import offline, pdf
from gotoquill.core import _decode_png
from tests.test_file_mode import page_data

CHROME = '/usr/bin/google-chrome'


@pytest.fixture
def chrome():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
        yield browser
        browser.close()


@pytest.fixture
def http_files(tmp_path):
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join()


def draw(page, mobile=False):
    page.click('#heroOpen')
    page.wait_for_selector('#heroSheet #pad', state='visible')
    page.wait_for_timeout(400)
    box = page.locator('#pad').bounding_box()
    points = [(box['x']+box['width']*x, box['y']+box['height']*y)
              for x, y in [(0.15, .6), (.25, .3), (.35, .65), (.45, .35), (.6, .55), (.8, .4)]]
    if mobile:
        cdp = page.context.new_cdp_session(page)
        for i, (x, y) in enumerate(points):
            cdp.send('Input.dispatchTouchEvent', {'type': 'touchStart' if i == 0 else 'touchMove',
                                                'touchPoints': [{'x': x, 'y': y}]})
        cdp.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
        cdp.detach()
    else:
        page.mouse.move(*points[0]); page.mouse.down()
        for point in points[1:]:
            page.mouse.move(*point, steps=5)
        page.mouse.up()


def ink_difference(original, signed, rect):
    before = Image.open(io.BytesIO(pdf.render_page_png(original, 1, 612))).convert('RGB')
    after = Image.open(io.BytesIO(pdf.render_page_png(signed, 1, 612))).convert('RGB')
    # Sample PDF width is 612 points.
    diff = ImageChops.difference(before, after).crop(tuple(map(int, rect)))
    assert sum(max(diff.getpixel((x, y))) > 40 for y in range(diff.height) for x in range(diff.width)) > 40


@pytest.mark.parametrize('dpr,mobile', [(1, False), (2, False), (2.625, True), (3, True)])
@pytest.mark.parametrize('protocol', ['file', 'http'])
@pytest.mark.parametrize('delivery', ['offline', 'local'])
def test_drawn_matrix(env, pdf_file, tmp_path, chrome, http_files, dpr, mobile, protocol, delivery):
    placements = [{'page': 1, 'x': 72, 'y': 580, 'width': 200, 'height': 58},
                  {'kind': 'date', 'page': 1, 'x': 340, 'y': 620, 'width': 150, 'height': 18,
                   'date_format': 'YYYY-MM-DD'}]
    if delivery == 'offline':
        req = offline.create_file_request(pdf_path=str(pdf_file), placements=placements)
        path = Path(req['html_path'])
        url = path.as_uri() if protocol == 'file' else http_files + '/' + str(path.relative_to(tmp_path))
    else:
        req = env.request(pdf_path=str(pdf_file), placements=placements)
        url = req['sign_url']
        if protocol == 'file':
            # Exercise the localhost template from disk, routing its API to the real local service.
            path = tmp_path / 'local.html'
            source = httpx.get(url).text
            import re
            source = re.sub(r'const base = [^;]+;', 'const base = '+json.dumps(url)+';', source)
            path.write_text(source)
            url = path.as_uri()
    ctx = chrome.new_context(viewport={'width': 390 if mobile else 1100, 'height': 844},
                             device_scale_factor=dpr, is_mobile=mobile, has_touch=mobile,
                             timezone_id='America/New_York', locale='en-GB')
    if delivery == 'local' and protocol == 'file':
        # Local API intentionally forbids file origins; route through the test HTTP client.
        def api(route):
            r = httpx.request(route.request.method, route.request.url,
                              content=route.request.post_data, headers={'Content-Type': 'application/json'})
            route.fulfill(status=r.status_code, body=r.content,
                          headers={'Content-Type': r.headers.get('content-type', 'application/json')})
        ctx.route(req['sign_url']+'/**', api)
    if delivery == 'offline' and protocol == 'file':
        ctx.set_offline(True)
    pg = ctx.new_page()
    errors = []; pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(url)
    pg.wait_for_selector('#pages button.box')
    pg.click('#heroOpen'); pg.check('#consent')
    assert pg.locator('#submit').is_disabled()  # consent alone never signs
    pg.keyboard.press('Escape')
    draw(pg, mobile)
    pg.check('#consent')
    pg.click('#submit')
    if delivery == 'offline':
        pg.wait_for_selector('#done:not(.hidden)')
        assert not pg.is_visible('#code')
        with pg.expect_download() as download:
            pg.click('#download')
        receipt = tmp_path / download.value.suggested_filename
        download.value.save_as(receipt)
        assert receipt.name == 'Contract signature.gotoquill'
        resp = json.loads(receipt.read_text())
        _decode_png(resp['signature_png'], 2_000_000)
        with pg.expect_download() as download:
            pg.click('#downloadPdf')
        browser_path = tmp_path / download.value.suggested_filename
        download.value.save_as(browser_path)
        assert browser_path.name == 'Contract signed.pdf'
        browser_bytes = browser_path.read_bytes()
        assert resp['browser_pdf_sha256'] == hashlib.sha256(browser_bytes).hexdigest()
        assert receipt.stat().st_size < 50000
        out = offline.apply_signature_response(req['request_id'], response_path=str(receipt))
        audit = out['audit']
        assert audit['browser_pdf_sha256'] == resp['browser_pdf_sha256']
        assert audit['python_pdf_sha256'] == hashlib.sha256(Path(out['output_path']).read_bytes()).hexdigest()
        ink_difference(pdf_file.read_bytes(), browser_bytes, (72, 580, 272, 638))
        # Both engines place the date's baseline and text at the same points.
        from gotoquill.pdfdoc import Document
        with Document.open(browser_bytes) as bd, Document.open(Path(out['output_path']).read_bytes()) as pd:
            import re
            bw = [w for w in bd[0].get_text('words') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', w[4])]
            pw = [w for w in pd[0].get_text('words') if re.fullmatch(r'\d{4}-\d{2}-\d{2}', w[4])]
            assert len(bw) == len(pw) == 1
            assert bw[0][:4] == pytest.approx(pw[0][:4], abs=.02)
        import pdfplumber
        with pdfplumber.open(io.BytesIO(browser_bytes)) as bd, pdfplumber.open(out['output_path']) as pd:
            bi, pi = bd.pages[0].images, pd.pages[0].images
            assert len(bi) == len(pi) == 1
            for key in ('x0', 'top', 'width', 'height'):
                assert bi[0][key] == pytest.approx(pi[0][key], abs=.02)
        from pypdf import PdfReader
        assert not PdfReader(io.BytesIO(browser_bytes)).get_fields()
        plan = page_data(path.read_text())['stamp_plan']
        assert [op['rect'] for op in plan['operations'] if op['kind'] in ('signature', 'date')] == [[72,580,272,638],[340,620,490,638]]
    else:
        pg.wait_for_selector('#closed.signed')
        out = env.status(req['request_id'], wait_seconds=10)
        assert out['status'] == 'completed'
    ink_difference(pdf_file.read_bytes(), Path(out['output_path']).read_bytes(), (72,580,272,638))
    assert not errors
    ctx.close()


@pytest.mark.parametrize('delivery', ['offline', 'local'])
def test_failed_export_keeps_ink_and_retries(env, pdf_file, chrome, delivery):
    req = (offline.create_file_request(pdf_path=str(pdf_file)) if delivery == 'offline'
           else env.request(pdf_path=str(pdf_file)))
    url = Path(req['html_path']).as_uri() if delivery == 'offline' else req['sign_url']
    pg = chrome.new_page()
    pg.goto(url); pg.wait_for_selector('#pages button.box')
    draw(pg)
    pg.check('#consent')
    before = pg.locator('#pad').evaluate('(c)=>c.toDataURL()')
    pg.evaluate("window.realExport=HTMLCanvasElement.prototype.toDataURL; HTMLCanvasElement.prototype.toDataURL=()=> 'data:,';")
    pg.click('#submit')
    pg.wait_for_function("document.getElementById('msg').textContent.includes('try again')")
    assert pg.is_visible('#pad')
    assert not pg.is_visible('#done' if delivery == 'offline' else '#closed')
    pg.evaluate('() => {HTMLCanvasElement.prototype.toDataURL=window.realExport;}')
    assert pg.locator('#pad').evaluate('(c)=>c.toDataURL()') == before
    pg.click('#submit')
    pg.wait_for_selector('#done:not(.hidden)' if delivery == 'offline' else '#closed.signed')


@pytest.mark.parametrize('rotation,date_format', [(0, 'DD/MM/YYYY'), (90, 'DD/MM/YYYY'), (270, 'DD/MM/YYYY'),
                                                  (0, 'YYYY-MM-DD')])
def test_crop_rotation_proof_and_role_dates(env, tmp_path, chrome, rotation, date_format):
    """Original page coordinates, crop offsets, typography and selected widgets survive both stamp engines."""
    from pdfmake import Doc
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import RectangleObject
    import pdfplumber
    doc = Doc(); p = doc.new_page(width=600, height=800)
    p.insert_text((60, 100), 'Synthetic role contract')
    for role, y in [('Client', 300), ('Witness', 600)]:
        p.text_field(role+'Signature', (60,y,260,y+40))
        p.text_field(role+'Date', (350,y+10,470,y+30))
    writer = PdfWriter(clone_from=io.BytesIO(doc.tobytes()))
    writer.pages[0].cropbox = RectangleObject((20,40,580,780))
    writer.pages[0].rotate(rotation)
    source = tmp_path/'Role contract.pdf'
    with source.open('wb') as f:
        writer.write(f)
    req = offline.create_file_request(pdf_path=str(source), spots='first', add_date=True, date_format=date_format)
    pg = chrome.new_page(locale='en-GB', timezone_id='Asia/Tokyo')
    pg.context.set_offline(True)
    pg.goto(Path(req['html_path']).as_uri()); pg.wait_for_selector('#pages button.box')
    pg.click('#heroOpen'); pg.click('#tabType'); pg.fill('#typed', 'Dana Synthetic Signer')
    pg.check('#signedBy'); pg.check('#consent'); pg.click('#submit')
    pg.wait_for_selector('#done:not(.hidden)')
    with pg.expect_download() as download:
        pg.click('#downloadPdf')
    browser_path = tmp_path/'Browser signed.pdf'; download.value.save_as(browser_path)
    with pg.expect_download() as download:
        pg.click('#download')
    receipt = tmp_path/'signature.gotoquill'; download.value.save_as(receipt)
    result = offline.apply_signature_response(req['request_id'], response_path=str(receipt))
    for path in [browser_path, Path(result['output_path'])]:
        reader = PdfReader(path)
        assert 'Signed by Dana Synthetic Signer' in reader.pages[0].extract_text()
        assert '(Asia/Tokyo)' in reader.pages[0].extract_text()
        fields = reader.get_fields()
        assert set(fields) == {'WitnessSignature', 'WitnessDate'}
        assert all(not f.get('/V') for f in fields.values())
    with pdfplumber.open(browser_path) as bd, pdfplumber.open(result['output_path']) as pd:
        bw, pw = bd.pages[0].extract_words(), pd.pages[0].extract_words()
        assert [w['text'] for w in bw] == [w['text'] for w in pw]
        for b, p in zip(bw, pw):
            for key in ['x0','x1','top','bottom']:
                assert b[key] == pytest.approx(p[key],abs=.03)
        bi, pi = bd.pages[0].images, pd.pages[0].images
        assert len(bi) == len(pi) == 1
        for key in ['x0','top','width','height']:
            assert bi[0][key] == pytest.approx(pi[0][key],abs=.02)
    pg.close()
