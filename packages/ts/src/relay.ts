/** Ciphertext mailbox clients: ntfy, gotoquill Worker, and in-memory (tests). */
import { envBool, envGet } from "./env.js";
import { SignError } from "./errors.js";

export const DEFAULT_RELAY_URL = "https://ntfy.sh";
export const DEFAULT_PAGE_URL = "https://example.github.io/gotoquill/";
export const GOTOQUILL_MAX_PAYLOAD_BYTES = 1 * 1024 * 1024;
export const NTFY_MAX_PAYLOAD_BYTES = 15 * 1024 * 1024;

export const MISSING_GOTOQUILL_RELAY =
  "GOTOQUILL_RELAY_URL is required for the gotoquill relay " +
  "(cloud mode / GOTOQUILL_RELAY_TYPE=gotoquill). " +
  "There is no shared public relay. deploy your own on your Cloudflare account.";

export class RelayError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RelayError";
  }
}

export interface Relay {
  base_url: string;
  kind: string;
  publish(topic: string, data: Uint8Array, filename?: string): Promise<Record<string, unknown>>;
  fetch(topic: string): Promise<Uint8Array[]>;
  exists?(topic: string): Promise<boolean>;
}

export function cloudMode(): boolean {
  return envBool("CLOUD", false);
}

export function relayType(baseUrl?: string | null): "ntfy" | "gotoquill" {
  let t = (envGet("RELAY_TYPE") || "").trim().toLowerCase();
  if (t === "agentsign" || t === "agent-sign") t = "gotoquill";
  if (t === "ntfy" || t === "gotoquill") return t;
  if (baseUrl == null && cloudMode()) return "gotoquill";
  const url = (baseUrl || envGet("RELAY") || envGet("RELAY_URL") || DEFAULT_RELAY_URL).replace(/\/$/, "");
  try {
    const u = new URL(url);
    const host = (u.hostname || "").toLowerCase();
    const path = (u.pathname || "").toLowerCase();
    if (
      host.includes("gotoquill-relay") ||
      host.includes("agent-sign-relay") ||
      host.includes("gotoquill-cloud") ||
      path.includes("/v1")
    ) {
      return "gotoquill";
    }
  } catch {
    /* ignore */
  }
  return "ntfy";
}

export function relayUrl(): string {
  const explicit = (envGet("RELAY") || envGet("RELAY_URL") || "").trim();
  if (explicit) return explicit.replace(/\/$/, "");
  if (relayType() === "gotoquill") throw new RelayError(MISSING_GOTOQUILL_RELAY);
  return DEFAULT_RELAY_URL;
}

export function pageUrl(): string {
  const u = (envGet("PAGE_BASE") || envGet("PAGE_URL") || DEFAULT_PAGE_URL).trim();
  return u.endsWith("/") ? u : u + "/";
}

export class GotoquillRelay implements Relay {
  kind = "gotoquill";
  base_url: string;
  constructor(base?: string) {
    this.base_url = (base || relayUrl()).replace(/\/$/, "");
  }
  private box(topic: string) {
    return `${this.base_url}/v1/box/${topic}`;
  }
  async publish(topic: string, data: Uint8Array, _filename = "payload.bin") {
    if (data.byteLength > GOTOQUILL_MAX_PAYLOAD_BYTES) {
      throw new RelayError("encrypted payload is larger than 1 MiB; use a smaller PDF");
    }
    const res = await fetch(this.box(topic), {
      method: "PUT",
      headers: { "Content-Type": "application/octet-stream", "X-TTL-Seconds": "3600", "User-Agent": "gotoquill" },
      body: Buffer.from(data),
    });
    if (!res.ok) throw new RelayError(`relay publish failed: HTTP ${res.status}`);
    try {
      return (await res.json()) as Record<string, unknown>;
    } catch {
      return { ok: true };
    }
  }
  async exists(topic: string): Promise<boolean> {
    const res = await fetch(this.box(topic), { method: "HEAD", headers: { "User-Agent": "gotoquill" } });
    if (res.status === 404) return false;
    return res.ok;
  }
  async fetch(topic: string): Promise<Uint8Array[]> {
    if (!(await this.exists(topic))) return [];
    const res = await fetch(this.box(topic), { method: "GET", headers: { "User-Agent": "gotoquill" } });
    if (res.status === 404) return [];
    if (!res.ok) throw new RelayError(`relay fetch failed: HTTP ${res.status}`);
    const buf = new Uint8Array(await res.arrayBuffer());
    if (buf.byteLength > GOTOQUILL_MAX_PAYLOAD_BYTES) return [];
    return [buf];
  }
}

export class NtfyRelay implements Relay {
  kind = "ntfy";
  base_url: string;
  constructor(base?: string) {
    this.base_url = (base || relayUrl()).replace(/\/$/, "");
  }
  async publish(topic: string, data: Uint8Array, filename = "payload.bin") {
    if (data.byteLength > NTFY_MAX_PAYLOAD_BYTES) {
      throw new RelayError("encrypted payload is larger than 15 MB");
    }
    const res = await fetch(`${this.base_url}/${topic}`, {
      method: "PUT",
      headers: {
        Filename: filename,
        "Content-Type": "application/octet-stream",
        "User-Agent": "gotoquill",
      },
      body: Buffer.from(data),
    });
    if (!res.ok) throw new RelayError(`ntfy publish failed: HTTP ${res.status}`);
    try {
      return (await res.json()) as Record<string, unknown>;
    } catch {
      return {};
    }
  }
  async fetch(topic: string): Promise<Uint8Array[]> {
    const res = await fetch(`${this.base_url}/${topic}/json?poll=1&since=all`, {
      headers: { "User-Agent": "gotoquill" },
    });
    if (!res.ok) throw new RelayError(`ntfy fetch failed: HTTP ${res.status}`);
    const text = await res.text();
    const out: Uint8Array[] = [];
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const m = JSON.parse(line);
        if (m.event !== "message") continue;
        const att = m.attachment || {};
        if (att.url) {
          const a = await fetch(att.url, { headers: { "User-Agent": "gotoquill" } });
          if (a.ok) out.push(new Uint8Array(await a.arrayBuffer()));
        } else if (m.message) {
          out.push(Buffer.from(m.message + "=".repeat((4 - (m.message.length % 4)) % 4), "base64url"));
        }
      } catch {
        continue;
      }
    }
    return out;
  }
}

export class MemoryRelay implements Relay {
  kind = "memory";
  base_url: string;
  topics = new Map<string, Uint8Array[]>();
  constructor(base = "https://relay.test") {
    this.base_url = base;
  }
  async publish(topic: string, data: Uint8Array) {
    const list = this.topics.get(topic) || [];
    list.push(Uint8Array.from(data));
    this.topics.set(topic, list);
    return { topic };
  }
  async fetch(topic: string) {
    return [...(this.topics.get(topic) || [])];
  }
  async exists(topic: string) {
    return (this.topics.get(topic) || []).length > 0;
  }
}

let _relay: Relay | null = null;

export function makeRelay(base?: string): Relay {
  const url = (base || relayUrl()).replace(/\/$/, "");
  if (relayType(url) === "gotoquill") return new GotoquillRelay(url);
  return new NtfyRelay(url);
}

export function getRelay(): Relay {
  return _relay || makeRelay();
}

export function setRelay(r: Relay | null) {
  _relay = r;
}

export function asSignError(e: unknown): SignError {
  if (e instanceof SignError) return e;
  if (e instanceof RelayError) return new SignError(String(e.message), 502);
  return new SignError(String((e as Error)?.message || e));
}
