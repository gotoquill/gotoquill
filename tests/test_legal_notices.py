from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["web/index.html", "gotoquill/static/sign.html", "gotoquill/static/offline.html"]


def test_signing_pages_show_as_is_notice():
    for p in PAGES:
        assert "provided as is; it is not legal advice" in (ROOT / p).read_text(), p


def test_disclaimer_files_present():
    d = (ROOT / "DISCLAIMER.md").read_text().lower()
    for s in ("as is", "not legal advice", "eidas", "esign", "ueta", "ntfy.sh", "solely responsible"):
        assert s in d
    assert "## Disclaimer" in (ROOT / "README.md").read_text()
    lic = (ROOT / "LICENSE").read_text()
    assert "Disclaimer of Warranty" in lic and "Limitation of Liability" in lic


def test_default_consent_mentions_electronic_signing():
    from gotoquill.config import Settings
    assert "electronically" in Settings().consent_text


def test_signing_pages_link_privacy():
    for p in PAGES[:2]:
        assert 'href="https://gotoquill.com/privacy/#local"' in (ROOT / p).read_text(), p
    # The offline file has no network dependency, but people may deliberately open the notice.
    assert 'href="https://gotoquill.com/privacy/"' in (ROOT / PAGES[2]).read_text()


def test_local_signer_notice_precedes_signing_action_on_every_route():
    for p in PAGES:
        text = (ROOT / p).read_text()
        notice = text.index('id="signerPrivacyNotice"')
        assert notice < text.index('<button id="submit"'), p
        assert "Shay Levi, the developer, does not receive them through Local" in text, p
        assert 'lang="he" dir="rtl"' in text, p
        assert 'href="https://gotoquill.com/privacy/he/"' in text, p
        assert "cannot sign here without them" in text, p
