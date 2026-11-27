"""Real-browser regression for date choices, typed ink and signed-file actions."""
import base64
import io
import json
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image

from gotoquill import offline
from tests.e2e.test_offline_drawn import chrome, http_files  # noqa: F401


@pytest.mark.parametrize('delivery',['offline','local'])
def test_date_choice_preview_stamp_download_and_share(env,pdf_file,tmp_path,chrome,delivery):
    request=(offline.create_file_request if delivery=='offline' else env.request)(
        pdf_path=str(pdf_file),add_date=True,date_format='YYYY-MM-DD',signer_name='Dana Cohen')
    url=Path(request['html_path']).as_uri() if delivery=='offline' else request['sign_url']
    context=chrome.new_context(locale='he-IL',timezone_id='Asia/Jerusalem',is_mobile=True,has_touch=True)
    # Keep time at the Jerusalem date boundary without advancing the server clock.
    context.add_init_script("""
      const OriginalDate=Date;
      window.Date=class extends OriginalDate {constructor(...a){super(...(a.length?a:['2026-11-26T22:30:00Z']));} static now(){return new OriginalDate('2026-11-26T22:30:00Z').getTime();}};
      Object.defineProperty(navigator,'canShare',{value:({files})=>files.length===1});
      Object.defineProperty(navigator,'share',{value:async({files})=>{window.shared={name:files[0].name,type:files[0].type,bytes:Array.from(new Uint8Array(await files[0].arrayBuffer()))};}});
    """)
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url);page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert page.locator('#datePreview').inner_text()=='תאריך: 2026-11-27'
    assert 'אמריקאית' in page.locator('#americanDateText').inner_text()
    page.check('#americanDate')
    assert page.locator('#datePreview').inner_text()=='תאריך: 11/27/2026'
    page.reload();page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert page.locator('#americanDate').is_checked()
    page.uncheck('#americanDate')
    assert page.locator('#datePreview').inner_text()=='תאריך: 27/11/2026'
    page.click('#tabType');page.fill('#typed','Dana Cohen');page.check('#consent')
    # Crossing midnight during review must preserve the date the signer actually saw.
    page.evaluate("() => {const Before=Date; window.Date=class extends Before {constructor(...a){super(...(a.length?a:['2026-11-27T22:30:00Z']));}};}")
    page.click('#submit')
    page.wait_for_selector('#done:not(.hidden)' if delivery=='offline' else '#closed.signed')
    if delivery=='local':
        result=env.status(request['request_id'],wait_seconds=10)
        assert result['status']=='completed' and not result['page_running']
    with page.expect_download() as download:
        page.click('#downloadPdf')
    path=tmp_path/'Downloaded signed.pdf';download.value.save_as(path)
    with pdfplumber.open(path) as doc:
        assert '27/11/2026' in doc.pages[0].extract_text()
        image=doc.pages[0].images[0]
        assert image['width']>0 and image['height']>0
    page.click('#sharePdf')
    page.wait_for_function('() => window.shared')
    assert bytes(page.evaluate('window.shared.bytes'))==path.read_bytes()
    assert page.evaluate('window.shared.type')=='application/pdf'
    if delivery=='offline':
        with page.expect_download() as receipt:
            page.click('#download')
        reply=tmp_path/'Synthetic signature.gotoquill';receipt.value.save_as(reply)
        response=json.loads(reply.read_text())
        assert response['date_format']=='DD/MM/YYYY' and response['date_text']=='27/11/2026'
        raw=base64.b64decode(response['signature_png'].split(',')[1])
        image=Image.open(io.BytesIO(raw))
        assert image.getchannel('A').getbbox()==(0,0,image.width,image.height)
        applied=offline.apply_signature_response(request['request_id'],response_path=str(reply))
        with pdfplumber.open(path) as browser, pdfplumber.open(applied['output_path']) as server:
            bi,si=browser.pages[0].images[0],server.pages[0].images[0]
            for key in ('x0','top','width','height'):
                assert bi[key]==pytest.approx(si[key],abs=.02)
    else:
        assert path.read_bytes()==Path(result['output_path']).read_bytes()
    assert not errors
    context.close()


@pytest.mark.parametrize('locale,fmt,expected',[('he-IL',None,False),('en-US',None,True),('en-US','DD/MM/YYYY',False)])
def test_default_and_remembered_date_choice(env,pdf_file,tmp_path,chrome,http_files,locale,fmt,expected):
    create=lambda:offline.create_file_request(pdf_path=str(pdf_file),date_format=fmt,html_path=str(tmp_path/'sign.html'))
    create()
    context=chrome.new_context(locale=locale)
    page=context.new_page();page.goto(http_files+'/sign.html');page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert page.locator('#americanDate').is_checked()==expected
    page.locator('#americanDate').set_checked(not expected)
    create()  # new request on the same origin remembers the signer's choice
    page.reload();page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert page.locator('#americanDate').is_checked()!=expected
    context.close()


def test_local_remembers_across_request_ports(env,pdf_file,chrome):
    context=chrome.new_context(locale='he-IL')
    first=env.request(pdf_path=str(pdf_file))
    page=context.new_page();page.goto(first['sign_url']);page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert not page.locator('#americanDate').is_checked()
    page.check('#americanDate')
    second=env.request(pdf_path=str(pdf_file),date_format='DD/MM/YYYY')
    assert first['sign_url'].split('/')[2]!=second['sign_url'].split('/')[2]
    page.goto(second['sign_url']);page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert page.locator('#americanDate').is_checked()
    context.close()


def test_unavailable_or_invalid_storage_does_not_block_signing(env,pdf_file,chrome):
    request=offline.create_file_request(pdf_path=str(pdf_file))
    context=chrome.new_context(locale='he-IL')
    page=context.new_page()
    page.add_init_script("Storage.prototype.getItem=()=> '__proto__'; Storage.prototype.setItem=()=>{throw new Error('blocked');};")
    page.goto(Path(request['html_path']).as_uri());page.wait_for_selector('#pages button.box');page.click('#heroOpen')
    assert not page.locator('#americanDate').is_checked()
    page.check('#americanDate')
    assert page.locator('#americanDate').is_checked()
    page.click('#tabType');page.fill('#typed','Dana Cohen');page.check('#consent');page.click('#submit')
    page.wait_for_selector('#done:not(.hidden)')
    context.close()
