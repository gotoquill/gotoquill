import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { PDFDocument, StandardFonts } from "pdf-lib";
import { MemoryRelay, setRelay } from "../src/relay.js";
import { createSealedRequest, applyResponseObj, sealedStatus } from "../src/sealed.js";
import { aad, seal, unseal, b64uDecode } from "../src/crypto.js";
import { createHash, createHmac } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

async function samplePdf(): Promise<Buffer> {
  const doc = await PDFDocument.create();
  const page = doc.addPage([612, 792]);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  page.drawText("Sealed test", { x: 72, y: 700, size: 14, font });
  return Buffer.from(await doc.save());
}

const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9Qz0AEYBxVSF+FABJADveWkH6aAAAAAElFTkSuQmCC",
  "base64",
);

describe("sealed memory relay", () => {
  it("create -> reply -> completed", async () => {
    process.env.GOTOQUILL_DATA_DIR = mkdtempSync(join(tmpdir(), "gq-"));
    const relay = new MemoryRelay();
    setRelay(relay);
    const pdf = await samplePdf();
    const created = await createSealedRequest({
      pdfBytes: pdf,
      documentName: "mem.pdf",
      signerName: "Bob",
      placements: [{ kind: "signature", page: 1, x: 72, y: 100, width: 200, height: 60 }],
      skipPageRasters: true,
      pageBase: "https://example.test/sign",
    });
    assert.equal(created.status, "pending");
    assert.ok(String(created.sign_url).includes("#"));

    const frag = new URLSearchParams(String(created.sign_url).split("#")[1]);
    const q = frag.get("q")!;
    const a = frag.get("a")!;
    const key = b64uDecode(frag.get("k")!);
    const blobs = await relay.fetch(q);
    assert.equal(blobs.length, 1);
    const payload = JSON.parse(unseal(key, blobs[0], aad("request", q)).toString());
    const D = payload.data;

    const sigSha = createHash("sha256").update(TINY_PNG).digest("hex");
    const clientTs = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
    const method = "drawn";
    const msg = ["gotoquill/v1", D.request_id, D.original_sha256, sigSha, method, "", "Bob", clientTs].join("|");
    const proof = createHmac("sha256", Buffer.from(D.key, "hex")).update(msg).digest("hex");
    const resp = {
      type: "gotoquill-response",
      version: 1,
      request_id: D.request_id,
      original_sha256: D.original_sha256,
      client_timestamp: clientTs,
      decision: "sign",
      signature_png: "data:image/png;base64," + TINY_PNG.toString("base64"),
      method,
      typed_name: "",
      signer_name: "Bob",
      consent: true,
      consent_text: D.consent_text,
      proof,
    };
    const reply = seal(key, Buffer.from(JSON.stringify(resp)), aad("reply", a));
    await relay.publish(a, reply, "reply.bin");

    const st = await sealedStatus(String(created.request_id), 2);
    assert.equal(st.status, "completed");
    assert.ok(st.signed_pdf_path || st.signed_pdf_base64);
  });
});
