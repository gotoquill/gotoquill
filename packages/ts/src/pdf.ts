/**
 * PDF inspect + stamp via pdf-lib.
 * Coordinates: PDF points, origin top-left (same as Python gotoquill.pdf).
 * pdf-lib uses bottom-left origin, so we convert when drawing.
 */
import { PDFDocument, PDFPage, rgb, StandardFonts, degrees } from "pdf-lib";
import { createHash } from "node:crypto";
import { SignError } from "./errors.js";

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

function defaultDateFormat(locale?: string | null): string {
  const loc = (locale || "").toLowerCase().replace("_", "-");
  if (!loc) return "dd MMM yyyy";
  if (loc === "en-us" || loc === "en" || loc.startsWith("en-us")) return "MM/dd/yyyy";
  return "dd/MM/yyyy";
}

function formatLocal(d: Date, fmt: string, locale?: string | null): string {
  // Minimal token formatter (not full strftime).
  const f = !fmt || fmt === "auto" || fmt === "locale" ? defaultDateFormat(locale) : fmt;
  const pad = (n: number) => String(n).padStart(2, "0");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const map: Record<string, string> = {
    YYYY: String(d.getFullYear()),
    yyyy: String(d.getFullYear()),
    "%Y": String(d.getFullYear()),
    YY: String(d.getFullYear()).slice(-2),
    MM: pad(d.getMonth() + 1),
    "%m": pad(d.getMonth() + 1),
    DD: pad(d.getDate()),
    dd: pad(d.getDate()),
    "%d": pad(d.getDate()),
    MMM: months[d.getMonth()],
    "%b": months[d.getMonth()],
    HH: pad(d.getHours()),
    "%H": pad(d.getHours()),
    mm: pad(d.getMinutes()),
    "%M": pad(d.getMinutes()),
  };
  // Prefer longer tokens first
  let out = f;
  for (const tok of ["YYYY", "yyyy", "%Y", "MMM", "%b", "MM", "%m", "DD", "dd", "%d", "YY", "HH", "%H", "mm", "%M"]) {
    out = out.split(tok).join(map[tok]);
  }
  // Handle "%d %b %Y" style leftovers
  return out;
}

function applySignerOffset(utc: Date, signer?: SignerCtx | null): { local: Date; label: string } {
  const off = signer?.utc_offset_minutes;
  if (typeof off === "number" && off >= -14 * 60 && off <= 14 * 60) {
    const local = new Date(utc.getTime() + off * 60_000);
    const sign = off >= 0 ? "+" : "-";
    const a = Math.abs(off);
    const label = `UTC${sign}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
    return { local, label };
  }
  if (signer?.timezone) {
    try {
      // Use Intl for wall-clock in zone; for stamp text only.
      const fmt = new Intl.DateTimeFormat("en-GB", {
        timeZone: signer.timezone,
        year: "numeric",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      // Still return a Date shifted approximately via offset parts
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: signer.timezone,
        timeZoneName: "shortOffset",
      }).formatToParts(utc);
      const tzName = parts.find((p) => p.type === "timeZoneName")?.value || signer.timezone;
      return { local: utc, label: String(tzName) };
    } catch {
      /* fall through */
    }
  }
  return { local: utc, label: "UTC" };
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
  const sigImage = await doc.embedPng(opts.signaturePng);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const { local, label } = applySignerOffset(opts.signedAt, opts.signer);
  // When timezone label path used Intl without shifting Date, format via locale offset path:
  const locale = opts.signer?.locale;
  const dateText = formatLocal(
    typeof opts.signer?.utc_offset_minutes === "number"
      ? new Date(opts.signedAt.getTime() + opts.signer.utc_offset_minutes * 60_000)
      : opts.signedAt,
    "dd MMM yyyy",
    locale,
  );

  for (const pl of opts.placements) {
    const kind = pl.kind || "signature";
    const pageIndex = Math.max(0, (pl.page || 1) - 1);
    if (pageIndex >= doc.getPageCount()) throw new SignError(`page ${pl.page} out of range`);
    const page = doc.getPage(pageIndex);
    const width = pl.width ?? 180;
    const height = pl.height ?? width / 3;
    const x = pl.x ?? 72;
    const yTop = pl.y ?? 72;
    const box = topLeftToPdfLib(page, x, yTop, width, height);

    if (kind === "date") {
      const text = formatLocal(
        typeof opts.signer?.utc_offset_minutes === "number"
          ? new Date(opts.signedAt.getTime() + opts.signer.utc_offset_minutes * 60_000)
          : opts.signedAt,
        pl.date_format || "auto",
        locale,
      );
      const fs = Math.max(6, Math.min(12, box.height * 0.75));
      page.drawText(text, { x: box.x + 1, y: box.y + 2, size: fs, font, color: rgb(0, 0, 0) });
      continue;
    }

    page.drawImage(sigImage, { x: box.x, y: box.y, width: box.width, height: box.height });

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
