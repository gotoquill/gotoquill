from pathlib import Path
from unittest.mock import Mock

import pytest
from gotoquill import cli, placement, offline
from pdfmake import Doc


@pytest.fixture
def two_roles(tmp_path):
    doc = Doc(); page = doc.new_page()
    # Intentionally insert in reverse order: numbering follows page geometry.
    for name, y in [('Witness', 600), ('Client', 300)]:
        page.text_field(name+'Signature', (60, y, 260, y+40))
        page.text_field(name+'Date', (350, y+10, 470, y+30))
    p = tmp_path/'two.pdf'; p.write_bytes(doc.tobytes())
    return p


def test_list_without_request(two_roles, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError('must not create request'))
    monkeypatch.setattr(offline, 'create_file_request', factory)
    cli.main(['sign', str(two_roles), '--list-spots', '--file-mode'])
    assert capsys.readouterr().out.splitlines() == ['1. Page 1: ClientSignature', '2. Page 1: WitnessSignature']
    factory.assert_not_called()


@pytest.mark.parametrize('option', [None, '', '0', '3', '1,no', 'invalid'])
def test_cli_requires_choice_and_validates(two_roles, option, capsys):
    args = ['sign', str(two_roles), '--file-mode']
    if option is not None:
        args += ['--spots', option]
    with pytest.raises(SystemExit) as e:
        cli.main(args)
    assert e.value.code == 2
    assert 'spots' in capsys.readouterr().err or option is not None


@pytest.mark.parametrize('branch', ['page', 'file', 'link', 'link-file'])
@pytest.mark.parametrize('spots', ['first', 'last', 'all', '1,2'])
def test_cli_forwards_spots(two_roles, monkeypatch, capsys, branch, spots):
    from gotoquill import local, sealed, tools
    factory = Mock(return_value={'request_id':'req_test', 'html_path':'Synthetic sign.html',
                                 'expires_at':'tomorrow', 'sign_url':'http://localhost/test'})
    signer = Mock()
    signer.request = factory
    signer.wait.return_value = signer.status.return_value = {'status':'completed'}
    monkeypatch.setattr(local, 'get_signer', lambda: signer)
    monkeypatch.setattr(offline, 'create_file_request', factory)
    monkeypatch.setattr(sealed, 'create_sealed_request', factory)
    monkeypatch.setattr(tools, 'attach_hooks', Mock())
    flags = {'page':[], 'file':['--file-mode'], 'link':['--link','--no-wait'],
             'link-file':['--link-file','--no-wait']}[branch]
    if branch == 'page':
        with pytest.raises(SystemExit) as e:
            cli.main(['sign', str(two_roles), '--spots', spots, *flags])
        assert e.value.code == 0
    else:
        cli.main(['sign', str(two_roles), '--spots', spots, *flags])
    assert factory.call_args.kwargs['spots'] == spots
    capsys.readouterr()


@pytest.mark.parametrize('spots,role', [('first','Client'),('last','Witness')])
def test_dates_belong_to_selected_role(two_roles, spots, role):
    ps, _ = placement.plan(two_roles.read_bytes(), None, add_date=True, spots=spots)
    assert [p['field_name'] for p in ps] == [role+'Signature', role+'Date']
    from gotoquill import pdf
    plan = pdf.stamp_plan(two_roles.read_bytes(), [dict(p, add_date=True) for p in ps])
    assert {r['name'] for r in plan['remove_widgets']} == {role+'Signature', role+'Date'}


@pytest.mark.parametrize('source,expected', [('Contract.pdf','Contract'),('Contract','Contract'),
                                             ('sample_contract.PDF','Sample contract'),('a__b.pdf','A b')])
def test_friendly_filenames(source, expected):
    name = offline.friendly_name(source)
    assert name+' signed.pdf' == expected+' signed.pdf'
    assert name+' signature.gotoquill' == expected+' signature.gotoquill'
    assert '_' not in name
