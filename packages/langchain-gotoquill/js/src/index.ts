/** Unpublished helper using the official @langchain/mcp-adapters 2.x API. */
import { MCPAdapter, type OAuthClientProvider, type AuthProvider } from '@langchain/mcp-adapters';

export const CLOUD_URL = 'https://mcp.gotoquill.com/mcp';
export type GotoquillOptions =
  | { command?: string; args?: string[]; url?: never; headers?: never; authProvider?: never }
  | { url: string; headers?: Record<string, string>; authProvider?: OAuthClientProvider | AuthProvider; command?: never; args?: never };

/** Keep this session open while using tools, then close it in finally. */
export async function connectGotoquill(options: GotoquillOptions = {}) {
  if (options.url !== undefined && (options.command !== undefined || options.args !== undefined)) {
    throw new Error('Choose either Local command/args or Cloud URL');
  }
  if (options.url === undefined && (options.headers !== undefined || options.authProvider !== undefined)) {
    throw new Error('Authentication is only valid for Cloud');
  }
  const server = options.url !== undefined
    ? { url: options.url, headers: options.headers, authProvider: options.authProvider }
    : { command: options.command ?? 'gotoquill', args: options.args ?? ['mcp'] };
  const adapter = new MCPAdapter({ servers: { gotoquill: server } });
  try {
    const tools = await adapter.listTools();
    return { tools, close: () => adapter.close() };
  } catch (error) {
    await adapter.close();
    throw error;
  }
}
