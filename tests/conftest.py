import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))


@pytest.fixture(autouse=True)
def fake_relay(monkeypatch):
    """Never touch the real ntfy.sh from unit tests."""
    from gotoquill import relay
    r = relay.MemoryRelay()
    relay.set_relay(r)
    monkeypatch.setenv("GOTOQUILL_PAGE_URL", "https://pages.test/gotoquill/")
    monkeypatch.setenv("GOTOQUILL_PAGE_CHECK", "0")  # no network; tests opt in and mock urlopen
    yield r
    relay.set_relay(None)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("GOTOQUILL_NO_KEYRING", "1")  # tests that need a keychain install a fake one
    from gotoquill import core, local
    from gotoquill.config import Settings, set_settings
    s = Settings(data_dir=tmp_path / "data", open_browser=False)
    set_settings(s)
    core.reset_service(s)
    signer = local.reset_signer()
    yield signer
    signer.shutdown()


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    from gotoquill.api import create_app
    return TestClient(create_app())


@pytest.fixture()
def sample_pdf(tmp_path):
    from make_sample_pdf import make
    return make(tmp_path / "sample.pdf")


@pytest.fixture()
def pdf_file(tmp_path, sample_pdf):
    p = tmp_path / "docs" / "contract.pdf"
    p.parent.mkdir()
    p.write_bytes(sample_pdf)
    return p
