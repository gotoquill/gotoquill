/** MCP tool annotations for the Local TypeScript package. */

export type ToolAnn = {
  title?: string;
  readOnlyHint: boolean;
  destructiveHint: boolean;
  openWorldHint: boolean;
  idempotentHint: boolean;
};

function ann(opts: {
  title?: string;
  readOnly?: boolean;
  destructive?: boolean;
  openWorld?: boolean;
  idempotent?: boolean;
}): ToolAnn {
  const readOnly = !!opts.readOnly;
  return {
    title: opts.title,
    readOnlyHint: readOnly,
    destructiveHint: !!opts.destructive,
    openWorldHint: !!opts.openWorld,
    idempotentHint: opts.idempotent === undefined ? readOnly : !!opts.idempotent,
  };
}

export const TOOL_ANNOTATIONS: Record<string, ToolAnn> = {
  request_signature: ann({ title: "Request a human signature", openWorld: true }),
  sign_pdf: ann({ title: "Sign a PDF (request + wait)", openWorld: true }),
  get_signature_status: ann({ title: "Get signature request status", readOnly: true }),
  wait_for_signature: ann({ title: "Wait for human to sign" }),
  connect_notifications: ann({ title: "Connect completion notifications", openWorld: true }),
  cancel_request: ann({ title: "Cancel a signature request", destructive: true }),
  apply_signature_response: ann({ title: "Apply offline signature response" }),
  ui_load_document: ann({ title: "Load document for in-chat signing UI", readOnly: true }),
  ui_submit_signature: ann({ title: "Submit human signature or decline", destructive: true }),
  ui_delete_saved_signature: ann({ title: "Delete a saved signature", destructive: true }),
};
