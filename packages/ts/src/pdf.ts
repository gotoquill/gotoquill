import { textBounds } from './text-layout.js';
/**
 * PDF inspect + stamp via pdf-lib.
 * Coordinates: PDF points, origin top-left (same as Python gotoquill.pdf).
 * pdf-lib uses bottom-left origin, so we convert when drawing.
 */
import { PDFDocument, PDFPage, rgb, StandardFonts } from "pdf-lib";
import UPNGModule from "@pdf-lib/upng";
import { createHash } from "node:crypto";
import { SignError } from "./errors.js";

// Handle the dependency's CommonJS default export in Node ESM and bundlers.
const UPNG = (UPNGModule as unknown as { default: typeof UPNGModule }).default || UPNGModule;

export function sha256(data: Uint8Array | Buffer): string {
  return createHash("sha256").update(data).digest("hex");
}

export type Placement = {
  kind?: "signature" | "initials" | "date";
  page?: number;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  field_name?: string;
  add_date?: boolean;
  proof_line?: boolean;
  date_format?: string;
  fill_document_date?: boolean;
};

export type SignerCtx = {
  date_format?: string | null;
  date_text?: string | null;
  timezone?: string | null;
  utc_offset_minutes?: number | null;
  locale?: string | null;
};

export async function inspectPdf(data: Uint8Array, maxPages = 60): Promise<{
  page_count: number;
  page_sizes: number[][];
}> {
  if (data.length < 5 || String.fromCharCode(...data.slice(0, 4)) !== "%PDF") {
    throw new SignError("document is not a PDF");
  }
  let doc: PDFDocument;
  try {
    doc = await PDFDocument.load(data, { ignoreEncryption: false });
  } catch (e) {
    throw new SignError(`cannot open PDF: ${(e as Error).message}`);
  }
  if (doc.isEncrypted) throw new SignError("encrypted PDFs are not supported");
  const n = doc.getPageCount();
  if (n > maxPages) throw new SignError(`PDF has ${n} pages; limit is ${maxPages}`);
  const sizes: number[][] = [];
  for (let i = 0; i < n; i++) {
    const p = doc.getPage(i);
    const { width, height } = p.getSize();
    sizes.push([Math.round(width * 100) / 100, Math.round(height * 100) / 100]);
  }
  return { page_count: n, page_sizes: sizes };
}

export const DATE_FORMATS = ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] as const;
export type DateFormat = typeof DATE_FORMATS[number];

export function signingDate(utc: Date, signer?: SignerCtx | null, requested?: string): string {
  const fmt = signer?.date_format;
  const text = signer?.date_text;
  if (fmt != null || text != null) {
    if (!DATE_FORMATS.includes(fmt as DateFormat) || typeof text !== "string" ||
        !/^(?:[0-9]{2}\/[0-9]{2}\/[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})$/.test(text)) throw new SignError("invalid numeric signing date");
    const parts = text.split(/[-/]/).map(Number);
    const [year, month, day] = fmt === "YYYY-MM-DD" ? parts : [parts[2], parts[fmt === "MM/DD/YYYY" ? 0 : 1], parts[fmt === "MM/DD/YYYY" ? 1 : 0]];
    const check = new Date(Date.UTC(year, month - 1, day));
    if (year < 2000 || year > 2100 || check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day ||
        (fmt === "YYYY-MM-DD" ? !text.includes("-") : !text.includes("/"))) throw new SignError("invalid numeric signing date");
    return text;
  }
  const { local } = applySignerOffset(utc, signer);
  const pad = (n: number) => String(n).padStart(2, "0");
  const y = local.getUTCFullYear(), m = pad(local.getUTCMonth() + 1), d = pad(local.getUTCDate());
  const locale = (signer?.locale || "").toLowerCase().replace(/_/g, "-");
  requested = ({"%d/%m/%Y":"DD/MM/YYYY", "%m/%d/%Y":"MM/DD/YYYY", "%Y-%m-%d":"YYYY-MM-DD"} as Record<string,string>)[requested || ""] || requested;
  const f = DATE_FORMATS.includes(requested as DateFormat) ? requested : /^en-us(?:-|$)/.test(locale) ? "MM/DD/YYYY" : "DD/MM/YYYY";
  return f === "YYYY-MM-DD" ? `${y}-${m}-${d}` : f === "MM/DD/YYYY" ? `${m}/${d}/${y}` : `${d}/${m}/${y}`;
}

function applySignerOffset(utc: Date, signer?: SignerCtx | null): { local: Date; label: string } {
  if (signer?.timezone) {
    try {
      const parts = new Intl.DateTimeFormat("en-GB", {timeZone: signer.timezone, year:"numeric", month:"2-digit", day:"2-digit",
        hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23"}).formatToParts(utc);
      const n = (key: string) => Number(parts.find(p => p.type === key)!.value);
      return {local: new Date(Date.UTC(n("year"), n("month")-1, n("day"), n("hour"), n("minute"), n("second"))), label: signer.timezone};
    } catch { /* use the browser offset if its zone is unavailable */ }
  }
  const off = signer?.utc_offset_minutes;
  if (typeof off === "number" && Number.isInteger(off) && Math.abs(off) <= 840) {
    const a = Math.abs(off);
    return {local: new Date(utc.getTime()+off*60000), label:`UTC${off>=0?"+":"-"}${String(Math.floor(a/60)).padStart(2,"0")}:${String(a%60).padStart(2,"0")}`};
  }
  return {local: utc, label:"UTC"};
}

export function trimSignature(bytes: Uint8Array): Uint8Array {
  const decoded = UPNG.decode(Uint8Array.from(bytes).buffer);
  const rgba = new Uint8Array(UPNG.toRGBA8(decoded)[0]), w = decoded.width, h = decoded.height;
  let left=w, top=h, right=-1, bottom=-1;
  for(let y=0;y<h;y++) for(let x=0;x<w;x++) if(rgba[(y*w+x)*4+3]) {
    left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);
  }
  if(right<left) throw new SignError("signature has no visible ink");
  const width=right-left+1,height=bottom-top+1,out=new Uint8Array(width*height*4);
  for(let y=0;y<height;y++) out.set(rgba.subarray(((top+y)*w+left)*4,((top+y)*w+left+width)*4),y*width*4);
  return new Uint8Array(UPNG.encode([out.buffer],width,height,0));
}

function topLeftToPdfLib(
  page: PDFPage,
  x: number,
  yTop: number,
  w: number,
  h: number,
): { x: number; y: number; width: number; height: number } {
  const { height: pageH } = page.getSize();
  // yTop is distance from top; pdf-lib y is bottom of rect from bottom.
  return { x, y: pageH - yTop - h, width: w, height: h };
}

export async function stampPdf(opts: {
  pdfBytes: Uint8Array;
  placements: Placement[];
  signaturePng: Uint8Array;
  signedAt: Date;
  signerName?: string | null;
  requestId: string;
  signer?: SignerCtx | null;
  signedByLine?: boolean;
}): Promise<Uint8Array> {
  const doc = await PDFDocument.load(opts.pdfBytes);
  const sigImage = await doc.embedPng(trimSignature(opts.signaturePng));
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const { local, label } = applySignerOffset(opts.signedAt, opts.signer);
  for (const pl of opts.placements) {
    const kind = pl.kind || "signature";
    const dateText = signingDate(opts.signedAt, opts.signer, pl.date_format);
    const pageIndex = Math.max(0, (pl.page || 1) - 1);
    if (pageIndex >= doc.getPageCount()) throw new SignError(`page ${pl.page} out of range`);
    const page = doc.getPage(pageIndex);
    const width = pl.width ?? 180;
    const height = pl.height ?? width / 3;
    const x = pl.x ?? 72;
    const yTop = pl.y ?? 72;
    const box = topLeftToPdfLib(page, x, yTop, width, height);

    if (kind === "date") {
      const text = dateText;
      const pad = Math.min(2, box.width / 8, box.height / 8);
      const [left, bottom, right, top] = textBounds(text, font);
      const fs = Math.min(11, (box.width - 2 * pad) / Math.max(right - left, 0.001),
        (box.height - 2 * pad) / Math.max(top - bottom, 0.001));
      page.drawText(text, {
        x: box.x + box.width / 2 - (left + right) * fs / 2,
        y: box.y + box.height / 2 - (top + bottom) * fs / 2,
        size: fs, font, color: rgb(0, 0, 0),
      });
      continue;
    }

    const pad=Math.min(2,box.width/8,box.height/8);
    const scale=Math.min((box.width-2*pad)/sigImage.width,(box.height-2*pad)/sigImage.height);
    const iw=sigImage.width*scale,ih=sigImage.height*scale;
    page.drawImage(sigImage, {x:box.x+(box.width-iw)/2,y:box.y+(box.height-ih)/2,width:iw,height:ih});

    if (opts.signedByLine) {
      const name = (opts.signerName || "").replace(/\s+/g, " ").slice(0, 80);
      const line = name ? `Signed by ${name} · ${dateText}` : `Signed · ${dateText}`;
      page.drawText(line, {
        x: box.x,
        y: Math.max(4, box.y - 10),
        size: 7,
        font,
        color: rgb(0.45, 0.45, 0.47),
      });
    }

    if (pl.add_date && pl.proof_line !== false) {
      const proof = `Signed ${dateText}, ${String(local.getUTCHours()).padStart(2, "0")}:${String(local.getUTCMinutes()).padStart(2, "0")} (${label})`;
      // Prefer a simple line under the signature box.
      page.drawText(proof, {
        x: box.x,
        y: Math.max(4, box.y - 12),
        size: 8,
        font,
        color: rgb(0.25, 0.25, 0.25),
      });
    }
  }

  doc.setProducer("gotoquill");
  doc.setKeywords([`gotoquill request ${opts.requestId}`]);
  return doc.save();
}

/** Default placement: bottom-right of last page (guess). */
export function defaultPlacements(pageCount: number, pageSizes: number[][]): Placement[] {
  const last = Math.max(1, pageCount);
  const size = pageSizes[last - 1] || [612, 792];
  const w = 180;
  const h = 60;
  const x = Math.max(36, size[0] - w - 36);
  const y = Math.max(36, size[1] - h - 72); // from top
  return [{ kind: "signature", page: last, x, y, width: w, height: h }];
}

/** Tiny 1x1 white PNG as placeholder when page rasterization is unavailable (Workers). */
export function placeholderPngBase64(): string {
  // 1x1 white PNG
  const b = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  return b.toString("base64");
}
