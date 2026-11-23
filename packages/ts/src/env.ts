/** GOTOQUILL_* with deprecated AGENT_SIGN_* fallbacks. */

export function envGet(suffix: string, fallback?: string): string | undefined {
  let s = suffix;
  if (s.startsWith("GOTOQUILL_")) s = s.slice("GOTOQUILL_".length);
  else if (s.startsWith("AGENT_SIGN_")) s = s.slice("AGENT_SIGN_".length);
  for (const prefix of ["GOTOQUILL_", "AGENT_SIGN_"]) {
    const v = process.env[prefix + s];
    if (v !== undefined) return v;
  }
  return fallback;
}

export function envBool(suffix: string, fallback = false): boolean {
  const v = envGet(suffix);
  if (v === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(v.trim().toLowerCase());
}

export function envInt(suffix: string, fallback: number): number {
  const v = envGet(suffix);
  if (v === undefined || v.trim() === "") return fallback;
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : fallback;
}
