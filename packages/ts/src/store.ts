/**
 * Local pending-request store (filesystem). Cloud Worker uses KV separately.
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync, chmodSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { envGet } from "./env.js";
import { SignError } from "./errors.js";

export type RequestState = {
  request_id: string;
  status: string;
  delivery: string;
  created_at: string;
  expires_at: string;
  document_name: string;
  friendly_name?: string;
  signer_name?: string | null;
  message?: string | null;
  placements: import("./pdf.js").Placement[];
  page_count: number;
  original_sha256: string;
  consent_text: string;
  /** Per-request HMAC key (hex). */
  key: string;
  pdf_path?: string;
  output_path?: string;
  audit_path?: string;
  return_to?: string | null;
  sealed?: {
    relay: string;
    relay_type: string;
    request_topic: string;
    reply_topic: string;
    key: string | null;
    payload_bytes?: number;
    abandoned?: boolean;
  };
  sign_url?: string | null;
  html_path?: string;
  decline_reason?: string | null;
  applied_at?: string;
  used_proof?: string;
  signed_pdf_base64?: string;
  placement_info?: Record<string, unknown>;
  /** Cloud: original PDF kept in memory/KV, not filesystem. */
  pdf_base64?: string;
};

function dataRoot(): string {
  const explicit = envGet("DATA_DIR");
  if (explicit) return explicit;
  const neu = join(homedir(), ".gotoquill");
  const old = join(homedir(), ".agent-sign");
  if (existsSync(neu) || !existsSync(old)) return neu;
  return old;
}

export function stateRoot(): string {
  const p = join(dataRoot(), "file-requests");
  mkdirSync(p, { recursive: true, mode: 0o700 });
  return p;
}

function dir(rid: string): string {
  if (!/^req_[0-9a-f]{16}$/.test(rid || "")) throw new SignError("unknown request_id", 404);
  return join(stateRoot(), rid);
}

export function exists(rid: string): boolean {
  try {
    return existsSync(join(dir(rid), "state.json"));
  } catch {
    return false;
  }
}

export function load(rid: string): RequestState {
  const f = join(dir(rid), "state.json");
  if (!existsSync(f)) throw new SignError("unknown request_id (no request with this id on this computer)", 404);
  return JSON.parse(readFileSync(f, "utf8")) as RequestState;
}

export function store(d: RequestState): void {
  const dpath = dir(d.request_id);
  mkdirSync(dpath, { recursive: true, mode: 0o700 });
  const f = join(dpath, "state.json");
  const tmp = f + ".tmp";
  writeFileSync(tmp, JSON.stringify(d, null, 2), { mode: 0o600 });
  try {
    chmodSync(tmp, 0o600);
  } catch {
    /* ignore */
  }
  writeFileSync(f, readFileSync(tmp));
}

export function writeOriginal(rid: string, pdf: Buffer): void {
  writeFileSync(join(dir(rid), "original.pdf"), pdf);
}

export function readOriginal(rid: string): Buffer {
  return readFileSync(join(dir(rid), "original.pdf"));
}

export function friendlyName(documentName: string): string {
  let stem = documentName.replace(/\.pdf$/i, "");
  stem = stem.replace(/[_\s]+/g, " ").replace(/^[.\s-]+|[.\s-]+$/g, "") || "Document";
  stem = stem.replace(/[\\/:*?"<>|]+/g, " ");
  return (stem[0].toUpperCase() + stem.slice(1)).slice(0, 80);
}

export const DEFAULT_CONSENT =
  "I have reviewed this document and agree to sign it electronically. This is my signature.";
