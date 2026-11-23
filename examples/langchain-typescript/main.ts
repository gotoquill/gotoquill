/** A LangGraph signing flow with real MCP tools and a private browser handoff. */
import { Annotation, StateGraph, START, END } from '@langchain/langgraph';
import { CLOUD_URL, connectGotoquill, type GotoquillOptions } from 'langchain-gotoquill';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';

type Tools = Awaited<ReturnType<typeof connectGotoquill>>['tools'];
type Result = Record<string, unknown>;

export function connection(mode: string): GotoquillOptions {
  // Switching changes this block. Finish pending work on its originating session.
  if (mode === 'local') return {command: process.env.GOTOQUILL_COMMAND ?? 'gotoquill', args: ['mcp']};
  if (mode !== 'cloud') throw new Error('Choose local or cloud');
  const token = process.env.GOTOQUILL_ACCESS_TOKEN;
  if (!token) throw new Error('Cloud needs an OAuth access token in GOTOQUILL_ACCESS_TOKEN');
  return {url: CLOUD_URL, headers: {Authorization: `Bearer ${token}`}};
}

export function payload(message: any): Result {
  if (message.status === 'error') throw new Error('MCP tool failed');
  const artifacts = Array.isArray(message.artifact) ? message.artifact : [message.artifact];
  for (const artifact of artifacts) {
    if (artifact?.type === 'mcp_structured_content') return artifact.data;
    if (artifact?.structuredContent) return artifact.structuredContent;
  }
  const content = typeof message.content === 'string' ? [{type:'text',text:message.content}] : message.content;
  for (const block of content ?? []) {
    if (block.type === 'text') {
      try { const value = JSON.parse(block.text); if (value && typeof value === 'object' && !Array.isArray(value)) return value; } catch { /* Continue to structured JSON text. */ }
    }
  }
  throw new Error('Expected structured Gotoquill output');
}

async function call(tools: Tools, name: string, args: Result): Promise<Result> {
  const matches = tools.filter(t => t.name === name || t.name === `gotoquill_${name}`);
  if (matches.length !== 1) throw new Error(`Expected one ${name} tool; refresh schemas`);
  return payload(await matches[0].invoke({name:matches[0].name,args,id:'gotoquill-example',type:'tool_call'}));
}

const State = Annotation.Root({request_id:Annotation<string>(),status:Annotation<string>(),result:Annotation<Result>()});
export function signingGraph(tools: Tools, args: Result, presentLink: (url:string) => Promise<void>, pollMs = 5000, maxChecks = 120) {
  return new StateGraph(State)
    .addNode('request', async () => {
      const result = await call(tools, 'request_signature', args);
      if (typeof result.sign_url !== 'string' || typeof result.request_id !== 'string') throw new Error('Missing signing link');
      await presentLink(result.sign_url);
      return {request_id: result.request_id, status:'pending'};
    })
    .addNode('wait', async state => {
      for (let i=0;i<maxChecks;i++) {
        const result = await call(tools, 'get_signature_status', {request_id:state.request_id});
        if (result.status !== 'pending') return {status:String(result.status ?? 'unknown'),result};
        await new Promise(done => setTimeout(done, pollMs));
      }
      return {status:'pending',result:{request_id:state.request_id,status:'pending'}};
    })
    .addEdge(START,'request').addEdge('request','wait').addEdge('wait',END).compile();
}

async function openSigningPage(url: string) {
  // No shell interpolation, logging or telemetry of the bearer-capable link.
  const command = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'rundll32' : 'xdg-open';
  const args = process.platform === 'win32' ? ['url.dll,FileProtocolHandler',url] : [url];
  await new Promise<void>((resolve,reject) => {
    const child = spawn(command,args,{stdio:'ignore'});
    child.on('error',() => reject(new Error('Provide a private signing-link UI callback')));
    child.on('exit',code => code === 0 ? resolve() : reject(new Error('Browser could not open')));
  });
  console.log('Opened the signing page. Review and consent there; waiting for completion.');
}

async function main() {
  const mode = process.argv[2] ?? 'local';
  const request = process.argv.includes('--request');
  const pdfIndex = process.argv.indexOf('--pdf');
  const pdf = pdfIndex >= 0 ? process.argv[pdfIndex + 1] : undefined;
  if (mode === 'cloud' && pdfIndex >= 0) throw new Error('Cloud sample mode cannot accept a local path');
  if (request && mode === 'local' && !pdf) throw new Error('Local request needs --pdf');
  const session = await connectGotoquill(connection(mode));
  try {
    if (!request) { console.log('Connected tools:', session.tools.map(t => t.name).join(', ')); return; }
    const args = mode === 'cloud' ? {sample:'nda',signer_role:'Party A',signer_name:'Dana Cohen'} : {pdf_path:pdf,delivery:'page',open_browser:false,signer_name:'Dana Cohen'};
    const result = await signingGraph(session.tools,args,openSigningPage).invoke({});
    console.log('Request status:',result.status);
    console.log('Return signed_pdf_path or signed_pdf_url through your private application UI.');
  } finally { await session.close(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {console.error('Gotoquill connection or request failed. Check mode, executable, OAuth and tool schemas privately.');process.exitCode=1;});
}
