import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { PDFDocument, StandardFonts, rgb } from "pdf-lib";
import { stampPdf, inspectPdf, sha256 } from "../src/pdf.js";

async function samplePdf(): Promise<Uint8Array> {
  const doc = await PDFDocument.create();
  const page = doc.addPage([612, 792]);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  page.drawText("Test", { x: 72, y: 720, size: 14, font, color: rgb(0, 0, 0) });
  return doc.save();
}

const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+FABJADveWkH6aAAAAAElFTkSuQmCC",
  "base64",
);

describe("pdf", () => {
  it("inspect + stamp", async () => {
    const pdf = await samplePdf();
    const info = await inspectPdf(pdf);
    assert.equal(info.page_count, 1);
    const signed = await stampPdf({
      pdfBytes: pdf,
      placements: [{ kind: "signature", page: 1, x: 72, y: 100, width: 180, height: 50 }],
      signaturePng: TINY_PNG,
      signedAt: new Date(),
      signerName: "Ada",
      requestId: "req_test",
      signer: { typed_name: "Ada" },
      signedByLine: true,
    });
    assert.equal(Buffer.from(signed.subarray(0, 4)).toString(), "%PDF");
    assert.notEqual(sha256(signed), sha256(pdf));
  });
});
