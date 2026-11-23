"""Create examples/sample_contract.pdf (a one-page agreement with a signature form field)."""
import io
import sys
from pathlib import Path

from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

W, H = 612, 792  # US Letter


def make(path: str | Path, with_field: bool = True) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, H - 90, "Freelance Services Agreement")
    body = ("This agreement is made between Example Client Ltd. and the Contractor named below. "
            "The Contractor will deliver the agreed work by the dates set out in the statement of work. "
            "Payment terms: net 30 days from invoice. Either party may end this agreement with 14 days "
            "written notice. This is a sample document generated for gotoquill tests.")
    c.setFont("Helvetica", 11)
    for i, line in enumerate(simpleSplit(body, "Helvetica", 11, 540 - 72)):
        c.drawString(72, H - 120 - 11 - i * 14, line)
    c.setLineWidth(1)
    c.line(72, H - 640, 300, H - 640)
    c.setFont("Helvetica", 9)
    c.drawString(72, H - 655, "Contractor signature")
    c.line(340, H - 640, 540, H - 640)
    c.drawString(340, H - 655, "Date")
    if with_field:
        c.acroForm.textfield(name="ContractorSignature", x=72, y=H - 638, width=228, height=58,
                             borderWidth=0, fillColor=None, borderColor=None, value="")
    c.showPage()
    c.save()
    data = buf.getvalue()
    Path(path).write_bytes(data)
    return data


if __name__ == "__main__":
    make(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("sample_contract.pdf"))
