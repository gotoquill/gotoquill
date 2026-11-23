export class SignError extends Error {
  code: number;
  constructor(message: string, code = 400) {
    super(message);
    this.name = "SignError";
    this.code = code;
  }
}

export function errResult(message: string, code = 400, next?: string): Record<string, unknown> {
  const low = message.toLowerCase();
  let n = next;
  if (n === undefined) {
    if (code === 404 || low.includes("not found") || low.includes("does not exist")) {
      n =
        "Check the value and call again with an absolute path to an existing PDF, or the request_id that request_signature returned (req_ + 16 hex chars).";
    } else {
      n = "Fix the argument named in the error and call the same tool again.";
    }
  }
  return { error: message, code, next: n };
}
