"""gotoquill: let any AI agent get a human signature on a local PDF."""
__version__ = "0.2.0"


def sign_pdf(pdf_path: str, timeout: float | None = None, **kw):
    """Open a local signing page for pdf_path and wait for the human. See gotoquill.tools."""
    from .tools import sign_pdf as _s
    return _s(pdf_path, timeout, **kw)
