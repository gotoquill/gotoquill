import importlib.util, pathlib, sys, types

spec = importlib.util.spec_from_file_location("cm", pathlib.Path(__file__).parent.parent / "scripts" / "client_matrix.py")
cm = importlib.util.module_from_spec(spec); sys.modules["cm"] = cm; spec.loader.exec_module(cm)


def _sb(tmp_path, signed=True):
    p = tmp_path / "doc" / "sample contract - signed.pdf"
    p.parent.mkdir()
    if signed:
        p.write_bytes(b"%PDF")
    return types.SimpleNamespace(signed_pdf=lambda: p)


def test_inferred_wait_needs_real_file_and_path(tmp_path):
    sb = _sb(tmp_path)
    ok = f"The signature request has been completed.\nsigned_pdf_path: {sb.signed_pdf()}"
    assert cm.inferred_wait(ok, sb)
    assert not cm.inferred_wait("The request has been completed.", sb)          # no path
    assert not cm.inferred_wait(f"Request sent; file will be {sb.signed_pdf()}", sb)  # no completion claim


def test_inferred_wait_false_when_not_signed(tmp_path):
    sb = _sb(tmp_path, signed=False)
    assert not cm.inferred_wait(f"completed: {sb.signed_pdf()}", sb)
