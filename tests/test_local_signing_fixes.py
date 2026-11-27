"""Numeric dates, centered ink, downloads and logical Hebrew spot numbering."""
import base64
import io
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber
import pytest
from PIL import Image, ImageDraw

from gotoquill import cli, offline, pdf, placement
from gotoquill.core import SignError
from gotoquill.labels import logical_label
from pdfmake import Doc, Opened, sig_png
from tests.test_file_mode import make_response, page_data
from tests.test_flow import sign_body


@pytest.mark.parametrize('locale,expected', [(None, '27/11/2026'), ('he-IL', '27/11/2026'),
    ('en-US', '11/27/2026'), ('en', '27/11/2026'), ('de-DE', '27/11/2026'), ('ja-JP', '27/11/2026')])
def test_numeric_date_at_jerusalem_midnight(sample_pdf, locale, expected):
    stamp = pdf.stamp(sample_pdf, [{'kind':'date','page':1,'x':100,'y':100,'width':150,'height':20}],
                      sig_png(), datetime(2026,11,26,22,30,tzinfo=timezone.utc), 'Dana Cohen', 'synthetic',
                      {'timezone':'Asia/Jerusalem','locale':locale})
    with Opened(stamp) as doc:
        assert expected in doc[0].get_text()


@pytest.mark.parametrize('fmt,text', [('DD/MM/YYYY','27/11/2026'), ('MM/DD/YYYY','11/27/2026'), ('YYYY-MM-DD','2026-11-27')])
def test_submitted_date_overrides_request_and_survives_apply(env, client, pdf_file, fmt, text):
    r=env.request(pdf_path=str(pdf_file), serve=False, add_date=True, date_format='YYYY-MM-DD')
    token=env.sessions[r['request_id']].sign_token
    response=client.post(f'/s/{token}/submit', json=sign_body(date_format=fmt,date_text=text))
    assert response.status_code==200
    downloaded=base64.b64decode(response.json()['signed_pdf_base64'])
    from gotoquill.core import get_service
    session=env.sessions[r['request_id']]
    applied=get_service().apply(r['request_id'],session.agent_token)
    assert downloaded==base64.b64decode(applied['signed_pdf_base64'])
    assert applied['audit']['date_text']==text
    # Rebuilding a deleted cache must still refresh the authoritative audit hash.
    get_service()._doc_path(r['request_id'],'signed.pdf').unlink()
    rebuilt=get_service().apply(r['request_id'],session.agent_token)
    assert rebuilt['audit']['signed_sha256']==pdf.sha256(base64.b64decode(rebuilt['signed_pdf_base64']))
    with Opened(downloaded) as doc:
        assert text in doc[0].get_text()


@pytest.mark.parametrize('fmt,text', [('DD/MM/YYYY','Nov 27, 2026'),('DD/MM/YYYY','31/02/2026'),
    ('MM/DD/YYYY','27/11/2026'),('YYYY-MM-DD','1800-01-01'),('YYYY-MM-DD','2101-01-01'),
    ('%B %d, %Y','November 27, 2026'),('DD/MM/YYYY','２７/１１/２０２６'),(None,'27/11/2026')])
def test_invalid_signer_dates_leave_pending(env, client, pdf_file, fmt, text):
    r=env.request(pdf_path=str(pdf_file),serve=False)
    token=env.sessions[r['request_id']].sign_token
    assert client.post(f'/s/{token}/submit',json=sign_body(date_format=fmt,date_text=text)).status_code in (400,422)
    assert env.status(r['request_id'])['status']=='pending'


def test_offline_date_choice_applied_and_invalid_rejected(env,pdf_file):
    r=offline.create_file_request(pdf_path=str(pdf_file),add_date=True,date_format='YYYY-MM-DD')
    data=page_data(Path(r['html_path']).read_text())
    with pytest.raises(SignError):
        offline.apply_signature_response(r['request_id'],response_obj=make_response(data,date_format='DD/MM/YYYY',date_text='31/02/2026'))
    out=offline.apply_signature_response(r['request_id'],response_obj=make_response(data,date_format='MM/DD/YYYY',date_text='11/27/2026'))
    with Opened(Path(out['output_path']).read_bytes()) as doc:
        assert '11/27/2026' in doc[0].get_text()


@pytest.mark.parametrize('factory', ['local','offline'])
def test_request_rejects_nonnumeric_format(env,pdf_file,factory):
    create=env.request if factory=='local' else offline.create_file_request
    with pytest.raises(SignError,match='date_format'):
        create(pdf_path=str(pdf_file),date_format='MMM DD, YYYY')


def test_python_centers_cropped_ink(sample_pdf):
    image=Image.new('RGBA',(400,160))
    ImageDraw.Draw(image).rectangle((15,100,114,119),fill=(11,26,74,255))
    raw=io.BytesIO();image.save(raw,'PNG')
    assert Image.open(io.BytesIO(pdf.trim_signature(raw.getvalue()))).size==(100,20)
    stamped=pdf.stamp(sample_pdf,[{'page':1,'x':100,'y':100,'width':200,'height':60}],raw.getvalue(),pdf.utcnow(),'Dana Cohen','synthetic')
    with pdfplumber.open(io.BytesIO(stamped)) as doc:
        image=doc.pages[0].images[0]
        assert image['x0']+image['width']/2==pytest.approx(200)
        assert image['top']+image['height']/2==pytest.approx(130)
        assert image['width']/image['height']==pytest.approx(5)
        assert image['width']<=196 and image['height']<=56


@pytest.mark.parametrize('text,expected', [('חתימת הנישום','חתימת הנישום'),('םושינה תמיתח','חתימת הנישום'),
    ('הנישום חתימת','חתימת הנישום'),('תמיתח םושינה','חתימת הנישום'),
    ('Dana Cohen 2026 םושינה תמיתח','Dana Cohen 2026 חתימת הנישום')])
def test_logical_label(text,expected):
    assert logical_label(text)==expected


def test_hebrew_pdf_signer_first_and_numbers_match(tmp_path,capsys):
    doc=Doc();page=doc.new_page()
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    for label,y in [('חתימת פקיד',200),('חתימת הנישום',400)]:
        page.draw_line((70,y),(250,y))
        page.insert_text((70,y+15),label[::-1],fontfile=font,fontsize=11)
    path=tmp_path/'Synthetic Hebrew.pdf';path.write_bytes(doc.tobytes())
    detected=placement.detect(path.read_bytes())['signature']
    assert len(detected)==2
    assert [s['label'] for s in detected]==['חתימת הנישום','חתימת פקיד']
    assert [s['role_hint'] for s in detected]==['signer?','official?']
    cli.main(['sign',str(path),'--list-spots'])
    lines=capsys.readouterr().out.splitlines()
    assert 'signer?' in lines[0] and 'חתימת הנישום' in lines[0]
    assert 'official?' in lines[1] and 'חתימת פקיד' in lines[1]
    for number in (1,2):
        planned,_=placement.plan(path.read_bytes(),None,spots=str(number))
        assert planned[0]['y']==detected[number-1]['y']


@pytest.mark.parametrize('fmt',list(pdf.DATE_FORMATS))
def test_cli_forwards_numeric_format(pdf_file,monkeypatch,capsys,fmt):
    from unittest.mock import Mock
    factory=Mock(return_value={'request_id':'req_test','html_path':'Synthetic.html','expires_at':'tomorrow'})
    monkeypatch.setattr(offline,'create_file_request',factory)
    cli.main(['sign',str(pdf_file),'--file-mode','--date-format',fmt])
    assert factory.call_args.kwargs['date_format']==fmt
    capsys.readouterr()


def test_mcp_request_tools_expose_numeric_formats():
    import asyncio
    from gotoquill.mcp_server import build_server
    async def check():
        tools={t.name:t for t in await build_server().list_tools()}
        for name in ('request_signature','sign_pdf','ui_submit_signature'):
            t=tools[name]
            schema=getattr(t,'input_schema',None) or getattr(t,'inputSchema',None) or t.parameters
            option=schema['properties']['date_format']
            assert set(option['anyOf'][0]['enum'])==set(pdf.DATE_FORMATS)
    asyncio.run(check())


@pytest.mark.parametrize('fmt',[[],{},False,17])
def test_malformed_date_format_is_validation_error(fmt):
    with pytest.raises(pdf.PdfError):
        pdf.validate_date_choice(fmt,'27/11/2026')
