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

import UPNGModule from "@pdf-lib/upng";
const UPNG = (UPNGModule as unknown as { default: typeof UPNGModule }).default || UPNGModule;
import { signingDate, trimSignature } from '../src/pdf.js';
import { PDFRawStream, decodePDFRawStream } from 'pdf-lib';

it('uses numeric dates in the signer zone independently of the server zone', () => {
  const when=new Date('2026-11-26T22:30:00Z');
  const old=process.env.TZ;
  try {
    process.env.TZ='America/Los_Angeles';
    assert.equal(signingDate(when,{timezone:'Asia/Jerusalem',locale:'he-IL'}),'27/11/2026');
    assert.equal(signingDate(when,{timezone:'Asia/Jerusalem',utc_offset_minutes:-300,locale:'en-US'}),'11/27/2026');
    assert.equal(signingDate(when,{utc_offset_minutes:120},'YYYY-MM-DD'),'2026-11-27');
    assert.equal(signingDate(when,{utc_offset_minutes:120},'%m/%d/%Y'),'11/27/2026');
    assert.equal(signingDate(when,{date_format:'MM/DD/YYYY',date_text:'11/27/2026'},'YYYY-MM-DD'),'11/27/2026');
    for(const text of ['Nov 27, 2026','31/02/2026','01/01/1800','27-11-2026']) {
      assert.throws(()=>signingDate(when,{date_format:'DD/MM/YYYY',date_text:text}));
    }
  } finally { if(old===undefined) delete process.env.TZ; else process.env.TZ=old; }
});

it('trims transparent margins and centers aspect-preserving ink inside padding', async () => {
  const rgba=new Uint8Array(400*160*4);
  for(let y=100;y<120;y++)for(let x=15;x<115;x++)rgba.set([11,26,74,255],(y*400+x)*4);
  const png=new Uint8Array(UPNG.encode([rgba.buffer],400,160,0));
  const trimmed=UPNG.decode(trimSignature(png).buffer as ArrayBuffer);
  assert.equal(trimmed.width,100);assert.equal(trimmed.height,20);
  const output=await stampPdf({pdfBytes:await samplePdf(),placements:[{x:100,y:100,width:200,height:60}],signaturePng:png,signedAt:new Date(),requestId:'synthetic'});
  const doc=await PDFDocument.load(output);
  const content=doc.context.enumerateIndirectObjects().filter(([,o])=>o instanceof PDFRawStream)
    .map(([,o])=>{try{return Buffer.from(decodePDFRawStream(o as PDFRawStream).decode()).toString();}catch{return '';}}).join('\n');
  assert.match(content,/1 0 0 1 102 642\.4 cm/);
  assert.match(content,/196 0 0 39\.2 0 0 cm/);
});
